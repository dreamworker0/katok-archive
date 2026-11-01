# -*- coding: utf-8 -*-
"""원본 데이터 백업 — backup_data.py.

백업은 필요한 날에야 처음으로 제대로 읽힌다. 그날 '사실은 반쪽이었다' 를 알면
늦는다. 그래서 담는 범위, 지우지 않는 사본, 반쯤 쓴 묶음, 묶음 주기를 지킨다.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import backup_data as bd  # noqa: E402


def make_tree(root: Path) -> None:
    files = {
        "output/messages.jsonl": "{}\n",
        "output/backup-x/old.json": "{}",
        "assets/images/2026-10/a.png": "png",
        "assets/files/b.pdf": "pdf",
        "inbox/processed/KakaoTalk_1.txt": "txt",
        "inbox/drawer/2026-10-31/b.pdf": "dup",
        "config/notify.json": '{"discord_webhook": "secret"}',
        "config/members.json": "{}",
        "scripts/x.py": "code",
        "KakaoTalk_20260723_group.txt": "txt",
        "output/__pycache__/x.pyc": "x",
    }
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


class CollectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        make_tree(self.tmp)
        self.rels = {rel for _, rel in bd.collect(self.tmp)}

    def test_keeps_what_cannot_be_rebuilt(self):
        for rel in ["output/messages.jsonl", "assets/images/2026-10/a.png", "assets/files/b.pdf",
                    "inbox/processed/KakaoTalk_1.txt", "config/members.json",
                    "KakaoTalk_20260723_group.txt"]:
            self.assertIn(rel, self.rels)

    def test_skips_drawer_stash_code_and_caches(self):
        """inbox/drawer 는 날마다 같은 파일이 쌓인 임시 보관함이고 알맹이는 assets 에 있다."""
        self.assertFalse(any(r.startswith("inbox/drawer/") for r in self.rels))
        self.assertNotIn("scripts/x.py", self.rels)
        self.assertFalse(any("__pycache__" in r for r in self.rels))

    def test_webhook_never_goes_to_the_cloud(self):
        self.assertIn("config/notify.json", bd.CLOUD_SKIP)


class MirrorTest(unittest.TestCase):
    def setUp(self):
        self.src = Path(tempfile.mkdtemp())
        self.dst = Path(tempfile.mkdtemp())
        make_tree(self.src)
        self.items = bd.collect(self.src)

    def test_second_run_copies_nothing(self):
        first = bd.mirror(self.items, self.dst)
        self.assertEqual(len(self.items), first["copied"])
        second = bd.mirror(self.items, self.dst)
        self.assertEqual(0, second["copied"])

    def test_changed_file_is_copied_again(self):
        bd.mirror(self.items, self.dst)
        p = self.src / "output" / "messages.jsonl"
        p.write_text("{}\n{}\n", encoding="utf-8")
        os.utime(p, (p.stat().st_atime, p.stat().st_mtime + 5))
        r = bd.mirror(bd.collect(self.src), self.dst)
        self.assertEqual(1, r["copied"])
        self.assertEqual("{}\n{}\n", (self.dst / "output" / "messages.jsonl").read_text(encoding="utf-8"))

    def test_deleting_the_original_does_not_delete_the_copy(self):
        """지움까지 따라가면 실수로 지운 것이 그날 밤 사본에서도 사라진다."""
        bd.mirror(self.items, self.dst)
        (self.src / "assets" / "files" / "b.pdf").unlink()
        bd.mirror(bd.collect(self.src), self.dst)
        self.assertTrue((self.dst / "assets" / "files" / "b.pdf").exists())

    def test_dry_run_writes_nothing(self):
        bd.mirror(self.items, self.dst, dry_run=True)
        self.assertEqual([], list(self.dst.iterdir()))


class ZipTest(unittest.TestCase):
    def setUp(self):
        self.src = Path(tempfile.mkdtemp())
        self.cloud = Path(tempfile.mkdtemp()) / "백업"
        make_tree(self.src)
        self.items = bd.collect(self.src)

    def test_zip_holds_every_item_and_leaves_no_partial(self):
        z = bd.write_zip(self.items, self.cloud, date(2026, 11, 1))
        self.assertEqual("katok-archive-20261101.zip", z.name)
        with zipfile.ZipFile(z) as zf:
            self.assertEqual(len(self.items), len(zf.namelist()))
        self.assertEqual([], list(self.cloud.glob("*.partial")))

    def test_due_every_seven_days_not_by_weekday(self):
        self.assertTrue(bd.zip_due(self.cloud, date(2026, 11, 1)))
        bd.write_zip(self.items, self.cloud, date(2026, 11, 1))
        self.assertFalse(bd.zip_due(self.cloud, date(2026, 11, 7)))
        self.assertTrue(bd.zip_due(self.cloud, date(2026, 11, 8)))
        self.assertTrue(bd.zip_due(self.cloud, date(2026, 11, 20)))

    def test_keeps_only_the_latest_few(self):
        for d in [date(2026, 10, 4), date(2026, 10, 11), date(2026, 10, 18),
                  date(2026, 10, 25), date(2026, 11, 1)]:
            bd.write_zip(self.items, self.cloud, d)
        gone = bd.prune_zips(self.cloud, keep=4)
        self.assertEqual(["katok-archive-20261004.zip"], [p.name for p in gone])
        self.assertEqual(4, len(bd.zips_in(self.cloud)))


class RunnerWiringTest(unittest.TestCase):
    PS1 = (Path(__file__).resolve().parent.parent / "scripts" / "run_daily.ps1").read_text(encoding="utf-8-sig")

    def test_backup_runs_on_quiet_days_and_publishing_days(self):
        skip = self.PS1.index("Report-Run -status 'skipped'")
        ok = self.PS1.index("Report-Run -status 'ok'")
        self.assertIn("Invoke-Backup", self.PS1[skip - 400:skip])
        self.assertIn("Invoke-Backup", self.PS1[self.PS1.index("Firestore 적재"):ok])

    def test_failure_reaches_admin_tab_and_discord(self):
        fn = self.PS1[self.PS1.index("function Invoke-Backup"):]
        fn = fn[:fn.index("\n}\n")]
        self.assertIn("$script:backupWarn", fn)
        self.assertIn("scripts\\notify.js", fn)
        self.assertGreaterEqual(self.PS1.count("$script:backupWarn) {"), 2)


if __name__ == "__main__":
    unittest.main()
