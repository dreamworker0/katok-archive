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


class RetireTests(unittest.TestCase):
    """합치기로 사라진 주제가 목록에 영영 남지 않는다 (2026-11-13, t-731 → t-730)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "replies-applied.json"
        p = mock.patch.object(ar, "APPLIED", self.path)
        p.start()
        self.addCleanup(p.stop)

    def test_merged_away_id_becomes_the_kept_one(self):
        write_json(self.path, {"rewrite": ["t-1", "t-731", "t-9"], "removed_threads": ["t-5"]})
        self.assertEqual(ar.retire_rewrites({"t-731": "t-730"}), 3)
        data = read_json(self.path)
        self.assertEqual(data["rewrite"], ["t-1", "t-730", "t-9"])
        self.assertEqual(data["removed_threads"], ["t-5"])     # 다른 칸은 그대로

    def test_kept_id_already_listed_is_not_doubled(self):
        write_json(self.path, {"rewrite": ["t-730", "t-731"]})
        self.assertEqual(ar.retire_rewrites({"t-731": "t-730"}), 1)
        self.assertEqual(read_json(self.path)["rewrite"], ["t-730"])

    def test_then_rewriting_the_kept_one_empties_the_list(self):
        write_json(self.path, {"rewrite": ["t-731"]})
        ar.retire_rewrites({"t-731": "t-730"})
        self.assertEqual(ar.clear_rewrites(["t-730"]), 0)

    def test_no_file_is_left_alone(self):
        self.assertEqual(ar.retire_rewrites({"t-731": "t-730"}), 0)
        self.assertFalse(self.path.exists())


class MergeThreadsCallsItTests(unittest.TestCase):
    def test_fix_side_files_retires_dropped_ids(self):
        from scripts import merge_threads as mt
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            applied = d / "replies-applied.json"
            write_json(applied, {"rewrite": ["t-731", "t-2"]})
            (d / "bak").mkdir()
            patches = [mock.patch.object(ar, "APPLIED", applied)]
            for name in ("SECONDARY", "KNOWLEDGE", "AI_SKIPS"):
                patches.append(mock.patch.object(mt, name, d / f"{name}.json"))
            for name in ("REPORTS", "AI_REPORTS"):
                patches.append(mock.patch.object(mt, name, d / name))
            patches.append(mock.patch.object(mt, "RETIRED", d / "retired.json"))
            patches.append(mock.patch.object(mt, "load_retired", return_value=[]))
            for p in patches:
                p.start()
                self.addCleanup(p.stop)
            mt.fix_side_files([{"keep": "t-730", "drop": ["t-731"],
                                "ids": ["t-730", "t-731"], "category": "chat"}], d / "bak")
            self.assertEqual(read_json(applied)["rewrite"], ["t-730", "t-2"])


class PendingCountTests(unittest.TestCase):
    """경고 숫자는 합치기·다시 쓰기 **뒤에** 센다 (2026-11-13)."""

    def _pending(self, path):
        import contextlib
        import io
        buf = io.StringIO()
        with mock.patch.object(ar, "APPLIED", path), \
             mock.patch.object(sys, "argv", ["apply_replies", "--pending"]), \
             contextlib.redirect_stdout(buf):
            self.assertEqual(ar.main(), 0)
        return buf.getvalue().strip()

    def test_pending_only_counts_and_touches_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "replies-applied.json"
            write_json(p, {"rewrite": ["t-1", "t-2"]})
            before = p.read_bytes()
            self.assertEqual(self._pending(p), "REWRITE_PENDING=2")
            self.assertEqual(p.read_bytes(), before)

    def test_no_file_counts_zero(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self._pending(Path(d) / "none.json"), "REWRITE_PENDING=0")

    def test_runner_counts_after_the_merge_step(self):
        daily = (ROOT / "scripts" / "run_daily.ps1").read_text(encoding="utf-8")
        merge = daily.index("python -m scripts.merge_threads --apply")
        call = daily.index("\nAdd-RewritePendingWarn")
        self.assertLess(merge, call)
        # 답장 반영 단계에서는 더 이상 경고를 올리지 않는다.
        apply_step = daily[daily.index("python -m scripts.apply_replies --apply"):merge]
        func = apply_step.index("function Add-RewritePendingWarn")
        self.assertNotIn("Add-StepWarn", apply_step[:func])


class RunnerSurfacesItTests(unittest.TestCase):
    def test_runner_reads_the_marker_and_warns(self):
        daily = (ROOT / "scripts" / "run_daily.ps1").read_text(encoding="utf-8")
        self.assertIn("REWRITE_PENDING=", daily)
        self.assertIn("Add-StepWarn \"다시 써야 할 보고서", daily)
        src = (ROOT / "scripts" / "apply_replies.py").read_text(encoding="utf-8")
        self.assertIn('print(f"REWRITE_PENDING={len(pending)}")', src)


if __name__ == "__main__":
    unittest.main()
