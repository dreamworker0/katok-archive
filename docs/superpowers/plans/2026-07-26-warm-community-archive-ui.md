# Warm Community Archive UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign every user-facing state as a spacious, warm community archive while preserving the current Firebase security model, data contracts, and eight archive views.

**Architecture:** Keep the existing no-build vanilla HTML/CSS/JavaScript application and its `data-view` routing contract. Replace the app shell and visual tokens, add one reusable confirmation dialog, and add a small deterministic image-optimization pipeline; do not change Firebase schemas, rules, upload logic, or view data models.

**Tech Stack:** HTML5, CSS custom properties, vanilla JavaScript, Python 3 `unittest`, Pillow 12+, Node.js built-in test runner, Firebase Hosting/Auth/Firestore/Storage.

## Global Constraints

- Primary environment is desktop; mobile must remain fully responsive.
- Preserve all eight views: `summary`, `graph`, `timeline`, `gallery`, `files`, `stats`, `mine`, `admin`.
- Preserve the existing element IDs and `data-view` values consumed by `web/app.js`.
- Preserve Firebase Auth, Firestore, Storage, Cloud Functions, security rules, and stored data shapes.
- The visible brand is “우리의 기록”; the current room name and “사회복지 바이브코딩 아카이브” remain as metadata.
- Use the light palette `#FBF6EE`, `#FFFDF8`, `#3C332C`, `#CA7154`, `#879D78`, `#B85F4B`.
- Use the dark palette `#292521`, `#37312C`, `#F4EBDD`, `#CABBAC`, `#DF8B6D`, `#9CAE8C`.
- Do not add a font, UI framework, bundler, or runtime dependency.
- Generated artwork must not contain identifiable faces, KakaoTalk UI, logos, readable text, or watermarks.
- Hero WebP must be at most 250KB; each state WebP must be at most 80KB.
- Respect `prefers-reduced-motion` and WCAG AA contrast.
- Keep `.superpowers/` and source image-generation outputs out of Git.

---

## File Structure

### Files to create

- `tests/test_ui_contract.py` — static app-shell, navigation, accessibility, CSS-token, and production-artifact contract tests.
- `tests/test_optimize_ui_art.py` — deterministic tests for converting generated source art into bounded WebP files.
- `scripts/optimize_ui_art.py` — Pillow-based image resizing and WebP optimization only.
- `web/art/archive-hero.webp` — shared login/home illustration.
- `web/art/state-pending.webp` — approval-pending illustration.
- `web/art/state-empty.webp` — empty archive illustration.
- `web/art/state-search.webp` — empty search-result illustration.

### Files to modify

- `web/index.html` — local-preview desktop sidebar, mobile navigation, utility bar, and confirmation dialog.
- `web/index.hosting.html` — the same shell plus the existing Firebase gate and SDK scripts.
- `web/styles.css` — warm design tokens, responsive shell, state screens, view polish, dark theme, accessibility.
- `web/app.js` — navigation synchronization, welcome/empty-state markup, user-facing consent labels, reusable confirmation dialog.
- `web/boot.js` — login, claim, pending, loading, and error state markup and copy.
- `scripts/build_site.py` — copy non-sensitive `web/art/` into local preview output.
- `scripts/build_hosting.py` — copy non-sensitive `web/art/` into Hosting while continuing to reject conversation assets.
- `.gitignore` — ignore `assets/design-source/`, where generated full-resolution source images are kept locally.

No Firebase rules, Functions, parser, payload, upload, or stored archive-data file is modified.

---

### Task 1: Lock the Shared App-Shell Contract

**Files:**
- Create: `tests/test_ui_contract.py`
- Modify: `web/index.html:9-44`
- Modify: `web/index.hosting.html:21-64`
- Test: `tests/test_ui_contract.py`

**Interfaces:**
- Consumes: existing IDs `appRoot`, `tabs`, `searchInput`, `participantFilter`, `sessionBox`, `themeBtn`, `view`, `lightbox`.
- Produces: desktop navigation `#tabs`, mobile navigation `#mobileNav`, and mobile menu `#mobileMore` for later tasks.

- [ ] **Step 1: Write the failing shell-contract test**

```python
# tests/test_ui_contract.py
from html.parser import HTMLParser
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent
VIEWS = {"summary", "graph", "timeline", "gallery", "files", "stats", "mine", "admin"}
REQUIRED_IDS = {
    "appRoot", "tabs", "mobileNav", "mobileMore", "searchInput",
    "participantFilter", "sessionBox", "themeBtn", "view",
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
```

- [ ] **Step 2: Run the test and verify the new shell contract fails**

Run:

```powershell
python -m unittest tests.test_ui_contract.UiShellContractTests -v
```

Expected: FAIL because `mobileNav`, `mobileMore`, `mine`, or `admin` is missing from at least one page.

- [ ] **Step 3: Replace both app shells with the approved structure**

Use the same app-shell markup in both HTML files. The local file starts with
`class="app"`; only the Hosting file keeps `class="app hidden"` because `boot.js`
reveals it after authentication:

