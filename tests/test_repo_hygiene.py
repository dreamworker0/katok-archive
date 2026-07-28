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


class UploadCoverageTests(unittest.TestCase):
    """발행본이 가리키는 자료는 **전부** 업로드 목록에 들어야 한다.

    실측 2026-07-28: `videos` 를 빠뜨려 동영상 4개가 저장소에 올라간 적이 없었다.
    화면은 칸에 미리보기만 걸고, 눌러도 파일이 없어 재생되지 않았다 — 화면 코드는
    정상이었으므로 '왜 안 되지'가 오래 남을 종류의 사고다.
    """

    def test_upload_list_covers_images_thumbs_and_videos(self):
        src = (ROOT / "scripts" / "build_firestore_payload.py").read_text(encoding="utf-8")
        block = src[src.index("used_images: list[str] = []"):]
        block = block[:block.index("used_files")]
        for field in ("images", "thumbs", "videos"):
            with self.subTest(field=field):
                self.assertIn('m.get("%s")' % field, block,
                              "업로드 목록이 %s 를 빠뜨린다" % field)

    def test_uploader_knows_video_content_types(self):
        src = (ROOT / "scripts" / "upload_firestore.js").read_text(encoding="utf-8")
        # mp4 를 image/jpeg 로 올리면 브라우저가 재생하지 않는다
        self.assertIn('".mp4": "video/mp4"', src)

    def test_uploader_indexes_every_storage_prefix_it_uploads_to(self):
        """올리는 곳은 원격 목록도 받아야 한다.

        목록이 없으면 '이미 있음' 판정을 못 해 매일 밤 같은 파일을 다시 올린다.
        thumbs 에서 한 번 겪고 주석까지 남겼는데 videos 에서 똑같이 겪었다(14MB/일).
        """
        src = (ROOT / "scripts" / "upload_firestore.js").read_text(encoding="utf-8")
        for prefix in ("images/", "thumbs/", "videos/", "files/"):
            with self.subTest(prefix=prefix):
                self.assertIn('remoteIndex(bucket, "%s")' % prefix, src)


class PreferenceRuleTests(unittest.TestCase):
    """'관심 주제 빠지기' 스위치가 규칙에 막히지 않는지.

    규칙이 막으면 저장이 조용히 실패하고 화면은 "저장했습니다"라고 말한다 — 사람이
    눌러 보기 전까지 아무도 모른다. 제대로 검증하려면 `scripts/test_rules.js`
    (권한 필요)를 써야 하고, 여기서는 규칙 글이 그 필드를 허용하는지만 본다.
    """

    @classmethod
    def setUpClass(cls):
        src = (ROOT / "firestore.rules").read_text(encoding="utf-8")
        start = src.index("match /preferences/")
        cls.block = src[start:src.index("match /", start + 10)]

    def test_hide_interests_is_an_allowed_field(self):
        self.assertIn("hideInterests", self.block)
        self.assertIn("hasOnly(['collection', 'hideInterests', 'updatedAt'])", self.block)

    def test_hide_interests_must_be_a_boolean(self):
        self.assertIn("hideInterests is bool", self.block)

    def test_client_sends_exactly_the_allowed_fields(self):
        """화면이 보내는 필드와 규칙이 허용하는 필드가 같아야 한다."""
        boot = (ROOT / "web" / "boot.js").read_text(encoding="utf-8")
        block = boot[boot.index("savePreferences"):]
        block = block[:block.index("},")]
        for field in ("collection", "hideInterests", "updatedAt"):
            with self.subTest(field=field):
                self.assertIn(field, block)


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
