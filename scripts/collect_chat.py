from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import tempfile

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.image_manifest import IMAGE_STATUSES, build_image_records
from scripts.kakao_parser import KST, Message, ParseResult, parse_chat


OUTPUT_NAMES = (
    "messages.jsonl",
    "images.jsonl",
    "participants.json",
    "conversation.md",
    "collection-report.md",
)
IMAGE_MUTABLE_FIELDS = (
    "status",
    "local_path",
    "original_filename",
    "extension",
    "byte_size",
    "sha256",
    "collected_at",
    "note",
    "assets",
)


def _read_existing_images(path: Path) -> dict[str, dict[str, object]]:
    if not path.is_file():
        return {}

    records: dict[str, dict[str, object]] = {}
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        record = json.loads(line)
        message_id = record.get("message_id")
        if not isinstance(message_id, str):
            raise ValueError(f"Invalid message_id at {path}:{line_number}")
        if message_id in records:
            raise ValueError(f"Duplicate message_id in existing manifest: {message_id}")
        records[message_id] = record
    return records


def _read_downloaded_files(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _merge_existing_images(
    fresh: list[dict[str, object]],
    existing: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    merged: list[dict[str, object]] = []
    identity_fields = ("message_id", "timestamp", "nickname", "image_sequence")

    for record in fresh:
        item = dict(record)
        previous = existing.get(str(record["message_id"]))
        if previous and all(previous.get(field) == record.get(field) for field in identity_fields):
            status = previous.get("status")
            if status in IMAGE_STATUSES:
                for field in IMAGE_MUTABLE_FIELDS:
                    previous_value = previous.get(field)
                    if field == "assets" and not isinstance(previous_value, list):
                        continue
                    item[field] = previous_value
                if item.get("assets"):
                    migrated_assets = []
                    for index, asset in enumerate(item["assets"], start=1):
                        migrated_asset = dict(asset)
                        migrated_asset["asset_id"] = (
                            f"{item['image_id']}-{index:02d}"
                        )
                        migrated_assets.append(migrated_asset)
                    item["assets"] = migrated_assets
                    expected_count = int(item.get("expected_asset_count") or 1)
                    if len(migrated_assets) < expected_count:
                        item["status"] = "partial"
                        item["note"] = (
                            f"{len(migrated_assets)}/{expected_count}개 파일 수집"
                        )
                    else:
                        item["status"] = "downloaded"
                        item["note"] = None
        merged.append(item)
    return merged


def _message_dict(message: Message) -> dict[str, object]:
    record = asdict(message)
    record["is_file_share"] = message.kind == "file"
    return record


def _build_participants(messages: list[Message]) -> dict[str, object]:
    participants: dict[str, dict[str, object]] = {}
    for message in messages:
        participant = participants.setdefault(
            message.nickname,
            {
                "nickname": message.nickname,
                "message_count": 0,
                "first_timestamp": message.timestamp,
                "last_timestamp": message.timestamp,
            },
        )
        participant["message_count"] = int(participant["message_count"]) + 1
        participant["last_timestamp"] = message.timestamp
    return {"participants": list(participants.values())}


def _render_conversation(
    messages: list[Message],
    images: list[dict[str, object]],
) -> str:
    image_by_id = {str(record["image_id"]): record for record in images}
    output = ["# 카카오톡 대화", ""]
    current_date: str | None = None

    for message in messages:
        if message.date != current_date:
            current_date = message.date
            output.extend([f"## {message.date}", ""])

        output.extend([f"### {message.time} · {message.nickname}", ""])
        if message.kind != "image":
            output.extend([message.text, ""])
            continue

        image = image_by_id[str(message.image_id)]
        status = image["status"]
        assets = image.get("assets") or []
        if status in {"downloaded", "partial"} and assets:
            for asset in assets:
                relative_path = "../" + str(asset["local_path"]).replace("\\", "/")
                output.extend(
                    [
                        f"![사진 · {asset['asset_id']}]({relative_path})",
                        "",
                    ]
                )
            if status == "partial":
                expected_count = int(image.get("expected_asset_count") or 1)
                output.extend(
                    [
                        f"> 사진 일부 수집: {len(assets)}/{expected_count}개",
                        "",
                    ]
                )
        elif status == "downloaded" and image.get("local_path"):
            relative_path = "../" + str(image["local_path"]).replace("\\", "/")
            output.extend([f"![사진 · {message.image_id}]({relative_path})", ""])
        elif status == "unavailable":
            output.extend([f"> 사진 이용 불가: {message.image_id}", ""])
        elif status == "needs_review":
            output.extend([f"> 사진 연결 검토 필요: {message.image_id}", ""])
        else:
            output.extend([f"> 사진 수집 대기: {message.image_id}", ""])

    return "\n".join(output).rstrip() + "\n"


def _source_digest(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _render_report(
    source: Path,
    result: ParseResult,
    images: list[dict[str, object]],
    downloaded_files: list[dict[str, object]],
    generated_at: str,
) -> str:
    messages = result.messages
    url_occurrences = sum(len(message.urls) for message in messages)
    unique_urls = {
        url
        for message in messages
        for url in message.urls
    }
    statuses = Counter(str(record["status"]) for record in images)
    downloaded_assets = sum(
        len(record.get("assets") or [])
        or int(record["status"] == "downloaded" and bool(record.get("local_path")))
        for record in images
    )
    participants = {message.nickname for message in messages}
    mapped_downloads = sum(
        record.get("status") == "mapped" for record in downloaded_files
    )
    unresolved_downloads = sum(
        record.get("status") == "unresolved" for record in downloaded_files
    )

    lines = [
        "# 카카오톡 수집 보고서",
        "",
        f"- 원본 파일: `{source.name}`",
        f"- 원본 크기: {source.stat().st_size} bytes",
        f"- 원본 SHA-256: `{_source_digest(source)}`",
        f"- 생성 시각: {generated_at}",
        f"- 수집된 메시지: {len(messages)}",
        f"- 참여 닉네임: {len(participants)}",
        f"- URL 출현: {url_occurrences}",
        f"- 고유 URL: {len(unique_urls)}",
        f"- 파일 공유 기록: {sum(message.kind == 'file' for message in messages)}",
        f"- 사진 메시지: {len(images)}",
        f"- 사진 메시지의 예상 파일 수: "
        f"{sum(int(record.get('expected_asset_count') or 1) for record in images)}",
        f"- 확보한 고유 사진 파일: {len(downloaded_files)}",
        f"- 대화와 자동 연결된 고유 사진: {mapped_downloads}",
        f"- 연결 보류 중인 고유 사진: {unresolved_downloads}",
        f"- 사진 파일 다운로드 완료: {downloaded_assets}",
        f"- 사진 다운로드 완료: {statuses['downloaded']}",
        f"- 사진 부분 수집: {statuses['partial']}",
        f"- 사진 수집 대기: {statuses['pending']}",
        f"- 사진 이용 불가: {statuses['unavailable']}",
        f"- 사진 연결 검토 필요: {statuses['needs_review']}",
        f"- 제외된 동영상: {result.excluded['video']}",
        f"- 제외된 이모티콘: {result.excluded['emoticon']}",
        f"- 제외된 시스템 메시지: {result.excluded['system']}",
        "",
        "## 파싱 경고",
        "",
    ]

    if not result.warnings:
        lines.append("- 없음")
    else:
        for warning in result.warnings:
            lines.append(
                f"- 원본 {warning['line']}행 · {warning['reason']}: "
                f"`{warning['text']}`"
            )

    return "\n".join(lines).rstrip() + "\n"


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    content = "".join(
        json.dumps(record, ensure_ascii=False) + "\n"
        for record in records
    )
    path.write_text(content, encoding="utf-8")


def _validate_staged(stage: Path) -> None:
    messages = [
        json.loads(line)
        for line in (stage / "messages.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    images = [
        json.loads(line)
        for line in (stage / "images.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    message_ids = [record["id"] for record in messages]
    image_ids = [record["image_id"] for record in images]
    asset_ids = [
        asset["asset_id"]
        for record in images
        for asset in (record.get("assets") or [])
    ]
    image_message_ids = {
        record["id"]
        for record in messages
        if record["kind"] == "image"
    }
    manifest_message_ids = {record["message_id"] for record in images}

    if len(message_ids) != len(set(message_ids)):
        raise ValueError("Duplicate message IDs")
    if len(image_ids) != len(set(image_ids)):
        raise ValueError("Duplicate image IDs")
    if len(asset_ids) != len(set(asset_ids)):
        raise ValueError("Duplicate image asset IDs")
    if image_message_ids != manifest_message_ids:
        raise ValueError("Image messages and image manifest do not match")
    if any(record["status"] not in IMAGE_STATUSES for record in images):
        raise ValueError("Unknown image status")

    json.loads((stage / "participants.json").read_text(encoding="utf-8"))
    for name in OUTPUT_NAMES:
        if not (stage / name).is_file():
            raise ValueError(f"Missing staged output: {name}")


def generate_outputs(input_path: Path, output_dir: Path) -> dict[str, int]:
    if not input_path.is_file():
        raise FileNotFoundError(input_path)

    source_text = input_path.read_text(encoding="utf-8-sig")
    result = parse_chat(source_text)
    fresh_images = build_image_records(result.messages)
    existing_images = _read_existing_images(output_dir / "images.jsonl")
    downloaded_files = _read_downloaded_files(
        output_dir / "downloaded-files.jsonl"
    )
    images = _merge_existing_images(fresh_images, existing_images)
    messages = [_message_dict(message) for message in result.messages]
    participants = _build_participants(result.messages)
    generated_at = datetime.now(KST).isoformat(timespec="seconds")

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".kakao-output-",
        dir=output_dir.parent,
    ) as temp_dir:
        stage = Path(temp_dir)
        _write_jsonl(stage / "messages.jsonl", messages)
        _write_jsonl(stage / "images.jsonl", images)
        (stage / "participants.json").write_text(
            json.dumps(participants, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (stage / "conversation.md").write_text(
            _render_conversation(result.messages, images),
            encoding="utf-8",
        )
        (stage / "collection-report.md").write_text(
            _render_report(
                input_path,
                result,
                images,
                downloaded_files,
                generated_at,
            ),
            encoding="utf-8",
        )
        _validate_staged(stage)

        output_dir.mkdir(parents=True, exist_ok=True)
        for name in OUTPUT_NAMES:
            os.replace(stage / name, output_dir / name)

    urls = [
        url
        for message in result.messages
        for url in message.urls
    ]
    return {
        "messages": len(result.messages),
        "participants": len(participants["participants"]),
        "url_occurrences": len(urls),
        "unique_urls": len(set(urls)),
        "files": sum(message.kind == "file" for message in result.messages),
        "images": len(images),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="카카오톡 TXT를 구조화된 대화 데이터로 변환합니다."
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, default=Path("output"))
    args = parser.parse_args()
    counts = generate_outputs(args.input, args.output)
    print(json.dumps(counts, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
