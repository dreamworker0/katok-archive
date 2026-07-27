# -*- coding: utf-8 -*-
"""옛 백업 합치기 검증.

여기서 지켜야 하는 것은 "두 출처 중 어느 쪽이 정본인가" 를 구간마다 다르게
적용하는 일이다. 실측에서 실제로 틀릴 뻔한 두 가지를 특히 붙잡아 둔다.

  · 모바일 내보내기는 500자에서 잘린다 → 겹치는 구간의 긴 글은 기존이 정본
  · 모바일의 '<사진 읽지 않음>' 은 기존의 실제 사진보다 나쁘다 → 버린다
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts import backfill_export as bf  # noqa: E402
from scripts.kakao_parser import parse_chat  # noqa: E402


def mobile(rows):
    """rows: [(날짜, 오전/오후, 시:분, 닉, 본문)] → 모바일 내보내기 형식"""
    lines = ["방 이름 카카오톡 대화", "저장한 날짜 : 2026년 7월 27일 오후 4:27", ""]
    for date, period, hm, nick, body in rows:
        y, m, d = date.split("-")
        lines.append(f"{y}년 {int(m)}월 {int(d)}일 {period} {hm}, {nick} : {body}")
    return "\n".join(lines)


def existing(rows):
    """rows: [(timestamp, 닉, 본문, kind)] → messages.jsonl 최소 레코드"""
    out = []
    for i, (ts, nick, text, kind) in enumerate(rows, start=1):
        out.append({
            "id": "msg-%06d" % i, "timestamp": ts, "date": ts[:10],
            "time": ts[11:16], "nickname": nick, "text": text, "urls": [],
            "kind": kind, "image_id": ("img-%06d" % i) if kind == "image" else None,
            "image_count": 1 if kind == "image" else None,
            "source_line": i, "is_file_share": False,
        })
    return out


ARCHIVE = existing([
    ("2026-02-27T18:06+09:00", "김종원", "사진", "image"),
    ("2026-03-01T10:00+09:00", "서지호", "안녕하세요", "text"),
])


class FormatDetectionTest(unittest.TestCase):
    def test_reads_mobile_export(self):
        result = parse_chat(mobile([
            ("2025-08-20", "오후", "4:34", "김종원", "안녕하세요."),
            ("2025-08-20", "오후", "4:35", "서지호", "반갑습니다"),
        ]))

        self.assertEqual([m.nickname for m in result.messages], ["김종원", "서지호"])
        self.assertEqual(result.messages[0].timestamp, "2025-08-20T16:34+09:00")

    def test_date_only_line_does_not_join_previous_message(self):
        """날짜 구분줄을 본문으로 삼키면 그 메시지가 매번 새 글로 잡힌다."""
        text = mobile([("2026-03-07", "오후", "12:54", "김종원", "오픈클로의 효과죠.")])
        text += "\n2026년 3월 8일 오전 9:48\n"
        text += "2026년 3월 8일 오전 9:48, 김종원 : 다음 글"

        result = parse_chat(text)

        self.assertEqual(result.messages[0].text, "오픈클로의 효과죠.")
        self.assertEqual(len(result.messages), 2)

    def test_lost_photo_and_media_reference_are_distinguished(self):
        ref = "a" * 64 + ".png"
        result = parse_chat(mobile([
            ("2026-03-08", "오전", "9:48", "김종원", "<사진 읽지 않음>"),
            ("2026-03-08", "오전", "9:49", "김종원", ref),
        ]))

        self.assertEqual([m.kind for m in result.messages], ["image", "image"])
        self.assertEqual(result.messages[0].media_status, "lost")
        self.assertEqual(result.messages[1].media_status, "referenced")
        self.assertEqual(result.messages[1].media_refs, (ref,))

    def test_pc_export_still_parses(self):
        """형식 자동 판별이 기존 경로를 깨지 않아야 한다."""
        result = parse_chat(
            "--------------- 2026년 3월 8일 일요일 ---------------\n"
            "[김종원] [오전 9:48] 사진\n"
        )

        self.assertEqual(result.messages[0].kind, "image")
        self.assertIsNone(result.messages[0].media_status)


class PlanMergeTest(unittest.TestCase):
    def test_takes_everything_before_archive_start(self):
        parsed = parse_chat(mobile([
            ("2025-08-20", "오후", "4:34", "김종원", "옛날 글"),
        ])).messages

        plan = bf.plan_merge(parsed, ARCHIVE)

        self.assertEqual([m.text for m in plan.old], ["옛날 글"])
        self.assertEqual(plan.overlap, [])

    def test_skips_message_already_archived(self):
        parsed = parse_chat(mobile([
            ("2026-03-01", "오전", "10:00", "서지호", "안녕하세요"),
        ])).messages

        plan = bf.plan_merge(parsed, ARCHIVE)

        self.assertEqual(plan.accepted, [])
        self.assertEqual(plan.skipped["이미_보관"], 1)

    def test_whitespace_only_difference_is_the_same_message(self):
        """PC 는 줄바꿈 하나, 모바일은 둘 — 같은 글이 새 글로 잡히면 안 된다."""
        archive = existing([("2026-03-01T10:00+09:00", "서지호", "첫 줄\n둘째 줄", "text")])
        parsed = parse_chat(
            mobile([("2026-03-01", "오전", "10:00", "서지호", "첫 줄")]) + "\n\n둘째 줄"
        ).messages

        plan = bf.plan_merge(parsed, archive)

        self.assertEqual(plan.accepted, [])
        self.assertEqual(plan.skipped["이미_보관"], 1)

    def test_truncated_500_char_copy_is_not_a_new_message(self):
        """모바일이 500자에서 자른 조각을 새 글로 받으면 잘린 중복이 남는다."""
        full = "가" * 900
        archive = existing([("2026-03-01T10:00+09:00", "하준서", full, "text")])
        parsed = parse_chat(
            mobile([("2026-03-01", "오전", "10:00", "하준서", full[:500])])
        ).messages

        plan = bf.plan_merge(parsed, archive)

        self.assertEqual(plan.accepted, [])
        self.assertEqual(plan.skipped["잘린_중복"], 1)

    def test_short_message_sharing_a_prefix_is_still_taken(self):
        """길이 조건이 없으면 짧은 글이 남의 앞부분과 겹쳤다고 버려진다."""
        archive = existing([("2026-03-01T10:00+09:00", "노민석", "우와 정말 대단하네요", "text")])
        parsed = parse_chat(
            mobile([("2026-03-01", "오전", "10:00", "노민석", "우와")])
        ).messages

        plan = bf.plan_merge(parsed, archive)

        self.assertEqual([m.text for m in plan.overlap], ["우와"])

    def test_lost_photo_in_overlap_is_dropped(self):
        """같은 자리에 기존이 실제 사진을 갖고 있다. 받으면 나빠진다."""
        parsed = parse_chat(mobile([
            ("2026-02-27", "오후", "6:06", "김종원", "<사진 읽지 않음>"),
        ])).messages

        plan = bf.plan_merge(parsed, ARCHIVE)

        self.assertEqual(plan.accepted, [])
        self.assertEqual(plan.skipped["겹침_읽지않음"], 1)

    def test_lost_photo_before_archive_start_is_kept_as_placeholder(self):
        """옛 구간에는 대신할 것이 없다. '여기 사진이 있었다'는 남겨야 한다."""
        parsed = parse_chat(mobile([
            ("2025-08-20", "오후", "4:34", "김종원", "<사진 읽지 않음>"),
        ])).messages

        plan = bf.plan_merge(parsed, ARCHIVE)

        self.assertEqual(len(plan.old), 1)
        record = bf.to_record(plan.old[0], 500)
        entry = bf.image_entry(record, plan.old[0], "없음")
        self.assertEqual(entry["status"], "lost")
        self.assertEqual(record["text"], "사진")

    def test_media_reference_in_overlap_links_to_existing_photo(self):
        """새 메시지가 아니라, 기존 사진 메시지에 붙일 파일 이름이다."""
        ref = "b" * 64 + ".png"
        parsed = parse_chat(mobile([
            ("2026-02-27", "오후", "6:06", "김종원", ref),
        ])).messages

        plan = bf.plan_merge(parsed, ARCHIVE)

        self.assertEqual(plan.accepted, [])
        self.assertEqual(plan.media_links, [("img-000001", ref)])

    def test_media_reference_with_no_slot_becomes_a_new_photo(self):
        """아카이브가 아직 못 본 사진. 버리면 파일을 쥐고도 잃는다."""
        ref = "d" * 64 + ".png"
        parsed = parse_chat(mobile([
            ("2026-07-27", "오후", "4:21", "최다인", ref),
        ])).messages

        plan = bf.plan_merge(parsed, ARCHIVE)

        self.assertEqual(len(plan.overlap), 1)
        self.assertEqual(plan.media_links, [])
        self.assertEqual(plan.overlap[0].media_refs, (ref,))

    def test_rerunning_the_same_export_adds_nothing(self):
        """카톡 내보내기는 늘 전체를 준다. 두 번째 실행은 조용해야 한다."""
        parsed = parse_chat(mobile([
            ("2025-08-20", "오후", "4:34", "김종원", "옛날 글"),
        ])).messages
        plan = bf.plan_merge(parsed, ARCHIVE)
        merged = ARCHIVE + [bf.to_record(m, 900 + i) for i, m in enumerate(plan.accepted)]
        merged.sort(key=lambda m: m["timestamp"])

        again = bf.plan_merge(parsed, merged)

        self.assertEqual(again.accepted, [])


class MediaLinkTest(unittest.TestCase):
    def test_does_not_overwrite_a_photo_we_already_have(self):
        images = [{"image_id": "img-000001", "assets": [{"sha256": "x"}]}]

        linked = bf.apply_media_links(images, [("img-000001", "c" * 64 + ".png")])

        self.assertEqual(linked, 0)
        self.assertNotIn("media_refs", images[0])

    def test_sha_index_finds_bytes_we_already_stored(self):
        images = [{"image_id": "img-1", "sha256": None, "local_path": None,
                   "assets": [{"sha256": "abc", "local_path": "assets/images/2026-05/a.png"}]}]

        self.assertEqual(bf.build_sha_index(images), {"abc": "assets/images/2026-05/a.png"})


class MonthlyTopicTest(unittest.TestCase):
    def test_groups_by_month_and_keeps_the_unsorted_id_shape(self):
        """classify_unsorted 는 t-unsorted-YYYY-MM-DD 형태만 미분류로 본다."""
        topics = {"threads": []}
        records = [
            {"id": "msg-002000", "date": "2025-08-20"},
            {"id": "msg-002001", "date": "2025-08-21"},
            {"id": "msg-002002", "date": "2025-09-01"},
        ]

        months = bf.assign_monthly(topics, records)

        self.assertEqual(months, 2)
        self.assertEqual([t["id"] for t in topics["threads"]],
                         ["t-unsorted-2025-08-01", "t-unsorted-2025-09-01"])
        self.assertEqual(topics["threads"][0]["message_ids"],
                         ["msg-002000", "msg-002001"])


class IdCollisionTest(unittest.TestCase):
    def test_next_number_uses_the_max_not_the_last_row(self):
        """합치기 뒤 파일은 시각 순이라 큰 번호가 중간에 있다."""
        from scripts import ingest_incremental as inc

        rows = [{"id": "msg-002000"}, {"id": "msg-000500"}]

        self.assertEqual(inc.next_message_number(rows), 2001)


if __name__ == "__main__":
    unittest.main()
