import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.collect_chat import generate_outputs


SAMPLE = """--------------- 2026년 7월 23일 목요일 ---------------
[A] [오전 9:00] 안녕하세요 https://example.com
[A] [오전 9:01] 사진
[B] [오전 9:02] 파일: 안내.pdf
[B] [오전 9:03] 이모티콘
"""


class CollectChatTests(unittest.TestCase):
    def test_generates_all_outputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "chat.txt"
            source.write_text(SAMPLE, encoding="utf-8")
            output = root / "output"
            counts = generate_outputs(source, output)

            messages = [
                json.loads(line)
                for line in (output / "messages.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            images = [
                json.loads(line)
                for line in (output / "images.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            participants = json.loads(
                (output / "participants.json").read_text(encoding="utf-8")
            )
            conversation_text = (output / "conversation.md").read_text(
                encoding="utf-8"
            )
            report_text = (output / "collection-report.md").read_text(
                encoding="utf-8"
            )

        self.assertEqual(counts["messages"], 3)
        self.assertEqual(counts["images"], 1)
        self.assertEqual(counts["files"], 1)
        self.assertEqual(messages[0]["nickname"], "A")
        self.assertEqual(messages[1]["kind"], "image")
        self.assertTrue(messages[2]["is_file_share"])
        self.assertEqual(images[0]["message_id"], "msg-000002")
        self.assertEqual(participants["participants"][0]["nickname"], "A")
        self.assertIn("사진 수집 대기: img-000002", conversation_text)
        self.assertIn("수집된 메시지: 3", report_text)

    def test_preserves_existing_download_state_when_regenerating(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "chat.txt"
            source.write_text(SAMPLE, encoding="utf-8")
            output = root / "output"
            generate_outputs(source, output)

            image_path = root / "assets" / "images" / "2026-07" / "msg-000002.jpg"
            image_path.parent.mkdir(parents=True)
            image_path.write_bytes(b"photo")
            record = json.loads(
                (output / "images.jsonl").read_text(encoding="utf-8").splitlines()[0]
            )
            record.update(
                {
                    "status": "downloaded",
                    "local_path": "assets/images/2026-07/msg-000002.jpg",
                    "original_filename": "photo.jpg",
                    "extension": ".jpg",
                    "byte_size": 5,
                    "sha256": "x" * 64,
                    "collected_at": "2026-07-23T22:00:00+09:00",
                }
            )
            (output / "images.jsonl").write_text(
                json.dumps(record, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            generate_outputs(source, output)
            regenerated = json.loads(
                (output / "images.jsonl").read_text(encoding="utf-8").splitlines()[0]
            )
            conversation_text = (output / "conversation.md").read_text(
                encoding="utf-8"
            )

        self.assertEqual(regenerated["status"], "downloaded")
        self.assertIn(
            "../assets/images/2026-07/msg-000002.jpg",
            conversation_text,
        )

    def test_renders_multiple_assets_for_one_image_message(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "chat.txt"
            source.write_text(SAMPLE, encoding="utf-8")
            output = root / "output"
            generate_outputs(source, output)

            record = json.loads(
                (output / "images.jsonl").read_text(encoding="utf-8").splitlines()[0]
            )
            record["status"] = "downloaded"
            record["assets"] = [
                {
                    "asset_id": "img-000001-01",
                    "local_path": "assets/images/2026-07/msg-000002-01.jpg",
                    "original_filename": "first.jpg",
                    "extension": ".jpg",
                    "byte_size": 5,
                    "sha256": "a" * 64,
                    "collected_at": "2026-07-23T22:00:00+09:00",
                },
                {
                    "asset_id": "img-000001-02",
                    "local_path": "assets/images/2026-07/msg-000002-02.png",
                    "original_filename": "second.png",
                    "extension": ".png",
                    "byte_size": 6,
                    "sha256": "b" * 64,
                    "collected_at": "2026-07-23T22:00:01+09:00",
                },
            ]
            (output / "images.jsonl").write_text(
                json.dumps(record, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            generate_outputs(source, output)
            conversation_text = (output / "conversation.md").read_text(
                encoding="utf-8"
            )

        self.assertIn("msg-000002-01.jpg", conversation_text)
        self.assertIn("msg-000002-02.png", conversation_text)

    def test_migrates_legacy_manifest_without_assets_to_empty_list(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "chat.txt"
            source.write_text(SAMPLE, encoding="utf-8")
            output = root / "output"
            generate_outputs(source, output)

            record = json.loads(
                (output / "images.jsonl").read_text(encoding="utf-8").splitlines()[0]
            )
            record.pop("assets")
            (output / "images.jsonl").write_text(
                json.dumps(record, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            generate_outputs(source, output)
            migrated = json.loads(
                (output / "images.jsonl").read_text(encoding="utf-8").splitlines()[0]
            )

        self.assertEqual(migrated["assets"], [])

    def test_migrates_legacy_image_id_by_stable_message_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "chat.txt"
            source.write_text(SAMPLE, encoding="utf-8")
            output = root / "output"
            generate_outputs(source, output)

            record = json.loads(
                (output / "images.jsonl").read_text(encoding="utf-8").splitlines()[0]
            )
            record.update(
                {
                    "image_id": "legacy-image-id",
                    "status": "downloaded",
                    "assets": [
                        {
                            "asset_id": "legacy-image-id-01",
                            "local_path": "assets/images/2026-07/msg-000002-01.png",
                            "original_filename": "photo.png",
                            "extension": ".png",
                            "byte_size": 5,
                            "sha256": "a" * 64,
                            "collected_at": "2026-07-23T22:00:00+09:00",
                        }
                    ],
                }
            )
            (output / "images.jsonl").write_text(
                json.dumps(record, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            generate_outputs(source, output)
            migrated = json.loads(
                (output / "images.jsonl").read_text(encoding="utf-8").splitlines()[0]
            )

        self.assertEqual(migrated["image_id"], "img-000002")
        self.assertEqual(migrated["status"], "downloaded")
        self.assertEqual(len(migrated["assets"]), 1)

    def test_migrates_incomplete_album_from_downloaded_to_partial(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "chat.txt"
            source.write_text(
                """--------------- 2026년 7월 23일 목요일 ---------------
[A] [오후 1:00] 사진 3장
""",
                encoding="utf-8",
            )
            output = root / "output"
            generate_outputs(source, output)

            record = json.loads(
                (output / "images.jsonl").read_text(encoding="utf-8").splitlines()[0]
            )
            record["status"] = "downloaded"
            record["assets"] = [
                {
                    "asset_id": "img-000001-01",
                    "local_path": "assets/images/2026-07/msg-000001-01.jpg",
                    "original_filename": "photo.jpg",
                    "extension": ".jpg",
                    "byte_size": 5,
                    "sha256": "a" * 64,
                    "collected_at": "2026-07-23T22:00:00+09:00",
                }
            ]
            (output / "images.jsonl").write_text(
                json.dumps(record, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            generate_outputs(source, output)
            migrated = json.loads(
                (output / "images.jsonl").read_text(encoding="utf-8").splitlines()[0]
            )
            conversation_text = (output / "conversation.md").read_text(
                encoding="utf-8"
            )

        self.assertEqual(migrated["status"], "partial")
        self.assertIn("사진 일부 수집: 1/3개", conversation_text)

    def test_reports_unique_downloaded_and_unresolved_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "chat.txt"
            source.write_text(SAMPLE, encoding="utf-8")
            output = root / "output"
            generate_outputs(source, output)
            downloaded = [
                {"download_id": "download-a", "status": "mapped"},
                {"download_id": "download-b", "status": "unresolved"},
            ]
            (output / "downloaded-files.jsonl").write_text(
                "".join(json.dumps(item) + "\n" for item in downloaded),
                encoding="utf-8",
            )

            generate_outputs(source, output)
            report_text = (output / "collection-report.md").read_text(
                encoding="utf-8"
            )

        self.assertIn("확보한 고유 사진 파일: 2", report_text)
        self.assertIn("대화와 자동 연결된 고유 사진: 1", report_text)
        self.assertIn("연결 보류 중인 고유 사진: 1", report_text)

    def test_missing_input_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "output"

            with self.assertRaises(FileNotFoundError):
                generate_outputs(root / "missing.txt", output)

            self.assertFalse(output.exists())

    def test_direct_script_invocation(self):
        project_root = Path(__file__).resolve().parents[1]
        script = project_root / "scripts" / "collect_chat.py"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "chat.txt"
            source.write_text(SAMPLE, encoding="utf-8")
            output = root / "output"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    str(source),
                    "--output",
                    str(output),
                ],
                cwd=project_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue((output / "messages.jsonl").is_file())


if __name__ == "__main__":
    unittest.main()
