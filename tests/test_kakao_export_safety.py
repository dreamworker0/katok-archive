# -*- coding: utf-8 -*-
"""내보내기 스크립트의 안전장치 계약.

kakao_export.ps1 은 카톡 창에 키를 보낸다. 잘못된 창에 보내면 남의 파일을 저장하거나
(Ctrl+S) 더 나쁜 일을 할 수 있으므로, 안전장치는 리팩터링으로 조용히 사라져서는
안 되는 종류의 코드다. 여기서는 그 장치들이 제자리에 있는지만 본다.
"""
from __future__ import annotations

from pathlib import Path
import re
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
        # 이 가드가 지키는 것은 입력칸 클릭과 그 뒤의 Ctrl+S 다. 파일 앞쪽에 다른
        # 클릭(탭 전환)이 생겼으므로 '파일의 첫 MouseClick' 이 아니라 '이 가드 다음
        # 클릭' 을 본다 — 앞쪽 클릭은 EveryClickIsGuardedTests 가 따로 지킨다.
        self.assertLess(guard, EXPORT.index("[Win32]::MouseClick()", guard))
        self.assertLess(guard, EXPORT.index("[Win32]::CtrlS()"))

    def test_mismatch_aborts_instead_of_clicking_anyway(self):
        block = EXPORT[EXPORT.index("if ($pidAt -ne $kakaoPid) {"):][:700]
        self.assertIn("Stop-Safely", block)
        # 어느 창이 덮었는지 알려줘야 사람이 치울 수 있다
        self.assertIn("Get-Process -Id $pidAt", block)

    def test_guard_names_the_fix_in_the_message(self):
        block = EXPORT[EXPORT.index("if ($pidAt -ne $kakaoPid) {"):][:700]
        self.assertIn("항상 위", block)


class KeyGoesOnlyToARoomThatStillHasFocusTests(unittest.TestCase):
    """자리 확인은 한 번 하고 끝나는 검사가 아니다 (실측 2026-08-04).

    가드를 통과한 직후, 클릭과 Ctrl+S 사이의 짧은 틈에 클로드 데스크톱 알림 풍선이
    바로 입력칸 위에 떴다. 클릭은 풍선이 받고 포커스도 그쪽으로 넘어갔으므로
    Ctrl+S 는 카톡에 닿지 않았다. 로그에는 예전과 똑같이 '최상단 확보 확인' 다음
    '저장 대화상자가 뜨지 않았습니다' 만 남아, 원인은 남긴 화면을 열어야 보였다.
    """

    def _between_click_and_key(self):
        guard = EXPORT.index("$pidAt = [Win32]::PidAt($ix, $iy)")
        click = EXPORT.index("[Win32]::MouseClick()", guard)
        return EXPORT[click:EXPORT.index("[Win32]::CtrlS()")]

    def test_focus_is_rechecked_just_before_the_key(self):
        between = self._between_click_and_key()
        self.assertIn("[Win32]::GetForegroundWindow()", between)
        self.assertIn("[Win32]::PidAt($ix, $iy)", between)

    def test_interference_means_the_key_is_not_sent(self):
        between = self._between_click_and_key()
        self.assertIn("-ne $kakaoPid", between)
        # 물러나는 길이 있어야 한다 — 확인이 어긋난 채로 Ctrl+S 까지 흐르면 안 된다
        self.assertTrue(
            "continue" in between and "Stop-Safely" in between,
            "끼어든 창을 확인한 뒤 다시 시도하거나 중단하는 길이 없다",
        )

    def test_one_interruption_does_not_lose_the_day(self):
        """잠깐 뜬 풍선 때문에 그날 갱신을 통째로 버리지 않는다.

        방 창을 다시 잡는 것은 위험을 늘리지 않는다 — 시도마다 자리 확인을 처음부터
        다시 하므로, 카톡이 아닌 창에 키가 가는 경로는 그대로 막혀 있다.
        """
        self.assertRegex(EXPORT, r"for \(\$att = 1; \$att -le \$maxTry")
        # 시도마다 창 자리를 다시 읽는다 — 그 사이 창이 움직일 수 있다
        loop = EXPORT[EXPORT.index("for ($att = 1; $att -le $maxTry"):EXPORT.index("[Win32]::CtrlS()")]
        self.assertIn("$r = $win.Current.BoundingRectangle", loop)

    def test_retry_does_not_press_the_key_over_a_late_dialog(self):
        # 늦게 뜬 대화상자를 두고 Ctrl+S 를 또 보내면 대화상자가 두 개 열린다.
        block = EXPORT[EXPORT.index("$dlg = Wait-SaveDialog -TimeoutSec 20"):]
        block = block[:block.index("Stop-Safely")]
        self.assertIn("Wait-SaveDialog -TimeoutSec 3", block)

    def test_failure_log_names_who_was_in_front(self):
        # 남긴 화면(png)을 열어야 알 수 있던 것을 로그에도 적는다.
        self.assertIn("function Get-ScreenState", EXPORT)
        body = EXPORT[EXPORT.index("function Get-ScreenState"):]
        body = body[:body.index("\nfunction ", 1)]
        self.assertIn("[Win32]::GetForegroundWindow()", body)
        self.assertIn("[Win32]::PidAt($X, $Y)", body)


