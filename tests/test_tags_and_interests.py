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


class PlaceTagTests(unittest.TestCase):
    """지명·조직 이름은 태그 구름에서 빼되, **기계가 정하지 않는다.**

    이 방에서 '장애인복지관'·'거주시설' 은 기관 종류가 아니라 이야기의 주제 그
    자체다. 접미사만 보고 뺐다면 후보 26개 중 6개가 그렇게 사라졌을 것이고(실측
    2026-08-04), 반대로 '홍대입구'·'노원구' 는 접미사로 잡히지도 않는다.
    """

    def test_marked_only_when_the_table_says_so(self):
        threads = [{"id": "t-%d" % i, "keywords": ["한빛종합사회복지관", "바이브코딩"]}
                   for i in range(2)]
        tags.attach_tags(threads, {})
        places = {tags.fold("한빛종합사회복지관")}
        idx = tags.build_tag_index(threads, {}, min_count=2, places=places)
        marked = {r["tag"]: r["place"] for r in idx["tags"]}
        self.assertTrue(marked["한빛종합사회복지관"])
        self.assertFalse(marked["바이브코딩"])

    def test_no_table_hides_nothing(self):
        threads = [{"id": "t-%d" % i, "keywords": ["한빛종합사회복지관"]} for i in range(2)]
        tags.attach_tags(threads, {})
        idx = tags.build_tag_index(threads, {}, min_count=2)
        self.assertFalse(idx["tags"][0]["place"], "표가 없으면 아무것도 빠지지 않는다")

    def test_missing_table_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual((set(), set()), tags.load_places(Path(d) / "없다.json"))

    def test_candidates_skip_what_the_table_already_answered(self):
        threads = [{"id": "t-1", "keywords": ["무지개노인복지관", "거주시설", "바이브코딩"]}]
        cands = tags.place_candidates(
            threads, places={tags.fold("무지개노인복지관")},
            not_places={tags.fold("거주시설")})
        self.assertEqual([], cands, "한 번 판단한 것을 또 물으면 표를 쓸 이유가 없다")

    def test_profession_is_not_mistaken_for_an_organization(self):
        # '지사'·'지회' 를 접미사에 넣었더니 '사회복지사' 가 걸렸다(실측).
        threads = [{"id": "t-1", "keywords": ["사회복지사", "대구 사회복지사"]}]
        self.assertEqual([], tags.place_candidates(threads))

    def test_generic_type_is_still_offered_as_a_candidate(self):
        # 종류를 가리키는 말도 후보로는 나온다 — 사람이 not_places 로 옮겨야 한다.
        # 기계가 미리 갈라 두면 그 판단이 코드에 숨는다.
        threads = [{"id": "t-1", "keywords": ["장애인복지관"]}]
        self.assertEqual([("장애인복지관", 1)], tags.place_candidates(threads))

    def test_suffix_alone_is_not_a_candidate(self):
        threads = [{"id": "t-1", "keywords": ["복지관", "센터"]}]
        self.assertEqual([], tags.place_candidates(threads))


class VocabularyTests(unittest.TestCase):
    """보고서를 쓸 때 고르라고 보여줄 공통 어휘.

    태그 1,224종 중 1,090종이 한 번만 쓰인 뿌리는 표기 차이가 아니라 보고서마다
    태그를 새로 지어낸 것이다. 사후 봉합으로는 1회짜리의 약 10%만 구제된다.
    """

    def setUp(self):
        self.threads = [
            {"id": "t-1", "keywords": ["바이브코딩", "clasp", "김종원"]},
            {"id": "t-2", "keywords": ["바이브 코딩", "한번만", "김종원"]},
            {"id": "t-3", "keywords": ["바이브코딩", "무지개노인복지관"]},
            {"id": "t-4", "keywords": ["무지개노인복지관"]},
        ]
        self.parts = {"participants": [{"nickname": "김종원"}]}

    def test_only_settled_words_are_offered(self):
        # 한 번 쓰인 말까지 보여주면 그 목록이 곧 지어낸 말들의 목록이 된다.
        names = [n for n, _ in tags.vocabulary(self.threads, self.parts)]
        self.assertIn("바이브코딩", names)
        self.assertNotIn("clasp", names)
        self.assertNotIn("한번만", names)

    def test_spelling_variants_count_as_one_word(self):
        rows = dict(tags.vocabulary(self.threads, self.parts))
        self.assertEqual(3, rows["바이브코딩"], "'바이브 코딩' 도 같은 말로 세야 한다")

    def test_people_and_places_are_left_out(self):
        # 어휘로 보여주면 다음 보고서가 그 이름을 또 태그로 쓴다.
        names = [n for n, _ in tags.vocabulary(
            self.threads, self.parts, places={tags.fold("무지개노인복지관")})]
        self.assertNotIn("김종원", names)
        self.assertNotIn("무지개노인복지관", names)

    def test_most_used_comes_first(self):
        rows = tags.vocabulary(self.threads, self.parts)
        self.assertEqual("바이브코딩", rows[0][0])


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


