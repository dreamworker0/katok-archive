# -*- coding: utf-8 -*-
"""내보내기 스크립트의 안전장치 계약.

kakao_export.ps1 은 카톡 창에 키를 보낸다. 잘못된 창에 보내면 남의 파일을 저장하거나
(Ctrl+S) 더 나쁜 일을 할 수 있으므로, 안전장치는 리팩터링으로 조용히 사라져서는
안 되는 종류의 코드다. 여기서는 그 장치들이 제자리에 있는지만 본다.
"""
from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent.parent
EXPORT = (ROOT / "scripts" / "kakao_export.ps1").read_text(encoding="utf-8")


class ClickTargetIsVerifiedTests(unittest.TestCase):
    """포그라운드만 확인하는 것으로는 부족하다 (실측 2026-07-27).

    작업 관리자의 '항상 위' 옵션이 켜져 있으면 카톡이 포그라운드여도 그 위에
    그려진다. 그 상태로 입력칸 좌표를 클릭하면 포커스가 그 창으로 넘어가고 Ctrl+S 도
    거기로 간다. 로그에는 '최상단 확보 확인' 다음에 '저장 대화상자가 뜨지
    않았습니다' 만 남아 원인이 보이지 않았다.
    """

    def test_pid_at_helper_exists(self):
        # 좌표에 '실제로 보이는' 창을 묻는 수단. 포그라운드와 다른 개념이다.
        self.assertIn("static extern IntPtr WindowFromPoint(POINT p)", EXPORT)
        self.assertIn("public static uint PidAt(int x, int y)", EXPORT)

    def test_click_is_guarded_by_pid_check(self):
        self.assertIn("$pidAt = [Win32]::PidAt($ix, $iy)", EXPORT)
        self.assertIn("if ($pidAt -ne $kakaoPid) {", EXPORT)

    def test_guard_runs_before_the_click_and_before_ctrl_s(self):
        guard = EXPORT.index("$pidAt = [Win32]::PidAt($ix, $iy)")
        self.assertLess(guard, EXPORT.index("[Win32]::MouseClick()"))
        self.assertLess(guard, EXPORT.index("[Win32]::CtrlS()"))

    def test_mismatch_aborts_instead_of_clicking_anyway(self):
        block = EXPORT[EXPORT.index("if ($pidAt -ne $kakaoPid) {"):][:700]
        self.assertIn("Stop-Safely", block)
        # 어느 창이 덮었는지 알려줘야 사람이 치울 수 있다
        self.assertIn("Get-Process -Id $pidAt", block)

    def test_guard_names_the_fix_in_the_message(self):
        block = EXPORT[EXPORT.index("if ($pidAt -ne $kakaoPid) {"):][:700]
        self.assertIn("항상 위", block)


class EscapeIsNeverSentTests(unittest.TestCase):
    """카톡에서 Esc 는 대화방 창을 닫는다 — 다음 실행이 창을 못 찾게 된다."""

    def test_no_escape_key(self):
        for forbidden in ("{ESC}", "0x1B", "VK_ESCAPE"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, EXPORT)


class MenuIsNeverTouchedTests(unittest.TestCase):
    """'대화 내용' 바로 아래에 '채팅방 나가기' 가 있고, 그 하위에 '대화 내용 모두
    삭제' 가 있다. 메뉴를 지나가지 않는 것이 이 설계의 핵심이다.

    '메뉴를 안 쓴다'를 문자열 부재로 단정하려 했더니 두 번 헛짚었다 — 위험한 메뉴
    이름도, 쓰지 않기로 한 SendKeys 도 '왜 안 쓰는가'를 설명하는 주석에 들어 있다.
    부재가 아니라 존재로 계약을 적는다.
    """

    def test_shortcut_is_used_instead_of_menu(self):
        self.assertIn("public static void CtrlS()", EXPORT)

    def test_header_records_why_the_menu_is_avoided(self):
        # 이 설명이 사라지면 다음 사람이 '메뉴 클릭이 더 명확하다'며 되돌린다.
        for name in ("채팅방 나가기", "대화 내용 모두 삭제"):
            with self.subTest(name=name):
                self.assertIn(name, EXPORT)


if __name__ == "__main__":
    unittest.main()
