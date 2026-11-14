# -*- coding: utf-8 -*-
"""첨부 대조 — 대화에 올라온 첨부가 아카이브에 들어왔는가.

이 점검은 첨부를 잃는 드문 날에만 의미 있게 돈다. 잘못 고쳐도 평소에는 아무 일도
없어 보이고, 정작 잃는 날 조용하다. 반대로 매일 같은 것을 외치면 다시 읽지 않는
경고가 된다 — 서랍 팝업의 '실패' 가 그랬다.
"""
from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import audit_attachments as aa  # noqa: E402


def file_msg(mid, name, day):
    return {"id": mid, "kind": "file", "text": "파일: " + name, "date": day}


def photo_msg(mid, day, kind="image"):
    return {"id": mid, "kind": kind, "text": "사진", "date": day}


TODAY = date(2026, 11, 1)


class AuditTest(unittest.TestCase):
    def test_received_attachments_are_not_reported(self):
        msgs = [file_msg("msg-1", "a.pdf", "2026-10-25"), photo_msg("msg-2", "2026-10-25")]
        images = [{"message_id": "msg-2", "status": "downloaded"}]
        r = aa.audit(msgs, set(), images, TODAY)
        self.assertEqual([], r["lost"] + r["urgent"] + r["waiting"])

    def test_missing_with_time_left_is_waiting(self):
        r = aa.audit([file_msg("msg-1", "a.pdf", "2026-10-30")], {"a.pdf"}, [], TODAY)
        self.assertEqual(["msg-1"], [x["id"] for x in r["waiting"]])
        self.assertEqual(12, r["waiting"][0]["days_left"])

    def test_close_to_expiry_is_urgent(self):
        # 공유 10-21 → 만료 11-04 → 11-01 에 3일 남음
        r = aa.audit([file_msg("msg-1", "a.pdf", "2026-10-21")], {"a.pdf"}, [], TODAY)
        self.assertEqual(["msg-1"], [x["id"] for x in r["urgent"]])

    def test_expiry_day_itself_is_already_lost(self):
        """유효기간 날짜에 닿으면 이미 못 받는다(실측 2026-08-20)."""
        r = aa.audit([file_msg("msg-1", "a.pdf", "2026-10-18")], {"a.pdf"}, [], TODAY)
        self.assertEqual(["msg-1"], [x["id"] for x in r["lost"]])
        self.assertEqual(["msg-1"], [x["id"] for x in r["fresh_lost"]])

    def test_old_losses_are_counted_but_not_shouted_again(self):
        r = aa.audit([file_msg("msg-1", "a.pdf", "2026-09-01")], {"a.pdf"}, [], TODAY)
        self.assertEqual(1, len(r["lost"]))
        self.assertEqual([], r["fresh_lost"])

    def test_photo_not_downloaded_is_missing(self):
        msgs = [photo_msg("msg-1", "2026-10-30"), photo_msg("msg-2", "2026-10-30", "video")]
        images = [{"message_id": "msg-1", "status": "pending"}]
        r = aa.audit(msgs, set(), images, TODAY)
        self.assertEqual({"msg-1", "msg-2"}, {x["id"] for x in r["waiting"]})

    def test_before_automation_is_ignored(self):
        """서랍 자동 수집 전에 빠진 것은 다시 받을 길이 없다 — 매일 읽게 할 뿐이다."""
        msgs = [file_msg("msg-1", "a.pdf", "2026-08-06"), photo_msg("msg-2", "2026-07-29")]
        r = aa.audit(msgs, {"a.pdf"}, [], TODAY)
        self.assertEqual([], r["lost"] + r["urgent"] + r["waiting"])

    def test_missing_for_more_than_a_day_is_stuck(self):
        """받을 수 있는데 하루 넘게 못 받으면 서랍이 막힌 것 — 2026-11-15 이것 없이 13일을 보냈다."""
        r = aa.audit([file_msg("msg-1", "a.pdf", "2026-10-30")], {"a.pdf"}, [], TODAY)
        self.assertEqual(["msg-1"], [x["id"] for x in r["stuck"]])
        self.assertEqual(2, r["stuck"][0]["age"])

    def test_shared_today_is_not_stuck_yet(self):
        r = aa.audit([file_msg("msg-1", "a.pdf", "2026-11-01")], {"a.pdf"}, [], TODAY)
        self.assertEqual([], r["stuck"])
        self.assertEqual(["msg-1"], [x["id"] for x in r["waiting"]])

    def test_urgent_is_not_also_stuck(self):
        """곧 만료는 이미 따로 외친다 — 같은 것을 두 번 세지 않는다."""
        r = aa.audit([file_msg("msg-1", "a.pdf", "2026-10-21")], {"a.pdf"}, [], TODAY)
        self.assertEqual([], r["stuck"])

    def test_text_messages_are_ignored(self):
        r = aa.audit([{"id": "msg-1", "kind": "text", "text": "파일: x", "date": "2026-10-30"}],
                     {"x"}, [], TODAY)
        self.assertEqual([], r["waiting"])


