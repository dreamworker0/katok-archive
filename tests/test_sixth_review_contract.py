# -*- coding: utf-8 -*-
"""외부 평가(agy) 6차 지적을 고친 자리. (2026-11-11)

1. 분류 요지가 삭제·숨김·보류된 주제까지 읽었다 — 첫 화면에 지워진 대화가 남을 수
   있었다. 이제 발행 대상만 읽고, 빠진 것이 생긴 분류는 보류하고 먼저 다시 쓴다.
2. 문서 크기 경고(80%)가 로그에만 있었다 — 관리 탭 사유 줄로 올린다.
3. 동기화 스크립트가 끝날 때 Firebase 연결을 닫지 않았다.
4. '새 버전' 과 '새 판' 알림이 같은 자리에 겹쳤다.
"""
from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts import digest_prose as dp  # noqa: E402
from scripts import report_cleanup as rc  # noqa: E402


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8-sig")


TOPICS = {"threads": [
    {"id": "t-1", "category": "hwp", "message_ids": ["m1", "m2"]},
    {"id": "t-2", "category": "hwp", "message_ids": ["m3"]},
    {"id": "t-3", "category": "projects", "message_ids": ["m4"]},
]}


class ExclusionFingerprintTests(unittest.TestCase):
    def test_nothing_excluded_means_no_fingerprint(self):
        self.assertEqual(rc.category_exclusion_fp(TOPICS, {"m1", "m2", "m3", "m4"}, set()), {})

    def test_only_the_category_that_lost_something_gets_one(self):
        fp = rc.category_exclusion_fp(TOPICS, {"m1", "m3", "m4"}, set())   # m2 빠짐
        self.assertEqual(list(fp), ["hwp"])

    def test_withheld_reports_count_too(self):
        fp1 = rc.category_exclusion_fp(TOPICS, {"m1", "m2", "m3", "m4"}, {"t-3"})
        self.assertEqual(list(fp1), ["projects"])

    def test_new_threads_do_not_change_it(self):
        more = {"threads": TOPICS["threads"] + [
            {"id": "t-9", "category": "hwp", "message_ids": ["m9"]}]}
        a = rc.category_exclusion_fp(TOPICS, {"m1", "m3", "m4"}, set())
        b = rc.category_exclusion_fp(more, {"m1", "m3", "m4", "m9"}, set())
        self.assertEqual(a, b, "새 주제마다 요지를 다시 쓰는 값을 치르지 않는다")


class WithholdDigestTests(unittest.TestCase):
    def digests(self, fp=""):
        return {"hwp": {"headline": "한 줄", "overview": "지워진 대화를 요약한 글",
                        "sections": [{"title": "절", "body": "본문"}], "keywords": ["가"],
                        "as_of": {"exclusion_fp": fp}},
                "projects": {"headline": "그대로", "overview": "그대로", "sections": [],
                             "keywords": [], "as_of": {}}}

    def test_digest_written_before_a_deletion_is_withheld(self):
        d = self.digests()
        got = rc.withhold_digests(d, {"hwp": "abc"})
        self.assertEqual(got, ["hwp"])
        self.assertEqual(d["hwp"]["overview"], rc.WITHHELD_DIGEST)
        self.assertEqual(d["hwp"]["sections"], [])
        self.assertEqual(d["projects"]["overview"], "그대로")

    def test_digest_rewritten_after_it_is_published_again(self):
        d = self.digests(fp="abc")
        self.assertEqual(rc.withhold_digests(d, {"hwp": "abc"}), [])

    def test_digest_prose_rewrites_that_category_first(self):
        cats = [{"id": "hwp", "label": "한글"}, {"id": "projects", "label": "프로젝트"}]
        threads = [{"id": "t-1", "category": "hwp"}, {"id": "t-3", "category": "projects"}]
        prose = {c: {"headline": "h", "overview": "o", "sections": [], "keywords": [],
                     "as_of": {"date": "2026-11-10", "thread_count": 1}}
                 for c in ("hwp", "projects")}
        got = dp.select_stale(cats, threads, prose, date(2026, 11, 11),
                              exclusion_fp={"hwp": "abc"})
        self.assertEqual(got, ["hwp"])


class WiringTests(unittest.TestCase):
    def test_digest_prose_reads_only_published_material(self):
        src = read("scripts/digest_prose.py")
        body = src[src.index("def load_state"):src.index("def facets_for")]
        self.assertIn("report_cleanup._current()", body)
        self.assertIn("if th[\"id\"] in withheld:", body)
        self.assertIn('"exclusion_fp": exclusion_fp', body)

    def test_payload_withholds_stale_digests(self):
        src = read("scripts/build_firestore_payload.py")
        self.assertIn("report_cleanup.withhold_digests(", src)
        self.assertLess(src.index("report_cleanup.withhold_digests("),
                        src.index('pii.mask_tree(data["digests"]'))

    def test_size_warnings_reach_the_reason_line(self):
        self.assertIn('print("SIZE_WARN=%d" % len(size_warns))',
                      read("scripts/build_firestore_payload.py"))
        self.assertIn("'^SIZE_WARN=(\\d+)$'", read("scripts/run_daily.ps1"))

    def test_sync_scripts_close_the_connection(self):
        for name in ("sync_members", "sync_member_requests", "sync_claims", "usage_rollup"):
            with self.subTest(script=name):
                self.assertIn(".then(() => admin.app().delete()", read("scripts/%s.js" % name))

    def test_only_one_toast_at_a_time(self):
        self.assertIn('.pwa-toast:not([hidden])', read("web/boot.js"))
        self.assertIn('.pwa-toast[data-kind="edition"]', read("web/pwa.js"))


if __name__ == "__main__":
    unittest.main()
