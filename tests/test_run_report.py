# -*- coding: utf-8 -*-
"""야간 갱신 결과가 화면까지 닿는지 — 세 조각의 계약.

갱신 경로가 둘인데 한쪽만 화면에 보였다. '지금 갱신' 버튼은 refresh_watcher.js 가
`settings/refresh` 에 상태를 써서 관리 탭이 실시간으로 보여줬지만, 매일 23:40
스케줄러는 **아무것도 쓰지 않았다**. 그래서 야간 갱신이 사흘 내리 실패해도 화면은
조용했고, 사람이 `logs\daily-*.log` 를 열어 보기 전까지 아무도 몰랐다.

고치는 데 세 조각이 필요하다. 하나만 빠져도 소식은 화면에 닿지 않는데, 그 실패는
조용하다 — 화면은 그냥 예전처럼 아무 말도 안 한다. 그래서 셋을 함께 검사한다.

  1. run_daily.ps1     세 갈래 종료(성공·건너뜀·실패)마다 결과를 남기는가
  2. report_run.js     남길 값을 검증하고, 실패해도 갱신을 죽이지 않는가
  3. app.js / boot.js  그 문서를 듣고 그리는가
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


class RunDailyReportsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ps1 = read("scripts/run_daily.ps1")

    def test_all_three_exits_report(self):
        """성공·건너뜀·실패 셋 다 남긴다.

        실패만 남기면 '조용한 날'과 '스케줄러가 아예 안 돌았다'를 구분할 수 없다.
        둘 다 화면에서는 '소식 없음'으로 보이는데, 하나는 정상이고 하나는 장애다.
        """
        for status in ("ok", "skipped", "failed"):
            with self.subTest(status=status):
                self.assertIn("Report-Run -status '%s'" % status, self.ps1)

    def test_failure_reports_which_step(self):
        """어느 단계에서 멈췄는지 남긴다 — 로그를 열지 않고도 보이게."""
        m = re.search(r"Report-Run -status 'failed'[^\n]*", self.ps1)
        self.assertIsNotNone(m, "실패 경로에 기록이 없다")
        self.assertIn("-step $name", m.group(0))
        self.assertIn("-code $code", m.group(0))

    def test_dry_run_does_not_write(self):
        """확인만 하는 실행이 화면의 '마지막 갱신'을 덮으면 그것이 곧 거짓말이 된다."""
        body = self.ps1.split("function Report-Run {", 1)[1].split("\n}", 1)[0]
        self.assertIn("if ($DryRun) { return }", body)

    def test_reporting_cannot_kill_the_run(self):
        """알림을 남기려는 코드가 그날 갱신을 죽여서는 안 된다.

        `$ErrorActionPreference = 'Stop'` 인 스크립트에서 node 가 stderr 에 한 줄만
        써도 그 자리에서 갱신이 끝난다. 그 함정에 이미 두 번 빠졌다
        (2026-07-27 테스트 단계, 그리고 분류 단계).
        """
        body = self.ps1.split("function Report-Run {", 1)[1].split("\n}", 1)[0]
        self.assertIn("$ErrorActionPreference = 'Continue'", body)
        # 종료 코드를 보고 무언가 하지 않는다 — 봤으면 exit 나 throw 가 있을 것이다.
        # `--exit` 는 node 에 넘기는 인자 이름이므로 문(statement)만 본다.
        self.assertIsNone(re.search(r"(^|[;{])\s*exit", body, re.M),
                          "Report-Run 안에 exit 문이 있다 — 기록 실패가 갱신을 죽인다")
        self.assertNotIn("throw", body)

    def test_lock_conflict_does_not_report(self):
        """겹쳐 돌아 물러난 실행(exit 75)은 남기지 않는다.

        그것은 실패가 아니고, 남기면 이미 돌고 있는 쪽의 결과를 덮는다.
        """
        head = self.ps1.split("function Invoke-Step", 1)[0]
        self.assertIn("exit 75", head)
        self.assertNotIn("Report-Run", head.split("$lockPath", 1)[1])


class ReportRunScriptTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = read("scripts/report_run.js")

    def test_only_known_statuses_are_accepted(self):
        self.assertIn('const VALID = ["ok", "skipped", "failed"]', self.js)
        self.assertIn("process.exit(2)", self.js)

    def test_writes_to_its_own_document(self):
        """`settings/refresh` 를 건드리지 않는다.

        버튼 한 건의 생애와 야간 갱신 결과는 서로를 지워서는 안 되는 별개의
        소식이다. 한 문서에 섞으면 버튼을 누르지 않았는데 '갱신 중'이 뜨거나,
        버튼 한 번이 지난 밤의 실패를 덮어 지운다.
        """
        self.assertIn('.doc("lastRun")', self.js)
        self.assertNotIn('.doc("refresh")', self.js)

    def test_swallows_its_own_failure(self):
        """기록에 실패해도 0 으로 끝난다 — 갱신은 성공한 것이다."""
        tail = self.js.split("main().catch", 1)[1]
        self.assertIn("process.exit(0)", tail)


class AdminScreenShowsItTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = read("web/app.js")
        cls.boot = read("web/boot.js")

    def test_boot_subscribes_to_the_document(self):
        self.assertIn("watchLastRun", self.boot)
        self.assertIn('doc("lastRun")', self.boot)

    def test_app_listens_and_draws(self):
        self.assertIn("watchLastRun", self.app)
        self.assertIn("lastRunLine", self.app)
        # 카드를 그릴 때 실제로 불러야 한다 — 함수만 있고 안 부르면 아무 일도 없다.
        self.assertIn("lastRunLine(state.lastRun)", self.app)

    def test_subscription_is_released(self):
        """구독을 놓아주지 않으면 관리 탭을 여닫을 때마다 리스너가 쌓인다."""
        self.assertIn("state.lastRunUnsub", self.app)
        block = self.app.split("function unwatchRefresh()", 1)[1].split("\n  }", 1)[0]
        self.assertIn("state.lastRunUnsub = null", block)

    def test_failure_and_staleness_are_warnings_not_notes(self):
        """실패와 '며칠째 안 돌았다'는 경고 색으로 낸다.

        `mine-note` 는 회색 보조 문구다. 실패를 그 색으로 내면 못 보고 지나간다.
        """
        body = self.app.split("function lastRunLine(lr) {", 1)[1].split("\n  }", 1)[0]
        failed = body.split('lr.status === "failed"', 1)[1].split("if (stale)", 1)[0]
        self.assertIn("rf-warn", failed)
        stale = body.split("if (stale)", 1)[1].split("var body", 1)[0]
        self.assertIn("rf-warn", stale)

    def test_quiet_day_and_failure_read_differently(self):
        """건너뛴 날과 실패한 날이 같은 문구로 보이면 이 줄이 있으나 마나다."""
        body = self.app.split("function lastRunLine(lr) {", 1)[1].split("\n  }", 1)[0]
        self.assertIn("올릴 것이 없어 건너뜀", body)
        self.assertIn("야간 갱신이 실패했습니다", body)

    def test_stale_record_is_not_shown_as_success(self):
        """'마지막 결과'만 보여주면 스케줄러가 꺼진 뒤에도 옛 성공이 계속 초록이다."""
        body = self.app.split("function lastRunLine(lr) {", 1)[1].split("\n  }", 1)[0]
        self.assertIn("LASTRUN_STALE_MS", body)
        self.assertIn("하루가 넘도록", body)


if __name__ == "__main__":
    unittest.main()
