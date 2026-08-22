# -*- coding: utf-8 -*-
"""개인정보 탐지·마스킹 검증.

두 층으로 본다.
  1. 탐지기 단위 — 진짜를 잡는지, 그리고 **오탐을 안 내는지**. 실측에서 오탐이
     진짜의 5배였으므로(2026-07-30, 25건 중 21건) 오탐 쪽 사례를 더 촘촘히 둔다.
  2. 발행 계약 — 실제 발행본에 가릴 것이 남아 있으면 실패한다. run_daily 가
     '발행본 → 테스트 → 적재' 순서이므로 이 검사가 적재를 막는 마지막 문이다.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts import pii  # noqa: E402
from tests.realdata import needs_real_data  # noqa: E402

EMPTY = {"phones": set(), "emails": set()}


class DetectTest(unittest.TestCase):
    def kinds(self, text, allow=EMPTY):
        return [(h.kind, h.grade) for h in pii.find(text, allow)]

    # ── 잡아야 하는 것 ──

    def test_email_is_masked_keeping_domain(self):
        out, hits = pii.mask("제 계정은 nobody9f3a@hanmail.net 입니다", EMPTY)
        self.assertEqual(out, "제 계정은 n****@hanmail.net 입니다")
        self.assertEqual(hits[0].grade, "certain")

    def test_hyphenated_mobile_is_certain_without_any_keyword(self):
        out, _ = pii.mask("010-0000-4321", EMPTY)
        self.assertEqual(out, "010-****-4321")

    def test_bare_mobile_needs_a_nearby_contact_word(self):
        """맨 숫자열은 근처에 '연락처' 같은 말이 있을 때만 가린다.

        지역번호·휴대전화 모양의 숫자열은 주문번호·기사 ID 로 흔하다. 키워드를
        요구하지 않으면 오탐이 진짜를 압도한다.
        """
        self.assertEqual(self.kinds("/t 01000004321"), [("mobile", "likely")])
        self.assertEqual(self.kinds("연락처 01000004321"), [("mobile", "certain")])

    def test_local_number_with_keyword(self):
        out, _ = pii.mask("문의 전화 02-3149-5000", EMPTY)
        self.assertEqual(out, "문의 전화 02-****-5000")

    def test_rrn_and_card(self):
        out, hits = pii.mask("주민번호 900101-1234567 / 카드 5432-1098-7654-3210", EMPTY)
        self.assertIn("900101-*******", out)
        self.assertIn("5432-****-****-3210", out)
        self.assertEqual([h.kind for h in hits], ["rrn", "card"])

    def test_email_inside_inline_code_is_still_found(self):
        """회귀: 인라인 코드를 검사에서 빼면 실제로 새던 것을 놓친다.

        보고서 t-346 이 "`nobody9f3a@hanmail.net` 을 들었다" 로 적어 두어, 인라인
        코드를 제외하던 초판이 이 한 건을 통째로 못 봤다. 보고서 규칙이 인용값을
        백틱으로 감싸게 하므로 인라인 코드는 개인정보가 가장 잘 숨는 자리다.
        """
        self.assertEqual(
            self.kinds("한도윤이 `nobody9f3a@hanmail.net` 을 들었다"),
            [("email", "certain")],
        )

    # ── 잡으면 안 되는 것 (전부 실제 대화에서 가져온 오탐) ──

    def test_numbers_inside_urls_are_ignored(self):
        for url in (
            "https://v.daum.net/v/20260203000002",
            "https://zdnet.co.kr/view/?no=20260114161950",
            "https://product.kyobobook.co.kr/detail/S000219133433",
            "https://www.facebook.com/groups/npo.smartwork/posts/2888936891441276/",
            "https://www.yna.co.kr/view/AKR20260724032900017?input=1195m",
            "https://it.chosun.com/news/articleView.html?idxno=2023092161316",
        ):
            self.assertEqual(self.kinds("공유합니다 " + url), [], url)

    def test_example_numbers_are_ignored(self):
        """슬랙이 전화번호를 링크로 안 만든다는 그 테스트 대화의 예시들."""
        for text in ("홍길동 010-1234-5678 이렇게 보내면",
                     "02-1234-5678 이건 또 복붙해도",
                     "/t 024998721 위 2개는 안됩니다",
                     "전화번호 010-0000-0000 으로 시험"):
            self.assertEqual(self.kinds(text), [], text)

    def test_a_column_of_numbers_is_not_a_card_number(self):
        """표를 OCR 하면 세로로 늘어선 값이 줄바꿈으로 이어진다.

        실측 img-002213-03: 식권 가격 '5000' 이 네 줄 늘어서 카드번호
        5000-0000-0000-5000 으로 읽혔고 사진 한 장이 통째로 감춰졌다.
        구분자에서 줄바꿈을 뺀 이유다.
        """
        self.assertEqual(self.kinds("5000\n5000\n5000\n5000"), [])
        self.assertEqual(self.kinds("연락처\n010\n0000\n4321"), [])

    def test_ocr_garbage_that_looks_like_an_email_is_ignored(self):
        """마지막 마디가 숫자면 이메일이 아니다 (OCR 로 읽은 터미널 화면)."""
        self.assertEqual(self.kinds("UbUntU@.24.@4.10]"), [])

    def test_placeholder_addresses_in_forms_are_ignored(self):
        """서식의 예시 주소를 가리면 그 사진만 이유 없이 사라진다."""
        for text in ("사용할 구글 계정 이메일  name@example.com",
                     "예: someone@test.com"):
            self.assertEqual(self.kinds(text), [], text)

    def test_dates_times_amounts_are_not_pii(self):
        for text in ("2026-07-30 10:30 에 만나요", "총 1,234,000원 입니다",
                     "버전 v1.2.3 으로 올렸습니다", "2026년 2분기 점검표.hwpx"):
            self.assertEqual(self.kinds(text), [], text)

    def test_code_fence_is_skipped(self):
        text = "설정은 이렇습니다\n```\nsecret = 900101-1234567\n```\n끝"
        self.assertEqual(self.kinds(text), [])

    def test_markdown_link_target_is_skipped_but_label_is_not(self):
        text = "[문의 010-0000-4321](https://x.test/v/20260203000002)"
        self.assertEqual(self.kinds(text), [("mobile", "certain")])

    # ── 허용 목록 ──

    def test_allow_list_spares_public_contacts(self):
        allow = {"phones": {"0231495000"}, "emails": {"help@sasw.or.kr"}}
        text = "대표전화 02-3149-5000 / help@sasw.or.kr"
        self.assertEqual(pii.find(text, allow), [])

    def test_allow_list_matches_regardless_of_separators(self):
        allow = {"phones": {"01000004321"}, "emails": set()}
        self.assertEqual(pii.find("연락처 010.0000.4321", allow), [])


class MaskTreeTest(unittest.TestCase):
    def test_nested_structures_are_walked(self):
        obj = {"report": "메일 a@b.co.kr 로", "links": [{"t": "010-0000-4321"}], "n": 3}
        out, hits = pii.mask_tree(obj, EMPTY)
        self.assertEqual(out["report"], "메일 a****@b.co.kr 로")
        self.assertEqual(out["links"][0]["t"], "010-****-4321")
        self.assertEqual(out["n"], 3)
        self.assertEqual(len(hits), 2)

    def test_likely_grade_is_reported_but_not_masked(self):
        out, hits = pii.mask_tree({"t": "/t 01000004321"}, EMPTY)
        self.assertEqual(out["t"], "/t 01000004321")
        self.assertEqual([h.grade for h in hits], ["likely"])


class ImageJudgeTest(unittest.TestCase):
    """OCR 로 읽은 글자로 사진을 판정하는 층."""

    def setUp(self):
        from scripts import scan_image_pii
        self.mod = scan_image_pii

    def test_verdicts(self):
        ocr = {
            "assets/images/a.png": ["연락처 010-0000-4321", "명함입니다"],
            "assets/images/b.png": ["대시보드 화면", "총 3,240건"],
            "assets/images/c.png": None,
            "assets/images/d.png": ["/t 01000004321"],
        }
        got = self.mod.judge(ocr, allow_paths=set())["images"]
        self.assertEqual(got["assets/images/a.png"]["verdict"], "hide")
        self.assertEqual(got["assets/images/b.png"]["verdict"], "ok")
        self.assertEqual(got["assets/images/c.png"]["verdict"], "unread")
        self.assertEqual(got["assets/images/d.png"]["verdict"], "review")

    def test_admin_allow_list_publishes_anyway(self):
        ocr = {"assets/images/a.png": ["문의 010-0000-4321"]}
        got = self.mod.judge(ocr, allow_paths={"assets/images/a.png"})["images"]
        self.assertEqual(got["assets/images/a.png"]["verdict"], "allowed")
        self.assertEqual(self.mod.hidden_paths({"images": got}), set())

    def test_the_allow_list_settles_a_review_too(self):
        """'한 번 볼 것'(review)도 표에 적으면 다시 묻지 않는다.

        예전에는 허용 목록이 `certain` 에만 적용돼서, likely 로 걸린 사진을 표에
        적어 두어도 판정이 계속 review 로 남아 매일 '확인필요 1' 이 찍혔다
        (실측 2026-08-14: 협회 대표번호가 적힌 모집 포스터). '사람이 발행하기로
        했다' 는 판단은 등급과 무관하다.
        """
        ocr = {"assets/images/d.png": ["/t 01000004321"]}
        plain = self.mod.judge(ocr, allow_paths=set())["images"]
        self.assertEqual(plain["assets/images/d.png"]["verdict"], "review")
        got = self.mod.judge(ocr, allow_paths={"assets/images/d.png"})["images"]
        self.assertEqual(got["assets/images/d.png"]["verdict"], "allowed")

    def test_a_clean_photo_in_the_allow_list_stays_ok(self):
        # 걸린 것이 없으면 표에 적혀 있어도 'allowed' 로 바꾸지 않는다 —
        # 'allowed' 는 '개인정보가 있는데 발행한다' 는 뜻이라 셈이 어긋난다.
        ocr = {"assets/images/b.png": ["대시보드 화면", "총 3,240건"]}
        got = self.mod.judge(ocr, allow_paths={"assets/images/b.png"})["images"]
        self.assertEqual(got["assets/images/b.png"]["verdict"], "ok")

    def test_verdict_file_never_stores_the_original_value(self):
        """판정 파일이 곧 개인정보 목록이 되면 안 된다 — output/ 은 무시되지만
        사람이 열어 보는 파일이고, 실수로 어딘가에 붙여 넣기 쉽다."""
        ocr = {"assets/images/a.png": ["연락처 010-0000-4321 / a@b.co.kr"]}
        blob = json.dumps(self.mod.judge(ocr, allow_paths=set()), ensure_ascii=False)
        self.assertNotIn("0000-4321", blob)
        self.assertNotIn("a@b.co.kr", blob)
        self.assertIn("010-****-4321", blob)

    def test_missing_verdict_file_hides_nothing(self):
        """검사를 아직 안 돌렸다고 발행이 멈추면 안 된다."""
        self.assertEqual(self.mod.hidden_paths({}), set())

    def test_apply_switch_defaults_to_on_when_config_is_absent(self):
        """설정이 없는 상태가 '안전한 쪽' 이어야 한다."""
        self.assertTrue(self.mod.hiding_enabled(ROOT / "no-such-file.json"))

    def test_apply_switch_can_hold_the_hiding(self):
        import json as _json
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "allow.json"
            p.write_text(_json.dumps({"apply": False, "paths": []}), encoding="utf-8")
            self.assertFalse(self.mod.hiding_enabled(p))
            p.write_text(_json.dumps({"apply": True, "paths": []}), encoding="utf-8")
            self.assertTrue(self.mod.hiding_enabled(p))


class HideMediaTest(unittest.TestCase):
    def setUp(self):
        from scripts import build_site
        self.hide = build_site.hide_pii_media

    def test_hidden_photo_and_its_thumb_both_leave(self):
        media = [{"kind": "image",
                  "images": ["assets/images/a.png", "assets/images/b.png"],
                  "thumbs": ["assets/thumbs/a.png", "assets/thumbs/b.png"],
                  "count": 2}]
        out = self.hide(media, {"assets/images/a.png"})[0]
        self.assertEqual(out["images"], ["assets/images/b.png"])
        # 작은 사진은 같은 그림을 줄인 것이라 글자가 그대로 남는다
        self.assertEqual(out["thumbs"], ["assets/thumbs/b.png"])
        self.assertEqual(out["pii_hidden"], 1)

    def test_untouched_items_keep_their_identity(self):
        media = [{"kind": "video", "videos": ["assets/videos/v.mp4"], "images": []},
                 {"kind": "file", "name": "x.pdf"}]
        self.assertEqual(self.hide(media, {"assets/images/a.png"}), media)

    def test_placeholder_count_survives_when_every_photo_is_hidden(self):
        """한 장도 안 남아도 '있었다'는 사실은 남아야 한다 — 그래야 화면이
        빈 칸 대신 이유를 그린다."""
        media = [{"kind": "image", "images": ["assets/images/a.png"],
                  "thumbs": ["assets/thumbs/a.png"], "count": 1}]
        out = self.hide(media, {"assets/images/a.png"})[0]
        self.assertEqual(out["images"], [])
        self.assertEqual(out["pii_hidden"], 1)


class RepoHygieneTest(unittest.TestCase):
    def test_allow_list_file_is_not_committed(self):
        """`config/pii_allow.json` 은 감추지 않을 연락처를 적는 곳이라
        그 자체가 연락처 목록이다. members.json 과 같은 취급을 한다."""
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("/config/pii_allow.json", ignore)
        self.assertTrue((ROOT / "config" / "pii_allow.example.json").exists())

    def test_daily_run_checks_photos_before_publishing(self):
        """검사가 발행보다 뒤면 그날 사진이 검사 없이 올라간다.

        '테스트가 적재보다 먼저' 와 같은 종류의 순서 문제다 — 한 번 겪은 자리라
        검사로 굳혀 둔다.
        """
        src = (ROOT / "scripts" / "run_daily.ps1").read_text(encoding="utf-8")
        scan = src.index("scripts.scan_image_pii")
        publish = src.index("scripts.build_firestore_payload")
        self.assertLess(scan, publish, "사진 개인정보 검사가 발행보다 뒤에 있다")


@needs_real_data
class PublicationTest(unittest.TestCase):
    """발행본에 가릴 것이 남아 있으면 배포를 막는다."""

    @classmethod
    def setUpClass(cls):
        from scripts import build_firestore_payload as bfp
        cls.payload = bfp.build_payload()

    def test_shared_documents_carry_no_maskable_pii(self):
        for name in ("meta", "threads", "media", "digests", "graph"):
            blob = json.dumps(self.payload[name], ensure_ascii=False)
            certain = [h for h in pii.find(blob) if h.grade == "certain"]
            self.assertEqual(
                certain, [],
                "%s 에 개인정보가 남았다: %s"
                % (name, ", ".join(h.value for h in certain[:5])),
            )

    def ledger_texts(self):
        """원장(`output/messages.jsonl`) 의 id → 본문.

        '가려지지 않았음' 은 **원장과 같은지**로 본다. 처음에는 `'****' 가
        없는지`로 검사했는데, 마스킹을 이야기하는 대화가 방에 올라온 순간
        (msg-002696 — "'우리의 기록' 앱에 **** 마킹이 되고") 오탐으로 발행이
        멈췄다(2026-07-30 23:43, 그날 새 글 34건이 이틀 묶였다). 마스킹 표식은
        사람이 쓸 수 있는 글자이므로, 표식의 존재가 아니라 **본문이 바뀌었는지**를
        봐야 한다.
        """
        path = ROOT / "output" / "messages.jsonl"
        out = {}
        with path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    m = json.loads(line)
                    out[m["id"]] = m.get("text") or ""
        return out

    def assert_untouched(self, items, where):
        ledger = self.ledger_texts()
        for m in items:
            original = ledger.get(m["id"])
            if original is None:      # 원장에 없는 것은 이 검사의 대상이 아니다
                continue
            self.assertEqual(
                m.get("text") or "", original,
                "%s 의 %s 본문이 원장과 다르다 — 가려진 것으로 보인다" % (where, m["id"]),
            )

    def test_admin_ledger_keeps_the_original(self):
        """관리자 원장은 가리지 않는다 — 오탐을 되돌릴 근거가 사라진다."""
        self.assert_untouched(self.payload["messages_source"], "messages_source")

    def test_own_messages_are_not_masked(self):
        """본인 글은 원문으로 보여야 한다. 무엇을 지울지 고르려면 봐야 한다."""
        for email, items in self.payload["my_messages"].items():
            self.assert_untouched(items, "my_messages[%s]" % email)


@needs_real_data
class HiddenPhotoIsNotUploadedTest(unittest.TestCase):
    """감출 사진은 **업로드 목록에서** 빠져야 한다.

    화면 발행본에서만 빼고 Storage 에는 올려 두면, 주소를 아는 사람은 화면을
    거치지 않고 그대로 받는다. 관심 주제 빠지기에서 같은 함정을 한 번 겪었다 —
    화면에서 감추는 것은 감추는 것이 아니다.
    """

    @classmethod
    def setUpClass(cls):
        from scripts import build_firestore_payload as bfp
        from scripts import scan_image_pii

        base = bfp.build_payload()
        cls.victim = next(
            (p for p in base["images"] if p.startswith("assets/images/")), None)

        # 판정 결과를 하나만 바꿔 끼우고 다시 발행해 본다
        original = scan_image_pii.hidden_paths
        scan_image_pii.hidden_paths = staticmethod(lambda *a, **k: {cls.victim})
        try:
            cls.payload = bfp.build_payload()
        finally:
            scan_image_pii.hidden_paths = original

    def test_the_photo_is_absent_from_the_upload_list(self):
        self.assertIsNotNone(self.victim, "발행본에 사진이 없어 검사할 수 없다")
        self.assertNotIn(self.victim, self.payload["images"])

    def test_its_thumbnail_leaves_too(self):
        thumb = self.victim.replace("assets/images/", "assets/thumbs/")
        self.assertNotIn(thumb, self.payload["images"])

    def test_other_photos_still_upload(self):
        """한 장을 감추는 일이 나머지를 함께 떨어뜨리면 안 된다."""
        others = [p for p in self.payload["images"]
                  if p.startswith("assets/images/")]
        self.assertGreater(len(others), 0)

    def test_the_screen_shows_a_placeholder_instead(self):
        marked = sum(m.get("pii_hidden") or 0 for m in self.payload["media"])
        self.assertEqual(marked, 1)


if __name__ == "__main__":
    unittest.main()