class BackfillTests(unittest.TestCase):
    """제목이 곧 그 화제인데 태그에 없으면 채운다."""

    def test_title_subject_is_added_with_unified_spelling(self):
        threads = [
            {"id": "t-1", "title": "차량 운행일지 전체 코드 공개",
             "tags": ["오픈소스", "깃허브"]},
            {"id": "t-2", "title": "차량운행일지 무료 배포", "tags": ["차량운행일지"]},
        ]
        added = tags.backfill_from_titles(threads, ["차량 운행일지"], aliases={})
        # 이미 붙은 주제는 건드리지 않는다
        self.assertEqual([a[0] for a in added], ["t-1"])
        # 띄어쓰기가 다른 이름으로 새 태그를 만들면 태그가 둘로 갈린다
        self.assertIn("차량운행일지", threads[0]["tags"])
        self.assertNotIn("차량 운행일지", threads[0]["tags"])

    def test_alias_table_decides_the_added_spelling(self):
        threads = [{"id": "t-1", "title": "구글 AI 스튜디오 무료 한도", "tags": []}]
        tags.backfill_from_titles(threads, ["구글 AI 스튜디오"],
                                  aliases={"구글ai스튜디오": "AI 스튜디오"})
        self.assertEqual(threads[0]["tags"], ["AI 스튜디오"])

    def test_short_labels_are_ignored(self):
        threads = [{"id": "t-1", "title": "AI 쓰는 법", "tags": []}]
        tags.backfill_from_titles(threads, ["AI"], aliases={})
        self.assertEqual(threads[0]["tags"], [], "두 글자 이름은 아무 제목에나 걸린다")


class TranslitFoldTests(unittest.TestCase):
    """조각만 로마자인 태그도 같은 것으로 본다."""

    def test_latin_and_hangul_spellings_fold_together(self):
        self.assertEqual(tags.fold("Claude Code"), tags.fold("클로드 코드"))
        self.assertEqual(tags.fold("Gemini 3 Pro"), tags.fold("제미나이 3 프로"))
        self.assertEqual(tags.fold("Google Workspace"), tags.fold("구글 워크스페이스"))

    def test_only_whole_words_are_transliterated(self):
        # 'pro' 를 글자 단위로 바꾸면 '프로젝트'·'프로그램'까지 망친다
        self.assertNotEqual(tags.fold("프로젝트"), tags.fold("project"))
        self.assertEqual(tags.fold("프로젝트"), tags.fold("프로 젝트"))

    def test_unmapped_words_are_left_alone(self):
        self.assertEqual(tags.fold("clasp"), "clasp")


class RollupTests(unittest.TestCase):
    """좁은 태그를 넓은 태그로도 찾게 한다."""

    def _ontology(self):
        """실제로 갈렸던 네 주제. t-352 만 '온톨로지' 가 없었다."""
        return [
            {"id": "t-027", "tags": ["웹앱 보안", "온톨로지", "팔란티어"]},
            {"id": "t-060", "tags": ["온톨로지", "TypeDB", "온톨로지 튜토리얼"]},
            {"id": "t-147", "tags": ["온톨로지", "지식그래프"]},
            {"id": "t-352", "tags": ["Ontology-Playground", "온톨로지 모델링", "포크"]},
        ]

    def test_narrow_tag_gains_the_broad_one(self):
        threads = self._ontology()
        added = tags.rollup_parent_tags(threads)
        self.assertIn(("t-352", "온톨로지"), added)
        # 좁은 태그를 잃지 않는다 — 덧붙이는 것이고 바꾸는 것이 아니다
        self.assertIn("온톨로지 모델링", threads[3]["tags"])
        idx = tags.build_tag_index(threads, min_count=2)
        row = next(r for r in idx["tags"] if r["tag"] == "온톨로지")
        self.assertEqual(row["count"], 4, "네 주제가 모두 '온톨로지' 로 찾혀야 한다")
        self.assertIn("t-352", row["thread_ids"])

    def test_latin_named_resource_reaches_the_hangul_tag(self):
        # 'Ontology-Playground' 는 '온톨로지' 를 한 글자도 품지 않는다
        threads = self._ontology()
        tags.rollup_parent_tags(threads)
        self.assertIn("온톨로지", threads[3]["tags"])

    def test_single_use_tag_cannot_be_a_parent(self):
        threads = [
            {"id": "t-1", "tags": ["대기 시스템"]},
            {"id": "t-2", "tags": ["대기 시스템 개편"]},
        ]
        self.assertEqual(tags.rollup_parent_tags(threads), [],
                         "한 번 쓰인 말이 부모가 되면 아무 말이나 부모가 된다")

    def test_short_tag_cannot_be_a_parent(self):
        threads = [
            {"id": "t-%d" % i, "tags": ["AI"]} for i in range(2)
        ] + [{"id": "t-9", "tags": ["AI 교육"]}]
        added = tags.rollup_parent_tags(threads)
        self.assertEqual(added, [], "'AI' 가 부모면 거의 모든 태그가 자식이 된다")

    def test_person_name_is_not_a_parent(self):
        threads = [
            {"id": "t-1", "tags": ["김종원"]},
            {"id": "t-2", "tags": ["김종원"]},
            {"id": "t-3", "tags": ["김종원 수정판"]},
        ]
        parts = {"participants": [{"nickname": "김종원(○○관)"}]}
        self.assertEqual(tags.rollup_parent_tags(threads, parts), [],
                         "이름 태그는 참여자 화면 몫이다")

    def test_grandparent_is_attached_too(self):
        threads = [
            {"id": "t-1", "tags": ["클로드"]}, {"id": "t-2", "tags": ["클로드"]},
            {"id": "t-3", "tags": ["클로드 코드"]}, {"id": "t-4", "tags": ["클로드 코드"]},
            {"id": "t-5", "tags": ["클로드코드 프로"]},
        ]
        tags.rollup_parent_tags(threads)
        self.assertEqual(set(threads[4]["tags"]),
                         {"클로드코드 프로", "클로드 코드", "클로드"})

    def test_running_twice_adds_nothing_new(self):
        threads = self._ontology()
        tags.rollup_parent_tags(threads)
        before = [list(th["tags"]) for th in threads]
        tags.rollup_parent_tags(threads)
        self.assertEqual([th["tags"] for th in threads], before)


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
