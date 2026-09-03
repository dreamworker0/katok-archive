# -*- coding: utf-8 -*-
"""형식 분류 감사 — 원장의 주 분류를 옮기는 일이라 되돌릴 자리를 먼저 본다.

이 작업의 실패 방식은 셋이다.

  · 제안에 없는 주제가 움직인다 — 사람이 기각한 것까지 옮겨진다
  · 목록에 없는 분류로 옮겨진다 — 발행이 그 주제를 어느 카드에도 담지 못한다
  · 주 분류와 보조 분류가 같아진다 — 한 주제를 두 번 세는 꼴이 된다

여기 나오는 이름은 전부 가짜다. 저장소가 공개다.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts import audit_form_categories as afc

CATEGORIES = [
    {"id": "projects", "label": "프로젝트·결과물"},
    {"id": "ai-models", "label": "AI 모델·요금제"},
    {"id": "welfare-practice", "label": "사회복지 실천·현장 적용"},
    {"id": "news-articles", "label": "뉴스·자료 공유"},
    {"id": "chat", "label": "일상·잡담"},
]

THREADS = [
    {"id": "t-001", "category": "news-articles", "title": "모델 장애 기사",
     "message_ids": ["msg-1", "msg-2"]},
    {"id": "t-002", "category": "news-articles", "title": "링크 모음",
     "message_ids": ["msg-3"]},
    {"id": "t-003", "category": "chat", "title": "안부 인사",
     "message_ids": ["msg-4"]},
    {"id": "t-004", "category": "chat", "title": "리터러시 논문 이야기",
     "message_ids": ["msg-5"]},
    {"id": "t-005", "category": "projects", "title": "가나다 앱 만들기",
     "message_ids": ["msg-6"]},
]

MAIN_OF = {t["id"]: t["category"] for t in THREADS}
VALID = {c["id"] for c in CATEGORIES}
ASKED = ["t-001", "t-002", "t-003", "t-004"]


class TargetsTest(unittest.TestCase):
    def test_only_the_form_categories_are_audited(self):
        self.assertEqual(ASKED, afc.targets(THREADS))

    def test_thread_order_is_kept(self):
        """원장 순서가 시간순이다 — 표를 읽는 사람이 흐름을 본다."""
        self.assertEqual(["t-001", "t-002"],
                         afc.targets(THREADS, ("news-articles",)))

    def test_first_message_date_is_the_threads_date(self):
        msgs = [{"id": "msg-1", "date": "2026-05-02"},
                {"id": "msg-2", "date": "2026-05-01"}]
        self.assertEqual({"t-001": "2026-05-01"},
                         afc.dates_of(THREADS[:1], msgs))


class ScreenTest(unittest.TestCase):
    def screen(self, replies):
        return afc.screen(replies, ASKED, MAIN_OF, VALID)

    def test_a_destination_outside_the_twelve_is_dropped(self):
        moves, kept = self.screen([{"moves": [
            {"id": "t-001", "to": "없는분류", "reason": "그럴듯한 말"}]}])
        self.assertEqual([], moves)
        self.assertIn("t-001", [k["id"] for k in kept])

    def test_a_form_category_is_never_a_destination(self):
        """형식 분류끼리 주고받으면 감사가 제자리를 돈다."""
        moves, _ = self.screen([{"moves": [
            {"id": "t-003", "to": "news-articles", "reason": "링크가 있다"}]}])
        self.assertEqual([], moves)

    def test_ids_that_were_not_asked_are_ignored(self):
        moves, _ = self.screen([{"moves": [
            {"id": "t-005", "to": "ai-models", "reason": "지어낸 대상"}]}])
        self.assertEqual([], moves)

    def test_everything_asked_lands_in_one_of_the_two_lists(self):
        moves, kept = self.screen([{
            "moves": [{"id": "t-001", "to": "ai-models", "reason": "장애 대응"}],
            "kept": [{"id": "t-002", "reason": "링크 모음"}],
        }])
        self.assertEqual(set(ASKED),
                         {m["id"] for m in moves} | {k["id"] for k in kept})
        self.assertEqual("ai-models", moves[0]["to"])
        self.assertEqual("news-articles", moves[0]["from"])

    def test_a_thread_in_both_lists_counts_as_a_move(self):
        moves, kept = self.screen([{
            "moves": [{"id": "t-004", "to": "welfare-practice", "reason": "논문"}],
            "kept": [{"id": "t-004", "reason": "잡담"}],
        }])
        self.assertEqual(["t-004"], [m["id"] for m in moves])
        self.assertNotIn("t-004", [k["id"] for k in kept])


class ApplyTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.topics = self.dir / "topics.json"
        self.secondary = self.dir / "secondary_categories.json"
        self._saved = (afc.TOPICS, afc.SECONDARY, afc.OUT)
        afc.TOPICS, afc.SECONDARY, afc.OUT = self.topics, self.secondary, self.dir
        self.write_topics(THREADS)
        self.write_secondary({"t-004": ["welfare-practice"]})

    def tearDown(self):
        afc.TOPICS, afc.SECONDARY, afc.OUT = self._saved

    def write_topics(self, threads):
        self.topics.write_text(json.dumps(
            {"categories": CATEGORIES,
             "threads": [dict(t) for t in threads]}, ensure_ascii=False),
            encoding="utf-8")

    def write_secondary(self, table):
        self.secondary.write_text(
            json.dumps({"secondary": table, "asked": ASKED}, ensure_ascii=False),
            encoding="utf-8")

    def read_topics(self):
        data = json.loads(self.topics.read_text(encoding="utf-8"))
        return {t["id"]: t["category"] for t in data["threads"]}

    def read_secondary(self):
        return json.loads(
            self.secondary.read_text(encoding="utf-8"))["secondary"]

    PROPOSAL = {"moves": [
        {"id": "t-001", "from": "news-articles", "to": "ai-models", "reason": "가"},
        {"id": "t-004", "from": "chat", "to": "welfare-practice", "reason": "나"},
    ]}

    def test_only_the_proposed_threads_move(self):
        done, _, _ = afc.apply_proposal(self.PROPOSAL, "20260904")
        cats = self.read_topics()
        self.assertEqual(2, len(done))
        self.assertEqual("ai-models", cats["t-001"])
        self.assertEqual("welfare-practice", cats["t-004"])
        self.assertEqual("news-articles", cats["t-002"], "제안에 없다")
        self.assertEqual("chat", cats["t-003"], "제안에 없다")
        self.assertEqual("projects", cats["t-005"], "대상이 아니다")

    def test_only_flag_applies_a_subset(self):
        """사람이 몇 개를 기각한다 — 승인한 것만 움직여야 한다."""
        done, _, _ = afc.apply_proposal(self.PROPOSAL, "20260904", only={"t-001"})
        self.assertEqual(["t-001"], [m["id"] for m in done])
        self.assertEqual("chat", self.read_topics()["t-004"])

    def test_the_old_category_becomes_a_secondary_one(self):
        afc.apply_proposal(self.PROPOSAL, "20260904")
        self.assertEqual(["news-articles"], self.read_secondary()["t-001"])

    def test_the_destination_is_removed_from_the_secondary_list(self):
        """주 분류와 보조가 같으면 한 주제를 두 번 세는 꼴이다."""
        afc.apply_proposal(self.PROPOSAL, "20260904")
        self.assertEqual(["chat"], self.read_secondary()["t-004"])

    def test_a_full_secondary_list_is_left_alone_and_logged(self):
        self.write_secondary({"t-001": ["projects", "chat"]})
        done, skipped, _ = afc.apply_proposal(
            {"moves": [self.PROPOSAL["moves"][0]]}, "20260904")
        self.assertEqual(["t-001"], [m["id"] for m in done])
        self.assertEqual(["projects", "chat"], self.read_secondary()["t-001"])
        self.assertTrue(any("보조 분류가 이미" in s for s in skipped))

    def test_applying_twice_changes_nothing_more(self):
        afc.apply_proposal(self.PROPOSAL, "20260904")
        first = (self.read_topics(), self.read_secondary())
        done, skipped, _ = afc.apply_proposal(self.PROPOSAL, "20260904")
        self.assertEqual([], done)
        self.assertEqual(2, len(skipped))
        self.assertEqual(first, (self.read_topics(), self.read_secondary()))

    def test_a_ledger_that_moved_on_is_not_touched(self):
        """제안을 만든 뒤 분류가 바뀌었으면 그때 판단이 맞는지 알 수 없다."""
        threads = [dict(t, category="projects") if t["id"] == "t-001" else t
                   for t in THREADS]
        self.write_topics(threads)
        done, skipped, _ = afc.apply_proposal(
            {"moves": [self.PROPOSAL["moves"][0]]}, "20260904")
        self.assertEqual([], done)
        self.assertEqual("projects", self.read_topics()["t-001"])
        self.assertTrue(any("제안" in s for s in skipped))

    def test_the_backup_folder_holds_the_files_as_they_were(self):
        _, _, backup = afc.apply_proposal(self.PROPOSAL, "20260904")
        self.assertTrue(backup.is_dir())
        saved = json.loads((backup / "topics.json").read_text(encoding="utf-8"))
        self.assertEqual("news-articles",
                         {t["id"]: t["category"]
                          for t in saved["threads"]}["t-001"])
        self.assertTrue((backup / "secondary_categories.json").is_file())


class MarkdownTest(unittest.TestCase):
    def test_the_table_shows_labels_not_ids(self):
        md = afc.render_markdown(
            [{"id": "t-001", "from": "news-articles", "to": "ai-models",
              "reason": "장애 대응"}],
            [{"id": "t-002", "reason": "링크 모음"}],
            {"t-001": "모델 장애 기사", "t-002": "링크 모음"},
            {c["id"]: c["label"] for c in CATEGORIES}, "20260904", "opus")
        self.assertIn("뉴스·자료 공유 → AI 모델·요금제", md)
        self.assertIn("옮길 것 1개", md)
        self.assertIn("그대로 둘 것 1개", md)

    def test_a_pipe_in_a_title_does_not_break_the_table(self):
        md = afc.render_markdown(
            [], [{"id": "t-002", "reason": "가|나"}], {"t-002": "제목|둘"},
            {}, "20260904", "opus")
        self.assertNotIn("제목|둘", md)
        self.assertIn("제목／둘", md)


if __name__ == "__main__":
    unittest.main()
