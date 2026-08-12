# -*- coding: utf-8 -*-
"""관계망 스키마의 계약.

예전 검증은 '엣지 종류가 목록에 있나 · 양 끝 노드가 있나' 두 가지뿐이라 뜻이 안
되는 엣지가 원장에 남았다 — 실측 2026-08-12 에 `person -belongs-> topic` 두 건
(belongs 는 앱·도구가 어느 주제에 속하는지를 말하는 관계다).

반대로 넉넉해야 할 곳도 있다. `person -interested-> tool` 32건은 '이 도구에 관심을
보였다' 로 `uses` 와 다른 말이고, `tool -uses-> tool` 은 스킬이 클로드 코드를 쓴다는
뜻이다. 좁게 잡으면 LLM 이 알아낸 것을 버린다. 그 두 방향을 여기서 못박는다.
"""
from __future__ import annotations

import unittest

from scripts import ontology


class ShapeTests(unittest.TestCase):
    def test_the_shapes_the_room_actually_produced_are_valid(self):
        """실제 원장에 있던 조합(2026-08-12). 이것을 막으면 데이터를 버린다."""
        for src, etype, dst in [
            ("person", "uses", "tool"), ("person", "interested", "topic"),
            ("person", "made", "app"), ("app", "uses", "tool"),
            ("tool", "belongs", "topic"), ("app", "belongs", "topic"),
            ("person", "interested", "tool"), ("person", "uses", "app"),
            ("person", "interested", "app"), ("tool", "uses", "tool"),
            ("person", "made", "tool"),
        ]:
            with self.subTest(shape=(src, etype, dst)):
                self.assertTrue(ontology.is_valid(src, etype, dst))

    def test_a_person_does_not_belong_to_a_category(self):
        # 실측 2026-08-12: 이 모양 두 건이 검증을 통과해 원장에 있었다.
        self.assertFalse(ontology.is_valid("person", "belongs", "topic"))

    def test_a_reversed_edge_is_rejected(self):
        self.assertFalse(ontology.is_valid("topic", "belongs", "app"))
        self.assertFalse(ontology.is_valid("app", "made", "person"))

    def test_an_unknown_relation_is_rejected(self):
        self.assertFalse(ontology.is_valid("person", "created", "app"))
        self.assertFalse(ontology.is_valid("person", "", "app"))

    def test_a_topic_is_never_a_source(self):
        # 토픽은 카테고리 클러스터의 중심이고, 무엇을 하지는 않는다.
        for etype in ontology.edge_type_ids():
            with self.subTest(etype=etype):
                self.assertFalse(ontology.is_valid("topic", etype, "tool"))


class RepairTests(unittest.TestCase):
    def test_a_shape_with_one_possible_meaning_is_fixed(self):
        # person → topic 에 성립하는 관계는 interested 하나다.
        self.assertEqual("interested",
                         ontology.repair("person", "belongs", "topic"))

    def test_a_shape_with_several_meanings_is_left_alone(self):
        """person → tool 은 made·uses·interested 가 다 성립한다.

        고르는 것이 곧 추측이다. '만들었다' 를 '관심을 보였다' 로 바꿔 놓으면
        틀린 것이 조용히 남는다.
        """
        self.assertIsNone(ontology.repair("person", "belongs", "tool"))

    def test_an_unknown_relation_is_not_guessed(self):
        # 무슨 뜻으로 쓴 것인지 모르는 이름은 고치지 않는다.
        self.assertIsNone(ontology.repair("person", "created", "topic"))

    def test_a_valid_shape_needs_no_repair(self):
        self.assertEqual([], [t for t in ontology.fits("app", "person")])
        self.assertIn("belongs", ontology.fits("app", "topic"))


def ledger() -> dict:
    return {
        "nodes": [
            {"id": "topic:members", "type": "topic", "category": "members"},
            {"id": "person:갑", "type": "person", "category": "members"},
            {"id": "person:을", "type": "person", "category": "members"},
            {"id": "tool:클로드", "type": "tool", "category": "ai-tools"},
        ],
        "edges": [],
    }


