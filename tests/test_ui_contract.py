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


if __name__ == "__main__":
    unittest.main()
