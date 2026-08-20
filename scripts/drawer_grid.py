# -*- coding: utf-8 -*-
"""카톡 '채팅방 서랍' 캡처에서 카드 자리를 찾는다.

왜 이 파일이 있나
  서랍의 항목은 접근성 API 에 하나도 노출되지 않는다(실측 2026-08-20: 격자 패널과
  스크롤바만 보인다). 그래서 저장하려면 좌표를 눌러야 하는데, 좌표를 고정값으로
  적어 둘 수 없다 — 월 구분 머리글('2026-08')이 행 사이에 끼어들어 아래 행을 전부
  밀기 때문이다. 스크롤 위치와 그 달의 장수에 따라 매번 달라진다.

  그래서 PowerShell 이 PrintWindow 로 찍은 그림을 여기서 읽어 카드 사각형을 찾고,
  체크 동그라미의 좌표를 돌려준다. 창을 다루는 일과 그림을 읽는 일을 나눈 것이다.

어떻게 찾나 — 평균이 아니라 '최솟값' 을 본다
  처음에는 줄·칸의 **평균 밝기**로 카드를 갈랐다. 사진 카드는 잘 됐지만 파일 카드는
  안쪽이 흰색이라 칸 평균이 여백과 구별되지 않아 5칸이 1칸으로 뭉갰다(실측).

  최솟값을 보면 둘 다 갈린다:
    · 카드 사이 여백은 패널 위아래로 끝까지 흰색이라 최솟값이 255 다
    · 카드가 걸친 칸은 테두리(약 229)나 그림이 어디선가 반드시 스친다
  파일 카드의 빈 줄도 좌우 테두리를 스치므로 카드 높이만큼 이어진다.

  순서는 칸 → 행이다. 칸을 먼저 잡아야 행을 '첫 칸의 폭 안에서' 잴 수 있다.
  칸 수는 행마다 다시 잰다 — 마지막 줄은 꽉 차 있지 않다.

  Pillow 에 '한 방향 최솟값' 이 없어 절반씩 겹쳐 접는다(_fold). 파이썬으로 픽셀을
  돌지 않으므로 780줄짜리 패널도 순식간이다. Pillow 만 쓴다 — 이 저장소의 의존성
  원칙(requirements.txt 주석)을 따른다.

사용
  python -m scripts.drawer_grid --image logs/drawer.png --pane 425,215,1474,694
  python -m scripts.drawer_grid --image ... --pane ... --json out.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageChops

# 여백으로 볼 밝기의 아래끝. 카드 테두리는 연한 회색(약 229)이고 여백은 흰색(255)
# 이라 그 사이에 둔다. 최솟값을 보기 때문에 문턱이 넉넉해도 갈린다.
WHITE_MIN = 250

# 카드로 인정할 최소 크기. 월 구분 머리글('2026-08')은 글자 높이가 20px 안쪽이라
# 이 값으로 걸러진다. 실측 카드 높이는 사진 190, 파일 229.
MIN_CARD_H = 90
MIN_CARD_W = 90

# 체크 동그라미의 중심 — 카드 좌상단에서의 거리(실측 2026-08-20).
# 파일 카드·사진 카드 모두 같았다.
CIRCLE_DX = 23
CIRCLE_DY = 25


def _pixels(img: Image.Image) -> list[float]:
    # Pillow 14 에서 getdata 가 사라진다. 새 이름을 쓰되 예전 버전에서도 돌게 둔다 —
    # 이 저장소는 pillow>=11 을 허용한다.
    getter = getattr(img, "get_flattened_data", None) or img.getdata
    return [float(v) for v in getter()]


def _row_means(img: Image.Image) -> list[float]:
    """세로 방향 줄별 평균 밝기."""
    h = img.height
    if h == 0:
        return []
    return _pixels(img.convert("L").resize((1, h), Image.BOX))


def _col_means(img: Image.Image) -> list[float]:
    """가로 방향 칸별 평균 밝기."""
    w = img.width
    if w == 0:
        return []
    return _pixels(img.convert("L").resize((w, 1), Image.BOX))


def _fold(img: Image.Image, vertical: bool) -> Image.Image:
    """절반씩 겹쳐 접어 픽셀별 **최솟값**을 남긴다.

    평균으로는 안 된다. 파일 카드는 안쪽이 흰색이라 칸 평균이 여백(255)과 구별되지
    않는다(실측: 5칸이 1칸으로 뭉갰다). 반면 **최솟값**은 잘 갈린다 —
      · 카드 사이 여백은 위아래로 끝까지 흰색이라 최솟값이 255 다
      · 카드가 걸친 칸은 테두리(약 229)나 그림이 반드시 스치므로 훨씬 어둡다
    Pillow 에 '한 방향 최솟값' 이 없으므로 절반씩 겹쳐 접는다. 780줄이면 열 번쯤
    접으면 끝나고, 접는 일은 C 안에서 돈다.
    """
    im = img.convert("L")
    while (im.height if vertical else im.width) > 1:
        n = im.height if vertical else im.width
        half = (n + 1) // 2          # 홀수여도 겹치게 잘라 한 줄도 빠뜨리지 않는다
        if vertical:
            a = im.crop((0, 0, im.width, half))
            b = im.crop((0, n - half, im.width, n))
        else:
            a = im.crop((0, 0, half, im.height))
            b = im.crop((n - half, 0, n, im.height))
        im = ImageChops.darker(a, b)
    return im


def _col_mins(img: Image.Image) -> list[float]:
    """칸별 최솟값(세로로 접는다)."""
    if img.width == 0 or img.height == 0:
        return []
    return _pixels(_fold(img, vertical=True))


def _row_mins(img: Image.Image) -> list[float]:
    """줄별 최솟값(가로로 접는다)."""
    if img.width == 0 or img.height == 0:
        return []
    return _pixels(_fold(img, vertical=False))


def _runs(values: list[float], limit: float, min_len: int) -> list[tuple[int, int]]:
    """limit 보다 어두운 값이 연속된 구간을 (시작, 길이) 로 모은다."""
    out: list[tuple[int, int]] = []
    start = None
    for i, v in enumerate(values):
        dark = v < limit
        if dark and start is None:
            start = i
        elif not dark and start is not None:
            if i - start >= min_len:
                out.append((start, i - start))
            start = None
    if start is not None and len(values) - start >= min_len:
        out.append((start, len(values) - start))
    return out


def find_cards(
    image_path: Path,
    pane: tuple[int, int, int, int],
    white_min: float = WHITE_MIN,
) -> dict:
    """카드 사각형과 동그라미 좌표를 찾는다.

    pane 은 (x, y, w, h) — 창 좌상단 기준. PowerShell 이 ctrlId 402(파일) /
    403(사진·동영상) 의 좌표를 재서 넘긴다. 선택 바가 떠 있으면 패널이 86px
    줄어들므로, 부르는 쪽이 **그때그때 다시 재서** 넘겨야 한다.
    """
    px, py, pw, ph = pane
    with Image.open(image_path) as raw:
        full = raw.convert("RGB")
    if px + pw > full.width or py + ph > full.height:
        raise SystemExit(
            "패널이 그림 밖입니다 — 그림 %dx%d, 패널 (%d,%d %dx%d)"
            % (full.width, full.height, px, py, pw, ph)
        )
    view = full.crop((px, py, px + pw, py + ph))

    # 1) 칸(열) 경계 — 패널 전체 높이에서 칸별 최솟값을 본다.
    #    카드 사이 여백은 끝까지 흰색이라 255 로 남고, 카드가 걸친 칸은 어두워진다.
    col_runs = _runs(_col_mins(view), white_min, MIN_CARD_W)
    if not col_runs:
        return {"pane": list(pane), "rows": [], "cards": [], "note": "칸을 찾지 못했습니다"}

    # 2) 행 경계 — 첫 칸의 폭 안에서 줄별 최솟값을 본다.
    #    파일 카드의 빈 줄도 좌우 테두리를 스치므로 카드 높이만큼 이어진다.
    x0, w0 = col_runs[0]
    row_runs = _runs(_row_mins(view.crop((x0, 0, x0 + w0, ph))), white_min, MIN_CARD_H)
    if not row_runs:
        return {"pane": list(pane), "rows": [], "cards": [], "note": "행을 찾지 못했습니다"}

    cards: list[dict] = []
    rows: list[dict] = []
    tall = max(h for _, h in row_runs)

    for top, height in row_runs:
        # 칸 수는 행마다 다시 잰다 — 마지막 줄은 꽉 차 있지 않다.
        band = _runs(
            _col_mins(view.crop((0, top, pw, top + height))), white_min, MIN_CARD_W
        )
        # 스크롤 때문에 잘린 행은 동그라미가 패널 밖이라 누를 수 없다.
        partial = height < tall * 0.75
        rows.append(
            {"y": py + top, "h": height, "cols": len(band), "partial": partial}
        )
        if partial:
            continue
        for left, width in band:
            cards.append(
                {
                    "x": px + left,
                    "y": py + top,
                    "w": width,
                    "h": height,
                    "circle": [px + left + CIRCLE_DX, py + top + CIRCLE_DY],
                }
            )

    return {"pane": list(pane), "rows": rows, "cards": cards}


def main() -> int:
    ap = argparse.ArgumentParser(description="서랍 캡처에서 카드 자리 찾기")
    ap.add_argument("--image", required=True, type=Path)
    ap.add_argument(
        "--pane",
        required=True,
        help="격자 패널 좌표 'x,y,w,h' (창 좌상단 기준)",
    )
    ap.add_argument("--json", type=Path, help="결과를 이 파일에 쓴다")
    ap.add_argument("--white-min", type=float, default=WHITE_MIN)
    args = ap.parse_args()

    try:
        pane = tuple(int(v) for v in args.pane.split(","))
    except ValueError:
        raise SystemExit("--pane 은 'x,y,w,h' 형식이어야 합니다")
    if len(pane) != 4:
        raise SystemExit("--pane 은 'x,y,w,h' 형식이어야 합니다")

    result = find_cards(args.image, pane, args.white_min)  # type: ignore[arg-type]

    print("행 %d개 / 누를 수 있는 카드 %d개" % (len(result.get("rows", [])), len(result["cards"])))
    for row in result.get("rows", []):
        print(
            "  y=%-5d 높이 %-4d 칸 %-2d %s"
            % (row["y"], row["h"], row["cols"], "(잘린 행 — 건너뜀)" if row["partial"] else "")
        )
    if result.get("note"):
        print("  " + result["note"])

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("→ %s" % args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
