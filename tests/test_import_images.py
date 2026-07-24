from pathlib import Path
import json
import tempfile
import unittest

from scripts.import_images import import_image_files, match_image_files


def record(image_id, message_id, timestamp, sequence):
    return {
        "image_id": image_id,
        "message_id": message_id,
        "timestamp": timestamp,
        "nickname": "A",
        "image_sequence": sequence,
        "status": "pending",
        "assets": [],
    }


class ImportImagesTests(unittest.TestCase):
    def test_matches_unique_minute(self):
        records = [record("img-000001", "msg-000001", "2026-07-23T13:24+09:00", 1)]
        files = [Path("KakaoTalk_20260723_132427513.png")]

        matches, unresolved = match_image_files(records, files)

        self.assertEqual(matches[0].image_id, "img-000001")
        self.assertEqual(unresolved, [])

    def test_groups_multiple_files_into_one_message_when_minute_is_unique(self):
        records = [record("img-000001", "msg-000001", "2026-07-23T13:24+09:00", 1)]
        files = [
            Path("KakaoTalk_20260723_132427513.png"),
            Path("KakaoTalk_20260723_132428514.png"),
        ]

        matches, unresolved = match_image_files(records, files)

        self.assertEqual([match.image_id for match in matches], ["img-000001", "img-000001"])
        self.assertEqual(unresolved, [])

    def test_maps_equal_file_and_message_counts_in_timestamp_order(self):
        records = [
            record("img-000001", "msg-000001", "2026-03-08T09:48+09:00", 1),
            record("img-000002", "msg-000002", "2026-03-08T09:48+09:00", 2),
        ]
        files = [
            Path("KakaoTalk_20260308_094801100.png"),
            Path("KakaoTalk_20260308_094859900.png"),
        ]

        matches, unresolved = match_image_files(records, files)

        self.assertEqual([match.image_id for match in matches], ["img-000001", "img-000002"])
        self.assertEqual(unresolved, [])

    def test_leaves_ambiguous_multi_message_minute_unresolved(self):
        records = [
            record("img-000001", "msg-000001", "2026-03-08T09:48+09:00", 1),
            record("img-000002", "msg-000002", "2026-03-08T09:48+09:00", 2),
        ]
        files = [
            Path("KakaoTalk_20260308_094801100.png"),
            Path("KakaoTalk_20260308_094802100.png"),
            Path("KakaoTalk_20260308_094859900.png"),
        ]

        matches, unresolved = match_image_files(records, files)

        self.assertEqual(matches, [])
        self.assertEqual(len(unresolved), 3)
        self.assertEqual(unresolved[0].reason, "ambiguous_minute")

    def test_imports_matched_file_and_updates_manifest(self):
        records = [record("img-000001", "msg-000001", "2026-07-23T13:24+09:00", 1)]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest = root / "output" / "images.jsonl"
            manifest.parent.mkdir()
            manifest.write_text(
                json.dumps(records[0], ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            source = root / "KakaoTalk_20260723_132427513.png"
            source.write_bytes(b"photo")

            summary = import_image_files(manifest, [source], root)
            updated = json.loads(manifest.read_text(encoding="utf-8").splitlines()[0])
            destination = root / updated["assets"][0]["local_path"]

        self.assertEqual(summary["imported"], 1)
        self.assertEqual(summary["unresolved"], [])
        self.assertEqual(updated["status"], "downloaded")
        self.assertTrue(destination.name.endswith("-01.png"))
        self.assertEqual(updated["assets"][0]["original_filename"], source.name)

    def test_skips_redownloaded_copy_with_same_kakao_timestamp_and_bytes(self):
        records = [record("img-000001", "msg-000001", "2026-07-23T13:24+09:00", 1)]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest = root / "output" / "images.jsonl"
            manifest.parent.mkdir()
            manifest.write_text(
                json.dumps(records[0], ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            first = root / "KakaoTalk_20260723_132427513.png"
            duplicate = root / "KakaoTalk_20260723_132427513 (1).png"
            first.write_bytes(b"same-photo")
            duplicate.write_bytes(b"same-photo")

            summary = import_image_files(manifest, [first, duplicate], root)
            updated = json.loads(manifest.read_text(encoding="utf-8").splitlines()[0])

        self.assertEqual(summary["imported"], 1)
        self.assertEqual(len(updated["assets"]), 1)


if __name__ == "__main__":
    unittest.main()
