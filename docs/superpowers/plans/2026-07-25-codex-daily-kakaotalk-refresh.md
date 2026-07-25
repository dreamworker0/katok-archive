# Codex Daily KakaoTalk Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and activate a Codex scheduled job that refreshes the private KakaoTalk archive every day at 04:00 Asia/Seoul, including messages, photos, semantic summaries, the knowledge graph, validation, and Firebase deployment.

**Architecture:** A local Codex cron automation controls the official KakaoTalk Windows UI, exports the full chat, and downloads new photos. Small deterministic Python gates validate that the export only moves forward, identify the new message slice, validate semantic artifacts, and refuse publication unless the full test and Firebase dry-run sequence succeeds. The scheduled Codex task performs the judgment-heavy topic, digest, and graph edits, while scripts own all repeatable safety checks and network publication order.

**Tech Stack:** Python 3.14 standard library, `unittest`, JSON/JSONL, Node.js 22, Firebase Admin SDK, Firebase CLI, Codex local cron automation, Codex Computer Use, Windows 11, PC KakaoTalk.

## Global Constraints

- Run against `D:\apps\카톡데이터크롤링` as the saved local Codex project.
- Schedule the job for 04:00 every day in `Asia/Seoul`.
- Require the PC and Codex app to be running, Windows to be unlocked, and PC KakaoTalk to be logged in.
- Use only the official KakaoTalk UI and export features; never inspect KakaoTalk databases or caches.
- Preserve human messages, timestamps, nicknames, multiline text, URLs, file-share names, downloadable photos, and photo ordering.
- Exclude videos, emoticons, and invite/leave system messages; do not download attachment document binaries.
- Update messages, participants, statistics, topics, threads, digest prose, and knowledge graph in the same successful run.
- Reuse the existing 12 categories unless repeated new content clearly requires a new category.
- Do not rewrite historical semantic assignments unless correcting a clear error.
- Never publish when collection, validation, tests, or the Firebase dry-run fails.
- Never commit or print `serviceAccountKey.json`, member emails, auth tokens, raw KakaoTalk exports, or runtime photo staging files.
- A repeated run over the same export must not duplicate messages, images, or Firestore documents.

---

## File Structure

- Create `scripts/refresh_guard.py`: validate a candidate KakaoTalk TXT against the current structured archive and emit the exact new-message slice.
- Create `tests/test_refresh_guard.py`: cover forward-only, identical, truncated, and rewritten export behavior.
- Create `scripts/validate_archive.py`: validate topic coverage, digest coverage, graph references, image files, hashes, and aggregate counts without writing or using the network.
- Create `tests/test_validate_archive.py`: exercise each validation failure with a minimal temporary archive.
- Create `scripts/publish_archive.py`: run the fixed validation/build/dry-run/upload/deploy sequence and stop at the first failure.
- Create `tests/test_publish_archive.py`: verify command order, dry-run behavior, and fail-closed behavior with a fake runner.
- Create `docs/DAILY_REFRESH.md`: exact UI and command runbook for the scheduled Codex task, including recovery and reporting.
- Create `AGENTS.md`: durable project rules and commands that every scheduled run must follow.
- Modify `.gitignore`: ignore `.refresh/`, daily exported TXT files, and the KakaoTalk download inbox.
- Modify `package.json`: expose `refresh:check`, `refresh:validate`, `refresh:dry`, and `refresh:publish` commands.
- Create Codex automation `카카오톡 아카이브 매일 갱신`: daily local project job at 04:00 Asia/Seoul.

---

### Task 1: Forward-only export guard

**Files:**
- Create: `scripts/refresh_guard.py`
- Create: `tests/test_refresh_guard.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `scripts.kakao_parser.parse_chat(text: str) -> ParseResult`
- Produces: `message_fingerprint(message: Message) -> tuple[str, str, str, str]`
- Produces: `inspect_candidate(candidate_path: Path, current_messages_path: Path) -> dict[str, object]`
- Produces CLI: `python -m scripts.refresh_guard C:\path\KakaoTalk_export.txt --current output/messages.jsonl --report .refresh/candidate-report.json`
- Report keys: `status`, `candidate_path`, `total_messages`, `current_messages`, `new_count`, `new_message_ids`, `first_new_timestamp`, `last_timestamp`

- [ ] **Step 1: Write failing forward-only tests**

```python
# tests/test_refresh_guard.py
import json
from pathlib import Path
import tempfile
import unittest

