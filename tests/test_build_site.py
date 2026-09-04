# -*- coding: utf-8 -*-
"""build_site 데이터 조립 및 topics 커버리지 검증."""
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts import build_site  # noqa: E402
from tests.realdata import needs_real_data  # noqa: E402


def _load():
    messages = build_site._read_jsonl(ROOT / "output" / "messages.jsonl")
    images = build_site._read_jsonl(ROOT / "output" / "images.jsonl")
    participants = build_site._read_json(ROOT / "output" / "participants.json")
    topics = build_site._read_json(ROOT / "output" / "topics.json")
    knowledge = build_site._read_json(ROOT / "output" / "knowledge.json")
    digest_prose = build_site._read_json(ROOT / "output" / "topic-digests.json")
    return messages, images, participants, topics, knowledge, digest_prose


@needs_real_data
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
    있었다 — 실측 2026-08-14: '소라2' 는 2025-10-04 하루에 1회, '슬랙' 은 2025-12-04
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


@needs_real_data
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
        실측 2026-08-14: `person -belongs-> topic` 두 건(belongs 는 앱·도구가 어느
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

    def test_edge_evidence_is_published_as_threads_not_messages(self):
        """원문을 발행하지 않으므로 message id 를 실으면 갈 곳 없는 링크가 된다."""
        tids = {t["id"] for t in self.data["threads"]}
        published = 0
        for e in self.data["knowledge"]["edges"]:
            self.assertNotIn("evidence", e, "원장의 message id 가 발행본에 새어 나갔다")
            for tid in e.get("evidence_threads") or []:
                self.assertIn(tid, tids, e)
            if e.get("evidence_threads"):
                published += 1
                self.assertTrue(e.get("by"), "어느 규칙이 찾았는지가 함께 가야 한다")
            else:
                self.assertNotIn("by", e, "근거 없는 엣지에 규칙 이름만 남으면 안 된다")
        self.assertGreater(published, 0, "근거가 하나도 발행되지 않았다")

    def test_publishing_does_not_touch_the_ledger(self):
        """원장 객체를 발행 때 바꾸면 그 뒤로 원장을 쓰는 코드가 발행본을 본다."""
        edges = [{"source": "a", "target": "b", "type": "uses",
                  "evidence": ["msg-1"], "by": "named-both"}]
        out = build_site.publish_edges(edges, {"msg-1": "t-1"})
        self.assertEqual(["msg-1"], edges[0]["evidence"])
        self.assertEqual(["t-1"], out[0]["evidence_threads"])
        self.assertNotIn("evidence", out[0])

    def test_two_messages_in_one_thread_become_one_thread(self):
        edges = [{"source": "a", "target": "b", "type": "uses",
                  "evidence": ["msg-1", "msg-2", "msg-9"], "by": "named-both"}]
        out = build_site.publish_edges(
            edges, {"msg-1": "t-1", "msg-2": "t-1", "msg-9": "t-2"})
        self.assertEqual(["t-1", "t-2"], out[0]["evidence_threads"])

    def test_a_thread_id_in_the_ledger_passes_through(self):
        """보고서에서 찾은 근거는 원장에서도 주제 id 다 — 두 이름이 한 메시지에
        없어 가리킬 한 줄이 없기 때문이다(`graph_evidence.from_reports`).
        """
        edges = [{"source": "a", "target": "b", "type": "uses",
                  "evidence": ["t-2"], "by": "named-both+report"}]
        out = build_site.publish_edges(edges, {"msg-1": "t-1", "msg-9": "t-2"})
        self.assertEqual(["t-2"], out[0]["evidence_threads"])
        self.assertEqual("named-both+report", out[0]["by"])

    def test_an_id_that_is_neither_is_dropped(self):
        edges = [{"source": "a", "target": "b", "type": "uses",
                  "evidence": ["msg-없음"], "by": "named-both"}]
        out = build_site.publish_edges(edges, {"msg-1": "t-1"})
        self.assertNotIn("evidence_threads", out[0])
        self.assertNotIn("by", out[0], "근거 없는 엣지에 규칙 이름만 남으면 안 된다")

    def test_a_node_talked_about_only_elsewhere_is_listed(self):
        """`belongs` 는 대화에서 찾은 주장이 아니라 노드의 분류 칸이다. 그 칸이
        어긋나면 근거 찾기가 그 엣지를 통째로 '근거 없음' 으로 낸다 — 근거를 못
        찾은 것이 아니라 물음이 어긋난 것이라, 분류를 다시 볼 목록으로 낸다.
        """
        nodes = [{"id": "tool:a", "type": "tool", "label": "바른도구",
                  "query": "바른도구", "category": "infra"}]
        hay = ["바른도구 좋아요", "바른도구 씁니다", "바른도구로 만들었어요"]
        cats = ["projects", "projects", "welfare-practice"]
        got = build_site.filed_elsewhere(nodes, hay, cats)
        self.assertEqual(1, len(got))
        self.assertEqual("tool:a", got[0][0]["id"])
        self.assertEqual(2, got[0][1]["projects"])

    def test_one_mention_in_its_own_category_is_enough_to_stay_quiet(self):
        nodes = [{"id": "tool:a", "type": "tool", "label": "바른도구",
                  "query": "바른도구", "category": "infra"}]
        hay = ["바른도구 좋아요", "바른도구 씁니다", "바른도구 이야기"]
        cats = ["projects", "projects", "infra"]
        self.assertEqual([], build_site.filed_elsewhere(nodes, hay, cats))

    def test_a_node_barely_mentioned_is_not_judged(self):
        """한두 번은 우연이다. 목록만 길어지면 진짜가 묻힌다."""
        nodes = [{"id": "tool:a", "type": "tool", "label": "바른도구",
                  "query": "바른도구", "category": "infra"}]
        self.assertEqual([], build_site.filed_elsewhere(
            nodes, ["바른도구 좋아요"], ["projects"]))

    def test_people_and_categories_are_not_filed_this_way(self):
        nodes = [{"id": "person:가나다", "type": "person", "label": "가나다",
                  "category": "projects"}]
        self.assertEqual([], build_site.filed_elsewhere(
            nodes, ["가나다 님 안녕하세요"] * 5, ["infra"] * 5))

    def test_a_generic_fragment_name_is_not_counted(self):
        """이름 규칙은 근거 찾기와 같은 것을 쓴다(ontology.findable_names).
        다른 잣대를 쓰면 언급이 많은 노드를 한쪽은 '안 나온다' 고 말한다.
        """
        nodes = [{"id": "tool:a", "type": "tool", "label": "상담 실시간 안내 도구",
                  "query": "상담", "category": "infra"}]
        self.assertEqual([], build_site.filed_elsewhere(
            nodes, ["오늘 상담 다녀왔습니다"] * 5, ["welfare-practice"] * 5))

    def test_every_digest_says_when_it_was_tidied(self):
        """정리 시점이 없으면 낡았는지 알 수 없다 — 화면도, 밤 갱신도.

        이 검사는 열두 편을 다시 쓴 뒤에 통과한다(`digest_prose --all`).
        """
        for c in self.topics["categories"]:
            as_of = self.data["digests"][c["id"]].get("as_of") or {}
            self.assertTrue(as_of.get("date"), "%s 에 as_of 가 없다" % c["id"])
            self.assertGreater(as_of.get("thread_count", 0), 0, c["id"])

    def test_a_big_category_is_split_into_sections(self):
        from scripts.topic_reports import DIGEST_SECTION_FROM
        for c in self.topics["categories"]:
            d = self.data["digests"][c["id"]]
            if len(d["threads"]) >= DIGEST_SECTION_FROM:
                self.assertTrue(d["sections"],
                                "%s 는 주제 %d개인데 절이 없다"
                                % (c["id"], len(d["threads"])))

    def test_facet_groups_cover_every_thread_exactly_once(self):
        """갈래별 개수의 합이 소속 주제 수와 다르면 어느 쪽이 틀렸는지 알 수 없다."""
        from scripts import ontology
        for cid, d in self.data["digests"].items():
            ids = [t for f in d["facets"] for t in f["thread_ids"]]
            if cid in ontology.CATEGORY_FACETS:
                self.assertEqual(sorted(ids), sorted(t["id"] for t in d["threads"]),
                                 "%s 갈래 합이 소속 주제와 다르다" % cid)
                self.assertEqual(len(ids), len(set(ids)), "%s 갈래가 겹친다" % cid)
                self.assertEqual(build_site.FACET_REST, d["facets"][-1]["label"],
                                 "'그 밖' 이 마지막이 아니다")
            else:
                self.assertEqual([], d["facets"], "%s 는 갈래 표가 없다" % cid)

    def test_the_group_table_goes_down_to_the_screen(self):
        """묶음 라벨을 화면에 하드코딩하면 온톨로지 원본이 둘이 된다."""
        from scripts import ontology
        self.assertEqual([g["label"] for g in ontology.CATEGORY_GROUPS],
                         [g["label"] for g in self.data["groups"]])
        listed = {c for g in self.data["groups"] for c in g["categories"]}
        self.assertEqual(self.cat_ids - ontology.PROVISIONAL_CATEGORIES, listed)

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


class FileShareExpiryTest(unittest.TestCase):
    """'수집 대기' 와 '만료' 를 가르는 경계.

    실측 2026-08-20: 서랍의 파일 카드 유효기간은 공유일 + 14일이고, **그 날짜에
    닿으면 이미 못 받는다** — 유효기간이 그날이던 파일 3개가 모두 저장에 실패했다.
    그래서 경계는 '지났으면' 이 아니라 '닿았으면' 이다.
    """

    TODAY = date(2026, 8, 20)

    def test_boundary_day_is_already_gone(self):
        # 08-06 공유 → 유효기간 08-20. 그날 이미 못 받는다.
        self.assertTrue(build_site.file_share_expired("2026-08-06", self.TODAY))

    def test_one_day_before_boundary_is_still_pending(self):
        # 08-07 공유 → 유효기간 08-21. 아직 받을 수 있다.
        self.assertFalse(build_site.file_share_expired("2026-08-07", self.TODAY))

    def test_recent_share_is_pending(self):
        self.assertFalse(build_site.file_share_expired("2026-08-19", self.TODAY))

    def test_long_past_share_is_gone(self):
        self.assertTrue(build_site.file_share_expired("2026-07-21", self.TODAY))

    def test_unknown_date_is_not_called_gone(self):
        """모르는 것을 '영영 없다' 고 단정하지 않는다 — 받을 수 있는 것을 포기하게 만든다."""
        for value in ("", None, "날짜아님", "2026-13-99"):
            self.assertFalse(build_site.file_share_expired(value, self.TODAY), value)

    def test_timestamp_form_is_accepted(self):
        self.assertTrue(build_site.file_share_expired("2026-07-21T10:00:00", self.TODAY))

    def test_media_payload_carries_the_flag(self):
        """build_media 는 필드를 골라 담는다 — 여기서 빠지면 화면이 구별할 수 없다."""
        shares = [
            {"id": "msg-1", "nickname": "가", "date": "2026-07-01", "time": "10:00",
             "kind": "file", "is_file_share": True, "text": "파일: 옛것.pdf",
             "file_expired": True},
            {"id": "msg-2", "nickname": "나", "date": "2026-08-19", "time": "11:00",
             "kind": "file", "is_file_share": True, "text": "파일: 새것.pdf",
             "file_expired": False},
        ]
        out = {m["id"]: m for m in build_site.build_media(shares)}
        self.assertTrue(out["msg-1"]["file_expired"])
        self.assertFalse(out["msg-2"]["file_expired"])


class VideoCountsAsThreadMaterialTests(unittest.TestCase):
    """스레드의 자료 수가 동영상을 세지 않으면 화면이 스스로 어긋난다.

    실측 2026-08-31 t-426: 동영상 한 편이 붙은 주제인데 `media_count` 가 0으로
    발행됐다. 자료가 0이라고 말하면서 아래에는 자료 상자를 여는 화면이 된다.
    """

    def test_video_message_raises_media_count(self):
        threads = [{"id": "t-1", "report": ""}]
        messages = [{"id": "msg-1", "thread_id": "t-1", "nickname": "김종원",
                     "date": "2026-08-31", "time": "09:16", "kind": "video",
                     "videos": ["assets/videos/2026-08/msg-1-01.mp4"],
                     "images": []}]
        out = build_site.enrich_threads(threads, messages)
        self.assertEqual(out[0]["media_count"], 1)


class ParticipantKindTallyTests(unittest.TestCase):
    """사람별 종류 합계는 남긴 글 수와 맞아야 한다."""

    @needs_real_data
    def test_kind_tally_matches_message_count(self):
        data = build_site.build_data(*_load())
        for p in data["stats"]["participants"]:
            with self.subTest(nickname=p["nickname"]):
                self.assertEqual(
                    p["text"] + p["image"] + p["video"] + p["file"],
                    p["message_count"],
                    "종류별 합이 글 수와 다릅니다 — 어느 종류가 빠졌는지 "
                    "화면에서는 보이지 않습니다",
                )


if __name__ == "__main__":
    unittest.main()