```html
<div class="app" id="appRoot">
  <aside class="sidebar" aria-label="주요 탐색">
    <div class="brand-lockup">
      <strong>우리의 기록</strong>
      <span id="roomTitle">아카이브</span>
      <small id="roomSub"></small>
    </div>
    <nav class="side-nav" id="tabs">
      <p class="nav-label">둘러보기</p>
      <button class="tab active" data-view="summary" aria-current="page">주제별 지식</button>
      <button class="tab" data-view="timeline">타임라인</button>
      <button class="tab" data-view="graph">관계망</button>
      <p class="nav-label">모아보기</p>
      <button class="tab" data-view="gallery">갤러리</button>
      <button class="tab" data-view="files">첨부파일</button>
      <button class="tab" data-view="stats">통계</button>
      <p class="nav-label">나의 공간</p>
      <button class="tab" data-view="mine">내 글 관리</button>
      <button class="tab" data-view="admin">관리자</button>
    </nav>
    <div class="sidebar-session" id="sessionBox"></div>
    <button class="theme-toggle" id="themeBtn" type="button" aria-label="화면 테마 전환">테마 전환</button>
  </aside>
  <div class="app-main">
    <header class="utility-bar">
      <label class="search">
        <span aria-hidden="true">⌕</span>
        <input id="searchInput" type="search" placeholder="대화·사람·주제 검색" autocomplete="off" />
      </label>
      <label class="filter">
        <span class="sr-only">참여자 필터</span>
        <select id="participantFilter"><option value="">전체 참여자</option></select>
      </label>
    </header>
    <main class="view" id="view"><p class="hint">불러오는 중…</p></main>
  </div>
  <nav class="mobile-nav" id="mobileNav" aria-label="모바일 주요 탐색">
    <button data-view="summary" aria-current="page">홈</button>
    <button data-view="timeline">타임라인</button>
    <button data-view="gallery">사진</button>
    <button data-view="mine">내 기록</button>
    <button id="mobileMoreButton" type="button" aria-controls="mobileMore" aria-expanded="false">더보기</button>
  </nav>
  <div class="mobile-more" id="mobileMore" hidden></div>
</div>
```

Keep the existing lightbox and script ordering unchanged. Local preview includes `mine` and `admin`; existing session checks remove them during initialization.

- [ ] **Step 4: Run the shell test**

Run:

```powershell
python -m unittest tests.test_ui_contract.UiShellContractTests -v
```

Expected: PASS.

- [ ] **Step 5: Build the local preview to catch missing IDs**

Run:

```powershell
python -m scripts.build_site
```

Expected: `site/` is regenerated without an exception.

- [ ] **Step 6: Commit the shell contract**

```powershell
git add tests/test_ui_contract.py web/index.html web/index.hosting.html
git commit -m "feat: 따뜻한 아카이브 앱 셸 구성"
```

---

### Task 2: Add Warm Design Tokens and Responsive Layout

**Files:**
- Modify: `tests/test_ui_contract.py`
- Modify: `web/styles.css:1-90`
- Modify: `web/styles.css:408-547`
- Test: `tests/test_ui_contract.py`

**Interfaces:**
- Consumes: shell class names from Task 1.
- Produces: CSS variables and responsive layout used by every later visual task.

- [ ] **Step 1: Add failing CSS-contract tests**

```python
class UiStyleContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")

    def test_warm_palette_tokens_exist(self):
        for value in ("#FBF6EE", "#FFFDF8", "#3C332C", "#CA7154", "#879D78", "#B85F4B"):
            self.assertIn(value.lower(), self.css.lower())

    def test_dark_theme_and_reduced_motion_are_explicit(self):
        self.assertIn(':root[data-theme="dark"]', self.css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", self.css)

    def test_desktop_and_mobile_navigation_rules_exist(self):
        self.assertIn(".sidebar", self.css)
        self.assertIn(".mobile-nav", self.css)
        self.assertIn("@media (max-width: 760px)", self.css)
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
python -m unittest tests.test_ui_contract.UiStyleContractTests -v
```

Expected: FAIL on the warm palette and new shell selectors.

- [ ] **Step 3: Replace the root tokens**

Define readable semantic tokens instead of repeating literal colors:

```css
:root {
  --bg: #FBF6EE;
  --surface: #FFFDF8;
  --surface-2: #F4EEE5;
  --ink: #3C332C;
  --ink-soft: #706257;
  --ink-faint: #99887A;
  --line: #E7DDD1;
  --line-strong: #D6C8BA;
  --accent: #CA7154;
  --accent-soft: #F4DDCF;
  --accent-ink: #FFFDF8;
  --sage: #879D78;
  --danger: #B85F4B;
  --danger-soft: #FAE7E0;
  --shadow-sm: 0 8px 24px rgba(62, 49, 38, .06);
  --shadow: 0 18px 52px rgba(62, 49, 38, .10);
  --radius: 18px;
  --sidebar-width: 240px;
  --reading-width: 72ch;
  --content-width: 1180px;
}
```

Apply the exact dark tokens from Global Constraints in both system-preference and explicit dark selectors.

- [ ] **Step 4: Implement the desktop shell**

Implement:

- `.app` as a two-column full-width grid.
- `.sidebar` as a sticky, full-height 240px rail.
- `.app-main` with `min-width: 0`.
- `.utility-bar` as a sticky top search/filter row.
- `.view` with `max-width: var(--content-width)` and 32–48px desktop padding.
- `.side-nav .tab` as full-width buttons with icon space, rounded active background, and no tab underline.
- `.mobile-nav` and `.mobile-more` hidden above 760px.

