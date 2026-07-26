# Contextual Report Assets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Place confidently matched links and media directly after their related report block across all existing and future reports without publishing source-message text.

**Architecture:** Add a pure Python report-context matcher that compares source messages with markdown blocks and emits build-only `![[link:msg-id]]` and existing media markers. Enrich thread link metadata with message IDs, then let the browser fill link and media anchors while retaining unmatched resources in the footer.

**Tech Stack:** Python 3 standard library, vanilla JavaScript, CSS, Python `unittest`

## Global Constraints

- Preserve all authored report prose and frontmatter.
- Never add source-message text to the public thread or media payload.
- Manual `![[msg-id]]` media markers override automatic placement.
- Only high-confidence matches render inline; ambiguous resources stay in the report footer.
- Do not fetch remote preview metadata or thumbnails.
- Deduplicate every URL and media message between inline and footer rendering.

---

### Task 1: Pure Report Context Matcher

**Files:**
- Modify: `scripts/topic_reports.py`
- Create: `tests/test_topic_reports.py`

**Interfaces:**
- Consumes: `report: str` and ordered `messages: list[dict]`
- Produces: `place_context_anchors(report: str, messages: list[dict]) -> str`

- [ ] **Step 1: Write failing behavior tests**

Add literal fixtures that prove:

```python
def test_link_from_same_message_is_placed_after_matching_quote(self):
    report = "## AI 윤리로\n\n> 일반적으로 AI가 공리주의적 사고에 기반한 응답을 합니다."
    messages = [{
        "id": "msg-001480",
        "nickname": "가온",
        "text": "일반적으로 AI가 공리주의적 사고에 기반한 응답을 합니다.\nhttps://youtu.be/demo",
        "urls": ["https://youtu.be/demo"],
        "kind": "text",
    }]
    self.assertEqual(
        place_context_anchors(report, messages),
        report + "\n\n![[link:msg-001480]]",
    )
```

Also cover manual media marker preservation, nearby same-author image placement, ambiguous image fallback, duplicate-marker prevention, and a short generic message that must not match.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
python -m unittest tests.test_topic_reports -v
```

Expected: import or attribute failure because `place_context_anchors` does not exist.

- [ ] **Step 3: Implement the minimal matcher**

Implement report block parsing and normalized similarity with the Python standard library. Strip URLs and markdown punctuation, require a meaningful normalized source length, prefer containment, and otherwise use `difflib.SequenceMatcher` above an explicit conservative threshold. Insert link markers after the matched block. For media-only messages, examine at most two neighboring text messages, prefer same-author immediate neighbors, and insert an existing media marker only for a single high-confidence winner.

- [ ] **Step 4: Run focused tests and refactor**

Run:

```powershell
python -m unittest tests.test_topic_reports -v
```

Expected: all matcher tests pass. Refactor only duplicated normalization or insertion logic, then rerun the same command.

- [ ] **Step 5: Commit the matcher**

```powershell
git add -- scripts/topic_reports.py tests/test_topic_reports.py
git commit -m "feat: match report resources to context"
```

---

### Task 2: Publish Context Metadata Without Source Text

**Files:**
- Modify: `scripts/build_site.py`
- Modify: `tests/test_build_site.py`
- Modify: `tests/test_firestore_payload.py`

**Interfaces:**
- Consumes: `place_context_anchors(report, messages)` from Task 1
- Produces: enriched thread dictionaries whose `report` contains build-only anchors and whose links include `id`, `nickname`, `date`, and `time`

- [ ] **Step 1: Write failing payload tests**

Build a controlled thread with one report, one URL message, and one media message. Assert that `enrich_threads()`:

```python
self.assertIn("![[link:msg-link]]", enriched[0]["report"])
self.assertEqual(enriched[0]["links"][0]["id"], "msg-link")
self.assertNotIn("text", enriched[0]["links"][0])
```

Add an integration assertion using the local `t-162` data: its enriched report contains `![[link:msg-001480]]`, and no published link dictionary contains a `text` field.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
python -m unittest tests.test_build_site.BuildDataTest.test_contextual_resources_are_published_without_source_text tests.test_firestore_payload -v
```

Expected: FAIL because link metadata has no message ID and reports are not contextualized during enrichment.

