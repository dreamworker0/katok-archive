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


class RootUrlTests(unittest.TestCase):
    """대문은 근거가 아니다.

    '중계 주소 말고 직접 주소를 달라' 고 했더니 모델이 www.law.go.kr ·
    www.snuh.org 처럼 **대문**을 대기 시작했다(실측 2026-08-27). 열리기는 열리므로
    규칙을 형식적으로는 지키는데, 정작 그 조문·그 안내는 거기 없다.
    """

    def test_root_urls_are_recognised(self):
        for u in ("https://www.law.go.kr", "https://www.law.go.kr/",
                  "http://a.kr", "https://a.kr/?x=1"):
            self.assertTrue(ar.is_root(u), u)

    def test_deep_links_are_not_roots(self):
        for u in ("https://ko.wikipedia.org/wiki/GS25",
                  "https://www.snuh.org/board/B003/view.do?bbs_no=5898"):
            self.assertFalse(ar.is_root(u), u)

    def test_compose_prompt_puts_roots_in_their_own_tier(self):
        """대문을 속페이지와 같이 두면 '열렸다' 만 보고 조문 번호를 거기 기댄다."""
        links = [
            {"url": "https://a.kr/deep", "final": "https://a.kr/deep",
             "root": False, "ok": True, "status": 200, "note": ""},
            {"url": "https://b.kr", "final": "https://b.kr",
             "root": True, "ok": True, "status": 200, "note": ""},
        ]
        p = ar.build_compose_prompt({"id": "t-1", "title": "제목"}, "보고서",
                                    "찾은 것", links)
        good = p.index("열린 주소(단정의 근거로 써도 되는 것):")
        weak = p.index("대문만 열린 주소")
        self.assertLess(good, weak)
        self.assertIn("https://a.kr/deep", p[good:weak])
        self.assertIn("https://b.kr", p[weak:])
        self.assertIn("구체적인 주장의 근거로는 쓸 수 없다", p)

    def test_search_prompt_forbids_homepage_roots(self):
        p = ar.build_search_prompt({"id": "t-1", "title": "제목"}, "보고서")
        self.assertIn("홈페이지 대문도 안 된다", p)
        self.assertIn("대문으로", p)


class RecoverTests(unittest.TestCase):
    """죽은 근거 주소를 한 번 되짚는다.

    agy 의 검색 근거는 일회성 중계 주소로 온다. 이미 죽었으면 원 출처에 닿을 길이
    없어, 사실인 것까지 '확인하지 못한 것' 으로 밀려난다(실측 2026-08-27:
    국립소방병원의 서울대병원 위·수탁 운영이 그렇게 밀려났다).
    """

    DEAD = {"url": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/X",
            "final": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/X",
            "ok": False, "status": 404, "note": "HTTP 404"}

    def test_prompt_shows_which_urls_died_and_why(self):
        p = ar.build_recover_prompt("찾은 것", [self.DEAD])
        self.assertIn("grounding-api-redirect/X", p)
        self.assertIn("HTTP 404", p)
        self.assertIn("찾은 것", p)

    def test_prompt_demands_direct_urls_and_forbids_redirectors(self):
        """되짚어 온 것이 또 중계 주소면 되짚은 뜻이 없다."""
        p = ar.build_recover_prompt("찾은 것", [self.DEAD])
        self.assertIn("그 내용이 실린 페이지", p)
        self.assertIn("홈페이지 대문(경로 없는 주소)은", p)
        self.assertIn("중계·리다이렉트 주소는 절대 적지 마라", p)
        # 되짚기 프롬프트가 스스로 모순되면 안 된다 — 대문을 금지해 놓고
        # 다음 줄에서 "공식 홈페이지를 찾아라" 라고 하면 대문이 다시 돌아온다.
        self.assertNotIn("**그 기관의 공식 홈페이지**를 우선", p)
        self.assertIn("지어내지 마라", p)

    def test_nothing_failed_means_no_extra_call(self):
        """멀쩡한 편에까지 agy 를 한 번 더 부르면 값과 시간이 곱절이 된다."""
        called = []
        old, ar.call_search = ar.call_search, lambda *a, **k: called.append(1)
        try:
            self.assertEqual(ar.recover_links("x", [], set()), [])
            self.assertEqual(called, [])
        finally:
            ar.call_search = old

    def test_urls_we_already_tried_are_not_tried_again(self):
        """같은 주소를 다시 열어 보는 것은 시간만 쓴다."""
        seen = "https://a.kr"
        opened = []
        old_search, ar.call_search = ar.call_search, lambda *a, **k: "근거: " + seen
        old_open, ar.open_url = ar.open_url, lambda u, **k: opened.append(u)
        try:
            self.assertEqual(ar.recover_links("x", [self.DEAD], {seen}), [])
            self.assertEqual(opened, [])
        finally:
            ar.call_search, ar.open_url = old_search, old_open

    def test_only_the_ones_that_open_come_back(self):
        """되짚어 왔어도 안 열리면 근거가 아니다 — 규칙은 그대로다."""
        old_search, ar.call_search = ar.call_search, lambda *a, **k: "https://live.kr https://dead.kr"
        old_open = ar.open_url
        ar.open_url = lambda u, **k: {"url": u, "final": u, "status": 200,
                                      "ok": u == "https://live.kr", "note": ""}
        try:
            got = ar.recover_links("x", [self.DEAD], set())
            self.assertEqual([l["url"] for l in got], ["https://live.kr"])
        finally:
            ar.call_search, ar.open_url = old_search, old_open

    def test_a_dead_search_does_not_break_the_report(self):
        old, ar.call_search = ar.call_search, lambda *a, **k: None
        try:
            self.assertEqual(ar.recover_links("x", [self.DEAD], set()), [])
        finally:
            ar.call_search = old


