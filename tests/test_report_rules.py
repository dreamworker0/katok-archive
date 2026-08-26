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

    def test_both_prompts_carry_the_same_tag_rules(self):
        """태그 규칙도 한 곳에서 나와야 한다.

        예전에는 두 프롬프트가 각자 'keywords 는 2~6개' 한 줄만 적어 두었고, 둘 다
        무슨 말을 쓸지는 말하지 않았다. 그 결과가 태그 1,224종 중 1,090종이 한 번만
        쓰인 상태였다(실측 2026-08-04). 규칙이 다시 갈라지면 한쪽만 어휘를 보게 된다.
        """
        rules = cu.tag_rules_now()
        classify = cu.build_prompt(MSGS, CATS, [], [])
        report = cu.build_report_prompt(
            {"id": "t-1", "title": "제목", "summary": "요지", "category": "projects"},
            MSGS, [], None)
        for name, prompt in (("분류", classify), ("보고서", report)):
            self.assertIn(rules, prompt, "%s 프롬프트가 공용 태그 규칙을 안 읽는다" % name)

    def test_tag_rule_shows_the_vocabulary_and_caps_new_words(self):
        rules = tr.tag_rules(["안티그래비티", "앱스스크립트"])
        self.assertIn("안티그래비티 · 앱스스크립트", rules)
        self.assertIn("%d개까지만" % tr.NEW_TAGS_ALLOWED, rules)

    def test_tag_debt_numbers_are_measured_not_baked_in(self):
        """규칙 글의 숫자는 재서 넣는다.

        '1,224종 중 1,090종' 이 박혀 있던 동안 실제로는 1,091종 중 947종이었다
        (실측 2026-08-21). 규칙 글의 숫자가 틀리면 규칙이 근거를 잃는다.
        """
        rules = tr.tag_rules(["안티그래비티"], 1091, 947)
        self.assertIn("1,091종", rules)
        self.assertIn("947종", rules)
        # 규칙 글에 박힌 숫자가 남아 있으면 안 된다(주석의 옛 실측은 기록이므로 괜찮다).
        self.assertNotIn("1,224", rules, "옛 숫자가 규칙 글에 아직 박혀 있다")
        # 못 재면 숫자 없이 말한다 — 틀린 숫자보다 낫다.
        blind = tr.tag_rules(["안티그래비티"])
        self.assertNotIn("종 중", blind)
        self.assertNotRegex(blind, r"\d[\d,]*종")

    def test_tag_rule_without_a_vocabulary_does_not_tell_a_lie(self):
        # 없는 목록에서 고르라고 하면 지시가 거짓이 된다(새 아카이브·첫 실행).
        rules = tr.tag_rules([])
        self.assertNotIn("이미 쓰이는 태그", rules)
        self.assertIn("keywords", rules)

    def test_vocabulary_failure_does_not_stop_classification(self):
        # 어휘를 못 읽는 것이 그날 분류를 막을 이유는 없다.
        try:
            cu.tag_corpus.__dict__["_cache"] = None
            real, cu.TOPICS = cu.TOPICS, cu.ROOT / "없는파일.json"
            self.assertEqual([], cu.tag_vocabulary())
            self.assertEqual(([], 0, 0), cu.tag_corpus())
        finally:
            cu.TOPICS = real
            cu.tag_corpus.__dict__["_cache"] = None

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

    def test_long_prose_from_a_short_conversation_is_caught(self):
        """건수만 보면 새는 구멍 — 대화 5건인데 한 문단 450자.

        2026-07-28 지적: 대화 5건이라 인용(6건)·절 나눔(10건) 기준을 둘 다 비껄러
        나갔다. 짧은 대화라도 길게 쓰면 구조가 필요하다.
        """
        sentence = "한 문단으로 길게 이어 쓴 글이다. "
        # 250자를 넘기면 인용부터 요구한다
        gaps = tr.structure_gaps([{"id": "t-347", "count": 5, "report": sentence * 18}])
        self.assertEqual(gaps[0][2], "인용")
        # 400자를 넘기면 절·목록까지 요구한다
        gaps = tr.structure_gaps([{"id": "t-347", "count": 5, "report": sentence * 30}])
        self.assertEqual(gaps[0][2], "인용·절 나눔")

    def test_list_counts_as_structure_even_without_headings(self):
        # 절 대신 목록으로 갈라 썼으면 그것도 눈으로 짚을 구조다.
        body = "짧은 도입.\n\n> 인용\n\n" + "\n".join("- 항목 %d" % i for i in range(8)) + \
            "\n\n" + "마무리 문단이다. " * 20
        self.assertEqual(tr.structure_gaps([
            {"id": "t-1", "count": 5, "report": body}]), [])

    def test_rules_state_the_length_thresholds_too(self):
        self.assertIn(str(tr.QUOTE_REQUIRED_CHARS) + "자", tr.REPORT_RULES)
        self.assertIn(str(tr.SECTION_REQUIRED_CHARS) + "자", tr.REPORT_RULES)

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


