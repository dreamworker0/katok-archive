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


class UnsortedIsCountedNotAssumedTests(unittest.TestCase):
    """'미분류가 생겼습니다' 는 세어 보고 말해야 한다.

    사람이 주 1회 재분류하던 시절에는 새 메시지가 있으면 곧 미분류였다. 5단계(주제
    분류)가 파이프라인에 들어온 뒤로는 아니다 — 실측 2026-08-04: 새 글 23건이 그 자리
    에서 네 주제로 분류됐는데도 이 줄이 찍혔다. 매일 없는 일을 찾게 만드는 줄은
    진짜 경고까지 같이 흘려보게 한다.
    """

    COUNT = (ROOT / "scripts" / "count_unsorted.py").read_text(encoding="utf-8")

    def test_counter_emits_an_ascii_marker(self):
        self.assertIn('print("UNSORTED=%d" % len(unsorted_threads))', self.COUNT)

    def test_marker_is_printed_on_both_paths(self):
        # 0개인 날에 표식이 없으면 부르는 쪽은 '못 읽었다' 와 구분할 수 없다.
        body = self.COUNT[self.COUNT.index("def main("):]
        self.assertEqual(1, body.count('print("UNSORTED='),
                         "표식은 분기마다가 아니라 한 곳에서 한 번만 낸다")
        self.assertLess(body.index("미분류 스레드 없음"), body.index('print("UNSORTED='))

    def test_runner_reads_the_marker(self):
        self.assertIn("UNSORTED=(\\d+)", DAILY)

    def test_runner_no_longer_warns_just_because_there_are_new_messages(self):
        idx = DAILY.index("'미분류' 스레드")
        block = DAILY[DAILY.index("$unsorted = $null"):idx]
        self.assertIn("$unsorted -gt 0", block)
        self.assertNotIn("if ($added -gt 0) {\n    Say \"주제 분류가 필요한", DAILY)

    def test_the_check_cannot_break_a_finished_update(self):
        # 적재가 끝난 뒤의 확인이다. Invoke-Step(실패하면 exit)을 쓰면 안 되고,
        # 파이썬이 stderr 에 한 줄 쓰는 것으로 죽어서도 안 된다.
        for line in DAILY.splitlines():
            if "scripts.count_unsorted" in line:
                self.assertNotIn("Invoke-Step", line)
        idx = DAILY.index("scripts.count_unsorted")
        block = DAILY[idx - 400:idx + 200]
        self.assertIn("$ErrorActionPreference = 'Continue'", block)
        self.assertIn("finally { $ErrorActionPreference = $prevEap }", block)
        body = DAILY[DAILY.index("$ErrorActionPreference"):]
        self.assertLess(body.index("Invoke-Step 'Firestore 적재'"),
                        body.index("scripts.count_unsorted"))


