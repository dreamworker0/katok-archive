# -*- coding: utf-8 -*-
"""번들 캐시 계약 — boot.js 가 지문이 같으면 다시 받지 않고, 로그아웃하면 지우는가.

닫힌 IIFE 라 node 에서 부를 수 없어 글자로 본다(test_ui_contract 와 같은 사정).
동작은 로그인한 브라우저에서 봐야 한다 — 재방문에 Firestore 읽기가 meta 1회로 줄면 맞다.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOOT = (ROOT / "web" / "boot.js").read_text(encoding="utf-8")


class BundleCacheContractTest(unittest.TestCase):
    def test_uses_indexeddb_keyed_by_content_hash(self):
        self.assertIn("indexedDB.open", BOOT)
        self.assertIn("meta.content_hash", BOOT)
        self.assertIn("cached.content_hash === meta.content_hash", BOOT)

    def test_a_cache_failure_falls_back_to_the_server(self):
        """캐시가 안 열리는 환경(사생활 창·막힘)에서도 화면은 떠야 한다."""
        body = BOOT[BOOT.index("function readBundleCache"):BOOT.index("function writeBundleCache")]
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

    def test_cache_is_written_before_assembly_mutates_threads(self):
        """조립이 threads 에 ai_report 를 덧붙인다. 그 뒤에 저장하면 두 벌이 섞인다."""
        block = BOOT[BOOT.index("return fetchBundles(db).then("):]
        block = block[:block.index("return meta;")]
        self.assertLess(block.index("writeBundleCache"), block.index("assembleArchive"))

    def test_without_a_hash_nothing_is_cached(self):
        """옛 발행본(content_hash 없음)에서는 예전처럼 매번 받는다 — 낡은 캐시를 못 알아보니까."""
        self.assertIn("if (meta.content_hash) {", BOOT)