from scripts.refresh_guard import inspect_candidate


def export(*bodies: str) -> str:
    rows = ["--------------- 2026년 7월 25일 토요일 ---------------"]
    rows.extend(
        f"[사용자] [오전 9:{index:02d}] {body}"
        for index, body in enumerate(bodies, start=1)
    )
    return "\n".join(rows) + "\n"


def current_rows(*bodies: str) -> str:
    return "".join(
        json.dumps(
            {
                "id": f"msg-{index:06d}",
                "timestamp": f"2026-07-25T09:{index:02d}+09:00",
                "nickname": "사용자",
                "text": body,
                "kind": "text",
            },
            ensure_ascii=False,
        ) + "\n"
        for index, body in enumerate(bodies, start=1)
    )


class RefreshGuardTests(unittest.TestCase):
    def inspect(self, candidate_text: str, current_text: str):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            candidate = root / "candidate.txt"
            current = root / "messages.jsonl"
            candidate.write_text(candidate_text, encoding="utf-8")
            current.write_text(current_text, encoding="utf-8")
            return inspect_candidate(candidate, current)

    def test_reports_only_appended_messages(self):
        report = self.inspect(export("기존", "새 메시지"), current_rows("기존"))
        self.assertEqual(report["status"], "advanced")
        self.assertEqual(report["new_count"], 1)
        self.assertEqual(report["new_message_ids"], ["msg-000002"])

    def test_accepts_identical_export_as_no_change(self):
        report = self.inspect(export("기존"), current_rows("기존"))
        self.assertEqual(report["status"], "unchanged")
        self.assertEqual(report["new_count"], 0)

    def test_rejects_truncated_export(self):
        with self.assertRaisesRegex(ValueError, "기존 메시지보다 적습니다"):
            self.inspect(export("기존"), current_rows("기존", "둘째"))

    def test_rejects_rewritten_history(self):
        with self.assertRaisesRegex(ValueError, "기존 대화와 일치하지 않습니다"):
            self.inspect(export("변경됨", "새 메시지"), current_rows("기존"))
```

- [ ] **Step 2: Run the tests and confirm the missing-module failure**

Run:

```powershell
python -m unittest tests.test_refresh_guard -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.refresh_guard'`.

- [ ] **Step 3: Implement the guard**

