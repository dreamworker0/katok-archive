# -*- coding: utf-8 -*-
"""스레드 소속 감사 — 메시지가 붙은 스레드가 **내용상** 맞는지 재검토한다.

카톡 txt 내보내기는 답장(인용) 구조를 통째로 버린다. '누구에게 답장' 헤더도
인용문도 없이 본문만 남는다. 그래서 몇 시간 전 글에 단 답장이 분류에서 바로
앞 화제에 흡수된다 — 실측 2026-08-06: 번역해서 읽어보겠다는 답장(msg-002784)이
직전의 한국어 유튜브 영상 스레드에 붙었는데, 실제로는 세 시간 전 영어 논문
공유에 단 답장이었다.

원본에 답장 표식이 없으니 기계적으로 골라낼 수 없고, 내용을 다시 읽는 수밖에
없다. 분류가 하루 단위로 돌았으므로 감사도 하루 단위로 돈다 — 그날 스레드들을
한 프롬프트에 놓고 '다른 스레드에 붙어야 할 메시지'를 묻는다. 어제오늘에 걸친
답장을 잡으려고 직전 며칠의 스레드 제목·요지도 후보로 같이 준다.

**옮기지는 않는다.** 의심 목록만 낸다 — 옮기는 것은 사람이 보고 결정한다.

    python -m scripts.audit_thread_fit                    # 전체
    python -m scripts.audit_thread_fit --days 2026-08-05  # 특정 날짜만
    python -m scripts.audit_thread_fit --model opus       # 더 좋게

출력: output/audit-thread-fit.json
원문은 출력물에 싣지 않는다(저장소가 공개다 — audit_quotes 와 같은 이유).
output/ 자체도 커밋되지 않지만, 로그로 흘러도 안 새게 이유(reason)는 모델에게
'원문 인용 없이 짧게'를 요구하고 길이를 자른다.
"""
from __future__ import annotations

import argparse
import collections
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

from scripts.classify_unsorted import call_claude, parse_reply
from scripts.jsonio import read_json, read_jsonl, write_json

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
TOPICS = OUTPUT / "topics.json"
MESSAGES = OUTPUT / "messages.jsonl"
RESULT = OUTPUT / "audit-thread-fit.json"

DEFAULT_MODEL = "sonnet"   # 걸러내는 1차 훑기다. 의심 건만 사람이(또는 opus 로) 본다.
TIMEOUT_SEC = 300
WORKERS = 3                # claude -p 동시 호출 수. 요금제 사용량이라 겸손하게.

# 후보로 같이 보여줄 '직전 스레드'의 범위. 답장은 보통 하루이틀을 넘지 않는다.
NEIGHBOR_DAYS = 3
# 메시지 하나를 프롬프트에 실을 때 자르는 길이. 소속 판단에는 앞부분이면 된다.
MSG_TRIM = 300
REASON_TRIM = 120


def build_prompt(day: str, day_threads: list[dict], msgs_by_thread: dict[str, list[dict]],
                 neighbors: list[dict]) -> str:
    blocks = []
    for t in day_threads:
        lines = [f"### {t['id']} | {t['title']}\n요지: {t.get('summary', '')}"]
        for m in msgs_by_thread[t["id"]]:
            text = (m.get("text") or "").replace("\n", " ⏎ ")[:MSG_TRIM]
            lines.append(f"  {m['id']} | {m['time']} | {m['nickname']} | {text}")
        blocks.append("\n".join(lines))
    threads_block = "\n\n".join(blocks)

    neighbor_lines = "\n".join(
        f"  {t['id']} | {t['title']} — {t.get('summary', '')}" for t in neighbors
    ) or "  (없음)"

    return f"""당신은 카카오톡 대화 아카이브의 분류 감사를 맡았습니다.

{day} 의 스레드 분류가 아래에 있습니다. 이미 한 번 분류된 것이지만, 카톡의 답장
기능으로 몇 시간 전 글에 답한 메시지가 **바로 앞 화제에 잘못 붙었을 수** 있습니다
(내보내기에 '누구에게 답장'이 남지 않습니다).

## 이날의 스레드와 메시지
{threads_block}

## 직전 며칠의 스레드 (제목·요지만 — 여기로 옮겨야 할 수도 있습니다)
{neighbor_lines}

## 할 일
다른 스레드에 붙어야 할 메시지를 찾으세요. 판단 기준:
- 말 속 단서(가리키는 대상, 언어, 매체, 호칭, 말투)가 지금 스레드가 아니라 다른
  스레드의 내용을 가리키는가.
- 시간이 가깝다는 것은 근거가 아닙니다. 내용 단서가 있을 때만 지적하세요.
- 인사·잡담처럼 어느 쪽에 있어도 이상하지 않은 말은 지적하지 마세요.
- 확신이 없으면 지적하지 않는 편이 낫습니다. 빈 목록도 좋은 답입니다.

## 출력
JSON 만 출력하세요. 산문·설명·코드펜스 없이 이 형태 그대로.
reason 은 원문을 인용하지 말고 한 문장으로 짧게.

{{"moves":[{{"msg":"msg-000000","to":"t-000","confidence":"high","reason":"왜 저 스레드인가"}}]}}

- msg 는 위 목록에 있는 message id, to 는 위에 나온 스레드 id 만 씁니다.
- confidence 는 high(단서가 분명) 또는 medium(그럴듯하지만 단정 못 함).
- 옮길 것이 없으면 {{"moves":[]}} 를 내세요."""


