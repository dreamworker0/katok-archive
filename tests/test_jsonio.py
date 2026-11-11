# -*- coding: utf-8 -*-
"""공용 JSON 쓰기는 '옛 파일 아니면 새 파일' 둘 중 하나만 남긴다.

대상 파일을 바로 열어 쓰면 여는 순간 비워져, 그 사이 갱신이 끊기면 원장이 반쯤
잘린 채 남는다. 임시 파일에 다 쓰고 바꿔 끼우는지, 그리고 바꾸면서 바이트가
예전과 달라지지 않았는지(git diff·write_json_if_changed 가 기대는 것) 본다.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts import jsonio  # noqa: E402


class AtomicWriteTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_bytes_match_plain_text_mode_write(self):
        data = {"가": [1, 2], "b": "줄\n바꿈"}
        jsonio.write_json(self.dir / "a.json", data)
        (self.dir / "old.json").write_text(jsonio._text(data, 2), encoding="utf-8")
        self.assertEqual((self.dir / "a.json").read_bytes(), (self.dir / "old.json").read_bytes())

        rows = [{"id": 1, "t": "한글"}, {"id": 2}]
        jsonio.write_jsonl(self.dir / "b.jsonl", rows)
        with (self.dir / "old.jsonl").open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        self.assertEqual((self.dir / "b.jsonl").read_bytes(), (self.dir / "old.jsonl").read_bytes())
        self.assertEqual(jsonio.read_jsonl(self.dir / "b.jsonl"), rows)

    def test_failure_mid_write_keeps_the_old_file(self):
        target = self.dir / "m.jsonl"
        jsonio.write_jsonl(target, [{"id": 1}])
        before = target.read_bytes()

        def rows():
            yield {"id": 2}
            raise RuntimeError("쓰다가 끊김")

        with self.assertRaises(RuntimeError):
            jsonio.write_jsonl(target, rows())
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(list(self.dir.glob("*.tmp")), [])

    def test_unchanged_content_is_not_rewritten(self):
        target = self.dir / "k.json"
        self.assertTrue(jsonio.write_json_if_changed(target, {"a": 1}))
        with mock.patch.object(jsonio, "_atomic_write") as w:
            self.assertFalse(jsonio.write_json_if_changed(target, {"a": 1}))
            w.assert_not_called()

    def test_locked_target_is_retried(self):
        target = self.dir / "r.json"
        real = os.replace
        calls = []

        def flaky(src, dst):
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError("다른 프로그램이 쥐고 있음")
            return real(src, dst)

        with mock.patch.object(jsonio.os, "replace", side_effect=flaky), \
                mock.patch.object(jsonio.time, "sleep"):
            jsonio.write_json(target, {"ok": True})
        self.assertEqual(jsonio.read_json(target), {"ok": True})
        self.assertEqual(len(calls), 3)
        self.assertEqual(list(self.dir.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
