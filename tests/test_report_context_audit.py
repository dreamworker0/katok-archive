# -*- coding: utf-8 -*-
"""보고서 문맥 자리표 전체 감사."""

import unittest

from scripts.audit_report_context import audit_context, audit_exit_code


class ReportContextAuditTest(unittest.TestCase):
    def test_counts_inline_fallback_invalid_and_duplicate_resources(self):
        threads = [
            {
                "id": "t-001",
                "report": (
                    "관련 문단\n\n"
                    "![[link:msg-link]]\n\n"
                    "![[msg-image]]\n\n"
                    "![[msg-missing]]\n\n"
                    "![[link:msg-link]]"
                ),
                "links": [
                    {"id": "msg-link", "url": "https://example.com/a"},
                    {"id": "msg-fallback", "url": "https://example.com/b"},
                ],
            }
        ]
        media = [
            {"id": "msg-image", "thread_id": "t-001", "kind": "image"},
            {"id": "msg-media-fallback", "thread_id": "t-001", "kind": "image"},
        ]

        result = audit_context(threads, media)

        self.assertEqual(result["reports"], 1)
        self.assertEqual(result["links_inline"], 1)
        self.assertEqual(result["links_fallback"], 1)
        self.assertEqual(result["media_inline"], 1)
        self.assertEqual(result["media_fallback"], 1)
        self.assertEqual(result["invalid_anchors"], ["t-001:msg-missing"])
        self.assertEqual(result["duplicate_anchors"], ["t-001:link:msg-link"])
        self.assertEqual(audit_exit_code(result), 1)

    def test_clean_fallback_resources_do_not_fail_the_audit(self):
        result = audit_context(
            [{
                "id": "t-002",
                "report": "자료가 어디에 속하는지 분명하지 않다.",
                "links": [{"id": "msg-link", "url": "https://example.com"}],
            }],
            [{"id": "msg-image", "thread_id": "t-002", "kind": "image"}],
        )

        self.assertEqual(result["invalid_anchors"], [])
        self.assertEqual(result["duplicate_anchors"], [])
        self.assertEqual(result["links_fallback"], 1)
        self.assertEqual(result["media_fallback"], 1)
        self.assertEqual(audit_exit_code(result), 0)

    def test_known_but_not_yet_collected_image_is_pending_not_invalid(self):
        result = audit_context(
            [{
                "id": "t-003",
                "report": "사진을 설명했다.\n\n![[msg-pending]]",
                "links": [],
            }],
            [],
            expected_media_ids={"msg-pending"},
        )

        self.assertEqual(result["invalid_anchors"], [])
        self.assertEqual(result["pending_anchors"], ["t-003:msg-pending"])
        self.assertEqual(audit_exit_code(result), 0)


if __name__ == "__main__":
    unittest.main()
