# -*- coding: utf-8 -*-
"""build_site 데이터 조립 및 topics 커버리지 검증."""
import json
import sys
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
        img_status = {i["image_id"]: i for i in self.images}
        n_with_files = 0
        for m in self.data["messages"]:
            if m["kind"] != "image":
                continue
            self.assertIn("images", m)
            self.assertIn("image_pending", m)
            if m["images"]:
                n_with_files += 1
                self.assertFalse(m["image_pending"])
                for p in m["images"]:
                    self.assertTrue(p.startswith("assets/images/"))
                    self.assertTrue((ROOT / p).exists(), p)
            else:
                self.assertTrue(m["image_pending"])
        # 다운로드/부분 상태 레코드 수와 파일 보유 메시지 수 정합
        downloaded_records = [
            i for i in self.images if i.get("assets")
        ]
        self.assertEqual(n_with_files, len(downloaded_records))

    def test_downloaded_image_count_matches_files(self):
        total = sum(len(m.get("images", [])) for m in self.data["messages"])
        on_disk = len(list((ROOT / "assets" / "images").rglob("*.*")))
        self.assertEqual(total, on_disk)
        self.assertEqual(self.data["stats"]["totals"]["downloaded_images"], total)

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
        """write_site 가 만든 data.js 가 유효한 JSON을 담는지 검증."""
        build_site.write_site(self.data)
        text = (ROOT / "site" / "data.js").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("window.ARCHIVE = "))
        payload = text[len("window.ARCHIVE = "):].rstrip().rstrip(";")
        parsed = json.loads(payload)
        self.assertEqual(len(parsed["messages"]), len(self.messages))
        # 정적 파일·이미지도 복사되었는지
        for name in build_site.STATIC_FILES:
            self.assertTrue((ROOT / "site" / name).exists(), name)
        self.assertTrue((ROOT / "site" / "assets" / "images").exists())


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
        build_site.write_site(self.data)
        text = (ROOT / "site" / "data.js").read_text(encoding="utf-8")
        payload = text[len("window.ARCHIVE = "):].rstrip().rstrip(";")
        parsed = json.loads(payload)
        self.assertIn("knowledge", parsed)
        self.assertIn("digests", parsed)
        self.assertEqual(len(parsed["knowledge"]["nodes"]), len(self.knowledge["nodes"]))
        self.assertEqual(len(parsed["digests"]), len(self.topics["categories"]))
        # graph.js 도 함께 배포되는지
        self.assertTrue((ROOT / "site" / "graph.js").exists())


if __name__ == "__main__":
    unittest.main()
