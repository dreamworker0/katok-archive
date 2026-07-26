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
        self.assertEqual(4, DAILY.count("'WARN'"))
        self.assertIn("표식 없음", DAILY)


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


if __name__ == "__main__":
    unittest.main()
