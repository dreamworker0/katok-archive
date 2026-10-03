# -*- coding: utf-8 -*-
"""merge_threads — 지어낸 주제로, 어디서든 돈다."""
import unittest
from unittest import mock

from scripts import merge_threads as mt


def _topics():
    return {"threads": [
        {"id": "t-010", "title": "가", "summary": "가 요지", "category": "governance",
         "keywords": ["A", "B"], "message_ids": ["msg-000001", "msg-000002"],
         "start_msg": "msg-000001", "end_msg": "msg-000002"},
        {"id": "t-011", "title": "끼어든 인사", "summary": "", "category": "members",
         "keywords": [], "message_ids": ["msg-000003"],
         "start_msg": "msg-000003", "end_msg": "msg-000003"},
        {"id": "t-012", "title": "나", "summary": "나 요지", "category": "infra",
         "keywords": ["B", "C"],
         "message_ids": ["msg-000004", "msg-000005", "msg-000006"],
         "start_msg": "msg-000004", "end_msg": "msg-000006"},
        {"id": "t-013", "title": "다", "summary": "", "category": "infra",
         "keywords": [], "message_ids": ["msg-000007"],
         "start_msg": "msg-000007", "end_msg": "msg-000007"},
    ]}


def _g(ids, conf="high", title="합친 제목"):
    return {"threads": ids, "confidence": conf, "reason": "r", "title": title,
            "summary": "합친 요지"}


class MergeThreadsTest(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(mt.member_requests, "load_hidden_threads", return_value=[])
        p.start()
        self.addCleanup(p.stop)

    def test_keeps_earliest_id_and_skips_the_interloper(self):
        topics = _topics()
        todo, _ = mt.plan(topics, [_g(["t-012", "t-010"])])
        self.assertEqual(todo[0]["keep"], "t-010")
        mt.apply(topics, todo)
        ids = [t["id"] for t in topics["threads"]]
        self.assertEqual(ids, ["t-010", "t-011", "t-013"])
        keep = topics["threads"][0]
        self.assertEqual(keep["message_ids"],
                         ["msg-000001", "msg-000002", "msg-000004", "msg-000005", "msg-000006"])
        self.assertEqual((keep["start_msg"], keep["end_msg"]), ("msg-000001", "msg-000006"))
        self.assertEqual(keep["title"], "합친 제목")
        self.assertEqual(keep["keywords"], ["A", "B", "C"])

    def test_category_follows_the_bigger_part(self):
        todo, _ = mt.plan(_topics(), [_g(["t-010", "t-012"])])
        self.assertEqual(todo[0]["category"], "infra")      # 3건 > 2건

    def test_overlapping_groups_from_different_days_join(self):
        todo, _ = mt.plan(_topics(), [_g(["t-010", "t-012"]), _g(["t-012", "t-013"], "medium")])
        self.assertEqual(len(todo), 1)
        self.assertEqual(todo[0]["ids"], ["t-010", "t-012", "t-013"])
        self.assertEqual(todo[0]["confidence"], "medium")  # 약한 쪽을 따른다

    def test_hidden_thread_blocks_the_group(self):
        with mock.patch.object(mt.member_requests, "load_hidden_threads",
                               return_value=["t-012"]):
            todo, skipped = mt.plan(_topics(), [_g(["t-010", "t-012"])])
        self.assertEqual(todo, [])
        self.assertIn("t-012", skipped[0]["why"])

    def test_unknown_ids_are_dropped(self):
        todo, skipped = mt.plan(_topics(), [_g(["t-010", "t-999"])])
        self.assertEqual(todo, [])
        self.assertTrue(skipped)


class ProposalTest(unittest.TestCase):
    def test_rejected_groups_never_come_back(self):
        days = {"days": {"2026-01-01": [_g(["t-1", "t-2"]), _g(["t-3", "t-4"], "medium"),
                                        dict(_g(["t-5", "t-6"]), confidence="rejected")]}}
        with mock.patch.object(mt, "read_json", return_value=days), \
             mock.patch("pathlib.Path.exists", return_value=True):
            self.assertEqual(len(mt.proposed_groups(False)), 1)
            got = mt.proposed_groups(True)
        self.assertEqual([g["threads"] for g in got], [["t-1", "t-2"], ["t-3", "t-4"]])


class RetiredIdsTest(unittest.TestCase):
    def test_next_id_skips_retired(self):
        from scripts import classify_unsorted as cu
        with mock.patch.object(cu, "load_json", return_value=["t-050"]), \
             mock.patch("pathlib.Path.exists", return_value=True):
            self.assertEqual(cu.next_thread_id([{"id": "t-010"}]), 51)


if __name__ == "__main__":
    unittest.main()