- [ ] **Step 3: Enrich threads at build time**

Update `enrich_threads()` to preserve message ID and time on link records, call `place_context_anchors()` with the thread's ordered source messages, and keep the public metadata free of source text. Preserve first-seen URL deduplication and media counts.

- [ ] **Step 4: Run payload tests**

Run:

```powershell
python -m unittest tests.test_build_site tests.test_firestore_payload -v
```

Expected: all build and Firestore payload tests pass.

- [ ] **Step 5: Commit the pipeline**

```powershell
git add -- scripts/build_site.py tests/test_build_site.py tests/test_firestore_payload.py
git commit -m "feat: publish contextual report anchors"
```

---

### Task 3: Inline Link Cards and Shared Resource Footer

**Files:**
- Modify: `web/app.js`
- Modify: `web/styles.css`
- Modify: `tests/test_ui_contract.py`

**Interfaces:**
- Consumes: `![[link:msg-id]]` anchors and link dictionaries with `id`
- Produces: inline `.md-link-anchor` cards and an unmatched-only `.tc-links`/`.tc-media` footer

- [ ] **Step 1: Write failing browser-contract tests**

Assert observable renderer behavior by executing `web/app.js` through the existing page contract where practical, and add a narrow source contract only for the static CSS shell. The behavior fixture must show that a link matching an anchor appears once inline, while an unmatched link remains once in the footer.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
python -m unittest tests.test_ui_contract -v
```

Expected: FAIL because link anchors and contextual link cards do not exist.

- [ ] **Step 3: Render and fill contextual links**

Teach `renderMarkdown()` to emit an escaped `.md-link-anchor` for `![[link:msg-id]]`. Add a link-card renderer that groups URLs by message ID, includes host, URL, author, and date, and uses safe external-link attributes. Fill anchors when a report opens, exclude filled URLs from the footer, and rename the residual footer heading to `이 주제에서 함께 공유된 자료`.

- [ ] **Step 4: Style contextual cards**

Add compact warm-surface styles for `.md-link-anchor`, `.context-link-card`, host, URL, and metadata. Preserve visible keyboard focus and allow long URLs to wrap.

- [ ] **Step 5: Run UI and full verification**

Run:

```powershell
python -m unittest tests.test_ui_contract -v
python -m unittest discover -s tests
npm.cmd test
python -m scripts.build_hosting
git diff --check
```

Expected: Python and Node suites pass, hosting build succeeds, and diff check is clean.

- [ ] **Step 6: Commit the renderer**

```powershell
git add -- web/app.js web/styles.css tests/test_ui_contract.py
git commit -m "feat: render report resources in context"
```

---

### Task 4: Whole-Archive Context Audit

**Files:**
- Create: `scripts/audit_report_context.py`
- Create: `tests/test_report_context_audit.py`
- Modify: `docs/AUTOMATION.md`

**Interfaces:**
- Consumes: local `output/messages.jsonl`, `output/topics.json`, and `output/reports/*.md`
- Produces: deterministic counts for inline links, inline media, fallback resources, duplicates, and invalid anchors

- [ ] **Step 1: Write failing audit tests**

Use a temporary fixture with one matched link, one unmatched link, one valid media marker, and one invalid marker. Assert literal counts and require a non-zero exit result only for invalid or duplicate anchors.

- [ ] **Step 2: Run audit tests and verify RED**

Run:

```powershell
python -m unittest tests.test_report_context_audit -v
```

Expected: import or file failure because the audit script does not exist.

- [ ] **Step 3: Implement the audit**

Reuse the production matcher and build enrichment path. Print stable summary lines, list report IDs with invalid or duplicate anchors, and avoid printing source-message text.

- [ ] **Step 4: Document and run the archive audit**

Document:

```powershell
python -m scripts.audit_report_context
```

Run it against all 164 local reports. Confirm `t-162` maps `msg-001480` inline, invalid anchors are zero, duplicate rendering candidates are zero, and ambiguous resources are reported as fallback rather than forced inline.

- [ ] **Step 5: Commit the audit**

```powershell
git add -- scripts/audit_report_context.py tests/test_report_context_audit.py docs/AUTOMATION.md
git commit -m "test: audit report resource context"
```

