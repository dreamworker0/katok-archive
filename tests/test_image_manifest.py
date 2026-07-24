from pathlib import Path
import tempfile
import unittest

from scripts.image_manifest import (
    build_image_records,
    mark_image_status,
    register_download,
)
from scripts.kakao_parser import parse_chat


class ImageManifestTests(unittest.TestCase):
    def test_builds_sequence_for_same_sender_and_minute(self):
        result = parse_chat(
            """--------------- 2026년 7월 23일 목요일 ---------------
[A] [오후 1:00] 사진
[A] [오후 1:00] 사진
[B] [오후 1:00] 사진
"""
        )
        records = build_image_records(result.messages)

        self.assertEqual([r["image_sequence"] for r in records], [1, 2, 1])
        self.assertTrue(all(r["status"] == "pending" for r in records))

    def test_registers_size_hash_path_and_original_name(self):
        result = parse_chat(
            """--------------- 2026년 7월 23일 목요일 ---------------
[A] [오후 1:00] 사진
"""
        )
        records = build_image_records(result.messages)
        with tempfile.TemporaryDirectory() as temp_dir:
            image = Path(temp_dir) / "msg-000001.jpg"
            image.write_bytes(b"photo-bytes")
            updated = register_download(
                records=records,
                image_id="img-000001",
                physical_path=image,
                relative_path="assets/images/2026-07/msg-000001.jpg",
                collected_at="2026-07-23T22:00:00+09:00",
                original_filename="KakaoTalk_20260723_130000.jpg",
            )

        self.assertEqual(updated[0]["status"], "downloaded")
        self.assertEqual(updated[0]["byte_size"], 11)
        self.assertEqual(len(updated[0]["sha256"]), 64)
        self.assertEqual(
            updated[0]["original_filename"],
            "KakaoTalk_20260723_130000.jpg",
        )

    def test_marks_unavailable_without_losing_message_metadata(self):
        result = parse_chat(
            """--------------- 2026년 7월 23일 목요일 ---------------
[A] [오후 1:00] 사진
"""
        )
        records = build_image_records(result.messages)
        updated = mark_image_status(
            records,
            "img-000001",
            "unavailable",
            "카카오톡에서 원본을 내려받을 수 없음",
        )

        self.assertEqual(updated[0]["status"], "unavailable")
        self.assertEqual(updated[0]["nickname"], "A")
        self.assertEqual(updated[0]["note"], "카카오톡에서 원본을 내려받을 수 없음")

    def test_manifest_records_expected_album_size(self):
        result = parse_chat(
            """--------------- 2026년 7월 23일 목요일 ---------------
[A] [오후 1:00] 사진 3장
"""
        )
        records = build_image_records(result.messages)

        self.assertEqual(records[0]["expected_asset_count"], 3)

    def test_registers_multiple_files_for_one_image_message(self):
        result = parse_chat(
            """--------------- 2026년 7월 23일 목요일 ---------------
[A] [오후 1:00] 사진
"""
        )
        records = build_image_records(result.messages)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "first.jpg"
            second = root / "second.png"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            updated = register_download(
                records,
                "img-000001",
                first,
                "assets/images/2026-07/msg-000001-01.jpg",
                "2026-07-23T22:00:00+09:00",
                "KakaoTalk_20260723_130001000.jpg",
            )
            updated = register_download(
                updated,
                "img-000001",
                second,
                "assets/images/2026-07/msg-000001-02.png",
                "2026-07-23T22:00:01+09:00",
                "KakaoTalk_20260723_130002000.png",
            )

        self.assertEqual(updated[0]["status"], "downloaded")
        self.assertEqual(len(updated[0]["assets"]), 2)
        self.assertEqual(updated[0]["assets"][0]["asset_id"], "img-000001-01")
        self.assertEqual(updated[0]["assets"][1]["asset_id"], "img-000001-02")

    def test_marks_album_partial_until_all_expected_files_are_registered(self):
        result = parse_chat(
            """--------------- 2026년 7월 23일 목요일 ---------------
[A] [오후 1:00] 사진 3장
"""
        )
        records = build_image_records(result.messages)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            files = []
            for index in range(3):
                image = root / f"album-{index + 1}.jpg"
                image.write_bytes(f"photo-{index + 1}".encode())
                files.append(image)

            updated = records
            for index, image in enumerate(files, start=1):
                updated = register_download(
                    updated,
                    "img-000001",
                    image,
                    f"assets/images/2026-07/msg-000001-{index:02d}.jpg",
                    f"2026-07-23T22:00:0{index}+09:00",
                    f"KakaoTalk_20260723_13000{index}000.jpg",
                )
                expected_status = "partial" if index < 3 else "downloaded"
                self.assertEqual(updated[0]["status"], expected_status)


if __name__ == "__main__":
    unittest.main()
