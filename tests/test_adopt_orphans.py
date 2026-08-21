# -*- coding: utf-8 -*-
"""고립 태그에 부모 붙이기 — 표를 고치면서 손 서식을 뭉개지 않는지.

실패 방식이 둘이다.

  · **서식을 뭉갠다.** 이 표는 사람이 한 줄에 여러 개씩 적어 다듬은 것이다.
    json.dumps 로 통째로 되쓰면 한 줄씩 펼쳐져 diff 가 파일 전체로 번지고,
    무엇을 고쳤는지 안 보인다(실측 2026-08-21: 실제로 그렇게 뭉갰다).
  · **목록에 없는 부모를 받는다.** 새 부모를 지어내면 그 부모가 또 1회짜리가 되어
    같은 빚을 한 층 위에서 다시 진다.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.adopt_orphans import NONE, add_children, parent_choices, render_array, screen

TABLE = """{
  "_설명": ["표 설명"],
  "short_parents": [
    "구글", "교육", "게임"
  ],
  "split_hints": {
    "앱 제작": { "업무 앱": "설명", "게임 제작": "설명" }
  },
  "broader": {
    "인프라": [
      "클라우드", "NAS", "VPN", "Tailscale", "WiFi", "UTP", "LAN 배선", "PoE",
      "GPU", "PC 스펙 업그레이드"
    ],
    "지식그래프": ["온톨로지", "TypeDB", "Neo4j", "RAG"],
    "앱 제작": ["업무 앱", "게임 제작"]
  }
}
"""


class WriterKeepsTheHandFormattingTest(unittest.TestCase):
    def test_no_change_means_no_byte_changes(self):
        out, fresh = add_children(TABLE, {})
        self.assertEqual(TABLE, out)
        self.assertEqual([], fresh)

    def test_a_child_that_is_already_there_changes_nothing(self):
        out, _ = add_children(TABLE, {"지식그래프": ["온톨로지", "RAG"]})
        self.assertEqual(TABLE, out)

    def test_spelling_differences_count_as_already_there(self):
        out, _ = add_children(TABLE, {"지식그래프": ["온톨로지 "]})
        self.assertEqual(TABLE, out)

    def test_a_short_array_stays_on_one_line(self):
        out, _ = add_children(TABLE, {"지식그래프": ["벡터DB"]})
        self.assertIn(
            '"지식그래프": ["온톨로지", "TypeDB", "Neo4j", "RAG", "벡터DB"]', out)
        # 다른 배열은 손대지 않는다
        self.assertIn('"클라우드", "NAS", "VPN", "Tailscale", "WiFi", "UTP", '
                      '"LAN 배선", "PoE",', out)

    def test_only_the_touched_array_is_rewritten(self):
        out, _ = add_children(TABLE, {"인프라": ["키오스크"]})
        self.assertIn('"지식그래프": ["온톨로지", "TypeDB", "Neo4j", "RAG"]', out)
        self.assertIn("키오스크", out)

    def test_a_new_parent_is_appended_and_the_json_stays_valid(self):
        out, fresh = add_children(TABLE, {"당사자 지원 앱": ["AAC", "소셜스토리"]})
        self.assertEqual(["당사자 지원 앱"], fresh)
        got = json.loads(out)
        self.assertEqual(["AAC", "소셜스토리"], got["broader"]["당사자 지원 앱"])
        self.assertEqual(["온톨로지", "TypeDB", "Neo4j", "RAG"],
                         got["broader"]["지식그래프"])

    def test_the_result_is_always_valid_json(self):
        out, _ = add_children(TABLE, {"인프라": ["우분투", "윈도우10", "키오스크"],
                                      "게임": ["스팀"]})
        json.loads(out)

    def test_render_wraps_long_arrays_with_the_files_indent(self):
        long = ["항목%02d" % i for i in range(20)]
        text = render_array("부모", long, "    ")
        self.assertTrue(text.startswith("[\n      "))
        self.assertTrue(text.endswith("\n    ]"))
        self.assertTrue(all(len(l) <= 92 for l in text.split("\n")), text)


class ParentChoicesTest(unittest.TestCase):
    def table(self) -> Path:
        p = Path(tempfile.mkdtemp()) / "tag_broader.json"
        p.write_text(TABLE, encoding="utf-8")
        return p

    def test_parents_come_from_the_table_only(self):
        got = parent_choices(self.table())
        for expected in ["인프라", "지식그래프", "앱 제작", "업무 앱", "게임 제작",
                         "구글", "교육", "게임"]:
            self.assertIn(expected, got)

    def test_the_real_table_offers_the_app_kinds_as_parents(self):
        """갈래로 세운 말은 고립 태그의 부모로 쓸 수 있어야 한다."""
        real = Path(__file__).resolve().parent.parent / "config" / "tag_broader.json"
        got = parent_choices(real)
        self.assertIn("당사자 지원 앱", got)
        self.assertIn("문서 처리 도구", got)


class ScreenTest(unittest.TestCase):
    PARENTS = ["인프라", "지식그래프", "당사자 지원 앱"]

    def test_answers_are_grouped_by_parent(self):
        got = screen({"우분투": "인프라", "AAC": "당사자 지원 앱", "키오스크": "인프라"},
                     self.PARENTS)
        self.assertEqual(["우분투", "키오스크"], got["인프라"])
        self.assertEqual(["AAC"], got["당사자 지원 앱"])

    def test_a_parent_outside_the_list_is_refused(self):
        """지어낸 부모를 받으면 같은 빚을 한 층 위에서 다시 진다."""
        self.assertEqual({}, screen({"우분투": "운영체제"}, self.PARENTS))

    def test_none_leaves_the_tag_alone(self):
        self.assertEqual({}, screen({"구현종": NONE, "기조강연": ""}, self.PARENTS))

    def test_a_tag_is_never_made_its_own_parent(self):
        self.assertEqual({}, screen({"인프라": "인프라"}, self.PARENTS))

    def test_spelling_of_the_answer_is_normalised(self):
        got = screen({"우분투": " 인프라 "}, self.PARENTS)
        self.assertEqual(["우분투"], got["인프라"])


if __name__ == "__main__":
    unittest.main()