```css
.app {
  display: grid;
  grid-template-columns: var(--sidebar-width) minmax(0, 1fr);
  min-height: 100vh;
}
.sidebar {
  position: sticky;
  top: 0;
  display: flex;
  flex-direction: column;
  height: 100vh;
  padding: 28px 18px 18px;
  border-right: 1px solid var(--line);
  background: var(--surface);
}
.app-main { min-width: 0; }
.utility-bar {
  position: sticky;
  top: 0;
  z-index: 20;
  display: flex;
  gap: 12px;
  padding: 18px 32px;
  border-bottom: 1px solid var(--line);
  background: color-mix(in srgb, var(--bg) 90%, transparent);
  backdrop-filter: blur(12px);
}
.view {
  width: 100%;
  max-width: var(--content-width);
  margin: 0 auto;
  padding: 36px 40px 56px;
}
.mobile-nav, .mobile-more { display: none; }
```

- [ ] **Step 5: Implement the mobile shell**

At `max-width: 760px`:

- Collapse `.app` to one column.
- Hide `.sidebar`.
- Show `.mobile-nav` fixed at the bottom with five equal targets.
- Add bottom padding to `.view` so content is not hidden behind navigation.
- Stack search and filter without horizontal overflow.
- Show `.mobile-more` as a bottom sheet.

```css
@media (max-width: 760px) {
  .app { display: block; }
  .sidebar { display: none; }
  .utility-bar { padding: 12px 16px; }
  .view { padding: 24px 16px 104px; }
  .mobile-nav {
    position: fixed;
    z-index: 40;
    right: 0;
    bottom: 0;
    left: 0;
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    padding: 8px max(8px, env(safe-area-inset-right))
      calc(8px + env(safe-area-inset-bottom))
      max(8px, env(safe-area-inset-left));
    border-top: 1px solid var(--line);
    background: color-mix(in srgb, var(--surface) 94%, transparent);
    backdrop-filter: blur(14px);
  }
  .mobile-more {
    position: fixed;
    z-index: 50;
    right: 12px;
    bottom: calc(76px + env(safe-area-inset-bottom));
    left: 12px;
    display: grid;
    gap: 8px;
    padding: 16px;
    border: 1px solid var(--line);
    border-radius: 20px;
    background: var(--surface);
    box-shadow: var(--shadow);
  }
  .mobile-more[hidden] { display: none; }
}
```

At `761px–1024px`, keep the sidebar but reduce it to 208px and use two-column content grids.

- [ ] **Step 6: Add accessibility and motion rules**

```css
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

:focus-visible {
  outline: 3px solid color-mix(in srgb, var(--accent) 72%, white);
  outline-offset: 3px;
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    scroll-behavior: auto !important;
    animation-duration: .01ms !important;
    transition-duration: .01ms !important;
  }
}
```

- [ ] **Step 7: Run the focused tests**

Run:

```powershell
python -m unittest tests.test_ui_contract.UiStyleContractTests -v
```

Expected: PASS.

- [ ] **Step 8: Commit the visual system**

```powershell
git add tests/test_ui_contract.py web/styles.css
git commit -m "feat: 따뜻한 아카이브 디자인 토큰과 반응형 셸"
```

---

### Task 3: Synchronize Desktop and Mobile Navigation

**Files:**
- Modify: `tests/test_ui_contract.py`
- Modify: `web/app.js:1954-2045`
- Test: `tests/test_ui_contract.py`

**Interfaces:**
- Consumes: `[data-view]` controls, `#mobileMoreButton`, `#mobileMore`, `setView(view)`.
- Produces: `setNavigationState(view)`, `setMobileMore(open)`, and synchronized `aria-current`.

- [ ] **Step 1: Add failing JavaScript-contract tests**

```python
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
```

- [ ] **Step 2: Run the test and verify failure**

Run:

```powershell
python -m unittest tests.test_ui_contract.UiJavascriptContractTests -v
```

Expected: FAIL because the current router only toggles direct children of `#tabs`.

- [ ] **Step 3: Add navigation state helpers**

Add element references for the mobile controls and implement:

```javascript
function setNavigationState(view) {
  Array.prototype.forEach.call(document.querySelectorAll("[data-view]"), function (control) {
    var active = control.getAttribute("data-view") === view;
    control.classList.toggle("active", active);
    if (active) control.setAttribute("aria-current", "page");
    else control.removeAttribute("aria-current");
  });
}

function setMobileMore(open) {
  el.mobileMore.hidden = !open;
  el.mobileMoreButton.setAttribute("aria-expanded", open ? "true" : "false");
}
```

`setView(v)` calls `setNavigationState(v)` and closes the mobile sheet before rendering.

- [ ] **Step 4: Bind navigation without duplicate listeners**

Bind one delegated click handler on `#appRoot` for `[data-view]`. Remove the old handler attached only to `#tabs`.

Populate `#mobileMore` with buttons for `graph`, `files`, `stats`, and `admin`, plus theme and sign-out actions. Hide `mine` and `admin` in both desktop and mobile controls when the existing permission checks fail.

Close the mobile sheet on Escape and on clicks outside the sheet. Return focus to `#mobileMoreButton`.
While the sheet is open, Tab and Shift+Tab cycle through its interactive controls.

