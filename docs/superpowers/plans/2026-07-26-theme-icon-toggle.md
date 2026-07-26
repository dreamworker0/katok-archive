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
