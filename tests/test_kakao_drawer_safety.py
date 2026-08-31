# -*- coding: utf-8 -*-
"""서랍 스크립트의 안전장치 계약.

kakao_drawer.ps1 은 두 가지 위험한 일을 한다. 서랍 창의 좌표를 누르고, 서랍이
닫혀 있으면 **방 창에 단축키를 보낸다**. 어느 쪽도 엉뚱한 창에 가면 안 된다 —
덮은 창이 편집기라면 단축키가 남의 파일에 가고, 커서가 다른 앱 위에 있으면
클릭이 그리로 간다(실측 2026-08-20, 2026-08-25).

그리고 이 스크립트가 **절대 하지 않기로 한 일**이 있다. 방 창 ☰ 메뉴를 열지
않는 것이다. 그 메뉴에는 '채팅방 나가기' 가 있다. 46명짜리 방을 잘못 나가면
되돌릴 수 없다.

안전장치는 리팩터링으로 조용히 사라져서는 안 되는 종류의 코드다. 여기서는 그
장치들이 제자리에 있는지만 본다 — 창을 띄우지 않으므로 CI 에서 돈다.
"""
from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent.parent
DRAWER = (ROOT / "scripts" / "kakao_drawer.ps1").read_text(encoding="utf-8")


def open_drawer_body() -> str:
    """Open-DrawerWindow 함수 본문만 잘라 낸다."""
    start = DRAWER.index("function Open-DrawerWindow")
    end = DRAWER.index("\nfunction ", start + 1)
    return DRAWER[start:end]


class KeyGoesOnlyToTheRoomTests(unittest.TestCase):
    """Ctrl+J 는 방 창에만 가야 한다.

    kakao_export.ps1 이 Ctrl+S 로 배운 것과 같다(실측 2026-07-27): 포그라운드
    확인만으로는 부족하다. 작업 관리자처럼 '항상 위' 로 뜬 창은 카톡이
    포그라운드여도 그 위에 그려지고, 그 자리를 누르면 포커스가 그리로 넘어간다.
    """

    def test_pid_at_helper_exists(self):
        self.assertIn("static extern IntPtr WindowFromPoint(POINT p)", DRAWER)
        self.assertIn("public static uint PidAt(int x, int y)", DRAWER)

    def test_click_is_guarded_by_pid_check(self):
        self.assertIn("$pidAt = [DW]::PidAt($ix, $iy)", DRAWER)
        self.assertIn("if ($pidAt -ne $kpid) {", DRAWER)

    def test_guard_runs_before_the_click_and_before_the_key(self):
        guard = DRAWER.index("$pidAt = [DW]::PidAt($ix, $iy)")
        self.assertLess(guard, DRAWER.index("[DW]::mouse_event([DW]::LEFTDOWN", guard))
        self.assertLess(guard, DRAWER.index("[DW]::SendCtrlJ()"))

    def test_mismatch_gives_up_instead_of_clicking_anyway(self):
        block = DRAWER[DRAWER.index("if ($pidAt -ne $kpid) {"):][:700]
        self.assertIn("return [IntPtr]::Zero", block)
        # 어느 창이 덮었는지 알려줘야 사람이 치울 수 있다
        self.assertIn("Get-Process -Id $pidAt", block)

    def test_foreground_is_secured_before_the_key(self):
        body = open_drawer_body()
        front = body.index("[DW]::ForceForeground($room)")
        self.assertLess(front, body.index("[DW]::SendCtrlJ()"))

    def test_failed_foreground_means_the_key_is_not_sent(self):
        body = open_drawer_body()
        block = body[body.index("if (-not $front) {"):][:600]
        self.assertIn("return [IntPtr]::Zero", block)
        # 앞에 무엇이 있었는지 남겨야 원인이 보인다
        self.assertIn("Describe", block)


