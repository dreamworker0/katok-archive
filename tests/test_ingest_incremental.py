# -*- coding: utf-8 -*-
"""증분 수집 로직 검증.

핵심은 "같은 파일을 여러 번 넣어도, 겹치는 구간이 있어도 중복되거나 누락되지
않는다"는 것이다. 카카오톡 내보내기는 항상 전체 대화를 주기 때문에 매번
대부분이 겹친다.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts import ingest_incremental as inc  # noqa: E402
from scripts.kakao_parser import parse_chat  # noqa: E402
from tests.realdata import needs_real_data  # noqa: E402


def export_text(days):
    """days: [(날짜문자열, [(오전/오후, 시:분, 닉, 본문), ...]), ...] → 내보내기 형식 txt"""
    lines = ["저장한 날짜 : 2026-07-25 09:30:00", ""]
    for date, rows in days:
        y, m, d = date.split("-")
        lines.append(f"--------------- {y}년 {int(m)}월 {int(d)}일 토요일 ---------------")
        for period, hm, nick, body in rows:
            lines.append(f"[{nick}] [{period} {hm}] {body}")
    return "\n".join(lines)


def as_existing(records):
    """messages.jsonl 형태의 최소 레코드"""
    return records


class FindNewMessagesTest(unittest.TestCase):
    def setUp(self):
        txt = export_text([
            ("2026-07-24", [
                ("오후", "1:51", "오세라", "이전 메시지 A"),
                ("오후", "4:27", "가온", "이전 메시지 B"),
            ]),
        ])
        parsed = parse_chat(txt).messages
        self.existing = [inc.to_record(m, i + 1) for i, m in enumerate(parsed)]

    def test_identical_file_yields_nothing(self):
        """같은 내용을 다시 넣으면 신규 0건 — 매일 전체를 내보내도 안전해야 한다."""
        txt = export_text([
            ("2026-07-24", [
                ("오후", "1:51", "오세라", "이전 메시지 A"),
                ("오후", "4:27", "가온", "이전 메시지 B"),
            ]),
        ])
        new, stats = inc.find_new_messages(parse_chat(txt).messages, self.existing)
        self.assertEqual(new, [])
        self.assertEqual(stats.get("신규", 0), 0)

    def test_overlap_plus_new(self):
        """겹치는 구간은 버리고 새 메시지만 남긴다."""
        txt = export_text([
            ("2026-07-24", [
                ("오후", "1:51", "오세라", "이전 메시지 A"),
                ("오후", "4:27", "가온", "이전 메시지 B"),
            ]),
            ("2026-07-25", [
                ("오전", "9:15", "김종원", "새 메시지 1"),
                ("오전", "9:20", "서지호", "새 메시지 2"),
            ]),
        ])
        new, stats = inc.find_new_messages(parse_chat(txt).messages, self.existing)
        self.assertEqual([m.text for m in new], ["새 메시지 1", "새 메시지 2"])
        self.assertEqual(stats["신규"], 2)

    def test_same_minute_multiple_messages_not_lost(self):
        """같은 시각에 여러 건이 와도 시각만으로 자르지 않으므로 누락되지 않는다."""
        txt = export_text([
            ("2026-07-24", [
                ("오후", "1:51", "오세라", "이전 메시지 A"),
                ("오후", "4:27", "가온", "이전 메시지 B"),
                ("오후", "4:27", "가온", "같은 분에 온 다른 메시지"),
                ("오후", "4:27", "김종원", "같은 분 다른 사람"),
            ]),
        ])
        new, _ = inc.find_new_messages(parse_chat(txt).messages, self.existing)
        self.assertEqual(
            [m.text for m in new],
            ["같은 분에 온 다른 메시지", "같은 분 다른 사람"],
        )

    def test_duplicate_within_same_file_collapses(self):
        """한 파일 안에 완전히 같은 줄이 두 번 있으면 한 건만 취한다."""
        txt = export_text([
            ("2026-07-25", [
                ("오전", "9:15", "김종원", "똑같은 줄"),
                ("오전", "9:15", "김종원", "똑같은 줄"),
            ]),
        ])
        new, _ = inc.find_new_messages(parse_chat(txt).messages, self.existing)
        self.assertEqual(len(new), 1)


class RecordShapeTest(unittest.TestCase):
    def test_ids_are_sequential_and_padded(self):
        txt = export_text([("2026-07-25", [
            ("오전", "9:15", "김종원", "가"),
            ("오전", "9:16", "김종원", "나"),
        ])])
        parsed = parse_chat(txt).messages
        recs = [inc.to_record(m, 1510 + i) for i, m in enumerate(parsed)]
        self.assertEqual([r["id"] for r in recs], ["msg-001510", "msg-001511"])

    def test_next_message_number_follows_last_id(self):
        self.assertEqual(inc.next_message_number([{"id": "msg-001509"}]), 1510)
        self.assertEqual(inc.next_message_number([]), 1)

    def test_image_message_gets_pending_stub(self):
        txt = export_text([("2026-07-25", [("오전", "9:22", "김종원", "사진")])])
        parsed = parse_chat(txt).messages
        rec = inc.to_record(parsed[0], 1510)
        self.assertEqual(rec["kind"], "image")
        self.assertEqual(rec["image_id"], "img-001510")
        stub = inc.image_stub(rec)
        self.assertEqual(stub["status"], "pending")
        self.assertEqual(stub["message_id"], "msg-001510")
        self.assertEqual(stub["assets"], [])

    def test_file_share_flagged(self):
        txt = export_text([("2026-07-25", [("오전", "9:30", "김종원", "파일: 계획서.md")])])
        rec = inc.to_record(parse_chat(txt).messages[0], 1510)
        self.assertEqual(rec["kind"], "file")
        self.assertTrue(rec["is_file_share"])


class TopicAssignmentTest(unittest.TestCase):
    def test_creates_unsorted_thread_and_keeps_coverage(self):
        topics = {"categories": [{"id": "chat", "label": "일상"}], "threads": []}
        topics = inc.assign_to_topics(topics, ["msg-001510", "msg-001511"], "2026-07-25")
        self.assertEqual(len(topics["threads"]), 1)
        t = topics["threads"][0]
        self.assertEqual(t["message_ids"], ["msg-001510", "msg-001511"])
        self.assertEqual(t["start_msg"], "msg-001510")
        self.assertEqual(t["end_msg"], "msg-001511")
        self.assertEqual(t["category"], inc.UNSORTED_CATEGORY)

    def test_same_day_appends_instead_of_duplicating_thread(self):
        topics = {"categories": [{"id": "chat", "label": "일상"}], "threads": []}
        topics = inc.assign_to_topics(topics, ["msg-001510"], "2026-07-25")
        topics = inc.assign_to_topics(topics, ["msg-001511"], "2026-07-25")
        self.assertEqual(len(topics["threads"]), 1)
        self.assertEqual(topics["threads"][0]["message_ids"],
                         ["msg-001510", "msg-001511"])

    def test_different_days_get_separate_threads(self):
        topics = {"categories": [{"id": "chat", "label": "일상"}], "threads": []}
        topics = inc.assign_to_topics(topics, ["msg-001510"], "2026-07-25")
        topics = inc.assign_to_topics(topics, ["msg-001512"], "2026-07-26")
        self.assertEqual(len(topics["threads"]), 2)

    @needs_real_data
    def test_unsorted_category_exists_in_real_topics(self):
        """폴백 카테고리가 실제 topics.json 에 존재해야 화면이 깨지지 않는다."""
        from scripts import build_site
        topics = build_site._read_json(ROOT / "output" / "topics.json")
        ids = {c["id"] for c in topics["categories"]}
        self.assertIn(inc.UNSORTED_CATEGORY, ids)


class ParticipantsTest(unittest.TestCase):
    def test_counts_and_ordering(self):
        msgs = [
            {"nickname": "가", "timestamp": "2026-07-25T09:15+09:00"},
            {"nickname": "나", "timestamp": "2026-07-25T09:16+09:00"},
            {"nickname": "가", "timestamp": "2026-07-25T09:17+09:00"},
        ]
        out = inc.rebuild_participants(msgs)["participants"]
        self.assertEqual(out[0]["nickname"], "가")
        self.assertEqual(out[0]["message_count"], 2)
        self.assertEqual(out[0]["first_timestamp"], "2026-07-25T09:15+09:00")
        self.assertEqual(out[0]["last_timestamp"], "2026-07-25T09:17+09:00")


class SameRoomGuardTest(unittest.TestCase):
    """엉뚱한 방을 내보내면 반영하지 않는다.

    증분 반영은 '마지막 메시지 이후'만 덧붙이므로, 다른 방을 내보내도 그 방의 최근
    글이 그냥 신규로 들어온다. 한 번 섞이면 어느 것이 남의 방 글인지 표시가 없다.

    길이로 판정하지 않는다. 옛 설계(codex 브랜치의 refresh_guard.py)는 내보내기가
    원장의 상위집합이라고 보고 더 짧으면 거부했는데, 수집을 전용 계정으로 돌린 뒤로
    내보내기에는 초대 이후 구간만 담긴다 — 그대로 켜면 매일 거부한다.
    """

    def setUp(self):
        txt = export_text([
            ("2026-07-24", [
                ("오후", "1:00", "김종원", "우리 방 첫 줄"),
                ("오후", "1:01", "오세라", "우리 방 둘째 줄"),
                ("오후", "1:02", "가온", "우리 방 셋째 줄"),
                ("오후", "1:03", "김종원", "우리 방 넷째 줄"),
                ("오후", "1:04", "오세라", "우리 방 다섯째 줄"),
                ("오후", "1:05", "가온", "우리 방 여섯째 줄"),
            ]),
        ])
        parsed = parse_chat(txt).messages
        self.existing = [inc.to_record(m, i + 1) for i, m in enumerate(parsed)]

    def rows(self, prefix, n=6, start=0):
        return [("오후", "1:%02d" % (start + i), "김종원", "%s %d" % (prefix, i))
                for i in range(n)]

    def test_same_room_passes(self):
        txt = export_text([("2026-07-24", [
            ("오후", "1:00", "김종원", "우리 방 첫 줄"),
            ("오후", "1:01", "오세라", "우리 방 둘째 줄"),
            ("오후", "1:02", "가온", "우리 방 셋째 줄"),
            ("오후", "1:03", "김종원", "우리 방 넷째 줄"),
            ("오후", "1:04", "오세라", "우리 방 다섯째 줄"),
            ("오후", "1:05", "가온", "우리 방 여섯째 줄"),
            ("오후", "2:00", "김종원", "오늘 새 글"),
        ])])
        ok, report = inc.check_same_room(parse_chat(txt).messages, self.existing)
        self.assertTrue(ok, report)

    def test_a_short_export_from_the_same_room_passes(self):
        """전용 계정 내보내기는 원장보다 짧다 — 그것만으로 거부하면 안 된다."""
        txt = export_text([("2026-07-24", [
            ("오후", "1:02", "가온", "우리 방 셋째 줄"),
            ("오후", "1:03", "김종원", "우리 방 넷째 줄"),
            ("오후", "1:04", "오세라", "우리 방 다섯째 줄"),
            ("오후", "1:05", "가온", "우리 방 여섯째 줄"),
            ("오후", "2:00", "김종원", "오늘 새 글"),
        ])])
        parsed = parse_chat(txt).messages
        self.assertLess(len(parsed), len(self.existing) + 1)
        ok, report = inc.check_same_room(parsed, self.existing)
        self.assertTrue(ok, report)

    def test_a_different_room_is_refused(self):
        txt = export_text([("2026-07-24", self.rows("남의 방 글"))])
        ok, report = inc.check_same_room(parse_chat(txt).messages, self.existing)
        self.assertFalse(ok)
        self.assertEqual(report["알아봄"], 0)

    def test_too_little_overlap_is_not_judged(self):
        """판정할 근거가 없으면 통과시킨다 — 멀쩡한 날 갱신이 멈추면 안 된다."""
        txt = export_text([("2026-07-24", [
            ("오후", "1:05", "가온", "우리 방 여섯째 줄"),
            ("오후", "3:00", "김종원", "한참 뒤 새 글"),
        ])])
        ok, report = inc.check_same_room(parse_chat(txt).messages, self.existing)
        self.assertTrue(ok)
        self.assertIn("비교하지 않음", report["판정"])

    def test_empty_ledger_is_not_judged(self):
        txt = export_text([("2026-07-24", self.rows("아무 글"))])
        ok, _ = inc.check_same_room(parse_chat(txt).messages, [])
        self.assertTrue(ok)

    def test_a_few_edits_still_count_as_the_same_room(self):
        """겹치는 구간에서 한 건쯤 어긋나도 거부하면 안 된다.

        파싱 차이(멘션 표기·잘린 긴 글)로 한두 건은 늘 어긋난다. 20건 중 1건이면
        같은 방이고, 그때 갱신이 멈추면 안 된다.
        """
        rows = self.rows("긴 대화", n=20)
        ledger_txt = export_text([("2026-07-24", rows)])
        ledger = [inc.to_record(m, i + 1)
                  for i, m in enumerate(parse_chat(ledger_txt).messages)]

        edited = list(rows)
        edited[7] = ("오후", "1:07", "김종원", "파싱이 조금 다르게 읽은 줄")
        txt = export_text([("2026-07-24", edited)])

        ok, report = inc.check_same_room(parse_chat(txt).messages, ledger)
        self.assertTrue(ok, report)
        self.assertEqual((report["겹침"], report["알아봄"]), (20, 19))

    def test_half_the_overlap_going_wrong_is_refused(self):
        """조금 다른 것과 딴판인 것은 갈라야 한다."""
        rows = self.rows("긴 대화", n=20)
        ledger_txt = export_text([("2026-07-24", rows)])
        ledger = [inc.to_record(m, i + 1)
                  for i, m in enumerate(parse_chat(ledger_txt).messages)]

        edited = list(rows)
        for i in range(10):
            edited[i] = ("오후", "1:%02d" % i, "김종원", "남의 방 글 %d" % i)
        txt = export_text([("2026-07-24", edited)])

        ok, report = inc.check_same_room(parse_chat(txt).messages, ledger)
        self.assertFalse(ok, report)


if __name__ == "__main__":
    unittest.main()
