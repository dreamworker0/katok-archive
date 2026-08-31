from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
from pathlib import Path
from typing import Iterable

from scripts.kakao_parser import Message


IMAGE_STATUSES = {
    "pending",
    "partial",
    "downloaded",
    "unavailable",
    "needs_review",
}


def build_image_records(messages: Iterable[Message]) -> list[dict[str, object]]:
    sequences: dict[tuple[str, str], int] = defaultdict(int)
    records: list[dict[str, object]] = []

    for message in messages:
        # 동영상도 같은 대장에 올린다 — kakao_parser 가 image_id 를 매기는 기준과
        # 같다. 여기서만 사진으로 좁혀 두면 동영상은 원본을 받아도 붙일 자리가 없다.
        if message.kind not in ("image", "video"):
            continue
        key = (message.nickname, message.timestamp)
        sequences[key] += 1
        records.append(
            {
                "image_id": message.image_id,
                "message_id": message.id,
                "timestamp": message.timestamp,
                "nickname": message.nickname,
                "media_kind": message.kind,
                "image_sequence": sequences[key],
                "expected_asset_count": message.image_count,
                "status": "pending",
                "local_path": None,
                "original_filename": None,
                "extension": None,
                "byte_size": None,
                "sha256": None,
                "collected_at": None,
                "note": None,
                "assets": [],
            }
        )

    return records


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def register_download(
    records: list[dict[str, object]],
    image_id: str,
    physical_path: Path,
    relative_path: str,
    collected_at: str,
    original_filename: str,
) -> list[dict[str, object]]:
    if not physical_path.is_file():
        raise FileNotFoundError(physical_path)

    found = False
    updated: list[dict[str, object]] = []
    for record in records:
        item = dict(record)
        if item["image_id"] == image_id:
            found = True
            assets = [dict(asset) for asset in item.get("assets", [])]
            asset_data = {
                "asset_id": f"{image_id}-{len(assets) + 1:02d}",
                "local_path": relative_path.replace("\\", "/"),
                "original_filename": original_filename,
                "extension": physical_path.suffix.lower(),
                "byte_size": physical_path.stat().st_size,
                "sha256": _file_sha256(physical_path),
                "collected_at": collected_at,
            }
            matching_index = next(
                (
                    index
                    for index, asset in enumerate(assets)
                    if asset.get("original_filename") == original_filename
                ),
                None,
            )
            if matching_index is None:
                assets.append(asset_data)
            else:
                asset_data["asset_id"] = assets[matching_index]["asset_id"]
                assets[matching_index] = asset_data

            expected_count = int(item.get("expected_asset_count") or 1)
            status = "downloaded" if len(assets) >= expected_count else "partial"
            note = (
                None
                if status == "downloaded"
                else f"{len(assets)}/{expected_count}개 파일 수집"
            )
            item.update({"status": status, "note": note, "assets": assets})
            item.update(
                {
                    field: asset_data[field]
                    for field in (
                        "local_path",
                        "original_filename",
                        "extension",
                        "byte_size",
                        "sha256",
                        "collected_at",
                    )
                }
            )
        updated.append(item)

    if not found:
        raise KeyError(f"Unknown image_id: {image_id}")
    return updated


def mark_image_status(
    records: list[dict[str, object]],
    image_id: str,
    status: str,
    note: str,
) -> list[dict[str, object]]:
    if status not in {"unavailable", "needs_review"}:
        raise ValueError("Manual status must be unavailable or needs_review")

    found = False
    updated: list[dict[str, object]] = []
    for record in records:
        item = dict(record)
        if item["image_id"] == image_id:
            found = True
            item.update(
                {
                    "status": status,
                    "local_path": None,
                    "original_filename": None,
                    "extension": None,
                    "byte_size": None,
                    "sha256": None,
                    "collected_at": None,
                    "note": note,
                    "assets": [],
                }
            )
        updated.append(item)

    if not found:
        raise KeyError(f"Unknown image_id: {image_id}")
    return updated
