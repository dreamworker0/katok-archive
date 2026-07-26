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


def _messages():
    return build_site._read_jsonl(ROOT / "output" / "messages.jsonl")


class PayloadShapeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = bfp.build_payload()
        cls.messages = _messages()

    def test_chunks_cover_all_messages_in_order(self):
        seen = []
        for ch in self.payload["chunks"]:
            seen.extend(m["id"] for m in ch["messages"])
        self.assertEqual(len(seen), len(self.messages))
        self.assertEqual(seen, [m["id"] for m in self.messages])

    def test_chunk_docs_are_well_under_firestore_limit(self):
        """Firestore 문서 상한은 1MiB. 청크가 이를 넘으면 적재가 실패한다."""
        for ch in self.payload["chunks"]:
            size = len(json.dumps(ch, ensure_ascii=False).encode("utf-8"))
            self.assertLess(size, 700_000, ch["id"])

    def test_chunk_sequence_is_contiguous(self):
        seqs = [c["seq"] for c in self.payload["chunks"]]
        self.assertEqual(seqs, list(range(len(seqs))))

    def test_meta_counts_match_payload(self):
        m = self.payload["meta"]
        self.assertEqual(m["chunk_count"], len(self.payload["chunks"]))
        self.assertEqual(m["thread_count"], len(self.payload["threads"]))
        self.assertEqual(m["message_count"], len(self.messages))
        self.assertEqual(m["image_count"], len(self.payload["images"]))

    def test_images_listed_exist_on_disk(self):
        for rel in self.payload["images"]:
            self.assertTrue(rel.startswith("assets/images/"), rel)
            self.assertTrue((ROOT / rel).exists(), rel)

    def test_graph_bulk_docs_present(self):
        self.assertTrue(self.payload["graph"]["nodes"])
        self.assertTrue(self.payload["graph"]["edges"])

    def test_bulk_docs_fit_in_one_document(self):
        """스레드·그래프는 한 문서로 묶어 발행한다(읽기 절약). 1MiB 한도 확인."""
        for name, obj in (
            ("threads/all", {"items": self.payload["threads"]}),
            ("graph/nodes", {"items": self.payload["graph"]["nodes"]}),
            ("graph/edges", {"items": self.payload["graph"]["edges"]}),
        ):
            size = len(json.dumps(obj, ensure_ascii=False).encode("utf-8"))
            self.assertLess(size, 700_000, "%s 가 너무 큼: %d bytes" % (name, size))

    def test_full_load_read_count_stays_small(self):
        """멤버 1명의 전체 로드 읽기 횟수 상한을 고정한다.

        메시지·스레드를 문서당 1건으로 두면 1,600회를 넘어 무료 한도를 위협한다.
        묶음 발행이 깨지면 이 테스트가 잡아낸다.
        """
        reads = (
            1                                   # meta/archive
            + len(self.payload["chunks"])       # 메시지 청크
            + 1                                 # threads/all
            + len(self.payload["digests"])      # 요지(주제별 편집 단위라 개별 유지)
            + 2                                 # graph/nodes, graph/edges
            + 1                                 # 본인 members 문서
        )
        self.assertLessEqual(reads, 60, "전체 로드 읽기가 너무 많음: %d회" % reads)

    def test_member_emails_are_lowercased_and_unique(self):
        emails = [m["email"] for m in self.payload["members"]]
        self.assertEqual(emails, [e.lower() for e in emails])
        self.assertEqual(len(emails), len(set(emails)))
        for m in self.payload["members"]:
            self.assertIn(m["role"], ("admin", "user"))

    def test_members_carry_nickname_field(self):
        for m in self.payload["members"]:
            self.assertIn("nickname", m)

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
        members = [{"email": "a@x.com", "nickname": "김종원"}]
        self.assertEqual(bfp.check_member_nicknames(members, self.PARTICIPANTS), [])

    def test_typo_is_reported(self):
        members = [{"email": "b@x.com", "nickname": "김종언"}]
        warnings = bfp.check_member_nicknames(members, self.PARTICIPANTS)
        self.assertEqual(len(warnings), 1)
        self.assertIn("b@x.com", warnings[0])
        self.assertIn("김종언", warnings[0])

    def test_missing_nickname_is_reported(self):
        members = [{"email": "c@x.com", "nickname": ""}]
        warnings = bfp.check_member_nicknames(members, self.PARTICIPANTS)
        self.assertEqual(len(warnings), 1)
        self.assertIn("미기입", warnings[0])


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

        # 1) 발행 청크에 해당 인물의 메시지가 하나도 없다
        for ch in payload["chunks"]:
            for m in ch["messages"]:
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

        for ch in payload["chunks"]:
            for m in ch["messages"]:
                self.assertNotIn(token, m.get("text") or "")
        reasons = payload["exclusion_report"]["dropped_by_reason"]
        self.assertIn("keyword:" + token, reasons)

    def test_message_id_exclusion(self):
        target = self.messages[5]["id"]
        excl = {"exclude_people": [], "exclude_keywords": [],
                "exclude_message_ids": [target], "drop_person_apps": True}
        payload = self._payload_with(excl)
        published = {m["id"] for ch in payload["chunks"] for m in ch["messages"]}
        self.assertNotIn(target, published)

    def test_threads_stay_consistent_after_exclusion(self):
        """제외 후에도 스레드가 발행된 메시지만 가리켜야 한다."""
        excl = {"exclude_people": [self.victim], "exclude_keywords": [],
                "exclude_message_ids": [], "drop_person_apps": True}
        payload = self._payload_with(excl)
        published = {m["id"] for ch in payload["chunks"] for m in ch["messages"]}
        for t in payload["threads"]:
            self.assertIn(t["start_msg"], published, t["id"])
            self.assertIn(t["end_msg"], published, t["id"])
            self.assertGreaterEqual(t["count"], 1)

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
        published = [m for ch in payload["chunks"] for m in ch["messages"]]
        self.assertEqual(len(published), len(self.messages))
        self.assertEqual(payload["exclusion_report"]["dropped_count"], 0)


if __name__ == "__main__":
    unittest.main()