class ConcurrentRunTests(unittest.TestCase):
    """긴 묶음을 돌리는 중에 밤 23:40 갱신이 끼어들 수 있다.

    둘 다 시작할 때 대장을 읽고 끝날 때 쓴다. 통째로 덮어쓰면 나중에 끝난 쪽이
    상대의 기록을 지우고, 지워진 만큼 다음 밤에 같은 대화를 다시 물어 돈을 쓴다.
    """

    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self._led, ar.SKIP_LEDGER = ar.SKIP_LEDGER, self.d / "skips.json"

    def tearDown(self):
        ar.SKIP_LEDGER = self._led

    def test_saving_merges_instead_of_clobbering(self):
        ar.save_skips({"t-001": {"why": "먼저"}})
        ar.save_skips({"t-002": {"why": "나중"}})       # 다른 실행이 쓴 것처럼
        got = ar.load_skips()
        self.assertEqual(sorted(got), ["t-001", "t-002"])

    def test_same_id_is_updated_not_duplicated(self):
        ar.save_skips({"t-001": {"why": "처음"}})
        ar.save_skips({"t-001": {"why": "고침"}})
        self.assertEqual(ar.load_skips()["t-001"]["why"], "고침")

    def test_report_file_never_exists_half_written(self):
        """반쯤 쓰인 파일을 발행이 읽으면 잘린 보고서가 사이트에 올라간다."""
        old, ar.AI_REPORTS_DIR = ar.AI_REPORTS_DIR, self.d
        try:
            p = ar.write_report("t-001", "## 제목", "a", "2026-08-27", "m")
            self.assertTrue(p.exists())
            # 갈아 끼운 뒤 임시 파일이 남아 있으면 발행이 그것까지 읽는다.
            self.assertEqual(list(self.d.glob("*.tmp")), [])
        finally:
            ar.AI_REPORTS_DIR = old


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


# 클래스 속성으로 두면 PUBLIC 이 메서드로 묶여 host 자리에 self 가 들어간다.
def _resolver(mapping):
    """이름 → IP 를 정해 주는 가짜 DNS.

    내부망에 **진짜로 요청을 보내지 않고** "192.168 로 풀리는 이름" 을 재현한다.
    없는 이름은 socket.gaierror 로 답한다 — 진짜 getaddrinfo 와 같은 모양이다.
    """
    import socket as _s

    def resolve(host, port, *a, **kw):
        if host not in mapping:
            raise _s.gaierror("이름 없음: %s" % host)
        return [(_s.AF_INET, _s.SOCK_STREAM, _s.IPPROTO_TCP, "", (ip, port))
                for ip in mapping[host]]
    return resolve


