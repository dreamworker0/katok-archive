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

from scripts.import_images import (
    PHOTO_EXTENSIONS,
    VIDEO_EXTENSIONS,
    import_image_files,
)

ROOT = Path(__file__).resolve().parent.parent
FILES_DIR = ROOT / "assets" / "files"
IMAGES_MANIFEST = ROOT / "output" / "images.jsonl"
INBOX = ROOT / "inbox" / "drawer"

# 목록은 import_images 한 곳에서 가져온다. 두 벌로 두면 갈라지고, 갈라지면
# 여기서 '동영상' 으로 골라 넘긴 것을 저쪽이 조용히 버린다 — 파일은 사라지지
# 않지만 붙지도 않고, 아무도 그 사실을 못 듣는다.
IMAGE_EXT = PHOTO_EXTENSIONS
VIDEO_EXT = VIDEO_EXTENSIONS


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
    # 이번 실행에서 이미 찜한 자리. 디스크만 봐서는 --dry-run 이 같은 묶음의 두 번째
    # 파일을 알아보지 못한다(아무것도 안 쓰니 자리가 계속 비어 보인다). 미리보기가
    # 실제와 다른 수를 말하면 그것이 곧 거짓말이다.
    claimed: dict[Path, str] = {}
    for src, name in docs:
        digest = _digest(src)
        dst = _place_for(src, name, digest, claimed)
        if dst is None:
            existing += 1
            continue
        claimed[dst] = digest
        added += 1
        if not dry_run:
            shutil.copy2(src, dst)
    return added, existing


def _place_for(src: Path, name: str, digest: str, claimed: dict[Path, str]) -> Path | None:
    """`assets/files/` 안에서 이 파일이 놓일 자리. 같은 내용이 이미 있으면 None.

    카톡은 같은 것을 또 저장하면 'name (1).pdf' 로 떨군다. 그 표시는 저장할 때
    이름이 겹쳐서 붙은 것이지 다른 파일이라는 뜻이 아니다. 그래서 **표시를 뗀
    이름을 먼저 노린다.**

    예전에는 'name (1).pdf' 를 그대로 놓은 뒤, 표시를 뗀 이름이 이미 있으면
    건너뛰는 식이었다. 그 검사는 한 묶음 안에서는 듣지 않는다 — 정렬하면
    'name (1).pdf' 가 'name.pdf' 보다 **앞선다**(공백 0x20 < 마침표 0x2E).
    표시 붙은 쪽이 먼저 처리되는 그 시점에는 견줄 원본이 아직 없어서 그냥
    들어가고, 곧이어 원본도 들어간다. 실측 2026-08-25: 같은 PDF 가 두 벌
    쌓였고(227391 bytes, 같은 해시) 자료 목록에 두 번 뜰 뻔했다.
    """
    suffix = Path(name).suffix
    marked = re.match(r"^(?P<base>.*) \(\d+\)$", Path(name).stem)
    # 노리는 순서: 표시를 뗀 이름 → 받은 그대로의 이름
    wanted = [FILES_DIR / name]
    if marked:
        wanted.insert(0, FILES_DIR / (marked.group("base") + suffix))

    for dst in wanted:
        taken = _taken_digest(dst, claimed)
        if taken is None:
            return dst
        if taken == digest:
            return None

    # 두 이름 다 **다른 내용**이 차지하고 있다. 덮어쓰지 않고 옆에 둔다
    # (같은 이름 다른 판본을 지키는 stash() 의 규칙과 같다).
    stem = wanted[-1].stem
    n = 2
    while True:
        dst = FILES_DIR / f"{stem}~{n}{suffix}"
        taken = _taken_digest(dst, claimed)
        if taken is None:
            return dst
        if taken == digest:
            return None
        n += 1


def _taken_digest(dst: Path, claimed: dict[Path, str]) -> str | None:
    """그 자리를 차지한 내용의 해시. 비어 있으면 None."""
    if dst in claimed:
        return claimed[dst]
    if dst.exists():
        return _digest(dst)
    return None


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

    # 사진과 동영상을 **한 번에** 넘긴다. 짝짓기는 import_images 가 종류를 갈라
    # 하므로(같은 분에 둘이 섞여도 엇갈리지 않는다) 여기서 나눠 부를 이유가 없다.
    imgs = [p for p, _ in moved if p.suffix.lower() in IMAGE_EXT]
    videos = [p for p, _ in moved if p.suffix.lower() in VIDEO_EXT]
    media = imgs + videos
    if media and not args.dry_run:
        result = import_image_files(IMAGES_MANIFEST, media, ROOT)
        print("  사진 %d장·동영상 %d개 중 %d개를 메시지에 연결"
              % (len(imgs), len(videos), result["imported"]))
        for item in result["unresolved"]:
            # 오늘 찍힌 것은 아직 대화 기록에 없다 — 내보내기가 돈 다음 실행에서 붙는다.
            print("    · 못 붙임: %s (%s)" % (Path(item["path"]).name, item["reason"]))
    elif media:
        print("  사진 %d장·동영상 %d개 (--dry-run: 연결하지 않음)" % (len(imgs), len(videos)))

    if args.dry_run:
        print("\n--dry-run: 아무것도 옮기지 않았습니다.")
    else:
        print("\n다음: python -m scripts.build_file_manifest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
