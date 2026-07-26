# -*- coding: utf-8 -*-
"""수집 단계 정책 — 원본에 넣지 않을 메시지를 제대로 가려내는지 확인.

되돌릴 수 없는 제외라서, 너무 많이 거르는 것도 너무 적게 거르는 것도 사고다.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import collection_policy as cp  # noqa: E402


def msg(nickname: str, text: str | None, ts: str = "2026-07-26T10:00+09:00"):
    return SimpleNamespace(nickname=nickname, text=text, timestamp=ts)


class KeywordTest(unittest.TestCase):
    POLICY = {"keywords": ["[제외]", "［제외］"], "opt_out_people": []}

    def test_keyword_anywhere_in_body_rejects(self):
        for body in ("[제외]", "이건 [제외] 해주세요", "앞말 [제외]"):
            self.assertEqual(cp.rejection_reason("홍길동", body, self.POLICY),
                             "keyword:[제외]", body)

    def test_fullwidth_bracket_also_rejects(self):
        """모바일 자판에서 전각 대괄호가 섞이면 사용자는 제외한 줄 알고 넘어간다."""
        self.assertEqual(cp.rejection_reason("홍길동", "［제외］ 부탁", self.POLICY),
                         "keyword:［제외］")

    def test_ordinary_message_is_kept(self):
        self.assertIsNone(cp.rejection_reason("홍길동", "제외 없이 그냥 대화", self.POLICY))

    def test_bare_word_without_brackets_is_kept(self):
        """'제외' 는 일상어다. 대괄호가 있어야 의사 표시로 본다."""
        self.assertIsNone(cp.rejection_reason("홍길동", "그건 제외하고 봅시다", self.POLICY))

    def test_empty_body_is_kept(self):
        self.assertIsNone(cp.rejection_reason("홍길동", None, self.POLICY))

    def test_empty_keyword_list_disables_rule(self):
        policy = {"keywords": [], "opt_out_people": []}
        self.assertIsNone(cp.rejection_reason("홍길동", "[제외]", policy))


class OptOutTest(unittest.TestCase):
    POLICY = {"keywords": [], "opt_out_people": ["홍길동"]}

    def test_opted_out_person_is_rejected(self):
        self.assertEqual(cp.rejection_reason("홍길동", "아무 말", self.POLICY), "person")

    def test_other_people_unaffected(self):
        self.assertIsNone(cp.rejection_reason("김철수", "아무 말", self.POLICY))


class FilterTest(unittest.TestCase):
    POLICY = {"keywords": ["[제외]"], "opt_out_people": ["나가리"]}

    def test_splits_and_counts_by_reason(self):
        rows = [
            msg("홍길동", "평범한 글"),
            msg("홍길동", "이건 [제외]"),
            msg("나가리", "수집 거부한 사람"),
            msg("김철수", "또 평범한 글"),
        ]
        kept, reasons, dropped = cp.filter_messages(rows, self.POLICY)
        self.assertEqual([m.text for m in kept], ["평범한 글", "또 평범한 글"])
        self.assertEqual(reasons, {"keyword:[제외]": 1, "person": 1})
        self.assertEqual(len(dropped), 2)

    def test_dropped_summary_carries_no_body(self):
        """거부한 글의 본문이 로그·리포트로 새면 설정의 의미가 없어진다."""
        _, _, dropped = cp.filter_messages([msg("홍길동", "비밀 [제외]")], self.POLICY)
        self.assertEqual(len(dropped), 1)
        self.assertNotIn("text", dropped[0])
        for value in dropped[0].values():
            self.assertNotIn("비밀", str(value))


class DefaultPolicyTest(unittest.TestCase):
    def test_default_keywords_used_when_no_config(self):
        """설정 파일 없이도 [제외] 는 바로 동작해야 한다."""
        policy = cp.load_policy()
        self.assertIn("[제외]", policy["keywords"])


if __name__ == "__main__":
    unittest.main()
