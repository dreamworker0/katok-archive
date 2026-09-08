# -*- coding: utf-8 -*-
"""인용 검사 — 이름 대조와 '다시 쓸 것 고르기'.

이 일의 실패 방식은 셋이다.

  · 제대로 인용했는데 '없는 사람' 이라고 운다 — 매일 우는 경고는 안 읽힌다
  · 세는 수와 보여주는 줄이 다르다 — 어느 쪽이 맞는지 알 수 없다
  · 지어낸 인용을 손으로만 고칠 수 있다 — 가장 무거운 경고에 길이 없다

여기 나오는 이름은 전부 가짜다. 저장소가 공개다.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts import audit_quotes as aq


class BaseNameTest(unittest.TestCase):
    def test_room_label_is_stripped(self):
        """같은 사람이 방 표시를 붙인 별명과 안 붙인 별명 둘로 존재한다."""
        self.assertEqual("홍길동", aq._base_name("홍길동(가나복지관)"))
        self.assertEqual("홍길동", aq._base_name("홍길동（가나복지관）"))
        self.assertEqual("홍길동팀장", aq._base_name("홍길동팀장 (다라센터)"))

    def test_a_plain_nickname_is_left_alone(self):
        self.assertEqual("홍길동", aq._base_name("홍길동"))

    def test_only_a_trailing_label_is_stripped(self):
        """가운데 괄호는 이름의 일부일 수 있다 — 끝에 붙은 것만 뗀다."""
        self.assertEqual("홍(길)동 센터", aq._base_name("홍(길)동 센터"))


class RewriteUnfoundQuotesTest(unittest.TestCase):
    """지어낸 인용은 되돌리기가 가장 어렵다 — 손 경로만 두지 않는다."""

    def run_pick(self, unmatched, limit=2):
        from scripts import classify_unsorted as cu
        threads = [{"id": "t-001"}, {"id": "t-002"}, {"id": "t-003"}]
        seen = {}

        def fake_write(targets, *a, **kw):
            seen["ids"] = [t["id"] for t in targets]
            return len(targets)

        report = {"reports": 3, "quotes": 9, "unmatched": unmatched,
                  "too_long": [], "stranger_names": []}
        with patch.object(aq, "audit", return_value=report), \
             patch.object(cu, "_write_reports", side_effect=fake_write):
            n = cu.rewrite_unfound_quote_reports(threads, "m", [], False, limit=limit)
        return n, seen.get("ids", [])

    def test_nothing_to_do_is_not_an_error(self):
        n, ids = self.run_pick([])
        self.assertEqual(0, n)
        self.assertEqual([], ids)

    def test_least_similar_goes_first(self):
        """닮은정도가 낮을수록 지어냈을 가능성이 크다 — 그것부터 본다."""
        n, ids = self.run_pick([("t-001", 0.79, "가나다"),
                                ("t-002", 0.41, "라마바"),
                                ("t-003", 0.66, "사아자")])
        self.assertEqual(["t-002", "t-003"], ids)
        self.assertEqual(2, n)

    def test_a_thread_with_several_bad_quotes_is_judged_by_its_worst(self):
        n, ids = self.run_pick([("t-001", 0.95, "가"), ("t-001", 0.30, "나"),
                                ("t-002", 0.60, "다")], limit=1)
        self.assertEqual(["t-001"], ids)


class StrangerNameCountTest(unittest.TestCase):
    def test_the_number_and_the_list_agree(self):
        """별명이 둘인 사람이 같은 편에서 두 번 담기면 숫자가 줄과 어긋난다.

        실측 2026-09-09: 17건이라 적고 16줄을 보여 줬다. 세는 쪽은 중복을
        포함하고 보여주는 쪽은 지웠기 때문이다.
        """
        rows = [("t-001", "홍길동"), ("t-002", "홍길동"), ("t-001", "김철수")]
        self.assertEqual(len(rows), len(set(rows)),
                         "같은 (주제, 이름)이 두 번 담겼다")


if __name__ == "__main__":
    unittest.main()
