# -*- coding: utf-8 -*-
"""Firestore 페이로드 생성 검증 — 네트워크 없이 순수 변환만 확인한다.

특히 '제외 규칙'이 발행본에서 완전히 사라지는지(메시지·스레드·통계·그래프·요지
전부)를 검증한다. 제외가 반쪽만 적용되면 이름이 통계나 그래프에 남기 때문이다.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts import build_firestore_payload as bfp  # noqa: E402
from scripts import build_site  # noqa: E402
from tests.realdata import needs_real_data  # noqa: E402


def _messages():
    return build_site._read_jsonl(ROOT / "output" / "messages.jsonl")


@needs_real_data
class PayloadShapeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = bfp.build_payload()
        cls.messages = _messages()

    def test_no_raw_message_text_is_published(self):
        """멤버에게 나가는 발행본에 대화 본문이 섞이면 안 된다.

        예전에는 chunks 문서에 본문이 실려 나가 화면에 안 보여도 devtools 로
        전부 읽혔다. 이 방의 가치는 오간 말이 아니라 그 안의 내용이다.
        """
        self.assertNotIn("chunks", self.payload)
        published = json.dumps(
            {k: self.payload[k] for k in ("meta", "threads", "media", "digests", "graph")},
            ensure_ascii=False,
        )
        # 원문에만 있고 요약에는 없을 법한 문장을 표본으로 확인한다
        # 링크는 결과물이라 일부러 남긴다. URL 이 든 글은 표본에서 뺀다.
        sample = [m["text"] for m in self.messages
                  if m.get("kind") == "text" and not m.get("urls")
                  and len(m.get("text") or "") > 40][:80]
        for text in sample:
            self.assertNotIn(text, published, "원문이 발행본에 남았다: " + text[:40])

    def test_every_published_document_fits(self):
        """올라가는 문서 하나하나가 한도 아래여야 한다 — 총량이 아니라 문서다.

        예전에는 threads·media 전체를 한 덩어리로 재서 700KB 와 비교했다. 그러면
        데이터가 늘기만 해도 깨진다 — 2026-09-01 밤 갱신이 주제 400개가 되며
        정확히 그렇게 멈췄다. 이제 나눠 담는 컬렉션은 업로더가 자르므로, 검사도
        업로더와 같은 규칙(plan_documents)으로 문서를 나눈 뒤 **각 문서**를 본다.
        """
        for d in bfp.plan_documents(self.payload):
            self.assertLess(d["bytes"], bfp.DOC_LIMIT,
                            "%s/%s 가 너무 큼: %d bytes"
                            % (d["collection"], d["id"], d["bytes"]))

    def test_meta_counts_match_payload(self):
        m = self.payload["meta"]
        self.assertEqual(m["thread_count"], len(self.payload["threads"]))
        self.assertEqual(m["media_count"], len(self.payload["media"]))
        self.assertEqual(m["message_count"], len(self.messages))
        self.assertEqual(m["image_count"], len(self.payload["images"]))

    def test_my_messages_only_hold_own_posts(self):
        """본인 문서에 남의 글이 섞이면 그대로 유출이다."""
        members = {m["email"]: set(m["nicknames"]) for m in self.payload["members"]}
        for email, items in self.payload["my_messages"].items():
            names = members.get(email, set())
            for it in items:
                self.assertIn(it["nickname"], names,
                              "%s 문서에 %s 의 글이 들어 있다" % (email, it["nickname"]))

    def test_my_messages_fit_in_one_document(self):
        for email, items in self.payload["my_messages"].items():
            size = len(json.dumps({"items": items}, ensure_ascii=False).encode("utf-8"))
            self.assertLess(size, 1_000_000, "%s 문서가 1MiB 를 넘음" % email)

    def test_images_listed_exist_on_disk(self):
        """올릴 목록은 세 뿌리 중 하나여야 한다 — 원본·갤러리용 작은 사진·동영상.

        경로 뿌리를 좁게 붙잡는 이유: storage.rules 가 images/**·thumbs/**·videos/**
        만 열어 둔다. 다른 뿌리를 올리면 규칙이 막아 화면에서 403 이 나고, 그건
        배포한 뒤에야 드러난다.

        videos 는 2026-07-28 에 더했다. 그때까지 업로드 목록이 동영상을 빠뜨려
        저장소에 파일이 아예 없었고, 화면은 미리보기만 걸린 채 재생되지 않았다.
        """
        roots = ("assets/images/", "assets/thumbs/", "assets/videos/")
        for rel in self.payload["images"]:
            self.assertTrue(rel.startswith(roots), rel)
            self.assertTrue((ROOT / rel).exists(), rel)

    def test_graph_bulk_docs_present(self):
        self.assertTrue(self.payload["graph"]["nodes"])
        self.assertTrue(self.payload["graph"]["edges"])

    def test_chunked_collections_split_into_documents_that_fit(self):
        """나눠 담는 컬렉션은 **항목 하나**가 한도를 넘지 않아야 한다.

        전체가 커지는 것은 나눠 담기가 해결한다. 나눠 담기가 못 푸는 경우는 하나뿐
        이다 — 항목 하나가 통째로 한 문서보다 클 때. 그때는 잘라도 그 문서가 한도를
        넘으므로 적재가 실패한다. 총량이 아니라 그것을 본다. 문서 수도 묶는다 —
        문서가 늘면 모두의 첫 화면 읽기가 늘어나므로 조용히 늘지 않게 한다.
        """
        docs = bfp.plan_documents(self.payload)
        for coll in ("threads", "aiReports", "media"):
            ds = [d for d in docs if d["collection"] == coll]
            self.assertTrue(ds and all(d["chunked"] for d in ds), coll)
            for d in ds:
                self.assertLess(d["largest_item"] + 3, bfp.CHUNK_BYTES,
                                "%s 의 항목 하나가 문서보다 큽니다(%d bytes) — "
                                "나눠 담아도 안 들어갑니다" % (coll, d["largest_item"]))
            self.assertLessEqual(len(ds), bfp.CHUNK_DOCS_MAX,
                                 "%s 가 %d문서로 갈라집니다" % (coll, len(ds)))

    def test_size_warnings_are_quiet_today(self):
        """80% 경고가 하나라도 있으면 사람이 봐야 한다.

        경고는 발행 로그에 찍히지만 로그는 아침에 읽는다. 여기서도 걸리게 해서
        '검사는 초록인데 로그에는 주의가 있다' 는 상태가 조용히 몇 주 가지 않게
        한다. 걸리면 그 문서를 나눠 담을 길을 정하고, 정한 뒤 이 검사를 고친다.
        """
        self.assertEqual(bfp.size_warnings(bfp.plan_documents(self.payload)), [])

    def test_full_load_read_count_stays_small(self):
        """멤버 1명의 전체 로드 읽기 횟수 상한을 고정한다.

        메시지·스레드를 문서당 1건으로 두면 1,600회를 넘어 무료 한도를 위협한다.
        묶음 발행이 깨지면 이 테스트가 잡아낸다. 어림값이 아니라 실제로 올라가는
        문서 수(plan_documents)를 센다 — 본인 myMessages 와 members 문서 하나씩.
        """
        docs = bfp.plan_documents(self.payload)
        reads = (sum(1 for d in docs if d["collection"] != "myMessages")
                 + 1 + 1)
        self.assertLessEqual(reads, 30, "전체 로드 읽기가 너무 많음: %d회" % reads)

    def test_member_emails_are_lowercased_and_unique(self):
        emails = [m["email"] for m in self.payload["members"]]
        self.assertEqual(emails, [e.lower() for e in emails])
        self.assertEqual(len(emails), len(set(emails)))
        for m in self.payload["members"]:
            self.assertIn(m["role"], ("admin", "user"))

    def test_members_carry_nickname_fields(self):
        for m in self.payload["members"]:
            self.assertIn("nickname", m)
            self.assertIsInstance(m["nicknames"], list)

    def test_storage_rules_hold_no_member_emails(self):
        """Custom Claims 로 옮긴 뒤로 규칙에 이메일이 들어가면 안 된다.

        예전에는 멤버 목록을 규칙에 생성해 박아 넣었고, 그 치환이 설명 주석까지
        건드려 멤버 2명째부터 배포가 깨졌다. 이제 규칙은 고정 파일이므로 다시
        생성물로 되돌아가지 않았는지만 지킨다.
        """
        rules = (Path(__file__).resolve().parent.parent / "storage.rules").read_text(
            encoding="utf-8")
        self.assertIn("request.auth.token.member == true", rules)
        self.assertNotIn("@", rules.split("service firebase.storage")[1])


class MemberNicknameTest(unittest.TestCase):
    """로그인 계정 ↔ 대화방 참여자 연결은 손으로 넣는 값이라 대조가 필요하다."""

    PARTICIPANTS = {"participants": [{"nickname": "김종원"}, {"nickname": "한도윤"}]}

    def test_matching_nickname_has_no_warning(self):
        members = [{"email": "a@x.com", "nicknames": ["김종원"]}]
        self.assertEqual(bfp.check_member_nicknames(members, self.PARTICIPANTS), [])

    def test_typo_is_reported(self):
        members = [{"email": "b@x.com", "nicknames": ["김종언"]}]
        warnings = bfp.check_member_nicknames(members, self.PARTICIPANTS)
        self.assertEqual(len(warnings), 1)
        self.assertIn("b@x.com", warnings[0])
        self.assertIn("김종언", warnings[0])

    def test_missing_nickname_is_reported(self):
        members = [{"email": "c@x.com", "nicknames": []}]
        warnings = bfp.check_member_nicknames(members, self.PARTICIPANTS)
        self.assertEqual(len(warnings), 1)
        self.assertIn("미연결", warnings[0])

    def test_non_speaking_account_is_not_warned_about(self):
        """대화에 참여하지 않는 운영 계정은 경고 대상이 아니다.

        카톡 수집을 위해 컴퓨터에 로그인해 둔 계정('문가은')은 영영 참여자 명단에
        없다. 그대로 두면 매일 밤 같은 경고가 뜨고, 늘 뜨는 경고는 아무도 안 본다.
        """
        members = [{"email": "d@x.com", "nicknames": ["문가은"], "speaks": False}]
        self.assertEqual(bfp.check_member_nicknames(members, self.PARTICIPANTS), [])

    def test_speaks_defaults_to_true(self):
        # 표시가 없으면 참여하는 사람으로 본다 — 조용히 넘어가는 쪽이 기본이면 안 된다
        members = [{"email": "e@x.com", "nicknames": ["없는이름"]}]
        self.assertEqual(len(bfp.check_member_nicknames(members, self.PARTICIPANTS)), 1)

    def test_load_members_carries_the_flag(self):
        # 수집용 계정을 이메일로 찍어 두지 않는다. 이 저장소는 공개이고, 실제
        # 주소를 검사에 박으면 그 자체가 연락처 목록이 된다(config/members.json 을
        # .gitignore 하는 것과 같은 이유다). 표시(speaks=false)로 찾는다.
        loaded = bfp.load_members()
        silent = [m for m in loaded if m.get("speaks") is False]
        for m in silent:   # 실제 명부에 있을 때만 (config 는 환경마다 다르다)
            with self.subTest(email=m["email"]):
                self.assertFalse(m["speaks"], "수집용 계정은 speaks=false 여야 한다")
        for m in loaded:
            with self.subTest(email=m["email"]):
                self.assertIn("speaks", m)

    def test_multiple_names_all_known_is_clean(self):
        """이름을 바꾼 사람은 두 표시명이 모두 명단에 있다."""
        members = [{"email": "d@x.com", "nicknames": ["김종원", "한도윤"]}]
        self.assertEqual(bfp.check_member_nicknames(members, self.PARTICIPANTS), [])

    def test_only_the_unknown_name_is_reported(self):
        members = [{"email": "e@x.com", "nicknames": ["김종원", "없는이름"]}]
        warnings = bfp.check_member_nicknames(members, self.PARTICIPANTS)
        self.assertEqual(len(warnings), 1)
        self.assertIn("없는이름", warnings[0])
        self.assertNotIn("김종원", warnings[0])


@needs_real_data
class ExclusionTest(unittest.TestCase):
    """제외 규칙이 발행본 전체에서 소거되는지 확인."""

    def setUp(self):
        self.messages = _messages()
        # 실제 데이터에서 대상 고르기: 메시지가 있는 참여자 1명
        self.victim = self.messages[0]["nickname"]

    def _payload_with(self, exclusions, monkey_messages=None):
        """build_payload 를 흉내내되 제외 설정만 바꿔 실행한다."""
        orig_load = bfp.load_exclusions
        bfp.load_exclusions = lambda: exclusions
        try:
            return bfp.build_payload()
        finally:
            bfp.load_exclusions = orig_load

    def test_person_exclusion_removes_from_everywhere(self):
        excl = {"exclude_people": [self.victim], "exclude_keywords": [],
                "exclude_message_ids": [], "drop_person_apps": True}
        payload = self._payload_with(excl)

        # 1) 발행본 어디에도 해당 인물이 남지 않는다
        for t in payload["threads"]:
            self.assertNotIn(self.victim, t.get("participants") or [])
        for m in payload["media"]:
            self.assertNotEqual(m["nickname"], self.victim)

        # 2) 통계 참여자 목록에서도 사라진다
        nicks = [p["nickname"] for p in payload["meta"]["stats"]["participants"]]
        self.assertNotIn(self.victim, nicks)

        # 3) 그래프에 person 노드가 없다
        labels = [n["label"] for n in payload["graph"]["nodes"] if n["type"] == "person"]
        self.assertNotIn(self.victim, labels)

        # 4) 그래프 엣지에 끊긴 참조가 남지 않는다
        ids = {n["id"] for n in payload["graph"]["nodes"]}
        for e in payload["graph"]["edges"]:
            self.assertIn(e["source"], ids)
            self.assertIn(e["target"], ids)

        # 5) 리포트가 무엇을 왜 뺐는지 남긴다 (조용한 누락 방지)
        self.assertGreater(payload["exclusion_report"]["dropped_count"], 0)
        self.assertIn("person", payload["exclusion_report"]["dropped_by_reason"])

    def test_keyword_exclusion_drops_matching_messages(self):
        # 실제 본문에 존재하는 토큰을 골라 키워드로 사용
        token = None
        for m in self.messages:
            if "파이어베이스" in (m.get("text") or ""):
                token = "파이어베이스"
                break
        self.assertIsNotNone(token, "테스트용 키워드를 찾지 못함")

        excl = {"exclude_people": [], "exclude_keywords": [token],
                "exclude_message_ids": [], "drop_person_apps": True}
        payload = self._payload_with(excl)

        for items in payload["my_messages"].values():
            for m in items:
                self.assertNotIn(token, m.get("text") or "")
        reasons = payload["exclusion_report"]["dropped_by_reason"]
        self.assertIn("keyword:" + token, reasons)

    def test_message_id_exclusion(self):
        target = self.messages[5]["id"]
        excl = {"exclude_people": [], "exclude_keywords": [],
                "exclude_message_ids": [target], "drop_person_apps": True}
        payload = self._payload_with(excl)
        for items in payload["my_messages"].values():
            self.assertNotIn(target, [m["id"] for m in items])
        self.assertNotIn(target, [m["id"] for m in payload["media"]])

    def test_threads_stay_consistent_after_exclusion(self):
        """제외 후에도 스레드가 발행된 메시지만 가리켜야 한다."""
        excl = {"exclude_people": [self.victim], "exclude_keywords": [],
                "exclude_message_ids": [], "drop_person_apps": True}
        payload = self._payload_with(excl)
        for t in payload["threads"]:
            self.assertGreaterEqual(t["count"], 1)
            self.assertNotIn(self.victim, t.get("participants") or [])
            self.assertTrue(t.get("title"))
            self.assertTrue(t.get("start_date"))

    def test_source_collection_keeps_everything(self):
        """원본(관리자 전용)은 제외와 무관하게 전량 보존한다."""
        excl = {"exclude_people": [self.victim], "exclude_keywords": [],
                "exclude_message_ids": [], "drop_person_apps": True}
        payload = self._payload_with(excl)
        self.assertEqual(len(payload["messages_source"]), len(self.messages))

    def test_no_exclusions_keeps_all(self):
        excl = {"exclude_people": [], "exclude_keywords": [],
                "exclude_message_ids": [], "drop_person_apps": True}
        payload = self._payload_with(excl)
        self.assertEqual(payload["exclusion_report"]["kept_count"], len(self.messages))
        self.assertEqual(payload["exclusion_report"]["dropped_count"], 0)


class DocumentPlanTest(unittest.TestCase):
    """plan_documents · chunk_items · size_warnings — 지어낸 자료로, 어디서든 돈다."""

    @staticmethod
    def _payload(**over):
        base = {
            "meta": {"chat_room": "x"},
            "threads": [{"id": "t-%03d" % i, "report": "가" * 100} for i in range(5)],
            "ai_reports": [],
            "media": [{"id": "m-1"}],
            "digests": {"projects": {"body": "나"}},
            "graph": {"nodes": [{"id": "n"}], "edges": []},
            "my_messages": {"a@example.com": [{"id": "msg-1", "text": "안녕"}]},
        }
        base.update(over)
        return base

    def test_chunk_items_splits_by_bytes_not_count(self):
        items = [{"s": "가" * 100}] * 10       # 항목 하나 ≈ 300 바이트
        docs = bfp.chunk_items(items, cap=1000)
        self.assertGreater(len(docs), 1)
        self.assertEqual(sum(len(d) for d in docs), 10)
        for d in docs:
            self.assertLessEqual(bfp._nbytes(d), 1000)

    def test_chunk_items_keeps_one_empty_doc(self):
        self.assertEqual(bfp.chunk_items([]), [[]])

    def test_plan_marks_chunked_collections(self):
        docs = bfp.plan_documents(self._payload())
        by = {(d["collection"], d["id"]): d for d in docs}
        self.assertTrue(by[("threads", "000")]["chunked"])
        self.assertTrue(by[("media", "000")]["chunked"])
        self.assertTrue(by[("aiReports", "000")]["chunked"])   # 비어도 문서 하나
        self.assertFalse(by[("graph", "nodes")]["chunked"])
        self.assertFalse(by[("digests", "projects")]["chunked"])
        self.assertFalse(by[("myMessages", "a@example.com")]["chunked"])

    def test_warns_at_eighty_percent_for_unsplittable_docs(self):
        big = [{"id": "n%d" % i, "label": "가" * 200} for i in range(1000)]  # ≈ 600KB
        docs = bfp.plan_documents(self._payload(graph={"nodes": big, "edges": []}))
        warns = bfp.size_warnings(docs)
        self.assertTrue(any("graph/nodes" in w and "80%" in w for w in warns), warns)

    def test_no_warning_when_small(self):
        self.assertEqual(bfp.size_warnings(bfp.plan_documents(self._payload())), [])

    def test_warns_when_a_single_item_nears_chunk_size(self):
        huge = [{"id": "t-1", "report": "가" * 170_000}]   # ≈ 510KB > 600KB 의 80%
        docs = bfp.plan_documents(self._payload(threads=huge))
        warns = bfp.size_warnings(docs)
        self.assertTrue(any(w.startswith("threads 의 항목 하나가") for w in warns), warns)


if __name__ == "__main__":
    unittest.main()
