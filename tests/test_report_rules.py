# -*- coding: utf-8 -*-
"""보고서 구조 규칙 — 규칙이 한 곳에 있고, 두 프롬프트가 같은 것을 읽고,
검사가 실제로 걸러내는지.

이 테스트가 있는 이유: 규칙이 두 곳에 따로 적혀 있어서 밤 자동 갱신이 쓰는 쪽만
낡은 규칙을 읽었다. 그래서 자동 갱신 보고서는 한 덩어리 산문이고 사진·링크가
전부 글 끝에 모였다(2026-07-27). 다시 갈라지면 여기서 걸린다.
"""
import unittest

from scripts import classify_unsorted as cu
from scripts import topic_reports as tr


CATS = [{"id": "projects", "label": "프로젝트·결과물"}]
MSGS = [{"id": "msg-1", "date": "2026-07-27", "time": "23:40",
         "nickname": "김종원", "text": "테스트"}]


class RuleSourceTests(unittest.TestCase):
    def test_both_prompts_carry_the_same_rules(self):
        classify = cu.build_prompt(MSGS, CATS, [], [])
        report = cu.build_report_prompt(
            {"id": "t-1", "title": "제목", "summary": "요지", "category": "projects"},
            MSGS, [], None)
        for name, prompt in (("분류", classify), ("보고서", report)):
            self.assertIn(tr.REPORT_RULES, prompt,
                          "%s 프롬프트가 공용 규칙을 안 읽는다" % name)

    def test_old_rule_that_pushed_media_to_the_bottom_is_gone(self):
        classify = cu.build_prompt(MSGS, CATS, [], [])
        self.assertNotIn("화면 아래에 따로 붙습니다", classify)

    def test_quote_limit_has_one_source(self):
        self.assertEqual(cu.MAX_VERBATIM_CHARS, tr.MAX_VERBATIM_CHARS)

    def test_rules_state_the_same_numbers_the_check_uses(self):
        self.assertIn(str(tr.QUOTE_REQUIRED_FROM) + "건 이상", tr.REPORT_RULES)
        self.assertIn(str(tr.SECTION_REQUIRED_FROM) + "건 이상", tr.REPORT_RULES)


class ShortReportAssetTests(unittest.TestCase):
    """문단이 하나뿐인 보고서는 자료가 글과 함께 있어야 한다.

    인용 기준 배치는 인용이 짧으면 건너뛴다. 그래서 두 건 대화의 한 문단짜리
    보고서에서 링크가 글과 떨어져 아래 상자로 밀렸다(2026-07-28 지적).
    """

    def test_link_lands_after_the_only_paragraph(self):
        body = "김종원이 윤문 도구를 공유했다. 비용 문제를 해결했다고 한다."
        msgs = [{"id": "msg-001510", "text": "https://urimal.vercel.app/ 써보세요",
                 "urls": ["https://urimal.vercel.app/"], "kind": "text",
                 "nickname": "김종원"}]
        out = tr.place_context_anchors(body, msgs)
        self.assertTrue(out.rstrip().endswith("![[link:msg-001510]]"), out)

    def test_photo_lands_after_two_paragraphs_too(self):
        body = "첫 문단이다.\n\n둘째 문단이다."
        msgs = [{"id": "msg-000002", "kind": "image", "text": "", "nickname": "호야"}]
        self.assertIn("![[msg-000002]]", tr.place_context_anchors(body, msgs))

    def test_long_reports_are_left_to_judgment(self):
        # 문단이 여럿이면 '어느 문단 뒤인가'가 판단이다. 기계가 아무 데나 놓으면
        # 글이 거짓말을 한다 — 그럴 때는 자료를 글 끝에 두는 편이 낫다.
        body = "\n\n".join("문단 %d 이다." % i for i in range(5))
        msgs = [{"id": "msg-000003", "kind": "image", "text": "", "nickname": "호야"}]
        self.assertNotIn("![[", tr.place_context_anchors(body, msgs))

    def test_manual_anchor_is_not_duplicated(self):
        body = "한 문단이다.\n\n![[msg-000004]]"
        msgs = [{"id": "msg-000004", "kind": "image", "text": "", "nickname": "호야"}]
        out = tr.place_context_anchors(body, msgs)
        self.assertEqual(out.count("![[msg-000004]]"), 1, out)


class StructureCheckTests(unittest.TestCase):
    def test_long_prose_without_quote_or_section_is_caught(self):
        gaps = tr.structure_gaps([
            {"id": "t-1", "count": 12, "report": "한 덩어리로 길게 쓴 산문이다. " * 20},
        ])
        self.assertEqual(gaps[0][2], "인용·절 나눔")

    def test_structured_report_passes(self):
        body = "## 무슨 일이 있었나\n\n김종원이 알렸다.\n\n> 짧은 인용\n\n- 정리\n"
        self.assertEqual(tr.structure_gaps([
            {"id": "t-1", "count": 30, "report": body}]), [])

    def test_short_conversations_are_not_required_to_have_structure(self):
        self.assertEqual(tr.structure_gaps([
            {"id": "t-1", "count": 3, "report": "두 문장으로 충분하다."}]), [])

    def test_quote_is_required_before_sections_are(self):
        # 6~9건: 인용은 있어야 하고 절 나눔은 아직 아니다
        gaps = tr.structure_gaps([{"id": "t-1", "count": 7, "report": "산문뿐이다."}])
        self.assertEqual(gaps[0][2], "인용")

    def test_missing_report_is_not_a_structure_problem(self):
        # 보고서가 없는 것은 다른 검사(fill_missing_reports)의 몫이다
        self.assertEqual(tr.structure_gaps([{"id": "t-1", "count": 30, "report": ""}]), [])


if __name__ == "__main__":
    unittest.main()
