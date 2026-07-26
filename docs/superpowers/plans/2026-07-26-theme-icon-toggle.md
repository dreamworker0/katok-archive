# Theme Icon Toggle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace visible light/dark theme text with accessible sun and moon SVG icons on desktop and mobile.

**Architecture:** Keep the existing theme detection, persistence, and click flow. Add one small `themeIcon()` renderer in `web/app.js`; `updateThemeControls()` will inject the correct inline SVG and update `aria-label`/`title`. CSS will size the desktop control as a compact square while preserving the mobile menu layout.

**Tech Stack:** Vanilla HTML, CSS, JavaScript, Python `unittest`

## Global Constraints

- Use inline SVG without an external icon library or raster asset.
- Show a moon in light mode because clicking enters dark mode.
- Show a sun in dark mode because clicking enters light mode.
- Keep `aria-label` and `title` synchronized with the destination theme.
- Apply the same icon rule to desktop and mobile controls.

---

### Task 1: Accessible SVG Theme Toggle

**Files:**
- Modify: `tests/test_ui_contract.py`
- Modify: `web/app.js`
- Modify: `web/index.html`
- Modify: `web/index.hosting.html`
- Modify: `web/styles.css`

**Interfaces:**
- Consumes: `currentTheme(): "light" | "dark"` and existing `toggleTheme(): void`
- Produces: `themeIcon(mode: "light" | "dark"): string` and updated `updateThemeControls(): void`

- [ ] **Step 1: Write the failing contract tests**

```python
def test_theme_controls_render_accessible_destination_icons(self):
    self.assertIn("function themeIcon(", self.app)
    self.assertIn('data-theme-icon="moon"', self.app)
    self.assertIn('data-theme-icon="sun"', self.app)
    self.assertIn('setAttribute("title", label)', self.app)
    self.assertIn('innerHTML = themeIcon(', self.app)

def test_theme_button_shell_is_icon_only(self):
    for name in ("index.html", "index.hosting.html"):
        source = (ROOT / "web" / name).read_text(encoding="utf-8")
        self.assertIn('class="theme-toggle"', source)
        self.assertIn('aria-label="다크 모드로 전환"></button>', source)
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
python -m unittest tests.test_ui_contract.UiJavascriptContractTests.test_theme_controls_render_accessible_destination_icons tests.test_ui_contract.FirebaseHostingContractTests.test_theme_button_shell_is_icon_only
```

Expected: FAIL because `themeIcon()`, sun/moon SVG markers, and empty icon-only button shells do not yet exist.

- [ ] **Step 3: Implement the SVG renderer and control updates**

Add a `themeIcon(mode)` function that returns a moon SVG for `dark` and a sun SVG for `light`, each with `aria-hidden="true"` and `data-theme-icon`. In `updateThemeControls()`, calculate the destination mode once, assign `innerHTML`, and synchronize `aria-label` and `title` on desktop and mobile.

Change both HTML shells to:

```html
<button class="theme-toggle" id="themeBtn" type="button"
  aria-label="다크 모드로 전환"></button>
```

Update CSS so `.theme-toggle` is 36×36px, centered, and visually square. Keep `[data-mobile-action="theme"]` sized by the existing mobile menu rules.

- [ ] **Step 4: Run focused and full verification**

Run:

```powershell
python -m unittest tests.test_ui_contract
python -m unittest discover -s tests
npm.cmd test
python -m scripts.build_hosting
git diff --check
```

Expected: all Python and Node tests pass, hosting build succeeds, and diff check returns no errors.

- [ ] **Step 5: Commit, push, and deploy**

```powershell
git add -- docs/superpowers/plans/2026-07-26-theme-icon-toggle.md tests/test_ui_contract.py web/app.js web/index.html web/index.hosting.html web/styles.css
git commit -m "feat: use icons for theme toggle"
git push origin main
.\node_modules\.bin\firebase.cmd deploy --only hosting
```

Verify both Firebase Hosting URLs return the updated icon markers in `app.js`.

---

### Task 2: Prominent Timeline Report Button

**Files:**
- Create: `docs/superpowers/specs/2026-07-26-timeline-report-button-design.md`
- Modify: `tests/test_ui_contract.py`
- Modify: `web/app.js`
- Modify: `web/styles.css`

**Interfaces:**
- Consumes: existing `.tc-toggle` report disclosure button and `.tc-detail.on` state
- Produces: `.tc-toggle-label`, `.tc-toggle-icon`, and synchronized `aria-expanded`

- [ ] **Step 1: Write the failing contract tests**

Assert that the report toggle contains a decorative document SVG, a dedicated label span, `aria-expanded`, `보고서 접기`, and CSS contracts for inline-flex layout, 40px minimum height, and 14px text.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
python -m unittest tests.test_ui_contract.UiJavascriptContractTests.test_timeline_report_toggle_is_a_prominent_accessible_action tests.test_ui_contract.UiStyleContractTests.test_timeline_report_toggle_is_visually_prominent
```

Expected: FAIL because the existing control is a 12.5px text-only button without an expanded-state attribute.

- [ ] **Step 3: Implement the prominent disclosure button**

Render an inline document SVG with `aria-hidden="true"`, wrap the state text in `.tc-toggle-label`, set the initial `aria-expanded`, and update both the label and attribute whenever the report opens or closes. Style `.tc-toggle` as a 40px soft-accent pill button and leave `.tc-dl` secondary.

- [ ] **Step 4: Run focused, full, visual, and build verification**

Run the focused tests, all Python tests, Node tests, hosting build, and `git diff --check`. In a local browser, verify the control size, document icon, `보고서 읽기` → `보고서 접기` behavior, and absence of console errors.
