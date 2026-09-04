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

from scripts import ontology
from scripts import graph_evidence as ge

NODES = [
    {"id": "topic:projects", "type": "topic", "label": "프로젝트", "category": "projects"},
    {"id": "person:가나다", "type": "person", "label": "가나다"},
    {"id": "person:라마바", "type": "person", "label": "라마바"},
    {"id": "app:sarangi", "type": "app", "label": "사랑이 앱", "query": "사랑이"},
    {"id": "app:vague", "type": "app", "label": "이야기 나누는 앱", "query": "이야기 나누는"},
    {"id": "tool:short", "type": "tool", "label": "상담 실시간 안내 도구", "query": "상담"},
    {"id": "tool:slack", "type": "tool", "label": "슬랙", "query": "슬랙"},
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
    ("msg-7", "2026-07-01", "슬랙에 붙였습니다", "가나다", "t-9", "chat"),
]

# t-1 은 '사랑이 앱' 을 다룬 주제, t-2 는 '상담' 도구를 다룬 주제.
THREADS = [
    {"id": "t-1", "title": "사랑이 앱 만들기", "tags": ["사랑이 앱"]},
    {"id": "t-2", "title": "상담 도구 후기", "tags": ["상담 실시간 안내 도구"]},
    {"id": "t-9", "title": "잡담", "tags": []},
]


def ctx(node_tags=None, reports=None) -> dict:
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
        "report_head": (reports or {}).get("head", {}),
        "report_paras": (reports or {}).get("paras", {}),
        "report_cat": {t[4]: t[5] for t in ROWS},
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


class NodeNameTest(unittest.TestCase):
    """라벨은 사람이 읽으라고 지은 표시용 이름이라 원문의 말과 다를 때가 많다."""

    def test_the_original_spelling_in_brackets_is_a_name_too(self):
        # 실측 2026-09-05: query 는 음역 두 글자인데 원문에는 로마자가 25건이었다.
        got = ontology.node_names({"label": "버셀(Vercel)", "query": "버셀"})
        self.assertIn("vercel", got)
        self.assertIn("버셀", got)

    def test_a_korean_bracket_is_a_description_not_a_name(self):
        """'센터 홈페이지(웹접근성)' 의 '웹접근성' 을 이름으로 삼으면 접근성
        이야기 전부가 그 홈페이지 언급이 된다."""
        got = ontology.node_names({"label": "센터 홈페이지(웹접근성)",
                                   "query": "센터 홈페이지"})
        self.assertNotIn("웹접근성", got)

    def test_the_middle_dot_is_not_split(self):
        """이 방의 라벨에서 `·` 는 서로 다른 둘을 묶는 자리로 더 자주 쓰인다 —
        '시놀로지 나스·도커' 를 갈라 '도커' 를 이름으로 삼으면 도커 이야기
        전부가 그 나스 언급이 된다."""
        got = ontology.node_names({"label": "시놀로지 나스·도커", "query": "시놀로지"})
        self.assertNotIn("도커", got)

    def test_every_reader_uses_the_same_names_and_the_same_matcher(self):
        """크기(build_site)·분류 확인·근거(graph_evidence)가 다른 것을 세면 안 된다.

        이름 목록만 같아서는 모자란다. 찾는 **방법**도 같아야 한다 — 한쪽만 낱말
        경계를 지키면 `aws` 가 `welfare-laws` 에 걸리는 자리가 그쪽에만 남는다.
        """
        site = (Path(ge.__file__).parent / "build_site.py").read_text(encoding="utf-8")
        self.assertIn("ontology.name_matcher(ontology.node_names(n))", site,
                      "노드 크기")
        self.assertIn("ontology.name_matcher(names)", site, "분류 확인")
        self.assertIn("ontology.findable_names(n)", site,
                      "분류 확인도 같은 이름 규칙을 써야 한다")
        src = Path(ge.__file__).read_text(encoding="utf-8")
        self.assertIn("names = ontology.node_names(node)", src)
        self.assertIn("ontology.name_matcher(long_names)", src, "근거 찾기")


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

    def test_a_short_name_that_is_the_whole_label_is_a_name(self):
        """방벽은 긴 이름에서 잘라 온 조각을 막으려는 것이다. 두 글자가 통째로
        이름인 것들이 같은 그물에 걸리면 안 된다 — 실측 2026-09-05: 두 글자가
        통째로 이름인 노드 셋에서 43건을 찾아 놓고 버리고 있었다.
        """
        thin = ctx()
        thin["threads"] = [{"id": t["id"], "title": "무제", "tags": []}
                           for t in THREADS]
        # 이어진 주제가 하나도 없어도 '슬랙' 은 제 이름으로 걸린다
        self.assertEqual([6], ge.mentions_of(BY_ID["tool:slack"], thin))


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


