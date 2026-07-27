# -*- coding: utf-8 -*-
"""태그 표기 통일·태그 색인·사람별 관심 주제."""
import json
import tempfile
import unittest
from pathlib import Path

from scripts import interests, tags


CATEGORIES = [
    {"id": "projects", "label": "프로젝트·결과물"},
    {"id": "ai-tools", "label": "AI 코딩 도구·에이전트"},
    {"id": "chat", "label": "일상·잡담"},
]


class FoldTests(unittest.TestCase):
    def test_case_and_space_differences_fold_together(self):
        self.assertEqual(tags.fold("AI Studio"), tags.fold("ai-studio"))
        self.assertEqual(tags.fold("바이브 코딩"), tags.fold("바이브코딩"))

    def test_most_used_spelling_wins_without_a_table(self):
        # 표에 안 적어도 많이 쓴 표기로 합쳐진다
        raw = ["바이브코딩"] * 3 + ["바이브 코딩"]
        m = tags.build_tag_map(raw, aliases={})
        self.assertEqual(m["바이브 코딩"], "바이브코딩")
        self.assertEqual(m["바이브코딩"], "바이브코딩")

    def test_alias_table_beats_frequency(self):
        # 'Gemini' 가 더 많이 쓰였어도 표가 대표 표기를 정한다
        raw = ["Gemini"] * 5 + ["제미나이"]
        m = tags.build_tag_map(raw, aliases={"gemini": "제미나이", "제미나이": "제미나이"})
        self.assertEqual(m["Gemini"], "제미나이")

    def test_alias_file_is_valid_and_self_consistent(self):
        table = tags.load_aliases()
        self.assertTrue(table, "config/tag_aliases.json 을 읽지 못했습니다")
        # 한 변형이 두 대표를 가리키면 결과가 실행 순서에 따라 달라진다
        raw = json.loads((tags.ALIAS_PATH).read_text(encoding="utf-8"))["aliases"]
        # 같은 변형이 두 대표를 가리키면 결과가 실행 순서에 따라 달라진다.
        # (공백만 다른 변형은 정상이다 — 어느 표기를 대표로 쓸지 고정하는 역할이다.)
        seen = {}
        for canon, variants in raw.items():
            for v in list(variants) + [canon]:
                key = tags.fold(v)
                prev = seen.get(key)
                self.assertIn(prev, (None, canon),
                              "'%s' 가 %s 와 %s 두 곳에 있습니다" % (v, prev, canon))
                seen[key] = canon


class TagIndexTests(unittest.TestCase):
    def setUp(self):
        self.threads = [
            {"id": "t-1", "category": "projects", "participants": ["김종원"],
             "keywords": ["바이브코딩", "clasp"]},
            {"id": "t-2", "category": "ai-tools", "participants": ["김종원", "호야"],
             "keywords": ["바이브 코딩", "한번만"]},
        ]
        tags.attach_tags(self.threads, {"participants": [{"nickname": "김종원"}]})

    def test_thread_tags_are_unified(self):
        self.assertEqual(self.threads[1]["tags"], ["바이브코딩", "한번만"])

    def test_index_hides_single_use_tags_but_counts_them(self):
        idx = tags.build_tag_index(self.threads, min_count=2)
        names = [r["tag"] for r in idx["tags"]]
        self.assertEqual(names, ["바이브코딩"])
        self.assertEqual(idx["hidden_tags"], 2)  # clasp, 한번만
        self.assertEqual(idx["tags"][0]["thread_ids"], ["t-1", "t-2"])

    def test_person_tags_are_marked(self):
        threads = [
            {"id": "t-%d" % i, "category": "chat", "participants": ["호야"],
             "keywords": ["김종원"]} for i in range(2)
        ]
        parts = {"participants": [{"nickname": "김종원(○○관)"}]}
        tags.attach_tags(threads, parts)
        idx = tags.build_tag_index(threads, parts, min_count=2)
        self.assertTrue(idx["tags"][0]["person"], "괄호 소속을 뗀 이름도 사람으로 봐야 한다")


