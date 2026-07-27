# -*- coding: utf-8 -*-
"""일일 갱신의 판단 신호 계약.

run_daily.ps1 은 자식 스크립트의 출력을 읽어 '발행할지'를 정한다. 예전에는 그
판단을 한국어 줄에서 읽었다 — `-match '요청 변경: 있음'`. Node 는 UTF-8 로 쓰는데
콘솔 코드페이지가 cp949 면 PowerShell 이 그 바이트를 cp949 로 읽어 글자가 깨지고,
깨진 글자는 절대 매칭되지 않는다. 그래서 조용한 날에 들어온 삭제 요청이 발행되지
않은 채 묻혔다(로그에 '요청 변경: 없음' 처럼 보였다).

지금은 ASCII 표식으로 주고받는다. 이 테스트는 그 약속이 양쪽에서 유지되는지 본다.
"""
from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parent.parent
DAILY = (ROOT / "scripts" / "run_daily.ps1").read_text(encoding="utf-8")
SYNC = (ROOT / "scripts" / "sync_member_requests.js").read_text(encoding="utf-8")
INGEST = (ROOT / "scripts" / "ingest_incremental.py").read_text(encoding="utf-8")


class SignalsAreAsciiTests(unittest.TestCase):
    def test_child_scripts_emit_ascii_markers(self):
        self.assertIn("REQUESTS_CHANGED=${changed ? 1 : 0}", SYNC)
        self.assertIn('print("NEW_MESSAGES=%d" % summary["added"])', INGEST)

    def test_runner_reads_those_markers(self):
        self.assertIn("REQUESTS_CHANGED=([01])", DAILY)
        self.assertIn("NEW_MESSAGES=(\\d+)", DAILY)

    def test_runner_no_longer_decides_on_korean_prose(self):
        """한국어 줄은 사람용으로 남기되, 판단에는 쓰지 않는다."""
        for fragile in ("요청 변경:\\s*있음", "신규\\s+(\\d+)건"):
            with self.subTest(fragile=fragile):
                self.assertNotIn("$l -match '%s'" % fragile, DAILY)

    def test_markers_survive_a_cp949_round_trip(self):
        """표식이 코드페이지를 건너가도 살아남는지 실제로 확인한다.

        한국어 줄은 이 왕복에서 깨진다 — 그게 바로 이 표식을 둔 이유다.
        """
        korean = "요청 변경: 있음"
        marker = "REQUESTS_CHANGED=1"
        for text, should_survive in ((marker, True), (korean, False)):
            with self.subTest(text=text):
                mangled = text.encode("utf-8").decode("cp949", errors="replace")
                self.assertEqual(should_survive, mangled == text)


class FailSafeDirectionTests(unittest.TestCase):
    """표식을 못 읽었을 때 어느 쪽으로 기우는지."""

    def test_missing_marker_publishes_instead_of_skipping(self):
        # 모를 때 '변경 없음' 으로 넘기면 요청이 묻히고 그 사실도 남지 않는다.
        # 불필요한 발행은 손해가 없지만, 삭제 요청을 못 지키는 건 되돌릴 수 없다.
        self.assertIn("$requestsChanged = $null", DAILY)
        block = DAILY[DAILY.index("REQUESTS_CHANGED 표식 없음"):]
        self.assertIn("$requestsChanged = $true", block[:400])

    def test_missing_marker_is_logged_loudly(self):
        # 조용히 넘어가면 다음에도 같은 일이 반복된다.
        #
        # 파일 전체의 WARN 개수를 세지 않는다. 무관한 경고(예: 갱신 잠금 충돌)가
        # 하나 늘 때마다 깨지는 반면, 정작 '표식 누락이 조용해지는' 변경은 다른
        # WARN 이 하나 늘어나 있으면 통과해 버린다. 두 블록을 직접 본다.
        self.assertIn("표식 없음", DAILY)
        for marker in ("REQUESTS_CHANGED 표식 없음", "NEW_MESSAGES 표식 없음"):
            with self.subTest(marker=marker):
                block = DAILY[DAILY.index(marker):][:400]
                self.assertEqual(2, block.count("'WARN'"))