class MenuIsNeverOpenedTests(unittest.TestCase):
    """☰ 메뉴에는 '채팅방 나가기' 가 있다. 열지 않는 것이 이 설계의 핵심이다.

    실측 2026-08-25: 그 메뉴에서 '채팅방 서랍' 은 y=277, '채팅방 나가기' 는
    y=544 였다. 267px 떨어져 있어 붙어 있지는 않지만, 카톡이 항목 하나만 끼워
    넣어도 좌표가 밀린다. 마침 하위 메뉴에 Ctrl+J 가 있어 메뉴를 아예 건너뛴다.
    """

    def test_shortcut_is_used_instead_of_the_menu(self):
        self.assertIn("public static void SendCtrlJ()", DRAWER)

    def test_the_menu_window_is_never_handled(self):
        # 메뉴 창 클래스를 다루기 시작하면 그 길로 되돌아간 것이다.
        self.assertNotIn("EVA_Menu", DRAWER)

    def test_header_records_why_the_menu_is_avoided(self):
        # 이 설명이 사라지면 다음 사람이 '메뉴 클릭이 더 명확하다'며 되돌린다.
        for name in ("채팅방 나가기", "대화 내용 모두 삭제"):
            with self.subTest(name=name):
                self.assertIn(name, DRAWER)


class EscapeIsNeverSentTests(unittest.TestCase):
    """카톡에서 Esc 는 '취소' 가 아니라 '창 닫기' 다.

    실측 2026-08-25: 메뉴를 닫으려고 Esc 를 두 번 보냈더니 첫 번째가 메뉴를,
    두 번째가 **방 창을** 닫았다. 방 창이 사라지면 다음 실행이 Ctrl+J 를 보낼
    곳을 잃는다. 닫을 것이 있으면 그 창에 WM_CLOSE 를 보낸다.
    """

    def test_no_escape_key(self):
        for forbidden in ("{ESC}", "0x1B", "VK_ESCAPE"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, DRAWER)


class NothingIsTypedIntoTheRoomTests(unittest.TestCase):
    """방 창에 보내는 것은 입력칸 클릭 한 번과 Ctrl+J 뿐이다.

    포커스가 메시지 입력칸에 있으므로, 글자를 보내면 그것이 46명에게 전송된다.
    되돌릴 수 없는 사고다.
    """

    def test_no_enter_key(self):
        for forbidden in ("0x0D", "{ENTER}", "VK_RETURN"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, DRAWER)

    def test_the_only_key_call_in_the_open_path_is_ctrl_j(self):
        body = open_drawer_body()
        for call in ("SendKeys", "Set-Clipboard", "SendWait", "keybd_event"):
            with self.subTest(call=call):
                self.assertNotIn(call, body)
        self.assertIn("[DW]::SendCtrlJ()", body)

    def test_the_reason_survives(self):
        self.assertIn("Enter 도,", DRAWER)


class OpeningIsDecidedByTheWindowTitleTests(unittest.TestCase):
    """'키를 보냈으니 열렸겠지' 로 넘어가면 안 된다 — 제목으로 확인한다."""

    def test_success_needs_the_window(self):
        body = open_drawer_body()
        after_key = body[body.index("[DW]::SendCtrlJ()"):]
        self.assertIn("[DW]::ByTitle($DrawerTitle)", after_key)

    def test_timeout_is_a_warning_not_a_lie(self):
        body = open_drawer_body()
        self.assertIn("서랍 창이 뜨지 않았습니다", body)


class EveryDrawerClickIsGuardedTests(unittest.TestCase):
    """서랍 안의 클릭은 그 픽셀이 서랍 소속일 때만 나간다.

    실측 2026-08-25: 콘솔 창이 서랍을 덮은 채로 돌았고, 이 가드가 카드 5개를
    누르지 않고 넘겼다. 가드가 없었다면 그 클릭들은 콘솔로 갔다.
    """

    def test_click_checks_the_owning_window(self):
        block = DRAWER[DRAWER.index("function Invoke-Click"):][:1600]
        self.assertIn("[DW]::WindowFromPoint($pt)", block)
        self.assertIn("[DW]::GetAncestor($at, [DW]::GA_ROOT) -ne $drawer", block)
        self.assertIn("누르지 않습니다", block)