PUBLIC = _resolver({"example.org": ["93.184.216.34"],
                    "www.law.go.kr": ["223.130.195.200"]})


class UrlGuardTests(unittest.TestCase):
    """열기 전에 거르는 자리 — 여기 들어오는 주소는 모델이 만들어 낸 것이다.

    이 코드는 수집 PC 에서 매일 밤 무인으로 돈다. 그 PC 는 집·사무실 안쪽에 있고,
    모델이 사설 주소를 대면 예전에는 그대로 열러 갔다.
    """

    def test_ordinary_public_addresses_pass(self):
        for url in ("https://example.org/a/b", "http://example.org",
                    "https://www.law.go.kr/법령/저작권법"):
            self.assertIsNone(ar.url_guard(url, resolve=PUBLIC), url)

    def test_private_and_loopback_are_refused(self):
        cases = {
            "http://127.0.0.1/admin": ["127.0.0.1"],
            "http://router.local/": ["192.168.0.1"],
            "http://nas/": ["10.0.0.5"],
            "http://x/": ["172.16.3.9"],
            # 클라우드 메타데이터 — 링크 로컬
            "http://metadata/": ["169.254.169.254"],
        }
        for url, ips in cases.items():
            host = ar.urllib.parse.urlsplit(url).hostname
            why = ar.url_guard(url, resolve=_resolver({host: ips}))
            self.assertIsNotNone(why, url)
            self.assertIn("내부망", why)

    def test_ipv6_loopback_and_unique_local_are_refused(self):
        for ip in ("::1", "fc00::1", "fe80::1"):
            why = ar.url_guard("http://h/", resolve=_resolver({"h": [ip]}))
            self.assertIsNotNone(why, ip)

    def test_a_name_that_resolves_to_both_is_refused(self):
        """바깥 IP 를 섞어 대도 하나라도 내부면 막는다."""
        why = ar.url_guard("http://mixed/",
                           resolve=_resolver({"mixed": ["93.184.216.34", "10.1.2.3"]}))
        self.assertIn("내부망", why)

    def test_only_http_and_https(self):
        for url in ("file:///c:/windows/win.ini", "ftp://ftp.example.org/x",
                    "gopher://example.org/", "data:text/html,hi", "javascript:1"):
            why = ar.url_guard(url, resolve=PUBLIC)
            self.assertIsNotNone(why, url)
            self.assertIn("http", why)

    def test_a_name_we_cannot_resolve_is_refused(self):
        """못 찾으면 열지 않는 쪽으로 기운다."""
        why = ar.url_guard("https://없는이름.example/", resolve=_resolver({}))
        self.assertIn("찾지 못함", why)

    def test_a_missing_host_is_refused(self):
        for url in ("http:///path", "https://", "not a url"):
            self.assertIsNotNone(ar.url_guard(url, resolve=PUBLIC), url)


class OpenUrlGuardTests(unittest.TestCase):
    """open_url 이 막힌 주소를 '못 연 것' 과 구분해 기록하는가."""

    def test_a_blocked_address_is_never_requested(self):
        called = []

        class _Boom:
            def open(self, *a, **kw):
                called.append(a)
                raise AssertionError("막힌 주소인데 요청이 나갔다")

        old = ar._opener
        ar._opener = lambda: _Boom()
        try:
            got = ar.open_url("http://192.168.0.1/",
                              resolve=_resolver({"192.168.0.1": ["192.168.0.1"]}))
        finally:
            ar._opener = old
        self.assertEqual(called, [])
        self.assertFalse(got["ok"])
        self.assertTrue(got["blocked"])
        self.assertIn("열지 않음", got["note"])

    def test_blocked_addresses_are_not_asked_again(self):
        """recover_links 는 '못 연 것' 만 되짚는다 — 막은 것을 되물으면 또 막힌다."""
        links = [
            {"url": "http://a/", "ok": False, "blocked": True, "note": "열지 않음 — 내부망"},
            {"url": "http://b/", "ok": False, "blocked": False, "note": "HTTP 404"},
        ]
        failed = [x for x in links if not x["ok"] and not x.get("blocked")]
        self.assertEqual([x["url"] for x in failed], ["http://b/"])

    def test_the_prompt_never_carries_our_internal_addresses(self):
        """막은 이유(풀린 IP)는 로컬 기록에만 남고 프롬프트에는 안 들어간다."""
        links = [
            {"url": "http://nas.local/x", "ok": False, "blocked": True,
             "note": "열지 않음 — 내부망·로컬 주소(10.0.0.5)", "status": 0},
            {"url": "https://example.org/a", "final": "https://example.org/a",
             "ok": True, "blocked": False, "root": False, "note": "", "status": 200},
        ]
        prompt = ar.build_compose_prompt({"title": "제목"}, "사람 보고서", "검색 결과", links)
        self.assertIn("열지 않기로 한 주소", prompt)
        self.assertIn("http://nas.local/x", prompt, "무엇을 안 열었는지는 알려준다")
        self.assertNotIn("10.0.0.5", prompt, "우리 망의 IP 를 바깥 모델에 주지 않는다")
        self.assertIn("https://example.org/a", prompt)


