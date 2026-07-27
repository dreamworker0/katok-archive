import unittest

from scripts.kakao_parser import parse_chat


SAMPLE = """방 이름 님과 카카오톡 대화
저장한 날짜 : 2026-07-23 21:12:40

--------------- 2026년 3월 8일 일요일 ---------------
[김 종원] [오전 9:48] 사진
[김 종원] [오전 9:48] 첫 줄
둘째 줄 https://example.com/a
[한도윤 (관리자)] [오후 12:00] 파일: 계획서.md
홍길동님이 새사용자님을 초대했습니다.
[김 종원] [오후 1:00] 동영상
[김 종원] [오후 1:01] 이모티콘
"""


class ParseChatTests(unittest.TestCase):
    def test_preserves_image_text_file_and_multiline_messages(self):
        result = parse_chat(SAMPLE)

        self.assertEqual([m.kind for m in result.messages],
                         ["image", "text", "file", "video"])
        self.assertEqual(result.messages[0].nickname, "김 종원")
        self.assertEqual(result.messages[0].image_id, "img-000001")
        # 동영상도 미디어 대장에 자리를 받는다 — 사진과 같은 열쇠를 쓴다
        self.assertEqual(result.messages[3].image_id, "img-000004")
        self.assertEqual(result.messages[1].text, "첫 줄\n둘째 줄 https://example.com/a")
        self.assertEqual(result.messages[1].urls, ["https://example.com/a"])
        self.assertEqual(result.messages[2].nickname, "한도윤 (관리자)")
        self.assertEqual(result.messages[2].time, "12:00")

    def test_excludes_emoticon_and_system_event_but_keeps_video(self):
        """동영상은 2026-07-27 부터 수집한다.

        그 전에는 버렸는데, 사진은 '그 자체가 공유된 결과물' 이라 남기면서 동영상만
        버릴 이유가 없다는 판단으로 바꿨다. 이모티콘은 계속 버린다 — 내용이 없다.
        """
        result = parse_chat(SAMPLE)

        self.assertEqual(result.excluded["video"], 0)
        self.assertEqual(result.excluded["emoticon"], 1)
        self.assertEqual(result.excluded["system"], 1)

    def test_converts_midnight_and_noon(self):
        text = """--------------- 2026년 7월 23일 목요일 ---------------
[A] [오전 12:01] 자정 이후
[B] [오후 12:01] 정오 이후
"""
        result = parse_chat(text)

        self.assertEqual(result.messages[0].time, "00:01")
        self.assertEqual(result.messages[1].time, "12:01")
        self.assertTrue(result.messages[0].timestamp.endswith("+09:00"))

    def test_warns_about_message_before_first_date(self):
        result = parse_chat("[A] [오전 9:00] 날짜 없는 메시지")

        self.assertEqual(result.messages, [])
        self.assertEqual(result.warnings[0]["reason"], "message_before_date")

    def test_deleted_message_notice_does_not_attach_to_previous_photo(self):
        result = parse_chat(
            """--------------- 2026년 7월 23일 목요일 ---------------
[A] [오후 4:30] 사진
메시지가 삭제되었습니다.
[A] [오후 4:31] 다음 메시지
"""
        )

        self.assertEqual(result.messages[0].kind, "image")
        self.assertEqual(result.messages[0].text, "사진")
        self.assertEqual(result.excluded["system"], 1)

    def test_classifies_multi_photo_album_and_preserves_expected_count(self):
        result = parse_chat(
            """--------------- 2026년 7월 23일 목요일 ---------------
[A] [오후 4:30] 사진 7장
"""
        )

        self.assertEqual(result.messages[0].kind, "image")
        self.assertEqual(result.messages[0].image_count, 7)
        self.assertEqual(result.messages[0].image_id, "img-000001")


if __name__ == "__main__":
    unittest.main()