class EncodingSetupTests(unittest.TestCase):
    def test_runner_pins_utf8_for_children(self):
        self.assertIn("[Console]::OutputEncoding = [System.Text.Encoding]::UTF8", DAILY)
        # 콘솔이 없는 환경(작업 스케줄러)에서는 설정이 실패할 수 있다 — 죽지 않아야 한다.
        self.assertRegex(DAILY, r"try \{ \[Console\]::OutputEncoding.*\} catch \{\}")

    def test_python_stdout_is_utf8_without_changing_file_defaults(self):
        # PYTHONIOENCODING 은 stdout 만 바꾼다. PYTHONUTF8 은 open() 기본값까지
        # 바꿔서 기존 파일 입출력 동작을 흔든다 — 그래서 쓰지 않는다.
        self.assertIn("$env:PYTHONIOENCODING = 'utf-8'", DAILY)
        # 설정하는 곳만 본다 — 왜 안 쓰는지는 주석에 적혀 있다.
        self.assertNotIn("$env:PYTHONUTF8", DAILY)

    def test_log_is_written_as_utf8(self):
        self.assertIn("Add-Content -Path $log -Value $line -Encoding utf8", DAILY)


class RunnerStillGuardsPublishingTests(unittest.TestCase):
    """인코딩을 고치면서 원래의 발행 조건이 흐트러지지 않았는지."""

    def test_quiet_day_with_no_requests_still_skips(self):
        self.assertIn("if ($added -eq 0 -and -not $requestsChanged) {", DAILY)

    def test_request_change_alone_is_a_reason_to_publish(self):
        # run_daily.ps1 머리말이 약속한 규칙이다.
        self.assertIn("새 메시지는 없지만 멤버 요청이 바뀌어 발행합니다.", DAILY)
        # 머리말이 같은 단계를 순서대로 나열하고 있어, 실제 호출부만 본다.
        body = DAILY[DAILY.index("$ErrorActionPreference"):]
        order = [body.index("Invoke-Step '%s'" % step) for step in (
            "멤버 요청 동기화", "증분 반영", "발행본 생성", "Firestore 적재"
        )]
        self.assertEqual(order, sorted(order))


class SingleRunLockTests(unittest.TestCase):
    """실행 경로가 둘이 됐다 — 23:40 스케줄러와 관리 탭의 '지금 갱신'.

    스케줄러의 IgnoreNew 는 자기 작업만 막으므로, 23:40 직전에 버튼을 누르면 둘이
    동시에 발행에 들어간다. 그래서 잠금은 run_daily.ps1 안에 있어야 한다.
    """

    def test_lock_is_an_exclusive_file_handle(self):
        # PID 파일이 아니라 핸들이어야 한다. 프로세스가 강제 종료돼도 OS 가 닫아
        # 잠금이 저절로 풀리므로, 찌꺼기 때문에 다음 갱신이 영영 막히지 않는다.
        self.assertIn("[System.IO.File]::Open($lockPath, 'OpenOrCreate', 'Write', 'None')",
                      DAILY)

    def test_contention_exits_with_a_distinct_code(self):
        # '실패' 와 '겹쳐서 안 함' 은 다르다. 부르는 쪽(refresh_watcher.js)이
        # 구분해야 화면에 엉뚱한 실패로 뜨지 않는다.
        block = DAILY[DAILY.index("$lockPath ="):]
        self.assertIn("exit 75", block[:900])

    def test_lock_is_taken_before_any_work(self):
        body = DAILY[DAILY.index("$ErrorActionPreference"):]
        lock = body.index("[System.IO.File]::Open($lockPath")
        for step in ("멤버 요청 동기화", "증분 반영", "발행본 생성", "Firestore 적재"):
            with self.subTest(step=step):
                self.assertLess(lock, body.index("Invoke-Step '%s'" % step))

    def test_watcher_agrees_on_the_code(self):
        watcher = (ROOT / "scripts" / "refresh_watcher.js").read_text(encoding="utf-8")
        self.assertIn("EXIT_ALREADY_RUNNING = 75", watcher)
        # 겹침은 실패가 아니라 skipped 로 보고해야 한다
        block = watcher[watcher.index("EXIT_ALREADY_RUNNING)"):][:600]
        self.assertIn('status: "skipped"', block)


if __name__ == "__main__":
    unittest.main()