class ReportTest(unittest.TestCase):
    def test_urgent_and_fresh_loss_are_warnings_with_a_next_step(self):
        msgs = [file_msg("msg-1", "a.pdf", "2026-10-21"), file_msg("msg-2", "b.pdf", "2026-10-18")]
        lines = aa.report(aa.audit(msgs, {"a.pdf", "b.pdf"}, [], TODAY), before=0)
        warns = [line for level, line in lines if level == "WARN"]
        self.assertTrue(any("곧 만료" in w and "a.pdf" in w for w in warns))
        self.assertTrue(any("잃음" in w and "b.pdf" in w for w in warns))
        self.assertTrue(any("서랍" in w for w in warns))

    def test_stuck_is_a_warning_that_points_at_the_drawer_log(self):
        msgs = [file_msg("msg-1", "a.pdf", "2026-10-30")]
        lines = aa.report(aa.audit(msgs, {"a.pdf"}, [], TODAY), before=0)
        warns = [line for level, line in lines if level == "WARN"]
        self.assertTrue(any("2일째 못 받음" in w and "a.pdf" in w for w in warns))
        self.assertTrue(any("kakao-drawer" in w for w in warns))

    def test_many_stuck_are_capped(self):
        msgs = [photo_msg("msg-%d" % i, "2026-10-28") for i in range(25)]
        lines = aa.report(aa.audit(msgs, set(), [], TODAY), before=0)
        per_item = [line for _, line in lines if "일째 못 받음" in line]
        self.assertEqual(aa.STUCK_LINES, len(per_item))
        self.assertTrue(any("15건 더" in line for _, line in lines))

    def test_quiet_day_is_one_info_line(self):
        lines = aa.report(aa.audit([], set(), [], TODAY), before=41)
        self.assertEqual(["INFO"], [level for level, _ in lines])
        self.assertIn("41건", lines[0][1])


class RunnerWiringTest(unittest.TestCase):
    """밤 갱신이 대조를 돌리고, 표식을 읽어 사람에게 올리는지."""

    PS1 = (Path(__file__).resolve().parent.parent / "scripts" / "run_daily.ps1").read_text(encoding="utf-8-sig")

    def test_runs_after_the_drawer_even_when_it_failed(self):
        drawer = self.PS1.index("scripts\\kakao_drawer.ps1")
        audit = self.PS1.index("python -m scripts.audit_attachments")
        self.assertLess(drawer, audit)
        # 서랍 성공 분기(else) 안이 아니라 그 뒤에 있어야 한다
        between = self.PS1[drawer:audit]
        self.assertIn("finally { $ErrorActionPreference = $prevEap }", between)

    def test_markers_reach_the_admin_tab_and_discord(self):
        block = self.PS1[self.PS1.index("python -m scripts.audit_attachments"):]
        block = block[:block.index("finally {")]
        self.assertIn("ATTACH_URGENT", block)
        self.assertIn("ATTACH_LOST", block)
        self.assertIn("ATTACH_STUCK", block)
        self.assertIn("$attachStuck -gt 0", block)
        self.assertIn("$script:drawerWarn", block)
        self.assertIn("scripts\\notify.js", block)

    def test_quiet_days_still_show_drawer_warnings(self):
        skip = self.PS1[self.PS1.index("Report-Run -status 'skipped'") - 300:]
        self.assertIn("drawerWarn", skip[:400])


if __name__ == "__main__":
    unittest.main()
