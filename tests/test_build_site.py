# -*- coding: utf-8 -*-
"""build_site 데이터 조립 및 topics 커버리지 검증."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts import build_site  # noqa: E402


def _load():
    messages = build_site._read_jsonl(ROOT / "output" / "messages.jsonl")
    images = build_site._read_jsonl(ROOT / "output" / "images.jsonl")
    participants = build_site._read_json(ROOT / "output" / "participants.json")
    topics = build_site._read_json(ROOT / "output" / "topics.json")
    knowledge = build_site._read_json(ROOT / "output" / "knowledge.json")
    digest_prose = build_site._read_json(ROOT / "output" / "topic-digests.json")
    return messages, images, participants, topics, knowledge, digest_prose


class BuildDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (cls.messages, cls.images, cls.participants, cls.topics,
         cls.knowledge, cls.digest_prose) = _load()
        cls.data = build_site.build_data(
            cls.messages, cls.images, cls.participants, cls.topics,
            cls.knowledge, cls.digest_prose,
        )

    def test_all_messages_present(self):
        self.assertEqual(len(self.data["messages"]), len(self.messages))

    def test_topic_coverage_full_and_unique(self):
        """모든 메시지가 정확히 하나의 스레드에 속한다."""
        seen = []
        for t in self.topics["threads"]:
            seen.extend(t["message_ids"])
        self.assertEqual(len(seen), len(self.messages), "커버리지 개수 불일치")
        self.assertEqual(len(set(seen)), len(seen), "스레드 간 메시지 중복")
        self.assertEqual(set(seen), {m["id"] for m in self.messages}, "누락/불일치")

    def test_every_message_has_category(self):
        cats = {c["id"] for c in self.topics["categories"]}
        for m in self.data["messages"]:
            self.assertIn("category", m, m["id"])
            self.assertIn(m["category"], cats)

    def test_image_join_downloaded_vs_pending(self):
        img_status = {i["message_id"]: i for i in self.images}
        n_with_files = 0
        for m in self.data["messages"]:
            if m["kind"] != "image":
                continue
            self.assertIn("images", m)
            self.assertIn("image_pending", m)
            if m["images"]:
                n_with_files += 1
                self.assertFalse(m["image_pending"])
                self.assertFalse(m["image_lost"])
                for p in m["images"]:
                    self.assertTrue(p.startswith("assets/images/"))
                    self.assertTrue((ROOT / p).exists(), p)
            else:
                # 파일이 없는 사진은 두 갈래다. '수집 대기'는 언젠가 채워지고,
                # '유실'은 원본이 영영 없다(옛 백업에서 온 <사진 읽지 않음>).
                # 둘을 한 상태로 뭉치면 남은 수집 일감을 셀 수 없다.
                lost = img_status[m["id"]]["status"] == "lost"
                self.assertEqual(m["image_lost"], lost, m["id"])
                self.assertEqual(m["image_pending"], not lost, m["id"])
        # 파일을 가진 '사진' 레코드 수와 파일 보유 사진 메시지 수 정합.
        # 동영상은 같은 대장(images.jsonl)을 쓰지만 사진 목록에 들어가지 않으므로
        # 여기서 빼야 한다 — 안 빼면 동영상을 넣는 순간 이 검사가 어긋난다.
        downloaded_records = [
            i for i in self.images
            if i.get("assets") and (i.get("media_kind") or "image") == "image"
        ]
        self.assertEqual(n_with_files, len(downloaded_records))

    def test_every_referenced_image_exists_and_every_file_is_used(self):
        """참조와 파일이 서로 빠짐없이 맞물리는가.

        '참조 수 == 파일 수' 로 보면 안 된다 — 내용이 같은 사진은 한 번만 저장하고
        여러 메시지가 함께 가리킨다(같은 사진을 두 사람이 올린 경우). 같은 바이트를
        두 번 두지 않으려고 일부러 그렇게 했다. 그래서 두 방향을 따로 본다.
        """
        referenced = set()
        for m in self.data["messages"]:
            for p in m.get("images") or []:
                self.assertTrue(p.startswith("assets/images/"), p)
                self.assertTrue((ROOT / p).exists(), "참조하는데 파일이 없다: " + p)
                referenced.add(p)

        on_disk = {
            str(p.relative_to(ROOT)).replace("\\", "/")
            for p in (ROOT / "assets" / "images").rglob("*.*")
        }
        self.assertEqual(on_disk - referenced, set(), "아무도 안 쓰는 사진 파일")
        self.assertEqual(
            self.data["stats"]["totals"]["downloaded_images"],
            sum(len(m.get("images") or []) for m in self.data["messages"]))

    def test_participant_totals_consistent(self):
        stat_sum = sum(p["message_count"] for p in self.data["stats"]["participants"])
        self.assertEqual(stat_sum, len(self.messages))

    def test_monthly_sums_to_total(self):
        s = sum(x["count"] for x in self.data["stats"]["monthly"])
        self.assertEqual(s, len(self.messages))

    def test_category_message_counts_sum_to_total(self):
        s = sum(c["messages"] for c in self.data["stats"]["categories"])
        self.assertEqual(s, len(self.messages))

    def test_threads_have_participants_and_dates(self):
        for t in self.data["threads"]:
            self.assertTrue(t["participants"])
            self.assertTrue(t["start_date"])
            self.assertTrue(t["end_date"])
            self.assertGreaterEqual(t["count"], 1)

    def test_contextual_resources_are_published_without_source_text(self):
        enriched = build_site.enrich_threads(self.data["threads"], self.data["messages"])
        thread = next(t for t in enriched if t["id"] == "t-162")
        target = next(link for link in thread["links"] if "youtu.be/HDfr8PvfoOw" in link["url"])

        self.assertIn("![[link:msg-001480]]", thread["report"])
        self.assertEqual(target["id"], "msg-001480")
        self.assertEqual(target["time"], "13:33")
        self.assertNotIn("text", target)
        self.assertNotIn(
            "일반적으로 AI가 공리주의적 사고에 기반한 응답",
            json.dumps(thread["links"], ensure_ascii=False),
        )

    def test_data_js_is_valid_json_payload(self):
        """write_site 가 만든 data.js 가 유효한 JSON을 담는지 검증.

        임시 폴더에 쓴다 — write_site 는 대상을 통째로 지우므로, 진짜 `site/` 에
        쓰면 사람이 보고 있던 미리보기가 테스트 때문에 사라진다.
        """
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp) / "site"
            build_site.write_site(self.data, site)
            text = (site / "data.js").read_text(encoding="utf-8")
            self.assertTrue(text.startswith("window.ARCHIVE = "))
            payload = text[len("window.ARCHIVE = "):].rstrip().rstrip(";")
            parsed = json.loads(payload)
            self.assertEqual(len(parsed["messages"]), len(self.messages))
            # 정적 파일·이미지도 복사되었는지
            for name in build_site.STATIC_FILES:
                self.assertTrue((site / name).exists(), name)
            self.assertTrue((site / "assets" / "images").exists())


class NodeSpanTest(unittest.TestCase):
    """노드에 언제 오간 이야기인지 붙인다.

    관계망에 시간이 없어서 작년에 한 번 스친 도구와 어제까지 쓰는 도구가 나란히 떠
    있었다 — 실측 2026-08-12: '소라2' 는 2025-10-04 하루에 1회, '슬랙' 은 2025-12-04
    부터 2026-08-12 까지 28회인데 화면에서 구별되지 않았다.
    """

    def _messages(self):
        return [
            {"id": "m1", "nickname": "갑", "date": "2025-10-01", "category": "chat",
             "text": "커서 써봤어요"},
            {"id": "m2", "nickname": "을", "date": "2025-11-05", "category": "ai-tools",
             "text": "옛날 도구 이야기"},
            {"id": "m3", "nickname": "갑", "date": "2026-08-01", "category": "ai-tools",
             "text": "커서 요즘도 쓴다", "urls": []},
        ]

    def _knowledge(self):
        return {"nodes": [
            {"id": "tool:cursor", "type": "tool", "label": "커서",
             "category": "ai-tools", "query": "커서"},
            {"id": "tool:ghost", "type": "tool", "label": "한번도안나온것",
             "category": "ai-tools", "query": "한번도안나온것"},
            {"id": "person:갑", "type": "person", "label": "갑", "category": "chat"},
            {"id": "topic:ai-tools", "type": "topic", "label": "AI 도구",
             "category": "ai-tools"},
        ], "edges": []}

    def _by_id(self, k):
        return {n["id"]: n for n in k["nodes"]}

    def test_span_comes_from_the_messages_that_name_it(self):
        k = self._knowledge()
        build_site.weigh_knowledge(k, self._messages())
        node = self._by_id(k)["tool:cursor"]
        self.assertEqual(("2025-10-01", "2026-08-01"),
                         (node["first_seen"], node["last_seen"]))
        self.assertEqual(2, node["mentions"], "중간의 남의 이야기는 세지 않는다")

    def test_a_node_never_mentioned_has_no_date_field_at_all(self):
        """빈 문자열을 넣지 않는다 — 화면이 '날짜가 있다' 고 믿고 빈 기간을 그린다."""
        k = self._knowledge()
        stale = build_site.weigh_knowledge(k, self._messages())
        node = self._by_id(k)["tool:ghost"]
        self.assertNotIn("first_seen", node)
        self.assertNotIn("last_seen", node)
        self.assertEqual(0, node["mentions"])
        self.assertIn("한번도안나온것(tool)", stale)

    def test_a_stale_date_is_removed_not_left_behind(self):
        # 옛 발행에서 붙은 날짜가 남아 있으면 화면이 없는 기간을 계속 보여준다.
        k = self._knowledge()
        self._by_id(k)["tool:ghost"].update(
            {"first_seen": "2025-01-01", "last_seen": "2025-01-02"})
        build_site.weigh_knowledge(k, self._messages())
        self.assertNotIn("first_seen", self._by_id(k)["tool:ghost"])

    def test_one_day_node_has_the_same_first_and_last(self):
        k = {"nodes": [{"id": "tool:sora", "type": "tool", "label": "소라2",
                        "category": "ai-models", "query": "소라2"}], "edges": []}
        build_site.weigh_knowledge(k, [
            {"id": "m1", "nickname": "갑", "date": "2025-10-04", "text": "소라2 나왔네"}])
        n = k["nodes"][0]
        self.assertEqual(n["first_seen"], n["last_seen"])

    def test_a_person_span_is_their_own_messages(self):
        k = self._knowledge()
        build_site.weigh_knowledge(k, self._messages())
        node = self._by_id(k)["person:갑"]
        self.assertEqual(("2025-10-01", "2026-08-01"),
                         (node["first_seen"], node["last_seen"]))
        self.assertNotIn("mentions", node, "사람 크기는 발언량으로 이미 정해져 있다")

    def test_a_topic_span_is_its_category_messages(self):
        k = self._knowledge()
        build_site.weigh_knowledge(k, self._messages())
        node = self._by_id(k)["topic:ai-tools"]
        self.assertEqual(("2025-11-05", "2026-08-01"),
                         (node["first_seen"], node["last_seen"]))

    def test_messages_without_a_date_do_not_make_an_empty_span(self):
        k = {"nodes": [{"id": "tool:x", "type": "tool", "label": "엑스",
                        "category": "ai-tools", "query": "엑스"}], "edges": []}
        build_site.weigh_knowledge(k, [{"id": "m1", "nickname": "갑", "text": "엑스"}])
        self.assertNotIn("first_seen", k["nodes"][0])
        self.assertEqual(1, k["nodes"][0]["mentions"], "언급은 셌지만 날짜는 없다")


class KnowledgeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (cls.messages, cls.images, cls.participants, cls.topics,
         cls.knowledge, cls.digest_prose) = _load()
        cls.data = build_site.build_data(
            cls.messages, cls.images, cls.participants, cls.topics,
            cls.knowledge, cls.digest_prose,
        )
        cls.cat_ids = {c["id"] for c in cls.topics["categories"]}

    def test_edge_endpoints_exist(self):
        """모든 엣지의 양끝 노드가 실제로 존재한다(참조 무결성)."""
        ids = {n["id"] for n in self.knowledge["nodes"]}
        for e in self.knowledge["edges"]:
            self.assertIn(e["source"], ids, e)
            self.assertIn(e["target"], ids, e)

    def test_every_node_has_valid_category(self):
        for n in self.knowledge["nodes"]:
            self.assertIn(n["category"], self.cat_ids, n)

    def test_every_node_type_is_declared(self):
        from scripts import ontology
        for n in self.knowledge["nodes"]:
            self.assertIn(n["type"], ontology.node_type_ids(), n["id"])

    def test_every_category_belongs_to_a_group(self):
        """분류를 새로 만들고 묶음에 넣는 것을 잊으면 여기서 걸린다.

        빠뜨리면 그 분류의 대화는 상위 묶음 계산에서 조용히 사라진다 —
        사람별 관심 분야가 그만큼 덜 나오는데 화면으로는 알 수 없다.
        일부러 안 넣은 것은 `ontology.PROVISIONAL_CATEGORIES` 에 적어 둔다.
        """
        from scripts import ontology
        missing = [c["id"] for c in self.topics["categories"]
                   if not ontology.group_of(c["id"])
                   and c["id"] not in ontology.PROVISIONAL_CATEGORIES]
        self.assertEqual([], missing, "묶음 없는 분류")

    def test_no_group_names_a_category_that_does_not_exist(self):
        from scripts import ontology
        ids = {c["id"] for c in self.topics["categories"]}
        for g in ontology.CATEGORY_GROUPS:
            for c in g["categories"]:
                self.assertIn(c, ids, "%s 가 없는 분류 '%s' 를 가리킵니다" % (g["id"], c))

    def test_every_edge_holds_its_shape(self):
        """관계마다 정의역·치역이 있고, 원장이 그것을 지킨다.

        예전에는 관계 **이름**만 검사했다. 그래서 뜻이 안 되는 엣지가 남았다 —
        실측 2026-08-12: `person -belongs-> topic` 두 건(belongs 는 앱·도구가 어느
        주제에 속하는지를 말하는 관계다).

        `ontology.apply` 가 발행할 때마다 고칠 수 있는 것은 고치므로, 여기서 걸리는
        것은 **뜻을 정할 수 없어 사람이 봐야 하는 것**이다.
        """
        from scripts import ontology
        type_of = {n["id"]: n["type"] for n in self.knowledge["nodes"]}
        bad = [
            "%s -%s-> %s" % (e["source"], e["type"], e["target"])
            for e in self.knowledge["edges"]
            if not ontology.is_valid(type_of.get(e["source"]), e["type"],
                                     type_of.get(e["target"]))
        ]
        self.assertEqual([], bad, "성립하지 않는 관계")

    def test_no_isolated_nodes(self):
        deg = {n["id"]: 0 for n in self.knowledge["nodes"]}
        for e in self.knowledge["edges"]:
            deg[e["source"]] += 1
            deg[e["target"]] += 1
        isolated = [k for k, v in deg.items() if v == 0]
        self.assertEqual(isolated, [], "고립 노드 존재")

    def test_app_makers_are_real_participants(self):
        nicks = {p["nickname"] for p in self.participants["participants"]}
        for n in self.knowledge["nodes"]:
            if n["type"] == "app" and n.get("maker"):
                self.assertIn(n["maker"], nicks, n["maker"])

    def test_person_nodes_match_participants(self):
        pnodes = {n["label"] for n in self.knowledge["nodes"] if n["type"] == "person"}
        nicks = {p["nickname"] for p in self.participants["participants"]}
        self.assertEqual(pnodes, nicks)

    def test_all_categories_have_digest_overview(self):
        for c in self.topics["categories"]:
            d = self.data["digests"].get(c["id"])
            self.assertIsNotNone(d, c["id"])
            self.assertTrue(d["overview"].strip(), c["id"])
            self.assertTrue(d["headline"].strip(), c["id"])

    def test_digest_derived_lists_consistent(self):
        # 카테고리 digest 메시지 합계 = 전체 메시지 수
        total = sum(d["message_count"] for d in self.data["digests"].values())
        self.assertEqual(total, len(self.messages))
        # 각 digest의 링크는 해당 카테고리 메시지에서만 왔는지(작성자 존재)
        nicks = {p["nickname"] for p in self.participants["participants"]}
        for d in self.data["digests"].values():
            for l in d["links"]:
                self.assertTrue(l["url"].startswith("http"))
                self.assertIn(l["nickname"], nicks)

    def test_data_js_contains_knowledge_and_digests(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp) / "site"
            build_site.write_site(self.data, site)
            text = (site / "data.js").read_text(encoding="utf-8")
            payload = text[len("window.ARCHIVE = "):].rstrip().rstrip(";")
            parsed = json.loads(payload)
            self.assertIn("knowledge", parsed)
            self.assertIn("digests", parsed)
            self.assertEqual(len(parsed["knowledge"]["nodes"]),
                             len(self.knowledge["nodes"]))
            self.assertEqual(len(parsed["digests"]), len(self.topics["categories"]))
            # graph.js 도 함께 배포되는지
            self.assertTrue((site / "graph.js").exists())


if __name__ == "__main__":
    unittest.main()
