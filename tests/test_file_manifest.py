# -*- coding: utf-8 -*-
"""첨부 파일 ↔ 메시지 연결.

이름이 조금이라도 다르면 붙이지 않는다. 엉뚱한 파일을 남의 메시지에 붙이는 것이
못 붙이는 것보다 나쁘다.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import build_file_manifest as bfm  # noqa: E402


def share(mid: str, filename: str, nickname: str = "홍길동"):
    return {"id": mid, "kind": "file", "text": "파일: " + filename,
            "nickname": nickname, "date": "2026-07-16"}


class FilenameTest(unittest.TestCase):
    def test_strips_prefix(self):
        self.assertEqual(bfm.filename_of(share("msg-000001", "보고서.pdf")), "보고서.pdf")

    def test_keeps_spaces_and_brackets(self):
        name = "[잇다] BEːPEOPLE_앱2차.pdf"
        self.assertEqual(bfm.filename_of(share("msg-000001", name)), name)


class MatchTest(unittest.TestCase):
    def _build(self, messages, local_names):
        fake = {}
        for n in local_names:
            m = mock.Mock()
            m.stat.return_value = mock.Mock(st_size=1234)
            fake[n] = m
        with mock.patch.object(bfm, "collect_local_files", return_value=fake), \
             mock.patch.object(bfm, "sha256_of", return_value="deadbeef"):
            return bfm.build_manifest(messages)

    def test_exact_name_matches(self):
        out = self._build([share("msg-000010", "보고서.pdf")], ["보고서.pdf"])
        self.assertEqual(len(out["rows"]), 1)
        self.assertEqual(out["rows"][0]["message_id"], "msg-000010")
        self.assertEqual(out["rows"][0]["local_path"], "assets/files/보고서.pdf")
        self.assertEqual(out["rows"][0]["file_id"], "file-000010")

    def test_near_miss_does_not_match(self):
        """'보고서 (1).pdf' 를 '보고서.pdf' 에 붙이면 안 된다."""
        out = self._build([share("msg-000010", "보고서.pdf")], ["보고서 (1).pdf"])
        self.assertEqual(out["rows"], [])
        self.assertEqual(out["missing"], ["보고서.pdf"])
        self.assertEqual(out["unused"], ["보고서 (1).pdf"])

    def test_same_name_twice_is_flagged(self):
        """같은 이름을 두 번 올렸으면 서로 다른 판본일 수 있다 — 붙이되 알린다."""
        out = self._build(
            [share("msg-000010", "mindmap.html"), share("msg-000020", "mindmap.html")],
            ["mindmap.html"])
        self.assertEqual(len(out["rows"]), 2)
        self.assertEqual(out["ambiguous"], ["mindmap.html"])

    def test_non_file_messages_ignored(self):
        msgs = [{"id": "msg-000001", "kind": "text", "text": "보고서.pdf",
                 "nickname": "홍길동", "date": "2026-07-16"}]
        out = self._build(msgs, ["보고서.pdf"])
        self.assertEqual(out["rows"], [])
        self.assertEqual(out["unused"], ["보고서.pdf"])


class ContentTypeTest(unittest.TestCase):
    def test_known_extensions(self):
        self.assertEqual(bfm.content_type_for("a.pdf"), "application/pdf")
        self.assertEqual(bfm.content_type_for("A.ZIP"), "application/zip")

    def test_unknown_extension_is_octet_stream(self):
        self.assertEqual(bfm.content_type_for("a.xyz"), "application/octet-stream")


if __name__ == "__main__":
    unittest.main()
