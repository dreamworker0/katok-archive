# -*- coding: utf-8 -*-
"""보고서 인용이 **실제 발언인지** 검사한다.

이 아카이브는 원문을 발행하지 않는다. 그래서 보고서가 유일한 기록이고, 인용은
'이 사람이 이렇게 말했다'는 가장 강한 주장이다. 그것이 지어낸 것이면 아카이브가
사람의 말을 왜곡해 남긴다 — 되돌리기 가장 어려운 종류의 사고다.

LLM 이 보고서를 쓰므로 프롬프트로 부탁하는 것만으로는 부족하다. 여기서 원문과
대조한다. 검사하는 것 세 가지:

  1. 인용(`>`)이 그 주제의 메시지 안에 실제로 있는가 (표기 차이는 무시)
  2. 인용이 {MAX} 자를 넘지 않는가 (넘으면 요약이 아니라 원문 발행이다)
  3. 보고서가 이름을 든 사람이 그 주제의 참여자인가

**원문은 출력하지 않는다.** 어긋난 인용은 앞 12자만 보여 준다 — 운영 로그에 대화
내용이 새면 원문을 발행하지 않기로 한 뜻이 무너진다.

    python -m scripts.audit_quotes            # 전체
    python -m scripts.audit_quotes --ids t-286,t-330
"""
from __future__ import annotations

import argparse
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

from scripts import build_site, topic_reports
from scripts.topic_reports import MAX_VERBATIM_CHARS

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"

# 이만큼 닮으면 같은 말로 본다. 말줄임·오타 교정·이모티콘 차이를 허용하되,
# 다른 말을 같다고 보지 않을 만큼은 높게 둔다.
MATCH = 0.82

_STRIP = re.compile(r"[^0-9A-Za-z가-힣]+")


def norm(s: str) -> str:
    return _STRIP.sub("", s or "").lower()


def quotes_of(body: str) -> list[str]:
    """인용 줄. 여러 줄로 이어진 인용은 한 덩어리로 본다."""
    out, buf = [], []
    for line in (body or "").splitlines():
        if line.lstrip().startswith(">"):
            buf.append(line.lstrip()[1:].strip())
        elif buf:
            out.append(" ".join(buf).strip())
            buf = []
    if buf:
        out.append(" ".join(buf).strip())
    return [q for q in out if q]


def best_match(quote: str, texts: list[str]) -> float:
    """인용이 원문에 얼마나 닮았나. 원문 안에 들어 있으면 1.0.

    메시지 **전체**와 비교하면 안 된다. 카톡 메시지에는 링크와 여러 줄이 섞여 있어,
    인용한 대목이 그대로 들어 있어도 나머지 때문에 점수가 뚝 떨어진다(실측: 원문에
    그대로 있는 인용이 0.52로 나왔다). 그래서 인용 길이만큼의 **창을 밀며** 가장
    닮은 자리를 찾는다.
    """
    q = norm(quote)
    if not q:
        return 1.0
    best = 0.0
    for t in texts:
        n = norm(t)
        if not n:
            continue
        if q in n:
            return 1.0
        if len(n) <= len(q):
            best = max(best, SequenceMatcher(None, q, n, autojunk=False).ratio())
            continue
        step = max(1, len(q) // 8)
        for start in range(0, len(n) - len(q) + 1, step):
            window = n[start:start + len(q)]
            best = max(best, SequenceMatcher(None, q, window, autojunk=False).ratio())
            if best >= 0.99:
                return best
    return best


def audit(ids: set[str] | None = None) -> dict:
    messages = build_site._read_jsonl(OUTPUT / "messages.jsonl")
    topics = build_site._read_json(OUTPUT / "topics.json")
    reports = topic_reports.load_reports()
    by_id = {m["id"]: m for m in messages}

    result = {"reports": 0, "quotes": 0, "unmatched": [], "too_long": [],
              "stranger_names": []}

    # 이름이 참여자인지 보려면 방 전체 명단이 필요하다(다른 방 사람 이름은 나올 수 있다)
    all_nicks = {m["nickname"] for m in messages}

    for t in topics["threads"]:
        tid = t["id"]
        if ids and tid not in ids:
            continue
        r = reports.get(tid)
        if not r:
            continue
        result["reports"] += 1
        msgs = [by_id[i] for i in t["message_ids"] if i in by_id]
        texts = [m.get("text") or "" for m in msgs]
        here = {m["nickname"] for m in msgs}

        for q in quotes_of(r["report"]):
            result["quotes"] += 1
            if len(q) > MAX_VERBATIM_CHARS:
                result["too_long"].append((tid, len(q), q[:12]))
            score = best_match(q, texts)
            if score < MATCH:
                result["unmatched"].append((tid, round(score, 2), q[:12]))

        # 보고서가 든 이름 중 이 주제에 없는 사람
        body = r["report"]
        for nick in all_nicks:
            base = re.sub(r"\s*[(（].*?[)）]\s*$", "", nick).strip()
            if len(base) < 2 or base in here or nick in here:
                continue
            if re.search(r"(?<![0-9A-Za-z가-힣])%s(?![0-9A-Za-z가-힣])"
                         % re.escape(base), body):
                result["stranger_names"].append((tid, base))
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default="", help="특정 주제만 (t-286,t-330)")
    args = ap.parse_args()
    ids = {s.strip() for s in args.ids.split(",") if s.strip()} or None

    r = audit(ids)
    print("보고서 %d편 · 인용 %d개" % (r["reports"], r["quotes"]))

    if r["too_long"]:
        print("\n[인용이 %d자 초과] %d건" % (MAX_VERBATIM_CHARS, len(r["too_long"])))
        for tid, n, head in r["too_long"][:20]:
            print("  %s %d자 — %s…" % (tid, n, head))
    else:
        print("인용 길이: 전부 %d자 이내" % MAX_VERBATIM_CHARS)

    if r["unmatched"]:
        print("\n[원문에서 못 찾은 인용] %d건 — 지어낸 말일 수 있다" % len(r["unmatched"]))
        for tid, score, head in r["unmatched"][:30]:
            print("  %s 닮은정도 %.2f — %s…" % (tid, score, head))
    else:
        print("인용: 전부 원문에서 확인됨")

    if r["stranger_names"]:
        # 참고용이다. 3인칭 언급('노민석 사무실을 다녀온')이 대부분이라 대체로 정상이고,
        # 실제로 남의 말로 잘못 적은 경우만 걸러 보려면 사람이 그 줄을 봐야 한다.
        print("\n[그 주제에 없는 사람 이름] %d건 (참고 — 3인칭 언급이면 정상)"
              % len(r["stranger_names"]))
        seen = set()
        for tid, nick in r["stranger_names"]:
            if (tid, nick) in seen:
                continue
            seen.add((tid, nick))
            print("  %s — %s" % (tid, nick))
    else:
        print("이름: 전부 그 대화의 참여자")

    bad = len(r["too_long"]) + len(r["unmatched"])
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
