# -*- coding: utf-8 -*-
"""AI 검증 주석 자동 생성 — 규칙이 코드에서 실제로 지켜지는지.

이 테스트가 있는 이유: 이 글의 규칙은 '원 출처를 연 것만 단정한다' 하나인데,
그것을 프롬프트 문장으로만 적어 두면 지켜지는지 알 수 없다. 여기서 고정하는 것은
**코드가 그 규칙을 강제하는 자리들**이다 — 열린 주소와 안 열린 주소를 갈라 주는지,
경유 주소 대신 끝 주소를 주는지, 미발행 원문을 밖으로 내보내지 않는지.

망은 타지 않는다. open_url 은 실제로 열어 보는 함수라 테스트가 인터넷에 기대면
비행기에서 갱신이 깨진다 — 그 함수는 부르는 쪽의 계약만 본다.
"""
import json
import tempfile
import unittest
from pathlib import Path

from scripts import ai_reports as ar


class UrlExtractTests(unittest.TestCase):
    def test_keeps_order_and_drops_duplicates(self):
        got = ar.extract_urls("먼저 https://a.kr 다음 https://b.kr 또 https://a.kr")
        self.assertEqual(got, ["https://a.kr", "https://b.kr"])

    def test_trailing_punctuation_is_not_part_of_the_url(self):
        """문장 끝의 마침표·괄호가 주소에 붙으면 멀쩡한 주소가 안 열린다."""
        self.assertEqual(ar.extract_urls("보라 (https://a.kr/x)."), ["https://a.kr/x"])
        self.assertEqual(ar.extract_urls("끝 https://a.kr/y,"), ["https://a.kr/y"])

    def test_caps_how_many_we_open(self):
        text = " ".join("https://x%d.kr" % i for i in range(30))
        self.assertEqual(len(ar.extract_urls(text)), ar.MAX_LINKS_PER_REPORT)

    def test_markdown_link_url_is_extracted_without_the_bracket(self):
        self.assertEqual(ar.extract_urls("[이름](https://a.kr/z)"), ["https://a.kr/z"])


class SkipSignalTests(unittest.TestCase):
    """'쓸 것이 없다' 는 신호는 **첫 줄일 때만** 듣는다.

    본문 어딘가에 그 낱말이 들어 있는지를 보면(처음에 그렇게 짰다) 그 말을 인용한
    멀쩡한 보고서가 통째로 버려진다.
    """

    def test_bare_signal_is_a_skip(self):
        for t in ("검증대상없음", "`검증대상없음`", "- 검증대상없음", "  검증대상없음  "):
            self.assertTrue(ar.is_skip(t), t)

    def test_signal_inside_a_real_report_is_not_a_skip(self):
        body = "## 확인한 것\n다른 모델은 검증대상없음 이라고 답했으나 아니다."
        self.assertFalse(ar.is_skip(body))

    def test_empty_is_not_a_skip(self):
        self.assertFalse(ar.is_skip(""))
        self.assertFalse(ar.is_skip("   \n  "))


class BodyCleanTests(unittest.TestCase):
    def test_model_added_frontmatter_is_removed(self):
        """프론트매터가 두 겹이 되면 파서가 본문을 통째로 오해한다."""
        self.assertEqual(ar.clean_body("---\ntitle: x\n---\n\n## 제목\n본문"),
                         "## 제목\n본문")

    def test_code_fence_is_removed(self):
        self.assertEqual(ar.clean_body("```markdown\n## 제목\n본문\n```"),
                         "## 제목\n본문")

    def test_plain_body_is_untouched(self):
        self.assertEqual(ar.clean_body("## 제목\n본문"), "## 제목\n본문")


class TargetPickTests(unittest.TestCase):
    """이미 쓴 것은 건드리지 않는다 — 사람이 손본 글이 밤새 사라지면 안 된다."""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self._dir, ar.AI_REPORTS_DIR = ar.AI_REPORTS_DIR, self.d
        self._led, ar.SKIP_LEDGER = ar.SKIP_LEDGER, self.d / "skips.json"
        self.threads = [{"id": "t-%03d" % i, "category": "projects"}
                        for i in (1, 2, 3, 4)]

    def tearDown(self):
        ar.AI_REPORTS_DIR, ar.SKIP_LEDGER = self._dir, self._led

    def test_existing_reports_are_left_alone(self):
        (self.d / "t-004.md").write_text("있다", encoding="utf-8")
        got = [t["id"] for t in ar.pick_targets(self.threads, 10)]
        self.assertNotIn("t-004", got)

    def test_skipped_threads_are_not_asked_again(self):
        """건너뛴 것을 기억하지 않으면 매일 밤 같은 대화를 다시 물어본다."""
        ar.SKIP_LEDGER.write_text(json.dumps({"t-003": {"why": "x"}}),
                                  encoding="utf-8")
        got = [t["id"] for t in ar.pick_targets(self.threads, 10)]
        self.assertNotIn("t-003", got)

    def test_limit_is_respected(self):
        self.assertEqual(len(ar.pick_targets(self.threads, 2)), 2)

    def test_newest_first(self):
        got = [t["id"] for t in ar.pick_targets(self.threads, 2)]
        self.assertEqual(got, ["t-004", "t-003"])

    def test_explicit_ids_override_everything(self):
        """사람이 이름을 대고 부르면 이미 있어도 다시 쓴다."""
        (self.d / "t-002.md").write_text("있다", encoding="utf-8")
        got = [t["id"] for t in ar.pick_targets(self.threads, 1, ids=["t-002"])]
        self.assertEqual(got, ["t-002"])


