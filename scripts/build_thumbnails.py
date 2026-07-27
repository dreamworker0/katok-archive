# -*- coding: utf-8 -*-
"""갤러리에 쓸 작은 사진을 만든다.

왜 필요한가
    갤러리는 200px 칸에 사진을 보여주는데, 지금은 **원본을 그대로 내려받는다**.
    22MB 사진을 손톱만 한 칸에 넣으려고 22MB 를 받는다. 실측 2026-07-27:
    사진 312장 합계 462.7MB — 한 사람이 갤러리를 끝까지 훑으면 그만큼 나간다.
    멤버 10명이면 4.6GB 다.

    페이징으로는 줄지 않는다. 다음 장을 누르면 어차피 받기 때문이다. 줄이는 것은
    작은 사진이다 — 원본은 눌러서 크게 볼 때만 받는다.

어디에 두는가
    assets/thumbs/<연-월>/<자산id>.webp

    원본과 폴더를 섞지 않는다. assets/images 는 '원본 하나당 파일 하나' 라는 성질을
    지켜야 하고(테스트가 그것을 센다), Storage 규칙도 경로로 갈라 두는 편이 명확하다.
    규칙에 thumbs/** 를 함께 열어야 한다 — 안 열면 화면에서 403 이 난다.

크기
    긴 변 640px. 화면 칸이 200px 이라 2배 화면(레티나)에서도 흐리지 않고, webp 로
    누르면 보통 20~60KB 로 떨어진다. 원본보다 큰 결과가 나오면 쓰지 않는다 —
    이미 작은 사진에 굳이 다른 파일을 하나 더 두는 것은 손해다.

사용
    python -m scripts.build_thumbnails            # 없는 것만 만든다
    python -m scripts.build_thumbnails --force    # 전부 다시 만든다
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from scripts import build_site
from scripts.optimize_ui_art import optimize_image

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
THUMB_DIR = ROOT / "assets" / "thumbs"
MAX_EDGE = 640
QUALITY = 72


def thumb_rel_path(asset_id: str, timestamp: str) -> str:
    """자산 하나에 대응하는 작은 사진의 상대 경로."""
    return "assets/thumbs/%s/%s.webp" % (timestamp[:7], asset_id)


def make_thumb(source: Path, dest: Path) -> int | None:
    """작은 사진을 만들고 바이트 수를 돌려준다. 만들 이유가 없으면 None.

    긴 변을 기준으로 줄인다. optimize_image 는 가로만 보므로, 세로로 긴 사진은
    가로 제한을 걸어도 작아지지 않는다 — 세로가 긴 화면 캡처가 많아서 실제로 문제가
    된다. 그래서 긴 변이 가로인지 보고 목표 폭을 정한다.
    """
    try:
        with Image.open(source) as opened:
            width, height = opened.size
    except (UnidentifiedImageError, OSError):
        return None

    longest = max(width, height)
    if longest <= MAX_EDGE and source.stat().st_size <= 80_000:
        # 이미 작고 가벼운 사진. 파일을 하나 더 두는 값이 없다.
        return None

    scale = min(1.0, MAX_EDGE / longest)
    target_width = max(1, round(width * scale))
    optimize_image(source, dest, max_width=target_width, quality=QUALITY)
    size = dest.stat().st_size
    if size >= source.stat().st_size:
        # 줄이려다 커졌다. 원본을 쓰는 편이 낫다.
        dest.unlink(missing_ok=True)
        return None
    return size


def make_poster(source: Path, dest: Path) -> int | None:
    """동영상 첫 장면을 뽑아 포스터로 만든다. 바이트 수, 실패하면 None.

    갤러리에 동영상을 그대로 걸면 재생하려고 15MB 를 받는다. 포스터만 걸어 두고
    누를 때 원본을 받게 하려면 그림 한 장이 필요하다.

    1초 지점을 쓴다 — 0초는 검은 화면인 영상이 흔하다. 영상이 1초보다 짧으면
    ffmpeg 이 아무것도 내놓지 않으므로 그때는 0초로 다시 시도한다.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    for offset in ("00:00:01", "00:00:00"):
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-ss", offset, "-i", str(source),
            "-frames:v", "1",
            "-vf", "scale='min(%d,iw)':-2" % MAX_EDGE,
            str(dest),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=60)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                FileNotFoundError):
            continue
        if dest.is_file() and dest.stat().st_size > 0:
            return dest.stat().st_size
    dest.unlink(missing_ok=True)
    return None


def run(force: bool) -> dict:
    rows = build_site._read_jsonl(OUTPUT / "images.jsonl")
    made = skipped = kept = failed = 0
    saved_from = saved_to = 0

    for row in rows:
        for asset in row.get("assets") or []:
            source = ROOT / asset["local_path"]
            if not source.is_file():
                failed += 1
                continue
            rel = thumb_rel_path(asset["asset_id"], row["timestamp"])
            dest = ROOT / rel
            if dest.is_file() and not force:
                asset["thumb_path"] = rel
                asset["thumb_bytes"] = dest.stat().st_size
                kept += 1
                continue

            # 동영상은 프레임을 뽑아야 한다. Pillow 는 mp4 를 못 읽는다.
            if (row.get("media_kind") == "video"
                    or source.suffix.lower() in (".mp4", ".mov")):
                size = make_poster(source, dest)
            else:
                size = make_thumb(source, dest)
            if size is None:
                # 작은 사진은 원본을 그대로 쓴다. 화면이 thumb_path 가 없으면
                # 원본을 쓰도록 되어 있어야 한다.
                asset.pop("thumb_path", None)
                asset.pop("thumb_bytes", None)
                skipped += 1
                continue
            asset["thumb_path"] = rel
            asset["thumb_bytes"] = size
            saved_from += source.stat().st_size
            saved_to += size
            made += 1

    with (OUTPUT / "images.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    print("작은 사진: 새로 %d개 · 그대로 %d개 · 원본 사용 %d개 · 못 읽음 %d개"
          % (made, kept, skipped, failed))
    if made:
        print("  줄인 용량: %.1fMB → %.1fMB (%.0f%%)"
              % (saved_from / 1e6, saved_to / 1e6, 100 * saved_to / saved_from))
    return {"made": made, "kept": kept, "skipped": skipped, "failed": failed}


def main() -> int:
    ap = argparse.ArgumentParser(description="갤러리용 작은 사진을 만든다")
    ap.add_argument("--force", action="store_true", help="이미 있어도 다시 만든다")
    args = ap.parse_args()
    run(args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