class EveryClickIsGuardedTests(unittest.TestCase):
    """좌표를 누르기 전에는 '그 자리에 보이는 창'이 카톡인지 먼저 묻는다.

    클릭 경로는 하나가 아니다 — 입력칸, 채팅 목록의 방 행, 왼쪽 탭 띠. 한 곳만
    이름으로 못박아 두면 새로 생긴 경로는 아무도 안 지킨다. 그래서 특정 위치가
    아니라 파일의 모든 클릭 호출을 훑는다.
    """

    def test_each_click_has_a_pid_check_just_above(self):
        clicks = list(re.finditer(r"\[Win32\]::Mouse(?:Double)?Click\(\)", EXPORT))
        self.assertGreaterEqual(len(clicks), 3, "클릭 경로를 못 찾았다 — 정규식을 확인할 것")
        for m in clicks:
            with self.subTest(at=EXPORT[:m.start()].count("\n") + 1):
                self.assertIn("[Win32]::PidAt(", EXPORT[max(0, m.start() - 900):m.start()])


class TabIsIdentifiedNotAssumedTests(unittest.TestCase):
    """채팅 목록을 클래스 이름만으로 고르면 친구 목록을 잡는다.

    실측 2026-08-02: 카톡이 '친구' 탭에 떠 있는 채로 밤 갱신이 돌았고, 같은
    클래스(EVA_VH_ListControl_Dblclk)인 친구 목록을 채팅 목록으로 잡아 사람
    이름을 훑다가 '최고 일치율 7%' 로 중단했다. 그날 대화가 통째로 빠졌다.
    """

    def test_list_is_chosen_by_control_name(self):
        self.assertIn("ChatRoomListCtrl", EXPORT)
        # 첫 번째 EVA_VH_ListControl_Dblclk 를 그냥 집는 구현으로 되돌아가지 않게
        self.assertNotIn("ClassName -eq 'EVA_VH_ListControl_Dblclk') { $list", EXPORT)

    def test_wrong_tab_is_recovered_not_just_reported(self):
        self.assertIn("function Select-ChatTab", EXPORT)
        body = EXPORT[EXPORT.index("$list = Get-ChatRoomList $main"):][:600]
        self.assertIn("Select-ChatTab", body)

    def test_tab_strip_geometry_is_measured_not_hardcoded(self):
        # 좌표를 박아 두면 배율·창 크기가 바뀌는 날 조용히 엉뚱한 곳을 누른다.
        body = EXPORT[EXPORT.index("function Select-ChatTab"):]
        body = body[:body.index("\nfunction ", 1)]
        self.assertIn("$Main.Current.BoundingRectangle", body)
        # 누른 뒤에는 반드시 '채팅 목록이 떴는지' 로 확인한다
        self.assertIn("Get-ChatRoomList $Main", body)

    def test_tab_search_stops_above_the_settings_icons(self):
        # 탭 띠 아래쪽에는 알림·설정이 있다. 끝까지 훑으면 설정 창을 연다.
        body = EXPORT[EXPORT.index("function Select-ChatTab"):]
        body = body[:body.index("\nfunction ", 1)]
        self.assertRegex(body, r"\$dy -le 3\d\d")


