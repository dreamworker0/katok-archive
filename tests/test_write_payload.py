# -*- coding: utf-8 -*-
"""발행본 폴더는 한 번에 바꿔 끼운다. (2026-11-11 외부 평가 지적)

예전에는 폴더를 지우고 파일을 하나씩 써서, 그 몇 초 사이 상주하는 질문 처리기
(ask_worker.js)가 읽으면 파일이 없거나 반쯤이었다. 옆 폴더에 다 쓴 뒤 이름만 바꾼다.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts import build_firestore_payload as b  # noqa: E402

KEYS = ("meta", "threads", "ai_reports", "media", "my_messages", "digests", "graph",
        "members", "images", "files", "exclusion_report")


def fake_payload(tag: str) -> dict:
    return {k: {"tag": tag} for k in KEYS}


class WritePayloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name) / "firestore-payload"
        p = mock.patch.object(b, "PAYLOAD", self.dir)
        p.start()
        self.addCleanup(p.stop)

    def siblings(self):
        return sorted(x.name for x in self.dir.parent.iterdir())

    def test_first_write_creates_the_folder(self):
        b.write_payload(fake_payload("1"))
        meta = json.loads((self.dir / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta, {"tag": "1"})
        self.assertEqual(self.siblings(), ["firestore-payload"])

    def test_rewrite_replaces_whole_folder_and_leaves_no_staging(self):
        b.write_payload(fake_payload("1"))
        (self.dir / "stale.json").write_text("{}", encoding="utf-8")   # 지난 판에만 있던 것
        b.write_payload(fake_payload("2"))
        meta = json.loads((self.dir / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta, {"tag": "2"})
        self.assertFalse((self.dir / "stale.json").exists())
        self.assertEqual(self.siblings(), ["firestore-payload"])

    def test_leftovers_from_an_interrupted_run_are_cleared(self):
        for name in ("firestore-payload.new", "firestore-payload.old"):
            (self.dir.parent / name).mkdir()
            (self.dir.parent / name / "junk.json").write_text("{}", encoding="utf-8")
        b.write_payload(fake_payload("3"))
        self.assertEqual(self.siblings(), ["firestore-payload"])

    def test_staging_folders_are_git_ignored(self):
        gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("/firestore-payload.new/", gi)
        self.assertIn("/firestore-payload.old/", gi)


if __name__ == "__main__":
    unittest.main()
