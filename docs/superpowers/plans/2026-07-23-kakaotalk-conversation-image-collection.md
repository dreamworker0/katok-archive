# KakaoTalk Conversation and Image Collection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse the exported KakaoTalk TXT into AI-ready conversation data with original nicknames, then download and map every available photo to its message timestamp, nickname, and order.

**Architecture:** A dependency-free Python parser converts the TXT into JSONL, Markdown, participant statistics, an image manifest, and a collection report. Computer Use operates only the official KakaoTalk Windows UI to download photos; Python then hashes and records downloaded files without inspecting KakaoTalk databases or caches.

**Tech Stack:** Python 3.14 standard library, `unittest`, JSON Lines, Markdown, Windows Computer Use (`@oai/sky`)

## Global Constraints

- Keep `KakaoTalk_20260723_2112_31_353_group.txt` unchanged.
- Preserve nicknames exactly as exported.
- Preserve human-authored text, URLs, file-share names, and image-message positions.
- Exclude videos, emoticons, and invitation/leave system messages.
- Do not collect attachment document binaries in this plan.
- Store images under `assets/images/YYYY-MM/` and link them to image-message IDs.
- Record uncertain mappings as `needs_review`; never guess.
- Use only Python standard-library packages for local processing.
- The workspace is not a Git repository, so this plan does not initialize Git or create commits.

## File Structure

- Create `scripts/kakao_parser.py`: parse dates, messages, continuations, URLs, kinds, and exclusion counts.
- Create `scripts/image_manifest.py`: update image paths, sizes, hashes, and collection states.
- Create `scripts/collect_chat.py`: command-line orchestration and atomic output generation.
- Create `tests/test_kakao_parser.py`: parser behavior tests.
- Create `tests/test_image_manifest.py`: image registration and hashing tests.
- Create `tests/test_collect_chat.py`: end-to-end output tests.
- Create `output/messages.jsonl`: structured conversation and image-message records.
- Create `output/conversation.md`: human- and AI-readable timeline.
- Create `output/participants.json`: nickname activity summary.
- Create `output/images.jsonl`: resumable photo collection manifest.
- Create `output/collection-report.md`: counts, warnings, and collection status.
- Create `assets/images/`: downloaded photos.
- Create `assets/staging/`: temporary KakaoTalk download location.

---

### Task 1: KakaoTalk TXT parser

**Files:**
- Create: `scripts/kakao_parser.py`
- Create: `tests/test_kakao_parser.py`

**Interfaces:**
- Produces: `parse_chat(text: str) -> ParseResult`
- Produces: `Message(id, timestamp, date, time, nickname, text, urls, kind, image_id, source_line)`
- Produces: `ParseResult(messages, excluded, warnings)`
- Consumes: UTF-8 or UTF-8-BOM KakaoTalk export text supplied as a Python string

- [ ] **Step 1: Write failing parser tests**

```python
# tests/test_kakao_parser.py
import unittest

from scripts.kakao_parser import parse_chat


SAMPLE = """방 이름 님과 카카오톡 대화
저장한 날짜 : 2026-07-23 21:12:40

--------------- 2026년 3월 8일 일요일 ---------------
[김 종원] [오전 9:48] 사진
[김 종원] [오전 9:48] 첫 줄
둘째 줄 https://example.com/a
[한도윤 (관리자)] [오후 12:00] 파일: 계획서.md
홍길동님이 새사용자님을 초대했습니다.
[김 종원] [오후 1:00] 동영상
[김 종원] [오후 1:01] 이모티콘
"""


class ParseChatTests(unittest.TestCase):
    def test_preserves_image_text_file_and_multiline_messages(self):
        result = parse_chat(SAMPLE)

        self.assertEqual([m.kind for m in result.messages], ["image", "text", "file"])
        self.assertEqual(result.messages[0].nickname, "김 종원")
        self.assertEqual(result.messages[0].image_id, "img-000001")
        self.assertEqual(result.messages[1].text, "첫 줄\n둘째 줄 https://example.com/a")
        self.assertEqual(result.messages[1].urls, ["https://example.com/a"])
        self.assertEqual(result.messages[2].nickname, "한도윤 (관리자)")
        self.assertEqual(result.messages[2].time, "12:00")

    def test_excludes_video_emoticon_and_system_event(self):
        result = parse_chat(SAMPLE)

        self.assertEqual(result.excluded["video"], 1)
        self.assertEqual(result.excluded["emoticon"], 1)
        self.assertEqual(result.excluded["system"], 1)

    def test_converts_midnight_and_noon(self):
        text = """--------------- 2026년 7월 23일 목요일 ---------------
[A] [오전 12:01] 자정 이후
[B] [오후 12:01] 정오 이후
"""
        result = parse_chat(text)

        self.assertEqual(result.messages[0].time, "00:01")
        self.assertEqual(result.messages[1].time, "12:01")
        self.assertTrue(result.messages[0].timestamp.endswith("+09:00"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the parser tests and confirm the expected import failure**

Run:

```powershell
python -m unittest tests.test_kakao_parser -v
```

Expected: `ModuleNotFoundError: No module named 'scripts.kakao_parser'`.

- [ ] **Step 3: Implement the parser**

Implement these exact public types and functions in `scripts/kakao_parser.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import re