```python
# scripts/refresh_guard.py
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from scripts.kakao_parser import Message, parse_chat


def message_fingerprint(message: Message) -> tuple[str, str, str, str]:
    return (message.timestamp, message.nickname, message.text, message.kind)


def _read_current(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def inspect_candidate(
    candidate_path: Path,
    current_messages_path: Path,
) -> dict[str, object]:
    parsed = parse_chat(candidate_path.read_text(encoding="utf-8-sig"))
    candidate = parsed.messages
    current = _read_current(current_messages_path)
    if len(candidate) < len(current):
        raise ValueError("후보 내보내기가 기존 메시지보다 적습니다")

    for index, old in enumerate(current):
        fresh = candidate[index]
        old_fingerprint = (
            str(old["timestamp"]),
            str(old["nickname"]),
            str(old["text"]),
            str(old["kind"]),
        )
        if message_fingerprint(fresh) != old_fingerprint:
            raise ValueError(
                f"후보 내보내기가 기존 대화와 일치하지 않습니다: {fresh.id}"
            )

    new_messages = candidate[len(current):]
    return {
        "status": "advanced" if new_messages else "unchanged",
        "candidate_path": str(candidate_path.resolve()),
        "total_messages": len(candidate),
        "current_messages": len(current),
        "new_count": len(new_messages),
        "new_message_ids": [message.id for message in new_messages],
        "first_new_timestamp": new_messages[0].timestamp if new_messages else None,
        "last_timestamp": candidate[-1].timestamp if candidate else None,
        "new_messages": [asdict(message) for message in new_messages],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--current", type=Path, default=Path("output/messages.jsonl"))
    parser.add_argument("--report", type=Path, default=Path(".refresh/candidate-report.json"))
    args = parser.parse_args()
    report = inspect_candidate(args.candidate, args.current)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({k: v for k, v in report.items() if k != "new_messages"},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Ignore runtime collection files**

Append exactly:

```gitignore
# 매일 갱신 런타임 상태와 카카오톡 내보내기
/.refresh/
/inbox/
/KakaoTalk_*_daily.txt
```

- [ ] **Step 5: Run focused and regression tests**

Run:

```powershell
python -m unittest tests.test_refresh_guard tests.test_kakao_parser tests.test_collect_chat -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add scripts/refresh_guard.py tests/test_refresh_guard.py .gitignore
git commit -m "feat: validate daily KakaoTalk exports"
```

---

### Task 2: Archive semantic and media validator

**Files:**
- Create: `scripts/validate_archive.py`
- Create: `tests/test_validate_archive.py`

**Interfaces:**
- Consumes: paths to `messages.jsonl`, `images.jsonl`, `participants.json`, `topics.json`, `topic-digests.json`, `knowledge.json`, and `assets/images`
- Produces: `validate_archive(output_dir: Path, workspace_root: Path) -> dict[str, int]`
- Raises: `ArchiveValidationError` containing all validation failures
- Produces CLI: `python -m scripts.validate_archive`

- [ ] **Step 1: Write failing validator tests**

```python
# tests/test_validate_archive.py
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from scripts.validate_archive import ArchiveValidationError, validate_archive


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def make_valid_archive(with_image: bool = False) -> Path:
    root = Path(tempfile.mkdtemp())
    messages = [
        {
            "id": "msg-000001",
            "timestamp": "2026-07-25T09:01+09:00",
            "date": "2026-07-25",
            "time": "09:01",
            "nickname": "사용자",
            "text": "첫 메시지",
            "kind": "text",
            "image_id": None,
        },
        {
            "id": "msg-000002",
            "timestamp": "2026-07-25T09:02+09:00",
            "date": "2026-07-25",
            "time": "09:02",
            "nickname": "사용자",
            "text": "둘째 메시지",
            "kind": "text",
            "image_id": None,
        },
    ]
    images = []
    if with_image:
        image_path = root / "assets/images/2026-07/msg-000002-01.jpg"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(b"photo")
        messages[1].update({"text": "사진", "kind": "image", "image_id": "img-000001"})
        images.append({
            "image_id": "img-000001",
            "message_id": "msg-000002",
            "status": "downloaded",
            "assets": [{
                "asset_id": "img-000001-01",
                "local_path": "assets/images/2026-07/msg-000002-01.jpg",
                "byte_size": 5,
                "sha256": sha256(b"photo").hexdigest(),
            }],
        })

    write_jsonl(root / "output/messages.jsonl", messages)
    write_jsonl(root / "output/images.jsonl", images)
    write_json(root / "output/participants.json", {
        "participants": [{"nickname": "사용자", "message_count": 2}],
    })
    write_json(root / "output/topics.json", {
        "categories": [{"id": "chat", "label": "일상·잡담"}],
        "threads": [{
            "id": "t-001",
            "title": "테스트 대화",
            "category": "chat",
            "message_ids": ["msg-000001", "msg-000002"],
        }],
    })
    write_json(root / "output/topic-digests.json", {
        "digests": {"chat": {"headline": "테스트", "overview": "테스트 대화 요약"}},
    })
    write_json(root / "output/knowledge.json", {
        "nodes": [
            {"id": "person:사용자", "type": "person", "label": "사용자", "category": "chat"},
            {"id": "topic:chat", "type": "topic", "label": "일상·잡담", "category": "chat"},
        ],
        "edges": [{"source": "person:사용자", "target": "topic:chat", "type": "participates"}],
    })
    return root