```javascript
el.app.addEventListener("click", function (event) {
  var viewControl = event.target.closest("[data-view]");
  if (viewControl) {
    setView(viewControl.getAttribute("data-view"));
    return;
  }
  if (event.target.closest("#mobileMoreButton")) {
    setMobileMore(el.mobileMore.hidden);
    return;
  }
  if (!el.mobileMore.hidden && !event.target.closest("#mobileMore")) {
    setMobileMore(false);
  }
});

document.addEventListener("keydown", function (event) {
  if (event.key === "Escape" && !el.mobileMore.hidden) {
    setMobileMore(false);
    el.mobileMoreButton.focus();
  }
  if (event.key === "Tab" && !el.mobileMore.hidden) {
    trapFocus(el.mobileMore, event);
  }
});
```

Implement `trapFocus(container, event)` by collecting
`button:not([disabled]), [href], input:not([disabled]), select:not([disabled])`,
moving from the last item to the first on Tab, and from the first to the last
on Shift+Tab.

- [ ] **Step 5: Run focused tests and build preview**

Run:

```powershell
python -m unittest tests.test_ui_contract.UiJavascriptContractTests -v
python -m scripts.build_site
```

Expected: PASS and a successful site build.

- [ ] **Step 6: Commit navigation behavior**

```powershell
git add tests/test_ui_contract.py web/app.js
git commit -m "feat: PC와 모바일 탐색 상태 동기화"
```

---

### Task 4: Redesign Login, Claim, Pending, Loading, and Error States

**Files:**
- Modify: `tests/test_ui_contract.py`
- Modify: `web/index.hosting.html:10-20`
- Modify: `web/boot.js:20-141`
- Modify: `web/styles.css:289-309`
- Test: `tests/test_ui_contract.py`

**Interfaces:**
- Consumes: existing `show(html)`, `gateSignIn`, `gateError`, `gateLoading`, `gateClaim`, `gatePending`.
- Produces: shared `.gate-state`, `.gate-copy`, `.gate-actions`, `.gate-progress` state markup.

- [ ] **Step 1: Add failing gate-state tests**

```python
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
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
python -m unittest tests.test_ui_contract.UiGateContractTests -v
```

Expected: FAIL on the new shared classes and copy.

- [ ] **Step 3: Introduce one gate-state wrapper**

Keep the existing Firebase behavior and event bindings. Each function passes state-specific inner HTML to this structure:

```html
<section class="gate-state gate-state--signin">
  <div class="gate-visual" aria-hidden="true"></div>
  <div class="gate-copy">
    <p class="eyebrow">WELCOME BACK</p>
    <h1>반가워요</h1>
    <p>Google 계정으로 로그인하면 승인된 멤버만 기록을 열람할 수 있어요.</p>
    <div class="gate-actions">…existing buttons…</div>
    <p class="privacy-note">대화와 사진은 회원 전용으로 보호됩니다.</p>
  </div>
</section>
```

Use the same wrapper for loading and error states. Keep detailed Firebase errors escaped and place them in a collapsible `<details class="error-detail">`.

- [ ] **Step 4: Add the three-step pending indicator**

`gatePending` renders:

1. 신청 완료 — current complete
2. 관리자 확인 — current waiting
3. 기록 열람 — future

Keep the current “다시 확인”, “이름 수정”, and “다른 계정으로 로그인” actions and bindings.

- [ ] **Step 5: Style gate states**

Desktop uses a two-column card with art and copy. Mobile stacks art above copy. The loading state preserves the existing spinner. The error state uses `--danger` only for the status icon and recovery action, not the whole page.

```css
.gate {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 32px;
  background: var(--bg);
}
.gate-card {
  width: min(920px, 100%);
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 24px;
  background: var(--surface);
  box-shadow: var(--shadow);
}
.gate-state {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(320px, .85fr);
  min-height: 520px;
}
.gate-visual { background: var(--sage); }
.gate-copy {
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 48px;
}
.gate-actions { display: flex; flex-wrap: wrap; gap: 10px; }
.gate-progress { display: flex; align-items: center; gap: 8px; }
@media (max-width: 760px) {
  .gate { padding: 16px; }
  .gate-state { grid-template-columns: 1fr; }
  .gate-visual { min-height: 180px; }
  .gate-copy { padding: 28px 22px; }
}
```

- [ ] **Step 6: Run gate tests**

Run:

```powershell
python -m unittest tests.test_ui_contract.UiGateContractTests -v
```

Expected: PASS.

- [ ] **Step 7: Commit gate redesign**

```powershell
git add tests/test_ui_contract.py web/index.hosting.html web/boot.js web/styles.css
git commit -m "feat: 로그인과 승인 상태를 따뜻한 화면으로 개편"
```

---

### Task 5: Add the Archive Welcome and Consistent Empty States

**Files:**
- Modify: `tests/test_ui_contract.py`
- Modify: `web/app.js:78-331`
- Modify: `web/app.js:723-855`
- Modify: `web/styles.css:91-280`
- Modify: `web/styles.css:310-419`
- Test: `tests/test_ui_contract.py`

**Interfaces:**
- Consumes: existing `STATS`, `THREADS`, `MEDIA`, `CATS`, `renderSummary`, `renderTimeline`, `renderGallery`, `renderFiles`, `renderStats`.
- Produces: `emptyState(kind, title, body, actionHtml)` and `.archive-welcome`.

- [ ] **Step 1: Add failing renderer-contract tests**

