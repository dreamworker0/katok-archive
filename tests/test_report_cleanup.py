# -*- coding: utf-8 -*-
"""삭제·제외된 글이 든 주제의 보고서는 보류하고, 남은 글로 다시 쓴다. (2026-11-11)

사용자 결정 '보류 + 다시 쓰기'. 여럿이 나눈 대화에서 한 사람의 글이 빠져도 주제는
살아남고, 그 글이 있을 때 쓴 보고서·AI 주석이 그대로 발행됐다(외부 평가 지적).
"""
from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts import report_cleanup as rc  # noqa: E402
from scripts.jsonio import read_json, write_json  # noqa: E402

TOPICS = {"threads": [
    {"id": "t-1", "title": "여럿", "message_ids": ["m1", "m2", "m3"]},
    {"id": "t-2", "title": "통째로 빠짐", "message_ids": ["m4"]},
    {"id": "t-3", "title": "그대로", "message_ids": ["m5", "m6"]},
]}
KEPT = {"m1", "m3", "m5", "m6"}       # m2·m4 가 빠졌다


class PendingTests(unittest.TestCase):
    def test_only_partly_excluded_threads_are_pending(self):
        # t-2 는 통째로 빠져 발행되지 않으므로 대상이 아니다
        self.assertEqual(rc.pending_exclusions(TOPICS, KEPT), {"t-1": ["m2"]})

    def test_withheld_until_the_same_exclusion_is_reflected(self):
        pending = {"t-1": ["m2"]}
        self.assertEqual(rc.withheld_ids(pending, {"cleaned": {}}), {"t-1"})
        self.assertEqual(rc.withheld_ids(pending, {"cleaned": {"t-1": ["m2"]}}), set())
        # 다시 쓴 뒤 다른 글이 또 빠지면 다시 보류한다
        self.assertEqual(rc.withheld_ids({"t-1": ["m2", "m3"]}, {"cleaned": {"t-1": ["m2"]}}),
                         {"t-1"})

    def test_withhold_replaces_report_and_drops_ai_note(self):
        threads = [{"id": "t-1", "report": "m2 를 인용한 글", "ai_report": "주석",
                    "ai_checked": "2026-11-01", "ai_models": ["x"]},
                   {"id": "t-3", "report": "그대로", "ai_report": "주석"}]
        self.assertEqual(rc.withhold(threads, {"t-1"}), 1)
        self.assertEqual(threads[0]["report"], rc.WITHHELD_REPORT)
        for k in ("ai_report", "ai_checked", "ai_models"):
            self.assertNotIn(k, threads[0])
        self.assertEqual(threads[1]["report"], "그대로")
        self.assertIn("ai_report", threads[1])


class MainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / "reports-cleaned.json"
        for p in (mock.patch.object(rc, "STATE", self.state),
                  mock.patch.object(rc, "_current",
                                    lambda: (TOPICS, {"t-1": ["m2"]}, KEPT)),
                  mock.patch.object(rc, "_retire_ai_report", lambda tid: True),
                  mock.patch.object(sys, "argv", ["report_cleanup"])):
            p.start()
            self.addCleanup(p.stop)

    def run_main(self, write_result):
        sent = []

        def fake_write(targets, model, examples, dry, timeout, min_by_id=None):
            sent.extend(targets)
            return write_result

        out = io.StringIO()
        with mock.patch("scripts.classify_unsorted._write_reports", fake_write), \
                redirect_stdout(out):
            rc.main()
        return sent, out.getvalue()

    def test_rewrite_sends_only_the_kept_messages(self):
        sent, out = self.run_main(1)
        self.assertEqual(sent[0]["message_ids"], ["m1", "m3"], "빠진 글은 AI 에게도 안 보낸다")
        self.assertEqual(read_json(self.state)["cleaned"], {"t-1": ["m2"]})
        self.assertIn("CLEANED_IDS=t-1", out)
        self.assertIn("REPORTS_WITHHELD=0", out)

    def test_failure_keeps_it_withheld_and_counts_tries(self):
        _, out = self.run_main(0)
        st = read_json(self.state)
        self.assertEqual(st["cleaned"], {})
        self.assertEqual(st["tries"], {"t-1": 1})
        self.assertIn("REPORTS_WITHHELD=1", out)

    def test_gives_up_after_max_tries(self):
        write_json(self.state, {"cleaned": {}, "tries": {"t-1": rc.MAX_TRIES}})
        sent, out = self.run_main(1)
        self.assertEqual(sent, [], "더 부르지 않는다")
        self.assertIn("REPORTS_WITHHELD=1", out)


class WiringContractTests(unittest.TestCase):
    def test_payload_withholds_before_ai_reports_are_split_out(self):
        src = (ROOT / "scripts" / "build_firestore_payload.py").read_text(encoding="utf-8")
        w = src.index("report_cleanup.withhold(threads_pub, withheld)")
        self.assertLess(w, src.index("ai_reports.append({"))

    def test_nightly_runs_cleanup_before_ai_notes(self):
        daily = (ROOT / "scripts" / "run_daily.ps1").read_text(encoding="utf-8")
        step = daily.index("python -m scripts.report_cleanup")
        self.assertLess(step, daily.index("# 5b-2) AI 검증 주석"))
        self.assertLess(step, daily.index("python -m scripts.publish_state"))
        self.assertIn("Test-StepExit '삭제 반영 보고서 다시 쓰기'", daily)


if __name__ == "__main__":
    unittest.main()
