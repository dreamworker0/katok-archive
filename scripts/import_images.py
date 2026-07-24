from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from scripts.image_manifest import register_download
from scripts.kakao_parser import KST


KAKAO_IMAGE_RE = re.compile(
    r"KakaoTalk_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})(\d{3})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ImageMatch:
    image_id: str
    path: Path
    captured_at: datetime


@dataclass(frozen=True)
class UnresolvedImage:
    path: Path
    reason: str
    minute: str | None


def _file_timestamp(path: Path) -> datetime | None:
    match = KAKAO_IMAGE_RE.search(path.stem)
    if not match:
        return None
    year, month, day, hour, minute, second, millisecond = map(int, match.groups())
    return datetime(
        year,
        month,
        day,
        hour,
        minute,
        second,
        millisecond * 1000,
        tzinfo=KST,
    )


def _file_digest(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def match_image_files(
    records: list[dict[str, object]],
    files: list[Path],
) -> tuple[list[ImageMatch], list[UnresolvedImage]]:
    records_by_minute: dict[str, list[dict[str, object]]] = defaultdict(list)
    for record in records:
        records_by_minute[str(record["timestamp"])[:16]].append(record)
    for minute_records in records_by_minute.values():
        minute_records.sort(key=lambda record: int(record["image_sequence"]))

    files_by_minute: dict[str, list[tuple[Path, datetime]]] = defaultdict(list)
    unresolved: list[UnresolvedImage] = []
    for path in files:
        timestamp = _file_timestamp(path)
        if timestamp is None:
            unresolved.append(UnresolvedImage(path, "unrecognized_filename", None))
            continue
        minute = timestamp.isoformat(timespec="minutes")[:16]
        files_by_minute[minute].append((path, timestamp))

    matches: list[ImageMatch] = []
    for minute, minute_files in files_by_minute.items():
        minute_files.sort(key=lambda item: (item[1], item[0].name))
        minute_records = records_by_minute.get(minute, [])
        if not minute_records:
            unresolved.extend(
                UnresolvedImage(path, "no_message", minute)
                for path, _ in minute_files
            )
            continue
        if len(minute_records) == 1:
            image_id = str(minute_records[0]["image_id"])
            matches.extend(
                ImageMatch(image_id, path, timestamp)
                for path, timestamp in minute_files
            )
            continue
        if len(minute_records) == len(minute_files):
            matches.extend(
                ImageMatch(str(record["image_id"]), path, timestamp)
                for record, (path, timestamp) in zip(minute_records, minute_files)
            )
            continue
        unresolved.extend(
            UnresolvedImage(path, "ambiguous_minute", minute)
            for path, _ in minute_files
        )

    matches.sort(key=lambda match: (match.captured_at, match.path.name))
    unresolved.sort(key=lambda item: item.path.name)
    return matches, unresolved


def _read_manifest(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_manifest_atomic(path: Path, records: list[dict[str, object]]) -> None:
    content = "".join(
        json.dumps(record, ensure_ascii=False) + "\n"
        for record in records
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        delete=False,
        dir=path.parent,
        prefix=".images-",
        suffix=".jsonl",
    ) as stream:
        stream.write(content)
        temporary_path = Path(stream.name)
    os.replace(temporary_path, path)


def import_image_files(
    manifest_path: Path,
    files: list[Path],
    workspace_root: Path,
) -> dict[str, object]:
    records = _read_manifest(manifest_path)
    image_files = [
        path
        for path in files
        if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
    ]
    matches, unresolved = match_image_files(records, image_files)
    record_by_id = {str(record["image_id"]): record for record in records}
    imported = 0

    for match in matches:
        record = record_by_id[match.image_id]
        existing_assets = record.get("assets") or []
        source_digest = _file_digest(match.path)
        duplicate = next(
            (
                asset
                for asset in existing_assets
                if asset.get("sha256") == source_digest
                and _file_timestamp(Path(str(asset.get("original_filename", ""))))
                == match.captured_at
            ),
            None,
        )
        if duplicate:
            continue
        existing = next(
            (
                asset
                for asset in existing_assets
                if asset.get("original_filename") == match.path.name
            ),
            None,
        )
        if existing:
            relative_path = str(existing["local_path"])
        else:
            index = len(existing_assets) + 1
            relative_path = (
                Path("assets")
                / "images"
                / match.captured_at.strftime("%Y-%m")
                / f"{record['message_id']}-{index:02d}{match.path.suffix.lower()}"
            ).as_posix()

        destination = workspace_root / Path(relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(match.path, destination)
        records = register_download(
            records=records,
            image_id=match.image_id,
            physical_path=destination,
            relative_path=relative_path,
            collected_at=datetime.now(KST).isoformat(timespec="seconds"),
            original_filename=match.path.name,
        )
        record_by_id = {str(item["image_id"]): item for item in records}
        imported += 1

    _write_manifest_atomic(manifest_path, records)
    return {
        "imported": imported,
        "unresolved": [
            {
                "path": str(item.path),
                "reason": item.reason,
                "minute": item.minute,
            }
            for item in unresolved
        ],
    }
