# -*- coding: utf-8 -*-
"""사진·동영상 메시지인데 대장(images.jsonl)에 줄이 없는 것을 메꾼다.

왜 필요한가
  화면도, 작은 사진 만들기도, 발행도 모두 `messages.jsonl` 의 `image_id` 로
  대장을 찾아간다. 그 줄이 없으면 원본을 받아 놔도 붙일 자리가 없다 — 파일은
  inbox 에 남고 화면에는 영영 안 나온다.

  실측 2026-08-31: `ingest_incremental.to_record` 가 `kind == "image"` 일 때만
  image_id 를 매겼다. parser 는 `("image", "video")` 둘 다 매기는데 여기만
  좁았다 — 같은 사실을 두 곳에서 다르게 적고 있었다. 그래서 동영상 메시지는
  image_id 가 없고 대장에도 줄이 없었다(msg-002790, msg-003098).

  코드는 고쳤지만 **이미 들어온 메시지는 스스로 낫지 않는다.** 증분 반영은 새
  메시지만 보기 때문이다. 이 스크립트가 그 빚을 갚는다.

되풀이해 돌려도 안전하다
  이미 줄이 있는 메시지는 건드리지 않는다. 원본을 받은 줄도 그대로 둔다 —
  '대기' 로 되돌리면 이미 붙은 사진이 화면에서 사라진다.

사용
  python -m scripts.backfill_media_records --dry-run
  python -m scripts.backfill_media_records
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
MESSAGES = OUTPUT / "messages.jsonl"
IMAGES = OUTPUT / "images.jsonl"

MEDIA_KINDS = ("image", "video")


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    """옆에 쓰고 갈아 끼운다 — 반쯤 쓰인 대장을 다른 단계가 읽으면 안 된다."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(path)


def image_id_for(message_id: str) -> str:
    """msg-003098 → img-003098. 대장의 기존 줄들이 쓰는 규칙 그대로다."""
    return "img-" + message_id.split("-", 1)[1]


def stub(message: dict) -> dict:
    return {
        "image_id": message["image_id"],
        "message_id": message["id"],
        "timestamp": message["timestamp"],
        "nickname": message["nickname"],
        "media_kind": message["kind"],
        "image_sequence": 1,
        "expected_asset_count": message.get("image_count") or 1,
        "status": "pending",
        "local_path": None,
        "original_filename": None,
        "extension": None,
        "byte_size": None,
        "sha256": None,
        "collected_at": None,
        "note": "뒤늦게 메꾼 기록 — 원본 미수집",
        "assets": [],
    }


def plan(messages: list[dict], records: list[dict]) -> list[dict]:
    """줄이 없는 사진·동영상 메시지를 시간 순으로 추린다."""
    known = {r.get("message_id") for r in records}
    return [
        m for m in messages
        if m.get("kind") in MEDIA_KINDS and m["id"] not in known
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    messages = _read_jsonl(MESSAGES)
    records = _read_jsonl(IMAGES)
    missing = plan(messages, records)

    if not missing:
        print("메꿀 것이 없습니다 — 사진·동영상 메시지가 모두 대장에 있습니다.")
        return 0

    # 새로 매길 번호가 남의 것과 겹치면 안 된다. 겹친 채로 쓰면 대장의 한 줄에
    # 두 메시지가 달라붙고, 어느 쪽 사진인지 화면이 알 수 없게 된다.
    taken = {str(r["image_id"]) for r in records}
    clashes = []
    for m in missing:
        want = m.get("image_id") or image_id_for(m["id"])
        if want in taken:
            clashes.append((m["id"], want))
    if clashes:
        for mid, want in clashes:
            print("  %s 에 줄 번호 %s 를 주려 했으나 이미 쓰이고 있습니다" % (mid, want))
        print("겹치는 번호가 있어 아무것도 고치지 않았습니다.")
        return 1

    for m in missing:
        if not m.get("image_id"):
            m["image_id"] = image_id_for(m["id"])
        records.append(stub(m))
        print("  %s %s %s → %s"
              % (m["id"], m["timestamp"], m["kind"], m["image_id"]))

    # 대장은 image_id 순으로 정렬돼 있다. 새 줄을 끝에 붙이면 그 약속이 깨진다.
    records.sort(key=lambda r: str(r["image_id"]))

    print("메꿀 기록 %d개" % len(missing))
    if args.dry_run:
        print("--dry-run: 아무것도 쓰지 않았습니다.")
        return 0

    _write_jsonl(MESSAGES, messages)
    _write_jsonl(IMAGES, records)
    print("messages.jsonl · images.jsonl 을 고쳤습니다.")
    print("다음: python -m scripts.collect_drawer  (원본이 inbox 에 있으면 붙습니다)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
