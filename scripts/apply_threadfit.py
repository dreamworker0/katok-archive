# -*- coding: utf-8 -*-
"""스레드 소속 감사(audit_thread_fit)의 의심 목록을 실제로 반영한다.

이것은 **추론을 반영하는 일**이다 — 사실을 반영하는 apply_replies 와 다르다
  apply_replies 가 옮기는 근거는 화면에 적혀 있던 '○○에게 답장' 머리글과 인용문,
  즉 카카오톡이 스스로 남긴 사실이다. 여기서 옮기는 근거는 모델이 글을 읽고
  "그럴 것 같다"고 한 판단이다. 같은 무게로 다룰 수 없다.

  그래서 여기는 더 좁게 간다:

    1. **기본이 high 뿐이다.** medium 은 --confidence medium 을 붙여야 들어온다.
       medium 은 실제로 갈리지 않는 것이 섞여 있다 — 실측 2026-09-22: '톡 내용
       이해 못 해서 챗지피티한테 물었다'는 말이 해커톤 상금 쪽인지 클라우드 기사
       쪽인지 글만으로는 정해지지 않는다.

    2. **답장으로 확정된 구간은 손대지 않는다.** replies.jsonl 이 덮는 날짜는
       사실이 있는 곳이고, 그 위에 추측을 덧씌우면 안 된다. audit_thread_fit 이
       애초에 그 구간을 건너뛰지만, 옛 결과가 파일에 남아 있을 수 있어 여기서
       한 번 더 막는다.

    3. **대화를 연 메시지는 옮기지 않는다.** apply_replies 와 같은 이유다 —
       스레드의 첫 메시지를 빼내면 뒤따르던 대화가 머리를 잃는다. 다만 거기서는
       reply_origin 을 적어 두었는데 여기서는 **아무것도 적지 않는다.** 화면의
       그 줄은 '답장이었다'고 단정하는 문장이고, 추론으로 그렇게 단정할 수 없다.
       건너뛴 것은 목록으로만 내어 사람이 본다.

되돌리기
  topics.json 은 손대기 전에 output/backup-threadfit-<날짜>/ 로 뜬다.
  반영한 항목은 output/threadfit-applied.json 에 남는다 — 무엇을 왜 옮겼는지와
  다시 써야 할 보고서 목록이 거기 있다.

사용
  python -m scripts.apply_threadfit                     # 무엇을 할지 보여주기만
  python -m scripts.apply_threadfit --apply             # high 만 반영
  python -m scripts.apply_threadfit --confidence medium --apply   # medium 까지
"""
from __future__ import annotations

import argparse
import shutil
from datetime import date
from pathlib import Path

from scripts.jsonio import read_json, read_jsonl, write_json

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
TOPICS = OUTPUT / "topics.json"
AUDIT = OUTPUT / "audit-thread-fit.json"
REPLIES = OUTPUT / "replies.jsonl"
APPLIED = OUTPUT / "threadfit-applied.json"


def facts_cover_from() -> str | None:
    """답장 관계가 사실로 확정된 구간의 시작일. 그 이후는 추론을 얹지 않는다."""
    if not REPLIES.exists():
        return None
    dates = [r.get("child_date") for r in read_jsonl(REPLIES) if r.get("child_date")]
    return min(dates) if dates else None


def plan(topics: dict, audit: list[dict], want_medium: bool) -> dict:
    by_id = {t["id"]: t for t in topics["threads"]}
    home: dict[str, str] = {}
    for t in topics["threads"]:
        for mid in t.get("message_ids") or []:
            home[mid] = t["id"]
    covered = facts_cover_from()

    moves, opens, skipped = [], [], []
    for r in audit:
        conf = r.get("confidence")
        if conf != "high" and not (want_medium and conf == "medium"):
            continue
        src = home.get(r["msg"])
        dst = r.get("to")
        if src is None or dst not in by_id:
            skipped.append({**r, "why": "메시지나 갈 스레드가 지금은 없음"})
            continue
        if src == dst:
            continue                        # 이미 반영됨
        if covered and r.get("date", "") >= covered:
            skipped.append({**r, "why": f"답장으로 확정된 구간({covered} 이후) — 추론을 얹지 않음"})
            continue
        ids = by_id[src].get("message_ids") or []
        if ids and ids[0] == r["msg"] and len(ids) > 1:
            # 대화를 연 메시지다. 빼내면 뒤따르던 것들이 머리를 잃는다.
            opens.append({**r, "from": src, "followers": len(ids) - 1})
            continue
        moves.append({"msg": r["msg"], "from": src, "to": dst,
                      "confidence": conf, "date": r.get("date", ""),
                      "reason": r.get("reason", ""), "emptied": len(ids) == 1})
    return {"moves": moves, "opens": opens, "skipped": skipped}