class ValidateArchiveTests(unittest.TestCase):
    def test_valid_archive_returns_counts(self):
        root = make_valid_archive()
        result = validate_archive(root / "output", root)
        self.assertEqual(result["messages"], 2)
        self.assertEqual(result["threads"], 1)
        self.assertEqual(result["nodes"], 2)

    def test_rejects_duplicate_or_missing_topic_coverage(self):
        root = make_valid_archive()
        topics = read_json(root / "output/topics.json")
        topics["threads"][0]["message_ids"] = ["msg-000001", "msg-000001"]
        write_json(root / "output/topics.json", topics)
        with self.assertRaisesRegex(ArchiveValidationError, "주제 커버리지"):
            validate_archive(root / "output", root)

    def test_rejects_graph_edge_with_missing_endpoint(self):
        root = make_valid_archive()
        graph = read_json(root / "output/knowledge.json")
        graph["edges"][0]["target"] = "tool:missing"
        write_json(root / "output/knowledge.json", graph)
        with self.assertRaisesRegex(ArchiveValidationError, "그래프 참조"):
            validate_archive(root / "output", root)

    def test_rejects_downloaded_image_with_bad_hash(self):
        root = make_valid_archive(with_image=True)
        image = next((root / "assets/images").rglob("*.jpg"))
        image.write_bytes(b"changed")
        with self.assertRaisesRegex(ArchiveValidationError, "SHA-256"):
            validate_archive(root / "output", root)

    def test_rejects_missing_digest_prose(self):
        root = make_valid_archive()
        write_json(root / "output/topic-digests.json", {"digests": {}})
        with self.assertRaisesRegex(ArchiveValidationError, "요약"):
            validate_archive(root / "output", root)
```

The helper must write valid values for every field the production validator reads; do not use the repository’s real `output/` in these unit tests.

- [ ] **Step 2: Run tests and confirm the missing-module failure**

Run:

```powershell
python -m unittest tests.test_validate_archive -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement complete validation in one focused module**

Implement `validate_archive()` with these checks:

```python
message_ids = [m["id"] for m in messages]
covered = [mid for thread in topics["threads"] for mid in thread["message_ids"]]
require(len(message_ids) == len(set(message_ids)), "메시지 ID 중복")
require(len(covered) == len(set(covered)), "주제 커버리지 중복")
require(set(covered) == set(message_ids), "주제 커버리지 누락/불일치")

category_ids = {category["id"] for category in topics["categories"]}
require(
    all(thread["category"] in category_ids for thread in topics["threads"]),
    "스레드 카테고리 불일치",
)

digest_ids = set(digest_prose.get("digests", {}))
require(digest_ids == category_ids, "주제별 요약 누락/불일치")
for category_id, digest in digest_prose["digests"].items():
    require(bool(str(digest.get("headline", "")).strip()), f"요약 headline 없음: {category_id}")
    require(bool(str(digest.get("overview", "")).strip()), f"요약 overview 없음: {category_id}")

node_ids = {node["id"] for node in knowledge["nodes"]}
for edge in knowledge["edges"]:
    require(
        edge["source"] in node_ids and edge["target"] in node_ids,
        f"그래프 참조 불일치: {edge}",
    )
```

Also validate:

- every graph node category belongs to `category_ids`;
- person-node labels equal the participant nickname set;
- participant message counts sum to the message count;
- every `downloaded`/`partial` image asset exists under the workspace;
- every asset’s `byte_size` and `sha256` match the file;
- every image manifest `message_id` points to an image message;
- no duplicate image, message, or asset IDs;
- the returned count dictionary has `messages`, `participants`, `threads`, `categories`, `nodes`, `edges`, and `image_assets`.

Accumulate all failures in a list and raise one `ArchiveValidationError("\n".join(failures))`.

- [ ] **Step 4: Add the CLI**

```python
def main() -> int:
    root = Path(__file__).resolve().parent.parent
    counts = validate_archive(root / "output", root)
    print(json.dumps(counts, ensure_ascii=False, indent=2))
    return 0
```

- [ ] **Step 5: Run focused and full archive tests**

Run:

```powershell
python -m unittest tests.test_validate_archive tests.test_build_site tests.test_firestore_payload -v
python -m scripts.validate_archive
```

Expected: all tests pass and the CLI prints current archive counts.

