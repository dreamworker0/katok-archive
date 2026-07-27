# -*- coding: utf-8 -*-
"""주제 분류의 검증 계약.

LLM 출력은 믿을 수 없다. 프롬프트는 부탁이고 검증이 보장이다. 실측 2026-07-27 에
두 가지가 실제로 났다:

  · `category` 없는 노드를 만들어 발행본 생성이 KeyError 로 깨졌다
    (build_site.build_digests 가 app 노드의 n["category"] 를 요구한다)
  · `app:urimal`(우리말 윤문)이 이미 있는데 `app:우리말`을 새로 만들었다

그리고 가장 무서운 것은 조용한 실패다 — 메시지가 스레드에서 사라지거나 한 메시지가
두 스레드에 들어가면 화면에서 바로 눈에 띄지 않는다. 그래서 불변식을 여기서 못박는다.
"""
from __future__ import annotations

import unittest

from scripts.classify_unsorted import merge_graph, norm_label, validate

CATS = {"projects", "ai-tools", "chat"}
IDS = {"msg-001", "msg-002", "msg-003"}


def graph_skeleton() -> dict:
    return {
        "node_types": [{"id": "topic"}, {"id": "app"}, {"id": "tool"},
                       {"id": "person"}],
        "edge_types": [{"id": "made"}, {"id": "uses"}, {"id": "belongs"},
                       {"id": "interested"}],
        "nodes": [
            {"id": "topic:projects", "type": "topic", "label": "프로젝트",
             "category": "projects"},
            {"id": "app:urimal", "type": "app", "label": "우리말 윤문",
             "category": "projects"},
            {"id": "person:김종원", "type": "person", "label": "김종원",
             "category": "projects"},
        ],
        "edges": [],
    }


class InvariantTests(unittest.TestCase):
    """모든 메시지는 정확히 하나의 스레드에 속한다."""

    def ok_thread(self, ids, cat="projects"):
        return {"category": cat, "title": "제목", "summary": "요지",
                "message_ids": list(ids)}

    def test_full_coverage_passes(self):
        data = {"threads": [self.ok_thread(["msg-001", "msg-002"]),
                            self.ok_thread(["msg-003"], "chat")]}
        out = validate(data, IDS, CATS)
        self.assertIsNotNone(out)
        self.assertEqual(2, len(out))

    def test_missing_message_is_rejected(self):
        # 빠뜨리면 그 메시지는 어느 스레드에도 속하지 않는다 — 조용히 사라진다.
        data = {"threads": [self.ok_thread(["msg-001", "msg-002"])]}
        self.assertIsNone(validate(data, IDS, CATS))

    def test_duplicate_message_is_rejected(self):
        data = {"threads": [self.ok_thread(["msg-001", "msg-002", "msg-003"]),
                            self.ok_thread(["msg-003"], "chat")]}
        self.assertIsNone(validate(data, IDS, CATS))

    def test_invented_message_id_is_rejected(self):
        data = {"threads": [self.ok_thread(
            ["msg-001", "msg-002", "msg-003", "msg-999"])]}
        self.assertIsNone(validate(data, IDS, CATS))

    def test_unknown_category_is_rejected(self):
        data = {"threads": [self.ok_thread(list(IDS), "does-not-exist")]}
        self.assertIsNone(validate(data, IDS, CATS))

    def test_empty_or_malformed_is_rejected(self):
        for data in ({"threads": []}, {"threads": "nope"}, {},
                     {"threads": [{"category": "chat", "message_ids": []}]},
                     {"threads": [{"category": "chat",
                                   "message_ids": list(IDS)}]}):
            with self.subTest(data=data):
                self.assertIsNone(validate(data, IDS, CATS))


