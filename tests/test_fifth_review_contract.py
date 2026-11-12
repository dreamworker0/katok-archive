# -*- coding: utf-8 -*-
"""외부 평가(agy) 5차 지적을 고친 자리가 조용히 되돌아가지 않게 본다. (2026-11-11)

창을 띄우거나 OCR 엔진·Firebase 를 부르지 않는 계약 검사라 CI 에서 돈다. 동작
자체는 고칠 때 실제로 돌려 확인했다(작은 사진 61줄 → 2배 확대 68줄, 캐시 비우기 대기).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8-sig")


class OcrContractTests(unittest.TestCase):
    """사진 개인정보 검사(ocr_images.ps1)."""

    def setUp(self):
        self.src = read("scripts/ocr_images.ps1")

    def test_small_photos_are_really_upscaled(self):
        # -Scale 은 돌려줄 좌표만 나눈다 — 실제로 키운 그림을 넘겨야 한다
        self.assertIn("function Read-Upscaled", self.src)
        body = self.src[self.src.index("function Read-Upscaled"):]
        body = body[:body.index("function Split-TallImage")]
        self.assertIn("($Width * 2), ($Height * 2)", body)
        self.assertIn("Read-Upscaled -Path $f.FullName", self.src)
        # 배열로 한 겹 싸서 돌려주면 @( ) 안에서 System.Object[] 가 된다
        self.assertNotIn(", @(Get-OcrLines", body)

    def test_unreadable_by_gdi_falls_back_to_winrt(self):
        # .webp 처럼 System.Drawing 이 못 여는 사진도 OCR 엔진에 원본을 바로 넘긴다
        self.assertRegex(self.src, r"if \(\$w -eq 0\) \{\s*\$lines = @\(Get-OcrLines -Path \$f\.FullName")

    def test_results_are_written_atomically_and_a_broken_file_does_not_stop_the_night(self):
        save = self.src[self.src.index("function Save-Json"):]
        save = save[:save.index("\n}\n") if "\n}\n" in save else 800]
        self.assertIn('$tmp = "$Path.tmp"', save)
        # 백업 경로에 $null 을 넘기면 PowerShell 이 "" 로 바꿔 Replace 가 죽는다
        # (2026-11-11 밤 갱신이 여기서 멈췄다). 진짜 null 은 [NullString]::Value.
        self.assertIn("[System.IO.File]::Replace($tmp, $Path, [NullString]::Value)", save)
        self.assertNotRegex(save, r"Replace\([^)]*\$null\)")
        self.assertIn(".broken-", self.src)

    @unittest.skipUnless(shutil.which("powershell"), "Windows PowerShell 이 없다")
    def test_save_json_actually_overwrites_an_existing_file(self):
        # 문자열 검사만으로는 위 사고를 못 잡았다 — 실제로 두 번 써서 덮어쓰기를 본다.
        save = self.src[self.src.index("function Save-Json"):]
        save = save[:save.index("\n}\n") + 3]
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, "x.json")
            script = os.path.join(d, "t.ps1")
            with open(script, "w", encoding="utf-8-sig") as f:
                f.write(save + "\n$ErrorActionPreference='Stop'\n"
                        "Save-Json @{a=1} $args[0]\nSave-Json @{a=2} $args[0]\n")
            r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                                "-File", script, target], capture_output=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace"))
            with open(target, encoding="utf-8") as f:
                self.assertEqual(json.load(f), {"a": 2})
            self.assertFalse(os.path.exists(target + ".tmp"))


class SecretEnvTests(unittest.TestCase):
    """AI 자식 프로세스에 디스코드 웹훅 주소를 넘기지 않는다."""

    def test_every_child_env_filter_drops_webhooks(self):
        for rel in ("scripts/llm.py", "scripts/verify_answer.py", "scripts/ask_worker.js"):
            with self.subTest(file=rel):
                line = next(ln for ln in read(rel).splitlines()
                            if "TOKEN|KEY|SECRET" in ln)
                self.assertIn("WEBHOOK", line)

    def test_llm_child_env_really_drops_it(self):
        import os
        from unittest import mock
        from scripts import llm
        with mock.patch.dict(os.environ, {"KATOK_NOTIFY_WEBHOOK": "https://x", "PLAIN": "1"}):
            env = llm.child_env()
        self.assertNotIn("KATOK_NOTIFY_WEBHOOK", env)
        self.assertEqual(env.get("PLAIN"), "1")


class NightlyWarnTests(unittest.TestCase):
    """실패를 삼키는 단계는 모두 관리 탭 사유 줄에 올린다."""

    def test_remaining_steps_reach_the_reason_line(self):
        daily = read("scripts/run_daily.ps1")
        for label in ("사용 기록 접기 실패", "답장 관계 수집 실패", "주제 분류 실패",
                      "AI 검증 주석 실패", "보조 분류 실패", "요지 산문 실패",
                      "관계망 근거 실패"):
            with self.subTest(step=label):
                self.assertRegex(daily, r'Add-StepWarnQuiet "%s\(exit' % re.escape(label))
        self.assertLess(daily.index("function Add-StepWarnQuiet"),
                        daily.index("# 0) 사용 기록 접기"))


class CliRemoveTests(unittest.TestCase):
    """명령줄 탈퇴(approve_claims --remove)는 웹 관리 탭과 같은 길로."""

    def test_cli_uses_the_same_guard_and_revokes_tokens(self):
        src = read("scripts/approve_claims.js")
        body = src[src.index("async function removeMembers"):]
        body = body[:body.index("async function reject")]
        self.assertIn("guards.removeMember(db, email", body)
        self.assertIn("revokeRefreshTokens(user.uid)", body)
        self.assertNotIn('collection("members").doc(email).delete()', body)


class RulesAndCacheTests(unittest.TestCase):
    def test_rules_check_covers_ai_reports(self):
        self.assertIn('"graph", "aiReports"]', read("scripts/test_rules.js"))

    def test_logout_waits_for_the_cache_to_be_cleared(self):
        src = read("web/pwa.js")
        body = src[src.index("function clearCaches"):][:900]
        self.assertIn("return caches.keys().then", body)
        self.assertIn("caches.delete(name)", body)


if __name__ == "__main__":
    unittest.main()
