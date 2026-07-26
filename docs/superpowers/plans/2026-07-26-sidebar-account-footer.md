# Sidebar Account Footer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the staggered sidebar account controls with one balanced two-row footer whose logout and theme controls share a 40px height.

**Architecture:** Add a stable account-footer shell to both HTML entry points. Keep session identity and logout rendering in the existing authentication flow, while CSS assigns identity and actions to separate rows and preserves the current mobile menu.

**Tech Stack:** Semantic HTML, vanilla JavaScript, CSS, Python `unittest`

## Global Constraints

- Use Noto Sans KR through existing inheritance; add no serif or icon font.
- Keep existing authentication, logout confirmation, and theme persistence behavior.
- Use the existing inline sun/moon SVG.
- Make logout and theme controls exactly 40px high.
- Preserve mobile navigation and mobile theme behavior.

---

### Task 1: Stable Sidebar Footer Shell

**Files:**
- Modify: `web/index.html`
- Modify: `web/index.hosting.html`
- Modify: `web/app.js`
- Modify: `tests/test_ui_contract.py`

**Interfaces:**
- Consumes: existing `renderSession()`, `signOutTop`, `themeBtn`, and `updateThemeControls()`
- Produces: `.sidebar-footer`, `.sidebar-session`, `.sidebar-actions`, and stable logout/theme controls

- [ ] **Step 1: Write failing semantic UI tests**

Parse both HTML shells and assert one `.sidebar-footer` contains `sessionBox`, `signOutTop`, and `themeBtn` in that order. Add a rendering test that proves the session identity contains separate name and role elements and that the stable logout button receives the existing confirmation handler.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
python -m unittest tests.test_ui_contract.UiShellContractTests tests.test_ui_contract.UiJavascriptContractTests -v
```

Expected: FAIL because the footer shell and stable logout control do not exist.

- [ ] **Step 3: Implement the stable shell**

Wrap the account area in:

```html
<div class="sidebar-footer">
  <div class="sidebar-session" id="sessionBox"></div>
  <div class="sidebar-actions">
    <button class="sidebar-signout" id="signOutTop" type="button" hidden>로그아웃</button>
    <button class="theme-toggle" id="themeBtn" type="button"
      aria-label="다크 모드로 전환"></button>
  </div>
</div>
```

Change `renderSession()` to populate only the identity name and role, reveal and bind the stable logout button for authenticated sessions, and hide it when no session is available.

- [ ] **Step 4: Run semantic UI tests**

Run:

```powershell
python -m unittest tests.test_ui_contract.UiShellContractTests tests.test_ui_contract.UiJavascriptContractTests -v
```

Expected: all focused tests pass.

- [ ] **Step 5: Commit the semantic shell**

```powershell
git add -- web/index.html web/index.hosting.html web/app.js tests/test_ui_contract.py
git commit -m "refactor: group sidebar account controls"
```

---

### Task 2: Balanced Account Footer Styling

**Files:**
- Modify: `web/styles.css`
- Modify: `tests/test_ui_contract.py`

**Interfaces:**
- Consumes: Task 1 footer classes
- Produces: two-row account footer with 40px equal-height actions and truncation-safe identity

- [ ] **Step 1: Write failing layout tests**

Assert that computed stylesheet contracts include a two-row `.sidebar-footer`, `.sidebar-actions` grid, `height: 40px` for both `.sidebar-signout` and `.theme-toggle`, and overflow handling for `.sidebar-name`.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
python -m unittest tests.test_ui_contract.UiStyleContractTests -v
```

Expected: FAIL because the footer layout and 40px action sizing do not exist.

- [ ] **Step 3: Implement the warm account footer**

Style the footer with a top divider and 16–18px separation from navigation. Render identity as a compact surface card with avatar, name, and subordinate role. Use a two-column action row where logout fills available width and theme is 40×40px; both share border, radius, hover, and focus treatment. Remove the old theme button's standalone top margin.

- [ ] **Step 4: Run full verification**

Run:

```powershell
python -m unittest tests.test_ui_contract -v
python -m unittest discover -s tests
npm.cmd test
python -m scripts.build_hosting
git diff --check
```

Expected: all tests pass, hosting build succeeds, and no whitespace errors remain.

- [ ] **Step 5: Commit the footer styling**

```powershell
git add -- web/styles.css tests/test_ui_contract.py
git commit -m "style: balance sidebar account footer"
```