class ButtonPathSaysWhatActuallyHappenedTests(unittest.TestCase):
    """'지금 갱신' 버튼이 끝난 뒤 화면에 남기는 말도 세어 보고 해야 한다.

    로그 줄은 2026-08-04 에 고쳤는데(위 클래스) 버튼 경로는 옛 문장을 그대로
    들고 있었다 — 새 글이 있으면 무조건 "주제 분류는 '미분류'로 들어갑니다".
    실측 2026-08-31: 새 글 14건이 그 자리에서 전부 분류됐고 미분류는 0개인데도
    그 문장이 떴다. 화면이 시키는 대로 미분류를 찾으러 가면 아무것도 없다.
    """

    WATCHER = (ROOT / "scripts" / "refresh_watcher.js").read_text(encoding="utf-8")
    # 관리 탭 카드는 web/admin.js 에 있다(2026-09-02 분리). 둘을 이어 읽는다.
    APP = ((ROOT / "web" / "app.js").read_text(encoding="utf-8")
           + (ROOT / "web" / "admin.js").read_text(encoding="utf-8"))

    def test_runner_emits_the_unsorted_marker_even_when_zero(self):
        # 0 과 '못 읽었다' 를 구분할 수 있어야 부르는 쪽이 말을 고를 수 있다.
        block = DAILY[DAILY.index("$unsorted = $null"):]
        marker = block.index('Say "    UNSORTED=$unsorted"')
        guard = block.index("if ($unsorted -gt 0) {")
        self.assertLess(marker, guard, "표식은 남아 있을 때만이 아니라 언제나 낸다")

    def test_watcher_reads_both_numbers(self):
        self.assertIn("CLASSIFIED=(\\d+)", self.WATCHER)
        self.assertIn("UNSORTED=(\\d+)", self.WATCHER)

    def done_message_body(self) -> str:
        """화면에 남길 말을 짓는 함수의 **본문**만. 주석은 뺀다 — 옛 문장을
        '이제 이렇게 말하지 않는다' 고 적어 두는 것은 코드가 아니다."""
        body = self.WATCHER[self.WATCHER.index("function doneMessage("):]
        return body[:body.index(chr(10) + "}")]

    def test_watcher_no_longer_asserts_unsorted(self):
        self.assertNotIn("주제 분류는 '미분류'로 들어갑니다", self.done_message_body())

    def test_watcher_stays_silent_about_numbers_it_could_not_read(self):
        body = self.done_message_body()
        # 못 읽으면 null 이다. `> 0` 은 null 에서 거짓이므로 아무 말도 하지 않는다 —
        # 모르는 것을 '0 건' 이나 '남았다' 로 지어내면 화면이 다시 거짓말을 한다.
        self.assertIn("classified > 0", body)
        self.assertIn("unsorted > 0", body)

    def test_card_no_longer_says_a_human_must_classify(self):
        idx = self.APP.index("카톡에서 대화를 내보내 새 글")
        blurb = self.APP[idx:idx + 400]
        self.assertNotIn("사람이 정리해야", blurb)


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
    """발행 조건이 흐트러지지 않았는지.

    발행 사유는 넷이다: 새 메시지 · 멤버 요청 변경 · 주제 분류 변경 ·
    발행본이 로컬보다 뒤처짐. 조용한 날에만 건너뛴다.
    """

    def test_truly_quiet_day_still_skips(self):
        self.assertIn(
            "if ($added -eq 0 -and -not $requestsChanged -and $classified -eq 0 "
            "-and -not $stale) {",
            DAILY)

    def test_request_change_alone_is_a_reason_to_publish(self):
        # run_daily.ps1 머리말이 약속한 규칙이다.
        self.assertIn("새 메시지는 없지만 멤버 요청 변경 또는 주제 분류가 있어 발행합니다.",
                      DAILY)
        # 머리말이 같은 단계를 순서대로 나열하고 있어, 실제 호출부만 본다.
        body = DAILY[DAILY.index("$ErrorActionPreference"):]
        order = [body.index("Invoke-Step '%s'" % step) for step in (
            "멤버 요청 동기화", "증분 반영", "발행본 생성", "Firestore 적재"
        )]
        self.assertEqual(order, sorted(order))

    def test_classification_alone_is_a_reason_to_publish(self):
        # 새 메시지가 없는 날에 미분류를 정리해 놓고 발행을 건너뛰면, 로컬은
        # 정리됐는데 화면은 그대로 '미분류'로 남는다 — 화면이 거짓말을 한다.
        self.assertIn("$classified -eq 0", DAILY)
        body = DAILY[DAILY.index("$ErrorActionPreference"):]
        self.assertLess(body.index("CLASSIFIED=(\\d+)"),
                        body.index("$classified -eq 0"))

    def test_unreadable_classification_marker_leans_to_publishing(self):
        # 모를 때는 발행하는 쪽으로 기운다. 불필요한 발행은 손해가 없다.
        self.assertIn("$classified = 1", DAILY)


class StaleProductionIsAReasonToPublishTests(unittest.TestCase):
    """지난 실행이 남긴 빚도 발행 사유다.

    앞의 사유 셋은 모두 '이번 실행에서 새로 생긴 것' 을 본다. 실측 2026-07-30:
    23:40 갱신이 새 글 34건을 원장에 넣고 테스트 단계에서 멈춰 적재까지 못 갔고,
    다음 날 '지금 갱신' 을 눌러도 증분이 0건이라 화면에는 "갱신을 마쳤습니다" 만
    뜨고 타임라인은 그대로였다. 버튼을 몇 번 눌러도 결과가 같았다.
    """

    def test_checker_emits_an_ascii_marker(self):
        src = (ROOT / "scripts" / "publish_state.py").read_text(encoding="utf-8")
        self.assertIn('print("PUBLISH_STALE=%d"', src)

    def test_runner_reads_that_marker(self):
        self.assertIn("PUBLISH_STALE=([01])", DAILY)

    def test_stale_alone_is_a_reason_to_publish(self):
        self.assertIn("새 메시지는 없지만 발행본이 로컬보다 뒤처져 있어 발행합니다.",
                      DAILY)

    def test_unreadable_marker_leans_to_publishing(self):
        # 모를 때는 발행하는 쪽으로 기운다. 적재는 달라진 문서만 쓰므로(해시 비교)
        # 헛발행은 거의 무료지만, 올릴 것을 안 올리면 화면이 거짓말을 한다.
        block = DAILY[DAILY.index("발행본이 최신인지 확인하지 못했습니다"):][:300]
        self.assertIn("'WARN'", block)
        self.assertIn("$stale = $true", block)

    def test_the_check_is_not_fatal(self):
        # 이 확인이 실패해도 갱신은 굴러가야 한다 — 발행을 돕는 검사가 발행을
        # 막아서는 안 된다.
        # Invoke-Step 은 실패하면 exit 한다. 이 확인에 그것을 쓰면 안 된다.
        for line in DAILY.splitlines():
            if "scripts.publish_state" in line:
                self.assertNotIn("Invoke-Step", line)
        idx = DAILY.index("scripts.publish_state")
        block = DAILY[idx - 400:idx + 200]
        self.assertIn("$ErrorActionPreference = 'Continue'", block)
        self.assertIn("finally { $ErrorActionPreference = $prevEap }", block)

    def test_the_check_runs_after_classification_and_before_the_decision(self):
        # 분류가 topics.json·보고서를 고치므로, 뒤처짐 판정은 그 뒤여야 한다.
        body = DAILY[DAILY.index("$ErrorActionPreference"):]
        self.assertLess(body.index("scripts.classify_unsorted"),
                        body.index("scripts.publish_state"))
        self.assertLess(body.index("scripts.publish_state"),
                        body.index("-and -not $stale"))


