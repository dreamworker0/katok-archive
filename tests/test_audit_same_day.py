# -*- coding: utf-8 -*-
"""audit_same_day — 밤 갱신이 기대는 두 성질. 지어낸 자료로, LLM 없이 돈다."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import audit_same_day as asd
from scripts.jsonio import read_json, write_json


def _g(ids, conf="high"):
    return {"date": "2026-01-01", "threads": ids, "confidence": conf, "reason": "r",
            "title": "t", "summary": "s"}


class SaveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()) / "same-day-merge.json"
        p = mock.patch.object(asd, "RESULT", self.tmp)
        p.start()
        self.addCleanup(p.stop)

    def test_rejected_mark_survives_a_reaudit(self):
        """사람이 뺀 묶음이 밤 감사에 같은 주제들로 다시 나오면 뺀 표시가 붙어 있어야 한다.

        안 그러면 다음 날 밤 자동 합치기가 사람이 거절한 것을 되살린다.
        """
        rej = dict(_g(["t-1", "t-2"]), confidence="rejected", rejected_why="메시지만 옮김")
        write_json(self.tmp, {"days": {"2026-01-01": [rej, _g(["t-3", "t-4"])]}})
        asd.save({"2026-01-01": [_g(["t-2", "t-1"]), _g(["t-5", "t-6"])]},
                 {"2026-01-01": "sig"})
        got = read_json(self.tmp)
        groups = got["days"]["2026-01-01"]
        self.assertEqual(groups[0]["confidence"], "rejected")
        self.assertEqual(groups[0]["rejected_why"], "메시지만 옮김")
        self.assertEqual(groups[1]["confidence"], "high")
        self.assertEqual(got["sigs"], {"2026-01-01": "sig"})

    def test_other_days_are_left_alone(self):
        write_json(self.tmp, {"days": {"2026-01-01": [_g(["t-1", "t-2"])]},
                              "sigs": {"2026-01-01": "a"}})
        asd.save({"2026-01-02": []}, {"2026-01-02": "b"})
        got = read_json(self.tmp)
        self.assertEqual(len(got["days"]["2026-01-01"]), 1)
        self.assertEqual(got["sigs"], {"2026-01-01": "a", "2026-01-02": "b"})


class SignatureTest(unittest.TestCase):
    def test_signature_changes_when_a_message_lands(self):
        a = {"t-1": [{}, {}], "t-2": [{}]}
        b = {"t-1": [{}, {}], "t-2": [{}, {}]}
        self.assertNotEqual(asd.day_signature(a), asd.day_signature(b))
        self.assertEqual(asd.day_signature(a), asd.day_signature(dict(reversed(a.items()))))


if __name__ == "__main__":
    unittest.main()
