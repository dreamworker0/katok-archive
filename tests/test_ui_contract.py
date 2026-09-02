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


def front_end_js() -> str:
    """app.js 와 거기서 떼어낸 화면 조각 전부를 이어 읽는다.

    이 검사들이 묻는 것은 "프런트가 이렇게 하는가" 이고, 그 답은 두 파일에 걸쳐
    있다. 글자·마크다운 다루기는 `web/text.js` 로 떼어냈다(app.js 안에 있는 동안
    동작 검사가 하나도 없었다 — 닫힌 IIFE 라 node 에서 부를 방법이 없었다).

    한쪽만 읽으면 코드를 옮길 때마다 이 검사들이 함께 깨진다. 실제로 떼어낼 때
    네 건이 그렇게 깨졌는데, 프런트의 동작은 하나도 바뀌지 않았다 — 검사가 파일
    경계를 본 것이지 동작을 본 것이 아니라는 뜻이다.

    동작 자체는 `tests/text.test.js` 가 실제로 함수를 불러서 본다.
    """
    parts = [(ROOT / "web" / name).read_text(encoding="utf-8")
             for name in ("app.js", "text.js", "timeline.js", "summary.js", "graph-view.js", "tags.js",
                          "gallery.js", "stats.js", "mine.js", "admin.js")]
    return "".join(parts)


def fn_body(src: str, name: str) -> str:
    """`function name(` 의 본문 — 들여쓰기와 무관하게 중괄호를 맞춰 자른다.

    화면 조각을 stats.js·mine.js·admin.js 로 떼어낸 뒤(2026-09-02) 같은 이름이 두 번
    나온다 — app.js 의 한 줄 위임 스텁과 조각 파일의 진짜 본문. 줄 앞 공백 수로
    자르던 검사는 스텁을 잡거나 파일 끝까지 먹었다. 가장 긴 본문이 진짜다.
    """
    best = ""
    start = 0
    while True:
        i = src.find("function %s(" % name, start)
        if i < 0:
            break
        j = src.index("{", i)
        depth, k = 0, j
        while k < len(src):
            c = src[k]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        body = src[i:k + 1]
        if len(body) > len(best):
            best = body
        start = i + 1
    if not best:
        raise ValueError("function %s 을 찾지 못했다" % name)
    return best


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


class ArchiveRebindContractTests(unittest.TestCase):
    """ARCHIVE 에서 뽑아 둔 값은 `init()` 에서 **다시** 읽어야 한다.

    보호모드(hosting)에서는 app.js 가 boot.js 보다 먼저 실행되므로 파일 위쪽의
    `window.ARCHIVE` 는 늘 비어 있다. boot.js 가 Firestore 로드를 끝낸 뒤 init() 을
    부르는데, 거기서 다시 읽지 않은 변수는 영원히 빈 값으로 남는다.

    실측 2026-07-28: TAGIDX·THREAD_BY_ID·TAG_THREADS 를 빠뜨려 태그 화면이 "아직
    모인 태그가 없어요", 분류 카드의 '곁 주제' 가 안 보였다. 데이터는 Firestore 에
    정상으로 올라가 있었다.
    """

    @classmethod
    def setUpClass(cls):
        cls.app = front_end_js()
        cls.init = cls.app[cls.app.index("function init(session)"):]

    def test_every_archive_derived_global_is_rebound_in_init(self):
        head = self.app[:self.app.index("function init(session)")]
        # 파일 위쪽에서 window.ARCHIVE(=A) 로 만든 전역들
        names = set(re.findall(r"var ([A-Z][A-Z_0-9]*) = A\.", head))
        names |= {"THREAD_BY_ID", "TAG_THREADS"}  # A 로 만든 파생 색인
        for name in sorted(names):
            with self.subTest(name=name):
                self.assertRegex(self.init, r"\b%s = " % name,
                                 "%s 를 init() 에서 다시 읽지 않는다" % name)


