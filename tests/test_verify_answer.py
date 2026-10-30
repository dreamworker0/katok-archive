# -*- coding: utf-8 -*-
"""scripts/verify_answer.py — 실시간 검증. 모델을 부르지 않고 '틀리면 조용히 새는' 것만 본다."""
import unittest

from scripts import verify_answer as V


def link(url, ok=True, root=False, blocked=False, final=None, note=""):
    return {"url": url, "final": final or url, "ok": ok, "root": root,
            "blocked": blocked, "status": 200 if ok else 404, "note": note}


class LinkLines(unittest.TestCase):
    def test_only_opened_inner_pages_get_numbers(self):
        lines, sources = V.link_lines([
            link("https://a.example/page"),
            link("https://b.example/", root=True),
            link("https://c.example/x", ok=False, note="HTTP 404"),
            link("http://10.0.0.1/x", ok=False, blocked=True),
        ])
        self.assertEqual(sources, [{"n": 1, "url": "https://a.example/page"}])
        text = "\n".join(lines)
        self.assertIn("[1] https://a.example/page", text)
        self.assertIn("대문만", text)
        self.assertNotIn("10.0.0.1 (", text)      # 막은 까닭(풀린 IP)은 알리지 않는다

    def test_login_wall_is_not_a_source(self):
        _, sources = V.link_lines([
            link("https://one.google.com/ai/invite",
                 final="https://accounts.google.com/v3/signin/identifier?continue=x"),
            link("https://site.example/login?next=/a"),
            link("https://gemini.google/students/"),
        ])
        self.assertEqual([s["url"] for s in sources], ["https://gemini.google/students/"])

    def test_is_login_does_not_catch_ordinary_paths(self):
        self.assertFalse(V.is_login("https://blog.example/authors/kim"))
        self.assertFalse(V.is_login("https://www.coursera.org/professional-certificates/google-ai"))


class Clean(unittest.TestCase):
    def test_urls_and_anchors_are_removed_from_body(self):
        body = V.clean("확인됐어요 https://evil.example/x (출처 1)\n![[msg-1]]\n\n\n\n끝")
        self.assertNotIn("http", body)
        self.assertNotIn("![[", body)
        self.assertNotIn("\n\n\n", body)


class Prompts(unittest.TestCase):
    def test_search_prompt_forbids_other_tools_and_keeps_today(self):
        p = V.build_search_prompt("질문?", "답", "2026-10-30")
        self.assertIn("search_web 도구만", p)
        self.assertIn("2026-10-30", p)
        self.assertIn("검증대상없음", p)

    def test_write_prompt_says_opened_only_and_no_urls(self):
        p = V.build_write_prompt("질문?", "답", "2026-10-30", "찾은 것", ["  [1] https://a"])
        self.assertIn("열린 주소로 뒷받침되는 것만 단정", p)
        self.assertIn("주소를 글에 쓰지 마라", p)


class ChildEnv(unittest.TestCase):
    def test_secrets_are_not_passed(self):
        import os
        os.environ["SOME_API_KEY"] = "x"
        try:
            self.assertNotIn("SOME_API_KEY", V.child_env())
        finally:
            del os.environ["SOME_API_KEY"]



class CitedNumbers(unittest.TestCase):
    def test_grouped_citations_are_all_kept(self):
        body = "맞아요 (출처 1)\n- 달라졌어요 (출처 2, 3)\n- 그대로 (출처 4·5) 2026년 기준"
        self.assertEqual(V.cited_numbers(body), {1, 2, 3, 4, 5})

    def test_years_outside_citation_are_not_numbers(self):
        self.assertEqual(V.cited_numbers("2026년 10월 기준이에요"), set())

class SearchOrder(unittest.TestCase):
    """사람이 기다리는 단추라 claude 가 먼저, 안 되면 agy. 엔진 기록은 실제로 찾은 쪽만."""

    def setUp(self):
        self.calls = []
        self._agy, self._claude = V.AR.call_agy, V.call_claude
        V.AR.call_agy = lambda p, t: self.calls.append("agy") or self.agy_out
        V.call_claude = lambda p, m, t, tools="": self.calls.append("claude") or self.claude_out

    def tearDown(self):
        V.AR.call_agy, V.call_claude = self._agy, self._claude

    def test_claude_first(self):
        self.claude_out, self.agy_out = "찾음", "agy"
        used = []
        self.assertEqual(V.search("p", V.DEFAULT_ENGINE, used), "찾음")
        self.assertEqual(self.calls, ["claude"])
        self.assertEqual(used, ["claude-sonnet"])

    def test_falls_back_to_agy(self):
        self.claude_out, self.agy_out = None, "agy 가 찾음"
        used = []
        self.assertEqual(V.search("p", "claude", used), "agy 가 찾음")
        self.assertEqual(self.calls, ["claude", "agy"])
        self.assertEqual(used, [V.AR.SEARCH_MODEL])


if __name__ == "__main__":
    unittest.main()