class ClassificationIsNonFatalTests(unittest.TestCase):
    """분류는 파이프라인에서 유일하게 LLM 을 쓰는 칸이고, 유일하게 실패가 허용되는
    칸이다. LLM 장애 때문에 그날 타임라인·통계·삭제 요청 반영이 통째로 날아가서는
    안 된다."""

    def test_classification_does_not_use_the_fatal_step_runner(self):
        # Invoke-Step 은 실패하면 exit 한다. 분류에 그것을 쓰면 안 된다.
        self.assertNotIn("Invoke-Step '주제 분류", DAILY)
        self.assertIn("python -m scripts.classify_unsorted", DAILY)

    def test_classification_failure_warns_and_continues(self):
        idx = DAILY.index("주제 분류가 실패했습니다")
        block = DAILY[idx - 200:idx + 300]
        self.assertIn("'WARN'", block)
        # exit **문장**이 없어야 한다. 로그 문구 안의 '(exit $classifyCode)' 는
        # 문장이 아니라 사람에게 보여주는 값이므로 세면 안 된다.
        for line in block.splitlines():
            with self.subTest(line=line):
                self.assertFalse(line.strip().startswith("exit "))

    def test_classification_runs_before_publishing(self):
        body = DAILY[DAILY.index("$ErrorActionPreference"):]
        self.assertLess(body.index("scripts.classify_unsorted"),
                        body.index("Invoke-Step '발행본 생성'"))

    def test_classification_stderr_is_not_promoted_to_an_error(self):
        # Invoke-Step 과 같은 함정이다 — 파이썬이 stderr 에 한 줄 쓰면 'Stop' 이
        # 여기서 갱신을 죽인다.
        idx = DAILY.index("scripts.classify_unsorted")
        block = DAILY[idx - 400:idx + 200]
        self.assertIn("$ErrorActionPreference = 'Continue'", block)
        self.assertIn("finally { $ErrorActionPreference = $prevEap }", block)


class NativeStderrIsNotAnErrorTests(unittest.TestCase):
    """성공한 명령이 스크립트를 죽이지 못하게 한다.

    PowerShell 5.1 에서 `& $body 2>&1` 은 네이티브 exe 의 stderr 한 줄마다
    NativeCommandError 를 만들고, $ErrorActionPreference = 'Stop' 이면 그것이 종료
    오류가 된다. `python -m unittest` 는 진행 표시와 'OK' 를 모두 stderr 로 쓴다.

    실측 2026-07-27: 237개가 전부 통과했는데 갱신이 '테스트' 단계에서 죽었고 로그에는
    단계 제목만 남았다. 앞선 이틀은 새 메시지가 0건이라 발행 전에 끝나서 이 단계가
    한 번도 돌지 않았고, 그래서 잠재 버그로 남아 있었다.
    """

    def test_step_runner_neutralizes_stop_around_native_calls(self):
        block = DAILY[DAILY.index("function Invoke-Step"):][:1800]
        self.assertIn("$ErrorActionPreference = 'Continue'", block)
        self.assertIn("& $body 2>&1", block)

    def test_preference_is_restored_even_if_the_step_throws(self):
        block = DAILY[DAILY.index("function Invoke-Step"):][:1800]
        self.assertIn("finally { $ErrorActionPreference = $prevEap }", block)

    def test_success_is_still_judged_by_exit_code(self):
        # stderr 를 무시하는 대신 종료 코드로 판단해야 한다. 둘 다 놓치면
        # 실패한 단계를 성공으로 보고 반쪽 상태로 발행한다.
        block = DAILY[DAILY.index("function Invoke-Step"):][:2200]
        self.assertIn("$code = $LASTEXITCODE", block)
        self.assertIn("$code -ne 0", block)


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
