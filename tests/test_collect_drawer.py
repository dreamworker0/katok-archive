# -*- coding: utf-8 -*-
"""서랍에서 받은 문서를 assets/files/ 에 놓을 때의 중복 판정.

카톡은 같은 것을 또 저장하면 'name (1).pdf' 로 떨군다. 그 표시는 저장할 때 이름이
겹쳐서 붙은 것이지 다른 파일이라는 뜻이 아니다. 두 벌이 들어가면 자료 목록에 같은
파일이 두 번 뜬다.

실측 2026-08-25: 한 묶음에 'AI 리더십 2026-0819 (1).pdf' 와 'AI 리더십 2026-0819.pdf'
가 같이 들어왔고(227391 bytes, 같은 해시) 둘 다 아카이브에 쌓였다. 정렬하면 표시
붙은 쪽이 앞서기 때문이다 — 공백(0x20) 이 마침표(0x2E) 보다 작다.
"""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from scripts import collect_drawer


class PlaceDocumentsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = Path(tempfile.mkdtemp())
        self._incoming = self._tmp / "incoming"
        self._incoming.mkdir()
        self._files = self._tmp / "files"
        self._files.mkdir()
        self._saved = collect_drawer.FILES_DIR
        collect_drawer.FILES_DIR = self._files

    def tearDown(self):
        collect_drawer.FILES_DIR = self._saved
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _incoming_file(self, name: str, body: bytes):
        p = self._incoming / name
        p.write_bytes(body)
        return (p, name)

    def _placed(self) -> list[str]:
        return sorted(p.name for p in self._files.iterdir())

    def test_marked_and_plain_in_one_batch_land_once(self):
        """한 묶음에 둘 다 와도 한 벌만 남는다 — 표시 붙은 쪽이 먼저 처리돼도."""
        body = b"%PDF-1.4 same bytes"
        items = [
            self._incoming_file("보고서 (1).pdf", body),
            self._incoming_file("보고서.pdf", body),
        ]
        # 실제 순서 그대로 — sorted() 하면 '보고서 (1).pdf' 가 앞선다
        self.assertEqual(sorted(n for _, n in items)[0], "보고서 (1).pdf")

        added, existing = collect_drawer.place_documents(items, dry_run=False)

        self.assertEqual(self._placed(), ["보고서.pdf"])
        self.assertEqual((added, existing), (1, 1))

    def test_plain_first_also_lands_once(self):
        """순서가 반대여도 결과는 같아야 한다."""
        body = b"%PDF-1.4 same bytes"
        items = [
            self._incoming_file("보고서.pdf", body),
            self._incoming_file("보고서 (1).pdf", body),
        ]
        added, existing = collect_drawer.place_documents(items, dry_run=False)

        self.assertEqual(self._placed(), ["보고서.pdf"])
        self.assertEqual((added, existing), (1, 1))

    def test_marked_alone_loses_the_marker(self):
        """표시 붙은 것만 왔으면 표시를 떼고 놓는다 — 대장이 짝을 찾을 수 있게."""
        items = [self._incoming_file("자료 (2).hwpx", b"hwpx bytes")]
        added, _ = collect_drawer.place_documents(items, dry_run=False)

        self.assertEqual(self._placed(), ["자료.hwpx"])
        self.assertEqual(added, 1)

    def test_same_content_already_in_archive_is_not_added_again(self):
        (self._files / "보고서.pdf").write_bytes(b"same")
        items = [self._incoming_file("보고서 (1).pdf", b"same")]

        added, existing = collect_drawer.place_documents(items, dry_run=False)

        self.assertEqual(self._placed(), ["보고서.pdf"])
        self.assertEqual((added, existing), (0, 1))

    def test_same_name_different_content_is_kept_not_overwritten(self):
        """이름만 같고 내용이 다르면 진짜 다른 파일이다 — 덮어쓰지 않는다."""
        (self._files / "보고서.pdf").write_bytes(b"old version")
        items = [self._incoming_file("보고서 (1).pdf", b"new version")]

        added, existing = collect_drawer.place_documents(items, dry_run=False)

        self.assertEqual(self._placed(), ["보고서 (1).pdf", "보고서.pdf"])
        self.assertEqual((added, existing), (1, 0))
        self.assertEqual((self._files / "보고서.pdf").read_bytes(), b"old version")

    def test_third_distinct_version_goes_beside_the_others(self):
        """두 이름이 다 찼는데 또 다른 판본이면 옆에 둔다(stash 와 같은 규칙)."""
        (self._files / "보고서.pdf").write_bytes(b"v1")
        (self._files / "보고서 (1).pdf").write_bytes(b"v2")
        items = [self._incoming_file("보고서 (1).pdf", b"v3")]

        added, _ = collect_drawer.place_documents(items, dry_run=False)

        self.assertIn("보고서 (1)~2.pdf", self._placed())
        self.assertEqual(added, 1)

    def test_dry_run_writes_nothing(self):
        body = b"%PDF-1.4"
        items = [
            self._incoming_file("보고서 (1).pdf", body),
            self._incoming_file("보고서.pdf", body),
        ]
        added, existing = collect_drawer.place_documents(items, dry_run=True)

        self.assertEqual(self._placed(), [])
        self.assertEqual((added, existing), (1, 1))


if __name__ == "__main__":
    unittest.main()
