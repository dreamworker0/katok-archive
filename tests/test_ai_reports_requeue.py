# -*- coding: utf-8 -*-
"""실시간 검증이 '달라짐' 을 찾은 주제를 밤에 먼저 다시 쓰는 목록(ai_reports.REQUEUE_FILE)."""
import json
import tempfile
import unittest
from pathlib import Path

from scripts import ai_reports as AR


class Requeue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self._file, self._dir = AR.REQUEUE_FILE, AR.AI_REPORTS_DIR
        AR.REQUEUE_FILE = d / "requeue.json"
        AR.AI_REPORTS_DIR = d / "ai-reports"
        AR.AI_REPORTS_DIR.mkdir()

    def tearDown(self):
        AR.REQUEUE_FILE, AR.AI_REPORTS_DIR = self._file, self._dir
        self.tmp.cleanup()

    def put(self, data):
        AR.REQUEUE_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def report(self, tid, checked):
        (AR.AI_REPORTS_DIR / ("%s.md" % tid)).write_text(
            "---\nchecked: %s\nmodels: x\n---\n\n본문\n" % checked, encoding="utf-8")

    def test_most_flagged_first_and_limited(self):
        self.put({"t-1": {"count": 1, "since": "2026-10-01"},
                  "t-2": {"count": 5, "since": "2026-10-02"},
                  "t-3": {"count": 2, "since": "2026-10-03"},
                  "t-4": {"count": 1, "since": "2026-10-04"}})
        threads = [{"id": "t-%d" % i} for i in range(1, 5)]
        picked, drop = AR.pick_requeued(threads, "2026-10-30", limit=2)
        self.assertEqual([t["id"] for t in picked], ["t-2", "t-3"])
        self.assertEqual(drop, {})

    def test_fresh_report_and_vanished_topic_are_dropped(self):
        self.put({"t-1": {"count": 1}, "t-2": {"count": 1}, "t-9": {"count": 1}})
        self.report("t-1", "2026-10-29")        # 어제 쓴 것 — 다시 쓰지 않는다
        self.report("t-2", "2026-08-28")        # 두 달 전 — 다시 쓴다
        picked, drop = AR.pick_requeued([{"id": "t-1"}, {"id": "t-2"}], "2026-10-30")
        self.assertEqual([t["id"] for t in picked], ["t-2"])
        self.assertEqual(drop, {"t-1": "drop", "t-9": "drop"})

    def test_save_keeps_new_entries_and_counts_failures(self):
        self.put({"t-1": {"count": 1}, "t-2": {"count": 1}})
        # 밤 갱신이 도는 사이 물어보기 검증이 t-3 을 올렸다
        cur = json.loads(AR.REQUEUE_FILE.read_text(encoding="utf-8"))
        cur["t-3"] = {"count": 1}
        self.put(cur)
        AR.save_requeue({"t-1": "drop", "t-2": "retry"})
        left = json.loads(AR.REQUEUE_FILE.read_text(encoding="utf-8"))
        self.assertNotIn("t-1", left)
        self.assertEqual(left["t-2"]["tries"], 1)
        self.assertIn("t-3", left)
        for _ in range(AR.REQUEUE_MAX_TRIES - 1):
            AR.save_requeue({"t-2": "retry"})
        self.assertNotIn("t-2", json.loads(AR.REQUEUE_FILE.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