```python
class UiViewContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

    def test_summary_has_archive_welcome(self):
        self.assertIn("archive-welcome", self.app)
        self.assertIn("함께 나눈 이야기를", self.app)

    def test_empty_state_helper_is_used(self):
        self.assertIn("function emptyState(", self.app)
        self.assertGreaterEqual(self.app.count("emptyState("), 4)
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
python -m unittest tests.test_ui_contract.UiViewContractTests -v
```

Expected: FAIL because the welcome and shared empty-state helper do not exist.

- [ ] **Step 3: Add the deterministic welcome block**

At the start of `renderSummary`, use only existing `STATS.totals` values:

```javascript
var totals = STATS.totals || {};
var welcome =
  '<section class="archive-welcome">' +
    '<div class="archive-welcome__copy">' +
      '<p class="eyebrow">우리의 공동 기록</p>' +
      '<h2>함께 나눈 이야기를<br>천천히 다시 만나요</h2>' +
      '<p>' + esc(totals.messages || 0) + "개의 기록과 " +
      esc(totals.participants || 0) + "명의 이야기가 이어지고 있어요.</p>" +
    '</div>' +
    '<div class="archive-welcome__art" aria-hidden="true"></div>' +
  '</section>';
```

Do not claim “new today” or “new this month” because the current payload does not contain a trustworthy delta.
At this task, `.archive-welcome__art` uses CSS paper, speech-bubble, and leaf
shapes so the task has no missing asset. Task 7 replaces this temporary art
with the generated WebP.

- [ ] **Step 4: Add a shared empty-state helper**

```javascript
function emptyState(kind, title, body, actionHtml) {
  return '<section class="empty-state">' +
    '<div class="empty-state__art" data-kind="' + esc(kind) + '" aria-hidden="true"></div>' +
    '<h2>' + esc(title) + '</h2>' +
    '<p>' + esc(body) + '</p>' +
    (actionHtml || "") +
  '</section>';
}
```

Use it for zero-result timeline search, empty gallery, empty file list, and missing summary content. Keep diagnostics in text; images never replace the explanation.
Use small CSS collage shapes until Task 7 replaces the art containers with
optimized images.

- [ ] **Step 5: Restyle core views**

Apply the approved spacing and reading widths:

- Summary: welcome followed by 2–3 column topic cards.
- Timeline: 72ch message reading width, quiet date separators, visible filter chips.
- Gallery: larger image gutters with no decorative background art.
- Files: filename, type, size, date, and related topic hierarchy.
- Stats: fewer boxed metrics; narrative labels adjacent to numbers.
- Graph: preserve the maximum graph viewport and only restyle controls, legend, and detail panel.

Do not change graph rendering, message filtering, Markdown parsing, downloads, or lightbox behavior.

Use these layout boundaries:

```css
.archive-welcome {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(260px, .85fr);
  gap: 28px;
  align-items: center;
  margin-bottom: 36px;
  padding: clamp(28px, 4vw, 48px);
  border-radius: 24px;
  background: var(--accent-soft);
}
.archive-welcome h2 {
  max-width: 14ch;
  margin: 10px 0 14px;
  font-size: clamp(2rem, 4vw, 3.6rem);
  line-height: 1.15;
  letter-spacing: -.065em;
}
.archive-welcome__art { min-height: 240px; border-radius: 45% 55% 48% 52%; }
.message-body, .md-body { max-width: var(--reading-width); }
.timeline { display: grid; gap: 20px; }
.gallery { gap: clamp(14px, 2vw, 24px); }
.empty-state {
  max-width: 520px;
  margin: 60px auto;
  text-align: center;
}
@media (max-width: 760px) {
  .archive-welcome { grid-template-columns: 1fr; }
  .archive-welcome__art { min-height: 160px; }
}
```

- [ ] **Step 6: Run renderer tests and existing build tests**

Run:

```powershell
python -m unittest tests.test_ui_contract.UiViewContractTests -v
python -m unittest tests.test_build_site -v
```

Expected: PASS.

- [ ] **Step 7: Commit archive view polish**

```powershell
git add tests/test_ui_contract.py web/app.js web/styles.css
git commit -m "feat: 아카이브 홈과 콘텐츠 화면에 여백과 빈 상태 적용"
```

---

### Task 6: Clarify Personal Controls and Replace Native Confirmations

**Files:**
- Modify: `tests/test_ui_contract.py`
- Modify: `web/index.html`
- Modify: `web/index.hosting.html`
- Modify: `web/app.js:1385-1951`
- Modify: `web/styles.css:420-514`
- Test: `tests/test_ui_contract.py`

**Interfaces:**
- Consumes: existing preference values `public`, `unpublished`, `none` and existing mutation callbacks.
- Produces: `confirmAction(options, onConfirm)` with `{title, description, confirmLabel, tone}`.

- [ ] **Step 1: Add failing safety-contract tests**

```python
class UiSafetyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

    def test_native_confirm_is_replaced(self):
        self.assertNotIn("window.confirm", self.app)
        self.assertIn("function confirmAction(", self.app)

    def test_consent_labels_are_honest(self):
        for label in ("함께 공개", "발행하지 않기", "수집 중단"):
            self.assertIn(label, self.app)
        self.assertIn("관리자에게는 운영 원본이 남습니다", self.app)
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
python -m unittest tests.test_ui_contract.UiSafetyContractTests -v
```

