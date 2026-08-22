# -*- coding: utf-8 -*-
"""작업 폴더 마름질 — 지우는 코드라서 검사가 필요하다.

이 스크립트는 파일을 지운다. 되돌릴 수 없는 쪽이므로 두 방향을 함께 본다.

  지워야 할 것을 지우는가   넉 주 된 카톡 창 스크린샷이 남아 있으면 이 스크립트는
                            있으나 마나다.
  지워선 안 될 것을 남기는가 실측 2026-08-22: 마름질 대상 폴더 793MB 중 766MB 가
                            중복이었지만, 나머지에 아카이브에 아예 없는 사진 1장과
                            동영상 1개가 있었다. 폴더째 지웠으면 영구 소실이다.

두 번째가 더 중요하다. 안 지운 실수는 다음 날 지우면 되지만, 지운 실수는 그것으로
끝이다.
"""
import json
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts import prune_workspace as pw

TODAY = date(2026, 8, 22)


class LogRetentionTest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.logs = Path(self._tmp.name)
        self._p = patch.object(pw, "LOGS", self.logs)
        self._p.start()

    def tearDown(self):
        self._p.stop()
        self._tmp.cleanup()

    def touch(self, name: str) -> Path:
        p = self.logs / name
        p.write_text("x", encoding="utf-8")
        return p

    def names(self, **kw):
        return sorted(p.name for p, _ in pw.plan_logs(TODAY, **kw))

    def test_old_screenshots_go(self):
        self.touch("abort-20260725-155003.png")     # 28일
        self.touch("abort-20260820-101010.png")     # 2일
        self.assertEqual(self.names(), ["abort-20260725-155003.png"])

    def test_screenshots_are_kept_shorter_than_logs(self):
        """스크린샷에는 대화 내용이 담긴다. 텍스트 로그와 같은 기간을 둘 이유가 없다."""
        self.touch("abort-20260801-120000.png")     # 21일
        self.touch("daily-20260801.log")            # 21일
        self.assertEqual(self.names(), ["abort-20260801-120000.png"])

    def test_old_logs_go_too(self):
        self.touch("daily-20260101.log")            # 반년 넘음
        self.touch("daily-20260820.log")
        self.assertEqual(self.names(), ["daily-20260101.log"])

    def test_the_lock_file_is_never_touched(self):
        """도는 중인 실행이 붙들고 있는 파일이다. 지우면 겹쳐 도는 것을 못 막는다."""
        self.touch("run_daily.lock")
        self.assertEqual(self.names(), [])

    def test_the_drawer_folder_is_never_touched(self):
        (self.logs / "drawer").mkdir()
        self.assertEqual(self.names(), [])

    def test_a_name_without_a_date_is_left_alone(self):
        """날짜를 못 읽으면 손대지 않는다 — 무엇인지 모르는 파일을 지우지 않는다."""
        self.touch("retag-2026-08-21-v2.log")   # YYYYMMDD 가 아니다
        self.touch("메모.txt")
        self.assertEqual(self.names(), [])

    def test_the_boundary_day_survives(self):
        """보관 기간과 정확히 같은 날은 남긴다 — 경계에서 하루를 더 주는 쪽으로."""
        self.touch("abort-20260808-120000.png")   # 정확히 14일
        self.assertEqual(self.names(), [])

    def test_retention_is_adjustable(self):
        self.touch("abort-20260820-101010.png")   # 2일
        self.assertEqual(self.names(shot_days=1), ["abort-20260820-101010.png"])

    def test_file_time_is_not_used(self):
        """백신이나 백업 도구가 훑고 지나가면 mtime 이 오늘로 바뀐다.

        그때 이름의 날짜를 안 보면 넉 주 된 스크린샷이 영영 안 지워진다.
        """
        p = self.touch("abort-20260725-155003.png")
        p.touch()   # mtime 을 지금으로
        self.assertEqual(self.names(), ["abort-20260725-155003.png"])