def audit_day(day: str, day_threads: list[dict], msgs_by_thread: dict[str, list[dict]],
              neighbors: list[dict], model: str, timeout: int) -> list[dict]:
    prompt = build_prompt(day, day_threads, msgs_by_thread, neighbors)
    data = parse_reply(call_claude(prompt, model, timeout) or "")
    if not data or not isinstance(data.get("moves"), list):
        return []

    by_id = {t["id"]: t for t in day_threads}
    for t in neighbors:
        by_id.setdefault(t["id"], t)
    msg_home = {
        m["id"]: (t["id"], m)
        for t in day_threads for m in msgs_by_thread[t["id"]]
    }

    found = []
    for mv in data["moves"]:
        if not isinstance(mv, dict):
            continue
        msg_id, to = mv.get("msg"), mv.get("to")
        if msg_id not in msg_home or to not in by_id:
            continue    # 지어낸 id — 버린다
        src, m = msg_home[msg_id]
        if to == src:
            continue
        confidence = mv.get("confidence")
        if confidence not in ("high", "medium"):
            confidence = "medium"
        found.append({
            "date": day,
            "msg": msg_id,
            "nickname": m.get("nickname"),
            "from": src,
            "from_title": by_id[src]["title"],
            "to": to,
            "to_title": by_id[to]["title"],
            "confidence": confidence,
            "reason": str(mv.get("reason") or "")[:REASON_TRIM],
        })
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", help="쉼표로 나눈 날짜 목록(YYYY-MM-DD). 없으면 전체")
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    help=f"claude -p 에 넘길 모델 (기본: {DEFAULT_MODEL})")
    ap.add_argument("--workers", type=int, default=WORKERS)
    ap.add_argument("--timeout", type=int, default=TIMEOUT_SEC)
    args = ap.parse_args()

    topics = read_json(TOPICS)
    threads = [t for t in topics["threads"] if t.get("message_ids") and t.get("title")]
    msgs = {m["id"]: m for m in read_jsonl(MESSAGES)}

    # 날짜 → 그날 메시지가 있는 스레드 → 그날의 메시지들
    per_day: dict[str, dict[str, list[dict]]] = collections.defaultdict(
        lambda: collections.defaultdict(list))
    thread_last_day: dict[str, str] = {}
    for t in threads:
        for mid in t["message_ids"]:
            m = msgs.get(mid)
            if not m:
                continue
            per_day[m["date"]][t["id"]].append(m)
            last = thread_last_day.get(t["id"])
            if last is None or m["date"] > last:
                thread_last_day[t["id"]] = m["date"]

    by_id = {t["id"]: t for t in threads}
    wanted = set(args.days.split(",")) if args.days else None
    jobs = []
    for day in sorted(per_day):
        if wanted and day not in wanted:
            continue
        tids = per_day[day]
        d = date.fromisoformat(day)
        lo, hi = (d - timedelta(days=NEIGHBOR_DAYS)).isoformat(), day
        neighbors = [
            by_id[tid] for tid, last in thread_last_day.items()
            if tid not in tids and lo <= last < hi
        ]
        # 스레드가 하나뿐이고 이웃도 없으면 옮겨 갈 곳이 없다 — 부를 이유가 없다.
        if len(tids) < 2 and not neighbors:
            continue
        day_threads = [by_id[tid] for tid in tids]
        jobs.append((day, day_threads, dict(tids), neighbors))

    print(f"감사 대상: {len(jobs)}일 / 스레드 {len(threads)}개 "
          f"(모델 {args.model}, 동시 {args.workers})")

    results: list[dict] = []
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {
            ex.submit(audit_day, day, dts, mbt, nbs, args.model, args.timeout): day
            for day, dts, mbt, nbs in jobs
        }
        for fut in as_completed(futures):
            day = futures[fut]
            done += 1
            try:
                found = fut.result()
            except Exception as e:    # 하루 실패로 전체를 버리지 않는다
                print(f"[{done}/{len(jobs)}] {day}: 실패 — {e}")
                continue
            results.extend(found)
            note = f", 의심 {len(found)}건" if found else ""
            print(f"[{done}/{len(jobs)}] {day} 끝{note}")
            # 중간에 죽어도 그때까지의 결과는 남긴다
            results.sort(key=lambda r: (r["confidence"] != "high", r["date"], r["msg"]))
            write_json(RESULT, results)

    results.sort(key=lambda r: (r["confidence"] != "high", r["date"], r["msg"]))
    write_json(RESULT, results)
    high = sum(1 for r in results if r["confidence"] == "high")
    print(f"\n의심 {len(results)}건 (high {high} / medium {len(results) - high})")
    print(f"목록: {RESULT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
