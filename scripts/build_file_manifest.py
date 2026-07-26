# -*- coding: utf-8 -*-
"""assets/files/ 의 첨부 파일을 파일 공유 메시지에 연결한다.

카카오톡 대화 내보내기(txt)에는 파일이 들어 있지 않고 이름 한 줄만 남는다.
그래서 아카이브의 파일 공유 메시지는 오랫동안 눌러도 아무 일이 없는 배지였다.
나중에 사람이 원본을 모아 assets/files/ 에 넣으면, 이 스크립트가 파일명으로
메시지와 이어 붙인다.

연결 기준은 **파일명 완전 일치**다. 메시지 본문이 "파일: <이름>" 형태라 이름이
그대로 남아 있어 대부분 그냥 맞는다. 비슷한 이름을 추측해서 잇지 않는다 —
엉뚱한 파일을 남의 메시지에 붙이는 것이 못 붙이는 것보다 나쁘다.

출력
  output/files.jsonl   {file_id, message_id, filename, local_path, byte_size, sha256}

사용
  python -m scripts.build_file_manifest
  python -m scripts.build_file_manifest --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from scripts import build_site

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
FILES_DIR = ROOT / "assets" / "files"
MANIFEST = OUTPUT / "files.jsonl"

CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".html": "text/html; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".zip": "application/zip",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".hwp": "application/x-hwp",
    ".hwpx": "application/haansofthwpx",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
}


def content_type_for(name: str) -> str:
    return CONTENT_TYPES.get(Path(name).suffix.lower(), "application/octet-stream")


def filename_of(message: dict) -> str:
    """'파일: 보고서.pdf' → '보고서.pdf'"""
    text = (message.get("text") or "").strip()
    if text.startswith("파일:"):
        return text[len("파일:"):].strip()
    return text


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def collect_local_files() -> dict[str, Path]:
    if not FILES_DIR.exists():
        return {}
    return {p.name: p for p in sorted(FILES_DIR.iterdir()) if p.is_file()}


def build_manifest(messages: list[dict]) -> dict:
    """파일 공유 메시지와 로컬 파일을 이어 붙인다."""
    local = collect_local_files()
    shares = [m for m in messages if m.get("kind") == "file"]

    by_name: dict[str, list[dict]] = defaultdict(list)
    for m in shares:
        by_name[filename_of(m)].append(m)

    rows, matched_names = [], set()
    digests: dict[str, str] = {}

    for name, msgs in sorted(by_name.items()):
        path = local.get(name)
        if path is None:
            continue
        matched_names.add(name)
        if name not in digests:
            digests[name] = sha256_of(path)
        for m in msgs:
            rows.append({
                "file_id": "file-" + m["id"].split("-")[1],
                "message_id": m["id"],
                "filename": name,
                "local_path": "assets/files/" + name,
                "byte_size": path.stat().st_size,
                "sha256": digests[name],
                "content_type": content_type_for(name),
                "nickname": m["nickname"],
                "date": m["date"],
            })

    rows.sort(key=lambda r: r["message_id"])

    # 한 파일이 여러 메시지에 걸리는 경우 — 같은 이름을 두 번 올렸을 때다.
    # 서로 다른 판본일 수 있으니 붙이되 눈에 띄게 알린다.
    ambiguous = sorted(n for n in matched_names if len(by_name[n]) > 1)

    return {
        "rows": rows,
        "missing": sorted(n for n in by_name if n not in matched_names),
        "unused": sorted(n for n in local if n not in matched_names),
        "ambiguous": ambiguous,
        "share_count": len(shares),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="첨부 파일을 메시지에 연결")
    ap.add_argument("--dry-run", action="store_true", help="파일을 쓰지 않고 결과만 출력")
    args = ap.parse_args()

    messages = build_site._read_jsonl(OUTPUT / "messages.jsonl")
    result = build_manifest(messages)
    rows = result["rows"]

    total = sum(r["byte_size"] for r in rows)
    print("파일 공유 메시지 %d건 중 %d건 연결 (%.1f MB)"
          % (result["share_count"], len(rows), total / 1024 / 1024))

    for r in rows:
        print("  ○ %s  %s  (%.1f MB, %s)"
              % (r["message_id"], r["filename"], r["byte_size"] / 1024 / 1024, r["nickname"]))
    for name in result["missing"]:
        print("  · 원본 없음: %s" % name)
    for name in result["unused"]:
        # 파일명이 조금이라도 다르면 안 붙는다. 이름을 맞춰 다시 돌리면 된다.
        print("  ! 짝을 못 찾은 파일: %s" % name)
    for name in result["ambiguous"]:
        print("  ! 같은 이름의 메시지가 여러 건: %s (모두 같은 파일로 연결됨)" % name)

    if args.dry_run:
        print("\n--dry-run: 파일을 쓰지 않았습니다.")
        return 0

    with MANIFEST.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("\noutput/files.jsonl 생성 (%d건)" % len(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
