# -*- coding: utf-8 -*-
"""새로 내보낸 카카오톡 txt 에서 '이전에 없던 메시지만' 골라 아카이브에 반영한다.

지금까지는 새 대화를 사람이 눈으로 보고 판단해 반영했다. 이 스크립트는 그 판단을
결정론적 규칙으로 바꾼다 — 같은 파일을 두 번 넣어도, 겹치는 구간이 있어도 안전하다.

흐름
  inbox/*.txt (또는 --file)
    → 파싱(기존 scripts.kakao_parser 재사용)
    → 이미 있는 마지막 메시지 이후만 추출
    → messages.jsonl · participants.json · images.jsonl · conversation.md 갱신
    → 새 메시지를 주제 스레드에 배정 (미분류 폴백 포함)
    → 처리한 txt 의 SHA-256 기록 (중복 처리 방지)

주제 분류
  새 메시지는 일단 '미분류' 스레드에 넣는다. 사람이 나중에 정리하거나 LLM 이
  재분류하면 되고, 이렇게 해야 '모든 메시지가 스레드에 속한다'는 불변식이
  자동 실행에서도 깨지지 않는다.

사용
  python -m scripts.ingest_incremental --dry-run
  python -m scripts.ingest_incremental
  python -m scripts.ingest_incremental --file "inbox/KakaoTalkExport-....txt"
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts import build_site, collection_policy
from scripts.kakao_parser import parse_chat

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
INBOX = ROOT / "inbox"
ARCHIVE_DIR = ROOT / "inbox" / "processed"
STATE_PATH = OUTPUT / "ingest-state.json"

UNSORTED_CATEGORY = "chat"      # 미분류 스레드가 임시로 속할 카테고리
UNSORTED_PREFIX = "t-unsorted-"


# ───────────────────────── 상태(중복 방지) ─────────────────────────

def load_state() -> dict:
    if STATE_PATH.exists():
        return build_site._read_json(STATE_PATH)
    return {"processed": [], "last_message_id": None, "last_timestamp": None}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ───────────────────────── 증분 추출 ─────────────────────────

def next_message_number(existing: list[dict]) -> int:
    """'msg-001509' → 1510

    마지막 줄이 아니라 **전체 최댓값**을 본다. 옛 백업을 합치면(backfill_export)
    파일이 시각 순으로 다시 정렬되면서 번호가 큰 레코드가 중간으로 간다. 그때
    마지막 줄을 믿으면 이미 쓴 번호를 다시 내주어 ID 가 겹친다.
    """
    numbers = [int(m["id"].split("-")[1]) for m in existing if m.get("id")]
    return max(numbers) + 1 if numbers else 1


def find_new_messages(parsed_messages, existing: list[dict]) -> tuple[list[dict], dict]:
    """이미 보관된 마지막 메시지 이후의 것만 고른다.

    시각만으로 자르면 같은 분에 여러 건이 있을 때 누락·중복이 생긴다. 그래서
    (timestamp, nickname, text) 조합으로 '이미 있는 것'을 집합으로 만들어 비교하고,
    마지막 시각보다 이전 것은 애초에 후보에서 제외한다.
    """
    seen = {(m["timestamp"], m["nickname"], m.get("text") or "") for m in existing}
    last_ts = existing[-1]["timestamp"] if existing else None

    new_rows = []
    stats = Counter()
    for msg in parsed_messages:
        key = (msg.timestamp, msg.nickname, msg.text)
        if last_ts and msg.timestamp < last_ts:
            stats["이전_구간"] += 1
            continue
        if key in seen:
            stats["이미_보관"] += 1
            continue
        seen.add(key)
        new_rows.append(msg)
        stats["신규"] += 1
    return new_rows, dict(stats)


def to_record(msg, number: int) -> dict:
    """parser 의 Message 를 messages.jsonl 레코드로 바꾼다."""
    mid = "msg-%06d" % number
    rec = {
        "id": mid,
        "timestamp": msg.timestamp,
        "date": msg.date,
        "time": msg.time,
        "nickname": msg.nickname,
        "text": msg.text,
        "urls": list(msg.urls),
        "kind": msg.kind,
        "image_id": ("img-%06d" % number) if msg.kind == "image" else None,
        "image_count": msg.image_count if msg.kind == "image" else None,
        "source_line": msg.source_line,
        "is_file_share": msg.kind == "file",
    }
    return rec


def image_stub(rec: dict) -> dict:
    """새 사진 메시지는 '수집 대기' 상태로 images.jsonl 에 넣는다."""
    return {
        "image_id": rec["image_id"],
        "message_id": rec["id"],
        "timestamp": rec["timestamp"],
        "nickname": rec["nickname"],
        "image_sequence": 1,
        "expected_asset_count": rec.get("image_count") or 1,
        "status": "pending",
        "local_path": None,
        "original_filename": None,
        "extension": None,
        "byte_size": None,
        "sha256": None,
        "collected_at": None,
        "note": "증분 수집으로 추가됨 — 사진 파일 미수집",
        "assets": [],
    }


# ───────────────────────── 주제 배정 ─────────────────────────

def assign_to_topics(topics: dict, new_ids: list[str], date_label: str) -> dict:
    """새 메시지를 '미분류' 스레드에 담는다.

    같은 날짜의 미분류 스레드가 이미 있으면 거기에 덧붙이고, 없으면 새로 만든다.
    이렇게 하면 '모든 메시지가 정확히 하나의 스레드에 속한다'는 불변식이 유지되고,
    나중에 사람이나 LLM 이 이 스레드를 쪼개 정리하면 된다.
    """
    tid = UNSORTED_PREFIX + date_label
    for t in topics["threads"]:
        if t["id"] == tid:
            t["message_ids"].extend(new_ids)
            t["end_msg"] = new_ids[-1]
            return topics

    topics["threads"].append({
        "id": tid,
        "category": UNSORTED_CATEGORY,
        "title": f"미분류 대화 ({date_label})",
        "summary": "증분 수집으로 추가된 새 대화입니다. 주제 분류가 필요합니다.",
        "start_msg": new_ids[0],
        "end_msg": new_ids[-1],
        "message_ids": list(new_ids),
    })
    return topics


# ───────────────────────── 본 처리 ─────────────────────────

def rebuild_participants(messages: list[dict]) -> dict:
    rows: dict[str, dict] = {}
    for m in messages:
        nk = m["nickname"]
        r = rows.get(nk)
        if r is None:
            rows[nk] = {"nickname": nk, "message_count": 1,
                        "first_timestamp": m["timestamp"], "last_timestamp": m["timestamp"]}
        else:
            r["message_count"] += 1
            if m["timestamp"] < r["first_timestamp"]:
                r["first_timestamp"] = m["timestamp"]
            if m["timestamp"] > r["last_timestamp"]:
                r["last_timestamp"] = m["timestamp"]
    ordered = sorted(rows.values(), key=lambda r: r["message_count"], reverse=True)
    return {"participants": ordered}


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def pick_input_files(explicit: str | None) -> list[Path]:
    if explicit:
        p = Path(explicit)
        if not p.is_absolute():
            p = ROOT / p
        if not p.exists():
            raise SystemExit("파일이 없습니다: %s" % p)
        return [p]
    if not INBOX.exists():
        return []
    return sorted(
        [p for p in INBOX.glob("*.txt") if p.is_file()],
        key=lambda p: p.stat().st_mtime,
    )


def ingest(paths: list[Path], dry_run: bool) -> dict:
    state = load_state()
    processed_hashes = {e["sha256"] for e in state.get("processed", [])}

    messages = build_site._read_jsonl(OUTPUT / "messages.jsonl")
    images = build_site._read_jsonl(OUTPUT / "images.jsonl")
    topics = build_site._read_json(OUTPUT / "topics.json")

    before_count = len(messages)
    total_new = 0
    total_refused = 0
    handled: list[dict] = []
    policy = collection_policy.load_policy()

    for path in paths:
        digest = sha256_of(path)
        if digest in processed_hashes:
            print("건너뜀(이미 처리): %s" % path.name)
            continue

        text = path.read_text(encoding="utf-8", errors="replace")
        result = parse_chat(text)
        new_msgs, stats = find_new_messages(result.messages, messages)

        # 수집 거부는 '신규 판정' 뒤에 적용한다. 순서를 바꿔도 결과는 같지만,
        # 이래야 "몇 건이 새로 왔고 그중 몇 건을 거부했는지"가 따로 보인다.
        new_msgs, refused, _ = collection_policy.filter_messages(new_msgs, policy)
        refused_count = sum(refused.values())
        total_refused += refused_count
        if refused_count:
            stats["신규"] = len(new_msgs)
            stats["수집거부"] = refused_count

        print("%s: 파일 내 메시지 %d건 / 신규 %d건 %s"
              % (path.name, len(result.messages), len(new_msgs), stats))
        if refused_count:
            # 본문은 찍지 않는다 — 수집하지 않기로 한 글을 로그에 남기면 의미가 없다
            print("  수집 거부 %d건 %s" % (refused_count, refused))
        if result.warnings:
            print("  파싱 경고 %d건" % len(result.warnings))

        if not new_msgs:
            entry = {"file": path.name, "sha256": digest, "added": 0}
            if refused_count:
                entry["refused"] = refused_count
            handled.append(entry)
            continue

        start_no = next_message_number(messages)
        new_records = [to_record(m, start_no + i) for i, m in enumerate(new_msgs)]
        messages.extend(new_records)
        for rec in new_records:
            if rec["kind"] == "image":
                images.append(image_stub(rec))

        date_label = new_records[0]["date"]
        topics = assign_to_topics(topics, [r["id"] for r in new_records], date_label)

        total_new += len(new_records)
        entry = {"file": path.name, "sha256": digest, "added": len(new_records),
                 "first": new_records[0]["id"], "last": new_records[-1]["id"]}
        if refused_count:
            entry["refused"] = refused_count
        handled.append(entry)

    summary = {
        "files": handled,
        "before": before_count,
        "after": len(messages),
        "added": total_new,
        "refused": total_refused,
    }

    if dry_run:
        print("\n--dry-run: 파일을 수정하지 않았습니다.")
        return summary
    if total_new == 0:
        # 처리 이력만 남겨 같은 파일을 다시 파싱하지 않도록 한다
        state["processed"].extend(handled)
        save_state(state)
        print("\n새 메시지가 없습니다. 처리 이력만 갱신했습니다.")
        return summary

    participants = rebuild_participants(messages)
    write_jsonl(OUTPUT / "messages.jsonl", messages)
    write_jsonl(OUTPUT / "images.jsonl", images)
    (OUTPUT / "participants.json").write_text(
        json.dumps(participants, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUT / "topics.json").write_text(
        json.dumps(topics, ensure_ascii=False, indent=2), encoding="utf-8")

    state["processed"].extend(handled)
    state["last_message_id"] = messages[-1]["id"]
    state["last_timestamp"] = messages[-1]["timestamp"]
    state["updated_at"] = datetime.now(KST).isoformat(timespec="seconds")
    save_state(state)

    # 처리한 txt 는 보관 폴더로 옮겨 inbox 를 비운다
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    for path in paths:
        if path.parent == INBOX:
            try:
                shutil.move(str(path), str(ARCHIVE_DIR / path.name))
            except Exception as exc:  # 이동 실패가 반영 자체를 되돌릴 이유는 아니다
                print("  경고: %s 이동 실패 (%s)" % (path.name, exc))

    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description="카카오톡 내보내기 txt 를 증분 반영")
    ap.add_argument("--file", help="특정 txt 하나만 처리")
    ap.add_argument("--dry-run", action="store_true", help="변경 없이 결과만 출력")
    args = ap.parse_args()

    paths = pick_input_files(args.file)
    if not paths:
        print("처리할 txt 가 없습니다. inbox/ 에 내보낸 파일을 두세요.")
        return 0

    print("대상 파일 %d개" % len(paths))
    summary = ingest(paths, args.dry_run)
    print("\n메시지 %d건 -> %d건 (신규 %d건%s)"
          % (summary["before"], summary["after"], summary["added"],
             ", 수집 거부 %d건" % summary["refused"] if summary["refused"] else ""))
    # 위 줄은 사람이 읽는 것이고, 아래 표식은 run_daily.ps1 이 읽는다. 콘솔
    # 코드페이지에 따라 한글이 깨지면 '신규 N건' 을 못 읽어 발행을 건너뛴다.
    print("NEW_MESSAGES=%d" % summary["added"])
    if summary["added"] and not args.dry_run:
        print("다음: python -m scripts.build_firestore_payload"
              " && node scripts/upload_firestore.js")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
