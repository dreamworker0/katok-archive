# -*- coding: utf-8 -*-
"""요지 산문 갱신 — 낡음 판정·규칙 검사·파일 쓰기.

이 일의 실패 방식은 넷이다.

  · 낡지 않은 것을 매일 다시 쓴다 — 같은 글에 하룻밤 $8~12 을 치른다
  · 낡은 것을 낡지 않았다고 본다 — 첫 화면이 다시 다섯 주 묵는다
  · 규칙을 어긴 글이 통과한다 — 어느 주제와도 이어지지 않는 태그, 절 없는 큰 분류
  · 한 편을 쓰면서 나머지 열한 편을 건드린다

여기 나오는 이름은 전부 가짜다. 저장소가 공개다.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from scripts import digest_prose as dp
from scripts import tag_surgery as ts
from scripts import topic_reports as tr

CATEGORIES = [
    {"id": "projects", "label": "프로젝트·결과물"},
    {"id": "hwp", "label": "한글(HWP) 문서 자동화"},
    {"id": "chat", "label": "일상·잡담"},
]
TODAY = date(2026, 9, 4)


def threads(**counts) -> list[dict]:
    out = []
    n = 0
    for cid, how_many in counts.items():
        for _ in range(how_many):
            n += 1
            out.append({"id": "t-%03d" % n, "category": cid,
                        "title": "제목 %d" % n, "summary": "요지 %d" % n,
                        "tags": [], "count": 3, "message_ids": ["msg-%d" % n]})
    return out


def prose(cid: str, day: str, count: int, **extra) -> dict:
    row = {"headline": "한 줄", "overview": "흐름", "keywords": ["가", "나"],
           "as_of": {"date": day, "thread_count": count, "last_thread_id": "t-001"}}
    row.update(extra)
    return {cid: row}


class SelectStaleTest(unittest.TestCase):
    def stale(self, prose_doc, **counts):
        return dp.select_stale(CATEGORIES, threads(**counts), prose_doc, TODAY)

    def test_a_category_with_no_as_of_is_stale(self):
        """언제 쓴 글인지 모르면 낡았는지도 알 수 없다 — 모르는 것을 새것으로 치지 않는다."""
        doc = {"projects": {"headline": "한 줄", "overview": "흐름"}}
        self.assertIn("projects", self.stale(doc, projects=3))

    def test_a_category_with_no_prose_at_all_is_stale(self):
        self.assertEqual(["projects"], self.stale({}, projects=3))

    def test_enough_new_threads_makes_it_stale(self):
        doc = prose("projects", "2026-09-03",
                    10 - tr.DIGEST_STALE_THREADS)     # 딱 기준만큼 늘었다
        self.assertIn("projects", self.stale(doc, projects=10))

    def test_a_few_new_threads_on_a_fresh_digest_is_not_stale(self):
        doc = prose("projects", "2026-09-03", 10 - (tr.DIGEST_STALE_THREADS - 1))
        self.assertEqual([], self.stale(doc, projects=10))

    def test_an_old_digest_with_one_new_thread_is_stale(self):
        doc = prose("projects", "2026-07-01", 9)      # 65일 전
        self.assertIn("projects", self.stale(doc, projects=10))

    def test_an_old_digest_with_nothing_new_is_left_alone(self):
        """조용한 분류는 한 달이 지나도 쓸 말이 그대로다 — 같은 글에 값을 치르지 않는다."""
        doc = prose("hwp", "2026-07-01", 12)
        self.assertEqual([], self.stale(doc, hwp=12))

    def test_the_most_grown_category_comes_first(self):
        doc = {}
        doc.update(prose("projects", "2026-09-01", 100))   # +6
        doc.update(prose("hwp", "2026-09-01", 2))          # +10
        got = self.stale(doc, projects=106, hwp=12)
        self.assertEqual(["hwp", "projects"], got)

    def test_a_broken_as_of_date_counts_as_stale(self):
        doc = prose("projects", "어제", 3)
        self.assertIn("projects", self.stale(doc, projects=3))


class StaleNoteTest(unittest.TestCase):
    """발행과 갱신이 같은 기준을 봐야 한다 — 갈라지면 둘 중 하나가 거짓말이다."""

    def test_no_as_of_says_so(self):
        self.assertEqual("프로젝트·결과물: 정리 시점 없음",
                         tr.digest_stale_note("프로젝트·결과물", 106, {}))

    def test_growth_is_reported_with_the_date(self):
        note = tr.digest_stale_note(
            "프로젝트·결과물", 106,
            {"as_of": {"date": "2026-07-28", "thread_count": 94}})
        self.assertEqual("프로젝트·결과물: 정리 뒤 주제 +12 (as_of 2026-07-28)", note)

    def test_a_fresh_digest_is_quiet(self):
        self.assertIsNone(tr.digest_stale_note(
            "프로젝트·결과물", 106,
            {"as_of": {"date": "2026-09-04", "thread_count": 106}}))


class PromptTest(unittest.TestCase):
    CAT = CATEGORIES[0]

    def build(self, **kw):
        rows = threads(projects=2)
        reports = {"t-001": {"title": "가나다 앱", "summary": "요지",
                             "keywords": ["업무 앱"], "report": "## 본문\n한 줄."}}
        args = dict(threads=rows, reports=reports, facets={}, vocabulary=["업무 앱"],
                    categories=CATEGORIES)
        args.update(kw)
        return dp.build_digest_prompt(self.CAT, **args)

    def test_the_prompt_carries_the_shared_rules_verbatim(self):
        """규칙이 프롬프트에만 있으면 검사가 다른 것을 본다."""
        self.assertIn(tr.DIGEST_RULES, self.build())

    def test_all_twelve_labels_are_shown_with_an_arrow_on_this_one(self):
        got = self.build()
        for c in CATEGORIES:
            self.assertIn(c["label"], got)
        self.assertIn("→ projects", got)

    def test_the_report_body_is_carried_but_not_raw_messages(self):
        got = self.build()
        self.assertIn("## 본문", got)
        self.assertIn("t-001", got)

    def test_facet_names_are_offered_as_section_titles(self):
        got = self.build(facets={"업무 앱": "실무자 업무", "게임 제작": "놀이"})
        self.assertIn("절 제목으로 쓰세요", got)
        self.assertIn("**업무 앱** — 실무자 업무", got)

    def test_a_category_without_facets_is_told_to_use_periods_or_topics(self):
        self.assertIn("시기나 화두로 나누고", self.build())

    def test_side_threads_are_titles_only_and_marked_as_reference(self):
        got = self.build(also_titles=["곁 주제 제목"])
        self.assertIn("곁 주제 제목", got)
        self.assertIn("본문에 쓰지 마세요", got)


class ValidateTest(unittest.TestCase):
    VOCAB = ["가", "나", "다", "라", "마"]

    def good(self, **extra):
        row = {"headline": "한 줄 제목", "overview": "흐름을 적은 글",
               "sections": [], "keywords": self.VOCAB[:tr.DIGEST_KEYWORDS[0]]}
        row.update(extra)
        return row

    def test_a_clean_answer_passes(self):
        obj, bad = dp.validate(self.good(), self.VOCAB, 5)
        self.assertEqual([], bad)
        self.assertEqual("한 줄 제목", obj["headline"])

    def test_keywords_outside_the_vocabulary_are_dropped_not_fatal(self):
        """어휘 밖 하나 때문에 편 전체를 버리면 나머지를 함께 잃는다."""
        obj, bad = dp.validate(
            self.good(keywords=self.VOCAB[:4] + ["없는 말"]), self.VOCAB, 5)
        self.assertEqual([], bad)
        self.assertNotIn("없는 말", obj["keywords"])
        self.assertEqual(4, len(obj["keywords"]))

    def test_too_few_keywords_after_dropping_is_refused(self):
        obj, bad = dp.validate(self.good(keywords=["없는 말", "가"]), self.VOCAB, 5)
        self.assertIsNone(obj)
        self.assertTrue(any("keywords" in b for b in bad))
        self.assertTrue(any("어휘 밖 버림" in b for b in bad))

    def test_a_big_category_without_sections_is_refused(self):
        obj, bad = dp.validate(self.good(), self.VOCAB, tr.DIGEST_SECTION_FROM)
        self.assertIsNone(obj)
        self.assertTrue(any("절이 없다" in b for b in bad))

    def test_a_big_category_with_sections_passes(self):
        obj, _ = dp.validate(
            self.good(sections=[{"title": "업무 앱", "body": "세 문장."}]),
            self.VOCAB, tr.DIGEST_SECTION_FROM)
        self.assertEqual([{"title": "업무 앱", "body": "세 문장."}], obj["sections"])

    def test_a_headline_over_the_limit_is_refused(self):
        obj, bad = dp.validate(
            self.good(headline="가" * (tr.DIGEST_HEADLINE_MAX + 1)), self.VOCAB, 5)
        self.assertIsNone(obj)
        self.assertTrue(any("headline" in b for b in bad))

    def test_an_overview_over_the_limit_is_refused(self):
        obj, bad = dp.validate(
            self.good(overview="가" * (tr.DIGEST_OVERVIEW_MAX + 1)), self.VOCAB, 5)
        self.assertIsNone(obj)
        self.assertTrue(any("overview" in b for b in bad))

    def test_empty_values_are_refused(self):
        obj, bad = dp.validate({"headline": "", "overview": ""}, self.VOCAB, 5)
        self.assertIsNone(obj)
        self.assertIn("headline 이 없다", bad)
        self.assertIn("overview 가 없다", bad)

    def test_a_reply_that_is_not_json_is_refused(self):
        self.assertEqual((None, ["JSON 이 아니다"]), dp.validate(None, self.VOCAB, 5))

    def test_half_written_sections_are_thrown_away_not_kept(self):
        obj, _ = dp.validate(
            self.good(sections=[{"title": "가", "body": ""}, {"title": "", "body": "나"}]),
            self.VOCAB, 5)
        self.assertEqual([], obj["sections"])

    def test_the_number_of_keywords_is_capped(self):
        vocab = ["말%d" % i for i in range(20)]
        obj, _ = dp.validate(self.good(keywords=vocab), vocab, 5)
        self.assertEqual(tr.DIGEST_KEYWORDS[1], len(obj["keywords"]))


class DryRunTest(unittest.TestCase):
    def test_dry_run_never_calls_the_model(self):
        """LLM 을 먼저 부르고 결과만 버리는 dry-run 은 이 저장소에서 결함으로 기록됐다."""
        state = {
            "categories": CATEGORIES,
            "threads": threads(projects=2),
            "reports": {},
            "dates": {},
            "secondary": {},
            "prose": {},
            "vocabulary": ["가"],
        }
        with patch.object(dp, "call_claude") as fake:
            got = dp.rewrite("projects", state, "opus", 60, dry_run=True)
        self.assertIsNone(got)
        fake.assert_not_called()


class WriteTest(unittest.TestCase):
    BEFORE = {"digests": {
        "projects": {"headline": "옛 제목", "overview": "옛 글", "keywords": ["가"]},
        "hwp": {"headline": "한글", "overview": "한글 글", "keywords": ["나"]},
    }}

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.path = self.dir / "topic-digests.json"
        self.path.write_text(json.dumps(self.BEFORE, ensure_ascii=False),
                             encoding="utf-8")
        # `tag_surgery.OUT` 도 함께 돌린다. 백업 폴더는 그쪽이 만들므로, 여기만
        # 돌리면 검사가 **진짜 output/ 에** 백업 폴더를 만든다 — 그리고 같은 날
        # 같은 이름이라 그날의 진짜 되돌릴 지점을 검사 자료로 덮는다.
        self._saved = (dp.DIGESTS, dp.OUT, ts.OUT)
        dp.DIGESTS, dp.OUT, ts.OUT = self.path, self.dir, self.dir

    def tearDown(self):
        dp.DIGESTS, dp.OUT, ts.OUT = self._saved

    def read(self):
        return json.loads(self.path.read_text(encoding="utf-8"))["digests"]

    def test_only_the_rewritten_category_changes(self):
        new = {"headline": "새 제목", "overview": "새 글", "sections": [],
               "keywords": ["다"], "as_of": {"date": "2026-09-04",
                                            "thread_count": 106,
                                            "last_thread_id": "t-999"}}
        dp.write_digests({}, {"projects": new}, "20260904")
        after = self.read()
        self.assertEqual(new, after["projects"])
        self.assertEqual(json.dumps(self.BEFORE["digests"]["hwp"], ensure_ascii=False),
                         json.dumps(after["hwp"], ensure_ascii=False))

    def test_the_backup_holds_the_file_as_it_was(self):
        backup = dp.write_digests({}, {"projects": {"headline": "새"}}, "20260904")
        saved = json.loads((backup / "topic-digests.json").read_text(encoding="utf-8"))
        self.assertEqual(self.BEFORE, saved)

    def test_a_missing_file_is_created(self):
        self.path.unlink()
        dp.write_digests({}, {"projects": {"headline": "새"}}, "20260904")
        self.assertEqual({"projects": {"headline": "새"}}, self.read())


if __name__ == "__main__":
    unittest.main()