Expected: FAIL because `window.confirm` is still used and the new labels are absent.

- [ ] **Step 3: Add the confirmation dialog markup**

Add identical dialog markup to both HTML files:

```html
<dialog class="confirm-dialog" id="confirmDialog" aria-labelledby="confirmTitle">
  <form method="dialog">
    <p class="eyebrow" id="confirmEyebrow">확인이 필요해요</p>
    <h2 id="confirmTitle"></h2>
    <p id="confirmDescription"></p>
    <div class="dialog-actions">
      <button value="cancel" class="btn ghost">취소</button>
      <button value="confirm" class="btn danger" id="confirmSubmit">계속하기</button>
    </div>
  </form>
</dialog>
```

- [ ] **Step 4: Implement `confirmAction`**

```javascript
function confirmAction(options, onConfirm) {
  el.confirmTitle.textContent = options.title;
  el.confirmDescription.textContent = options.description;
  el.confirmSubmit.textContent = options.confirmLabel || "계속하기";
  el.confirmDialog.dataset.tone = options.tone || "danger";
  el.confirmDialog.returnValue = "";
  el.confirmDialog.onclose = function () {
    if (el.confirmDialog.returnValue === "confirm") onConfirm();
  };
  el.confirmDialog.showModal();
}
```

Refactor all seven `window.confirm` call sites to callback form. Preserve the existing mutation calls, loading messages, and error handlers exactly.

- [ ] **Step 5: Replace internal consent wording**

Keep submitted values unchanged:

| Stored value | Visible label | Required explanation |
|---|---|---|
| `public` | 함께 공개 | 수집하고 승인된 멤버 화면에 보여요 |
| `unpublished` | 발행하지 않기 | 수집은 계속되지만 멤버 화면에서는 제외돼요. 관리자에게는 운영 원본이 남습니다 |
| `none` | 수집 중단 | 앞으로의 글을 저장하지 않으며 그 기간은 복구할 수 없어요 |

- [ ] **Step 6: Restyle personal and admin workspaces**

- Use section headings and explanatory copy before controls.
- Keep deletion requests grouped by text, image, and file.
- Give pending mutations a sage status chip.
- Separate approval/rejection from role changes and removal.
- Use `--danger` only for irreversible actions.
- Add `::backdrop` styling and restore focus after dialog close.

```css
.mine, .admin { max-width: 920px; margin: 0 auto; }
.mine-card, .admin-section {
  margin-bottom: 20px;
  padding: clamp(20px, 3vw, 30px);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface);
}
.mine-mode {
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 14px;
}
.mine-mode.on {
  border-color: var(--sage);
  background: color-mix(in srgb, var(--sage) 14%, var(--surface));
}
.btn.danger { color: white; background: var(--danger); }
.confirm-dialog {
  width: min(480px, calc(100% - 32px));
  padding: 0;
  border: 1px solid var(--line);
  border-radius: 20px;
  color: var(--ink);
  background: var(--surface);
  box-shadow: var(--shadow);
}
.confirm-dialog form { padding: 28px; }
.confirm-dialog::backdrop { background: rgba(41, 37, 33, .52); backdrop-filter: blur(3px); }
```

Capture `document.activeElement` before `showModal()` and focus it after
`onclose`; if it is no longer connected, focus the current view heading.

- [ ] **Step 7: Run safety and data-ownership tests**

Run:

```powershell
python -m unittest tests.test_ui_contract.UiSafetyContractTests -v
python -m unittest tests.test_member_requests -v
python -m unittest tests.test_firestore_payload -v
```

Expected: PASS.

- [ ] **Step 8: Commit personal/admin redesign**

```powershell
git add tests/test_ui_contract.py web/index.html web/index.hosting.html web/app.js web/styles.css
git commit -m "feat: 내 기록과 관리자 작업의 설명과 확인 절차 개선"
```

---

### Task 7: Generate, Optimize, and Publish the Illustration Set

**Files:**
- Create: `scripts/optimize_ui_art.py`
- Create: `tests/test_optimize_ui_art.py`
- Create: `web/art/archive-hero.webp`
- Create: `web/art/state-pending.webp`
- Create: `web/art/state-empty.webp`
- Create: `web/art/state-search.webp`
- Modify: `tests/test_ui_contract.py`
- Modify: `scripts/build_site.py:23-27, 450-468`
- Modify: `scripts/build_hosting.py:18-46`
- Modify: `web/app.js`
- Modify: `web/boot.js`
- Modify: `web/styles.css`
- Modify: `.gitignore`
- Test: `tests/test_optimize_ui_art.py`
- Test: `tests/test_ui_contract.py`

**Interfaces:**
- Consumes: ImageGen PNG sources under ignored `assets/design-source/`.
- Produces: `optimize_image(src: Path, dest: Path, max_width: int, quality: int) -> None` and four bounded production WebPs.

- [ ] **Step 1: Write the failing optimizer test**

```python
# tests/test_optimize_ui_art.py
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from PIL import Image

from scripts.optimize_ui_art import optimize_image


class OptimizeUiArtTests(unittest.TestCase):
    def test_resizes_and_writes_webp(self):
        with TemporaryDirectory() as td:
            src = Path(td) / "source.png"
            dest = Path(td) / "result.webp"
            Image.new("RGB", (1800, 1000), "#CA7154").save(src)
            optimize_image(src, dest, max_width=800, quality=78)
            with Image.open(dest) as image:
                self.assertEqual("WEBP", image.format)
                self.assertLessEqual(image.width, 800)
                self.assertEqual("RGB", image.mode)
```

