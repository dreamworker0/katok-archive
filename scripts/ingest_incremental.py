# -*- coding: utf-8 -*-
"""새로 내보낸 카카오톡 txt 에서 '이전에 없던 메시지만' 골라 아카이브에 반영한다.

지금까지는 새 대화를 사람이 눈으로 보고 판단해 반영했다. 이 스크립트는 그 판단을
결정론적 규칙으로 바꾼다 — 같은 파일을 두 번 넣어도, 겹치는 구간이 있어도 안전하다.

흐름
  inbox/*.txt (또는 --file)
    → 파싱(기존 scripts.kakao_parser 재사용)
    → 이미 있는 마지막 메시지 이후만 추출
    → messages.jsonl · participants.json · images.jsonl 갱신
      (conversation.md 는 **만들지 않는다.** 이 주석이 만든다고 적어 둔 탓에 아무도
       갱신하지 않는 원문 사본이 output/ 에 유령으로 남아 있었다 — 2026-07-27 에
       멈춘 채였고 2026-07-28 에 backup-3a-20260728/ 로 옮겼다. 원문의 정본은
       messages.jsonl 하나다.)
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


# 겹치는 구간에서 이만큼은 알아봐야 같은 방이라고 본다.
#
# 실측 2026-08-02, 같은 방의 실제 내보내기: 겹침 161건 중 154건을 알아봤다(95.7%).
# 못 알아본 7건은 파싱 차이다(멘션 표기·잘린 긴 글). 100% 를 요구하면 멀쩡한 날
# 갱신이 멈추고, 절반까지 늘어지면 다른 방을 통과시킨다. 그 사이에 둔다.
SAME_ROOM_MIN_MATCH = 0.9
# 이보다 적게 겹치면 판단하지 않는다 — 우연히 몇 건 어긋난 것으로 갱신을 멈출 수 없다.
SAME_ROOM_MIN_OVERLAP = 5


def check_same_room(parsed_messages, existing: list[dict]) -> tuple[bool, dict]:
    """이 내보내기가 원장과 같은 방의 것인지 본다.

    왜 필요한가
      증분 반영은 '마지막 메시지 이후'만 덧붙인다. 그래서 **엉뚱한 방을 내보내도**
      그 방의 최근 글이 그냥 '새 메시지 N건'으로 들어온다. 한 번 섞이면 어느 것이
      남의 방 글인지 표시가 없어 손으로 골라내야 한다.

    왜 '상위집합' 으로 검사하지 않는가
      옛 설계(codex/daily-kakaotalk-refresh 의 refresh_guard.py)는 내보내기가 늘
      원장의 상위집합이라고 보고, 후보가 더 짧으면 거부했다. 수집을 전용 계정으로
      돌린 뒤로 그 전제가 깨졌다 — 내보내기에는 그 계정이 초대된 뒤 구간만 담긴다
      (실측 2026-08-02: 후보 285줄 vs 원장 2,682건). 그대로 켜면 매일 거부한다.

      그래서 길이가 아니라 **겹치는 구간**만 본다. 원장의 마지막 시각 이하인 후보
      메시지는 이미 원장에 있어야 한다. 같은 방이면 거의 다 알아보고, 다른 방이면
      거의 못 알아본다.

    모를 때는 통과시킨다
      겹치는 구간이 너무 짧으면(SAME_ROOM_MIN_OVERLAP 미만) 판단하지 않는다.
      섞이는 것도 나쁘지만, 멀쩡한 날 갱신이 멈추는 것도 그만큼 나쁘다 — 판정할
      근거가 없을 때는 사람이 볼 수 있게 알리고 지나간다.
    """
    if not existing:
        return True, {"판정": "원장이 비어 비교하지 않음"}

    seen = {(m["timestamp"], m["nickname"], m.get("text") or "") for m in existing}
    last_ts = existing[-1]["timestamp"]

    overlap = [m for m in parsed_messages if m.timestamp <= last_ts]
    if len(overlap) < SAME_ROOM_MIN_OVERLAP:
        return True, {"판정": "겹치는 구간이 %d건뿐이라 비교하지 않음" % len(overlap)}

    matched = sum(1 for m in overlap
                  if (m.timestamp, m.nickname, m.text) in seen)
    ratio = matched / len(overlap)
    report = {"겹침": len(overlap), "알아봄": matched, "비율": round(ratio, 3)}
    return ratio >= SAME_ROOM_MIN_MATCH, report


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
        # 동영상도 사진과 같은 자리를 쓴다. 화면(build_site)도, 작은 사진 만들기도,
        # 발행도 이미 kind=="video" 를 다루는데 **여기서만** 사진으로 좁혀 놓아
        # 동영상은 image_id 가 없고 images.jsonl 에 기록도 안 생겼다. 그래서 원본을
        # 받아 놔도 붙일 자리가 없었다(실측 2026-08-31: msg-003098).
        # kakao_parser 도 같은 규칙을 쓴다 — 같은 사실을 두 곳에서 다르게 적고 있었다.
        "image_id": ("img-%06d" % number) if msg.kind in ("image", "video") else None,
        "image_count": msg.image_count if msg.kind == "image" else None,
        "source_line": msg.source_line,
        "is_file_share": msg.kind == "file",
    }
    return rec


def image_stub(rec: dict) -> dict:
    """새 사진·동영상 메시지는 '수집 대기' 상태로 images.jsonl 에 넣는다.

    media_kind 를 적어 두는 이유: 뒤 단계가 사진과 동영상을 갈라 다뤄야 한다.
    작은 사진은 프레임을 뽑아야 하고(Pillow 는 mp4 를 못 읽는다), 원본이 놓일
    자리도 assets/images 가 아니라 assets/videos 다. 확장자로도 갈릴 수 있지만
    그건 **원본을 받은 뒤에야** 알 수 있다 — 대기 상태에서는 파일이 없다.
    """
    return {
        "image_id": rec["image_id"],
        "message_id": rec["id"],
        "timestamp": rec["timestamp"],
        "nickname": rec["nickname"],
        "media_kind": rec["kind"],
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


def ingest(paths: list[Path], dry_run: bool, force_room: bool = False) -> dict:
    state = load_state()
    processed_hashes = {e["sha256"] for e in state.get("processed", [])}
    refused_rooms: list[str] = []

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

        # 엉뚱한 방을 내보냈으면 여기서 멈춘다. 섞인 뒤에는 표시가 없어 손으로
        # 골라내야 하므로, 의심스러우면 안 넣는 쪽이 되돌리기 쉽다.
        same_room, room_report = check_same_room(result.messages, messages)
        if not same_room and force_room:
            print("%s: 다른 방으로 보이지만 --force-room 이라 반영합니다 %s"
                  % (path.name, room_report))
            same_room = True
        if not same_room:
            print("%s: 원장과 다른 방으로 보입니다 %s" % (path.name, room_report))
            print("  반영하지 않습니다. 내보낸 방이 맞는지 확인하세요.")
            print("  맞다면 이 파일만 지정해 다시 돌리세요:"
                  " python -m scripts.ingest_incremental --file <경로> --force-room")
            refused_rooms.append(path.name)
            continue
        if "비율" in room_report and room_report["비율"] < 1:
            print("  같은 방 확인: %s" % room_report)

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
            if rec["kind"] in ("image", "video"):
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
        "refused_rooms": refused_rooms,
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
    ap.add_argument("--force-room", action="store_true",
                    help="다른 방으로 보여도 반영한다 (방 이름을 바꿨을 때 등)")
    args = ap.parse_args()

    paths = pick_input_files(args.file)
    if not paths:
        print("처리할 txt 가 없습니다. inbox/ 에 내보낸 파일을 두세요.")
        return 0

    print("대상 파일 %d개" % len(paths))
    summary = ingest(paths, args.dry_run, args.force_room)
    print("\n메시지 %d건 -> %d건 (신규 %d건%s)"
          % (summary["before"], summary["after"], summary["added"],
             ", 수집 거부 %d건" % summary["refused"] if summary["refused"] else ""))
    # 위 줄은 사람이 읽는 것이고, 아래 표식은 run_daily.ps1 이 읽는다. 콘솔
    # 코드페이지에 따라 한글이 깨지면 '신규 N건' 을 못 읽어 발행을 건너뛴다.
    print("NEW_MESSAGES=%d" % summary["added"])
    if summary["added"] and not args.dry_run:
        print("다음: python -m scripts.build_firestore_payload"
              " && node scripts/upload_firestore.js")

    # 다른 방으로 보이는 파일이 있으면 실패로 끝낸다.
    #
    # 조용히 넘기면 그 파일은 inbox 에 남아 매일 같은 자리에서 걸리는데, 로그에는
    # '신규 0건' 으로만 보인다 — 오늘 고친 '조용히 안 올라가던' 문제와 같은 꼴이다.
    # run_daily.ps1 은 Invoke-Step 이라 여기서 멈추고, 그날 발행은 건너뛴다.
    # 원본은 그대로 남으므로 방을 확인한 뒤 다시 돌리면 된다.
    if summary["refused_rooms"]:
        print("\n다른 방으로 보여 반영하지 않은 파일 %d개: %s"
              % (len(summary["refused_rooms"]), ", ".join(summary["refused_rooms"])))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