class BackupRetentionTest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.out = Path(self._tmp.name)
        self._p = patch.object(pw, "OUT", self.out)
        self._p.start()

    def tearDown(self):
        self._p.stop()
        self._tmp.cleanup()

    def mk(self, name: str):
        (self.out / name).mkdir()

    def names(self, keep=pw.BACKUP_KEEP):
        return sorted(p.name for p, _ in pw.plan_backups(keep))

    def test_counts_per_kind_not_overall(self):
        """종류가 다른 수술은 서로의 되돌릴 지점을 밀어내지 않는다.

        전체로 세면 태그 백업 세 개가 반년 전 재분류 백업을 밀어낸다 — 둘은
        되돌리는 대상이 다르다.
        """
        for d in ("20260801", "20260810", "20260815", "20260820"):
            self.mk("backup-retag-" + d)
        self.mk("backup-reclassify-20260728")
        self.assertEqual(self.names(keep=3), ["backup-retag-20260801"])

    def test_keeps_the_newest(self):
        for d in ("20260801", "20260810", "20260820"):
            self.mk("backup-split-" + d)
        self.assertEqual(self.names(keep=1),
                         ["backup-split-20260801", "backup-split-20260810"])

    def test_kind_with_a_hyphen_stays_one_kind(self):
        """`backup-threadfit-medium-20260806` 의 종류는 `threadfit-medium` 이다."""
        self.mk("backup-threadfit-20260806")
        self.mk("backup-threadfit-medium-20260806")
        self.assertEqual(self.names(keep=1), [])

    def test_files_are_not_mistaken_for_backup_folders(self):
        (self.out / "backup-state-20260101.json").write_text("{}", encoding="utf-8")
        self.assertEqual(self.names(keep=0), [])


