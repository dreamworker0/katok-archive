# -*- coding: utf-8 -*-
"""태그 수술의 공통 골격 — 원본 md 를 덮어쓰는 자리라서 검사가 필요하다.

네 스크립트(retag_reports·split_tag·retire_tag·adopt_orphans)가 `apply_proposal`
26줄을 거의 그대로 되풀이했고, `split_tag` 와 `retire_tag` 것은 diff 하면 코드
한 줄만 달랐다(백업 폴더 이름). 그런데 **그 함수에는 검사가 하나도 없었다** —
`replace_keywords_line` 은 7건이 지켰지만, 백업을 먼저 만드는지·한 편이 깨졌을 때
나머지를 계속 고치는지는 아무도 안 봤다.

되풀이된 코드가 위험한 이유가 그것이다. 검사를 붙이려면 네 벌에 네 번 붙여야 하니
아무도 안 붙인다. 한 곳으로 모은 지금 붙인다.
"""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts import tag_surgery as ts

CRLF = ("---\r\n"
        "title: 제미나이 3 프로 첫인상\r\n"
        "keywords: 제미나이, 모델 비교\r\n"
        "---\r\n"
        "\r\n"
        "본문 첫 줄.\r\n"
        "본문 둘째 줄.\r\n")


class ApplyKeywordChangesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        root = Path(self._tmp.name)
        self.reports = root / "reports"
        self.reports.mkdir()
        self.backup = root / "backup-테스트-20260822"
        self.backup.mkdir()
        self._p = patch.object(ts, "REPORTS_DIR", self.reports)
        self._p.start()

    def tearDown(self):
        self._p.stop()
        self._tmp.cleanup()

    def write(self, tid: str, text: str = CRLF) -> Path:
        p = self.reports / ("%s.md" % tid)
        p.write_text(text, encoding="utf-8", newline="")
        return p

    @staticmethod
    def change(before, after):
        return {"before": before, "after": after}

    def test_rewrites_only_the_keywords_line(self):
        p = self.write("t-001")
        done, failed = ts.apply_keyword_changes(
            {"t-001": self.change(["제미나이", "모델 비교"], ["제미나이 3 프로"])},
            self.backup)
        self.assertEqual((done, failed), (1, []))
        out = p.read_text(encoding="utf-8", newline="")
        self.assertIn("keywords: 제미나이 3 프로\r\n", out)
        self.assertIn("본문 첫 줄.\r\n본문 둘째 줄.\r\n", out)
        self.assertIn("title: 제미나이 3 프로 첫인상\r\n", out)

    def test_crlf_survives(self):
        """이 폴더는 CRLF 다. 줄바꿈이 바뀌면 371편의 diff 가 쓸모없어진다."""
        p = self.write("t-001")
        ts.apply_keyword_changes(
            {"t-001": self.change(["가"], ["나"])}, self.backup)
        raw = p.read_bytes()
        self.assertNotIn(b"\n\n", raw.replace(b"\r\n", b"\r"))
        self.assertEqual(raw.count(b"\r\n"), CRLF.count("\r\n"))

    def test_backup_holds_the_version_from_before(self):
        """순서가 뒤바뀌면(쓰고 나서 복사하면) 백업이 '바꾼 뒤' 가 되어 되돌릴 수 없다."""
        self.write("t-001")
        ts.apply_keyword_changes(
            {"t-001": self.change(["제미나이", "모델 비교"], ["딴것"])}, self.backup)
        saved = (self.backup / "t-001.md").read_text(encoding="utf-8", newline="")
        self.assertEqual(saved, CRLF)
        self.assertIn("keywords: 제미나이, 모델 비교", saved)

    def test_before_tags_are_saved_as_json(self):
        self.write("t-001")
        self.write("t-002")
        ts.apply_keyword_changes({
            "t-001": self.change(["가", "나"], ["다"]),
            "t-002": self.change(["라"], ["마"]),
        }, self.backup)
        data = json.loads((self.backup / "keywords-before.json").read_text(encoding="utf-8"))
        self.assertEqual(data, {"t-001": ["가", "나"], "t-002": ["라"]})

    def test_a_missing_file_does_not_stop_the_rest(self):
        """한 편이 없다고 나머지 예순 편을 못 고치면 수술 전체가 멈춘다."""
        self.write("t-001")
        self.write("t-003")
        done, failed = ts.apply_keyword_changes({
            "t-001": self.change(["가"], ["나"]),
            "t-002": self.change(["가"], ["나"]),   # 파일 없음
            "t-003": self.change(["가"], ["다"]),
        }, self.backup)
        self.assertEqual(done, 2)
        self.assertEqual(len(failed), 1)
        self.assertIn("t-002", failed[0])
        self.assertIn("파일이 없습니다", failed[0])
        self.assertIn("keywords: 나", (self.reports / "t-001.md").read_text(encoding="utf-8"))
        self.assertIn("keywords: 다", (self.reports / "t-003.md").read_text(encoding="utf-8"))

    def test_broken_front_matter_is_reported_not_raised(self):
        self.write("t-001")
        self.write("t-002", "프론트매터가 없는 본문\r\n")
        done, failed = ts.apply_keyword_changes({
            "t-001": self.change(["가"], ["나"]),
            "t-002": self.change(["가"], ["나"]),
        }, self.backup)
        self.assertEqual(done, 1)
        self.assertEqual(len(failed), 1)
        self.assertIn("프론트매터", failed[0])
        # 못 고친 편은 손대지 않는다 — 백업도 남기지 않는다.
        self.assertEqual(
            (self.reports / "t-002.md").read_text(encoding="utf-8", newline=""),
            "프론트매터가 없는 본문\r\n")
        self.assertFalse((self.backup / "t-002.md").exists())

    def test_no_change_means_no_write_and_no_backup(self):
        """같은 태그를 다시 쓰는 것은 바꾼 것이 아니다.

        세지 않는 이유: 로그의 '몇 편 고쳤다'가 실제와 달라지면, 수술이 먹혔는지
        아닌지를 그 숫자로 판단할 수 없다. 백업을 안 남기는 이유: 바뀐 것이 없는데
        사본을 만들면 백업 폴더가 무엇이 바뀌었는지 알려주기를 그만둔다.
        """
        self.write("t-001")
        done, failed = ts.apply_keyword_changes(
            {"t-001": self.change(["제미나이", "모델 비교"],
                                  ["제미나이", "모델 비교"])}, self.backup)
        self.assertEqual((done, failed), (0, []))
        self.assertFalse((self.backup / "t-001.md").exists())

    def test_empty_changes_still_leaves_a_record(self):
        """아무것도 안 바꿔도 keywords-before.json 은 남는다 — '돌았다'는 기록이다."""
        done, failed = ts.apply_keyword_changes({}, self.backup)
        self.assertEqual((done, failed), (0, []))
        self.assertTrue((self.backup / "keywords-before.json").exists())


