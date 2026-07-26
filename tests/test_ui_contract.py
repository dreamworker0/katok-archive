from html.parser import HTMLParser
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent.parent
VIEWS = {
    "summary",
    "graph",
    "timeline",
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
    "themeBtn",
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
        self.assertIn(".sidebar-session .chip", self.css)
        self.assertIn(".sidebar-session .icon-btn", self.css)
        self.assertIn(".theme-toggle svg", self.css)
        self.assertIn("width: 36px", self.css)

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