class RoomWindowIsOpenedSafelyTests(unittest.TestCase):
    """방 창이 없으면 직접 연다 (2026-07-28 밤 갱신이 이것 때문에 통째로 빠졌다).

    방을 여는 경로는 대화방을 다루므로 내보내기만큼 위험하다. 특히 '키를 보내지
    않는다' 는 리팩터링으로 조용히 되돌리기 쉬운 계약이다 — 검색창에 방 이름을
    타이핑하는 구현이 더 직관적으로 보이기 때문이다. 그 구현은 포커스가 대화방
    입력칸에 있으면 방 이름을 40명 방에 메시지로 전송한다.
    """

    def test_recovery_exists(self):
        self.assertIn("function Open-RoomWindow", EXPORT)
        self.assertIn("$win = Open-RoomWindow", EXPORT)

    def test_tray_icon_is_not_clicked(self):
        # 트레이 아이콘은 숨김 영역·아이콘 순서·배율에 따라 자리가 바뀐다.
        # 숨겨진 메인 창에 ShowWindow 를 부르는 것이 같은 일을 좌표 없이 한다.
        self.assertIn("public static IntPtr KakaoMain()", EXPORT)
        for forbidden in ("Shell_TrayWnd", "NotifyIconOverflowWindow", "TrayNotifyWnd"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, EXPORT)

    def test_no_enter_key_anywhere(self):
        # Enter 는 목록에서 동작하지 않았고(실측), 잘못 가면 메시지를 전송한다.
        for forbidden in ("0x0D", "{ENTER}", "VK_RETURN"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, EXPORT)

    def test_no_typing_into_kakao(self):
        """방 이름을 타이핑해 검색하는 구현을 막는다.

        문자열 부재로 쓰면 헛짚는다 — 'SendKeys 를 쓰지 않는 이유' 를 적은 주석에도
        그 이름이 들어 있다(이 파일 MenuIsNeverTouchedTests 의 교훈과 같다).
        그래서 '방을 여는 함수 본문에 키를 보내는 호출이 없다' 로 좁혀서 적는다.
        """
        body = EXPORT[EXPORT.index("function Open-RoomWindow"):]
        end = body.index("\nfunction ", 1)
        body = body[:end]
        for call in ("keybd_event", "SendKeys", "CtrlS()", "Set-Clipboard", "SendWait"):
            with self.subTest(call=call):
                self.assertNotIn(call, body)
        # 그리고 왜 그런지가 남아 있어야 한다 — 사라지면 다음 사람이 타이핑으로 되돌린다.
        self.assertIn("메시지로 전송", EXPORT)

    def test_row_is_chosen_by_reading_the_screen(self):
        # 채팅 목록은 접근성 API 에 항목이 0개다. 몇 번째 행인지 추정해 클릭하면
        # 엉뚱한 방을 연다 — 클릭할 행의 글자를 먼저 읽는다.
        self.assertIn("kakao_ocr.ps1", EXPORT)
        self.assertIn("function Get-RowMatchScore", EXPORT)

    def test_row_click_is_guarded_by_pid_check(self):
        self.assertIn("$pidAtRow = [Win32]::PidAt($cx, $cy)", EXPORT)
        guard = EXPORT.index("$pidAtRow = [Win32]::PidAt($cx, $cy)")
        self.assertLess(guard, EXPORT.index("[Win32]::MouseDoubleClick()"))

    def test_success_is_decided_by_the_window_title(self):
        # OCR 은 글자를 틀린다(실측: '바이브코딩' -> '바이브코팅'). 근사 일치로 고른 뒤
        # 제목이 정확히 같은 창이 떴는지로만 성공을 판정해야 Ctrl+S 가 남의 방에 가지 않는다.
        block = EXPORT[EXPORT.index("[Win32]::MouseDoubleClick()"):][:900]
        self.assertIn("Get-RoomWindow", block)

    def test_scroll_does_not_move_the_real_cursor(self):
        # 실제 휠 입력은 이 컨트롤에서 무시된다(실측). 컨트롤에 WM_MOUSEWHEEL 을
        # 직접 보내므로 스크롤이 다른 창에 닿을 수 없다.
        self.assertIn("0x020A", EXPORT)
        self.assertNotIn("mouse_event(0x0800", EXPORT)

    def test_failure_still_aborts_with_a_screenshot(self):
        # 복구가 실패하면 예전 동작으로 돌아가야 한다 — 나빠지는 경우를 만들지 않는다.
        block = EXPORT[EXPORT.index("$win = Open-RoomWindow"):][:900]
        self.assertIn("Stop-Safely", block)


