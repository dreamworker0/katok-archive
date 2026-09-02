# -*- coding: utf-8 -*-
"""번들 캐시·지연 로드 계약 — boot.js 와 app.js 의 글자를 본다.

동작은 tests/boot_cache.test.js 가 가짜 Firestore·IndexedDB 로 실제로 돌려 본다
(첫 방문 7회 읽기 → 재방문 2회). 여기서는 그 검사가 못 보는 모양을 지킨다.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOOT = (ROOT / "web" / "boot.js").read_text(encoding="utf-8")
APP = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
SUMMARY = (ROOT / "web" / "summary.js").read_text(encoding="utf-8")


class BundleCacheContractTest(unittest.TestCase):
    def test_uses_indexeddb_keyed_by_content_hash(self):
        self.assertIn("indexedDB.open", BOOT)
        self.assertIn("meta.content_hash", BOOT)
        self.assertIn("c.content_hash === hash", BOOT)

    def test_a_cache_failure_falls_back_to_the_server(self):
        """캐시가 안 열리는 환경(사생활 창·막힘)에서도 화면은 떠야 한다."""
        body = BOOT[BOOT.index("function readPart"):BOOT.index("function writePart")]
        self.assertIn(".catch(", body)
        self.assertIn("return null", body)

    def test_cache_is_cleared_on_sign_out(self):
        """멤버 전용 내용이 공용 컴퓨터의 브라우저에 남으면 안 된다."""
        sign_out = BOOT[BOOT.index("signOut: function ()"):]
        sign_out = sign_out[:sign_out.index("},")]
        self.assertIn("clearBundleCache", sign_out)
        signed_out_branch = BOOT[BOOT.index("if (user) onSignedIn(user);"):]
        signed_out_branch = signed_out_branch[:signed_out_branch.index("gateSignIn();")]
        self.assertIn("clearBundleCache", signed_out_branch)

    def test_without_a_hash_nothing_is_cached(self):
        """옛 발행본(content_hash 없음)에서는 예전처럼 매번 받는다 — 낡은 캐시를 못 알아보니까."""
        self.assertIn("if (hash && data) writePart(", BOOT)


class LazyLoadContractTest(unittest.TestCase):
    def test_heavy_parts_load_after_the_app_starts(self):
        """요지 1.7MB·AI 주석 1MB 는 첫 화면이 그리지 않는다. 화면을 띄운 뒤 받는다."""
        block = BOOT[BOOT.index("ensureClaim(user).then("):]
        block = block[:block.index("gateError(")]
        self.assertLess(block.index("start(user, member)"), block.index("loadRest(db, meta)"))
        core = BOOT[BOOT.index("function fetchCore"):BOOT.index("function fetchDigests")]
        self.assertNotIn('"digests"', core)
        self.assertNotIn('"aiReports"', core)

    def test_app_takes_the_parts_when_they_arrive(self):
        self.assertIn("attachDigests: attachDigests", APP)
        self.assertIn("attachAiReports: attachAiReports", APP)
        for name in ("attachDigests", "attachAiReports"):
            self.assertIn("app.%s(" % name, BOOT)

    def test_summary_waits_instead_of_saying_empty(self):
        """요지가 오기 전의 요지 화면은 '비었다' 가 아니라 '오는 중' 이다."""
        body = SUMMARY[SUMMARY.index("function renderSummary()"):SUMMARY.index("function renderDoc(")]
        self.assertIn("state.digestsPending", body)
        self.assertIn("요지를 불러오는 중", body)
        self.assertIn("state.digestsPending = !!(A.lazy && A.lazy.digests)", APP)

    def test_ai_buttons_are_patched_in_not_redrawn(self):
        """읽던 자리와 펼친 카드를 날리지 않는다 — 단추만 끼운다."""
        body = APP[APP.index("function attachAiReports"):APP.index("function aiReportBlock")]
        self.assertIn("patchAiButtons(el.view)", body)
        self.assertNotIn("render()", body)
        patch = APP[APP.index("function patchAiButtons"):APP.index("function attachDigests")]
        self.assertIn("bindAiToggle(", patch)

    def test_ai_failure_is_not_fatal(self):
        """곁딸린 글 하나 때문에 본문 전체가 안 보이는 것은 맞바꿀 만한 일이 아니다."""
        body = BOOT[BOOT.index("function fetchAiReports"):BOOT.index("function assembleArchive")]
        self.assertIn(".catch(", body)
        self.assertIn("return null", body)
