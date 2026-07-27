# -*- coding: utf-8 -*-
"""보고서 문단과 링크·사진 메시지의 문맥 연결."""

import unittest

from scripts.topic_reports import content_chars, place_context_anchors, thin_reports


class ContextAnchorTest(unittest.TestCase):
    def test_link_from_same_message_is_placed_after_matching_quote(self):
        report = (
            "## AI 윤리로\n\n"
            "> 일반적으로 AI가 공리주의적 사고에 기반한 응답을 합니다."
        )
        messages = [
            {
                "id": "msg-001480",
                "nickname": "가온",
                "text": (
                    "일반적으로 AI가 공리주의적 사고에 기반한 응답을 합니다.\n"
                    "https://youtu.be/demo"
                ),
                "urls": ["https://youtu.be/demo"],
                "kind": "text",
            }
        ]

        self.assertEqual(
            place_context_anchors(report, messages),
            report + "\n\n![[link:msg-001480]]",
        )

    def test_manual_media_anchor_is_preserved_without_duplicate(self):
        report = (
            "사진을 보며 구조를 설명했다.\n\n"
            "![[msg-000123]]\n\n"
            "다음 이야기로 넘어갔다."
        )
        messages = [
            {
                "id": "msg-000122",
                "nickname": "김종원",
                "text": "사진을 보며 구조를 설명했다.",
                "urls": [],
                "kind": "text",
            },
            {
                "id": "msg-000123",
                "nickname": "김종원",
                "text": "",
                "urls": [],
                "kind": "image",
                "images": ["assets/images/demo.png"],
            },
        ]

        result = place_context_anchors(report, messages)

        self.assertEqual(result, report)
        self.assertEqual(result.count("![[msg-000123]]"), 1)

    def test_nearby_same_author_image_uses_the_matching_paragraph(self):
        report = (
            "김종원은 기관에서 사용할 신청 화면의 구성을 자세히 설명했다.\n\n"
            "이후 비용 문제를 논의했다."
        )
        messages = [
            {
                "id": "msg-000200",
                "nickname": "김종원",
                "text": "기관에서 사용할 신청 화면의 구성을 자세히 설명했다.",
                "urls": [],
                "kind": "text",
            },
            {
                "id": "msg-000201",
                "nickname": "김종원",
                "text": "",
                "urls": [],
                "kind": "image",
                "images": ["assets/images/form.png"],
            },
        ]

        self.assertEqual(
            place_context_anchors(report, messages),
            (
                "김종원은 기관에서 사용할 신청 화면의 구성을 자세히 설명했다.\n\n"
                "![[msg-000201]]\n\n"
                "이후 비용 문제를 논의했다."
            ),
        )

    def test_ambiguous_image_stays_unanchored(self):
        report = (
            "배포 화면을 함께 확인했다.\n\n"
            "배포 화면을 다시 확인했다."
        )
        messages = [
            {
                "id": "msg-000300",
                "nickname": "김종원",
                "text": "배포 화면을 함께 확인했다.",
                "urls": [],
                "kind": "text",
            },
            {
                "id": "msg-000301",
                "nickname": "김종원",
                "text": "",
                "urls": [],
                "kind": "image",
                "images": ["assets/images/deploy.png"],
            },
            {
                "id": "msg-000302",
                "nickname": "김종원",
                "text": "배포 화면을 다시 확인했다.",
                "urls": [],
                "kind": "text",
            },
        ]

        self.assertEqual(place_context_anchors(report, messages), report)

    def test_short_generic_link_message_does_not_force_a_match(self):
        report = "관련 자료를 공유했다.\n\n다음 주제로 넘어갔다."
        messages = [
            {
                "id": "msg-000400",
                "nickname": "윤가온",
                "text": "관련 자료\nhttps://example.com",
                "urls": ["https://example.com"],
                "kind": "text",
            }
        ]

        self.assertEqual(place_context_anchors(report, messages), report)


class ContentCharsTest(unittest.TestCase):
    """'보고서가 얇은가'의 기준이 되는 값이라, 요약할 수 없는 것은 세면 안 된다."""

    def test_link_and_photo_placeholders_do_not_count(self):
        self.assertEqual(content_chars("사진"), 0)
        self.assertEqual(content_chars("사진 3장"), 0)
        self.assertEqual(content_chars("동영상"), 0)
        self.assertEqual(
            content_chars("https://script.google.com/macros/s/AKfycbyKIWGSQ/exec"), 0
        )

    def test_counts_only_the_words_around_a_link(self):
        self.assertEqual(content_chars("링크 보세요 https://a.com/very/long/path 확인"), 7)

    def test_thin_check_stops_demanding_length_when_there_is_nothing_to_summarize(self):
        """실측 t-214: 3건 108자로 잡혔지만 실제 내용은 한 줄이었다.

        링크와 '사진'을 세면 요약할 것이 없는 주제에 분량을 요구하게 되고,
        그건 없는 내용을 지어내라는 말이 된다.
        """
        thread = [{"id": "t-1", "count": 3, "report": "김종원이 강의 녹화 링크를 올렸다."}]
        texts = ["https://drive.google.com/file/d/1PrQQxoy_5mDCrHMgKKsAatVrpSoCq/view",
                 "사진", "이 강의 녹화해놨어요. 시간되실 때 보세요."]

        naive = thin_reports(thread, {"t-1": sum(len(t) for t in texts)})
        honest = thin_reports(thread, {"t-1": sum(content_chars(t) for t in texts)})

        self.assertEqual([x[0] for x in naive], ["t-1"])   # 예전 기준: 얇다고 잡힌다
        self.assertEqual(honest, [])                        # 새 기준: 이 정도면 충분하다


if __name__ == "__main__":
    unittest.main()