class FileOriginContractTests(unittest.TestCase):
    """원본을 못 구한 첨부를 '만료' 와 '수집 대기' 로 가르는 뼈대.

    하나로 뭉뚱그리면 읽는 사람이 '아직 안 올린 것' 으로 읽는다. 사진 쪽에서 유실과
    수집 대기를 이미 갈라 둔 것과 같은 이유다. 첨부가 보이는 자리는 세 곳이라
    (주제 보고서 안 · 첨부파일 화면 · 내 글) 한 곳만 고치면 화면끼리 말이 달라진다.
    """

    @classmethod
    def setUpClass(cls):
        cls.app = front_end_js()
        cls.css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
        cls.py = (ROOT / "scripts" / "build_site.py").read_text(encoding="utf-8")

    def test_all_three_places_tell_the_two_apart(self):
        # 첨부가 보이는 세 자리가 모두 file_expired 를 본다
        self.assertGreaterEqual(self.app.count("m.file_expired"), 3, self.app.count("m.file_expired"))

    def test_no_place_still_says_only_original_missing(self):
        """'원본 없음' 한 마디로 끝내는 자리가 남아 있으면 안 된다."""
        self.assertNotIn('">원본 없음</span>', self.app)
        self.assertNotIn('"원본을 구하지 못한 파일"', self.app)

    def test_the_two_states_look_different(self):
        # 60여 개를 훑을 때 글자만 다르면 구분이 안 된다
        self.assertIn(".fc-gone", self.css)
        self.assertIn(".fc-none", self.css)

    def test_the_count_line_says_how_many_are_gone(self):
        self.assertIn('" · 만료 " + gone.length', self.app)

    def test_the_note_does_not_explain_a_label_that_is_not_shown(self):
        block = fn_body(self.app, "renderFiles")
        self.assertIn("if (pending)", block[:4000])
        self.assertIn("if (gone.length)", block[:4000])

    def test_the_screen_and_the_publisher_agree_on_the_field(self):
        """화면이 보는 이름과 발행이 적는 이름이 같아야 한다."""
        self.assertIn('"file_expired"', self.py)

    def test_retention_days_are_not_written_twice_differently(self):
        """보관 기간은 발행 쪽이 원본이다 — 화면 안내문의 숫자가 어긋나면 거짓말이 된다."""
        m = re.search(r"FILE_RETENTION_DAYS = (\d+)", self.py)
        self.assertIsNotNone(m, "발행 쪽에 보관 기간 상수가 없습니다")
        days = m.group(1)
        for text in ("카톡 보관 기간(%s일)" % days, "파일을 %s일만 보관" % days):
            self.assertIn(text, self.app, text)


