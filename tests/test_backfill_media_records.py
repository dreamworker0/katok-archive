# -*- coding: utf-8 -*-
"""뒤늦게 메꾸는 대장 줄의 계약.

코드를 고쳐도 **이미 들어온 메시지는 스스로 낫지 않는다.** 증분 반영은 새
메시지만 보기 때문이다. 그래서 빚을 갚는 스크립트가 따로 있고, 그것이 되풀이해
돌려도 안전해야 한다 — 이 저장소에서 대장을 잘못 건드리면 이미 붙은 사진이
화면에서 사라진다.
"""
from __future__ import annotations

import unittest

from scripts import backfill_media_records as bf


def message(mid, kind, timestamp="2026-08-31T09:16+09:00", image_id=None):
    return {
        "id": mid,
        "timestamp": timestamp,
        "date": timestamp[:10],
        "time": timestamp[11:16],
        "nickname": "A",
        "text": kind,
        "kind": kind,
        "image_id": image_id,
        "image_count": None,
    }


def row(image_id, message_id):
    return {"image_id": image_id, "message_id": message_id, "assets": []}


class PlanTests(unittest.TestCase):
    def test_only_media_messages_without_a_row_are_picked(self):
        messages = [
            message("msg-000001", "image"),
            message("msg-000002", "video"),
            message("msg-000003", "text"),
            message("msg-000004", "file"),
        ]
        records = [row("img-000001", "msg-000001")]

        picked = [m["id"] for m in bf.plan(messages, records)]

        self.assertEqual(picked, ["msg-000002"])

    def test_running_twice_finds_nothing_the_second_time(self):
        messages = [message("msg-000002", "video")]
        records = []

        first = bf.plan(messages, records)
        self.assertEqual(len(first), 1)

        records.append(row(bf.image_id_for("msg-000002"), "msg-000002"))
        self.assertEqual(bf.plan(messages, records), [])


class NumberingTests(unittest.TestCase):
    def test_the_id_follows_the_message_number(self):
        self.assertEqual(bf.image_id_for("msg-003098"), "img-003098")

    def test_the_stub_is_pending_and_says_its_kind(self):
        m = message("msg-003098", "video", image_id="img-003098")
        stub = bf.stub(m)

        self.assertEqual(stub["status"], "pending")
        self.assertEqual(stub["media_kind"], "video")
        self.assertEqual(stub["assets"], [])
        # 원본을 아직 안 받았다는 뜻이 줄에 남아야 한다 — 나중에 이 줄을 보는
        # 사람이 '왜 비어 있나' 를 로그에서 찾지 않아도 되게.
        self.assertIn("원본", str(stub["note"]))


if __name__ == "__main__":
    unittest.main()