class ApplyTests(unittest.TestCase):
    def test_types_are_written_from_code(self):
        k = {"nodes": [], "edges": [], "node_types": [{"id": "옛것"}]}
        report = ontology.apply(k)
        self.assertTrue(report["types_changed"])
        self.assertEqual([t["id"] for t in k["node_types"]],
                         [t["id"] for t in ontology.NODE_TYPES])
        self.assertIn("domain", k["edge_types"][0])
        # 두 번째 실행은 바꿀 것이 없다
        self.assertFalse(ontology.apply(k)["types_changed"])

    def test_a_wrong_edge_is_repaired_in_place(self):
        k = ledger()
        k["edges"] = [{"source": "person:갑", "target": "topic:members",
                       "type": "belongs", "weight": 1}]
        report = ontology.apply(k)
        self.assertEqual([("person:갑", "topic:members", "belongs", "interested")],
                         report["repaired"])
        self.assertEqual("interested", k["edges"][0]["type"])
        self.assertEqual(1, k["edges"][0]["weight"], "다른 필드는 건드리지 않는다")

    def test_a_repair_that_would_duplicate_drops_the_wrong_edge(self):
        """같은 뜻의 엣지가 이미 있으면 어긋난 쪽을 지운다.

        사람 노드는 `build_site.sync_person_nodes` 가 person→topic 을 interested 로
        만들어 두므로 이 길로 오는 것이 흔하다. 고쳐 놓으면 같은 엣지가 둘이 된다.
        """
        k = ledger()
        k["edges"] = [
            {"source": "person:갑", "target": "topic:members", "type": "interested"},
            {"source": "person:갑", "target": "topic:members", "type": "belongs"},
        ]
        report = ontology.apply(k)
        self.assertEqual([], report["repaired"])
        self.assertEqual(1, len(report["dropped"]))
        self.assertEqual(1, len(k["edges"]))
        self.assertEqual("interested", k["edges"][0]["type"])

    def test_an_unfixable_edge_stays_and_is_reported(self):
        """고칠 수 없는 것은 지우지 않고 알린다.

        누적된 원장이다. 그날 판단으로 과거를 지우면 되돌릴 수 없고, 무엇이
        틀렸는지도 사라진다 — `merge_graph` 가 옛 노드를 안 지우는 것과 같은 이유다.
        """
        k = ledger()
        k["edges"] = [{"source": "person:갑", "target": "person:을", "type": "uses"}]
        report = ontology.apply(k)
        self.assertEqual([("person:갑", "uses", "person:을")], report["invalid"])
        self.assertEqual(1, len(k["edges"]), "지우지 않는다")

    def test_a_dangling_edge_is_not_judged_here(self):
        # 없는 노드를 가리키는 엣지는 종류를 알 수 없어 고칠 수도 없다.
        # test_build_site.test_edges_reference_existing_nodes 의 몫이다.
        k = ledger()
        k["edges"] = [{"source": "person:갑", "target": "app:없는것",
                       "type": "belongs"}]
        report = ontology.apply(k)
        self.assertEqual(([], [], []),
                         (report["repaired"], report["dropped"], report["invalid"]))

    def test_running_twice_changes_nothing_more(self):
        k = ledger()
        k["edges"] = [{"source": "person:갑", "target": "topic:members",
                       "type": "belongs"}]
        ontology.apply(k)
        before = [dict(e) for e in k["edges"]]
        second = ontology.apply(k)
        self.assertEqual(before, k["edges"])
        self.assertEqual(([], [], []),
                         (second["repaired"], second["dropped"], second["invalid"]))


class PromptRuleTests(unittest.TestCase):
    """프롬프트가 규칙을 옮겨 적지 않는다.

    보고서 규칙이 두 곳에 따로 적혀 있어서 사고가 났던 것과 같은 이유다
    (docs/REPORT-RULES.md). 관계 표가 바뀌면 프롬프트도 같이 바뀌어야 한다.
    """

    def test_every_relation_and_its_shape_is_in_the_prompt(self):
        rules = ontology.prompt_rules()
        for e in ontology.EDGE_TYPES:
            self.assertIn(e["id"], rules)
            for t in e["domain"] + e["range"]:
                self.assertIn(t, rules)

    def test_the_classify_prompt_reads_the_rules(self):
        from scripts import classify_unsorted as cu
        prompt = cu.build_prompt(
            [{"id": "msg-001", "nickname": "갑", "text": "안녕",
              "date": "2026-08-12", "time": "10:00"}],
            [{"id": "chat", "label": "일상"}], [], [])
        self.assertIn(ontology.prompt_rules(), prompt)