class TagPickContractTests(unittest.TestCase):
    """태그를 여러 개 골라 겹치는 주제를 보는 기능의 뼈대."""

    @classmethod
    def setUpClass(cls):
        cls.app = front_end_js()
        cls.css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")

    def test_pick_limit_is_stated_once_and_shown_to_the_user(self):
        self.assertIn("var TAG_PICK_MAX = 3", self.app)
        # 화면 안내문도 같은 값을 쓴다 — 숫자를 두 곳에 적으면 어긋난다
        # (tags.js 로 떼어낸 뒤에는 ctx 로 건네받는다 — 값은 여전히 한 곳이다)
        self.assertIn('"개 · 최대 " + ctx.TAG_PICK_MAX', self.app)

    def test_intersection_not_union(self):
        # 고른 태그가 **모두** 붙은 주제만 남아야 한다
        block = self.app[self.app.index("function tagPickIds()"):]
        self.assertIn("sets.every(", block[:600])

    def test_dead_combinations_are_disabled_before_the_user_taps(self):
        self.assertIn("disabled", fn_body(self.app, "renderTags")[:3000])
        self.assertIn(".tag-chip[disabled]", self.css)

    def test_selected_state_has_its_own_look(self):
        self.assertIn(".tag-chip.on", self.css)

    def test_translit_table_matches_the_publisher(self):
        """화면의 음역 대응표가 발행 쪽과 같아야 한다.

        발행 때 'Claude Code' 를 '클로드 코드' 로 합쳐 놓는다. 화면이 그 대응을
        모르면 카드에 적힌 원래 표기('Claude Code')를 눌렀을 때 태그가 열리지
        않고 글자 검색으로 떨어진다 — 눌러도 아무 일 없는 것처럼 보인다.
        """
        from scripts.tags import TRANSLIT

        block = self.app[self.app.index("var TAG_TRANSLIT = {"):]
        block = block[:block.index("};") + 1]
        pairs = dict(re.findall(r'([A-Za-z][\w]*)\s*:\s*"([^"]+)"', block))
        self.assertEqual(pairs, TRANSLIT,
                         "web/app.js 의 TAG_TRANSLIT 과 scripts/tags.py 의 "
                         "TRANSLIT 이 어긋났습니다")

    def test_cards_show_the_published_tags_not_the_raw_keywords(self):
        """카드 칩은 발행 때 통일·승격한 `tags` 여야 한다.

        '온톨로지 모델링' 주제를 '온톨로지' 로 찾아 들어왔는데 카드에 '온톨로지' 가
        없으면 "이게 왜 여기 있지" 가 된다. 표기도 카드마다 갈리지 않는다.
        """
        block = self.app[self.app.index('<div class="tc-kw">') - 400:]
        block = block[:800]
        self.assertIn("t.tags || t.keywords", block,
                      "카드 칩이 원본 keywords 로 되돌아갔습니다")

    def test_cloud_leaves_out_people_and_places(self):
        """태그 구름은 '무엇을 이야기했나' 의 자리다.

        사람 이름과 지명·기관 이름은 구름에서 빼고 아래에 따로 모은다 — 이름으로
        주제를 찾는 사람은 없고(참여자 필터가 그 몫이다), 1회짜리 지명이 구름을
        채우면 정작 화제가 눈에 안 들어온다. 빼는 것이지 지우는 것이 아니므로
        검색으로는 그대로 찾힌다.
        """
        block = fn_body(self.app, "renderTags")[:900]
        self.assertIn("!r.person && !r.place", block)
        self.assertIn("r.place", block)
        # 따로 모은 것도 화면에 있어야 한다 — 빼고 안 보여주면 사라진 것과 같다
        later = fn_body(self.app, "renderTags")[:6000]
        self.assertIn("지명·기관 이름으로 붙은 태그", later)
        self.assertIn("사람 이름으로 붙은 태그", later)

    def test_tag_fold_transliterates_whole_words_only(self):
        block = self.app[self.app.index("function tagFold(s)"):][:400]
        # 조각으로 끊어 낱말 단위로만 바꿔야 '프로젝트'가 망가지지 않는다
        self.assertIn(".split(", block)
        self.assertIn("TAG_TRANSLIT[p]", block)


