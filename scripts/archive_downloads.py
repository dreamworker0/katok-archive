from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import shutil


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


def _digest(path: Path) -> str:
    value = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _mapped_hashes(manifest_path: Path) -> dict[str, list[str]]:
    mapped: dict[str, list[str]] = defaultdict(list)
    if not manifest_path.is_file():
        return mapped
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        for asset in record.get("assets") or []:
            digest = asset.get("sha256")
            if isinstance(digest, str):
                mapped[digest].append(str(record["image_id"]))
    return mapped


def archive_downloads(
    downloads_dir: Path,
    workspace_root: Path,
    manifest_path: Path,
    since: datetime | None = None,
) -> list[dict[str, object]]:
    candidates = [
        path
        for path in downloads_dir.iterdir()
        if path.is_file()
        and path.suffix.lower() in IMAGE_EXTENSIONS
        and (since is None or datetime.fromtimestamp(path.stat().st_mtime).astimezone() >= since)
    ]
    files_by_hash: dict[str, list[Path]] = defaultdict(list)
    for path in candidates:
        files_by_hash[_digest(path)].append(path)

    mapped = _mapped_hashes(manifest_path)
    staging = workspace_root / "assets" / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []

    for digest, paths in sorted(
        files_by_hash.items(),
        key=lambda item: min(path.stat().st_mtime for path in item[1]),
    ):
        paths.sort(key=lambda path: (path.stat().st_mtime, path.name))
        source = paths[0]
        relative_path = (
            Path("assets") / "staging" / f"{digest[:16]}{source.suffix.lower()}"
        ).as_posix()
        destination = workspace_root / relative_path
        if not destination.is_file() or _digest(destination) != digest:
            shutil.copy2(source, destination)
        image_ids = sorted(set(mapped.get(digest, [])))
        records.append(
            {
                "download_id": f"download-{digest[:16]}",
                "status": "mapped" if image_ids else "unresolved",
                "local_path": relative_path,
                "source_filenames": [path.name for path in paths],
                "byte_size": source.stat().st_size,
                "sha256": digest,
                "saved_at": datetime.fromtimestamp(
                    min(path.stat().st_mtime for path in paths)
                )
                .astimezone()
                .isoformat(timespec="seconds"),
                "mapped_image_ids": image_ids,
            }
        )

    output_path = workspace_root / "output" / "downloaded-files.jsonl"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    return records


def main() -> int:
    parser = argparse.ArgumentParser(
        description="카카오톡 다운로드 폴더의 사진을 중복 제거해 작업 폴더에 보관합니다."
    )
    parser.add_argument("downloads_dir", type=Path)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("output/images.jsonl"),
    )
    parser.add_argument(
        "--since",
        type=datetime.fromisoformat,
        help="이 시각 이후 저장된 파일만 처리합니다(ISO 8601).",
    )
    args = parser.parse_args()
    records = archive_downloads(
        downloads_dir=args.downloads_dir,
        workspace_root=args.workspace,
        manifest_path=args.manifest,
        since=args.since,
    )
    print(
        json.dumps(
            {
                "unique_images": len(records),
                "mapped": sum(record["status"] == "mapped" for record in records),
                "unresolved": sum(
                    record["status"] == "unresolved" for record in records
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
