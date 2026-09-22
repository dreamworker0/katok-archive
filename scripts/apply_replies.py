# -*- coding: utf-8 -*-
"""건져 온 답장 관계를 분류에 반영한다.

왜 이 파일이 있나
  `reply_bubbles.py` 가 화면에서 건져 온 답장 관계(output/replies.jsonl)는 모으기만
  해서는 아무것도 바꾸지 않는다. 그것을 실제 스레드 분류에 얹는 것이 여기다.

  분류는 '가까이 있는 것끼리 묶는다'로 돌아간다. 그래서 몇 시간·며칠 전 글에 단
  답장이 바로 앞 화제에 흡수된다 — 실측 2026-09-22: 확정한 답장 96건 가운데 15건이
  부모와 다른 스레드에 있었다.

무엇을 옮기고 무엇을 안 옮기나 — 이 판단이 이 파일의 전부다
  답장이 옛 글에 걸렸다는 것과, 그 답장이 **새 대화를 열었다**는 것은 둘 다 사실이다.
  전자만 보고 기계적으로 옮기면 후자가 부서진다.

  실측 2026-09-22, 갈라진 15건의 속을 보니 두 종류였다:

    1. **홀로 떨어진 답장** (5건) — 스레드에 그것뿐이거나, 스레드 한가운데 있다.
       뒤따르는 대화가 그것에 매달려 있지 않다. → 부모의 스레드로 **옮긴다**.

    2. **대화를 연 답장** (10건) — 스레드의 첫 메시지이고 뒤에 1~22건이 따라붙었다.
       이것만 빼내면 남은 것들이 머리 없는 대화가 된다. t-429 는 22건이 그렇게
       된다. → **옮기지 않는다.** 대신 스레드에 '이 대화가 어디서 비롯됐는지'를
       `reply_origin` 으로 적어 둔다.

  둘째를 옮기지 않는 것은 타협이 아니라 사실에 더 가까운 기록이다. 그 대화는
  정말로 거기서 시작했고, 정말로 다른 글에 뿌리를 두고 있다.

옮기고 나면 보고서가 어긋난다
  메시지가 드나든 스레드의 보고서는 더 이상 내용과 맞지 않는다. 그래서 손댄 스레드
  목록을 output/replies-applied.json 에 남긴다 —
  `classify_unsorted.py --rewrite-ids` 에 그대로 넘기면 된다.

되돌리기
  topics.json 과 reports/ 는 손대기 전에 output/backup-replyfit-<날짜>/ 로 떠 둔다.
  비어서 사라지는 스레드의 보고서도 지우지 않고 그리로 옮긴다.

사용
  python -m scripts.apply_replies              # 무엇을 할지 보여주기만 한다
  python -m scripts.apply_replies --apply      # 실제로 고친다
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
REPLIES = OUTPUT / "replies.jsonl"
REPORTS = OUTPUT / "reports"
APPLIED = OUTPUT / "replies-applied.json"


def backup_dir() -> Path:
    return OUTPUT / f"backup-replyfit-{date.today():%Y%m%d}"


def plan(topics: dict, replies: list[dict]) -> dict:
    """무엇을 옮기고 무엇을 남길지 정한다. 쓰지 않는다."""
    threads = topics["threads"]
    by_id = {t["id"]: t for t in threads}
    home: dict[str, str] = {}
    for t in threads:
        for mid in t.get("message_ids") or []:
            home[mid] = t["id"]

    moves, origins, skipped = [], [], []
    for r in replies:
        src, dst = home.get(r["child"]), home.get(r["parent"])
        if src is None or dst is None:
            skipped.append({**r, "why": "메시지가 어느 스레드에도 없음"})
            continue
        if src == dst:
            continue                      # 이미 같은 곳 - 할 일 없음
        ids = by_id[src].get("message_ids") or []
        first = ids and ids[0] == r["child"]
        if first and len(ids) > 1:
            # 대화를 연 답장 - 옮기면 뒤따르는 것들이 고아가 된다.
            # 이미 같은 내용으로 적혀 있으면 할 일이 아니다. 매일 도는 단계라
            # '할 일 10건' 이 매번 찍히면 그것이 곧 거짓말이 된다.
            have = by_id[src].get("reply_origin") or {}
            if have.get("parent") == r["parent"] and have.get("parent_thread") == dst:
                continue
            origins.append({"thread": src, "parent": r["parent"],
                            "parent_thread": dst, "child": r["child"],
                            "followers": len(ids) - 1})
        else:
            moves.append({"child": r["child"], "from": src, "to": dst,
                          "emptied": len(ids) == 1})
    return {"moves": moves, "origins": origins, "skipped": skipped}


def apply(topics: dict, todo: dict) -> tuple[dict, list[str], list[str]]:
    """계획대로 고친 topics 와 (다시 써야 할 스레드, 사라진 스레드)."""
    by_id = {t["id"]: t for t in topics["threads"]}
    touched: set[str] = set()

    for mv in todo["moves"]:
        src, dst = by_id[mv["from"]], by_id[mv["to"]]
        src["message_ids"] = [m for m in src["message_ids"] if m != mv["child"]]
        if mv["child"] not in dst["message_ids"]:
            dst["message_ids"].append(mv["child"])
            # 메시지 ID 는 수집 순서 = 시간 순서라 그대로 정렬하면 된다.
            dst["message_ids"].sort()
        touched.update((mv["from"], mv["to"]))

    # 출처는 **옮기기가 끝난 뒤** 적는다. 옮겨지는 메시지가 다른 스레드의 뿌리인
    # 경우가 있어서다 - 실측 2026-09-22: msg-003074 는 t-422 로 옮겨지면서 동시에
    # t-429 의 뿌리였다. 옮기기 전 값을 적으면 이미 거기 없는 스레드를 가리킨다.
    where = {mid: t["id"] for t in topics["threads"] for mid in (t.get("message_ids") or [])}
    for og in todo["origins"]:
        t = by_id[og["thread"]]
        # 이 대화가 어디서 비롯됐는지. 옮기지 않고 적어만 둔다.
        t["reply_origin"] = {"parent": og["parent"],
                             "parent_thread": where.get(og["parent"], og["parent_thread"])}
        touched.add(og["thread"])

    kept, gone = [], []
    for t in topics["threads"]:
        ids = t.get("message_ids") or []
        if not ids:
            gone.append(t["id"])
            continue
        t["start_msg"], t["end_msg"] = ids[0], ids[-1]
        kept.append(t)
    topics["threads"] = kept

    # 사라진 스레드는 다시 쓸 대상이 아니다.
    rewrite = sorted(touched - set(gone))
    return topics, rewrite, gone


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="실제로 고친다(기본은 보여주기만)")
    args = ap.parse_args()

    topics = read_json(TOPICS)
    if not REPLIES.exists():
        print(f"{REPLIES.name} 이 없습니다 — 먼저 scripts/kakao_replies.ps1 을 돌리세요.")
        return 1
    replies = read_jsonl(REPLIES)
    titles = {t["id"]: t.get("title", "") for t in topics["threads"]}
    counts = {t["id"]: len(t.get("message_ids") or []) for t in topics["threads"]}

    todo = plan(topics, replies)
    print(f"답장 {len(replies)}건 가운데 손댈 것: "
          f"옮김 {len(todo['moves'])}건, 출처만 적음 {len(todo['origins'])}건")

    if todo["moves"]:
        print("\n── 부모의 스레드로 옮긴다 (홀로 떨어진 답장) ──")
        for mv in todo["moves"]:
            note = "  ← 비어서 사라짐" if mv["emptied"] else ""
            print(f"  {mv['child']}  {mv['from']} '{titles[mv['from']]}'{note}")
            print(f"        → {mv['to']} '{titles[mv['to']]}'")
    if todo["origins"]:
        print("\n── 옮기지 않고 출처만 적는다 (대화를 연 답장) ──")
        for og in todo["origins"]:
            print(f"  {og['thread']} '{titles[og['thread']]}' ({counts[og['thread']]}건, "
                  f"뒤따르는 {og['followers']}건)")
            print(f"        뿌리: {og['parent']} in {og['parent_thread']} "
                  f"'{titles[og['parent_thread']]}'")
    for s in todo["skipped"]:
        print(f"  [건너뜀] {s['child']}: {s['why']}")

    if not args.apply:
        print("\n(--apply 를 주면 실제로 고칩니다. 지금은 아무것도 쓰지 않았습니다.)")
        return 0

    bak = backup_dir()
    bak.mkdir(parents=True, exist_ok=True)
    if not (bak / TOPICS.name).exists():
        shutil.copy2(TOPICS, bak / TOPICS.name)

    topics, rewrite, gone = apply(topics, todo)
    write_json(TOPICS, topics)

    # 사라진 스레드의 보고서는 지우지 않고 백업으로 옮긴다.
    moved_reports = []
    for tid in gone:
        p = REPORTS / f"{tid}.md"
        if p.exists():
            shutil.move(str(p), str(bak / p.name))
            moved_reports.append(p.name)

    write_json(APPLIED, {"rewrite": rewrite, "removed_threads": gone,
                         "moved_reports": moved_reports})
    print(f"\n고쳤습니다. 사라진 스레드 {len(gone)}개{': ' + ', '.join(gone) if gone else ''}")
    if moved_reports:
        print(f"  보고서는 {bak.name}/ 로 옮겼습니다: {', '.join(moved_reports)}")
    print(f"  다시 써야 할 보고서 {len(rewrite)}편 — {APPLIED.name} 에 적었습니다:")
    print(f"    python -m scripts.classify_unsorted --rewrite-ids {','.join(rewrite)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
