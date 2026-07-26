# -*- coding: utf-8 -*-
"""홈 화면에 설치될 PWA 아이콘(PNG)을 코드로 그린다.

favicon.svg 와 같은 형태(줄이 쓰인 문서)를 쓰지만 색은 화면의 따뜻한 팔레트
(--accent #CA7154, --surface #FFFDF8)에 맞춘다. 설치하면 홈 화면에 남는 그림이므로
앱을 열었을 때와 같은 색이어야 한다. (favicon.svg 는 예전 파란색을 그대로 둔다 —
브라우저 탭에만 쓰이고, 바꾸면 별개의 판단이 필요하다.)

PNG 로 굽는 이유: 매니페스트의 SVG 아이콘은 플랫폼마다 지원이 고르지 않아
설치 자격 판정에서 떨어질 수 있다.

손으로 만든 바이너리를 저장소에 두면 왜 이 색·이 여백인지 나중에 알 수 없다.
그래서 그림 자체를 스크립트로 남긴다: `python -m scripts.build_pwa_icons`
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ICONS = ROOT / "web" / "icons"

ACCENT = "#CA7154"  # --accent
PAPER = "#FFFDF8"  # --surface

# 계단 현상을 없애려고 4배로 그린 뒤 줄인다.
SUPERSAMPLE = 4

# favicon.svg 의 64 단위 좌표를 그대로 옮긴 문서 마크.
GLYPH_UNITS = 64.0
DOC = (18.0, 14.0, 28.0, 36.0)  # x, y, w, h  (rx 3)
DOC_RADIUS = 3.0
LINES = (  # 문서 원점(18,14) 기준 x, y, w, h  (rx 1.5)
    (5.0, 7.0, 18.0, 3.0),
    (5.0, 14.0, 18.0, 3.0),
    (5.0, 21.0, 12.0, 3.0),
)
LINE_RADIUS = 1.5


def draw_icon(size: int, *, corner_ratio: float, glyph_ratio: float) -> Image.Image:
    """아이콘 한 장을 그린다.

    corner_ratio: 배경 사각형의 모서리 반지름 / 변 길이. 0 이면 꽉 찬 정사각형.
    glyph_ratio:  문서 마크의 높이 / 변 길이. 마스커블은 잘려도 살아남게 작게 준다.
    """
    if size < 1:
        raise ValueError("size는 1 이상이어야 합니다.")
    if not 0.0 <= corner_ratio <= 0.5:
        raise ValueError("corner_ratio는 0~0.5여야 합니다.")
    if not 0.0 < glyph_ratio <= 1.0:
        raise ValueError("glyph_ratio는 0 초과 1 이하여야 합니다.")

    canvas = size * SUPERSAMPLE
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    corner = corner_ratio * canvas
    if corner > 0:
        draw.rounded_rectangle((0, 0, canvas - 1, canvas - 1), radius=corner, fill=ACCENT)
    else:
        draw.rectangle((0, 0, canvas - 1, canvas - 1), fill=ACCENT)

    # 문서 마크: 높이를 glyph_ratio 에 맞춰 재고, 가로세로 비율은 유지한 채 중앙에 둔다.
    _, _, doc_w, doc_h = DOC
    scale = glyph_ratio * canvas / doc_h
    left = (canvas - doc_w * scale) / 2.0
    top = (canvas - doc_h * scale) / 2.0
    draw.rounded_rectangle(
        (left, top, left + doc_w * scale, top + doc_h * scale),
        radius=DOC_RADIUS * scale,
        fill=PAPER,
    )
    for lx, ly, lw, lh in LINES:
        x0 = left + lx * scale
        y0 = top + ly * scale
        draw.rounded_rectangle(
            (x0, y0, x0 + lw * scale, y0 + lh * scale),
            radius=LINE_RADIUS * scale,
            fill=ACCENT,
        )

    return image.resize((size, size), Image.Resampling.LANCZOS)


# (파일명, 변 길이, 모서리 비율, 마크 비율)
#   any 아이콘  : 앱 목록에 그림 그대로 놓인다 → 스스로 모서리를 둥글린다.
#   maskable    : OS 가 원·사각형 등으로 잘라낸다 → 배경을 꽉 채우고 마크를 안쪽에.
#   apple-touch : iOS 가 알아서 모서리를 둥글리므로 꽉 찬 정사각형으로 준다.
SPECS = (
    ("icon-192.png", 192, 0.22, 0.56),
    ("icon-512.png", 512, 0.22, 0.56),
    ("icon-maskable-512.png", 512, 0.0, 0.42),
    ("apple-touch-icon.png", 180, 0.0, 0.52),
)


def main() -> None:
    ICONS.mkdir(parents=True, exist_ok=True)
    for name, size, corner_ratio, glyph_ratio in SPECS:
        icon = draw_icon(size, corner_ratio=corner_ratio, glyph_ratio=glyph_ratio)
        path = ICONS / name
        icon.save(path, format="PNG", optimize=True)
        print("%-24s %4dx%-4d %5.1f KB" % (name, size, size, path.stat().st_size / 1024))
    # 콘솔이 cp949 라서 em dash 같은 문자는 그대로 못 찍는다. 다른 스크립트와 같이 피한다.
    print("web/icons/ 생성 완료. 다음: python -m scripts.build_hosting")


if __name__ == "__main__":
    main()
