# -*- coding: utf-8 -*-
"""넓은 태그 가르기 — 가른 것이 넓은 입구에서 사라지지 않는지.

이 작업의 실패 방식은 하나다. 갈래를 넣었는데 그 갈래가 `broader` 의 자식이
아니면, 넓은 태그가 그 편을 되찾지 못해 **갈라낸 편이 넓은 입구에서 없어진다.**
가르는 것이 아니라 잃는 것이다. 그래서 여기서 두 가지를 묶어 둔다.

  · 갈래가 `broader` 에 없으면 아예 시작하지 않는다
  · 목록에 없는 갈래로 답이 오면 그 편을 손대지 않는다
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts import tags as taglib
from scripts.split_tag import (
    NONE,
    facet_keys,
    fill_targets,
    load_kinds,
    screen,
    screen_fill,
    targets,
)

TAG = "앱 제작"
KINDS = {"업무 앱": "실무자 업무", "게임": "놀이", "실천 도구": "실천에 쓰는 것"}

REPORTS = {
    "t-014": {"title": "차량운행일지", "summary": "요", "report": "본문",
              "keywords": ["차량운행일지", TAG, "한컴한글"]},
    "t-251": {"title": "아기하마 게임", "summary": "요", "report": "본문",
              "keywords": [TAG, "아기하마 게임"]},
    "t-255": {"title": "월급계산기", "summary": "요", "report": "본문",
              "keywords": ["월급계산기", "사회복지사", TAG]},
    "t-900": {"title": "앱 이야기 아님", "summary": "요", "report": "본문",
              "keywords": ["클로드", "요금·비용"]},
}


class TargetsTest(unittest.TestCase):
    def test_only_reports_that_carry_the_tag_themselves(self):
        """승격으로 얻은 태그는 md 에 없다 — 대상이 아니다."""
        self.assertEqual(["t-014", "t-251", "t-255"], targets(REPORTS, TAG))

    def test_spelling_differences_still_match(self):
        reports = {"t-1": {"keywords": ["앱제작"]}, "t-2": {"keywords": ["앱 제작"]}}
        self.assertEqual(["t-1", "t-2"], targets(reports, "앱 제작"))

    def test_no_match_is_empty(self):
        self.assertEqual([], targets(REPORTS, "없는 태그"))


class LoadKindsTest(unittest.TestCase):
    def write(self, data) -> Path:
        d = Path(tempfile.mkdtemp())
        p = d / "tag_broader.json"
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return p

    def test_kinds_and_hints_come_from_the_table(self):
        p = self.write({"broader": {TAG: ["업무 앱", "게임"]},
                        "split_hints": {TAG: {"업무 앱": "실무자 업무"}}})
        got = load_kinds(TAG, p)
        self.assertEqual(["업무 앱", "게임"], list(got))
        self.assertEqual("실무자 업무", got["업무 앱"])
        self.assertEqual("", got["게임"], "설명이 없으면 빈 문자열이지 오류가 아니다")

    def test_a_tag_with_no_children_stops_the_run(self):
        """자식이 없으면 갈라내도 넓은 태그가 되찾지 못한다 — 시작하지 않는다."""
        p = self.write({"broader": {"다른 태그": ["가"]}})
        with self.assertRaises(SystemExit):
            load_kinds(TAG, p)

    def test_empty_child_names_do_not_count(self):
        p = self.write({"broader": {TAG: ["", "  "]}})
        with self.assertRaises(SystemExit):
            load_kinds(TAG, p)


class ScreenTest(unittest.TestCase):
    def test_the_kind_takes_the_broad_tags_place(self):
        """순서에는 사람이 쓴 무게가 담겨 있다 — 뒤로 밀면 뜻이 흐려진다."""
        got = screen(REPORTS, {"t-014": "업무 앱"}, TAG, KINDS)
        self.assertEqual(["차량운행일지", "업무 앱", "한컴한글"], got["t-014"]["after"])
        self.assertEqual("업무 앱", got["t-014"]["kind"])

    def test_other_tags_are_untouched(self):
        got = screen(REPORTS, {"t-255": "실천 도구"}, TAG, KINDS)
        self.assertEqual(["월급계산기", "사회복지사", "실천 도구"], got["t-255"]["after"])

    def test_a_kind_outside_the_list_is_refused(self):
        got = screen(REPORTS, {"t-014": "복지 앱"}, TAG, KINDS)
        self.assertEqual({}, got, "목록 밖 갈래는 broader 의 자식이 아니다")

    def test_none_leaves_the_broad_tag_alone(self):
        got = screen(REPORTS, {"t-014": NONE, "t-251": ""}, TAG, KINDS)
        self.assertEqual({}, got)

    def test_spelling_of_the_answer_is_normalised(self):
        got = screen(REPORTS, {"t-251": " 게임 "}, TAG, KINDS)
        self.assertEqual("게임", got["t-251"]["kind"])
        self.assertEqual(["게임", "아기하마 게임"], got["t-251"]["after"])

    def test_a_kind_already_present_does_not_double(self):
        reports = {"t-1": {"keywords": ["게임", TAG]}}
        got = screen(reports, {"t-1": "게임"}, TAG, KINDS)
        self.assertEqual(["게임"], got["t-1"]["after"])

    def test_every_answered_report_keeps_its_tag_count_or_loses_only_the_duplicate(self):
        got = screen(REPORTS, {"t-014": "업무 앱", "t-251": "게임",
                               "t-255": "실천 도구"}, TAG, KINDS)
        self.assertEqual(3, len(got))
        for tid, change in got.items():
            self.assertEqual(len(REPORTS[tid]["keywords"]), len(change["after"]))
            self.assertNotIn(TAG, change["after"])


class FillTest(unittest.TestCase):
    """갈래를 **채우는** 쪽. 가르는 쪽과 반대로, 갈래가 없는 주제를 찾아 붙인다."""

    BROADER = {
        "broader": {
            "앱 제작": ["업무 앱", "게임 제작", "실천 도구", "C#", "파워앱스"],
            "실천 도구": ["월급계산기"],
        },
        "split_hints": {"앱 제작": {"업무 앱": "실무자 업무", "게임 제작": "놀이",
                                 "실천 도구": "실천에 쓰는 것"}},
    }

    def table(self) -> Path:
        d = Path(tempfile.mkdtemp())
        p = d / "tag_broader.json"
        p.write_text(json.dumps(self.BROADER, ensure_ascii=False), encoding="utf-8")
        return p

    def test_only_kinds_with_a_hint_count_as_facets(self):
        """'C#'·'파워앱스' 는 자식이지만 갈래가 아니다 — 결과물·도구 이름이다."""
        got = load_kinds("앱 제작", self.table(), hinted_only=True)
        self.assertEqual(["업무 앱", "게임 제작", "실천 도구"], list(got))

    def test_a_facet_owns_its_grandchildren(self):
        keys = facet_keys("앱 제작", ["실천 도구"], self.table())
        self.assertIn(taglib.fold("월급계산기"), keys["실천 도구"])

    def test_threads_that_already_have_a_facet_are_not_targets(self):
        reports = {
            "t-1": {"keywords": ["업무 앱", "구글 시트"]},        # 갈래 그대로
            "t-2": {"keywords": ["월급계산기"]},                 # 갈래의 자식
            "t-3": {"keywords": ["C#", "안티그래비티"]},          # 갈래 아님
            "t-4": {"keywords": ["클로드"]},
        }
        threads = [{"id": "t-1", "category": "projects"},
                   {"id": "t-2", "category": "projects"},
                   {"id": "t-3", "category": "projects"},
                   {"id": "t-4", "category": "projects"},
                   {"id": "t-5", "category": "ai-tools"}]
        keys = facet_keys("앱 제작", ["업무 앱", "게임 제작", "실천 도구"], self.table())
        self.assertEqual(["t-3", "t-4"],
                         fill_targets(reports, threads, "projects", keys))

    def spare(self, *tags):
        """고립 태그(부모도 없고 목록에도 안 나오는 것)의 fold 집합."""
        return {taglib.fold(t) for t in tags}

    def test_a_spare_slot_gets_the_facet_appended(self):
        reports = {"t-3": {"keywords": ["C#", "안티그래비티"]}}
        got = screen_fill(reports, {"t-3": "업무 앱"}, KINDS, self.spare())
        self.assertEqual(["C#", "안티그래비티", "업무 앱"], got["t-3"]["after"])
        self.assertNotIn("dropped", got["t-3"])

    def test_a_full_line_swaps_the_last_tag_with_no_entrance(self):
        """입구가 있는 태그는 갈래 자리 때문에 버리지 않는다."""
        keywords = ["클로드", "안티그래비티", "가", "나", "다", "라"]
        reports = {"t-6": {"keywords": keywords}}
        got = screen_fill(reports, {"t-6": "업무 앱"}, KINDS, self.spare("가", "다"))
        self.assertEqual("다", got["t-6"]["dropped"], "뒤가 가장 곁가지다")
        self.assertEqual(["클로드", "안티그래비티", "가", "나", "업무 앱", "라"],
                         got["t-6"]["after"])
        self.assertEqual(6, len(got["t-6"]["after"]))

    def test_a_full_line_with_nothing_to_spare_is_skipped(self):
        keywords = ["클로드", "커서", "노션", "슬랙", "디스코드", "깃허브"]
        reports = {"t-7": {"keywords": keywords}}
        got = screen_fill(reports, {"t-7": "업무 앱"}, KINDS, self.spare())
        self.assertEqual({}, got, "잘 붙은 태그를 갈래 자리 때문에 버리지 않는다")

    def test_a_tag_that_has_a_parent_is_not_spare(self):
        """`도커`→인프라 처럼 부모로 찾히는 태그는 그 편에만 있는 말이 아니다.

        실측 2026-09-04: 부모를 안 보던 판에서 `도커`·`알리고`·`Open Notebook`
        셋을 버렸고, `Open Notebook` 은 그 주제의 제목이기도 했다.
        """
        keywords = ["가", "나", "다", "라", "마", "도커"]
        reports = {"t-8": {"keywords": keywords}}
        self.assertEqual({}, screen_fill(reports, {"t-8": "업무 앱"}, KINDS,
                                         self.spare()))

    def test_none_adds_nothing(self):
        reports = {"t-3": {"keywords": ["C#"]}}
        self.assertEqual({}, screen_fill(reports, {"t-3": NONE}, KINDS, self.spare()))
        self.assertEqual({}, screen_fill(reports, {"t-3": "복지 앱"}, KINDS,
                                         self.spare()))

    def test_a_facet_already_present_is_left_alone(self):
        reports = {"t-1": {"keywords": ["업무 앱"]}}
        self.assertEqual({}, screen_fill(reports, {"t-1": "업무 앱"}, KINDS,
                                         self.spare()))


class BroaderTableIsConsistentTest(unittest.TestCase):
    """실제 표를 본다 — 설명을 적어 둔 갈래가 자식으로도 적혀 있어야 한다."""

    def test_every_hinted_kind_is_also_a_child(self):
        p = Path(__file__).resolve().parent.parent / "config" / "tag_broader.json"
        raw = json.loads(p.read_text(encoding="utf-8"))
        broader = raw.get("broader") or {}
        for tag, kinds in (raw.get("split_hints") or {}).items():
            children = {taglib.fold(c) for c in broader.get(tag, [])}
            for kind in kinds:
                self.assertIn(
                    taglib.fold(kind), children,
                    "'%s' 의 갈래 '%s' 가 broader 의 자식이 아니다 — 갈라내면 "
                    "넓은 입구에서 사라진다" % (tag, kind))


if __name__ == "__main__":
    unittest.main()