class TheRoomIsCheckedBeforeAnythingIsReadTests(unittest.TestCase):
    """어느 방의 서랍인지 먼저 확인한다.

    서랍 창은 방마다 따로 열리지 않는다 — 하나의 창이 왼쪽 목록에서 고른 방을
    비출 뿐이다. 그래서 사람이 다른 방을 한 번 눌러 두면 그 뒤로는 매일 밤 남의
    방을 훑는다. 실측 2026-08-29~31: '제6선교회' 가 골라져 있어 사흘 내리 두 탭
    모두 카드 0개를 읽고 '정상 종료' 로 끝냈다. 로그도 화면도 조용했고 첨부는
    14일 시계를 그냥 태웠다.

    이 스크립트가 여태 확인하지 않던 단 하나의 전제였다.
    """

    RUN = (ROOT / "scripts" / "run_daily.ps1").read_text(encoding="utf-8")

    def test_the_check_runs_before_the_tabs(self):
        check = DRAWER.index("Assert-DrawerRoom)")
        tabs = DRAWER.index("foreach ($tab in @(")
        self.assertLess(check, tabs, "탭을 훑기 전에 방을 확인해야 한다")

    def test_a_wrong_room_stops_the_run(self):
        body = DRAWER[DRAWER.index("if (-not (Assert-DrawerRoom))"):]
        body = body[:body.index("$totalClicked")]
        self.assertIn("exit 4", body)
        self.assertIn("Restore-Window", body)   # 창을 옮겨 둔 채로 끝내지 않는다

    def test_it_tries_to_fix_itself_before_giving_up(self):
        # 밤 자동 실행이다. 사람이 알아채기를 기다리는 동안에도 14일 시계는 돈다.
        body = DRAWER[DRAWER.index("function Assert-DrawerRoom"):]
        body = body[:body.index(chr(10) + "}")]
        self.assertIn("Select-DrawerRoom", body)
        self.assertEqual(2, body.count("Get-DrawerRoomName"),
                         "고르기 전후로 두 번 읽어야 바로잡혔는지 알 수 있다")

    def test_choosing_a_room_is_the_only_thing_clicked_in_the_list(self):
        body = DRAWER[DRAWER.index("function Select-DrawerRoom"):]
        body = body[:body.index(chr(10) + "}")]
        self.assertIn("Invoke-Click $LIST_CLICK_X", body)
        # 목록 클릭도 다른 클릭과 같은 안전장치를 지난다(그 픽셀이 서랍 소속인가)
        self.assertNotIn("mouse_event", body)

    def test_an_empty_sweep_is_not_reported_as_success(self):
        # 서랍은 지난 것을 계속 보여준다. 두 탭 모두 0개면 '오늘 새 첨부가 없다' 가
        # 아니라 잘못 보고 있다는 뜻이다. OCR 이 없는 PC 에서는 이 그물만 남는다.
        body = DRAWER[DRAWER.index("if ($totalCards -eq 0)"):]
        self.assertIn("exit 5", body[:600])
        self.assertLess(DRAWER.index("$totalCards += "), DRAWER.index("if ($totalCards -eq 0)"))

    def test_missing_ocr_does_not_block_collection(self):
        # OCR 이 없다고 그날 수집을 통째로 버리면 손해가 더 크다 — 카드 수 그물이 남는다.
        body = DRAWER[DRAWER.index("function Assert-DrawerRoom"):]
        body = body[:body.index(chr(10) + "}")]
        head = body[:body.index("Get-DrawerRoomName")]
        self.assertIn("OcrReady", head)
        self.assertIn("return $true", head)

    def test_the_daily_run_tells_the_screen_which_way_it_failed(self):
        # 로그에만 남으면 아무도 모른다 — 그것이 이 사고의 본체였다.
        self.assertIn("$drawerExit -eq 4", self.RUN)
        self.assertIn("$drawerExit -eq 5", self.RUN)
        block = self.RUN[self.RUN.index("$drawerExit -eq 4"):]
        self.assertIn("drawerWarn", block[:900])

    def test_a_trailing_chevron_does_not_look_like_another_room(self):
        # 머리글은 이름 뒤 화살표 단추까지 함께 읽힌다('새벽기도팀 ?되').
        # 기대한 이름으로 시작하면 같은 방이고, 여기에는 길이 문턱을 두지 않는다.
        body = DRAWER[DRAWER.index("function Test-SameRoom"):]
        body = body[:body.index(chr(10) + "}")]
        line = next(l for l in body.splitlines() if "$a.StartsWith($b)" in l)
        self.assertNotIn("-ge 6", line, "짧은 방 이름('새벽기도팀')을 못 알아본다")


class TheOldBehaviourStaysReachableTests(unittest.TestCase):
    """자동으로 여는 것이 말썽이면 끌 수 있어야 한다."""

    def test_no_auto_open_switch_exists(self):
        self.assertIn("[switch]$NoAutoOpen", DRAWER)
        self.assertIn("-not $NoAutoOpen", DRAWER)


if __name__ == "__main__":
    unittest.main()
