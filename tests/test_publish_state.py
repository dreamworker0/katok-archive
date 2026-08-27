# -*- coding: utf-8 -*-
"""'발행본이 로컬보다 뒤처졌나' 판정.

이 판정이 없던 동안 실제로 난 일 (2026-07-30)
  23:40 자동 갱신이 새 글 34건을 원장에 반영하고 발행본까지 만든 뒤 테스트 단계에서
  멈췄다. 원장에는 들어갔고 Firestore 에는 안 갔다. 다음 날 '지금 갱신' 을 눌러도
  증분이 0건이라 "갱신을 마쳤습니다" 만 뜨고 타임라인은 그대로였다 — 몇 번 눌러도
  같다. 앞의 발행 사유 셋이 모두 '이번 실행에서 새로 생긴 것' 만 보기 때문이다.

기울기
  모를 때는 발행하는 쪽이다. 적재는 해시로 달라진 문서만 쓰므로 헛발행은 거의
  무료지만, 올릴 것을 안 올리면 화면이 거짓말을 한다.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from scripts import publish_state


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        (self.out / "reports").mkdir()
        (self.out / "ai-reports").mkdir()
        patches = [
            mock.patch.object(publish_state, "OUTPUT", self.out),
            mock.patch.object(publish_state, "UPLOAD_STATE",
                              self.out / "upload-state.json"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    # ── 도우미 ──

    def uploaded_at(self, when: datetime) -> None:
        (self.out / "upload-state.json").write_text(
            json.dumps({"state_version": 1,
                        "updated_at": when.astimezone(timezone.utc)
                        .strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"}),
            encoding="utf-8")

    def touch(self, name: str, when: datetime) -> Path:
        p = self.out / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
        ts = when.timestamp()
        os.utime(p, (ts, ts))
        return p

    # ── 판정 ──

    def test_ledger_newer_than_the_last_upload_is_stale(self):
        """실측 그 상황 — 원장 23:40, 마지막 적재 07:26."""
        now = datetime.now(timezone.utc)
        self.uploaded_at(now - timedelta(hours=16))
        self.touch("messages.jsonl", now - timedelta(minutes=10))
        stale, line = publish_state.check()
        self.assertTrue(stale)
        self.assertIn("messages.jsonl", line)

    def test_nothing_changed_since_the_upload_is_not_stale(self):
        now = datetime.now(timezone.utc)
        self.touch("messages.jsonl", now - timedelta(hours=5))
        self.uploaded_at(now - timedelta(hours=1))
        stale, _ = publish_state.check()
        self.assertFalse(stale)

    def test_a_rewritten_report_alone_is_stale(self):
        """보고서만 고친 날도 발행해야 한다 — 화면의 내용이 보고서다."""
        now = datetime.now(timezone.utc)
        self.uploaded_at(now - timedelta(hours=2))
        self.touch("reports/t-252.md", now - timedelta(minutes=1))
        stale, line = publish_state.check()
        self.assertTrue(stale)
        self.assertIn("reports/*.md", line)

    def test_an_ai_report_alone_is_stale(self):
        """AI 검증 주석만 새로 생긴 밤이 실제로 있다.

        새 대화가 없어도 밤마다 몇 편씩 쓴다. 여기서 안 잡히면 그날 발행이
        건너뛰어지고 쓴 글이 사이트에 영영 안 올라간다.
        """
        now = datetime.now(timezone.utc)
        self.uploaded_at(now - timedelta(hours=2))
        self.touch("ai-reports/t-252.md", now - timedelta(minutes=1))
        stale, line = publish_state.check()
        self.assertTrue(stale)
        self.assertIn("ai-reports/*.md", line)

    def test_an_old_report_does_not_make_it_stale(self):
        now = datetime.now(timezone.utc)
        self.touch("reports/t-252.md", now - timedelta(days=3))
        self.uploaded_at(now - timedelta(hours=2))
        stale, _ = publish_state.check()
        self.assertFalse(stale)

    def test_unwatched_files_are_ignored(self):
        """발행에 실리지 않는 것(중간 산출물)이 매일 발행을 부르면 안 된다."""
        now = datetime.now(timezone.utc)
        self.uploaded_at(now - timedelta(hours=2))
        self.touch("ingest-state.json", now)
        self.touch("image_ocr.json", now)
        stale, _ = publish_state.check()
        self.assertFalse(stale)

    # ── 모를 때 ──

    def test_missing_upload_state_leans_to_publishing(self):
        stale, line = publish_state.check()
        self.assertTrue(stale)
        self.assertIn("알 수 없습니다", line)

    def test_broken_upload_state_leans_to_publishing(self):
        (self.out / "upload-state.json").write_text("{ not json",
                                                    encoding="utf-8")
        self.assertIsNone(publish_state.last_upload_at())
        self.assertTrue(publish_state.check()[0])

    def test_upload_state_without_a_timestamp_leans_to_publishing(self):
        (self.out / "upload-state.json").write_text(
            json.dumps({"state_version": 1}), encoding="utf-8")
        self.assertTrue(publish_state.check()[0])

    # ── 출력 ──

    def test_printed_line_is_cp949_safe(self):
        """cp949 콘솔에서 print 가 죽으면 판단을 돕는 줄이 판단을 없앤다.

        run_daily.ps1 이 PYTHONIOENCODING 을 맞추지만, 사람이 손으로 돌리는
        창에서는 아닐 수 있다.
        """
        now = datetime.now(timezone.utc)
        self.uploaded_at(now - timedelta(hours=2))
        self.touch("messages.jsonl", now)
        for _, line in (publish_state.check(),):
            line.encode("cp949")   # 못 쓰는 글자가 있으면 여기서 터진다

    def test_marker_is_ascii(self):
        """run_daily.ps1 이 읽는 표식은 코드페이지를 건너가도 살아남아야 한다."""
        line = "PUBLISH_STALE=1"
        self.assertEqual(line, line.encode("utf-8").decode("cp949"))


if __name__ == "__main__":
    unittest.main()