- [ ] **Step 6: Commit**

```powershell
git add scripts/validate_archive.py tests/test_validate_archive.py
git commit -m "feat: validate archive publication integrity"
```

---

### Task 3: Fail-closed Firebase publication command

**Files:**
- Create: `scripts/publish_archive.py`
- Create: `tests/test_publish_archive.py`
- Modify: `package.json`

**Interfaces:**
- Consumes: `run(command: list[str], cwd: Path) -> None`, injectable in tests
- Produces: `publish(root: Path, dry_run: bool, runner: Runner = subprocess_runner) -> list[list[str]]`
- Produces CLI: `python -m scripts.publish_archive --dry-run` and `python -m scripts.publish_archive`

- [ ] **Step 1: Write failing command-order tests**

```python
# tests/test_publish_archive.py
class PublishArchiveTests(unittest.TestCase):
    def test_dry_run_stops_before_network_writes(self):
        calls = []
        publish(ROOT, dry_run=True, runner=lambda command, cwd: calls.append(command))
        self.assertEqual(calls, [
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
            [sys.executable, "-m", "scripts.validate_archive"],
            [sys.executable, "-m", "scripts.build_firestore_payload"],
            ["node", "scripts/upload_firestore.js", "--dry-run"],
            [sys.executable, "-m", "scripts.build_hosting"],
        ])

    def test_live_run_uploads_only_after_all_checks(self):
        calls = []
        publish(ROOT, dry_run=False, runner=lambda command, cwd: calls.append(command))
        self.assertEqual(calls[-2:], [
            ["node", "scripts/upload_firestore.js"],
            ["firebase", "deploy"],
        ])

    def test_failure_prevents_later_commands(self):
        calls = []
        def fail_on_validate(command, cwd):
            calls.append(command)
            if command[-1] == "scripts.validate_archive":
                raise subprocess.CalledProcessError(1, command)
        with self.assertRaises(subprocess.CalledProcessError):
            publish(ROOT, dry_run=False, runner=fail_on_validate)
        self.assertFalse(any(command[0] == "node" for command in calls))
        self.assertFalse(any(command[0] == "firebase" for command in calls))
```

- [ ] **Step 2: Run tests and confirm the missing-module failure**

Run:

```powershell
python -m unittest tests.test_publish_archive -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the fixed command pipeline**

```python
# scripts/publish_archive.py
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
from typing import Callable

Runner = Callable[[list[str], Path], None]


