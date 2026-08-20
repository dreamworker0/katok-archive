# -*- coding: utf-8 -*-
"""서랍에서 받은 첨부를 아카이브에 넣는다.

scripts/kakao_drawer.ps1 이 '내 문서\\카카오톡 받은 파일' 로 내려받은 것을 여기서
치운다. 지우지 않고 **옮긴다** — inbox/drawer/<날짜>/ 로 보관한 뒤 거기서 아카이브에
붙인다. 받은 파일 폴더를 비워 두는 이유는 두 가지다:

  · 다음 실행에서 '새로 받은 것'을 파일 수로 셀 수 있다
  · 같은 것을 다시 저장하면 카톡이 'name (1).jpg' 를 만드는데, 폴더가 비어 있으면
    그 찌꺼기가 쌓이지 않는다

문서·압축파일은 assets/files/ 로, 사진은 import_image_files 로 메시지에 잇는다.
파일 이름과 메시지를 잇는 일은 scripts/build_file_manifest.py 가 따로 한다 —
이 스크립트는 파일을 제자리에 놓는 것까지만 한다.

사용
  python -m scripts.collect_drawer
  python -m scripts.collect_drawer --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from scripts.import_images import import_image_files

ROOT = Path(__file__).resolve().parent.parent
FILES_DIR = ROOT / "assets" / "files"
IMAGES_MANIFEST = ROOT / "output" / "images.jsonl"
INBOX = ROOT / "inbox" / "drawer"

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".webm"}


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def default_save_dir() -> Path:
    return Path(os.environ.get("USERPROFILE", "~")).expanduser() / "Documents" / "카카오톡 받은 파일"


def stash(save_dir: Path, day: str, dry_run: bool) -> list[tuple[Path, str]]:
    """받은 파일을 inbox/drawer/<날짜>/ 로 옮긴다.

    돌려주는 값은 (옮긴 자리, **원래 이름**) 이다. 보관함에서 이름이 겹치면 뒤에
    '~2' 를 붙여 덧쓰기를 피하는데, 그 이름을 그대로 assets/files/ 로 가져가면
    메시지의 파일명과 영원히 안 맞는다(실측: 그렇게 6개가 짝을 잃었다).
    연결은 파일명 완전 일치로 하므로 원래 이름을 따로 들고 다닌다.
    """
    if not save_dir.is_dir():
        return []
    incoming = sorted(p for p in save_dir.iterdir() if p.is_file())
    if not incoming:
        return []
    target = INBOX / day
    moved: list[tuple[Path, str]] = []
    if not dry_run:
        target.mkdir(parents=True, exist_ok=True)
    for src in incoming:
        dst = target / src.name
        if dry_run:
            moved.append((dst, src.name))
            continue
        # 같은 이름이 이미 있으면 덧쓰지 않는다 — 판본이 다를 수 있다.
        if dst.exists():
            stem, suffix = dst.stem, dst.suffix
            n = 2
            while dst.exists():
                dst = target / f"{stem}~{n}{suffix}"
                n += 1
        shutil.move(str(src), str(dst))
        moved.append((dst, src.name))
    return moved


def place_documents(items: list[tuple[Path, str]], dry_run: bool) -> tuple[int, int]:
    """문서·압축파일을 assets/files/ 에 **원래 이름으로** 놓는다.

    (새로 놓은 수, 이미 있던 수)
    """
    docs = [(p, name) for p, name in items if p.suffix.lower() not in IMAGE_EXT | VIDEO_EXT]
    if not docs:
        return 0, 0
    if not dry_run:
        FILES_DIR.mkdir(parents=True, exist_ok=True)
    added = existing = 0
    for src, name in docs:
        dst = FILES_DIR / name
        if dst.exists():
            existing += 1
            continue
        # 카톡은 같은 것을 또 저장하면 'name (1).html' 로 떨군다. 그 표시를 떼고
        # 같은 내용이 이미 있으면 새 파일이 아니다 — 그대로 두면 대장에서 영원히
        # '짝을 못 찾은 파일' 로 남는다(실측: 그렇게 3개가 쌓였다).
        marked = re.match(r"^(?P<base>.*) \(\d+\)$", Path(name).stem)
        if marked:
            plain = FILES_DIR / (marked.group("base") + Path(name).suffix)
            if plain.is_file() and _digest(plain) == _digest(src):
                existing += 1
                continue
        added += 1
        if not dry_run:
            shutil.copy2(src, dst)
    return added, existing


def main() -> int:
    ap = argparse.ArgumentParser(description="서랍에서 받은 첨부를 아카이브에 넣는다")
    ap.add_argument("--save-dir", type=Path, default=None, help="카톡이 저장한 폴더")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    save_dir = args.save_dir or default_save_dir()
    day = datetime.now().strftime("%Y-%m-%d")

    moved = stash(save_dir, day, args.dry_run)
    if not moved:
        print("받은 파일이 없습니다 (%s)" % save_dir)
        return 0
    print("받은 파일 %d개 → inbox/drawer/%s/" % (len(moved), day))

    added, existing = place_documents(moved, args.dry_run)
    if added or existing:
        print("  문서: assets/files/ 에 %d개 추가, %d개는 이미 있었음" % (added, existing))

    imgs = [p for p, _ in moved if p.suffix.lower() in IMAGE_EXT]
    if imgs and not args.dry_run:
        result = import_image_files(IMAGES_MANIFEST, imgs, ROOT)
        print("  사진: %d장 중 %d장을 메시지에 연결" % (len(imgs), result["imported"]))
        for item in result["unresolved"]:
            # 오늘 찍힌 사진은 아직 대화 기록에 없다 — 내보내기가 돈 다음 실행에서 붙는다.
            print("    · 못 붙임: %s (%s)" % (Path(item["path"]).name, item["reason"]))
    elif imgs:
        print("  사진 %d장 (--dry-run: 연결하지 않음)" % len(imgs))

    videos = [p for p, _ in moved if p.suffix.lower() in VIDEO_EXT]
    if videos:
        print("  동영상 %d개는 inbox 에 두었습니다 — 붙이는 경로가 아직 없습니다" % len(videos))

    if args.dry_run:
        print("\n--dry-run: 아무것도 옮기지 않았습니다.")
    else:
        print("\n다음: python -m scripts.build_file_manifest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