def apply(topics: dict, todo: dict) -> tuple[list[str], list[str]]:
    by_id = {t["id"]: t for t in topics["threads"]}
    touched: set[str] = set()
    for mv in todo["moves"]:
        src, dst = by_id[mv["from"]], by_id[mv["to"]]
        src["message_ids"] = [m for m in src["message_ids"] if m != mv["msg"]]
        if mv["msg"] not in dst["message_ids"]:
            dst["message_ids"].append(mv["msg"])
            dst["message_ids"].sort()       # 메시지 ID = 수집 순서 = 시간 순서
        touched.update((mv["from"], mv["to"]))

    kept, gone = [], []
    for t in topics["threads"]:
        ids = t.get("message_ids") or []
        if not ids:
            gone.append(t["id"])
            continue
        t["start_msg"], t["end_msg"] = ids[0], ids[-1]
        kept.append(t)
    topics["threads"] = kept
    return sorted(touched - set(gone)), gone


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="실제로 고친다(기본은 보여주기만)")
    ap.add_argument("--confidence", choices=["high", "medium"], default="high",
                    help="medium 을 주면 확신이 낮은 것까지 포함한다(기본: high 만)")
    args = ap.parse_args()

    if not AUDIT.exists():
        print(f"{AUDIT.name} 이 없습니다 — 먼저 scripts.audit_thread_fit 을 돌리세요.")
        return 1
    topics = read_json(TOPICS)
    titles = {t["id"]: t.get("title", "") for t in topics["threads"]}
    counts = {t["id"]: len(t.get("message_ids") or []) for t in topics["threads"]}
    todo = plan(topics, read_json(AUDIT), args.confidence == "medium")

    print(f"옮김 {len(todo['moves'])}건 · 대화를 연 것이라 건너뜀 {len(todo['opens'])}건 "
          f"· 그 밖 건너뜀 {len(todo['skipped'])}건")
    if todo["moves"]:
        print("\n── 옮긴다 ──")
        for mv in todo["moves"]:
            note = "  ← 비어서 사라짐" if mv["emptied"] else ""
            print(f"  [{mv['confidence']}] {mv['date']} {mv['msg']}{note}")
            print(f"        {mv['from']} '{titles[mv['from']]}' ({counts[mv['from']]}건)")
            print(f"     →  {mv['to']} '{titles[mv['to']]}' ({counts[mv['to']]}건)")
            print(f"        {mv['reason'][:76]}")
    if todo["opens"]:
        print("\n── 옮기지 않는다 (그 대화의 첫 메시지다) ──")
        for op in todo["opens"]:
            print(f"  [{op['confidence']}] {op['date']} {op['msg']} — "
                  f"{op['from']} '{titles[op['from']]}' 의 첫 글, 뒤따르는 {op['followers']}건")
            print(f"        제안: {op['to']} '{titles.get(op['to'], '')}'")
    for s in todo["skipped"]:
        print(f"  [건너뜀] {s['msg']}: {s['why']}")

    if not args.apply:
        print("\n(--apply 를 주면 실제로 고칩니다. 지금은 아무것도 쓰지 않았습니다.)")
        return 0

    bak = OUTPUT / f"backup-threadfit-{date.today():%Y%m%d}"
    bak.mkdir(parents=True, exist_ok=True)
    if not (bak / TOPICS.name).exists():
        shutil.copy2(TOPICS, bak / TOPICS.name)
        shutil.copy2(AUDIT, bak / AUDIT.name)

    rewrite, gone = apply(topics, todo)
    write_json(TOPICS, topics)
    write_json(APPLIED, {"confidence": args.confidence, "moves": todo["moves"],
                         "opens": todo["opens"], "rewrite": rewrite,
                         "removed_threads": gone})
    print(f"\n고쳤습니다. 사라진 스레드 {len(gone)}개"
          f"{': ' + ', '.join(gone) if gone else ''}")
    print(f"  다시 써야 할 보고서 {len(rewrite)}편 — {APPLIED.name} 에 적었습니다:")
    if rewrite:
        print(f"    python -m scripts.classify_unsorted --rewrite-ids {','.join(rewrite)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
