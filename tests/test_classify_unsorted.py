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

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import classify_unsorted as classify
from scripts.classify_unsorted import (
    merge_graph, norm_label, render_report, validate, write_report,
)
from scripts.topic_reports import parse_report

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


class ReportRenderTests(unittest.TestCase):
    """보고서 md 가 화면의 실제 내용 단위다.

    apply_reports() 가 제목·요지·**태그**·본문을 여기서 읽어 스레드에 얹는다.
    보고서가 없으면 그 주제는 태그도 본문도 없다 — 실측 2026-07-27 에 자동 분류가
    스레드만 만들고 보고서를 빼먹어 새 주제 두 개가 그 상태로 남았다.
    """

    def test_rendered_report_round_trips_through_parse_report(self):
        text = render_report("제목", "요지 한 문장", ["태그1", "태그2"], "본문이다.")
        back = parse_report(text, "t-999.md")
        self.assertEqual("제목", back["title"])
        self.assertEqual("요지 한 문장", back["summary"])
        self.assertEqual(["태그1", "태그2"], back["keywords"])
        self.assertEqual("본문이다.", back["report"])

    def test_newlines_in_values_are_flattened(self):
        # parse_report 는 프론트매터를 줄 단위로 읽는다. 값에 줄바꿈이 들어가면
        # 다음 줄이 '콜론이 없는 줄'이 되어 ValueError 로 파이프라인이 멈춘다.
        text = render_report("제목\n둘째 줄", "요지\n계속", ["태\n그"], "본문")
        back = parse_report(text, "t-999.md")
        self.assertEqual("제목 둘째 줄", back["title"])
        self.assertEqual("요지 계속", back["summary"])

    def test_keywords_are_optional(self):
        text = render_report("제목", "요지", [], "본문")
        self.assertEqual([], parse_report(text, "t-999.md")["keywords"])
        self.assertNotIn("keywords:", text)

    def test_colon_in_title_survives(self):
        # parse_report 가 첫 콜론에서만 자르는 이유가 이것이다(제목에 URL·시각).
        text = render_report("우리말: 윤문 도구", "요지", [], "본문")
        self.assertEqual("우리말: 윤문 도구",
                         parse_report(text, "t-999.md")["title"])


class ReportGuardTests(unittest.TestCase):
    """지어낸 본문을 막되, 정상적인 보고서를 막지는 않는다.

    write_report 는 파일을 쓴다. 실제 output/reports/ 에 쓰게 두면 테스트가 아카이브를
    더럽히고, 단정이 먼저 실패하면 찌꺼기가 남는다. 임시 폴더로 갈아끼운다.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(
            classify, "REPORTS_DIR", Path(self.tmp.name))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def base(self, body):
        return {"id": "t-999", "title": "제목", "summary": "요지",
                "keywords": [], "report": body}

    def test_empty_body_is_refused(self):
        self.assertIsNotNone(write_report("t-999", self.base(""), 100))

    def test_placeholder_in_body_is_refused(self):
        # 자리표를 만들면 audit_report_context 가 '유효하지 않은 자리표'로 잡는다.
        why = write_report("t-999", self.base("본문 ![[img-1]] 끝"), 1000)
        self.assertIsNotNone(why)
        self.assertIn("자리표", why)

    def test_slightly_longer_than_source_is_allowed(self):
        # 실측 2026-07-27: 95자 원문의 정상 보고서가 110자로 나왔는데, '원문보다
        # 짧아야 한다'는 규칙에 걸려 거부됐다. 짧고 압축된 말을 풀어 쓰면 원문보다
        # 길어지는 것이 당연하다. topic_reports 도 최소 분량만 정한다.
        why = write_report("t-999", self.base("가" * 110), 95)
        self.assertIsNone(why, msg=f"거부됨: {why}")
        self.assertTrue((Path(self.tmp.name) / "t-999.md").exists())

    def test_wildly_longer_than_source_is_refused(self):
        why = write_report("t-999", self.base("가" * 900), 95)
        self.assertIsNotNone(why)
        self.assertIn("너무 깁니다", why)
        self.assertFalse((Path(self.tmp.name) / "t-999.md").exists())


class NormalizeTests(unittest.TestCase):
    def test_label_normalization_catches_spacing_variants(self):
        self.assertEqual(norm_label("우리말 윤문"), norm_label("우리말윤문"))
        self.assertEqual(norm_label("Claude -p"), norm_label("claude-p"))
        self.assertNotEqual(norm_label("우리말"), norm_label("우리말윤문"))


if __name__ == "__main__":
    unittest.main()