def reports(head: dict, paras: dict) -> dict:
    """보고서 문맥을 만든다. 띄어쓰기를 지운 소문자로 — ge.squeeze 와 같게."""
    return {"head": {k: ge.squeeze(v) for k, v in head.items()},
            "paras": {k: [ge.squeeze(x) for x in v] for k, v in paras.items()}}


class ReportRouteTest(unittest.TestCase):
    """원문에 자리가 없으면 보고서를 본다.

    이 방에서 '무엇으로 만들었다' 는 보고서가 가장 또렷하게 적는다. 원문에서는
    앱 이야기와 도구 이야기가 이어지는 **다른** 메시지로 오간다 — 한 메시지 안만
    보는 규칙이 볼 수 없는 자리다(실측 2026-09-05: 빈칸 153개 중 84개).
    """

    def test_two_things_in_one_paragraph_is_evidence_and_points_at_the_thread(self):
        c = ctx(reports=reports(
            {"t-3": "무제"},
            {"t-3": ["이야기 나누는 앱은 바른도구로 만들었다"]}))
        c["report_cat"]["t-3"] = "projects"
        edge = {"source": "app:vague", "type": "uses", "target": "tool:bareun"}
        ids, by = ge.find_evidence(edge, BY_ID, c, {})
        self.assertEqual(["t-3"], ids, "자리는 주제 id 다 — 가리킬 한 줄이 없다")
        self.assertEqual("named-both+report", by)

    def test_the_narrow_place_wins(self):
        """원문에 한 줄이 있으면 그것을 쓴다. 보고서는 없을 때의 자리다."""
        c = ctx(reports=reports(
            {"t-3": "무제"},
            {"t-3": ["사랑이 앱은 바른도구로 만들었다"]}))
        edge = {"source": "app:sarangi", "type": "uses", "target": "tool:bareun"}
        ids, by = ge.find_evidence(edge, BY_ID, c, {})
        self.assertEqual(["msg-2"], ids)
        self.assertEqual("named-both", by)

    def test_a_person_and_a_thing_must_meet_in_one_paragraph(self):
        """보고서에는 여러 사람이 나온다. 한 편 전체를 그릇으로 삼으면 서로 다른
        문단에 따로 나온 사람과 도구가 이어진다.
        """
        apart = ctx(reports=reports(
            {"t-3": "무제"},
            {"t-3": ["라마바가 인사했다", "누군가 바른도구를 소개했다"]}))
        edge = {"source": "person:라마바", "type": "uses", "target": "tool:bareun"}
        self.assertEqual(([], "named-it"), ge.find_evidence(edge, BY_ID, apart, {}))
        together = ctx(reports=reports(
            {"t-3": "무제"},
            {"t-3": ["라마바가 바른도구를 쓴다고 했다"]}))
        ids, by = ge.find_evidence(edge, BY_ID, together, {})
        self.assertEqual(["t-3"], ids)
        self.assertEqual("named-it+report", by)

    def test_the_subject_of_the_report_carries_the_whole_report(self):
        """보고서는 주제가 하나다. 그 결과물이 제목에 있으면 본문의 도구는 그
        이야기다 — 문단이 갈려도 이어 준다.
        """
        c = ctx(reports=reports(
            {"t-3": "이야기 나누는 앱 만들기"},
            {"t-3": ["처음에는 막막했다", "바른도구를 붙이니 풀렸다"]}))
        edge = {"source": "app:vague", "type": "uses", "target": "tool:bareun"}
        ids, by = ge.find_evidence(edge, BY_ID, c, {})
        self.assertEqual(["t-3"], ids)
        self.assertEqual("named-both+report", by)

    def test_two_things_passing_through_someone_elses_report_do_not_count(self):
        """제목에 없고 한 문단에서도 안 만나면 붙이지 않는다."""
        c = ctx(reports=reports(
            {"t-3": "모임 앞두고 발표자료 공유"},
            {"t-3": ["이야기 나누는 앱이 잠깐 나왔다", "바른도구 이야기도 잠깐 나왔다"]}))
        edge = {"source": "app:vague", "type": "uses", "target": "tool:bareun"}
        self.assertEqual(([], "named-both"), ge.find_evidence(edge, BY_ID, c, {}))

    def test_spacing_does_not_hide_a_name(self):
        """보고서는 다듬은 글이라 '사랑이 앱' 을 '사랑이앱' 으로도 적는다."""
        c = ctx(reports=reports(
            {"t-3": "무제"}, {"t-3": ["이야기나누는앱은 바른도구로 만들었다"]}))
        edge = {"source": "app:vague", "type": "uses", "target": "tool:bareun"}
        self.assertEqual(["t-3"], ge.find_evidence(edge, BY_ID, c, {})[0])


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


