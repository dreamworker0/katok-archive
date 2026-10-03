# -*- coding: utf-8 -*-
"""하루 안에서 같은 맥락인데 둘로 갈린 주제를 찾는다 — 합칠 묶음을 **제안만** 한다.

분류는 메시지를 시간순으로 읽으며 화제가 바뀌는 자리에서 주제를 끊는다. 그런데
한 대화 사이에 다른 화제(새 멤버 인사, 링크 하나)가 끼면 거기서 끊기고, 끼어든
화제가 끝난 뒤 이어진 말은 새 주제가 된다. 실측 2026-10-03: '사례관리 AI 활용과
개인정보 유출 우려' 가 t-533(5건)·t-535(6건)로 갈렸고, 사이에 신규 멤버 초대
t-534 가 끼어 있었다. 한 사람의 사진과 그 사진을 설명하는 말이 두 주제로 갈린
곳도 있었다(t-084/t-085).

태그가 겹치는 쌍만 골라 보면 놓친다 — 같은 대화여도 보고서가 다른 면을 짚으면
태그가 안 겹친다. 그래서 주제가 둘 이상인 날마다 그날 대화 전체를 한 프롬프트에
놓고 묻는다.

기준(사용자 결정 2026-10-03): **하루 대화 안에서 맥락이 같으면 하나로 합친다.**
비슷한 화제라는 것만으로는 합치지 않는다 — 같은 대화가 이어진 것이어야 한다.

    python -m scripts.audit_same_day                       # 전체
    python -m scripts.audit_same_day --days 2026-10-02     # 특정 날짜만
    python -m scripts.audit_same_day --recent 2            # 밤 갱신: 최근 이틀, 바뀐 날만

출력: output/same-day-merge.json — 날짜별로 **합쳐 쓴다**(다시 돌린 날만 바뀐다).
반영은 scripts.merge_threads 가 한다. 원문은 출력에 싣지 않는다(저장소가 공개다).
"""
from __future__ import annotations

import argparse
import collections
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from scripts.jsonio import read_json, read_jsonl, write_json
from scripts.llm import call_claude, parse_reply

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
TOPICS = OUTPUT / "topics.json"
MESSAGES = OUTPUT / "messages.jsonl"
RESULT = OUTPUT / "same-day-merge.json"

# 합칠지는 주제 구조를 바꾸는 판단이다. 틀리면 사람이 나중에 찾아 되돌려야 하므로
# 분류와 같은 모델을 쓴다.
DEFAULT_MODEL = "opus"
TIMEOUT_SEC = 600
WORKERS = 3
MSG_TRIM = 300
REASON_TRIM = 160


def build_prompt(day: str, day_threads: list[dict], msgs: dict[str, list[dict]]) -> str:
    # 하루치를 시간순 한 줄로 놓고 줄마다 주제를 붙인다. 주제별로 묶어 보여주면
    # '사이에 끼어든 화제' 가 안 보인다 — 그게 이 감사가 찾는 것이다.
    rows = sorted(((m, tid) for tid, ms in msgs.items() for m in ms),
                  key=lambda r: r[0]["id"])
    lines = []
    for m, tid in rows:
        text = (m.get("text") or "").replace("\n", " ⏎ ")[:MSG_TRIM]
        lines.append(f"{m['time']} [{tid}] {m['nickname']}: {text}")
    heads = "\n".join(f"- {t['id']} | {t['title']} — {t.get('summary', '')}"
                      for t in day_threads)
    return f"""당신은 카카오톡 대화 아카이브의 주제 나눔을 감사합니다.

{day} 의 대화가 시간순으로 있습니다. 줄 앞 [t-...] 은 그 메시지가 지금 속한 주제입니다.
분류가 화제가 바뀌는 자리에서 주제를 끊다 보니, **한 대화가 둘 이상의 주제로
갈렸을 수** 있습니다. 흔한 경우:
- 대화 중간에 다른 화제(새 멤버 인사, 링크 하나)가 끼어들어 거기서 끊겼고,
  끼어든 화제가 끝난 뒤 이어진 말이 새 주제가 됐다.
- 한 사람이 올린 사진·링크와 그것을 설명하는 말이 서로 다른 주제로 갈렸다.
- 질문과 그 답, 초대와 그 환영 인사가 갈렸다.

## 이날의 주제
{heads}

## 이날의 대화
{chr(10).join(lines)}

## 할 일
같은 대화가 이어진 것인데 갈린 주제들을 묶으세요.
- **같은 대화의 연속**이어야 합니다: 앞 말을 받아 답하거나, 같은 글·사진·사건을
  두고 이어 말하거나, 같은 질문을 계속 붙드는 것.
- 비슷한 화제라는 것만으로는 묶지 마세요. 같은 날 따로 시작된 두 대화가 우연히
  같은 도구를 다루면 그건 두 주제입니다.
- 묶으면 한 주제가 됩니다. 묶은 주제의 제목·요지를 새로 쓰세요. 요지는 기존
  요지들처럼 한 문장, 누가 무엇을 했는지.
- 확신이 없으면 묶지 마세요. 빈 목록도 좋은 답입니다.

## 출력
JSON 만 출력하세요. 산문·코드펜스 없이 이 형태 그대로. reason 은 원문 인용 없이 한 문장.

{{"groups":[{{"threads":["t-000","t-001"],"confidence":"high","reason":"왜 한 대화인가","title":"묶은 주제 제목","summary":"묶은 주제 요지"}}]}}

- threads 에는 위 '이날의 주제' 에 있는 id 만, 둘 이상.
- confidence 는 high(이어지는 단서가 분명) 또는 medium(그럴듯하지만 단정 못 함).
- 묶을 것이 없으면 {{"groups":[]}}."""


