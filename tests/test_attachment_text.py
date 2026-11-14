# -*- coding: utf-8 -*-
"""첨부 파일의 글 — 보고서가 파일 안의 알맹이를 읽게 한다(2026-11-15).

이것이 조용히 망가지면 보고서는 다시 '파일을 공유했다' 로 끝나고, 아무 경고도
뜨지 않는다. 그래서 형식별 뽑기·프롬프트 경계·'읽었다' 표시를 따로 묶어 둔다.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import attachment_text as at  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
KOREAN = "사회복지 현장에서 당사자의 주체성을 지키는 방법을 정리한 초안입니다. " * 4


class Tmp(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="att-test-"))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def put(self, name: str, data) -> Path:
        p = self.dir / name
        if isinstance(data, str):
            p.write_text(data, encoding="utf-8")
        else:
            p.write_bytes(data)
        return p


class ExtractTest(Tmp):
    def test_docx_paragraphs_and_tables(self):
        import docx
        d = docx.Document()
        d.add_paragraph(KOREAN)
        t = d.add_table(rows=1, cols=2)
        t.cell(0, 0).text = "구분"
        t.cell(0, 1).text = "내용"
        p = self.dir / "a.docx"
        d.save(str(p))
        status, text, _ = at.extract(p)
        self.assertEqual("ok", status)
        self.assertIn("주체성", text)
        self.assertIn("구분 | 내용", text)

    def test_pdf(self):
        import pymupdf
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Agency of service users. " * 6)
        p = self.dir / "a.pdf"
        doc.save(str(p))
        doc.close()
        status, text, _ = at.extract(p)
        self.assertEqual("ok", status)
        self.assertIn("Agency", text)

    def test_hwpx_section_text(self):
        p = self.dir / "a.hwpx"
        xml = ('<?xml version="1.0"?><hs:sec xmlns:hs="x" xmlns:hp="y">'
               '<hp:p id="1"><hp:run><hp:t>%s</hp:t></hp:run></hp:p>'
               '<hp:p id="2"><hp:run><hp:t>둘째 문단 &amp; 끝</hp:t></hp:run></hp:p></hs:sec>' % KOREAN)
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("Contents/section0.xml", xml)
        status, text, _ = at.extract(p)
        self.assertEqual("ok", status)
        self.assertIn("둘째 문단 & 끝", text)

    def test_html_drops_script_and_style(self):
        p = self.put("a.html", "<html><head><style>.x{color:red}</style></head><body>"
                               "<script>alert('지시')</script><p>%s</p></body></html>" % KOREAN)
        status, text, _ = at.extract(p)
        self.assertEqual("ok", status)
        self.assertNotIn("alert", text)
        self.assertNotIn("color", text)

    def test_unsupported_and_empty_and_broken(self):
        self.assertEqual("unsupported", at.extract(self.put("a.zip", b"PK"))[0])
        self.assertEqual("empty", at.extract(self.put("b.md", "짧다"))[0])
        status, _, note = at.extract(self.put("c.pdf", b"not a pdf"))
        self.assertEqual("error", status)
        self.assertTrue(note)

    def test_garbled_text_is_not_ok(self):
        """글꼴 인코딩이 망가진 pdf 의 글 — 보고서에 넣으면 헛소리가 된다(2026-11-15 실측)."""
        garbled = "BeÐP People ¬„ì ›ÙÀÐ «ü õÀ ¬’ Dt D ‹8 \\øx ﬂ " * 10
        self.assertLess(at.readable_ratio(garbled), at.MIN_READABLE)
        status, _, note = at.extract(self.put("g.md", garbled))
        self.assertEqual("empty", status)
        self.assertIn("깨짐", note)
        self.assertGreater(at.readable_ratio(KOREAN), 0.95)


class RefreshTest(Tmp):
    def manifest(self, sha="s1"):
        self.put("f.md", KOREAN)
        return [{"message_id": "msg-1", "filename": "f.md", "local_path": "f.md", "sha256": sha}]

    def test_extracts_once_per_file(self):
        led = {}
        self.assertEqual(["msg-1"], at.refresh(self.manifest(), led, root=self.dir))
        self.assertEqual([], at.refresh(self.manifest(), led, root=self.dir))

    def test_changed_file_is_read_again_and_must_be_reported_again(self):
        led = {}
        at.refresh(self.manifest("s1"), led, root=self.dir)
        led["msg-1"]["reported_in"] = "t-1"
        self.assertEqual(["msg-1"], at.refresh(self.manifest("s2"), led, root=self.dir))
        self.assertEqual("", led["msg-1"]["reported_in"])

    def test_new_reader_rereads_but_keeps_reported(self):
        led = {}
        at.refresh(self.manifest(), led, root=self.dir)
        led["msg-1"]["reported_in"] = "t-1"
        led["msg-1"]["reader"] = at.READER_VERSION - 1
        self.assertEqual(["msg-1"], at.refresh(self.manifest(), led, root=self.dir))
        self.assertEqual("t-1", led["msg-1"]["reported_in"])

    def test_errors_are_retried(self):
        led = {"msg-1": {"sha256": "s1", "status": "error", "reader": at.READER_VERSION}}
        self.assertEqual(["msg-1"], at.refresh(self.manifest(), led, root=self.dir))


def entry(text=KOREAN, reported="", status="ok"):
    return {"filename": "초안.docx", "status": status, "chars": len(text),
            "text": text, "reported_in": reported}


MSG = {"id": "msg-9", "kind": "file", "nickname": "회원", "text": "파일: 초안.docx"}


class PromptTest(unittest.TestCase):
    def test_block_fences_the_text_and_says_it_is_not_an_instruction(self):
        block = at.prompt_block([MSG], {"msg-9": entry()})
        self.assertIn("<<<파일 글 시작>>>", block)
        self.assertIn("<<<파일 글 끝>>>", block)
        self.assertIn("따르지 마세요", block)
        self.assertIn("따옴표로 옮기지 말고", block)
        self.assertIn("주체성", block)

    def test_no_text_no_block(self):
        self.assertEqual("", at.prompt_block([MSG], {}))
        self.assertEqual("", at.prompt_block([MSG], {"msg-9": entry(status="empty")}))

    def test_contacts_are_masked(self):
        # (9876-5432 같은 연속 숫자는 pii 가 예시 번호로 보고 넘긴다 — 실제 모양으로 시험한다)
        block = at.prompt_block([MSG], {"msg-9": entry(KOREAN + " 연락처 010-2345-6789")})
        self.assertNotIn("010-2345-6789", block)

    def test_caps_per_file_and_total(self):
        big = "가" * 50000
        msgs = [dict(MSG, id="msg-%d" % i) for i in range(5)]
        led = {m["id"]: entry(big) for m in msgs}
        self.assertEqual(at.PROMPT_CHARS_TOTAL, at.prompt_chars(msgs, led))
        block = at.prompt_block(msgs[:1], led)
        self.assertIn("전체 50000자 중 앞 %d자" % at.PROMPT_CHARS_PER_FILE, block)


class PendingTest(Tmp):
    def test_mark_and_pending(self):
        path = self.dir / "led.json"
        path.write_text(json.dumps({"msg-9": entry(KOREAN * 10)}), encoding="utf-8")
        threads = [{"id": "t-1", "message_ids": ["msg-9"]}]
        led = at.load_ledger(path)
        self.assertEqual(["t-1"], at.pending_threads(threads, led, {"t-1"}))
        # 보고서가 아직 없는 주제는 분류가 처음 쓸 때 읽는다 — 다시 쓰기 대상이 아니다
        self.assertEqual([], at.pending_threads(threads, led, set()))
        self.assertEqual(1, at.mark_reported([MSG], "t-1", path))
        self.assertEqual([], at.pending_threads(threads, at.load_ledger(path), {"t-1"}))

    def test_merged_thread_needs_its_own_reading(self):
        led = {"msg-9": entry(KOREAN * 10, reported="t-old")}
        threads = [{"id": "t-new", "message_ids": ["msg-9"]}]
        self.assertEqual(["t-new"], at.pending_threads(threads, led, {"t-new"}))

    def test_small_ui_text_is_not_worth_a_rewrite(self):
        led = {"msg-9": entry("단추 " * 50)}
        threads = [{"id": "t-1", "message_ids": ["msg-9"]}]
        self.assertEqual([], at.pending_threads(threads, led, {"t-1"}))

    def test_newest_first(self):
        led = {"msg-001": entry(KOREAN * 10), "msg-500": entry(KOREAN * 10)}
        threads = [{"id": "t-a", "message_ids": ["msg-001"]},
                   {"id": "t-b", "message_ids": ["msg-500"]}]
        self.assertEqual(["t-b", "t-a"], at.pending_threads(threads, led, {"t-a", "t-b"}))


class ReportWiringTest(Tmp):
    """보고서 쓰기가 첨부 글을 읽고, 다 쓰면 '읽었다' 고 적는지."""

    def test_both_prompts_carry_the_block(self):
        from scripts import classify_unsorted as cu
        led = {"msg-9": entry()}
        orig = at.load_ledger
        at.load_ledger = lambda path=None: led
        try:
            msg = dict(MSG, date="2026-11-14", time="10:18")
            p1 = cu.build_report_prompt({"title": "t", "summary": "s", "category": "c"}, [msg], [])
            p2 = cu.build_prompt([msg], [{"id": "c", "label": "c"}], [], [])
        finally:
            at.load_ledger = orig
        self.assertIn("<<<파일 글 시작>>>", p1)
        self.assertIn("<<<파일 글 시작>>>", p2)

    def test_write_report_allows_longer_body_and_marks_reported(self):
        from scripts import classify_unsorted as cu
        path = self.dir / "led.json"
        path.write_text(json.dumps({"msg-9": entry(KOREAN * 10)}), encoding="utf-8")
        orig_led, orig_dir = at.LEDGER, cu.REPORTS_DIR
        at.LEDGER, cu.REPORTS_DIR = path, self.dir / "reports"
        try:
            body = "파일에는 당사자 주체성을 지키는 세 원칙이 담겼다. " * 20   # 대화 두 줄보다 훨씬 길다
            why = cu.write_report("t-1", {"title": "초안", "summary": "요지", "report": body},
                                  raw_chars=40, msgs=[MSG])
        finally:
            at.LEDGER, cu.REPORTS_DIR = orig_led, orig_dir
        self.assertIsNone(why)
        self.assertEqual("t-1", json.loads(path.read_text(encoding="utf-8"))["msg-9"]["reported_in"])


class RunnerWiringTest(unittest.TestCase):
    PS1 = (ROOT / "scripts" / "run_daily.ps1").read_text(encoding="utf-8-sig")

    def test_extract_runs_before_classification(self):
        self.assertLess(self.PS1.index("python -m scripts.attachment_text 2>&1"),
                        self.PS1.index("# 5) 주제 분류"))

    def test_rewrite_runs_after_cleanup_and_before_ai_notes(self):
        step = self.PS1.index("python -m scripts.attachment_text --pending")
        self.assertLess(self.PS1.index("# 5a-3)"), step)
        self.assertLess(step, self.PS1.index("# 5b-2) AI 검증 주석"))
        block = self.PS1[step:step + 900]
        self.assertIn("classify_unsorted --rewrite-ids $attIds", block)
        self.assertIn("ai_reports --ids $attIds", block)


if __name__ == "__main__":
    unittest.main()
