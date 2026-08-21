# -*- coding: utf-8 -*-
"""유산 태그 재부여 — 태그만 바뀌고 글은 그대로인지 묶어 둔다.

이 스크립트는 보고서 300편을 한 번에 만진다. 그러니 두 가지가 지켜져야 한다.

  · **글이 안 바뀐다** — keywords 줄 하나만 바뀌고 본문·제목·요지·줄바꿈은
    그대로다. 이 폴더는 CRLF 이고, 한 줄이라도 LF 로 바뀌면 git diff 가
    파일 전체로 번져 무엇을 고쳤는지 안 보인다.
  · **지어낸 말이 안 들어온다** — 갚으려는 빚이 1회짜리 태그이므로, 모델이
    새 말을 지어 오면 그것을 받으면 안 된다.
"""
from __future__ import annotations

import unittest

from scripts.retag_reports import (
    replace_keywords_line,
    sanitize,
    select_targets,
    tag_stats,
)
from scripts.topic_reports import TAG_COUNT_MAX, parse_report

CRLF = (
    "---\r\n"
    "title: Gemini 2.5 flash와 3 flash 성능 비교\r\n"
    "summary: 두 모델을 나란히 돌리는 비교 도구: 3이 낫다\r\n"
    "keywords: Gemini, 모델 비교, flash\r\n"
    "---\r\n"
    "\r\n"
    "김종원이 두 모델을 **같은 입력으로** 돌려 비교했다.\r\n"
    "\r\n"
    "> keywords: 이 줄은 본문이다\r\n"
)


class ReplaceKeywordsLineTest(unittest.TestCase):
    def test_only_the_keywords_line_changes(self):
        out = replace_keywords_line(CRLF, ["제미나이", "모델 비교"])
        self.assertIn("keywords: 제미나이, 모델 비교\r\n", out)
        self.assertNotIn("keywords: Gemini", out)
        # 나머지 줄은 글자 그대로
        for line in CRLF.split("\r\n"):
            if line.startswith("keywords:"):
                continue
            self.assertIn(line, out, line)

    def test_crlf_survives(self):
        """`$` 로 끊으면 그 줄만 LF 가 된다 — 그러면 diff 가 파일 전체로 번진다."""
        out = replace_keywords_line(CRLF, ["제미나이", "모델 비교"])
        self.assertEqual(out.count("\r\n"), CRLF.count("\r\n"))
        # 마지막 조각(파일 끝) 말고는 모두 \r 로 끝나야 한다 = 홀로 선 LF 가 없다
        bare = [line for line in out.split("\n")[:-1] if not line.endswith("\r")]
        self.assertEqual(bare, [], out.encode("unicode_escape"))

    def test_body_line_starting_with_keywords_is_untouched(self):
        out = replace_keywords_line(CRLF, ["제미나이", "모델 비교"])
        self.assertIn("> keywords: 이 줄은 본문이다", out)

    def test_title_with_colon_still_parses(self):
        """프론트매터는 첫 콜론에서만 자르는 형식이다 — 바꾼 뒤에도 읽혀야 한다."""
        out = replace_keywords_line(CRLF, ["제미나이", "모델 비교"])
        got = parse_report(out, "t-000")
        self.assertEqual(got["keywords"], ["제미나이", "모델 비교"])
        self.assertEqual(got["title"], "Gemini 2.5 flash와 3 flash 성능 비교")
        self.assertEqual(got["summary"], "두 모델을 나란히 돌리는 비교 도구: 3이 낫다")
        self.assertIn("같은 입력으로", got["report"])

    def test_lf_file_stays_lf(self):
        out = replace_keywords_line(CRLF.replace("\r\n", "\n"), ["제미나이", "모델 비교"])
        self.assertNotIn("\r", out)

    def test_missing_front_matter_raises(self):
        with self.assertRaises(ValueError):
            replace_keywords_line("본문만 있는 파일\n", ["가", "나"])

    def test_missing_keywords_line_raises(self):
        text = "---\r\ntitle: 제목\r\nsummary: 요지\r\n---\r\n\r\n본문\r\n"
        with self.assertRaises(ValueError):
            replace_keywords_line(text, ["가", "나"])


VOCAB = {"제미나이", "모델 비교", "클로드", "앱 제작", "파이어베이스", "바이브코딩", "깃허브"}


def keys(names):
    from scripts.tags import fold
    return {fold(n) for n in names}


