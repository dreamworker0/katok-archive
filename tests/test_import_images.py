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


class VideoGoesToItsOwnShelfTests(unittest.TestCase):
    """동영상은 사진과 갈라서 다뤄야 한다.

    화면(build_site)은 videos 를 images 에 섞지 않는다 — 섞으면 <img> 로 그리려다
    깨진다. 적재도 videos/ 를 따로 훑는다. 그러니 붙이는 쪽에서 이미 갈라져 있어야
    한다. 파일명 규칙은 사진과 같다(실측 2026-08-31: KakaoTalk_20260831_091607135.mp4).
    """

    def video_record(self, image_id, message_id, timestamp):
        rec = record(image_id, message_id, timestamp, 1)
        rec["media_kind"] = "video"
        return rec

    def test_mp4_matches_a_video_record(self):
        records = [self.video_record("img-003098", "msg-003098", "2026-08-31T09:16+09:00")]
        files = [Path("KakaoTalk_20260831_091607135.mp4")]

        matches, unresolved = match_image_files(records, files)

        self.assertEqual([m.image_id for m in matches], ["img-003098"])
        self.assertEqual(unresolved, [])

    def test_a_photo_and_a_video_in_the_same_minute_do_not_swap(self):
        # 종류를 안 가르면 '기록 수 = 파일 수' 라는 이유만으로 mp4 가 사진 기록에
        # 붙는다. 그러면 그 자리가 화면에서 깨진다.
        records = [
            record("img-000001", "msg-000001", "2026-08-31T09:16+09:00", 1),
            self.video_record("img-003098", "msg-003098", "2026-08-31T09:16+09:00"),
        ]
        files = [
            Path("KakaoTalk_20260831_091607135.mp4"),
            Path("KakaoTalk_20260831_091601000.png"),
        ]

        matches, _ = match_image_files(records, files)
        by_suffix = {m.path.suffix: m.image_id for m in matches}

        self.assertEqual(by_suffix[".mp4"], "img-003098")
        self.assertEqual(by_suffix[".png"], "img-000001")

    def test_the_file_lands_under_assets_videos(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "KakaoTalk_20260831_091607135.mp4"
            source.write_bytes(b"not really a movie, but bytes are bytes")
            manifest = root / "images.jsonl"
            manifest.write_text(
                json.dumps(
                    self.video_record("img-003098", "msg-003098", "2026-08-31T09:16+09:00"),
                    ensure_ascii=False,
                ) + "\n",
                encoding="utf-8",
            )

            result = import_image_files(manifest, [source], root)

            self.assertEqual(result["imported"], 1)
            row = json.loads(manifest.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(
                row["assets"][0]["local_path"],
                "assets/videos/2026-08/msg-003098-01.mp4",
            )
            self.assertTrue((root / "assets" / "videos" / "2026-08" / "msg-003098-01.mp4").is_file())

    def test_an_old_record_without_media_kind_is_read_from_its_asset_path(self):
        # 백필로 들어온 옛 줄에는 media_kind 칸이 없다. 이미 받아 둔 원본의 경로로
        # 되짚는다 — 그러지 않으면 옛 동영상이 사진 무리에 섞여 짝짓기가 흔들린다.
        old = record("img-002613", "msg-002613", "2026-03-18T13:16+09:00", 1)
        old["assets"] = [{"local_path": "assets/videos/2026-03/img-002613-01.mp4"}]
        files = [Path("KakaoTalk_20260318_131629111.mp4")]

        matches, unresolved = match_image_files([old], files)

        self.assertEqual([m.image_id for m in matches], ["img-002613"])
        self.assertEqual(unresolved, [])

