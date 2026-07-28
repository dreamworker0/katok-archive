# -*- coding: utf-8 -*-
"""파이프라인 위생 — 조용히 사고를 만드는 습관들을 검사로 막는다.

여기 있는 것은 기능이 아니라 **습관**에 대한 검사다. 기능 버그는 한 번 물면 눈에
보이는데, 이런 것은 몇 달 뒤에 엉뚱한 자리에서 터진다.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class WriteSiteSafetyTests(unittest.TestCase):
    """테스트가 사람이 보고 있는 `site/` 를 지우면 안 된다.

    `write_site` 는 대상 폴더를 통째로 지우고 다시 만든다. 인자 없이 부르면 진짜
    `site/` 가 사라진다 — 미리보기를 띄워 둔 채 테스트를 돌리다 하루에 세 번 물렸다.
    """

    def test_write_site_takes_a_destination(self):
        src = (ROOT / "scripts" / "build_site.py").read_text(encoding="utf-8")
        self.assertRegex(src, r"def write_site\(data: dict, dest")

    def test_no_test_writes_the_real_site(self):
        for path in sorted((ROOT / "tests").glob("test_*.py")):
            src = path.read_text(encoding="utf-8")
            for m in re.finditer(r"write_site\(([^)]*)\)", src):
                args = m.group(1)
                head = src[max(0, m.start() - 800):m.start()]
                with self.subTest(file=path.name, call=args[:40]):
                    self.assertTrue(
                        "," in args or 'mock.patch.object(build_site, "SITE"' in head,
                        "%s 가 진짜 site/ 에 쓴다 — 임시 폴더를 주거나 SITE 를 "
                        "patch 할 것" % path.name)


class DailyOrderTests(unittest.TestCase):
    """검사는 적재보다 **먼저** 돌아야 막을 수 있다."""

    def test_tests_run_before_upload(self):
        src = (ROOT / "scripts" / "run_daily.ps1").read_text(encoding="utf-8-sig")
        test_at = src.index("Invoke-Step '테스트'")
        upload_at = src.index("Invoke-Step 'Firestore 적재'")
        self.assertLess(test_at, upload_at,
                        "적재 뒤에 검사하면 이미 올라간 것을 두고 '틀렸다'고 말하는 셈")


class SharedJsonIoTests(unittest.TestCase):
    """공용으로 쓰는 것은 공용 자리에 둔다."""

    def test_build_site_json_helpers_come_from_the_shared_module(self):
        src = (ROOT / "scripts" / "build_site.py").read_text(encoding="utf-8")
        self.assertIn("_read_json = jsonio.read_json", src)
        self.assertIn("_read_jsonl = jsonio.read_jsonl", src)


class GhostFileTests(unittest.TestCase):
    """만든다고 적어 두고 아무도 만들지 않는 파일을 남기지 않는다."""

    def test_ingest_does_not_promise_conversation_md(self):
        src = (ROOT / "scripts" / "ingest_incremental.py").read_text(encoding="utf-8")
        self.assertNotIn("images.jsonl · conversation.md 갱신", src,
                         "ingest 는 conversation.md 를 만들지 않는다")

    def test_nothing_in_the_pipeline_writes_conversation_md_to_output(self):
        """스테이징(collect_chat)은 자기 폴더에 쓴다 — output/ 에 쓰는 곳이 없어야 한다."""
        for path in sorted((ROOT / "scripts").glob("*.py")):
            src = path.read_text(encoding="utf-8")
            for line in src.splitlines():
                if "conversation.md" not in line or line.lstrip().startswith("#"):
                    continue
                with self.subTest(file=path.name, line=line.strip()[:60]):
                    self.assertNotRegex(
                        line, r"OUTPUT\s*/\s*\"conversation\.md\"",
                        "%s 가 output/conversation.md 를 만든다" % path.name)


if __name__ == "__main__":
    unittest.main()