KST = timezone(timedelta(hours=9))
DATE_RE = re.compile(r"^-+ (\d{4})년 (\d{1,2})월 (\d{1,2})일 .+ -+$")
MESSAGE_RE = re.compile(r"^\[(.+)\] \[(오전|오후) (\d{1,2}):(\d{2})\] ?(.*)$")
URL_RE = re.compile(r"https?://[^\s\)\]<>]+")
SYSTEM_RE = re.compile(
    r"^.+님이 .+님(?:, .+님)*을 초대했습니다\.$"
)


@dataclass(frozen=True)
class Message:
    id: str
    timestamp: str
    date: str
    time: str
    nickname: str
    text: str
    urls: list[str]
    kind: str
    image_id: str | None
    source_line: int


@dataclass(frozen=True)
class ParseResult:
    messages: list[Message]
    excluded: dict[str, int]
    warnings: list[dict[str, object]]


def _to_24_hour(period: str, hour: int) -> int:
    if period == "오전":
        return 0 if hour == 12 else hour
    return 12 if hour == 12 else hour + 12


def _kind_for(text: str) -> str:
    if text == "사진":
        return "image"
    if text.startswith("파일:"):
        return "file"
    return "text"


def parse_chat(text: str) -> ParseResult:
    lines = text.lstrip("\ufeff").splitlines()
    current_date: tuple[int, int, int] | None = None
    raw_messages: list[dict[str, object]] = []
    excluded = {"video": 0, "emoticon": 0, "system": 0}
    warnings: list[dict[str, object]] = []
    active: dict[str, object] | None = None

    def flush() -> None:
        nonlocal active
        if active is not None:
            raw_messages.append(active)
            active = None

    for line_number, line in enumerate(lines, start=1):
        date_match = DATE_RE.match(line)
        if date_match:
            flush()
            current_date = tuple(map(int, date_match.groups()))
            continue

        if SYSTEM_RE.match(line):
            flush()
            excluded["system"] += 1
            continue

        message_match = MESSAGE_RE.match(line)
        if message_match:
            flush()
            nickname, period, hour_text, minute_text, body = message_match.groups()
            if current_date is None:
                warnings.append({"line": line_number, "reason": "message_before_date", "text": line})
                continue
            active = {
                "nickname": nickname,
                "period": period,
                "hour": int(hour_text),
                "minute": int(minute_text),
                "lines": [body],
                "source_line": line_number,
                "date_parts": current_date,
            }
            continue

        if active is not None:
            active["lines"].append(line)
        elif current_date is not None and line.strip():
            excluded["system"] += 1

    flush()

    messages: list[Message] = []
    image_count = 0
    for raw in raw_messages:
        body = "\n".join(raw["lines"]).rstrip()
        if body == "동영상":
            excluded["video"] += 1
            continue
        if body == "이모티콘":
            excluded["emoticon"] += 1
            continue
        kind = _kind_for(body)
        if kind == "image":
            image_count += 1
        year, month, day = raw["date_parts"]
        hour = _to_24_hour(raw["period"], raw["hour"])
        minute = raw["minute"]
        dt = datetime(year, month, day, hour, minute, tzinfo=KST)
        message_number = len(messages) + 1
        messages.append(
            Message(
                id=f"msg-{message_number:06d}",
                timestamp=dt.isoformat(timespec="minutes"),
                date=dt.date().isoformat(),
                time=dt.strftime("%H:%M"),
                nickname=raw["nickname"],
                text=body,
                urls=URL_RE.findall(body),
                kind=kind,
                image_id=f"img-{image_count:06d}" if kind == "image" else None,
                source_line=raw["source_line"],
            )
        )
    return ParseResult(messages=messages, excluded=excluded, warnings=warnings)