class LoggingNeverAbortsTheRunTests(unittest.TestCase):
    """진단을 남기려고 둔 코드가 실행을 멈춰서는 안 된다.

    실측 2026-07-27: 진행 상황을 보려고 로그를 `tail -f` 로 열어둔 것만으로 내보내기가
    첫 줄에서 죽었다. $ErrorActionPreference = 'Stop' 이라 Add-Content 실패가
    스크립트를 그 자리에서 끝냈다. 백신·백업·편집기도 같은 잠금을 만든다.
    """

    DAILY = (ROOT / "scripts" / "run_daily.ps1").read_text(encoding="utf-8")

    def test_export_log_write_is_guarded(self):
        block = EXPORT[EXPORT.index("function Write-Log"):][:1600]
        self.assertIn("try {", block)
        self.assertIn("Add-Content -Path $script:LogFile", block)
        self.assertIn("} catch {", block)

    def test_daily_log_write_is_guarded(self):
        block = self.DAILY[self.DAILY.index("function Say"):][:1200]
        self.assertIn("try { Add-Content -Path $log", block)
        self.assertIn("catch {", block)

    def test_failure_is_surfaced_on_screen_not_swallowed(self):
        # 조용히 삼키면 왜 로그가 비었는지 알 수 없다.
        for text in (EXPORT, self.DAILY):
            with self.subTest():
                self.assertIn("로그 파일이 잠겨 있어 화면에만 남깁니다", text)

    def test_warning_is_printed_once_not_per_line(self):
        # 줄마다 경고하면 로그가 두 배로 늘고 정작 읽을 것이 묻힌다.
        for text in (EXPORT, self.DAILY):
            with self.subTest():
                self.assertIn("$script:LogWriteWarned", text)


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