class BackupDirTest(unittest.TestCase):
    def test_named_by_kind_and_day(self):
        with TemporaryDirectory() as tmp:
            with patch.object(ts, "OUT", Path(tmp)):
                d = ts.backup_dir("split", "20260822")
                self.assertTrue(d.is_dir())
                self.assertEqual(d.name, "backup-split-20260822")

    def test_same_day_twice_is_not_an_error(self):
        """한 번의 수술을 되돌리는 데 필요한 것은 '그 수술 직전' 상태 하나뿐이다."""
        with TemporaryDirectory() as tmp:
            with patch.object(ts, "OUT", Path(tmp)):
                a = ts.backup_dir("retire", "20260822")
                b = ts.backup_dir("retire", "20260822")
                self.assertEqual(a, b)


class EveryScriptUsesTheSharedSkeletonTest(unittest.TestCase):
    """네 스크립트가 골격을 쓰는지 — 하나가 자기 사본으로 되돌아가지 않게.

    되돌아가도 검사는 통과한다(그 사본이 같은 일을 하니까). 그래서 골격을 쓰는지를
    따로 본다. 여기서 갈라지면 검사가 지키는 것은 골격 하나뿐이고, 실제로 원본
    md 를 덮어쓰는 코드는 검사 밖에 있게 된다.
    """
    SCRIPTS = {"retag_reports": "retag", "split_tag": "split", "retire_tag": "retire"}

    def test_apply_proposal_delegates(self):
        for name, kind in self.SCRIPTS.items():
            with self.subTest(script=name):
                src = (Path(__file__).resolve().parent.parent
                       / "scripts" / (name + ".py")).read_text(encoding="utf-8")
                body = src.split("def apply_proposal(", 1)[1].split("\ndef ", 1)[0]
                self.assertIn("apply_keyword_changes(", body)
                self.assertIn('backup_dir("%s"' % kind, body)
                # 자기 사본으로 되돌아간 표시들
                self.assertNotIn("shutil.copy2", body)
                self.assertNotIn("REPORTS_DIR /", body)

    def test_backup_kinds_are_distinct(self):
        """폴더 이름이 겹치면 다른 수술이 서로의 되돌릴 지점을 덮는다."""
        kinds = list(self.SCRIPTS.values())
        self.assertEqual(len(kinds), len(set(kinds)))


if __name__ == "__main__":
    unittest.main()