- [ ] **Step 2: Run the optimizer test and verify failure**

Run:

```powershell
python -m unittest tests.test_optimize_ui_art -v
```

Expected: FAIL because `scripts.optimize_ui_art` does not exist.

- [ ] **Step 3: Implement the optimizer**

```python
# scripts/optimize_ui_art.py
from pathlib import Path
from PIL import Image


def optimize_image(src: Path, dest: Path, max_width: int, quality: int) -> None:
    with Image.open(src) as image:
        image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
        if image.width > max_width:
            height = round(image.height * max_width / image.width)
            image = image.resize((max_width, height), Image.Resampling.LANCZOS)
        dest.parent.mkdir(parents=True, exist_ok=True)
        image.save(dest, "WEBP", quality=quality, method=6)
```

Add an argparse CLI accepting `src`, `dest`, `--max-width`, and `--quality`.

- [ ] **Step 4: Run the optimizer test**

Run:

```powershell
python -m unittest tests.test_optimize_ui_art -v
```

Expected: PASS.

- [ ] **Step 5: Generate four source images with ImageGen**

Use the `imagegen` skill and save full-resolution outputs under `assets/design-source/`.

Hero prompt:

```text
Warm editorial paper-collage illustration for a private Korean community archive website.
Layered handwritten-note shapes without readable writing, overlapping conversation bubbles,
soft morning sunlight, small leaves, and threads connecting records. Ivory paper, muted coral,
sage green, and pale ochre palette. Calm, humane, spacious, tactile cut-paper texture.
No identifiable people, no faces, no KakaoTalk interface, no logos, no letters, no watermark.
Wide 8:5 composition, key objects inside the central 70%, clean background, web hero artwork.
```

Pending-state prompt:

```text
Small warm paper-collage illustration of a sealed envelope beside neatly stacked archive cards,
suggesting a request safely received and waiting for review. Ivory, muted coral, sage green.
Calm and reassuring, centered object, transparent-looking plain background, no text, no logos,
no faces, no watermark.
```

Empty-state prompt:

```text
Small warm paper-collage illustration of an open archive box with one tiny green sprout,
suggesting a quiet space ready for future memories. Ivory, muted coral, sage green.
Centered object, generous empty space, no text, no logos, no faces, no watermark.
```

Search-state prompt:

```text
Small warm paper-collage illustration of a magnifying glass beside a few softly scattered
conversation-bubble shapes, suggesting no matching record yet. Ivory, muted coral, sage green.
Centered object, generous empty space, no text, no logos, no faces, no watermark.
```

- [ ] **Step 6: Optimize images and enforce size budgets**

Run:

```powershell
python -m scripts.optimize_ui_art assets/design-source/archive-hero.png web/art/archive-hero.webp --max-width 1280 --quality 78
python -m scripts.optimize_ui_art assets/design-source/state-pending.png web/art/state-pending.webp --max-width 480 --quality 76
python -m scripts.optimize_ui_art assets/design-source/state-empty.png web/art/state-empty.webp --max-width 480 --quality 76
python -m scripts.optimize_ui_art assets/design-source/state-search.png web/art/state-search.webp --max-width 480 --quality 76
```

If a file exceeds its budget, lower quality by 4 and rerun until hero ≤250KB and each state image ≤80KB. Do not reduce state images below 320px wide.

- [ ] **Step 7: Add failing production-art tests**

Add to `tests/test_ui_contract.py`:

```python
class UiArtContractTests(unittest.TestCase):
    def test_art_exists_and_fits_budget(self):
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
```

Before updating build scripts, also assert `art/archive-hero.webp` appears in both local and Hosting build results; this must fail.

- [ ] **Step 8: Replace temporary CSS art with generated images**

In `renderSummary`, replace `.archive-welcome__art` with:

```javascript
'<img class="archive-welcome__art" src="art/archive-hero.webp" alt="" width="1280" height="800" />'
```

Update `emptyState()` to select `state-search.webp` for search results and
`state-empty.webp` for other empty collections. Update `gatePending` to use
`state-pending.webp`, and the login gate to use `archive-hero.webp`.

Every art image is decorative because adjacent headings explain the state, so
use `alt=""`; state images use `loading="lazy"`.

- [ ] **Step 9: Copy only safe art into both builds**

In both build scripts, define `STATIC_DIRS = ("art",)` and copy `web/art` recursively. Keep `assets` in `scripts/build_hosting.py::FORBIDDEN`; do not weaken the privacy guard.

Update build statistics to count actual files after directory copying.

Add `/assets/design-source/` to `.gitignore`.

- [ ] **Step 10: Build and run art tests**

Run:

```powershell
python -m scripts.build_site
python -m scripts.build_hosting
python -m unittest tests.test_optimize_ui_art tests.test_ui_contract.UiArtContractTests -v
```

Expected:

- Both builds contain `art/*.webp`.
- Hosting still contains no `data.js` or conversation `assets/`.
- All size tests pass.

- [ ] **Step 11: Commit the illustration pipeline and production art**