class RoutingContractTests(unittest.TestCase):
    """보고 있는 화면이 주소에 남아야 한다.

    없으면 F5·뒤로 가기에서 첫 화면으로 튕기고, 남에게 링크를 줄 수도 없다.
    """

    @classmethod
    def setUpClass(cls):
        cls.app = front_end_js()

    def test_view_change_writes_the_address(self):
        block = self.app[self.app.index("function setView(v)"):]
        self.assertIn("writeHash()", block[:500])

    def test_startup_reads_the_address_before_falling_back(self):
        # 주소에 화면이 적혀 있으면 그리로 가야 한다
        block = self.app[self.app.index("setNavigationState(state.view);\n    // 주소에"):]
        self.assertIn("if (!applyHash())", block[:400])

    def test_back_and_forward_are_both_handled(self):
        for ev in ("hashchange", "popstate"):
            with self.subTest(event=ev):
                self.assertIn('addEventListener("%s", onRouteChange)' % ev, self.app)

    def test_typing_does_not_pile_up_history(self):
        """검색은 주소를 바꿔치기한다 — 한 글자마다 히스토리가 쌓이면 뒤로 가기가
        글자 지우기가 된다."""
        block = self.app[self.app.index('el.search.addEventListener("input"'):]
        self.assertIn("writeHash(true)", block[:900])

    def test_path_routing_with_a_server_rewrite(self):
        """경로 주소(`/tags`)를 쓴다 — `#` 없이. 그러려면 없는 경로를 index.html 로
        되돌리는 규칙이 **양쪽 서버**에 있어야 한다. 하나만 있으면 배포본이나
        로컬 미리보기 한쪽에서 새로고침이 404 가 된다."""
        self.assertIn('return "/" + state.view', self.app)
        fb = json.loads((ROOT / "firebase.json").read_text(encoding="utf-8"))
        for site in fb["hosting"]:
            with self.subTest(site=site["site"]):
                rules = site.get("rewrites", [])
                self.assertEqual(len(rules), 1, "화면 경로만 되돌려야 한다")
                src = rules[0]["source"]
                self.assertEqual(rules[0]["destination"], "/index.html")
                # 모든 경로를 되돌리면 없는 그림까지 200+HTML 이 되어, 무엇이
                # 빠졌는지 알 수 없다(실측 `/nope.png` 200).
                self.assertNotEqual(src, "**")
                for view in VIEWS:
                    with self.subTest(view=view):
                        self.assertIn(view, src, "새 화면을 rewrites 에 안 넣었다")
        serve = (ROOT / "scripts" / "serve_hosting.py").read_text(encoding="utf-8")
        self.assertIn("path.strip(\"/\") in view_names()", serve)

    def test_old_hash_links_still_open(self):
        # 이미 나눠준 `#/mine` 같은 링크가 깨지면 안 된다
        self.assertIn("out.legacy = true", self.app)
        self.assertIn("if (r.legacy) writeHash(true)", self.app)

    def test_thread_ids_are_not_put_in_the_address(self):
        block = self.app[self.app.index("function stateToPath()"):]
        block = block[:block.index("\n  }")]
        self.assertNotIn("pick", block, "추림(주제 ID 목록)은 주소에 담지 않는다")


class InlineDisplayContractTests(unittest.TestCase):
    """CSS 기본이 `display: none` 인 요소는 **구체적인 값**으로 보여야 한다.

    실측 2026-07-28: 동영상을 열 때 `v.style.display = ""` 로 되돌렸더니 인라인
    스타일이 사라져 `#lightboxVideo { display: none }` 이 다시 이겼다. 숨은
    `<video>` 도 재생은 되므로 **소리는 나고 화면은 안 보였다** — 원인을 찾기
    어려운 종류의 증상이다.
    """

    @classmethod
    def setUpClass(cls):
        cls.app = front_end_js()
        cls.css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")

    def test_ids_hidden_by_css_are_shown_with_an_explicit_value(self):
        hidden_ids = set(re.findall(r"#([A-Za-z][\w-]*)\s*\{[^}]*display:\s*none",
                                    self.css))
        self.assertIn("lightboxVideo", hidden_ids, "검사가 낡았다 — CSS 가 바뀌었다")
        for name in sorted(hidden_ids):
            if name not in self.app:
                continue
            with self.subTest(id=name):
                # 그 요소를 다루는 코드가 빈 문자열로 되돌리지 않는지
                self.assertNotRegex(
                    self.app, r'%s[^;]{0,200}style\.display = ""' % re.escape(name),
                    "#%s 는 CSS 가 숨기고 있어 빈 값으로는 다시 보이지 않는다" % name)


