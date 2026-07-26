from html.parser import HTMLParser
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


if __name__ == "__main__":
    unittest.main()