class SanitizeTest(unittest.TestCase):
    def run_it(self, proposed, current=("차량운행일지", "Gemini 3 프로 성능"),
               people=("김종원",), places=("○○복지관",), categories=("AI 모델·요금제",),
               corpus=("MCP",)):
        from scripts.tags import fold
        return sanitize(list(proposed), list(current), keys(VOCAB), set(people),
                        {fold(p) for p in places}, set(categories), keys(corpus))

    def test_vocabulary_words_pass(self):
        tags, notes = self.run_it(["제미나이", "모델 비교"])
        self.assertEqual(tags, ["제미나이", "모델 비교"])
        self.assertEqual(notes, [])

    def test_invented_word_is_dropped(self):
        """어휘에도 없고 지금 붙어 있지도 않은 말 = 새 1회짜리 태그다."""
        tags, notes = self.run_it(["제미나이", "모델 비교", "플래시 벤치마크"])
        self.assertEqual(tags, ["제미나이", "모델 비교"])
        self.assertEqual(len(notes), 1)
        self.assertIn("지어낸", notes[0])

    def test_one_existing_unique_word_survives(self):
        tags, _ = self.run_it(["제미나이", "모델 비교", "차량운행일지"])
        self.assertEqual(tags, ["제미나이", "모델 비교", "차량운행일지"])

    def test_a_rare_word_from_another_report_may_spread_here(self):
        """말뭉치에 한 번 있는 말이 두 번째 편을 얻는 것이 이 작업의 목적이다.

        '그 편에 붙어 있던 말' 로만 좁혀 받았더니, 다른 편의 1회짜리 태그를 이 편으로
        넓히려는 제안까지 '지어낸 말' 로 버렸다 — 실측 2026-08-21: 그렇게 버린 13개 중
        8개가 말뭉치에 한 번씩 있는 말이었다. 두 번 쓰이면 추천 어휘에 오른다.
        """
        tags, notes = self.run_it(["제미나이", "MCP"])
        self.assertEqual(tags, ["제미나이", "MCP"])
        self.assertEqual(notes, [])

    def test_a_word_nowhere_in_the_corpus_is_still_dropped(self):
        tags, notes = self.run_it(["제미나이", "모델 비교", "페르소나 평가"])
        self.assertEqual(tags, ["제미나이", "모델 비교"])
        self.assertTrue(any("지어낸" in n for n in notes))

    def test_second_unique_word_is_dropped(self):
        tags, notes = self.run_it(["제미나이", "차량운행일지", "Gemini 3 프로 성능"])
        self.assertEqual(tags, ["제미나이", "차량운행일지"])
        self.assertTrue(any("둘 이상" in n for n in notes))

    def test_person_place_category_are_dropped(self):
        tags, notes = self.run_it(
            ["제미나이", "김종원", "○○복지관", "AI 모델·요금제", "모델 비교"])
        self.assertEqual(tags, ["제미나이", "모델 비교"])
        self.assertEqual(len(notes), 3)

    def test_duplicates_fold_together(self):
        tags, _ = self.run_it(["제미나이", "Gemini", " 제미나이 "])
        self.assertEqual(tags, ["제미나이"])

    def test_cap_at_max(self):
        tags, _ = self.run_it(list(VOCAB) + ["차량운행일지"])
        self.assertEqual(len(tags), TAG_COUNT_MAX)

    def test_junk_values_do_not_crash(self):
        tags, _ = self.run_it(["", None, "  ", "제미나이", 7, "클로드"])
        self.assertEqual(tags, ["제미나이", "클로드"])

    def test_non_list_reply_gives_nothing(self):
        from scripts.tags import fold
        tags, _ = sanitize("제미나이", [], keys(VOCAB), set(), set(), set())
        self.assertEqual(tags, [])


class SelectTargetsTest(unittest.TestCase):
    def state(self):
        return {
            "reports": {
                # 어휘가 없던 달 + 어휘 밖 태그 → 대상
                "t-001": {"keywords": ["Gemini 3 프로 성능", "제미나이"]},
                # 어휘가 없던 달인데 태그가 이미 전부 어휘 안 → 흔들지 않는다
                "t-002": {"keywords": ["제미나이", "클로드"]},
                # 어휘가 생긴 뒤 → 그 편의 '새 태그 1개' 는 정당하다
                "t-003": {"keywords": ["새로운 도구", "제미나이"]},
                # topics.json 에 스레드가 없는 보고서
                "t-999": {"keywords": ["아무 말"]},
            },
            "by_id": {
                "t-001": {"id": "t-001", "message_ids": ["m1"]},
                "t-002": {"id": "t-002", "message_ids": ["m2"]},
                "t-003": {"id": "t-003", "message_ids": ["m3"]},
            },
        }

    def test_picks_only_pre_vocabulary_reports_with_outside_tags(self):
        dates = {"m1": "2026-05-02", "m2": "2026-05-03", "m3": "2026-08-11"}
        got = select_targets(self.state(), sorted(VOCAB), dates, since="2026-08")
        self.assertEqual(got, ["t-001"])

    def test_thread_month_uses_the_earliest_message(self):
        state = self.state()
        state["by_id"]["t-001"]["message_ids"] = ["m9", "m1"]
        dates = {"m1": "2026-05-02", "m9": "2026-08-30", "m2": "2026-05-03",
                 "m3": "2026-08-11"}
        got = select_targets(state, sorted(VOCAB), dates, since="2026-08")
        self.assertEqual(got, ["t-001"])

    def test_report_without_a_thread_is_skipped(self):
        dates = {"m1": "2026-05-02", "m2": "2026-05-03", "m3": "2026-08-11"}
        got = select_targets(self.state(), sorted(VOCAB), dates, since="2026-08")
        self.assertNotIn("t-999", got)


class TagStatsTest(unittest.TestCase):
    def test_counts_kinds_after_folding(self):
        got = tag_stats(
            {"a": ["제미나이", "Gemini"], "b": ["제미나이", "차량운행일지"]},
            keys(VOCAB),
        )
        self.assertEqual(got["reports"], 2)
        self.assertEqual(got["tags"], 4)
        # 'Gemini' 는 '제미나이' 와 한 덩어리다
        self.assertEqual(got["kinds"], 2)
        self.assertEqual(got["once"], 1)      # 차량운행일지
        self.assertEqual(got["outside"], 1)   # 차량운행일지

    def test_empty(self):
        got = tag_stats({}, keys(VOCAB))
        self.assertEqual((got["tags"], got["kinds"], got["once"]), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
