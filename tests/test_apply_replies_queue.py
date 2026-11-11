# -*- coding: utf-8 -*-
"""답장 반영이 남긴 '다시 써야 할 보고서' 목록은 쌓이고, 다 쓴 것만 빠진다. (2026-11-11)

예전에는 밤마다 목록을 덮어써서, 옮길 게 없는 밤이 한 번만 지나도 빈 목록이 되어
다시 써야 할 보고서를 잃었다(외부 평가 지적).
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts import apply_replies as ar  # noqa: E402
from scripts.jsonio import read_json, write_json  # noqa: E402


class MergeTests(unittest.TestCase):
    def test_keeps_old_and_adds_new_in_order(self):
        self.assertEqual(ar.merge_rewrites(["t-1", "t-2"], ["t-2", "t-3"], []),
                         ["t-1", "t-2", "t-3"])

    def test_gone_threads_are_dropped(self):
        self.assertEqual(ar.merge_rewrites(["t-1", "t-2"], ["t-3"], ["t-2"]), ["t-1", "t-3"])

    def test_a_quiet_night_does_not_empty_the_list(self):
        self.assertEqual(ar.merge_rewrites(["t-1"], [], []), ["t-1"])


class ClearTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "replies-applied.json"
        p = mock.patch.object(ar, "APPLIED", self.path)
        p.start()
        self.addCleanup(p.stop)

    def test_rewritten_ids_leave_the_list(self):
        write_json(self.path, {"rewrite": ["t-1", "t-2", "t-3"], "removed_threads": [],
                               "moved_reports": []})
        self.assertEqual(ar.clear_rewrites(["t-2"]), 2)
        self.assertEqual(read_json(self.path)["rewrite"], ["t-1", "t-3"])

    def test_no_file_means_nothing_pending(self):
        self.assertEqual(ar.clear_rewrites(["t-1"]), 0)
        self.assertFalse(self.path.exists())


class RunnerSurfacesItTests(unittest.TestCase):
    def test_runner_reads_the_marker_and_warns(self):
        daily = (ROOT / "scripts" / "run_daily.ps1").read_text(encoding="utf-8")
        self.assertIn("REWRITE_PENDING=", daily)
        self.assertIn("Add-StepWarn \"다시 써야 할 보고서", daily)
        src = (ROOT / "scripts" / "apply_replies.py").read_text(encoding="utf-8")
        self.assertIn('print(f"REWRITE_PENDING={len(pending)}")', src)


if __name__ == "__main__":
    unittest.main()