class DiagnosticsNeverStopTheRunTests(unittest.TestCase):
    """진단 문구 때문에 그날 수집이 멈추면 안 된다.

    실측 2026-08-12 10:59 — 창 좌표를 찍는 **로그 한 줄**에서 죽었다.

        Cannot convert value "∞" to type "System.Int32"
        at kakao_export.ps1:688  [int]$r.X
        ERROR 카카오톡 대화 내보내기 실패 (exit 1) — 중단합니다.

    UIAutomation 의 BoundingRectangle 은 창이 최소화·숨김이면 좌표를 무한대로
    돌려주고, `[int]∞` 는 형변환 오류다. 11:01 재실행으로 살아났지만 밤 자동
    실행이었다면 그날이 빈다(2026-08-02 에 실제로 그렇게 하루가 빠졌다).

    형변환을 손으로 검증한 결과(PowerShell 5.1): `[int]∞` 는 RuntimeException,
    `Format-Coord ∞` 는 '?', `Test-UsableRect` 는 무한대·0크기·null 에 모두 False.
    여기서는 그 장치가 제자리에 있는지만 본다.
    """

    def test_safe_helpers_exist(self):
        self.assertIn("function Format-Coord", EXPORT)
        self.assertIn("function Test-UsableRect", EXPORT)

    def test_infinity_and_nan_are_handled_not_cast(self):
        for guard in ("[double]::IsNaN", "[double]::IsInfinity"):
            with self.subTest(guard=guard):
                self.assertIn(guard, EXPORT)

    def test_every_rect_cast_is_behind_a_guard(self):
        """좌표를 정수로 바꾸는 자리마다 그 앞에 `Test-UsableRect` 가 있어야 한다.

        '쓰지 마라' 가 아니라 '가드 뒤에서' 가 계약이다 — 좌표는 결국 정수로
        바꿔야 스크롤·클릭에 쓸 수 있고, 무한대만 걸러내면 된다. 이 시험을
        '맨 형변환 금지' 로 적었을 때 목록 좌표(`$lr`)에서 실제로 같은 사고 자리
        세 곳이 걸렸다(2026-08-12) — 규칙이 자리를 찾아 준 셈이다.

        주석 줄은 뺀다. 왜 이렇게 하는지 설명하는 주석에 그 꼴이 들어 있다.
        """
        code = "\n".join(l for l in EXPORT.splitlines()
                         if not l.lstrip().startswith("#"))
        for m in re.finditer(r"\[int\]\$(\w+)\.(?:X|Y|Width|Height)\b", code):
            var, at = m.group(1), m.start()
            guard = code.find("Test-UsableRect $%s" % var)
            with self.subTest(cast=m.group(0)):
                self.assertNotEqual(-1, guard,
                                    "$%s 에 Test-UsableRect 가 없다" % var)
                self.assertLess(guard, at, "가드가 형변환보다 앞에 있어야 한다")

    def test_coordinates_are_converted_once_per_rect(self):
        """같은 좌표를 여러 자리에서 각각 바꾸지 않는다.

        예전에는 `[int]$lr.X` 가 OCR 호출 세 곳에 흩어져 있었다. 그 꼴이 남아
        있으면 다음 사람이 가드 없는 자리에 같은 것을 또 쓴다.
        """
        code = "\n".join(l for l in EXPORT.splitlines()
                         if not l.lstrip().startswith("#"))
        for var in set(re.findall(r"\[int\]\$(\w+)\.(?:X|Y|Width|Height)\b", code)):
            n = len(re.findall(r"\[int\]\$%s\.X\b" % var, code))
            with self.subTest(var=var):
                self.assertLessEqual(n, 1, "$%s.X 를 %d 군데서 바꾼다" % (var, n))

    def test_the_window_log_line_uses_the_safe_formatter(self):
        line = next(l for l in EXPORT.splitlines() if "창 확인:" in l)
        self.assertIn("{0}", line, "좌표를 직접 끼워 넣지 말고 서식으로 넘긴다")
        self.assertNotIn("[int]", line)

    def test_the_click_coordinates_are_guarded_before_use(self):
        # 좌표로 계산하기 전에 쓸 수 있는 값인지 먼저 묻는다.
        guard = EXPORT.index("Test-UsableRect $r")
        use = EXPORT.index("$ix = [int]($r.X + 60)")
        self.assertLess(guard, use, "가드가 계산보다 앞에 있어야 한다")

    def test_an_unusable_rect_stops_with_a_readable_reason(self):
        # 형변환 오류가 아니라 사람이 읽을 문장으로 멈춘다.
        self.assertIn("좌표를 읽을 수 없습니다", EXPORT)


if __name__ == "__main__":
    unittest.main()