```

- [ ] **Step 4: Run tests and confirm all parser tests pass**

Run:

```powershell
python -m unittest tests.test_kakao_parser -v
```

Expected: 3 tests pass.

---

### Task 2: Image manifest state and hashing

**Files:**
- Create: `scripts/image_manifest.py`
- Create: `tests/test_image_manifest.py`

**Interfaces:**
- Consumes: parser `Message` objects where `kind == "image"`
- Produces: `build_image_records(messages) -> list[dict[str, object]]`
- Produces: `register_download(records, image_id, path, collected_at) -> list[dict[str, object]]`

- [ ] **Step 1: Write failing image-manifest tests**

```python
# tests/test_image_manifest.py
from pathlib import Path
import tempfile
import unittest

from scripts.image_manifest import build_image_records, register_download
from scripts.kakao_parser import parse_chat


class ImageManifestTests(unittest.TestCase):
    def test_builds_sequence_for_same_sender_and_minute(self):
        result = parse_chat("""--------------- 2026년 7월 23일 목요일 ---------------
[A] [오후 1:00] 사진
[A] [오후 1:00] 사진
[B] [오후 1:00] 사진
""")
        records = build_image_records(result.messages)

        self.assertEqual([r["image_sequence"] for r in records], [1, 2, 1])
        self.assertTrue(all(r["status"] == "pending" for r in records))

    def test_registers_size_hash_and_relative_path(self):
        result = parse_chat("""--------------- 2026년 7월 23일 목요일 ---------------
[A] [오후 1:00] 사진
""")
        records = build_image_records(result.messages)
        with tempfile.TemporaryDirectory() as temp_dir:
            image = Path(temp_dir) / "msg-000001.jpg"
            image.write_bytes(b"photo-bytes")
            updated = register_download(
                records,
                "img-000001",
                image,
                "assets/images/2026-07/msg-000001.jpg",
                "2026-07-23T22:00:00+09:00",
            )

        self.assertEqual(updated[0]["status"], "downloaded")
        self.assertEqual(updated[0]["byte_size"], 11)
        self.assertEqual(len(updated[0]["sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and confirm the expected import failure**

Run:

```powershell
python -m unittest tests.test_image_manifest -v
```

Expected: `ModuleNotFoundError: No module named 'scripts.image_manifest'`.

- [ ] **Step 3: Implement image records and download registration**

Implement `scripts/image_manifest.py` with:

```python
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
from pathlib import Path
from typing import Iterable

from scripts.kakao_parser import Message


def build_image_records(messages: Iterable[Message]) -> list[dict[str, object]]:
    sequences: dict[tuple[str, str], int] = defaultdict(int)
    records: list[dict[str, object]] = []
    for message in messages:
        if message.kind != "image":
            continue
        key = (message.nickname, message.timestamp)
        sequences[key] += 1
        records.append(
            {
                "image_id": message.image_id,
                "message_id": message.id,
                "timestamp": message.timestamp,
                "nickname": message.nickname,
                "image_sequence": sequences[key],
                "status": "pending",
                "local_path": None,
                "original_filename": None,
                "extension": None,
                "byte_size": None,
                "sha256": None,
                "collected_at": None,
            }
        )
    return records


def register_download(
    records: list[dict[str, object]],
    image_id: str,
    physical_path: Path,
    relative_path: str,
    collected_at: str,
) -> list[dict[str, object]]:
    payload = physical_path.read_bytes()
    found = False
    updated: list[dict[str, object]] = []
    for record in records:
        item = dict(record)
        if item["image_id"] == image_id:
            found = True
            item.update(
                {
                    "status": "downloaded",
                    "local_path": relative_path.replace("\\", "/"),
                    "original_filename": physical_path.name,
                    "extension": physical_path.suffix.lower(),
                    "byte_size": len(payload),
                    "sha256": sha256(payload).hexdigest(),
                    "collected_at": collected_at,
                }
            )
        updated.append(item)
    if not found:
        raise KeyError(f"Unknown image_id: {image_id}")
    return updated
```

- [ ] **Step 4: Run parser and image-manifest tests**

Run:

```powershell
python -m unittest tests.test_kakao_parser tests.test_image_manifest -v
```

Expected: 5 tests pass.

---

### Task 3: Atomic output generator

**Files:**
- Create: `scripts/collect_chat.py`
- Create: `tests/test_collect_chat.py`

**Interfaces:**
- Consumes: input TXT path and output directory
- Produces: `generate_outputs(input_path: Path, output_dir: Path) -> dict[str, int]`
- Uses: `parse_chat`, `build_image_records`

- [ ] **Step 1: Write a failing end-to-end output test**

```python
# tests/test_collect_chat.py
import json
from pathlib import Path
import tempfile
import unittest

from scripts.collect_chat import generate_outputs


class CollectChatTests(unittest.TestCase):
    def test_generates_all_outputs(self):
        text = """--------------- 2026년 7월 23일 목요일 ---------------
[A] [오전 9:00] 안녕하세요 https://example.com
[A] [오전 9:01] 사진
[B] [오전 9:02] 파일: 안내.pdf
[B] [오전 9:03] 이모티콘
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "chat.txt"
            source.write_text(text, encoding="utf-8")
            output = root / "output"
            counts = generate_outputs(source, output)

            messages = [
                json.loads(line)
                for line in (output / "messages.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            images = [
                json.loads(line)
                for line in (output / "images.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            participants_text = (output / "participants.json").read_text(encoding="utf-8")
            conversation_text = (output / "conversation.md").read_text(encoding="utf-8")

        self.assertEqual(counts["messages"], 3)
        self.assertEqual(counts["images"], 1)
        self.assertEqual(messages[0]["nickname"], "A")
        self.assertEqual(images[0]["message_id"], "msg-000002")
        self.assertIn("A", participants_text)
        self.assertIn("2026-07-23", conversation_text)
```

- [ ] **Step 2: Run the test and confirm the expected import failure**

Run:

```powershell
python -m unittest tests.test_collect_chat -v
```

Expected: `ModuleNotFoundError: No module named 'scripts.collect_chat'`.

- [ ] **Step 3: Implement staged output generation**

Implement `scripts/collect_chat.py` so it:

1. Reads with `encoding="utf-8-sig"`.
2. Calls `parse_chat`.
3. Serializes dataclasses with `dataclasses.asdict`.
4. Builds participant counts and first/last timestamps.
5. Writes `messages.jsonl`, `images.jsonl`, `participants.json`, `conversation.md`, and `collection-report.md` to a temporary sibling directory.
6. Parses every JSONL line back with `json.loads`.
7. Verifies unique message IDs and one image record per image message.
8. Creates the output directory and replaces each target file with `os.replace`.
9. Returns counts for messages, participants, URLs, files, and images.

The CLI must be:

```python
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, default=Path("output"))
    args = parser.parse_args()
    counts = generate_outputs(args.input, args.output)
    print(json.dumps(counts, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

The Markdown timeline format must be:

```markdown
# 카카오톡 대화

## 2026-07-23

### 09:00 · A

안녕하세요 https://example.com

### 09:01 · A

![사진](../assets/images/2026-07/msg-000002.jpg)
```

Pending images must use `사진 수집 대기: img-000001` instead of a broken image link. File shares remain literal text.

- [ ] **Step 4: Run all tests**

Run:

```powershell
python -m unittest discover -s tests -v
```

Expected: 6 tests pass.

---

### Task 4: Generate and validate the real conversation dataset

**Files:**
- Create: `output/messages.jsonl`
- Create: `output/conversation.md`
- Create: `output/participants.json`
- Create: `output/images.jsonl`
- Create: `output/collection-report.md`

**Interfaces:**
- Consumes: `KakaoTalk_20260723_2112_31_353_group.txt`
- Produces: validated structured output, 201 image-message records, and 249 expected photo assets

- [ ] **Step 1: Run the collector**

Run:

```powershell
python scripts/collect_chat.py KakaoTalk_20260723_2112_31_353_group.txt --output output
```

Expected JSON output includes `images: 201`, `files: 28`, and at least one participant.

- [ ] **Step 2: Run deterministic validation**

Run:

```powershell
python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 3: Inspect the report and spot-check source mapping**

Check:

- First image: 2026-02-27 18:06, nickname `김종원`
- 2026-03-08 09:48 and 09:49 image runs retain source order
- `gemini_cli_에이전트_구현계획서.md` remains a file-share message
- Videos and emoticons do not appear in `messages.jsonl`
- Every `image_id` in `messages.jsonl` occurs exactly once in `images.jsonl`

Expected: no duplicate IDs and no parse warning that silently drops a human-authored message.

---

### Task 5: Computer Use pilot for three photos

**Files:**
- Create: `assets/staging/` downloaded pilot files
- Modify: `output/images.jsonl`
- Modify: `output/conversation.md`
- Modify: `output/collection-report.md`

**Interfaces:**
- Consumes: three `pending` image records and the running KakaoTalk Windows app
- Produces: three verified `downloaded` or explicitly unresolved image records

- [ ] **Step 1: Select exactly one KakaoTalk target window**

Use Computer Use `list_apps()`, filter to the returned KakaoTalk app, and require exactly one candidate window for the target group chat. If the group chat is not open, launch or select KakaoTalk and stop for user login if authentication is required. Never automate authentication.

- [ ] **Step 2: Observe the window before each action**

Use `get_window_state` with screenshot and accessibility text. Open the upper-right chat drawer, then the photo/video section, using one click followed by a fresh observation each time. Do not reuse coordinates, screenshot IDs, or accessibility indexes after state changes.

- [ ] **Step 3: Verify the mapping workflow on three photos**

For each pilot photo:

1. Open the thumbnail.
2. Read its visible date group and order.
3. Use the viewer's original-message navigation when available to verify nickname and time.
4. Download the original image into `D:\apps\카톡데이터크롤링\assets\staging`.
5. Refresh the app state after the download action.
6. If the UI does not expose enough information to map the photo confidently, set the record to `needs_review` and do not guess.

Downloads are inbound transfers and do not require an additional action-time confirmation.

- [ ] **Step 4: Normalize and register the pilot files**

For each verified pilot:

1. Detect the actual extension from the downloaded filename.
2. Move it to `assets/images/YYYY-MM/msg-NNNNNN.<extension>`.
3. Call `register_download` with the corresponding `image_id`.
4. Rewrite `images.jsonl`, `conversation.md`, and `collection-report.md`.

Expected: three image records have local paths, nonzero sizes, 64-character hashes, and the correct nickname/timestamp mapping.

- [ ] **Step 5: Review the three pilot records**

Compare each downloaded image against the original KakaoTalk message. Continue only if all three mappings are correct. If any mismatch occurs, stop full collection and revise the mapping method.

---

### Task 6: Full photo collection with resumable checkpoints

**Files:**
- Create: `assets/images/YYYY-MM/*`
- Modify: `output/images.jsonl`
- Modify: `output/conversation.md`
- Modify: `output/collection-report.md`

**Interfaces:**
- Consumes: remaining `pending` image records
- Produces: mapped photos plus explicit `unavailable` and `needs_review` states

- [ ] **Step 1: Process one month at a time**

Use the validated pilot workflow for February through July 2026. After every 20 photos or at each month boundary, whichever occurs first:

1. Stop UI input.
2. Save manifest progress.
3. Verify every downloaded path exists.
4. Recompute SHA-256 for the checkpoint.
5. Report downloaded, unavailable, pending, and review counts.

- [ ] **Step 2: Record unavailable photos**

If KakaoTalk shows an expired, unavailable, or failed-download state, update only that image record:

```json
{
  "status": "unavailable",
  "local_path": null,
  "byte_size": null,
  "sha256": null
}
```

Preserve its message ID, timestamp, nickname, and sequence.

- [ ] **Step 3: Record uncertain mappings**

If timestamp, nickname, or sequence cannot be confirmed, set `status` to `needs_review`, leave `local_path` null, and add the reason to the collection report. Do not consume the next manifest item until the UI order is understood.

- [ ] **Step 4: Regenerate timeline and report at every checkpoint**

Downloaded image messages render as relative Markdown images. Pending, unavailable, and review-needed image messages render as labeled placeholders so the timeline never silently loses a photo position.

---

### Task 7: Final verification and handoff

**Files:**
- Verify: `output/messages.jsonl`
- Verify: `output/images.jsonl`
- Verify: `output/participants.json`
- Verify: `output/conversation.md`
- Verify: `output/collection-report.md`
- Verify: `assets/images/**/*`

**Interfaces:**
- Consumes: complete local dataset
- Produces: verified AI-ready archive source

- [ ] **Step 1: Run the full automated test suite**

Run:

```powershell
python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 2: Run integrity checks**

Verify:

- Every JSONL line parses.
- Message IDs are unique.
- Image IDs are unique.
- Image-message and image-manifest counts both equal 201; expected photo assets equal 249.
- Every `downloaded` record points to an existing file whose size and SHA-256 match.
- Every non-downloaded image has one of `pending`, `unavailable`, or `needs_review`.
- Participant nicknames remain identical to the TXT export.
- The original TXT hash and modification time are unchanged from before collection.

- [ ] **Step 3: Report final collection status**

Return:

- human-authored message count
- participant nickname count
- URL occurrence and unique counts
- file-share record count
- photo-message count
- downloaded photo count
- unavailable photo count
- needs-review photo count
- clickable paths to the Markdown timeline, JSONL data, participant data, image manifest, and collection report
