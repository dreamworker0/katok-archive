# -*- coding: utf-8 -*-
"""경고는 달라진 것을 말해야 신호다 — warnlog 의 계약."""
import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts import warnlog

ROOT = Path(__file__).resolve().parent.parent


class WarnlogTest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.state = Path(self._tmp.name) / "warnings-seen.json"
        self._p = patch.object(warnlog, "STATE", self.state)
        self._p.start()
        warnlog.reset()

    def tearDown(self):
        self._p.stop()
        warnlog.reset()
        self._tmp.cleanup()

    def say(self, *a, **kw):
        buf = io.StringIO()
        with redirect_stdout(buf):
            line = warnlog.note(*a, **kw)
        return line, buf.getvalue()

    def test_first_time_says_everything(self):
        line, out = self.say("k", ["a", "b", "c"], "[관계망] 고립 노드", advice="표에 넣으세요")
        self.assertIn("3개", line)
        self.assertIn("표에 넣으세요", line)
        self.assertIn("a, b, c", line)
        self.assertEqual(out.strip(), line)

    def test_unchanged_is_one_short_line(self):
        self.state.write_text(json.dumps({"k": ["a", "b"]}), encoding="utf-8")
        line, _ = self.say("k", ["b", "a"], "[관계망] 고립 노드", advice="표에 넣으세요")
        self.assertEqual(line, "[관계망] 고립 노드 2개 — 지난번과 같음")

    def test_change_names_only_the_delta(self):
        self.state.write_text(json.dumps({"k": ["a", "b"]}), encoding="utf-8")
        line, _ = self.say("k", ["b", "c", "d"], "[관계망] 고립 노드", advice="표에")
        self.assertIn("3개 (새로 2 · 사라짐 1)", line)
        self.assertIn("새로: c, d", line)
        self.assertIn("사라짐: a", line)
        self.assertNotIn("새로: b", line)

    def test_gone_entirely_is_still_said_once(self):
        self.state.write_text(json.dumps({"k": ["a"]}), encoding="utf-8")
        line, _ = self.say("k", [], "[관계망] 고립 노드")
        self.assertIn("0개", line)
        self.assertIn("지난번 1개", line)

    def test_nothing_before_nothing_now_is_silent(self):
        line, out = self.say("k", [], "[관계망] 고립 노드")
        self.assertIsNone(line)
        self.assertEqual(out, "")

    def test_note_alone_does_not_touch_the_state(self):
        """검사가 build_data 를 불러도 그날 밤 발행이 '같음' 만 보게 되면 안 된다."""
        self.say("k", ["a"], "[x]")
        self.assertFalse(self.state.exists())

    def test_save_merges_and_keeps_keys_not_seen_this_run(self):
        self.state.write_text(json.dumps({"old": ["z"], "k": ["a"]}), encoding="utf-8")
        self.say("k", ["a", "b"], "[x]")
        warnlog.save()
        self.assertEqual(json.loads(self.state.read_text(encoding="utf-8")),
                         {"old": ["z"], "k": ["a", "b"]})

    def test_broken_state_file_is_treated_as_first_run(self):
        self.state.write_text("{not json", encoding="utf-8")
        line, _ = self.say("k", ["a"], "[x]")
        self.assertIn("앞 1개: a", line)


class PipelineWiringTest(unittest.TestCase):
    def test_only_the_entry_points_save(self):
        """build_data 안에서 save 하면 검사가 상태를 갱신한다."""
        site = (ROOT / "scripts" / "build_site.py").read_text(encoding="utf-8")
        bfp = (ROOT / "scripts" / "build_firestore_payload.py").read_text(encoding="utf-8")
        body = site[site.index("def build_data("):site.index("def write_site")]
        self.assertNotIn("warnlog.save", body)
        self.assertIn("warnlog.save()", site[site.index("def main()"):])
        self.assertIn("warnlog.save()", bfp[bfp.index("def main()"):])

    def test_recurring_warnings_go_through_warnlog(self):
        site = (ROOT / "scripts" / "build_site.py").read_text(encoding="utf-8")
        for key in ("orphan_tags", "stale_nodes", "unlinked_nodes", "thin_reports",
                    "structure_gaps", "place_candidates"):
            self.assertIn('warnlog.note("%s"' % key, site)

    def test_daily_run_keeps_only_the_tail_of_a_passing_test_run(self):
        ps1 = (ROOT / "scripts" / "run_daily.ps1").read_text(encoding="utf-8")
        self.assertIn("Invoke-Step '테스트' { python -m unittest discover -s tests } -TailOnSuccess", ps1)
        body = ps1[ps1.index("function Invoke-Step {"):ps1.index("Say \"===== 일일 갱신 시작")]
        # 실패하면 전부 남긴다 — 꼬리만 남기는 가지는 성공($ok)에만 걸린다
        self.assertIn("if ($ok -and $TailOnSuccess -gt 0", body)
