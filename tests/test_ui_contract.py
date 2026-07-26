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
}


class Markup(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.views = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        if attrs.get("data-view"):
            self.views.add(attrs["data-view"])


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


if __name__ == "__main__":
    unittest.main()
