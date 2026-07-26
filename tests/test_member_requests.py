# -*- coding: utf-8 -*-
"""멤버 요청 반영 — 특히 소유권 검증.

보안 규칙은 "본인 문서에만 쓴다"까지만 보장한다. 그 문서 안에 남의 메시지 ID 를
적는 것은 규칙으로 막을 수 없으므로, 여기가 마지막 방어선이다.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import member_requests as mr  # noqa: E402


MESSAGES = [
    {"id": "msg-000001", "nickname": "홍길동"},
    {"id": "msg-000002", "nickname": "홍길동"},
    {"id": "msg-000003", "nickname": "김철수"},
    {"id": "msg-000004", "nickname": "이영희"},
]


def request(nickname, email="a@x.com", collection="public",
            delete_all=False, ids=()):
    names = [nickname] if isinstance(nickname, str) else list(nickname)
    return {"email": email, "nicknames": names, "collection": collection,
            "delete_all": delete_all, "delete_message_ids": list(ids)}


class OwnershipTest(unittest.TestCase):
    def test_own_messages_are_accepted(self):
        out = mr.verify_ownership([request("홍길동", ids=["msg-000001"])], MESSAGES)
        self.assertEqual(out["exclude_message_ids"], ["msg-000001"])
        self.assertEqual(out["rejected"], [])

    def test_other_peoples_messages_are_refused(self):
        """남의 글을 지우려는 요청은 반드시 걸러야 한다."""
        out = mr.verify_ownership([request("홍길동", ids=["msg-000003"])], MESSAGES)
        self.assertEqual(out["exclude_message_ids"], [])
        self.assertEqual(len(out["rejected"]), 1)
        self.assertEqual(out["rejected"][0]["reason"], "본인 메시지가 아님")

    def test_mixed_request_keeps_only_own(self):
        out = mr.verify_ownership(
            [request("홍길동", ids=["msg-000001", "msg-000003", "msg-000002"])], MESSAGES)
        self.assertEqual(out["exclude_message_ids"], ["msg-000001", "msg-000002"])
        self.assertEqual(len(out["rejected"]), 1)

    def test_unknown_message_id_is_refused(self):
        out = mr.verify_ownership([request("홍길동", ids=["msg-999999"])], MESSAGES)
        self.assertEqual(out["exclude_message_ids"], [])
        self.assertEqual(out["rejected"][0]["reason"], "없는 메시지")

    def test_delete_all_takes_only_own_messages(self):
        out = mr.verify_ownership([request("홍길동", delete_all=True)], MESSAGES)
        self.assertEqual(out["exclude_message_ids"], ["msg-000001", "msg-000002"])

    def test_unpublished_excludes_the_person(self):
        out = mr.verify_ownership([request("김철수", collection="unpublished")], MESSAGES)
        self.assertEqual(out["exclude_people"], ["김철수"])

    def test_public_changes_nothing(self):
        out = mr.verify_ownership([request("김철수", collection="public")], MESSAGES)
        self.assertEqual(out["exclude_people"], [])
        self.assertEqual(out["exclude_message_ids"], [])


class OptOutTest(unittest.TestCase):
    def test_none_is_a_collection_opt_out_not_a_publish_exclusion(self):
        """수집 거부는 수집 단계에서 막는다. 발행 제외 목록에 들어가면 안 된다."""
        rows = [request("이영희", collection="none")]
        self.assertEqual(mr.collection_opt_outs(rows), ["이영희"])
        self.assertEqual(mr.verify_ownership(rows, MESSAGES)["exclude_people"], [])


class RenamedPersonTest(unittest.TestCase):
    """카톡에서 이름을 바꾸면 그 시점부터 다른 참여자로 잡힌다.

    표시명을 하나만 붙들면 그 사람 글의 절반이 사라진다. 옛 이름과 새 이름을
    함께 묶을 수 있어야 한다.
    """

    MESSAGES = [
        {"id": "msg-000001", "nickname": "김종원"},
        {"id": "msg-000002", "nickname": "김종원(사협)"},
        {"id": "msg-000003", "nickname": "다른사람"},
    ]

    def test_delete_all_covers_every_name(self):
        out = mr.verify_ownership(
            [request(["김종원", "김종원(사협)"], delete_all=True)], self.MESSAGES)
        self.assertEqual(out["exclude_message_ids"], ["msg-000001", "msg-000002"])

    def test_can_delete_message_written_under_old_name(self):
        out = mr.verify_ownership(
            [request(["김종원(사협)", "김종원"], ids=["msg-000001"])], self.MESSAGES)
        self.assertEqual(out["exclude_message_ids"], ["msg-000001"])
        self.assertEqual(out["rejected"], [])

    def test_still_cannot_touch_other_people(self):
        out = mr.verify_ownership(
            [request(["김종원", "김종원(사협)"], ids=["msg-000003"])], self.MESSAGES)
        self.assertEqual(out["exclude_message_ids"], [])
        self.assertEqual(out["rejected"][0]["reason"], "본인 메시지가 아님")

    def test_unpublished_hides_every_name(self):
        out = mr.verify_ownership(
            [request(["김종원", "김종원(사협)"], collection="unpublished")], self.MESSAGES)
        self.assertEqual(out["exclude_people"], ["김종원", "김종원(사협)"])

    def test_opt_out_covers_every_name(self):
        rows = [request(["김종원", "김종원(사협)"], collection="none")]
        self.assertEqual(mr.collection_opt_outs(rows), ["김종원", "김종원(사협)"])


class LegacyShapeTest(unittest.TestCase):
    """옛 요청 파일은 nickname 하나만 갖고 있다. 그대로 읽혀야 한다."""

    def test_single_nickname_is_promoted_to_list(self):
        import json, tempfile, os
        from unittest import mock
        payload = {"requests": [{"email": "a@x.com", "nickname": "홍길동",
                                 "collection": "unpublished"}]}
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "member-requests.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with mock.patch.object(mr, "REQUESTS_PATH", path):
                rows = mr.load_requests()
        self.assertEqual(rows[0]["nicknames"], ["홍길동"])


class MergeTest(unittest.TestCase):
    def test_manual_entries_survive(self):
        """관리자가 손으로 넣은 제외를 멤버 요청이 덮어써서는 안 된다."""
        exclusions = {"exclude_people": ["관리자가넣은사람"],
                      "exclude_message_ids": ["msg-000004"],
                      "exclude_keywords": ["[비공개]"]}
        resolved = {"exclude_people": ["김철수"],
                    "exclude_message_ids": ["msg-000001"], "rejected": []}
        out = mr.merge_into_exclusions(exclusions, resolved)
        self.assertEqual(out["exclude_people"], ["관리자가넣은사람", "김철수"])
        self.assertEqual(out["exclude_message_ids"], ["msg-000001", "msg-000004"])
        self.assertEqual(out["exclude_keywords"], ["[비공개]"])


class LoadTest(unittest.TestCase):
    def test_missing_file_means_no_requests(self):
        self.assertIsInstance(mr.load_requests(), list)


if __name__ == "__main__":
    unittest.main()