class PromptContractTests(unittest.TestCase):
    THREAD = {"id": "t-001", "title": "제목", "category": "projects"}
    REPORT = "사람이 쓴 보고서 본문이다."

    def test_search_prompt_carries_only_the_published_report(self):
        """미발행 대화 원문을 외부 서비스로 내보내지 않는다 — 사람이 정한 방침이다."""
        p = ar.build_search_prompt(self.THREAD, self.REPORT)
        self.assertIn(self.REPORT, p)
        self.assertIn("search_web", p)
        # 원문을 넘길 자리가 아예 없다는 것을 계약으로 못 박는다.
        self.assertNotIn("message", p.lower())

    def test_search_prompt_asks_for_urls_and_forbids_making_them_up(self):
        p = ar.build_search_prompt(self.THREAD, self.REPORT)
        self.assertIn("근거 URL", p)
        self.assertIn("지어내지 마라", p)

    def test_search_prompt_does_not_dig_into_people(self):
        self.assertIn("개인의 경력·신원은 캐지 마라",
                      ar.build_search_prompt(self.THREAD, self.REPORT))

    def test_compose_prompt_separates_opened_from_failed(self):
        """이 갈라 주기가 규칙을 강제하는 자리다. 한 덩어리로 주면 규칙이 사라진다."""
        links = [
            {"url": "https://open.kr", "final": "https://open.kr", "ok": True,
             "status": 200, "note": ""},
            {"url": "https://dead.kr", "final": "https://dead.kr", "ok": False,
             "status": 404, "note": "HTTP 404"},
        ]
        p = ar.build_compose_prompt(self.THREAD, self.REPORT, "찾은 것", links)
        opened = p.index("열린 주소(단정의 근거로 써도 되는 것):")
        failed = p.index("열리지 않은 주소(근거로 쓸 수 없다):")
        self.assertLess(opened, failed)
        self.assertIn("https://open.kr", p[opened:failed])
        self.assertIn("https://dead.kr", p[failed:])

    def test_compose_prompt_hands_over_the_final_url_not_the_redirector(self):
        """경유 주소를 근거에 적으면 읽는 사람은 어디로 가는지 알 수 없다."""
        links = [{"url": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/AAA",
                  "final": "https://ko.wikipedia.org/wiki/GS25",
                  "ok": True, "status": 200, "note": ""}]
        p = ar.build_compose_prompt(self.THREAD, self.REPORT, "찾은 것", links)
        self.assertIn("https://ko.wikipedia.org/wiki/GS25", p)
        self.assertNotIn("grounding-api-redirect", p)

    def test_compose_prompt_says_agreement_is_not_evidence(self):
        """이 한 줄이 2026-08-27 의 두 사고에서 얻은 것이다."""
        p = ar.build_compose_prompt(self.THREAD, self.REPORT, "찾은 것", [])
        self.assertIn("동의는 근거가 아니다", p)
        self.assertIn("열린 주소로 뒷받침되는 것만 단정하라", p)

    def test_compose_prompt_carries_the_shared_rules(self):
        """규칙 원본은 topic_reports 하나다. 여기서 다시 적으면 또 갈라진다."""
        from scripts.topic_reports import AI_REPORT_RULES
        p = ar.build_compose_prompt(self.THREAD, self.REPORT, "", [])
        self.assertIn(AI_REPORT_RULES, p)

    def test_compose_prompt_reports_no_open_links_honestly(self):
        p = ar.build_compose_prompt(self.THREAD, self.REPORT, "찾은 것", [])
        self.assertIn("열린 주소: 없음", p)


class WriteTests(unittest.TestCase):
    def test_frontmatter_is_written_so_the_loader_can_read_it(self):
        d = Path(tempfile.mkdtemp())
        old, ar.AI_REPORTS_DIR = ar.AI_REPORTS_DIR, d
        try:
            p = ar.write_report("t-001", "## 제목\n본문", "a, b", "2026-08-27", "방법")
            from scripts.topic_reports import load_ai_reports
            got = load_ai_reports(d)
            self.assertEqual(got["t-001"]["report"], "## 제목\n본문")
            self.assertEqual(got["t-001"]["models"], "a, b")
            self.assertEqual(got["t-001"]["checked"], "2026-08-27")
            self.assertTrue(p.exists())
        finally:
            ar.AI_REPORTS_DIR = old


if __name__ == "__main__":
    unittest.main()