```powershell
git add .gitignore scripts/optimize_ui_art.py scripts/build_site.py scripts/build_hosting.py tests/test_optimize_ui_art.py tests/test_ui_contract.py web/app.js web/boot.js web/styles.css web/art
git commit -m "feat: 따뜻한 아카이브 생성 이미지와 최적화 파이프라인"
```

---

### Task 8: Accessibility, Responsive Visual QA, and Full Regression

**Files:**
- Modify: `tests/test_ui_contract.py`
- Modify: `web/index.html`
- Modify: `web/index.hosting.html`
- Modify: `web/styles.css`
- Modify: `web/app.js`
- Modify: `web/boot.js`
- Modify: `docs/DEPLOY.md`
- Test: all `tests/test_*.py`
- Test: all `tests/*.test.js`

**Interfaces:**
- Consumes: every prior task's final UI.
- Produces: verified keyboard, responsive, light/dark, local-preview, and Hosting behavior.

- [ ] **Step 1: Add final accessibility-contract tests**

Extend the parser in `tests/test_ui_contract.py` to record duplicate IDs, buttons without text/`aria-label`, images without `alt`, and active navigation without `aria-current`.

```python
def test_no_duplicate_ids(self):
    for name in ("index.html", "index.hosting.html"):
        page = self.parse(name)
        self.assertEqual([], page.duplicate_ids)

def test_all_images_have_alt(self):
    for name in ("index.html", "index.hosting.html"):
        page = self.parse(name)
        self.assertEqual([], page.images_without_alt)
```

- [ ] **Step 2: Run the accessibility tests**

Run:

```powershell
python -m unittest tests.test_ui_contract -v
```

Expected: FAIL on any missing names, duplicate IDs, or missing alt attributes.

- [ ] **Step 3: Apply the exact accessibility attributes**

Make these source changes instead of weakening the tests:

```html
<button type="button" data-view="summary" aria-current="page">주제별 지식</button>
<button type="button" id="mobileMoreButton"
  aria-label="더 많은 화면 열기" aria-controls="mobileMore" aria-expanded="false">더보기</button>
<img src="art/archive-hero.webp" alt="" width="1280" height="800" />
<dialog id="confirmDialog" aria-labelledby="confirmTitle"
  aria-describedby="confirmDescription">…</dialog>
```

Ensure every repeated navigation button has `type="button"`, every icon-only
button has `aria-label`, every decorative image has `alt=""`, and no ID appears
twice in either HTML file. Do not suppress the tests.

- [ ] **Step 4: Run the complete automated suite**

Run:

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
npm.cmd test
```

Expected: all existing 127 tests plus the new UI/art tests pass.

- [ ] **Step 5: Build both delivery targets**

Run:

```powershell
python -m scripts.build_site
python -m scripts.build_hosting
```

Expected:

- Local preview includes `data.js`, local archive images, and UI art.
- Hosting includes UI art but no `data.js`, `assets/`, conversation image, member config, or service-account key.

- [ ] **Step 6: Inspect with the in-app browser**

Serve the local preview and inspect at:

- 1440×1000
- 1280×800
- 1024×768
- 768×1024
- 390×844

For each width, record screenshots of summary, timeline, gallery, mine, and admin when available. Verify:

- no horizontal page scroll,
- no content hidden behind mobile navigation,
- 68–72 character reading width,
- long names and filenames wrap,
- current navigation is visible,
- mobile “더보기” opens, traps keyboard focus, closes on Escape, and returns focus,
- confirmation dialog distinguishes safe and destructive actions,
- light and dark themes both remain readable,
- reduced-motion mode does not animate decorative transitions.

- [ ] **Step 7: Update deployment documentation**

Add a short “UI artwork” note to `docs/DEPLOY.md`:

```markdown
### UI 일러스트

`web/art/`은 대화에서 수집한 사진이 아니라 공개 가능한 UI 장식 자산이다.
`build_hosting.py`가 이 폴더만 Hosting에 복사하며, 개인정보가 있는 `assets/`는
계속 차단한다. 원본 생성 이미지는 `assets/design-source/`에 두고 Git에는 넣지 않는다.
```

- [ ] **Step 8: Re-run final verification**

Run:

```powershell
git diff --check
python -m unittest discover -s tests -p "test_*.py"
npm.cmd test
python -m scripts.build_hosting
git status --short
```

Expected: no whitespace errors, all tests pass, Hosting build succeeds, and only intended source files are modified.

- [ ] **Step 9: Commit verified UI**

```powershell
git add web tests scripts docs/DEPLOY.md .gitignore
git commit -m "test: 따뜻한 아카이브 반응형 UI 검증"
```

---

## Implementation Completion Checklist

- [ ] All eight views remain reachable with the same `data-view` values.
- [ ] Desktop sidebar, mobile bottom navigation, and mobile more sheet stay synchronized.
- [ ] Login, claim, pending, loading, and error states use the warm archive visual language.
- [ ] Consent labels truthfully describe publishing and administrator access.
- [ ] All seven native confirmations use the accessible confirmation dialog.
- [ ] Hero and three state images meet their file-size budgets.
- [ ] Hosting contains public UI art but no conversation data or assets.
- [ ] Keyboard navigation, focus restoration, dark theme, and reduced motion work.
- [ ] Existing 127 tests and all new UI/art tests pass.
- [ ] Visual checks pass at all five target widths.
