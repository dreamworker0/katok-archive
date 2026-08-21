# -*- coding: utf-8 -*-
"""태그 거두기 — 거뒀다고 생각했는데 안 거둬진 상태를 막는다.

이 작업의 실패 방식은 둘이다.

  · 거둘 태그가 승격 표의 **부모**면, keywords 에서 떼도 승격이 다시 붙인다.
    화면에서는 그대로인데 md 에서는 사라진 상태 — 무엇이 참인지 알 수 없게 된다.
  · **자식**이면, 그 편이 부모에게 닿는 길을 잃는다. 넓은 입구에서 조용히 빠진다.

둘 다 시작 전에 멈춰야 한다. 그리고 떼기만 하면 태그 하나짜리 주제가 생기므로,
얇아지는 편은 골라내야 한다.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.retire_tag import guard_broader, targets, without

TAG = "링크 공유"

REPORTS = {
    "t-180": {"keywords": ["링크 공유", "구글 Opal"]},
    "t-240": {"keywords": ["링크 공유", "시사IN"]},
    "t-010": {"keywords": ["다위드 복지 허브", "앱 제작", "아카이빙", "링크공유"]},
    "t-900": {"keywords": ["클로드", "요금·비용"]},
}


class TargetsTest(unittest.TestCase):
    def test_finds_reports_that_carry_the_tag(self):
        self.assertEqual(["t-010", "t-180", "t-240"], targets(REPORTS, TAG))

    def test_spelling_differences_match(self):
        """'링크공유' 도 같은 태그다 — 하나만 거두면 나머지가 남는다."""
        self.assertIn("t-010", targets(REPORTS, TAG))

    def test_unrelated_reports_are_left_alone(self):
        self.assertNotIn("t-900", targets(REPORTS, TAG))


class WithoutTest(unittest.TestCase):
    def test_removes_every_spelling_and_keeps_order(self):
        self.assertEqual(["다위드 복지 허브", "앱 제작", "아카이빙"],
                         without(REPORTS["t-010"]["keywords"], TAG))

    def test_a_report_that_becomes_thin_is_visible_as_such(self):
        self.assertEqual(["구글 Opal"], without(REPORTS["t-180"]["keywords"], TAG))

    def test_removing_a_tag_that_is_not_there_changes_nothing(self):
        self.assertEqual(["클로드", "요금·비용"],
                         without(REPORTS["t-900"]["keywords"], TAG))


class GuardBroaderTest(unittest.TestCase):
    def write(self, data) -> Path:
        p = Path(tempfile.mkdtemp()) / "tag_broader.json"
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return p

    def test_a_tag_tangled_in_no_table_may_be_retired(self):
        p = self.write({"broader": {"AI 모델": ["클로드"]}, "short_parents": ["구글"]})
        guard_broader(TAG, p)   # 예외가 없으면 통과다

    def test_a_parent_stops_the_run(self):
        """부모를 거두면 승격이 다시 붙인다 — md 와 화면이 어긋난다."""
        p = self.write({"broader": {TAG: ["페이스북 공유"]}})
        with self.assertRaises(SystemExit) as e:
            guard_broader(TAG, p)
        self.assertIn("부모", str(e.exception))

    def test_a_child_stops_the_run(self):
        """자식을 거두면 그 편이 넓은 입구에서 조용히 빠진다."""
        p = self.write({"broader": {"자료 공유": ["링크 공유", "사진 공유"]}})
        with self.assertRaises(SystemExit) as e:
            guard_broader(TAG, p)
        self.assertIn("자식", str(e.exception))

    def test_a_short_parent_stops_the_run(self):
        p = self.write({"broader": {}, "short_parents": ["링크 공유"]})
        with self.assertRaises(SystemExit):
            guard_broader(TAG, p)

    def test_spelling_differences_are_caught_too(self):
        p = self.write({"broader": {"링크공유": ["페이스북 공유"]}})
        with self.assertRaises(SystemExit):
            guard_broader(TAG, p)


class TheRealTableStillAllowsWhatWeRetiredTest(unittest.TestCase):
    """실제 표를 본다 — 거둔 태그가 나중에 표로 되살아나면 안 된다."""

    def test_retired_act_tags_are_not_in_the_table(self):
        p = Path(__file__).resolve().parent.parent / "config" / "tag_broader.json"
        guard_broader("링크 공유", p)


if __name__ == "__main__":
    unittest.main()
