import json
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

from scripts.archive_downloads import archive_downloads


class ArchiveDownloadsTests(unittest.TestCase):
    def test_copies_unique_images_and_records_duplicates_and_mapping(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            downloads = root / "downloads"
            downloads.mkdir()
            first = downloads / "KakaoTalk_20260723_130000000.png"
            duplicate = downloads / "KakaoTalk_20260723_130000000 (1).png"
            other = downloads / "KakaoTalk_20260723_140000000.jpg"
            video = downloads / "KakaoTalk_20260723_150000000.mp4"
            first.write_bytes(b"same-photo")
            duplicate.write_bytes(b"same-photo")
            other.write_bytes(b"other-photo")
            video.write_bytes(b"video")

            manifest = root / "output" / "images.jsonl"
            manifest.parent.mkdir()
            manifest.write_text(
                json.dumps(
                    {
                        "image_id": "img-000001",
                        "assets": [{"sha256": sha256(b"same-photo").hexdigest()}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            records = archive_downloads(
                downloads_dir=downloads,
                workspace_root=root,
                manifest_path=manifest,
            )
            staged_count = len(list((root / "assets" / "staging").glob("*")))

        self.assertEqual(len(records), 2)
        duplicate_record = next(
            record for record in records if len(record["source_filenames"]) == 2
        )
        self.assertCountEqual(
            duplicate_record["source_filenames"],
            [first.name, duplicate.name],
        )
        self.assertTrue(duplicate_record["local_path"].startswith("assets/staging/"))
        self.assertEqual(duplicate_record["status"], "mapped")
        self.assertEqual(staged_count, 2)


if __name__ == "__main__":
    unittest.main()