class AiReportTests(unittest.TestCase):
    """AI 보고서(output/ai-reports/) 로더와 규칙.

    이 테스트가 있는 이유: 통과 기준이 '두 모델의 합의' 였던 판이 오류를
    통과시켰다(2026-08-27). 두 모델이 파이어베이스 전송량을 "Blaze 는 월 10GB" 로
    나란히 틀렸고, 동의했다는 사실이 그것을 걸러 주지 못했다. 기준은 원 출처다.
    """

    def _write(self, lines):
        import tempfile, pathlib
        d = pathlib.Path(tempfile.mkdtemp())
        (d / "t-001.md").write_text(chr(10).join(lines), encoding="utf-8")
        return d

    def test_ai_report_needs_no_title_or_summary(self):
        """사람 보고서 파서와 달라야 한다 — 제목은 사람 쪽 것을 쓴다."""
        got = tr.load_ai_reports(self._write(
            ["---", "checked: 2026-08-27", "models: a, b", "---",
             "", "본문이다.", ""]))
        self.assertEqual(got["t-001"]["report"], "본문이다.")
        self.assertEqual(got["t-001"]["checked"], "2026-08-27")
        self.assertEqual(got["t-001"]["models"], "a, b")

    def test_empty_body_is_skipped(self):
        """프론트매터만 있고 할 말이 없으면 싣지 않는다."""
        d = self._write(["---", "checked: 2026-08-27", "---", "", "   ", ""])
        self.assertEqual(tr.load_ai_reports(d), {})

    def test_missing_folder_is_not_an_error(self):
        import pathlib
        self.assertEqual(tr.load_ai_reports(pathlib.Path("없는폴더")), {})

    def test_apply_does_not_touch_the_human_title(self):
        """화면에 보이는 제목은 사람이 쓴 것 하나여야 한다."""
        threads = [{"id": "t-001", "title": "사람 제목", "summary": "사람 요지",
                    "keywords": ["가"], "report": "사람 본문"}]
        n = tr.apply_ai_reports(threads, {
            "t-001": {"report": "기계 본문", "checked": "2026-08-27",
                      "models": "a, b", "method": ""}})
        self.assertEqual(n, 1)
        t = threads[0]
        self.assertEqual(t["title"], "사람 제목")
        self.assertEqual(t["summary"], "사람 요지")
        self.assertEqual(t["keywords"], ["가"])
        self.assertEqual(t["report"], "사람 본문")
        self.assertEqual(t["ai_report"], "기계 본문")

    def test_unknown_id_is_ignored(self):
        """주제가 합쳐지거나 사라져도 파이프라인이 멈추면 안 된다."""
        threads = [{"id": "t-001"}]
        self.assertEqual(tr.apply_ai_reports(threads, {"t-999": {
            "report": "x", "checked": "", "models": "", "method": ""}}), 0)

    def test_rule_passes_on_sources_not_on_agreement(self):
        """'합의하면 통과' 로 되돌아가면 여기서 걸린다."""
        self.assertIn("원 출처", tr.AI_REPORT_RULES)
        self.assertIn("합의했다는 사실은 근거가 아닙니다", tr.AI_REPORT_RULES)
        self.assertIn("확인하지 못한 것", tr.AI_REPORT_RULES)

if __name__ == "__main__":
    unittest.main()