class HiddenAttributeContractTests(unittest.TestCase):
    """`el.hidden = true` 로 숨기는 요소는 CSS 가 그것을 이기지 않아야 한다.

    실측 2026-07-28: `.tag-chip { display: inline-flex }` 가 브라우저 기본
    `[hidden] { display: none }` 보다 세서, 태그 좁히기 검색이 아무 일도 하지
    않았다(hidden 은 걸렸는데 칩이 그대로 보였다).
    """

    @classmethod
    def setUpClass(cls):
        cls.app = front_end_js()
        cls.css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")

    def test_js_hidden_targets_have_a_matching_css_rule(self):
        # JS 가 `.hidden =` 로 숨기는 클래스들
        classes = set()
        for m in re.finditer(r"\.hidden = ", self.app):
            head = self.app[max(0, m.start() - 400):m.start()]
            classes.update(re.findall(r'querySelectorAll\("\.([a-z-]+)"\)', head))
        self.assertTrue(classes, "숨기는 대상을 못 찾았다 — 검사 자체가 낡았다")
        for name in sorted(classes):
            with self.subTest(cls=name):
                declares_display = re.search(
                    r"\.%s\s*\{[^}]*display:" % re.escape(name), self.css)
                if not declares_display:
                    continue
                self.assertRegex(
                    self.css, r"\.%s\[hidden\]\s*\{[^}]*display:\s*none" % re.escape(name),
                    ".%s 에 display 가 있으니 [hidden] 규칙도 있어야 한다" % name)


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
        app = front_end_js()
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
        app = front_end_js()
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
        cls.app = front_end_js()

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


class InlineVideoContractTests(unittest.TestCase):
    """본문 사이의 자리표는 동영상도 그려야 한다.

    실측 2026-08-31 t-426: `mediaHtml` 이 `image` 와 `file` 만 그려서, 동영상
    한 편짜리 주제는 "이 주제에서 함께 공유된 자료" 라는 제목만 뜨고 아래가
    비었다. 갤러리는 같은 동영상을 잘 그리고 있었다 — 두 곳이 같은 자료를
    다르게 알고 있던 것이다.
    """

    @classmethod
    def setUpClass(cls):
        cls.app = front_end_js()
        cls.css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
        start = cls.app.index("function mediaHtml(")
        cls.fn = cls.app[start:cls.app.index("\n  }", start)]

    def test_media_html_draws_videos(self):
        self.assertIn('m.kind === "video"', self.fn,
                      "본문 사이 자료 그리기가 동영상을 모릅니다")
        self.assertIn("m.videos", self.fn)

    def test_video_cell_opens_the_player_not_the_image_viewer(self):
        # 라이트박스는 data-video 를 보고 <video> 로 연다. 이 표시가 없으면
        # 16MB 짜리 mp4 를 <img> 에 넣으려다 빈 칸이 된다.
        self.assertIn('data-video="1"', self.fn)

    def test_video_poster_is_not_the_original(self):
        # 목록을 훑기만 해도 원본이 내려오면 안 된다 — 칸에는 포스터,
        # 원본은 눌렀을 때(data-full).
        self.assertIn("m.thumbs", self.fn)

    def test_play_badge_has_a_style_of_its_own(self):
        self.assertIn(".im-video {", self.css,
                      "재생 표시에 자리가 없으면 포스터 위에 얹히지 않습니다")
        self.assertIn("pointer-events: none", self.css)