def subprocess_runner(command: list[str], cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def publish(root: Path, dry_run: bool, runner: Runner = subprocess_runner) -> list[list[str]]:
    commands = [
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        [sys.executable, "-m", "scripts.validate_archive"],
        [sys.executable, "-m", "scripts.build_firestore_payload"],
        ["node", "scripts/upload_firestore.js", "--dry-run"],
        [sys.executable, "-m", "scripts.build_hosting"],
    ]
    if not dry_run:
        commands.extend([
            ["node", "scripts/upload_firestore.js"],
            ["firebase", "deploy"],
        ])
    for command in commands:
        runner(command, root)
    return commands
```

Add an `argparse` CLI with `--dry-run`, resolve the repository root from
`Path(__file__).resolve().parent.parent`, and return exit code 0 only after every
command succeeds.

- [ ] **Step 4: Add package shortcuts**

Add these scripts without removing the existing entries:

```json
{
  "refresh:check": "python -m scripts.refresh_guard",
  "refresh:validate": "python -m scripts.validate_archive",
  "refresh:dry": "python -m scripts.publish_archive --dry-run",
  "refresh:publish": "python -m scripts.publish_archive"
}
```

`refresh:check` is documentation discoverability only; the scheduled job must pass
the candidate TXT path explicitly through the Python CLI because npm cannot know it.

- [ ] **Step 5: Run tests and a real local dry-run**

Run:

```powershell
python -m unittest tests.test_publish_archive -v
python -m scripts.publish_archive --dry-run
```

Expected: unit tests pass; the real command runs the entire test suite, validates
the current archive, builds the payload and Hosting shell, and stops without
Firestore, Storage, or Hosting writes.

- [ ] **Step 6: Commit**

```powershell
git add scripts/publish_archive.py tests/test_publish_archive.py package.json
git commit -m "feat: add fail-closed archive publisher"
```

---

### Task 4: Scheduled-run operating instructions

**Files:**
- Create: `docs/DAILY_REFRESH.md`
- Create: `AGENTS.md`

**Interfaces:**
- Consumes: the CLIs created in Tasks 1-3 and existing `collect_chat`, `import_images`, and `archive_downloads` modules
- Produces: one deterministic runbook that a fresh Codex scheduled task can follow without conversation history

- [ ] **Step 1: Write the runbook**

`docs/DAILY_REFRESH.md` must contain this exact stage order:

1. Record the run start time and create `.refresh/YYYY-MM-DD/`.
2. Use Computer Use to verify Windows is unlocked, PC KakaoTalk is logged in,
   and the exact room title contains `바이브코딩,업무자동화 화상회의모임`.
3. Export the full chat TXT into `.refresh/YYYY-MM-DD/`.
4. Run `python -m scripts.refresh_guard <export> --report .refresh/candidate-report.json`.
5. If the report is `unchanged`, run no semantic edits and no Firebase writes;
   report “변경 없음” and stop successfully.
6. Copy `output/*.json`, `output/*.jsonl`, and `output/*.md` to
   `.refresh/YYYY-MM-DD/backup-output/` before mutation.
7. Run `python -m scripts.collect_chat <export> --output output`.
8. Use the KakaoTalk photo drawer to download only photos posted from
   `first_new_timestamp` through the final candidate timestamp.
9. Import downloaded photos with the existing Python interface:

   ```powershell
   python -c "from pathlib import Path; from scripts.import_images import import_image_files; import json,sys; folder=Path(sys.argv[1]); result=import_image_files(Path('output/images.jsonl'), [p for p in folder.iterdir() if p.is_file()], Path.cwd()); print(json.dumps(result, ensure_ascii=False, indent=2))" "<download-folder>"
   python -m scripts.archive_downloads "<download-folder>" --since "<run-start-iso8601>"
   ```

   Replace only the two angle-bracketed runtime values with the actual download
   folder and the ISO 8601 run-start timestamp recorded in stage 1.
10. Read `.refresh/candidate-report.json` and edit only the affected semantic
    areas in `output/topics.json`, `output/topic-digests.json`, and
    `output/knowledge.json`.
11. Preserve all old message coverage; assign every new message to exactly one
    thread; prefer extending a recent coherent thread over creating a one-message
    thread.
12. Update digest `headline` and `overview` only for affected categories.
13. Add/remove graph facts only when supported by messages; keep IDs stable and
    ensure all endpoints exist.
14. Run `python -m scripts.publish_archive --dry-run`.
15. If dry-run fails, restore `backup-output`, retain downloaded images for review,
    report the exact failed command, and do not publish.
16. If dry-run succeeds, run `python -m scripts.publish_archive`.
17. Open `https://katok-crawling-project.web.app`, sign in if a valid session is
    available, and verify the latest message date, total count, affected digest,
    graph rendering, and a newly downloaded image when present.
18. Report old/new message counts, new photo counts, affected categories, upload
    result, deployed URL, unresolved images, and any manual-review items.

Include a prominent prohibition against guessing photo-message mappings and against
printing secrets.

- [ ] **Step 2: Write durable repository instructions**

Create `AGENTS.md` with:

```markdown
# Project Instructions

## Daily archive refresh

- Follow `docs/DAILY_REFRESH.md` exactly for scheduled KakaoTalk refreshes.
- Treat `python -m scripts.publish_archive --dry-run` as the publication gate.
- Never run the live publisher after any failed collection, integrity check, test,
  payload dry-run, or Hosting build.
- Do not inspect KakaoTalk databases or caches; use only the official Windows UI.
- Do not guess image mappings. Preserve uncertain files as unresolved.
- Do not expose or commit service-account keys, member data, auth tokens, raw daily
  exports, `.refresh/`, or the download inbox.
- Preserve existing topic IDs and historical assignments unless correcting a clear
  error supported by the messages.

## Verification commands

- Full tests: `python -m unittest discover -s tests -v`
- Archive integrity: `python -m scripts.validate_archive`
- Publication dry-run: `python -m scripts.publish_archive --dry-run`
```

- [ ] **Step 3: Review the instructions for standalone usability**

Start a fresh local Codex task mentally from only `AGENTS.md` and
`docs/DAILY_REFRESH.md`. Confirm it identifies:

- exact chat room;
- exact candidate validation command;
- semantic update files and invariants;
- fail-closed publication command;
- success verification and report fields.

Run:

```powershell
rg -n "바이브코딩|refresh_guard|topics.json|topic-digests.json|knowledge.json|publish_archive --dry-run|web.app" AGENTS.md docs/DAILY_REFRESH.md
```

Expected: every required term appears in the runbook, and the safety commands appear
in both files where appropriate.

- [ ] **Step 4: Commit**

```powershell
git add AGENTS.md docs/DAILY_REFRESH.md
git commit -m "docs: define scheduled KakaoTalk refresh runbook"
```

---

### Task 5: First manual dry run and failure rehearsal

**Files:**
- No source files expected
- Runtime only: `.refresh/manual-test/`

**Interfaces:**
- Consumes: a fresh daytime KakaoTalk export and the current archive
- Produces: evidence that unchanged, forward-only, and fail-closed paths work before scheduling

- [ ] **Step 1: Test the unchanged-export path**

Use Computer Use to export the full target room into
`.refresh/manual-test/KakaoTalk_daily.txt`, then run:

```powershell
python -m scripts.refresh_guard ".refresh/manual-test/KakaoTalk_daily.txt" --report ".refresh/manual-test/candidate.json"
```

Expected: `status` is `unchanged` or `advanced` relative to the current
`output/messages.jsonl`; a truncated or rewritten export fails and must be investigated
before continuing.

- [ ] **Step 2: Run the real publication dry-run**

Run:

```powershell
python -m scripts.publish_archive --dry-run
```

Expected: all tests and integrity checks pass; no Firebase write command runs.

- [ ] **Step 3: Rehearse fail-closed behavior**

Copy `output/topics.json` to `.refresh/manual-test/topics.json`, remove one message ID
only in the temporary copy, and invoke `validate_archive()` against a temporary output
directory assembled from the backup. Do not modify the real `output/`.

Expected: `ArchiveValidationError` contains `주제 커버리지`, and no upload/deploy
command is invoked.

- [ ] **Step 4: Verify credentials without mutating Firebase**

Run:

```powershell
node scripts/upload_firestore.js --dry-run
firebase use
```

Expected: the payload plan prints, and the active Firebase project is
`katok-crawling-project`.

- [ ] **Step 5: Record the rehearsal result**

Append a dated “최초 운영 검증” section to `docs/DAILY_REFRESH.md` containing:

- test suite result count;
- current message and image counts;
- active Firebase project;
- unchanged/advanced guard result;
- confirmation that no network writes were performed.

- [ ] **Step 6: Commit**

```powershell
git add docs/DAILY_REFRESH.md
git commit -m "docs: record daily refresh rehearsal"
```

---

### Task 6: Live daytime end-to-end trial

**Files:**
- Runtime archive files may change if the KakaoTalk room has new content
- No unrelated source changes

**Interfaces:**
- Consumes: unlocked Windows session, logged-in PC KakaoTalk, Firebase credentials
- Produces: one verified live refresh before the unattended schedule is activated

- [ ] **Step 1: Follow the runbook through collection and semantic updates**

Execute `docs/DAILY_REFRESH.md` from stage 1 through stage 14 during daytime. Use
Computer Use for KakaoTalk only. Stop immediately if the room title does not match.

- [ ] **Step 2: Inspect the dry-run evidence**

Require:

- no failed unit tests;
- no `ArchiveValidationError`;
- Firebase upload dry-run success;
- new messages have exactly one thread assignment;
- unresolved images are explicitly reported.

- [ ] **Step 3: Ask for approval only if the trial reveals ambiguous image mappings**

Do not block for ordinary successful collection. If and only if a new photo cannot be
mapped with timestamp/sender/order evidence, leave it unresolved, continue the text
refresh, and surface the specific photo filenames in the final trial report.

- [ ] **Step 4: Publish the trial**

Run:

```powershell
python -m scripts.publish_archive
```

Expected: Firestore and Storage synchronization completes before Firebase Hosting
deployment.

- [ ] **Step 5: Verify production**

Open `https://katok-crawling-project.web.app` and confirm:

- login gate still appears for signed-out users;
- the latest message date and total count match local validation;
- affected topic digests render;
- the knowledge graph renders without missing endpoints;
- at least one newly collected image loads when new images exist.

- [ ] **Step 6: Commit only durable source/data changes that are intended for Git**

Before committing, inspect `git status --short`. Never add raw daily exports,
`.refresh/`, inbox files, service keys, member configuration, or runtime staging.

```powershell
git add scripts tests docs AGENTS.md package.json .gitignore
git commit -m "feat: automate daily KakaoTalk archive refresh"
```

If no tracked durable file changed, do not create an empty commit.

---

### Task 7: Create and activate the Codex scheduled job

**Files:**
- No repository files
- Codex automation state only

**Interfaces:**
- Consumes saved Codex project ID for `D:\apps\카톡데이터크롤링`
- Produces active local cron automation named `카카오톡 아카이브 매일 갱신`

- [ ] **Step 1: Confirm the saved local project**

Call Codex `list_projects` and select the exact entry whose path is
`D:\apps\카톡데이터크롤링`. Do not use a worktree: the job needs the saved local
checkout, its ignored Firebase credential, the live Windows desktop, and PC KakaoTalk.

- [ ] **Step 2: Create the active daily local automation**

Use Codex `automation_update` in create mode with:

- kind: cron;
- execution environment: local;
- destination: local;
- project: the exact ID returned in Step 1;
- name: `카카오톡 아카이브 매일 갱신`;
- model: `gpt-5.6-sol`;
- reasoning effort: `high`;
- status: active;
- schedule: every day at 04:00 in the user’s `Asia/Seoul` timezone;
- notifications: retain the default so successes and failures remain visible.

Use this automation prompt verbatim:

```text
`AGENTS.md`와 `docs/DAILY_REFRESH.md`를 먼저 전부 읽고, 문서의 일일 갱신 절차를
처음부터 끝까지 수행하세요. 대상은 PC 카카오톡의
`바이브코딩,업무자동화 화상회의모임` 채팅방입니다. 공식 카카오톡 Windows UI만
사용해 전체 대화 TXT와 새 사진을 수집하세요. 새 메시지가 없으면 Firebase를
변경하지 말고 “변경 없음”으로 종료하세요. 새 메시지가 있으면 기존 주제 체계를
우선 유지하면서 topics.json, topic-digests.json, knowledge.json을 함께
갱신하세요. 사진 연결은 추측하지 말고 불확실하면 unresolved로 남기세요.
`python -m scripts.publish_archive --dry-run`이 완전히 성공한 경우에만
`python -m scripts.publish_archive`를 실행하세요. 실패하면 원격 배포를 하지
말고 기존 공개본을 유지하며 실패 단계와 원인을 보고하세요. 성공하면 이전/현재
메시지 수, 새 사진 수, 영향받은 주제, 미해결 사진, Firebase 업로드 결과와
배포 URL을 보고하세요. 비밀키, 토큰, 멤버 이메일, 원본 대화 전문은 출력하지
마세요.
```

- [ ] **Step 3: View the created automation**

Call `automation_update` in view mode with the returned automation ID. Confirm:

- name matches exactly;
- status is active;
- project is the saved local KakaoTalk project;
- the next run corresponds to 04:00 Asia/Seoul;
- the prompt includes the dry-run publication gate.

- [ ] **Step 4: Hand off operational constraints**

Report clearly that the scheduled run requires:

- PC powered on;
- Codex app running;
- Windows session unlocked;
- PC KakaoTalk logged in and not blocked by an update dialog;
- network access available for Firebase upload/deploy.

Do not claim the schedule is operational until the create call and view verification
both succeed.
