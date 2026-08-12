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
            # 실제 관계망에는 카테고리마다 토픽 노드가 있다(chat 만 없다). 새 노드를
            # 매달 자리가 있는지 없는지가 갈리므로 fixture 도 그렇게 둔다.
            {"id": "topic:ai-tools", "type": "topic", "label": "AI 도구",
             "category": "ai-tools"},
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
        # 엣지가 하나 함께 생긴다 — 아래 test_isolated_new_node_is_anchored 참고.
        self.assertEqual((1, 1), (n, e))
        added = [x for x in k["nodes"] if x["id"] == "tool:claude-p"][0]
        self.assertEqual("ai-tools", added["category"])
        self.assertIn("query", added)

    def test_isolated_new_node_is_anchored_to_its_category(self):
        """엣지를 못 얻은 새 노드는 카테고리 토픽에 매달린다.

        실측 2026-07-30: `tool:munja-sesang` 이 엣지 없이 붙어 관계망에 섬이 뜨고
        `test_no_isolated_nodes` 가 그날 발행을 막았다 — 새 글 34건이 이틀 묶였다.
        """
        k = graph_skeleton()
        n, e = merge_graph(k, {"nodes": [
            {"id": "tool:munja-sesang", "type": "tool", "category": "ai-tools",
             "label": "문자세상 문자발송"}
        ]}, CATS)
        self.assertEqual((1, 1), (n, e))
        self.assertIn({"source": "tool:munja-sesang", "target": "topic:ai-tools",
                       "type": "belongs", "weight": 1}, k["edges"])

    def test_isolated_new_node_without_an_anchor_is_dropped(self):
        """매달 토픽이 없으면(chat) 노드째 버린다 — 섬으로 남기지 않는다."""
        k = graph_skeleton()
        n, e = merge_graph(k, {"nodes": [
            {"id": "tool:nowhere", "type": "tool", "category": "chat",
             "label": "어디에도 없는 것"}
        ]}, CATS)
        self.assertEqual((0, 0), (n, e))
        self.assertEqual([], [x for x in k["nodes"] if x["id"] == "tool:nowhere"])

    def test_a_new_node_that_got_a_real_edge_is_not_anchored_twice(self):
        """엣지를 이미 얻은 새 노드에는 카테고리 엣지를 덧붙이지 않는다."""
        k = graph_skeleton()
        n, e = merge_graph(k, {
            "nodes": [{"id": "tool:claude-p", "type": "tool",
                       "category": "ai-tools", "label": "Claude -p"}],
            "edges": [{"source": "person:김종원", "target": "tool:claude-p",
                       "type": "uses"}],
        }, CATS)
        self.assertEqual((1, 1), (n, e))
        self.assertEqual([], [x for x in k["edges"] if x["type"] == "belongs"])

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

    def test_an_edge_whose_shape_does_not_hold_is_dropped(self):
        """관계 이름이 맞아도 양 끝의 종류가 안 맞으면 버린다.

        예전에는 이름만 봤다. 그래서 뜻이 안 되는 엣지가 원장에 남았다 —
        실측 2026-08-12: `person -belongs-> topic` 두 건. 여기서는 사람이 도구를
        '만든' 것을 거꾸로 적은 모양을 본다.
        """
        k = graph_skeleton()
        _, e = merge_graph(k, {"edges": [
            {"source": "app:urimal", "target": "person:김종원", "type": "made"}
        ]}, CATS)
        self.assertEqual(0, e)
        self.assertEqual([], k["edges"])

    def test_an_edge_with_one_possible_meaning_is_fixed_and_kept(self):
        """뜻이 하나로 정해지면 관계 이름을 고쳐서 받는다 — 버리면 알아낸 것이 사라진다.

        person → topic 에 성립하는 관계는 interested 하나다.
        """
        k = graph_skeleton()
        _, e = merge_graph(k, {"edges": [
            {"source": "person:김종원", "target": "topic:projects", "type": "belongs"}
        ]}, CATS)
        self.assertEqual(1, e)
        self.assertEqual("interested", k["edges"][0]["type"])

    def test_the_meanings_the_room_actually_uses_are_kept(self):
        """'관심을 보였다'(interested)는 '썼다'(uses)와 다른 말이다.

        치역을 좁게 잡으면 이 32건이 조용히 버려진다. 넉넉히 잡고 성립하지 않는
        모양만 막는 것이 요점이다.
        """
        k = graph_skeleton()
        k["nodes"].append({"id": "tool:antigravity", "type": "tool",
                           "label": "안티그래비티", "category": "ai-tools"})
        _, e = merge_graph(k, {"edges": [
            {"source": "person:김종원", "target": "tool:antigravity",
             "type": "interested"}
        ]}, CATS)
        self.assertEqual(1, e)
        self.assertEqual("interested", k["edges"][0]["type"])

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
        self.assertIsNotNone(write_report("t-999", self.base(""), 100, []))

    def test_bad_placeholder_is_dropped_instead_of_killing_the_report(self):
        """2026-07-28 방침 변경: 자리표는 쓰라고 한다.

        안 쓰면 사진·링크가 전부 글 끝으로 밀려 '글 따로 자료 따로'가 된다. 대신
        없는 자료를 가리키는 줄만 지운다 — 보고서를 통째로 버리지 않는다.
        """
        body = "첫 문단.\n\n![[msg-000001]]\n\n둘째 문단.\n\n![[msg-999999]]\n"
        msgs = [{"id": "msg-000001", "kind": "image", "text": ""}]
        why = write_report("t-999", self.base(body), 1000, msgs)
        self.assertIsNone(why, msg=f"거부됨: {why}")
        saved = (Path(self.tmp.name) / "t-999.md").read_text(encoding="utf-8")
        self.assertIn("![[msg-000001]]", saved, "실제로 있는 사진 자리는 남아야 한다")
        self.assertNotIn("msg-999999", saved, "없는 자료를 가리키는 줄은 지워야 한다")

    def test_inline_placeholder_in_a_sentence_is_dropped(self):
        # 화면은 한 줄로 놓인 자리표만 읽는다. 문장 속에 섞이면 글자로 새어 나온다.
        why = write_report("t-999", self.base("본문 ![[msg-000001]] 끝"), 1000,
                           [{"id": "msg-000001", "kind": "image", "text": ""}])
        self.assertIsNone(why, msg=f"거부됨: {why}")
        saved = (Path(self.tmp.name) / "t-999.md").read_text(encoding="utf-8")
        self.assertNotIn("![[", saved)

    def test_slightly_longer_than_source_is_allowed(self):
        # 실측 2026-07-27: 95자 원문의 정상 보고서가 110자로 나왔는데, '원문보다
        # 짧아야 한다'는 규칙에 걸려 거부됐다. 짧고 압축된 말을 풀어 쓰면 원문보다
        # 길어지는 것이 당연하다. topic_reports 도 최소 분량만 정한다.
        why = write_report("t-999", self.base("가" * 110), 95, [])
        self.assertIsNone(why, msg=f"거부됨: {why}")
        self.assertTrue((Path(self.tmp.name) / "t-999.md").exists())

    def test_every_caller_hands_over_the_messages(self):
        """`msgs` 에 기본값을 두면 안 된다.

        기본값 `None` 이 있던 동안 밤 분류 쪽 호출부가 메시지를 안 넘겼고,
        `sanitize_anchors` 가 '이 대화에 자료가 하나도 없다'고 보아 본문이 짚어 둔
        자리표를 **전부** 지웠다. 링크·사진이 글 끝으로 밀리는 것이 여러 번 고쳐
        달라고 해도 안 고쳐지던 원인이다(2026-07-29: t-350·t-351·t-352 에서 7줄).
        빈 목록이 맞는 상황이면 호출부가 `[]` 를 분명히 적게 한다.
        """
        import inspect

        p = inspect.signature(write_report).parameters["msgs"]
        self.assertIs(p.default, inspect.Parameter.empty,
                      "msgs 에 기본값이 생기면 안 넘긴 호출부가 조용히 자리표를 "
                      "잃습니다")

    def test_link_anchor_survives_when_the_message_has_a_url(self):
        # 링크 자리표는 그 메시지에 urls 가 있으면 살아야 한다. t-352 가 이 줄을
        # 잃어 자료 두 개가 글 끝으로 밀렸다.
        body = "온톨로지 웹앱을 공유했다.\n\n![[link:msg-002662]]\n\n반응이 좋았다.\n"
        msgs = [{"id": "msg-002662", "kind": "text", "text": "링크",
                 "urls": ["https://microsoft.github.io/Ontology-Playground/"]}]
        why = write_report("t-999", self.base(body), 1000, msgs)
        self.assertIsNone(why, msg=f"거부됨: {why}")
        saved = (Path(self.tmp.name) / "t-999.md").read_text(encoding="utf-8")
        self.assertIn("![[link:msg-002662]]", saved)

    def test_wildly_longer_than_source_is_refused(self):
        why = write_report("t-999", self.base("가" * 900), 95, [])
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