class InterestTests(unittest.TestCase):
    def _threads(self):
        """방 평균: 프로젝트 4 / 도구 6. 김종원은 프로젝트에, 호야는 도구에 몰린다."""
        rows = []
        for i in range(4):
            # 호야도 절반은 낀다 — 그래도 도구 쪽 비중이 방 평균보다 높아야 한다
            who = ["김종원", "호야"] if i < 2 else ["김종원"]
            rows.append({"id": "p%d" % i, "category": "projects",
                         "participants": who, "tags": ["clasp", "공통태그"]})
        for i in range(6):
            rows.append({"id": "a%d" % i, "category": "ai-tools",
                         "participants": ["호야", "손님"], "tags": ["공통태그"]})
        return rows

    def test_shared_tag_loses_to_personal_tag(self):
        out = interests.build_interests(self._threads(), CATEGORIES)
        me = [p for p in out["people"] if p["nickname"] == "김종원"][0]
        self.assertEqual(me["topics"][0]["tag"], "clasp",
                         "모두가 쓴 '공통태그' 가 개인 특징으로 올라오면 안 된다")

    def test_fields_compare_against_room_average(self):
        out = interests.build_interests(self._threads(), CATEGORIES)
        hoya = [p for p in out["people"] if p["nickname"] == "호야"][0]
        kim = [p for p in out["people"] if p["nickname"] == "김종원"][0]
        self.assertEqual([f["category"] for f in hoya["fields"]], ["ai-tools"])
        self.assertEqual([f["category"] for f in kim["fields"]], ["projects"])

    def test_opt_out_removes_the_person_from_published_data(self):
        out = interests.build_interests(self._threads(), CATEGORIES, hidden={"호야"})
        self.assertNotIn("호야", [p["nickname"] for p in out["people"]])
        self.assertIn("김종원", [p["nickname"] for p in out["people"]])
        self.assertEqual(out["hidden_count"], 1)

    def test_quiet_people_are_left_out(self):
        rows = self._threads()
        rows.append({"id": "x", "category": "chat", "participants": ["잠깐"], "tags": []})
        out = interests.build_interests(rows, CATEGORIES)
        self.assertNotIn("잠깐", [p["nickname"] for p in out["people"]])


class DigestKeywordTests(unittest.TestCase):
    """요지 산문의 태그는 눌러서 갈 곳이 있어야 화면에 낸다."""

    def test_unreachable_digest_keywords_are_dropped(self):
        from scripts import build_site
        threads = [{"id": "t-1", "category": "projects", "title": "차량운행일지 공개",
                    "summary": "티맵 연동", "report": "슬랙으로 알린다.",
                    "message_ids": ["m1"], "count": 1, "tags": ["차량운행일지"]}]
        topics = {"categories": [{"id": "projects", "label": "프로젝트"}],
                  "threads": [{"id": "t-1", "category": "projects", "message_ids": ["m1"]}]}
        prose = {"digests": {"projects": {"keywords": [
            "차량 운행일지",   # 태그와 띄어쓰기만 다르다 → 남는다
            "슬랙",            # 보고서 본문에 있다 → 남는다
            "망분리·보안",      # 어디에도 없다 → 뺀다
        ]}}}
        digests = build_site.build_digests(
            [{"id": "m1", "nickname": "김종원", "date": "2026-01-01", "category": "projects"}],
            threads, topics, {"nodes": []}, prose,
        )
        self.assertEqual(digests["projects"]["keywords"], ["차량 운행일지", "슬랙"])


class SecondaryCategoryTests(unittest.TestCase):
    """보조 분류는 통계를 건드리지 않아야 한다."""

    def test_load_secondary_tolerates_missing_file(self):
        from scripts import build_site
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(build_site.load_secondary(Path(d) / "nope.json"), {})

    def test_reply_parser_drops_rule_breaking_rows(self):
        from scripts import assign_secondary as sec
        reply = json.dumps({"assign": [
            {"id": "t-1", "also": ["ai-tools"]},
            {"id": "t-1", "also": ["projects"]},      # 주 분류를 다시 적은 것
            {"id": "t-2", "also": ["chat"]},          # 잡담은 보조로 달지 않는다
            {"id": "t-9", "also": ["ai-tools"]},      # 없는 주제
            {"id": "t-2", "also": ["nope"]},          # 없는 분류
        ]})
        got = sec.parse_reply(reply, {"t-1", "t-2"}, {"projects", "ai-tools", "chat"},
                              {"t-1": "projects", "t-2": "projects"})
        self.assertEqual(got, {"t-1": ["ai-tools"]})


if __name__ == "__main__":
    unittest.main()