def audit_day(day: str, day_threads: list[dict], msgs: dict[str, list[dict]],
              model: str, timeout: int) -> list[dict]:
    data = parse_reply(call_claude(build_prompt(day, day_threads, msgs), model, timeout,
                                   what="같은 날 합치기 감사") or "")
    if not data or not isinstance(data.get("groups"), list):
        raise RuntimeError("결과를 받지 못함")
    known = {t["id"]: t for t in day_threads}
    out, used = [], set()
    for g in data["groups"]:
        if not isinstance(g, dict):
            continue
        ids = [i for i in dict.fromkeys(g.get("threads") or []) if i in known]
        ids = [i for i in ids if i not in used]     # 한 주제가 두 묶음에 들면 앞 것만
        if len(ids) < 2:
            continue
        used.update(ids)
        conf = g.get("confidence") if g.get("confidence") in ("high", "medium") else "medium"
        out.append({
            "date": day,
            "threads": ids,
            "titles": [known[i]["title"] for i in ids],
            "confidence": conf,
            "reason": str(g.get("reason") or "")[:REASON_TRIM],
            "title": str(g.get("title") or "").strip(),
            "summary": str(g.get("summary") or "").strip(),
        })
    return out


def day_signature(msgs: dict[str, list[dict]]) -> str:
    """그날의 주제 구성. 같으면 다시 물어도 같은 답이 나올 것이므로 묻지 않는다."""
    return ",".join(f"{tid}:{len(ms)}" for tid, ms in sorted(msgs.items()))


def load() -> dict:
    old = read_json(RESULT) if RESULT.exists() else {}
    return old if isinstance(old, dict) else {}


def save(by_day: dict[str, list[dict]], sigs: dict[str, str]) -> None:
    """날짜별로 덮어쓰되, 사람이 뺀 묶음(rejected)은 살려 둔다.

    밤마다 같은 날을 다시 감사하면 그날 목록이 새로 쓰인다. 사람이 읽고 뺀 묶음이
    같은 주제들로 다시 제안되면 그 표시를 옮겨 붙인다 — 안 그러면 다음 날 밤 자동
    합치기가 사람이 거절한 것을 되살린다.
    """
    old = load()
    days = dict(old.get("days") or {})
    for day, groups in by_day.items():
        rejected = {frozenset(g["threads"]): g for g in days.get(day, [])
                    if g.get("confidence") == "rejected"}
        for g in groups:
            r = rejected.get(frozenset(g["threads"]))
            if r:
                g["confidence"] = "rejected"
                g["rejected_why"] = r.get("rejected_why", "")
        days[day] = groups
    all_sigs = dict(old.get("sigs") or {})
    all_sigs.update(sigs)
    write_json(RESULT, {"days": dict(sorted(days.items())),
                        "sigs": dict(sorted(all_sigs.items()))})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", help="쉼표로 나눈 날짜(YYYY-MM-DD). 없으면 주제가 둘 이상인 날 전부")
    ap.add_argument("--recent", type=int, default=0,
                    help="최근 N일만, 그것도 지난 감사 뒤로 주제 구성이 바뀐 날만 (밤 갱신용)")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--workers", type=int, default=WORKERS)
    ap.add_argument("--timeout", type=int, default=TIMEOUT_SEC)
    args = ap.parse_args()

    threads = [t for t in read_json(TOPICS)["threads"] if t.get("message_ids")]
    by_id = {t["id"]: t for t in threads}
    msgs = {m["id"]: m for m in read_jsonl(MESSAGES)}
    per_day: dict[str, dict[str, list[dict]]] = collections.defaultdict(
        lambda: collections.defaultdict(list))
    for t in threads:
        for mid in t["message_ids"]:
            m = msgs.get(mid)
            if m:
                per_day[m["date"]][t["id"]].append(m)

    wanted = set(args.days.split(",")) if args.days else None
    if args.recent:
        seen = load().get("sigs") or {}
        recent = sorted(per_day)[-args.recent:]
        wanted = {d for d in recent if seen.get(d) != day_signature(per_day[d])}
    jobs = [(d, [by_id[i] for i in sorted(tids)], dict(tids))
            for d, tids in sorted(per_day.items())
            if len(tids) > 1 and (wanted is None or d in wanted)]
    print(f"감사 대상 {len(jobs)}일 (모델 {args.model}, 동시 {args.workers})")

    done_days: dict[str, list[dict]] = {}
    failed = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(audit_day, d, dts, ms, args.model, args.timeout): d
                for d, dts, ms in jobs}
        for n, fut in enumerate(as_completed(futs), 1):
            d = futs[fut]
            try:
                done_days[d] = fut.result()
            except Exception as e:      # 하루 실패로 전체를 버리지 않는다
                failed.append(d)
                print(f"[{n}/{len(jobs)}] {d}: 실패 — {e}")
                continue
            g = done_days[d]
            print(f"[{n}/{len(jobs)}] {d} 끝" + (f", 묶음 {len(g)}" if g else ""))
            save({d: done_days[d]}, {d: day_signature(per_day[d])})   # 중간에 죽어도 남긴다

    groups = [g for gs in done_days.values() for g in gs]
    hi = sum(g["confidence"] == "high" for g in groups)
    print(f"\n묶음 {len(groups)}개 (high {hi} · medium {len(groups) - hi}) — {RESULT.name}")
    if failed:
        print(f"실패한 날 {len(failed)}일 — 다시: --days {','.join(sorted(failed))}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