class AssetsAreProtectedTest(unittest.TestCase):
    """중복만 지운다. 이 검사가 이 파일의 존재 이유다."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.assets = Path(self._tmp.name)
        (self.assets / "images").mkdir()
        (self.assets / "staging").mkdir()
        self._p = patch.object(pw, "ASSETS", self.assets)
        self._p.start()

    def tearDown(self):
        self._p.stop()
        self._tmp.cleanup()

    def test_only_byte_identical_copies_are_removed(self):
        (self.assets / "images" / "a.jpg").write_bytes(b"AAAA")
        # 이름이 달라도 내용이 같으면 중복이다 — staging 은 해시로 이름을 짓는다.
        (self.assets / "staging" / "deadbeef.jpg").write_bytes(b"AAAA")
        dup, orphan = pw.plan_assets()
        self.assertEqual([p.name for p, _ in dup], ["deadbeef.jpg"])
        self.assertEqual(orphan, [])

    def test_a_file_the_archive_does_not_have_is_kept_and_reported(self):
        """실제로 이런 파일이 있었다 — 사진 1장(11.9MB)과 동영상 1개(2.5MB)."""
        (self.assets / "images" / "a.jpg").write_bytes(b"AAAA")
        (self.assets / "staging" / "only-here.mp4").write_bytes(b"BBBB")
        dup, orphan = pw.plan_assets()
        self.assertEqual(dup, [])
        self.assertEqual([p.name for p, _ in orphan], ["only-here.mp4"])

    def test_same_size_is_not_enough(self):
        """크기만 보면 다른 사진을 중복으로 판정한다. 해시로 봐야 한다."""
        (self.assets / "images" / "a.jpg").write_bytes(b"AAAA")
        (self.assets / "staging" / "b.jpg").write_bytes(b"AAAB")
        dup, orphan = pw.plan_assets()
        self.assertEqual(dup, [])
        self.assertEqual(len(orphan), 1)

    def test_export_folders_are_matched_loosely(self):
        """폴더명은 기기와 판마다 다르다 — Chats/Chat, 대소문자까지 갈렸다.

        좁게 잡으면 다음 폴더가 그물을 빠져나간다(.gitignore 가 같은 함정에
        두 번 빠졌다).
        """
        (self.assets / "images" / "a.jpg").write_bytes(b"AAAA")
        for name in ("KakaoTalk_Chats_2026-07-27_x", "Kakaotalk_Chat_어쩌고_20260721"):
            d = self.assets / name
            d.mkdir()
            (d / "dup.png").write_bytes(b"AAAA")
        dup, _ = pw.plan_assets()
        self.assertEqual(len(dup), 2)

    def test_videos_and_files_count_as_archived(self):
        """보관본은 images 만이 아니다. 동영상·첨부도 이미 보관된 것이다."""
        (self.assets / "videos").mkdir()
        (self.assets / "files").mkdir()
        (self.assets / "videos" / "v.mp4").write_bytes(b"VVVV")
        (self.assets / "files" / "f.pdf").write_bytes(b"FFFF")
        (self.assets / "staging" / "v2.mp4").write_bytes(b"VVVV")
        (self.assets / "staging" / "f2.pdf").write_bytes(b"FFFF")
        dup, orphan = pw.plan_assets()
        self.assertEqual(len(dup), 2)
        self.assertEqual(orphan, [])


class UnreferencedTest(unittest.TestCase):
    """원장이 가리키지 않는 보관본 파일 — 가장 위험한 판정이다.

    "원장에 없으면 지운다" 는 기준은 원장을 잘못 읽는 순간 보관본 전체를 지울
    것으로 만든다. 실측 2026-08-22: `assets/` 를 절대 경로로 들고 있어서 원장의
    상대 경로와 하나도 안 맞았고, 사진 335장·첨부 21개를 포함한 684개(649MB)가
    전부 '원장에 없음' 으로 잡혔다. 기본이 '계획만' 이어서 살았다.

    그래서 여기서 보는 것은 "지울 것을 찾는가" 보다 "안 지울 것을 지키는가" 다.
    """

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.assets = self.root / "assets"
        for d in ("images", "videos", "thumbs", "files"):
            (self.assets / d).mkdir(parents=True)
        self.out = self.root / "output"
        self.out.mkdir()
        self._p = [patch.object(pw, "ROOT", self.root),
                   patch.object(pw, "ASSETS", self.assets),
                   patch.object(pw, "OUT", self.out)]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()
        self._tmp.cleanup()

    def ledger(self, rows):
        (self.out / "images.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
            encoding="utf-8")

    def put(self, rel: str, data: bytes) -> Path:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p

    def test_finds_a_duplicate_the_ledger_forgot(self):
        """옛 백업을 합칠 때 같은 동영상이 새 image_id 로 또 들어왔다."""
        self.put("assets/videos/2026-03/img-1-01.mp4", b"VIDEO")
        self.put("assets/videos/2026-03/img-9-01.mp4", b"VIDEO")   # 원장에 없음
        self.ledger([{"local_path": "assets/videos/2026-03/img-1-01.mp4"}])
        doomed, unique = pw.plan_unreferenced()
        self.assertEqual([p.name for p, _ in doomed], ["img-9-01.mp4"])
        self.assertEqual(unique, [])

    def test_a_unique_unreferenced_file_is_kept(self):
        """원장에서 빠진 것일 수 있다. 마름질할 쓰레기가 아니다."""
        self.put("assets/videos/2026-03/img-1-01.mp4", b"VIDEO")
        self.put("assets/videos/2026-03/img-9-01.mp4", b"OTHER")
        self.ledger([{"local_path": "assets/videos/2026-03/img-1-01.mp4"}])
        doomed, unique = pw.plan_unreferenced()
        self.assertEqual(doomed, [])
        self.assertEqual([p.name for p, _ in unique], ["img-9-01.mp4"])

    def test_paths_are_compared_relative_to_the_repo(self):
        """절대/상대 경로가 어긋나면 보관본 전체가 지울 것이 된다.

        이 검사가 이 클래스의 존재 이유다. 어긋난 채로 돌면 참조된 파일까지
        doomed 에 들어오는데, 그것을 잡아 주는 것은 이 한 줄뿐이다.
        """
        self.put("assets/images/2026-03/img-1-01.jpg", b"PHOTO")
        self.ledger([{"local_path": "assets/images/2026-03/img-1-01.jpg"}])
        doomed, unique = pw.plan_unreferenced()
        self.assertEqual((doomed, unique), ([], []),
                         "원장이 가리키는 파일이 지울 것으로 잡혔다")

    def test_refuses_when_nothing_on_disk_matches_the_ledger(self):
        """맞는 것이 하나도 없으면 보관본이 빈 것이 아니라 견주기가 어긋난 것이다."""
        self.put("assets/images/2026-03/img-1-01.jpg", b"PHOTO")
        self.put("assets/images/2026-03/img-2-01.jpg", b"PHOTO2")
        # 원장이 엉뚱한 곳을 가리킨다 (경로 규칙이 바뀐 상황을 흉내 낸다)
        self.ledger([{"local_path": "assets/photos/2026-03/img-1-01.jpg"}])
        doomed, unique = pw.plan_unreferenced()
        self.assertEqual((doomed, unique), ([], []))

    def test_refuses_when_the_ledger_is_missing(self):
        """원장이 없으면 모든 파일이 '원장에 없음' 이 된다 — 최악의 경우다."""
        self.put("assets/images/2026-03/img-1-01.jpg", b"PHOTO")
        doomed, unique = pw.plan_unreferenced()
        self.assertEqual((doomed, unique), ([], []))

    def test_nested_asset_paths_count_as_referenced(self):
        """경로는 한 자리에 없다 — assets[].local_path·thumb_path 에 흩어져 있다.

        특정 키만 읽으면 한 메시지의 사진 일곱 장 중 여섯 장이 '원장에 없음' 이
        된다. 그 실수의 대가가 사진 원본 삭제다.
        """
        self.put("assets/images/2026-03/img-1-01.jpg", b"A")
        self.put("assets/images/2026-03/img-1-02.jpg", b"B")
        self.put("assets/thumbs/2026-03/img-1-02.webp", b"T")
        self.ledger([{
            "local_path": "assets/images/2026-03/img-1-01.jpg",
            "assets": [
                {"local_path": "assets/images/2026-03/img-1-01.jpg"},
                {"local_path": "assets/images/2026-03/img-1-02.jpg",
                 "thumb_path": "assets/thumbs/2026-03/img-1-02.webp"},
            ],
        }])
        doomed, unique = pw.plan_unreferenced()
        self.assertEqual((doomed, unique), ([], []))

    def test_a_thumb_is_deleted_without_asking_about_content(self):
        """축소판은 원본에서 다시 만든다 — 내용이 유일해도 지운다."""
        self.put("assets/images/2026-03/img-1-01.jpg", b"A")
        self.put("assets/thumbs/2026-03/img-9-01.webp", b"UNIQUE-THUMB")
        self.ledger([{"local_path": "assets/images/2026-03/img-1-01.jpg"}])
        doomed, unique = pw.plan_unreferenced()
        self.assertEqual([p.name for p, _ in doomed], ["img-9-01.webp"])
        self.assertEqual(unique, [])


class DefaultIsToKeepTest(unittest.TestCase):
    def test_remove_does_nothing_without_apply(self):
        """기본이 '지우지 않음' 이어야 한다.

        이 스크립트가 지우는 것은 대부분 다시 만들 수 없다(로그는 그날의 유일한
        기록이다). 실수로 도는 쪽이 실수로 안 도는 쪽보다 나쁘다.
        """
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "abort-20260101-000000.png"
            p.write_bytes(b"x" * 100)
            n = pw.remove([(p, "검사")], apply=False, label="검사")
            self.assertEqual(n, 100)
            self.assertTrue(p.exists(), "--apply 없이 지웠다")

    def test_remove_deletes_with_apply(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "abort-20260101-000000.png"
            p.write_bytes(b"x" * 100)
            pw.remove([(p, "검사")], apply=True, label="검사")
            self.assertFalse(p.exists())


class NightlyRunPrunesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ps1 = (Path(__file__).resolve().parent.parent
                   / "scripts" / "run_daily.ps1").read_text(encoding="utf-8-sig")

    def test_pipeline_calls_it(self):
        self.assertIn("scripts.prune_workspace", self.ps1)

    def test_it_runs_after_upload(self):
        """마름질이 잘못돼도 그날 발행은 이미 끝나 있어야 한다."""
        self.assertLess(self.ps1.index("upload_firestore.js"),
                        self.ps1.index("scripts.prune_workspace"))

    def test_dry_run_does_not_delete(self):
        block = self.ps1.split("scripts.prune_workspace", 1)[1].split("finally", 1)[0]
        self.assertIn("if (-not $DryRun) { $pruneArgs += '--apply' }", block)

    def test_assets_are_not_pruned_nightly(self):
        """해시 계산이 1분 가까이 걸리고, 사람이 보고 판단할 파일이 섞여 있다."""
        block = self.ps1.split("$pruneArgs = @(", 1)[1].split("finally", 1)[0]
        self.assertNotIn("--assets", block)

    def test_failure_does_not_stop_the_run(self):
        block = self.ps1.split("# 11) 작업 폴더 마름질", 1)[1].split("finally", 1)[0]
        self.assertIn("$ErrorActionPreference = 'Continue'", block)
        self.assertNotIn("Invoke-Step", block)


if __name__ == "__main__":
    unittest.main()