class RedirectGuardTests(unittest.TestCase):
    """리다이렉트 목적지도 같은 잣대로 본다.

    agy 의 근거는 애초에 경유 주소로 오므로 리다이렉트는 예외가 아니라 기본값이다.
    첫 주소만 보고 통과시키면 바깥 주소가 내부망으로 넘겨주는 순간 방어가 없다.
    """

    def _redirect_to(self, newurl, resolve):
        handler = ar._GuardedRedirect()
        old = ar.socket.getaddrinfo
        ar.socket.getaddrinfo = resolve
        try:
            return handler.redirect_request(
                ar.urllib.request.Request("https://example.org/"),
                None, 302, "Found", {}, newurl)
        finally:
            ar.socket.getaddrinfo = old

    def test_a_redirect_into_the_private_network_is_refused(self):
        with self.assertRaises(ar.BlockedURL):
            self._redirect_to("http://192.168.0.1/",
                              _resolver({"192.168.0.1": ["192.168.0.1"]}))

    def test_a_redirect_to_a_non_http_scheme_is_refused(self):
        with self.assertRaises(ar.BlockedURL):
            self._redirect_to("ftp://ftp.example.org/x",
                              _resolver({"ftp.example.org": ["93.184.216.34"]}))

    def test_an_ordinary_redirect_still_works(self):
        req = self._redirect_to("https://example.org/b",
                                _resolver({"example.org": ["93.184.216.34"]}))
        self.assertEqual(req.full_url, "https://example.org/b")

    def test_we_do_not_follow_forever(self):
        self.assertLessEqual(ar._GuardedRedirect.max_redirections, 5)


class FetchLimitTests(unittest.TestCase):
    """이미 있던 두 가지 — 없어지면 알아채야 한다."""

    def test_there_is_a_timeout(self):
        self.assertGreater(ar.FETCH_TIMEOUT_SEC, 0)
        self.assertLessEqual(ar.FETCH_TIMEOUT_SEC, 60, "야간 갱신을 붙들면 안 된다")

    def test_the_body_read_is_capped(self):
        src = Path(ar.__file__).read_text(encoding="utf-8")
        self.assertIn("r.read(2048)", src,
                      "본문을 통째로 받으면 안 된다 — 열리는지만 본다")


def _stream(*events):
    """agy stream-json 한 판을 꾸민다. 한 줄에 사건 하나."""
    return "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n"


def _init(agent=None):
    return {"event": "init", "init": {"agent": agent or ar.AGY_AGENT,
                                      "model": ar.SEARCH_MODEL}}


def _tool(name):
    return {"event": "step_update",
            "step_update": {"step_type": "tool", "state": "DONE", "tool_name": name,
                            "tool_info": {"name": name, "parameters": {}}}}


def _result(text, status="SUCCESS"):
    return {"event": "result", "result": {"status": status, "response": text}}


