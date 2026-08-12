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

import json
import pathlib
import tempfile
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


class NodeTagTests(unittest.TestCase):
    """관계망 노드와 태그가 같은 것을 가리킬 때 짝지어 둔다.

    '주요 앱' 의 '다룬 주제' 판정이 이름 글자로 되어 있어서, 이름이 서술형인
    결과물은 어느 태그·제목과도 안 맞아 다룬 주제가 0개였다 — 실측 2026-08-12 에
    앱 78개 중 38개, 그중 11개는 아무 주제도 없어 눌러도 빈 화면이었다.

    자동으로 잇지 않는다. 후보를 뽑아 보면 38개 전부에 후보가 나오지만
    '○○○ 깃허브 개인 사이트 → 깃허브' 처럼 일반 도구명이 섞여, 그것으로 이으면
    깃허브 이야기 전부가 그 사이트를 다룬 주제가 된다.
    """

    THREADS = [
        {"id": "t-1", "title": "채용 허브 만들었다", "tags": ["job-hub", "앱 제작"]},
        {"id": "t-2", "title": "깃허브 액션 이야기", "tags": ["깃허브"]},
        {"id": "t-3", "title": "마인드맵 협업", "tags": ["마인드맵"]},
    ]
    NODES = [
        {"id": "app:job-hub", "type": "app", "label": "job-hub 채용공고 허브",
         "category": "projects"},
        {"id": "app:jsh-site", "type": "app", "label": "누군가의 깃허브 개인 사이트",
         "category": "projects"},
        {"id": "app:mindmap", "type": "app", "label": "마인드맵", "category": "projects"},
        {"id": "tool:claude", "type": "tool", "label": "클로드", "category": "ai-tools"},
    ]

    def _table(self, raw):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "node_tags.json"
            p.write_text(json.dumps({"node_tags": raw}, ensure_ascii=False),
                         encoding="utf-8")
            return ontology.load_node_tags(p)

    def test_missing_table_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual({}, ontology.load_node_tags(pathlib.Path(d) / "없다.json"))

    def test_blank_rows_are_dropped(self):
        table = self._table({"app:x": ["", "  "], "  ": ["태그"], "app:y": ["태그"]})
        self.assertEqual({"app:y": ["태그"]}, table)

    def test_a_node_already_in_the_table_is_not_a_candidate(self):
        rows = ontology.node_tag_candidates(
            self.NODES, self.THREADS, {"app:job-hub": ["job-hub"]})
        self.assertNotIn("app:job-hub", [r[0] for r in rows])

    def test_a_node_whose_name_is_the_tag_is_not_a_candidate(self):
        # '마인드맵' 은 태그와 이름이 같아 예전 방법으로 이미 이어진다.
        rows = ontology.node_tag_candidates(self.NODES, self.THREADS, {})
        self.assertNotIn("app:mindmap", [r[0] for r in rows])

    def test_only_the_asked_types_are_offered(self):
        # '주요 앱' 목록이 app 노드만 쓰므로 도구는 후보로 내지 않는다.
        rows = ontology.node_tag_candidates(self.NODES, self.THREADS, {})
        self.assertEqual([], [r for r in rows if r[0].startswith("tool:")])

    def test_the_generic_candidate_is_offered_not_applied(self):
        """일반 도구명도 후보로는 보여준다 — 고르는 것은 사람이다.

        기계가 미리 걸러 두면 그 판단이 코드에 숨고, 사람은 무엇이 빠졌는지 모른다.
        `place_candidates` 가 '장애인복지관' 을 후보로 내놓는 것과 같은 이유다.
        """
        rows = ontology.node_tag_candidates(self.NODES, self.THREADS, {})
        cand = dict((nid, c) for nid, _, c in rows)
        self.assertIn("깃허브", cand.get("app:jsh-site", []))

    def test_a_node_settled_as_not_linkable_is_not_asked_again(self):
        """잇지 않기로 정한 것도 판단이 끝난 상태다.

        실측 2026-08-12: 남은 후보 13개를 하나씩 보고 전부 '잇지 않는다' 로 정했다 —
        후보가 죄다 일반 도구명·개념·기관 이름이었다. 그 결정을 적을 자리가 없으면
        로그가 매일 같은 13개를 다시 묻는다.
        """
        rows = ontology.node_tag_candidates(
            self.NODES, self.THREADS, {}, settled={"app:jsh-site"})
        self.assertNotIn("app:jsh-site", [r[0] for r in rows])

    def test_settled_and_linked_are_different_lists(self):
        # 둘을 한 목록에 섞으면 '이었다' 와 '안 잇기로 했다' 를 구분할 수 없다.
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "node_tags.json"
            p.write_text(json.dumps({"node_tags": {"app:a": ["가"]},
                                     "no_tag": ["app:b"]}, ensure_ascii=False),
                         encoding="utf-8")
            self.assertEqual({"app:a": ["가"]}, ontology.load_node_tags(p))
            self.assertEqual({"app:b"}, ontology.load_settled_nodes(p))

    def test_missing_no_tag_list_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(set(), ontology.load_settled_nodes(
                pathlib.Path(d) / "없다.json"))

    def test_the_shipped_table_does_not_settle_and_link_the_same_node(self):
        table, settled = ontology.load_node_tags(), ontology.load_settled_nodes()
        both = sorted(set(table) & settled)
        self.assertEqual([], both, "두 목록에 함께 있는 노드: %s" % both)

    def test_longer_candidates_come_first(self):
        threads = [{"id": "t-1", "tags": ["근태관리", "NFC 근태 관리"]}]
        nodes = [{"id": "app:nfc", "type": "app", "label": "NFC 근태 관리 앱",
                  "category": "projects"}]
        rows = ontology.node_tag_candidates(nodes, threads, {})
        self.assertEqual(["NFC 근태 관리", "근태관리"], rows[0][2],
                         "긴 쪽이 그 물건의 이름일 확률이 높다")


