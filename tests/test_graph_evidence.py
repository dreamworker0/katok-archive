# -*- coding: utf-8 -*-
"""관계망 근거 — 틀린 근거는 없는 근거보다 나쁘다.

이 작업의 실패 방식은 넷이다.

  · 모양에 안 맞는 규칙으로 찾는다 — 사람의 말을 분류의 근거로 세는 식
  · 일반어 이름('상담'·'게임')이 아무 말이나 근거로 만든다
  · 근거를 못 찾았는데 빈 배열을 남긴다 — 화면이 '근거가 있다' 고 믿는다
  · 근거를 다 담아 원장이 근거 목록이 된다

여기 나오는 이름은 전부 가짜다. 저장소는 공개다.
"""
from __future__ import annotations

import os
import json
import tempfile
import unittest
from pathlib import Path

from scripts import graph_evidence as ge

NODES = [
    {"id": "topic:projects", "type": "topic", "label": "프로젝트", "category": "projects"},
    {"id": "person:가나다", "type": "person", "label": "가나다"},
    {"id": "person:라마바", "type": "person", "label": "라마바"},
    {"id": "app:sarangi", "type": "app", "label": "사랑이 앱", "query": "사랑이"},
    {"id": "app:vague", "type": "app", "label": "이야기 나누는 앱", "query": "이야기 나누는"},
    {"id": "tool:short", "type": "tool", "label": "상담", "query": "상담"},
    {"id": "tool:bareun", "type": "tool", "label": "바른도구", "query": "바른도구"},
]
BY_ID = {n["id"]: n for n in NODES}

# (id, 날짜, 글, 말한 이, 주제, 분류)
ROWS = [
    ("msg-1", "2026-01-01", "사랑이 앱을 만들었습니다", "가나다", "t-1", "projects"),
    ("msg-2", "2026-02-01", "사랑이 앱에 바른도구를 붙였어요 " + "가" * 60,
     "가나다", "t-1", "projects"),
    ("msg-3", "2026-03-01", "사랑이 앱 잘 씁니다", "라마바", "t-1", "projects"),
    ("msg-4", "2026-04-01", "오늘 상담 다녀왔습니다", "라마바", "t-9", "chat"),
    ("msg-5", "2026-05-01", "상담 도구가 좋네요", "라마바", "t-2", "projects"),
    ("msg-6", "2026-06-01", "잡담입니다", "가나다", "t-9", "chat"),
]

# t-1 은 '사랑이 앱' 을 다룬 주제, t-2 는 '상담' 도구를 다룬 주제.
THREADS = [
    {"id": "t-1", "title": "사랑이 앱 만들기", "tags": ["사랑이 앱"]},
    {"id": "t-2", "title": "상담 도구 후기", "tags": ["상담"]},
    {"id": "t-9", "title": "잡담", "tags": []},
]


def ctx(node_tags=None) -> dict:
    return {
        "ids": [r[0] for r in ROWS],
        "hay": [r[2].lower() for r in ROWS],
        "dates": [r[1] for r in ROWS],
        "lens": [len(r[2]) for r in ROWS],
        "who": [r[3] for r in ROWS],
        "thread": [r[4] for r in ROWS],
        "cat": [r[5] for r in ROWS],
        "threads": [dict(t) for t in THREADS],
        "node_tags": node_tags or {},
    }


def evidence(source: str, etype: str, target: str, **kw):
    edge = {"source": source, "type": etype, "target": target}
    return ge.find_evidence(edge, BY_ID, ctx(**kw), {})


class RuleTest(unittest.TestCase):
    def test_a_person_and_a_category_is_what_that_person_said_there(self):
        ids, rule = evidence("person:가나다", "interested", "topic:projects")
        self.assertEqual("spoke-in", rule)
        self.assertEqual(["msg-1", "msg-2"], ids, "잡담(msg-6)은 그 분류가 아니다")

    def test_a_person_and_a_thing_is_that_persons_own_words(self):
        ids, rule = evidence("person:가나다", "made", "app:sarangi")
        self.assertEqual("named-it", rule)
        self.assertEqual(["msg-1", "msg-2"], ids, "라마바의 말(msg-3)은 근거가 아니다")

    def test_a_thing_and_a_category_is_that_categorys_words(self):
        ids, rule = evidence("app:sarangi", "belongs", "topic:projects")
        self.assertEqual("named-in", rule)
        self.assertEqual(["msg-1", "msg-2", "msg-3"], ids)

    def test_two_things_must_meet_in_one_message(self):
        ids, rule = evidence("app:sarangi", "uses", "tool:bareun")
        self.assertEqual("named-both", rule)
        self.assertEqual(["msg-2"], ids)

    def test_nothing_found_gives_the_rule_name_and_no_ids(self):
        ids, rule = evidence("person:라마바", "made", "tool:bareun")
        self.assertEqual(([], "named-it"), (ids, rule))