class AgyAgentDefinitionTests(unittest.TestCase):
    """agy 는 실행 옵션으로 도구를 끌 수 없다. 끄는 자리는 이 정의 하나다.

    실측 2026-10-14: 기본 에이전트는 `--sandbox` 여도 폴더 밖 파일을 `view_file`
    로 읽었고, 이 정의로 띄우면 같은 요청에 도구를 하나도 부르지 못했다.
    """

    def _frontmatter(self):
        md = ar.AGY_AGENT_MD
        self.assertTrue(md.startswith("---\n"))
        return md.split("---\n")[1]

    def test_built_in_tools_are_excluded(self):
        self.assertIn("excludeDefaultComponents: true", self._frontmatter())

    def test_the_only_tool_is_web_search(self):
        tools = self._frontmatter().split("tools:\n", 1)[1]
        listed = [l.strip()[2:].strip() for l in tools.splitlines()
                  if l.strip().startswith("- ")]
        self.assertEqual(listed, ["search_web"])
        self.assertEqual(ar.AGY_ALLOWED_TOOLS, frozenset({"search_web"}))

    def test_no_mcp_and_no_subagent_use(self):
        fm = self._frontmatter()
        self.assertIn("inheritMcp: false", fm)
        self.assertIn("subagent: false", fm)

    def test_name_matches_what_we_ask_for(self):
        """이름이 어긋나면 agy 가 exit 1 로 멈춘다 — 밤마다 전부 claude 로 넘어간다."""
        self.assertIn("name: %s\n" % ar.AGY_AGENT, self._frontmatter())


class AgyStreamTests(unittest.TestCase):
    """답 글자만 보지 않고 **무엇을 했는지**를 본다."""

    def test_a_search_only_run_is_accepted(self):
        text, problem = ar.read_agy_stream(_stream(
            _init(), _tool("search_web"), _tool("search_web"),
            _result("1. 맞다 https://firebase.google.com/pricing")))
        self.assertEqual(text, "1. 맞다 https://firebase.google.com/pricing")
        self.assertEqual(problem, "")

    def test_any_other_tool_throws_the_answer_away(self):
        for name in ("view_file", "run_command", "read_url_content", "manage_task"):
            text, problem = ar.read_agy_stream(_stream(
                _init(), _tool("search_web"), _tool(name), _result("CANARY")))
            self.assertIsNone(text, name)
            self.assertIn(name, problem)

    def test_the_default_agent_is_refused(self):
        """기본 에이전트는 파일을 읽는다. 그쪽으로 돌았으면 답을 쓰지 않는다."""
        text, problem = ar.read_agy_stream(_stream(
            _init(agent="default"), _result("답")))
        self.assertIsNone(text)
        self.assertIn("검색 전용", problem)

    def test_a_missing_init_is_refused(self):
        self.assertIsNone(ar.read_agy_stream(_stream(_result("답")))[0])

    def test_a_subagent_is_refused(self):
        ev = {"event": "step_update",
              "step_update": {"step_type": "tool", "tool_name": "search_web",
                              "subagent_info": {"conversation_id": "x"}}}
        text, problem = ar.read_agy_stream(_stream(_init(), ev, _result("답")))
        self.assertIsNone(text)
        self.assertIn("하위 에이전트", problem)

    def test_an_unknown_step_kind_is_refused(self):
        ev = {"event": "step_update", "step_update": {"step_type": "browser"}}
        self.assertIsNone(ar.read_agy_stream(_stream(_init(), ev, _result("답")))[0])

    def test_the_gemini_filter_message_is_not_an_answer(self):
        """필터에 걸리면 SUCCESS 상태로 이 문구를 답 자리에 낸다(실측)."""
        text, problem = ar.read_agy_stream(_stream(_init(), _result(
            "This request was blocked by Gemini's filters. They can occasionally "
            "trigger by mistake.")))
        self.assertIsNone(text)
        self.assertIn("필터", problem)

    def test_a_failed_status_or_empty_answer_is_refused(self):
        self.assertIsNone(ar.read_agy_stream(_stream(_init(), _result("x", "ERROR")))[0])
        self.assertIsNone(ar.read_agy_stream(_stream(_init(), _result("  ")))[0])
        self.assertIsNone(ar.read_agy_stream("")[0])

    def test_noise_lines_are_ignored(self):
        raw = "경고 한 줄\n" + _stream(_init(), _tool("search_web"), _result("답"))
        self.assertEqual(ar.read_agy_stream(raw)[0], "답")


class _Ran:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr


class AgyCallTests(unittest.TestCase):
    """agy 를 어디서, 무엇으로 부르는지."""

    def setUp(self):
        self.seen = {}
        self._old = ar.subprocess.run

        def fake_run(cmd, **kw):
            cwd = Path(kw["cwd"])
            self.seen["cmd"], self.seen["cwd"] = cmd, cwd
            self.seen["files"] = sorted(str(p.relative_to(cwd)).replace("\\", "/")
                                        for p in cwd.rglob("*") if p.is_file())
            agent = cwd / ".agents" / "agents" / ("%s.md" % ar.AGY_AGENT)
            self.seen["agent"] = agent.read_text(encoding="utf-8")
            return _Ran(_stream(_init(), _tool("search_web"), _result("찾음")))
        ar.subprocess.run = fake_run

    def tearDown(self):
        ar.subprocess.run = self._old

    def test_runs_in_a_fresh_empty_folder_with_only_the_definition(self):
        """이 저장소에서 돌리지 않는다 — output/ 에 대화 원문이 있다."""
        self.assertEqual(ar.call_agy("물음"), "찾음")
        cwd = self.seen["cwd"].resolve()
        self.assertNotEqual(cwd, ar.ROOT.resolve())
        self.assertNotIn(ar.ROOT.resolve(), cwd.parents)
        self.assertEqual(self.seen["files"], [".agents/agents/%s.md" % ar.AGY_AGENT])
        self.assertEqual(self.seen["agent"], ar.AGY_AGENT_MD)
        self.assertFalse(self.seen["cwd"].exists(), "임시 폴더는 지운다")

    def test_asks_for_the_search_agent_and_the_model(self):
        ar.call_agy("물음")
        cmd = self.seen["cmd"]
        self.assertEqual(cmd[cmd.index("--agent") + 1], ar.AGY_AGENT)
        self.assertEqual(cmd[cmd.index("--model") + 1], ar.SEARCH_MODEL)
        self.assertEqual(cmd[cmd.index("--output-format") + 1], "stream-json")
        self.assertIn("--sandbox", cmd)
        self.assertNotIn("--dangerously-skip-permissions", cmd)

    def test_a_too_long_prompt_is_not_sent(self):
        self.assertIsNone(ar.call_agy("가" * (ar.AGY_MAX_PROMPT_CHARS + 1)))
        self.assertNotIn("cmd", self.seen)

    def test_a_nonzero_exit_is_a_failure(self):
        ar.subprocess.run = lambda cmd, **kw: _Ran(_stream(_init(), _result("답")), 1)
        self.assertIsNone(ar.call_agy("물음"))

    def test_a_missing_agy_is_a_failure_not_a_crash(self):
        def gone(cmd, **kw):
            raise FileNotFoundError("agy")
        ar.subprocess.run = gone
        self.assertIsNone(ar.call_agy("물음"))


class SearchFallbackTests(unittest.TestCase):
    """agy 가 안 되면 claude 가 찾고, 누가 찾았는지 기록이 정직하다."""

    def setUp(self):
        self._agy, self._claude = ar.call_agy, ar.llm.call_claude
        self.claude_calls = []

        def fake_claude(prompt, model, timeout=0, what="", tools=""):
            self.claude_calls.append((model, tools))
            return "claude 가 찾음"
        ar.llm.call_claude = fake_claude

    def tearDown(self):
        ar.call_agy, ar.llm.call_claude = self._agy, self._claude

    def test_agy_answer_is_used_and_recorded(self):
        ar.call_agy = lambda p, t=0: "agy 가 찾음"
        used = []
        self.assertEqual(ar.call_search("물음", used=used), "agy 가 찾음")
        self.assertEqual(used, [ar.SEARCH_MODEL])
        self.assertEqual(self.claude_calls, [])

    def test_claude_takes_over_with_web_search_only(self):
        ar.call_agy = lambda p, t=0: None
        used = []
        self.assertEqual(ar.call_search("물음", used=used), "claude 가 찾음")
        self.assertEqual(used, ["claude-%s" % ar.FALLBACK_SEARCH_MODEL])
        self.assertEqual(self.claude_calls, [(ar.FALLBACK_SEARCH_MODEL, "WebSearch")])

    def test_both_failing_records_nothing(self):
        ar.call_agy = lambda p, t=0: None
        ar.llm.call_claude = lambda *a, **k: None
        used = []
        self.assertIsNone(ar.call_search("물음", used=used))
        self.assertEqual(used, [])