class DigestNodeLinkTests(unittest.TestCase):
    """표로 이은 주제는 원문에 이름이 없어도 '다룬 주제' 가 된다."""

    def _digests(self, node_tags):
        from scripts import build_site
        threads = [
            {"id": "t-1", "category": "projects", "title": "토론 도우미를 만들었다",
             "summary": "요지", "report": "본문", "message_ids": ["m1"], "count": 1,
             "tags": ["토론 앱"]},
            {"id": "t-2", "category": "projects", "title": "딴 이야기",
             "summary": "요지", "report": "본문", "message_ids": ["m2"], "count": 1,
             "tags": ["파이어베이스"]},
        ]
        topics = {"categories": [{"id": "projects", "label": "프로젝트"}],
                  "threads": [{"id": "t-1", "category": "projects", "message_ids": ["m1"]},
                              {"id": "t-2", "category": "projects", "message_ids": ["m2"]}]}
        # 원문에 'AI 토론 앱' 이라는 말은 한 번도 안 나온다.
        msgs = [{"id": "m1", "nickname": "갑", "date": "2026-08-12",
                 "category": "projects", "text": "이거 써보세요"},
                {"id": "m2", "nickname": "갑", "date": "2026-08-12",
                 "category": "projects", "text": "파이어베이스 좋네요"}]
        knowledge = {"nodes": [{"id": "app:debate", "type": "app", "label": "AI 토론 앱",
                                "category": "projects", "query": "토론"}]}
        out = build_site.build_digests(msgs, threads, topics, knowledge,
                                       {"digests": {}}, node_tags)
        return out["projects"]["apps"][0]

    def test_without_the_table_the_node_finds_no_subject(self):
        app = self._digests({})
        self.assertEqual([], app["subject_ids"],
                         "서술형 이름은 글자로 이어지지 않는다 — 이것이 실측 38개다")

    def test_with_the_table_the_tagged_thread_is_the_subject(self):
        app = self._digests({"app:debate": ["토론 앱"]})
        self.assertEqual(["t-1"], app["subject_ids"])
        self.assertNotIn("t-2", app["subject_ids"], "남의 주제를 끌어오지 않는다")

    def test_the_table_wins_even_if_the_name_is_nowhere_in_the_text(self):
        # 원문에 이름이 한 번도 없어 threads_matching 이 못 찾는 노드도 살아난다.
        app = self._digests({"app:debate": ["토론 앱"]})
        self.assertIn("t-1", app["thread_ids"])

    def test_spelling_differences_are_forgiven(self):
        app = self._digests({"app:debate": ["토론앱"]})
        self.assertEqual(["t-1"], app["subject_ids"], "공백 차이로 갈리면 표가 함정이 된다")


class CategoryGroupTests(unittest.TestCase):
    """분류 12개의 상위 묶음. 분류가 평평해서 얇은 표본이 묻혔다."""

    def test_no_category_belongs_to_two_groups(self):
        seen: dict[str, str] = {}
        for g in ontology.CATEGORY_GROUPS:
            for c in g["categories"]:
                self.assertNotIn(c, seen,
                                 "'%s' 가 %s 와 %s 두 묶음에 있습니다"
                                 % (c, seen.get(c), g["id"]))
                seen[c] = g["id"]

    def test_every_group_has_a_label_and_members(self):
        for g in ontology.CATEGORY_GROUPS:
            self.assertTrue(g["label"].strip(), g["id"])
            self.assertTrue(g["categories"], g["id"])
            self.assertEqual(g["label"], ontology.group_label(g["id"]))

    def test_chat_is_deliberately_ungrouped(self):
        """미분류의 임시 자리라서 '아직 안 정해졌다'는 뜻이다.

        `build_site.sync_person_nodes` 가 chat 을 대표 분류로 쓰지 않는 것과 같은
        이유고, 잡담이 누군가의 '관심 분야'로 올라오면 화면이 우스워진다.
        """
        self.assertIsNone(ontology.group_of("chat"))
        self.assertIn("chat", ontology.PROVISIONAL_CATEGORIES)

    def test_an_unknown_category_has_no_group(self):
        self.assertIsNone(ontology.group_of("does-not-exist"))
        self.assertIsNone(ontology.group_of(None))

    def test_group_label_falls_back_to_the_id(self):
        # 라벨을 못 찾아도 빈칸을 내지 않는다 — 화면에 빈 칩이 서는 것보다 낫다.
        self.assertEqual("group:없음", ontology.group_label("group:없음"))


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