class ShortNameTest(unittest.TestCase):
    """일반어 이름은 그 주제가 그 노드와 이어질 때만 근거가 된다.

    실측 2026-09-04: `query` 가 두 글자인 노드가 17개다(`상담`·`게임`·`토론`·
    `엑셀`). 통째로 막으면 `슬랙`(30회)·`노션` 같은 진짜 이름까지 잃는다.
    """

    def test_a_generic_name_needs_the_thread_to_agree(self):
        ids, _ = evidence("tool:short", "belongs", "topic:projects")
        self.assertEqual(["msg-5"], ids,
                         "'상담' 이 든 잡담(msg-4)은 근거가 아니다 — 그 주제가 상담 도구를 "
                         "다루지 않는다")

    def test_a_long_name_needs_no_backing(self):
        got = ge.mentions_of(BY_ID["app:sarangi"], ctx())
        self.assertEqual([0, 1, 2], got)

    def test_a_generic_name_with_no_linked_thread_finds_nothing(self):
        thin = ctx()
        thin["threads"] = [{"id": t["id"], "title": "무제", "tags": []}
                           for t in THREADS]
        self.assertEqual([], ge.mentions_of(BY_ID["tool:short"], thin))


class TaggedRouteTest(unittest.TestCase):
    """이름이 서술형인 앱이 제 근거를 찾는 유일한 길."""

    def test_the_table_finds_what_the_letters_cannot(self):
        ids, rule = evidence("person:가나다", "made", "app:vague")
        self.assertEqual(([], "named-it"), (ids, rule), "이름으로는 못 찾는다")
        ids, rule = evidence("person:가나다", "made", "app:vague",
                             node_tags={"app:vague": ["사랑이 앱"]})
        self.assertEqual("named-it+tagged", rule, "어느 길로 살아났는지 남는다")
        self.assertEqual(["msg-1", "msg-2"], ids)

    def test_a_tagged_thread_alone_is_not_evidence_that_two_things_meet(self):
        """`app uses tool` 은 도착 도구가 그 말에 나와야 근거다.

        처음 판은 규칙이 비었을 때만 태그 길로 물러섰다. 그래서 출발 앱의 주제
        메시지가 **도착 도구가 안 나와도** 근거가 됐다 — 관계를 보여 주지 않는
        근거이고, 그건 없는 근거보다 나쁘다.
        """
        table = {"app:vague": ["사랑이 앱"]}
        # t-1 의 말 가운데 '바른도구' 가 나오는 것은 msg-2 하나뿐이다.
        ids, rule = evidence("app:vague", "uses", "tool:bareun", node_tags=table)
        self.assertEqual(["msg-2"], ids)
        self.assertEqual("named-both+tagged", rule)
        # 그 주제에 아예 나오지 않는 도구는 근거가 없다.
        nowhere = dict(BY_ID)
        ids, _ = ge.find_evidence(
            {"source": "app:vague", "type": "uses", "target": "tool:short"},
            nowhere, ctx(node_tags=table), {})
        self.assertEqual([], ids, "'상담' 은 t-1 의 말에 안 나온다")


class PickTest(unittest.TestCase):
    def test_earliest_latest_and_longest(self):
        got = ge.pick([0, 1, 2, 3, 4, 5], ctx())
        self.assertEqual(3, len(got))
        self.assertEqual(["msg-1", "msg-2", "msg-6"],
                         [ROWS[i][0] for i in got],
                         "처음 · 가장 긴 것 · 마지막")

    def test_the_cap_is_one_constant(self):
        self.assertEqual(ge.EVIDENCE_MAX, len(ge.pick([0, 1, 2, 3, 4, 5], ctx())))

    def test_fewer_than_the_cap_is_not_padded(self):
        self.assertEqual([0], ge.pick([0], ctx()))
        self.assertEqual(2, len(ge.pick([0, 5], ctx())))

    def test_empty_stays_empty(self):
        self.assertEqual([], ge.pick([], ctx()))


class ApplyTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.path = self.dir / "knowledge.json"
        self._saved = (ge.KNOWLEDGE, ge.OUT)
        ge.KNOWLEDGE, ge.OUT = self.path, self.dir
        from scripts import tag_surgery as ts
        self._ts_out, ts.OUT = ts.OUT, self.dir
        self.ts = ts

    def tearDown(self):
        ge.KNOWLEDGE, ge.OUT = self._saved
        self.ts.OUT = self._ts_out

    def knowledge(self):
        return {"nodes": [dict(n) for n in NODES], "edges": [
            {"source": "person:가나다", "target": "app:sarangi", "type": "made",
             "weight": 3},
            {"source": "person:라마바", "target": "tool:bareun", "type": "made"},
        ]}

    def run_once(self, k):
        # 원장이 디스크에 있어야 백업이 뜬다 — 실제 실행과 같은 순서로 둔다.
        self.path.write_text(json.dumps(k, ensure_ascii=False), encoding="utf-8")
        rows = ge.survey(k, ctx())["rows"]
        return ge.apply_evidence(k, rows, "20260904")

    def test_evidence_is_added_and_the_rest_untouched(self):
        k = self.knowledge()
        changed, _ = self.run_once(k)
        self.assertEqual(1, changed)
        made, none = k["edges"]
        self.assertEqual(["msg-1", "msg-2"], made["evidence"])
        self.assertEqual("named-it", made["by"])
        self.assertEqual(3, made["weight"], "다른 값은 손대지 않는다")

    def test_an_edge_with_no_evidence_has_no_such_key(self):
        """빈 배열을 넣으면 화면이 '근거가 있다' 고 믿고 빈 목록을 그린다."""
        k = self.knowledge()
        self.run_once(k)
        self.assertNotIn("evidence", k["edges"][1])
        self.assertNotIn("by", k["edges"][1])

    def test_running_twice_changes_nothing_more(self):
        k = self.knowledge()
        self.run_once(k)
        first = json.dumps(k, ensure_ascii=False, sort_keys=True)
        changed, _ = self.run_once(k)
        self.assertEqual(0, changed)
        self.assertEqual(first, json.dumps(k, ensure_ascii=False, sort_keys=True))

    def test_a_stale_evidence_key_is_removed(self):
        """근거가 사라졌으면 옛 근거도 지운다 — 남으면 원장이 거짓말을 한다."""
        k = self.knowledge()
        k["edges"][1]["evidence"] = ["msg-9"]
        k["edges"][1]["by"] = "named-it"
        changed, _ = self.run_once(k)
        self.assertEqual(2, changed)
        self.assertNotIn("evidence", k["edges"][1])

    def test_the_backup_holds_the_ledger_as_it_was(self):
        k = self.knowledge()
        _, backup = self.run_once(k)
        saved = json.loads((backup / "knowledge.json").read_text(encoding="utf-8"))
        self.assertNotIn("evidence", saved["edges"][0])

    def test_nothing_changed_means_the_ledger_is_not_rewritten(self):
        """내용이 같은데 다시 쓰면 파일 시각만 바뀐다. `publish_state` 는
        knowledge.json 의 시각을 보고 발행할지 정하므로, 밤마다 돌리는 칸에서
        그러면 조용한 날에도 발행이 돈다.
        """
        k = self.knowledge()
        self.run_once(k)
        os.utime(self.path, (0, 0))
        rows = ge.survey(k, ctx())["rows"]
        changed, backup = ge.apply_evidence(k, rows, "20260905")
        self.assertEqual(0, changed)
        self.assertIsNone(backup, "쓰지 않았으면 백업도 만들지 않는다")
        self.assertEqual(0, self.path.stat().st_mtime, "파일을 건드리지 않았다")
        self.assertFalse((self.dir / "backup-graph-20260905").exists())

    def test_it_asks_no_model(self):
        """근거는 원문에서 **찾는** 것이다. 모델에게 물으면 그럴듯한 message id 를
        지어낼 수 있고, 그것은 근거의 반대다. 밤마다 도는 칸이 되었으니 더 그렇다.
        """
        src = (Path(ge.__file__)).read_text(encoding="utf-8")
        self.assertNotIn("call_claude", src)
        self.assertNotIn("from scripts import llm", src)


class NodesMissingTest(unittest.TestCase):
    def test_an_edge_pointing_at_a_missing_node_is_skipped_quietly(self):
        edge = {"source": "person:없는이", "target": "app:sarangi", "type": "made"}
        self.assertEqual(([], ""), ge.find_evidence(edge, BY_ID, ctx(), {}))


if __name__ == "__main__":
    unittest.main()
