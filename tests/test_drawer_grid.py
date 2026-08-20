# -*- coding: utf-8 -*-
"""서랍 캡처 판독기 — 카드 자리를 제대로 찾는지 본다.

실제 캡처 대신 같은 성질을 가진 그림을 만들어 쓴다. 판독기가 기대는 성질은 둘뿐이다:
  · 카드 사이 여백은 패널 위아래로 끝까지 흰색이다
  · 카드가 걸친 칸은 테두리나 그림이 어디선가 스친다
그래서 '흰 바탕에 테두리만 있는 카드'(파일 탭)와 '꽉 찬 카드'(사진 탭) 두 경우를
만들어 확인한다. 파일 탭이 특히 중요하다 — 평균 밝기로 재던 판독기가 여기서
5칸을 1칸으로 뭉갰다(실측 2026-08-20).
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from scripts.drawer_grid import CIRCLE_DX, CIRCLE_DY, find_cards

WIN_W, WIN_H = 1900, 1106
PANE = (425, 325, 1474, 780)


def _canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (WIN_W, WIN_H), (255, 255, 255))
    return img, ImageDraw.Draw(img)


def _save(img: Image.Image, tmp: str, name: str) -> Path:
    path = Path(tmp) / name
    img.save(path)
    return path


class DrawerGridTest(unittest.TestCase):
    def test_file_cards_are_split_by_column(self):
        """흰 바탕 + 테두리만 있는 카드 5개 + 2개를 각각 세어야 한다."""
        img, draw = _canvas()
        border = (229, 229, 229)
        top1, top2 = 416, 656
        for row_top, count in ((top1, 5), (top2, 2)):
            for i in range(count):
                x = 425 + i * 264
                draw.rectangle([x, row_top, x + 248, row_top + 224], outline=border)
                # 아이콘·글자처럼 안쪽 일부만 어둡게 — 나머지는 흰색이다
                draw.rectangle([x + 30, row_top + 30, x + 70, row_top + 80], fill=(60, 120, 200))
        # 월 구분 머리글: 얇은 글자 띠. 카드로 세면 안 된다.
        draw.rectangle([425, 380, 520, 398], fill=(120, 120, 120))

        with tempfile.TemporaryDirectory() as tmp:
            result = find_cards(_save(img, tmp, "file.png"), PANE)

        self.assertEqual(len(result["rows"]), 2, result["rows"])
        self.assertEqual([r["cols"] for r in result["rows"]], [5, 2])
        self.assertEqual(len(result["cards"]), 7)
        first = result["cards"][0]
        self.assertEqual(first["circle"], [425 + CIRCLE_DX, top1 + CIRCLE_DY])

    def test_media_cards_filled(self):
        """꽉 찬 카드 7개 + 3개."""
        img, draw = _canvas()
        top1, top2 = 398, 596
        for row_top, count in ((top1, 7), (top2, 3)):
            for i in range(count):
                x = 425 + i * 198
                draw.rectangle([x, row_top, x + 182, row_top + 182], fill=(90, 110, 140))

        with tempfile.TemporaryDirectory() as tmp:
            result = find_cards(_save(img, tmp, "media.png"), PANE)

        self.assertEqual([r["cols"] for r in result["rows"]], [7, 3])
        self.assertEqual(len(result["cards"]), 10)

    def test_clipped_row_is_skipped(self):
        """스크롤 때문에 잘린 행은 동그라미가 패널 밖이라 누를 수 없다."""
        img, draw = _canvas()
        # 패널 맨 위에 위가 잘린 행, 그 아래 온전한 행(높이 182).
        # 잘린 높이는 120 으로 둔다 — 최소 카드 높이(90)보다는 크고 온전한 행의
        # 75% 보다는 작아서, '너무 작아 버려지는' 길이 아니라 'partial 로 걸러지는'
        # 길을 지나간다. 60 으로 두면 애초에 행으로 세지도 않아 이 판정을 못 본다.
        for i in range(4):
            x = 425 + i * 198
            draw.rectangle([x, 325, x + 182, 325 + 119], fill=(90, 110, 140))
        for i in range(7):
            x = 425 + i * 198
            draw.rectangle([x, 480, x + 182, 480 + 182], fill=(90, 110, 140))

        with tempfile.TemporaryDirectory() as tmp:
            result = find_cards(_save(img, tmp, "clip.png"), PANE)

        partials = [r for r in result["rows"] if r["partial"]]
        self.assertEqual(len(partials), 1)
        self.assertEqual(len(result["cards"]), 7)
        self.assertTrue(all(c["y"] == 480 for c in result["cards"]))

    def test_empty_pane(self):
        img, _ = _canvas()
        with tempfile.TemporaryDirectory() as tmp:
            result = find_cards(_save(img, tmp, "empty.png"), PANE)
        self.assertEqual(result["cards"], [])
        self.assertIn("note", result)


if __name__ == "__main__":
    unittest.main()