class GraphMergeTests(unittest.TestCase):
    def test_new_node_gets_category_and_query(self):
        # category 가 없으면 발행본 생성이 KeyError 로 깨진다.
        k = graph_skeleton()
        n, e = merge_graph(k, {"nodes": [
            {"id": "tool:claude-p", "type": "tool", "category": "ai-tools",
             "label": "Claude -p"}
        ]}, CATS)
        self.assertEqual((1, 0), (n, e))
        added = [x for x in k["nodes"] if x["id"] == "tool:claude-p"][0]
        self.assertEqual("ai-tools", added["category"])
        self.assertIn("query", added)

    def test_node_without_category_is_dropped(self):
        k = graph_skeleton()
        n, _ = merge_graph(k, {"nodes": [
            {"id": "tool:claude-p", "type": "tool", "label": "Claude -p"}
        ]}, CATS)
        self.assertEqual(0, n)

    def test_non_slug_id_is_dropped(self):
        # 'tool:Claude -p' 처럼 공백·대문자가 섞인 id 가 실제로 나왔다.
        k = graph_skeleton()
        for bad in ("tool:Claude -p", "app:우리말", "tool:", "nope:x"):
            with self.subTest(bad=bad):
                n, _ = merge_graph(k, {"nodes": [
                    {"id": bad, "type": "tool", "category": "ai-tools",
                     "label": "x"}
                ]}, CATS)
                self.assertEqual(0, n)

    def test_duplicate_label_is_dropped(self):
        # 'app:urimal' = '우리말 윤문' 이 이미 있다. 다른 id 로 또 만들면 안 된다.
        k = graph_skeleton()
        n, _ = merge_graph(k, {"nodes": [
            {"id": "app:urimal-tool", "type": "app", "category": "projects",
             "label": "우리말윤문"}
        ]}, CATS)
        self.assertEqual(0, n)

    def test_person_nodes_are_never_created(self):
        # 참여자는 결정론적 파이프라인이 관리한다. LLM 이 실명을 만들면 안 된다.
        k = graph_skeleton()
        n, _ = merge_graph(k, {"nodes": [
            {"id": "person:없는사람", "type": "person", "category": "chat",
             "label": "없는사람"}
        ]}, CATS)
        self.assertEqual(0, n)

    def test_topic_nodes_are_never_created(self):
        k = graph_skeleton()
        n, _ = merge_graph(k, {"nodes": [
            {"id": "topic:invented", "type": "topic", "category": "chat",
             "label": "새 주제"}
        ]}, CATS)
        self.assertEqual(0, n)

    def test_edge_to_missing_node_is_dropped(self):
        # 없는 노드를 가리키는 엣지는 화면에서 그려지지 않거나 그리다 깨진다.
        k = graph_skeleton()
        _, e = merge_graph(k, {"edges": [
            {"source": "person:김종원", "target": "tool:does-not-exist",
             "type": "uses"}
        ]}, CATS)
        self.assertEqual(0, e)

    def test_edge_between_existing_nodes_is_added(self):
        k = graph_skeleton()
        _, e = merge_graph(k, {"edges": [
            {"source": "person:김종원", "target": "app:urimal", "type": "made"}
        ]}, CATS)
        self.assertEqual(1, e)

    def test_unknown_edge_type_is_dropped(self):
        k = graph_skeleton()
        _, e = merge_graph(k, {"edges": [
            {"source": "person:김종원", "target": "app:urimal", "type": "떠올림"}
        ]}, CATS)
        self.assertEqual(0, e)

    def test_existing_edge_is_not_duplicated(self):
        k = graph_skeleton()
        k["edges"].append({"source": "person:김종원", "target": "app:urimal",
                           "type": "made", "weight": 5})
        _, e = merge_graph(k, {"edges": [
            {"source": "person:김종원", "target": "app:urimal", "type": "made"}
        ]}, CATS)
        self.assertEqual(0, e)
        self.assertEqual(1, len(k["edges"]))

    def test_existing_nodes_are_never_modified(self):
        # 덧붙이기만 한다. 그날 대화만 본 판단으로 과거를 고치면 안 된다.
        k = graph_skeleton()
        before = [dict(n) for n in k["nodes"]]
        merge_graph(k, {"nodes": [
            {"id": "app:urimal", "type": "app", "category": "chat",
             "label": "딴 이름"}
        ]}, CATS)
        self.assertEqual(before, k["nodes"])


class NormalizeTests(unittest.TestCase):
    def test_label_normalization_catches_spacing_variants(self):
        self.assertEqual(norm_label("우리말 윤문"), norm_label("우리말윤문"))
        self.assertEqual(norm_label("Claude -p"), norm_label("claude-p"))
        self.assertNotEqual(norm_label("우리말"), norm_label("우리말윤문"))


if __name__ == "__main__":
    unittest.main()