class MyVideoContractTests(unittest.TestCase):
    """내 동영상도 골라서 내릴 수 있어야 한다.

    `mineKind` 가 동영상을 몰라 '글' 로 떨어졌고, 내 동영상은 "동영상" 이라는
    글 한 줄로 보였다. 무엇을 지울지 고르려면 봐야 하는데 볼 것이 없었다.
    통계 쪽은 더 나빴다 — 동영상을 **첨부로** 세어 '올린 파일' 칸이 있지도
    않은 파일을 셌다.
    """

    @classmethod
    def setUpClass(cls):
        cls.app = front_end_js()
        cls.css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")

    def test_mine_kind_knows_video(self):
        block = fn_body(self.app, "mineKind")
        self.assertIn('m.kind === "video"', block)
        self.assertIn('return "video"', block)

    def test_my_video_row_shows_a_poster_that_plays(self):
        block = fn_body(self.app, "mineRow")
        self.assertIn('kind === "video"', block)
        self.assertIn("m.videos", block)
        # .mine-thumb 에 걸린 클릭이 라이트박스를 연다 — data-video 가 있어야
        # <img> 가 아니라 <video> 로 열린다.
        self.assertIn("mine-thumb", block)
        self.assertIn('data-video="1"', block)

    def test_the_kind_tally_has_a_slot_for_video(self):
        # 없으면 counts[mineKind(m)]++ 가 NaN 이 되어 머리글의 숫자가 사라진다.
        self.assertIn("{ text: 0, image: 0, video: 0, file: 0 }", self.app)

    def test_footprint_does_not_count_videos_as_files(self):
        block = fn_body(self.app, "myFootprint")
        self.assertIn('m.kind === "video"', block,
                      "'올린 파일' 칸이 동영상을 파일로 셉니다")

    def test_play_badge_is_shared_by_both_views(self):
        # 한쪽에만 표시가 있으면 다른 쪽에서는 포스터를 사진으로 읽는다.
        self.assertIn(".im-video .play", self.css)
        self.assertNotIn(".imgs .im-video", self.css)


class MobileDensityContractTests(unittest.TestCase):
    """모바일에서 첫 화면이 읽을 만한 길이로 유지되는지.

    12개 주제 카드가 전부 펼쳐졌을 때 첫 화면이 20,375px(25화면 분량)였다. 접기를
    넣어 4,647px(5.7화면)로 줄였다. 개수를 줄여 정보를 버리는 대신 접었다 —
    발행에서 빼면 "그 앱 어디 갔지" 를 되찾을 방법이 없다.
    """

    @classmethod
    def setUpClass(cls):
        cls.css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
        cls.app = front_end_js()
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
        """주제 개수는 세지 않는다 — doc-meta 가 위에서 이미 "N개 주제" 를 적는다.

        검사 범위를 '자세히 보기' 힌트를 만드는 대목으로 좁힌다. 파일 전체를 보면
        결과물 버튼의 '주제 3 · 언급 3' 같은 다른 자리의 표기까지 걸린다.
        """
        self.assertIn('개 메시지 · " + (d.threads || []).length + "개 주제', self.app)
        start = self.app.index("var counts = [];")
        hint = self.app[start:self.app.index("var body =", start)]
        self.assertNotIn('counts.push("주제 ', hint)

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
        # 칩은 button 이었다가 a(.cat-nav-item)가 됐다 — 주제별로 건넬 주소가
        # 있어야 해서다(2026-08-27). 이름이 무엇이든 **줄지 않아야** 한다.
        self.assertIn(".cat-nav button, .cat-nav-item { flex: 0 0 auto;", self.mobile)
        # 숨기지 않았는지.
        self.assertNotIn(".cat-nav { display: none", self.mobile)

    def test_category_chips_are_real_links(self):
        """골라가기 칩과 주제 제목은 주소를 가진 링크다.

        예전에는 페이지 안에서 자리를 옮기기만 해서 "저 주제 봐"라고 건넬 주소가
        없었다. 눌러서 가는 것과 링크로 건네는 것은 다른 일이다.
        """
        self.assertIn('href="/summary?cat=', self.app)
        self.assertIn("cat-nav-item", self.css)
        self.assertIn(".doc-title .doc-link", self.css)
        # 제목이 링크 색으로 물들면 문서가 아니라 목록처럼 읽힌다.
        self.assertIn(".doc-title .doc-link { color: inherit;", self.css)

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
        cls.app = front_end_js()

    def test_summary_opens_with_archive_welcome(self):
        self.assertIn("archive-welcome", self.app)
        self.assertIn("함께 나눈 이야기를", self.app)

    def test_core_views_share_a_kind_empty_state(self):
        self.assertIn("function emptyState(", self.app)
        self.assertGreaterEqual(self.app.count("emptyState("), 5)


class UiSafetyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = front_end_js()

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
