from html.parser import HTMLParser
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parent.parent
VIEWS = {
    "summary",
    "graph",
    "timeline",
    "tags",
    "gallery",
    "files",
    "stats",
    "mine",
    "admin",
}
REQUIRED_IDS = {
    "appRoot",
    "tabs",
    "mobileNav",
    "mobileMore",
    "searchInput",
    "participantFilter",
    "sessionBox",
    "signOutTop",
    "themeBtn",
    "fontBtn",
    "view",
    "lightbox",
    "confirmDialog",
    "confirmTitle",
    "confirmDesc",
    "confirmSubmit",
}


class Markup(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.id_counts = {}
        self.views = set()
        self.buttons = []
        self.images = []
        self.tags_by_id = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.ids.add(attrs["id"])
            self.id_counts[attrs["id"]] = self.id_counts.get(attrs["id"], 0) + 1
            self.tags_by_id[attrs["id"]] = tag
        if attrs.get("data-view"):
            self.views.add(attrs["data-view"])
        if tag == "button":
            self.buttons.append(attrs)
        if tag == "img":
            self.images.append(attrs)


class UiShellContractTests(unittest.TestCase):
    def parse(self, name):
        parser = Markup()
        parser.feed((ROOT / "web" / name).read_text(encoding="utf-8"))
        return parser

    def test_local_and_hosting_shells_expose_same_views_and_ids(self):
        for name in ("index.html", "index.hosting.html"):
            with self.subTest(name=name):
                page = self.parse(name)
                self.assertTrue(REQUIRED_IDS <= page.ids)
                self.assertEqual(VIEWS, page.views)

    def test_shell_markup_has_accessible_controls_and_unique_ids(self):
        for name in ("index.html", "index.hosting.html"):
            with self.subTest(name=name):
                page = self.parse(name)
                self.assertFalse(
                    [item for item, count in page.id_counts.items() if count > 1]
                )
                self.assertTrue(all("alt" in image for image in page.images))
                self.assertTrue(all(button.get("type") for button in page.buttons))
                self.assertEqual("button", page.tags_by_id.get("lightboxClose"))
                source = (ROOT / "web" / name).read_text(encoding="utf-8")
                self.assertIn('<span class="sr-only">아카이브 검색</span>', source)
                self.assertIn('id="mobileMoreButton" aria-label=', source)
                self.assertIn('id="lightboxClose" type="button" aria-label=', source)

    def test_sidebar_footer_contains_stable_account_actions(self):
        for name in ("index.html", "index.hosting.html"):
            with self.subTest(name=name):
                source = (ROOT / "web" / name).read_text(encoding="utf-8")
                footer = source.index('class="sidebar-footer"')
                session = source.index('id="sessionBox"', footer)
                actions = source.index('class="sidebar-actions"', session)
                signout = source.index('id="signOutTop"', actions)
                font = source.index('id="fontBtn"', signout)
                theme = source.index('id="themeBtn"', font)
                aside_end = source.index("</aside>", theme)
                self.assertLess(footer, session)
                self.assertLess(session, actions)
                self.assertLess(actions, signout)
                self.assertLess(signout, font)
                self.assertLess(font, theme)
                self.assertLess(theme, aside_end)


class UiStyleContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")

    def test_warm_palette_tokens_exist(self):
        for value in (
            "#FBF6EE",
            "#FFFDF8",
            "#3C332C",
            "#CA7154",
            "#879D78",
            "#B85F4B",
        ):
            self.assertIn(value.lower(), self.css.lower())

    def test_dark_theme_and_reduced_motion_are_explicit(self):
        self.assertIn(':root[data-theme="dark"]', self.css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", self.css)

    def test_desktop_and_mobile_navigation_rules_exist(self):
        self.assertIn(".sidebar", self.css)
        self.assertIn(".mobile-nav", self.css)
        self.assertIn("@media (max-width: 760px)", self.css)

    def test_sidebar_and_toolbar_controls_have_clear_size_hierarchy(self):
        self.assertIn(".room-sub__dates", self.css)
        self.assertIn("font-size: 11.5px", self.css)
        self.assertIn("font-size: 14px", self.css)
        self.assertIn("height: 50px", self.css)
        self.assertIn(".sidebar-avatar", self.css)
        self.assertIn(".sidebar-signout", self.css)
        self.assertIn(".theme-toggle svg", self.css)
        self.assertIn("width: 40px", self.css)

    def test_sidebar_account_footer_has_equal_height_actions(self):
        # 로그아웃 | 글자 크기 | 테마 — 아이콘 두 개는 자리를 못 박아 둔다.
        # 로그아웃이 hidden 일 때(로그인 전) 왼쪽으로 밀려가지 않게 하려는 것이다.
        self.assertIn(
            ".sidebar-actions { display: grid; "
            "grid-template-columns: minmax(0, 1fr) 40px 40px",
            self.css,
        )
        self.assertIn(
            ".sidebar-signout, .theme-toggle, .font-toggle { height: 40px", self.css
        )
        self.assertIn(".font-toggle { display: grid; place-items: center; grid-column: 2", self.css)
        self.assertIn(".theme-toggle { display: grid; place-items: center; grid-column: 3", self.css)
        self.assertIn(".sidebar-name", self.css)
        self.assertIn("text-overflow: ellipsis", self.css)

    def test_reading_area_scales_as_a_whole_not_class_by_class(self):
        """배율은 읽는 영역(.view)에 한 번만 건다.

        본문 클래스를 하나씩 골라 곱하던 때 첫 화면의 .doc-overview 를 빠뜨려,
        버튼 속 '가' 만 커지고 읽는 글은 그대로였다. 화면마다 흩어진 px 규칙이
        170개가 넘어 하나씩 세는 방식으로는 또 빠지고, 새 화면이 생기면 막을
        방법도 없다. 그래서 .view(본문) 대 그 밖(chrome)이라는 경계를 쓴다.
        """
        self.assertIn("--reading-scale: 1;", self.css)
        self.assertIn(':root[data-font="large"] { --reading-scale: 1.12; }', self.css)
        self.assertIn(':root[data-font="xlarge"] { --reading-scale: 1.26; }', self.css)
        self.assertIn(".view { zoom: var(--reading-scale); }", self.css)

    def test_no_class_also_multiplies_the_scale(self):
        """개별 규칙에 배율이 남아 있으면 두 번 곱해진다(1.26 x 1.26)."""
        self.assertNotIn("* var(--reading-scale)", self.css)

    def test_graph_opts_out_because_it_maps_pointer_moves_to_coordinates(self):
        # graph.js 는 포인터 이동량을 SVG 좌표에 그대로 더한다. 배율이 걸리면
        # 끌기가 그만큼 빨라진다. 그림이라 글자 크기와도 상관이 없다.
        self.assertIn(".graph-wrap { zoom: calc(1 / var(--reading-scale)); }", self.css)

    def test_chrome_sits_outside_the_scaled_reading_area(self):
        """사이드바·검색바·모바일 내비가 #view 밖에 있어야 배율을 타지 않는다."""
        for name in ("index.html", "index.hosting.html"):
            with self.subTest(name=name):
                source = (ROOT / "web" / name).read_text(encoding="utf-8")
                view = source.index('id="view"')
                self.assertLess(source.index('class="sidebar"'), view)
                self.assertLess(source.index('class="utility-bar"'), view)
                self.assertLess(view, source.index('id="mobileNav"'))
                # #view 는 홑 태그로 닫힌다 — 그 뒤에 오는 것은 배율 밖이다.
                self.assertLess(source.index("</main>", view),
                                source.index('id="mobileNav"'))

    def test_mobile_more_items_all_look_like_the_same_kind_of_thing(self):
        """모바일 '더보기'의 글자 크기·테마도 다른 항목과 같은 전체폭 행이다.

        라벨이 붙은 전체폭 행들의 목록에 아이콘만 있는 44px 버튼을 끼우니 다른
        물건처럼 보였다. 모바일에서는 '가' 와 달 모양만 보고 무엇인지 추측해야
        한다는 문제도 있었다. 이름과 지금 값을 적어 목록에 맞춘다.
        """
        app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn('.mobile-more button[data-mobile-action="font"]', self.css)
        self.assertIn('.mobile-more button[data-mobile-action="theme"]', self.css)
        self.assertIn("function mobileRow(", app)
        self.assertIn('mobileRow("글자 크기", now.label)', app)
        self.assertIn('mobileRow("다크 모드",', app)
        # 오른쪽에 지금 값 — 열지 않고도 상태를 읽을 수 있어야 한다.
        self.assertIn('class="mm-value"', app)
        self.assertIn(".mobile-more .mm-value { margin-left: auto;", self.css)
        # 아이콘만 있던 옛 묶음은 남기지 않는다.
        self.assertNotIn("mobile-more__icons", self.css)
        self.assertNotIn("mobile-more__icons", app)

    def test_mobile_more_rows_keep_a_reachable_tap_target(self):
        block = self.css[self.css.index('.mobile-more button[data-mobile-action="font"]'):]
        self.assertIn("min-height: 44px", block[:260])

    def test_sidebar_keeps_the_compact_icon_toggles(self):
        # 사이드바 푸터는 40px 아이콘 자리다. 목록이 아니므로 라벨 행이 아니라
        # 아이콘이 맞다 — 같은 동작이라도 자리에 따라 모양이 다를 수 있다.
        app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn('class="font-toggle__mark" aria-hidden="true">가<', app)
        self.assertIn(".font-toggle__mark", self.css)

    def test_font_toggle_previews_the_size_it_will_switch_to(self):
        self.assertIn(".font-toggle__mark", self.css)
        for step in ("normal", "large", "xlarge"):
            with self.subTest(step=step):
                self.assertIn('[data-font-next="%s"] .font-toggle__mark' % step, self.css)

    def test_every_interface_uses_noto_sans_korean_without_serif_overrides(self):
        self.assertIn('font-family: "Noto Sans KR", sans-serif;', self.css)
        for legacy_family in (
            "Pretendard",
            "Apple SD Gothic Neo",
            "Malgun Gothic",
            "Nanum Myeongjo",
            "Batang",
            "ui-monospace",
        ):
            self.assertNotIn(legacy_family, self.css)

    def test_timeline_report_toggle_is_visually_prominent(self):
        self.assertIn(".tc-toggle { display: inline-flex", self.css)
        self.assertIn("min-height: 40px", self.css)
        self.assertIn("font-size: 14px", self.css)
        self.assertIn(".tc-toggle-icon", self.css)

    def test_contextual_link_cards_are_readable_and_wrap_long_urls(self):
        self.assertIn(".md-link-anchor", self.css)
        self.assertIn(".context-link-card", self.css)
        self.assertIn(".context-link-url", self.css)
        self.assertIn("overflow-wrap: anywhere", self.css)


class UiJavascriptContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

    def test_navigation_updates_every_data_view_control(self):
        self.assertIn('querySelectorAll("[data-view]")', self.app)
        self.assertIn('setAttribute("aria-current", "page")', self.app)
        self.assertIn("setNavigationState", self.app)

    def test_mobile_more_has_explicit_open_state(self):
        self.assertIn("setMobileMore", self.app)
        self.assertIn("mobileMoreButton", self.app)

    def test_font_size_cycles_through_named_steps_with_correct_particles(self):
        self.assertIn("var FONT_STEPS", self.app)
        self.assertIn("function cycleFont(", self.app)
        self.assertIn("function updateFontControls(", self.app)
        self.assertIn('localStorage.setItem("kakao-archive-font"', self.app)
        self.assertIn('data-mobile-action="font"', self.app)
        self.assertIn('setAttribute("data-font-next"', self.app)
        # 조사가 어긋나지 않게 갈 곳의 표기를 그대로 적어 둔다.
        for particle in ("보통으로", "크게로", "아주 크게로"):
            with self.subTest(particle=particle):
                self.assertIn(particle, self.app)
        # 라벨은 반드시 to 에서 만든다 — label 을 쓰면 받침에 따라 조사가 틀어진다.
        self.assertIn('next.to + " 전환', self.app)

    def test_theme_controls_render_accessible_destination_icons(self):
        self.assertIn("function updateThemeControls(", self.app)
        self.assertIn("function themeIcon(", self.app)
        self.assertIn('data-theme-icon="moon"', self.app)
        self.assertIn('data-theme-icon="sun"', self.app)
        self.assertIn('aria-hidden="true"', self.app)
        self.assertIn('setAttribute("aria-label", label)', self.app)
        self.assertIn('setAttribute("title", label)', self.app)
        self.assertIn("innerHTML = themeIcon(", self.app)
        self.assertIn('data-mobile-action="theme"', self.app)

    def test_room_summary_breaks_dates_onto_their_own_line(self):
        self.assertIn('class="room-sub__counts"', self.app)
        self.assertIn('class="room-sub__dates"', self.app)

    def test_timeline_report_toggle_is_a_prominent_accessible_action(self):
        self.assertIn('class="tc-toggle-icon"', self.app)
        self.assertIn('class="tc-toggle-label"', self.app)
        self.assertIn('aria-hidden="true"', self.app)
        self.assertIn('aria-expanded="', self.app)
        self.assertIn('"보고서 접기"', self.app)
        self.assertIn('setAttribute("aria-expanded"', self.app)

    def test_report_markdown_supports_contextual_link_anchors(self):
        self.assertIn('class="md-link-anchor"', self.app)
        self.assertIn("function contextualLinkHtml(", self.app)
        self.assertIn("link:([A-Za-z0-9_-]+)", self.app)
        self.assertIn('rel="noopener noreferrer"', self.app)

    def test_contextual_links_are_removed_from_the_footer(self):
        self.assertIn("context: context", self.app)
        self.assertIn("lk.context", self.app)
        self.assertIn("data-link-anchor", self.app)
        self.assertIn("이 주제에서 함께 공유된 자료", self.app)

    def test_session_renders_identity_into_the_stable_footer(self):
        self.assertIn("signOut: document.getElementById(\"signOutTop\")", self.app)
        self.assertIn('class="sidebar-name"', self.app)
        self.assertIn('class="sidebar-role"', self.app)
        self.assertIn("el.signOut.hidden = false", self.app)
        self.assertNotIn("'<button class=\"icon-btn\" id=\"signOutTop\"", self.app)


class MobileDensityContractTests(unittest.TestCase):
    """모바일에서 첫 화면이 읽을 만한 길이로 유지되는지.

    12개 주제 카드가 전부 펼쳐졌을 때 첫 화면이 20,375px(25화면 분량)였다. 접기를
    넣어 4,647px(5.7화면)로 줄였다. 개수를 줄여 정보를 버리는 대신 접었다 —
    발행에서 빼면 "그 앱 어디 갔지" 를 되찾을 방법이 없다.
    """

    @classmethod
    def setUpClass(cls):
        cls.css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
        cls.app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        cls.mobile = cls.css[cls.css.index("@media (max-width: 760px)"):]

    def test_desktop_never_shows_the_toggle_and_never_collapses(self):
        # 데스크톱은 넓어서 견딜 만하다. 기본값이 '펼침' 이어야 자바스크립트 없이도
        # 온전히 읽힌다.
        self.assertIn(".doc-toggle { display: none;", self.css)
        before_mobile = self.css[:self.css.index("@media (max-width: 760px)")]
        self.assertNotIn(".doc:not(.open) .doc-body", before_mobile)

    def test_mobile_collapses_the_card_body_and_clamps_the_overview(self):
        self.assertIn(".doc-toggle { display: flex; }", self.mobile)
        self.assertIn(".doc:not(.open) .doc-body { display: none; }", self.mobile)
        # 개요만 12개여도 8화면이라 세 줄로 줄인다.
        self.assertIn("-webkit-line-clamp: 3", self.mobile)

    def test_toggle_says_what_is_inside_before_you_open_it(self):
        # 열어봐야 아는 상자는 안 열어보게 된다.
        self.assertIn('class="doc-toggle-hint"', self.app)
        for label in ("결과물 ", "링크 "):
            with self.subTest(label=label):
                self.assertIn('counts.push("%s"' % label, self.app)

    def test_toggle_hint_does_not_repeat_the_card_header(self):
        """주제 개수는 세지 않는다 — doc-meta 가 위에서 이미 "N개 주제" 를 적는다."""
        self.assertIn('개 메시지 · " + (d.threads || []).length + "개 주제', self.app)
        self.assertNotIn('counts.push("주제 ', self.app)

    def test_toggle_is_an_accessible_disclosure(self):
        self.assertIn('aria-expanded="false"', self.app)
        self.assertIn('aria-controls="docbody-', self.app)
        self.assertIn('class="doc-body" id="docbody-', self.app)
        self.assertIn("function setDocOpen(", self.app)
        self.assertIn('btn.setAttribute("aria-expanded", open ? "true" : "false")', self.app)
        self.assertIn('open ? "접기" : "자세히 보기"', self.app)

    def test_category_shortcut_opens_the_card_it_jumps_to(self):
        # 골라서 찾아간 주제가 닫힌 채면 "눌렀는데 아무것도 없네" 가 된다.
        goto = self.app.index('data-goto"))')
        self.assertIn("setDocOpen(t, true)", self.app[goto:goto + 400])

    def test_tap_target_stays_reachable(self):
        block = self.css[self.css.index(".doc-toggle {"):]
        self.assertIn("min-height: 44px", block[:400])

    def test_category_bar_lies_down_instead_of_disappearing(self):
        """카테고리 바는 눕히되 없애지 않는다.

        12개가 여러 줄로 접혀 426px 를 먹었다. 다만 카드를 접어 둔 이상 이 바가
        주제로 가는 유일한 길이라, 숨기면 접힌 카드를 열 방법이 사라진다.
        """
        self.assertIn(".cat-nav { flex-wrap: nowrap; overflow-x: auto;", self.mobile)
        self.assertIn(".cat-nav button { flex: 0 0 auto;", self.mobile)
        # 숨기지 않았는지.
        self.assertNotIn(".cat-nav { display: none", self.mobile)

    def test_hero_art_steps_aside_on_mobile_only(self):
        # 장식이라 alt 가 비어 있다 — 빼도 읽는 데 잃는 것이 없다. 데스크톱은 그대로.
        self.assertIn(".archive-welcome__art { display: none; }", self.mobile)
        before_mobile = self.css[:self.css.index("@media (max-width: 760px)")]
        self.assertIn(".archive-welcome__art", before_mobile)


class UiGateContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.boot = (ROOT / "web" / "boot.js").read_text(encoding="utf-8")

    def test_gate_states_share_semantic_classes(self):
        for class_name in ("gate-state", "gate-copy", "gate-actions", "gate-progress"):
            self.assertIn(class_name, self.boot)

    def test_gate_copy_explains_privacy_and_next_step(self):
        self.assertIn("회원 전용으로 보호", self.boot)
        self.assertIn("신청을 잘 받았어요", self.boot)
        self.assertIn("관리자가 확인", self.boot)


class UiViewContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

    def test_summary_opens_with_archive_welcome(self):
        self.assertIn("archive-welcome", self.app)
        self.assertIn("함께 나눈 이야기를", self.app)

    def test_core_views_share_a_kind_empty_state(self):
        self.assertIn("function emptyState(", self.app)
        self.assertGreaterEqual(self.app.count("emptyState("), 5)


class UiSafetyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

    def test_risky_actions_use_the_shared_dialog(self):
        self.assertNotIn("window.confirm", self.app)
        self.assertIn("function confirmAction(", self.app)

    def test_mine_explains_the_per_message_exclusion_keyword(self):
        """'내 글 관리'가 [제외] 를 알려주고, 소급되지 않는다는 단서를 같이 준다.

        단서가 빠지면 이미 보낸 글도 빠지는 줄 알게 된다 — 안 빠진 걸 나중에 알게
        되는 쪽이 아예 모르는 것보다 나쁘다. 규칙은 scripts/collection_policy.py.
        """
        self.assertIn("[제외]", self.app)
        self.assertIn("［제외］", self.app)  # 전각. 모바일 자판에서 섞여 들어온다
        self.assertIn("앞으로 보내는 글에만", self.app)
        self.assertIn("mine-keyword", self.app)

    def test_exclusion_keyword_shown_matches_the_collector(self):
        """화면에 적은 단어가 실제 수집 규칙과 같아야 한다."""
        policy = (ROOT / "scripts" / "collection_policy.py").read_text(encoding="utf-8")
        keywords = re.findall(r'"(\[?［?제외\]?］?)"', policy)
        self.assertTrue(keywords)
        for keyword in set(keywords):
            with self.subTest(keyword=keyword):
                self.assertIn(keyword, self.app)

    def test_collection_choices_use_plain_honest_labels(self):
        for label in ("함께 공개", "발행하지 않기", "수집 중단"):
            self.assertIn(label, self.app)
        self.assertIn("관리자에게는 운영 원본이 남습니다", self.app)


class UiArtworkContractTests(unittest.TestCase):
    def test_production_art_exists_within_size_budgets(self):
        art = ROOT / "web" / "art"
        budgets = {
            "archive-hero.webp": 250 * 1024,
            "state-pending.webp": 80 * 1024,
            "state-empty.webp": 80 * 1024,
            "state-search.webp": 80 * 1024,
        }
        for name, budget in budgets.items():
            with self.subTest(name=name):
                path = art / name
                self.assertTrue(path.is_file())
                self.assertLessEqual(path.stat().st_size, budget)


class FirebaseHostingContractTests(unittest.TestCase):
    def test_hosting_enables_oauth_popup_opener_compatibility(self):
        config = json.loads((ROOT / "firebase.json").read_text(encoding="utf-8"))
        for hosting in config["hosting"]:
            with self.subTest(site=hosting["site"]):
                headers = [
                    header
                    for rule in hosting.get("headers", [])
                    for header in rule.get("headers", [])
                ]
                self.assertIn(
                    {
                        "key": "Cross-Origin-Opener-Policy",
                        "value": "same-origin-allow-popups",
                    },
                    headers,
                )

    def test_shells_load_noto_sans_korean_and_use_icon_only_theme_action(self):
        for name in ("index.html", "index.hosting.html"):
            with self.subTest(name=name):
                source = (ROOT / "web" / name).read_text(encoding="utf-8")
                self.assertIn("fonts.googleapis.com/css2?family=Noto+Sans+KR", source)
                self.assertIn('aria-label="다크 모드로 전환"></button>', source)
                self.assertNotIn(">다크 모드</button>", source)


if __name__ == "__main__":
    unittest.main()
