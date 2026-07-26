# -*- coding: utf-8 -*-
"""Generated UI artwork를 화면용 WebP로 축소·최적화한다."""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageOps


def optimize_image(
    source: Path | str,
    output: Path | str,
    *,
    max_width: int,
    quality: int,
) -> Path:
    source = Path(source)
    output = Path(output)
    if max_width < 1:
        raise ValueError("max_width는 1 이상이어야 합니다.")
    if not 1 <= quality <= 100:
        raise ValueError("quality는 1~100이어야 합니다.")

    output.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened)
        if image.width > max_width:
            height = max(1, round(image.height * max_width / image.width))
            image = image.resize((max_width, height), Image.Resampling.LANCZOS)
        image.save(output, "WEBP", quality=quality, method=6)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--max-width", type=int, required=True)
    parser.add_argument("--quality", type=int, default=76)
    args = parser.parse_args()
    path = optimize_image(
        args.source,
        args.output,
        max_width=args.max_width,
        quality=args.quality,
    )
    print("%s (%.1f KB)" % (path, path.stat().st_size / 1024))


if __name__ == "__main__":
    main()