class BelongsIsNotAClaimTest(unittest.TestCase):
    """`belongs` 는 대화에서 찾은 주장이 아니라 노드의 분류 칸을 옮긴 것이다.

    그러니 '그 분류의 말에 이 이름이 나오나' 를 물으면 분류가 어긋난 노드가 전부
    근거 없음으로 나온다 — 못 찾은 것이 아니라 물음이 어긋난 것이다. 그래서 '왜
    못 찾았나' 표에서 빼고 '분류를 다시 볼 목록' 으로 돌린다.
    """

    def gaps(self):
        c = ctx()
        c["cat_label"] = {"projects": "프로젝트", "infra": "인프라"}
        rows = [
            {"edge": {"source": "tool:bareun", "type": "belongs",
                      "target": "topic:projects"},
             "shape": "tool -belongs-> topic", "evidence": [], "by": "named-in"},
            {"edge": {"source": "app:vague", "type": "uses",
                      "target": "tool:bareun"},
             "shape": "app -uses-> tool", "evidence": [], "by": "named-both"},
        ]
        return rows, c

    def test_belongs_gets_its_own_section(self):
        rows, c = self.gaps()
        out = "\n".join(ge.gaps_belongs_section([rows[0]], BY_ID, c))
        self.assertIn("분류가 어긋나 보이는 노드", out)
        self.assertIn("바른도구", out)
        self.assertNotIn("왜 못 찾았나", out)

    def test_the_section_does_not_claim_the_filing_is_wrong(self):
        """도구의 분류는 '어떤 것인가' 이고 언급 분포는 '어디서 이야기됐나' 다."""
        rows, c = self.gaps()
        out = "\n".join(ge.gaps_belongs_section([rows[0]], BY_ID, c))
        self.assertIn("단정하지 않는다", out)

    def test_nothing_is_written_when_there_is_no_belongs(self):
        rows, c = self.gaps()
        self.assertEqual([], ge.gaps_belongs_section([], BY_ID, c))


class NodesMissingTest(unittest.TestCase):
    def test_an_edge_pointing_at_a_missing_node_is_skipped_quietly(self):
        edge = {"source": "person:없는이", "target": "app:sarangi", "type": "made"}
        self.assertEqual(([], ""), ge.find_evidence(edge, BY_ID, ctx(), {}))


if __name__ == "__main__":
    unittest.main()
