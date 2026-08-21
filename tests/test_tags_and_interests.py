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
            self.assertEqual(set(), tags.load_named_people(Path(d) / "없다.json"))

    def test_a_named_outsider_is_not_offered_as_vocabulary(self):
        """방에 없는 사람의 이름은 추천 어휘에 오르면 안 된다.

        실측 2026-08-21: 한 교수의 이름이 태그로 4번 쓰여 어휘 142종에 올라 있었고,
        유산 태그를 다시 고르게 하니 그 이름이 다른 보고서에도 붙었다. 참여자
        목록으로는 못 막는다 — 그 사람은 이 방에 없다. 저장소는 공개다.
        """
        threads = [{"id": "t-%d" % i, "keywords": ["홍길동", "바이브코딩"]}
                   for i in range(3)]
        names = {n for n, _ in tags.vocabulary(threads, {})}
        self.assertIn("홍길동", names, "표가 없으면 걸러지지 않는다(전제 확인)")

        with tempfile.TemporaryDirectory() as d:
            table = Path(d) / "tag_places.json"
            table.write_text('{"people": ["홍길동"]}', encoding="utf-8")
            self.assertEqual({"홍길동"}, tags.load_named_people(table))
            merged = tags.person_names({"participants": [{"nickname": "김종원(○○관)"}]},
                                       named=tags.load_named_people(table))
            self.assertEqual({"홍길동", "김종원(○○관)", "김종원"}, merged)

    def test_a_tag_that_is_itself_a_parent_is_not_an_orphan(self):
        """자기가 부모인 태그에 부모를 붙이라고 물으면 없는 층을 하나 더 세운다.

        실측 2026-08-21: '게임' 은 보고서 한 편에만 직접 붙어 있어 1회짜리로 세어졌지만,
        자식들이 승격돼 와 태그 목록에는 8편으로 나온다. 헛후보가 목록에 섞여 있었다.
        """
        threads = [{"id": "t-1", "keywords": ["게임", "아기하마 게임"]},
                   {"id": "t-2", "keywords": ["아기하마 게임"]},
                   {"id": "t-3", "keywords": ["없는말"]}]
        tags.attach_tags(threads, {})
        got = dict(tags.broader_candidates(threads, {"아기하마게임": "게임"}, {},
                                           short_parents=["게임"]))
        self.assertNotIn("게임", got, "부모인 태그는 후보가 아니다")
        self.assertIn("없는말", got, "진짜 고립은 그대로 나와야 한다")

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

    def test_every_field_says_which_level_it_came_from(self):
        out = interests.build_interests(self._threads(), CATEGORIES)
        for p in out["people"]:
            for f in p["fields"]:
                self.assertEqual("category", f["level"])


class CategoryGroupFallbackTests(unittest.TestCase):
    """분류로 아무것도 안 나온 사람만 상위 묶음으로 한 번 더 본다.

    분류가 평평해서 주제 3~5개짜리 참여자는 12분면에서 표본이 너무 얇다 — 실측
    2026-08-14 에 32명 중 5명이 관심 분야가 0개였다. 'AI 코딩 도구' 1건 +
    'AI 모델' 1건은 분류로는 각각 1건이라 묻히지만 묶으면 2건이 된다.
    """

    CATS = CATEGORIES + [{"id": "ai-models", "label": "AI 모델"}]
    GROUPS = {"ai-tools": "group:ai", "ai-models": "group:ai",
              "projects": "group:building"}
    LABELS = {"group:ai": "AI 도구·모델", "group:building": "만들기·기술"}

    def _rows(self):
        """방은 프로젝트 이야기가 많다. '새내기' 는 AI 쪽에 1건씩 흩어져 있다.

        김종원은 프로젝트에 몰려 있어 분류 층에서 이미 분야가 나온다 — 묶음이
        그것을 덮지 않는다는 것을 볼 상대다. AI 쪽은 '고수' 가 채운다.
        """
        rows = [{"id": "p%d" % i, "category": "projects",
                 "participants": ["김종원"], "tags": ["공통태그"]} for i in range(6)]
        rows += [{"id": "q%d" % i, "category": "projects",
                  "participants": ["고수"], "tags": ["공통태그"]} for i in range(2)]
        rows += [{"id": "x%d" % i, "category": "ai-tools",
                  "participants": ["고수"], "tags": ["공통태그"]} for i in range(2)]
        rows += [{"id": "y%d" % i, "category": "ai-models",
                  "participants": ["고수"], "tags": ["공통태그"]} for i in range(2)]
        rows += [
            {"id": "a1", "category": "ai-tools", "participants": ["새내기"],
             "tags": ["커서"]},
            {"id": "a2", "category": "ai-models", "participants": ["새내기"],
             "tags": ["오퍼스"]},
            {"id": "p9", "category": "projects", "participants": ["새내기"],
             "tags": ["공통태그"]},
        ]
        return rows

    def _out(self, **kw):
        return interests.build_interests(self._rows(), self.CATS, **kw)

    def rookie(self, out):
        return [p for p in out["people"] if p["nickname"] == "새내기"][0]

    def test_without_groups_the_thin_person_gets_nothing(self):
        self.assertEqual([], self.rookie(self._out())["fields"],
                         "12분면에서는 1건씩이라 묻힌다 — 이것이 실측 5명이다")

    def test_the_group_fills_it_in(self):
        out = self._out(group_of=self.GROUPS.get,
                        group_label=lambda g: self.LABELS.get(g, g))
        fields = self.rookie(out)["fields"]
        self.assertEqual(["group:ai"], [f["category"] for f in fields])
        self.assertEqual("AI 도구·모델", fields[0]["label"])
        self.assertEqual(2, fields[0]["count"])
        self.assertEqual("group", fields[0]["level"])

    def test_a_person_who_already_has_a_field_is_left_alone(self):
        """묶음은 채우는 것이 아니라 대신하는 것이다.

        섞으면 '프로젝트·결과물' 옆에 '만들기·기술' 이 나란히 서서 같은 말을 두 번 한다.
        """
        out = self._out(group_of=self.GROUPS.get,
                        group_label=lambda g: self.LABELS.get(g, g))
        kim = [p for p in out["people"] if p["nickname"] == "김종원"][0]
        self.assertEqual(["category"], sorted({f["level"] for f in kim["fields"]}))

    def _with_chat(self, **kw):
        rows = self._rows()
        rows += [{"id": "c%d" % i, "category": "chat", "participants": ["새내기"],
                  "tags": []} for i in range(8)]
        return interests.build_interests(
            rows, self.CATS + [{"id": "chat", "label": "일상·잡담"}], **kw)

    def test_chat_never_becomes_an_interest(self):
        """'일상·잡담' 을 관심 분야로 내지 않는다.

        실측 2026-08-14: 이 걸림이 없을 때 발행본에서 세 사람이 '일상·잡담' 을
        관심 분야로 달고 있었고 한 명은 그게 1순위였다. 사람을 평가하는 화면처럼
        읽히지 않게 공들여 만든 자리다.
        """
        out = self._with_chat(skip_categories={"chat"})
        self.assertEqual([], [f for p in out["people"] for f in p["fields"]
                              if f["category"] == "chat"])

    def test_without_the_guard_chat_would_show_up(self):
        # 걸림이 실제로 무언가를 막고 있다는 것을 못박는다.
        out = self._with_chat()
        self.assertIn("chat", [f["category"] for f in self.rookie(out)["fields"]])

    def test_the_group_layer_ignores_chat_on_both_sides(self):
        """묶음 층에서 chat 은 개인과 방 양쪽 분모에서 빠진다.

        한쪽만 빼면 비율이 어긋나 lift 가 부풀거나 쪼그라든다.
        """
        out = self._with_chat(group_of=self.GROUPS.get,
                              group_label=lambda g: self.LABELS.get(g, g),
                              skip_categories={"chat"})
        fields = self.rookie(out)["fields"]
        self.assertEqual(["group:ai"], [f["category"] for f in fields],
                         "잡담 8건이 묶음 분모에 남으면 AI 쪽 비율이 눌려 사라진다")

    def test_skipping_a_category_does_not_move_other_lifts(self):
        # 잡담을 안 내는 것이 남의 관심 분야를 바꿀 이유는 없다 — 분모는 그대로다.
        plain = {p["nickname"]: [(f["category"], f["lift"]) for f in p["fields"]]
                 for p in self._with_chat()["people"]}
        guarded = {p["nickname"]: [(f["category"], f["lift"]) for f in p["fields"]]
                   for p in self._with_chat(skip_categories={"chat"})["people"]}
        for nick, rows in guarded.items():
            self.assertEqual([r for r in plain[nick] if r[0] != "chat"], rows, nick)


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
    """좁은 태그를 넓은 태그로도 찾게 한다 — **글자가 겹치는** 쪽.

    표(`config/tag_broader.json`)를 일부러 비워서 부른다. 실제 표를 읽으면 이
    시험들이 그 표의 내용에 따라 결과가 바뀐다 — '클로드' 에 'AI 모델' 이 붙는
    것은 맞는 동작이지만, 여기서 보려는 것은 글자 판정이다. 표 쪽은
    `BroaderTableTests` 가 본다.
    """

    def roll(self, threads, participants=None, **kw):
        return tags.rollup_parent_tags(threads, participants, broader={},
                                       short_parents=[], **kw)

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
        added = self.roll(threads)
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
        self.roll(threads)
        self.assertIn("온톨로지", threads[3]["tags"])

    def test_single_use_tag_cannot_be_a_parent(self):
        threads = [
            {"id": "t-1", "tags": ["대기 시스템"]},
            {"id": "t-2", "tags": ["대기 시스템 개편"]},
        ]
        self.assertEqual(self.roll(threads), [],
                         "한 번 쓰인 말이 부모가 되면 아무 말이나 부모가 된다")

    def test_short_tag_cannot_be_a_parent(self):
        threads = [
            {"id": "t-%d" % i, "tags": ["AI"]} for i in range(2)
        ] + [{"id": "t-9", "tags": ["AI 교육"]}]
        added = self.roll(threads)
        self.assertEqual(added, [], "'AI' 가 부모면 거의 모든 태그가 자식이 된다")

    def test_person_name_is_not_a_parent(self):
        threads = [
            {"id": "t-1", "tags": ["김종원"]},
            {"id": "t-2", "tags": ["김종원"]},
            {"id": "t-3", "tags": ["김종원 수정판"]},
        ]
        parts = {"participants": [{"nickname": "김종원(○○관)"}]}
        self.assertEqual(self.roll(threads, parts), [],
                         "이름 태그는 참여자 화면 몫이다")

    def test_grandparent_is_attached_too(self):
        threads = [
            {"id": "t-1", "tags": ["클로드"]}, {"id": "t-2", "tags": ["클로드"]},
            {"id": "t-3", "tags": ["클로드 코드"]}, {"id": "t-4", "tags": ["클로드 코드"]},
            {"id": "t-5", "tags": ["클로드코드 프로"]},
        ]
        self.roll(threads)
        self.assertEqual(set(threads[4]["tags"]),
                         {"클로드코드 프로", "클로드 코드", "클로드"})

    def test_running_twice_adds_nothing_new(self):
        threads = self._ontology()
        self.roll(threads)
        before = [list(th["tags"]) for th in threads]
        self.roll(threads)
        self.assertEqual([th["tags"] for th in threads], before)


class BroaderTableTests(unittest.TestCase):
    """글자가 겹치지 않는 상하위는 표(`config/tag_broader.json`)가 맡는다.

    글자 판정으로는 원리적으로 못 하는 몫이다 — '앱스스크립트' 가 '구글 워크스페이스'
    에 든다는 것도, 'AWS' 가 '클라우드' 라는 것도 글자에 단서가 없다. 실측
    2026-08-14: 부모를 하나도 못 얻은 1회짜리 태그가 843개였다.
    """

    TABLE = {"구글 워크스페이스": ["앱스스크립트", "clasp"],
             "AI 모델": ["Gemma 3 27B"],
             "AI": ["AI 모델"]}

    def _table(self, raw=None):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "tag_broader.json"
            p.write_text(json.dumps({"broader": raw or self.TABLE},
                                    ensure_ascii=False), encoding="utf-8")
            return tags.load_broader(p, aliases={})

    def test_tag_reaches_a_parent_it_shares_no_letter_with(self):
        threads = [{"id": "t-1", "tags": ["앱스스크립트"]}]
        added = tags.rollup_parent_tags(threads, broader=self._table())
        self.assertIn(("t-1", "구글 워크스페이스"), added)
        self.assertIn("앱스스크립트", threads[0]["tags"], "좁은 태그를 잃지 않는다")

    def test_table_parent_needs_no_prior_use(self):
        """넓은 태그가 아직 아무 보고서에도 없어도 붙는다.

        글자 판정의 `min_count` 방벽은 '한 번 쓰인 말이 부모가 되면 아무 말이나
        부모가 된다' 는 이유로 있다. 표는 사람이 적은 것이라 그 이유가 없고,
        새 입구를 세우는 것이 표의 몫이다.
        """
        threads = [{"id": "t-1", "tags": ["Gemma 3 27B"]}]
        tags.rollup_parent_tags(threads, broader=self._table())
        self.assertIn("AI 모델", threads[0]["tags"])

    def test_table_chain_is_followed(self):
        # 'Gemma 3 27B' → 'AI 모델' → 'AI'. 표끼리 이어지는 것도 올라간다.
        threads = [{"id": "t-1", "tags": ["Gemma 3 27B"]}]
        tags.rollup_parent_tags(threads, broader=self._table())
        self.assertIn("AI", threads[0]["tags"])

    def test_a_short_parent_from_the_table_is_allowed(self):
        # 글자 판정에서 'AI' 는 부모가 될 수 없다(min_len). 표는 사람 판단이므로 된다.
        threads = [{"id": "t-1", "tags": ["AI 모델"]}]
        tags.rollup_parent_tags(threads, broader=self._table())
        self.assertIn("AI", threads[0]["tags"])

    def test_a_cycle_in_the_table_does_not_hang(self):
        table = self._table({"가": ["나"], "나": ["가"]})
        threads = [{"id": "t-1", "tags": ["가"]}]
        tags.rollup_parent_tags(threads, broader=table)
        self.assertEqual({"가", "나"}, set(threads[0]["tags"]))

    def test_a_person_name_is_never_a_parent_even_from_the_table(self):
        table = self._table({"김종원": ["차량운행일지"]})
        threads = [{"id": "t-1", "tags": ["차량운행일지"]}]
        parts = {"participants": [{"nickname": "김종원(○○관)"}]}
        tags.rollup_parent_tags(threads, parts, broader=table)
        self.assertEqual(["차량운행일지"], threads[0]["tags"],
                         "이름 태그는 참여자 화면 몫이다")

    def test_the_broad_name_goes_through_the_alias_table(self):
        """표에 '구글시트' 라고 적어도 대표 표기 '구글 시트' 로 붙는다.

        안 그러면 색인에 '구글 시트' 와 '구글시트' 가 나란히 서서 태그가 둘로
        갈린다 — 통일표를 만든 이유가 그것이다.
        """
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "b.json"
            p.write_text(json.dumps({"broader": {"구글시트": ["삽입 수식"]}},
                                    ensure_ascii=False), encoding="utf-8")
            # 통일표의 열쇠는 fold 값이다(`load_aliases` 가 그렇게 만든다).
            table = tags.load_broader(
                p, aliases={tags.fold("구글시트"): "구글 시트"})
        threads = [{"id": "t-1", "tags": ["삽입 수식"]}]
        tags.rollup_parent_tags(threads, broader=table)
        self.assertIn("구글 시트", threads[0]["tags"])

    def test_missing_table_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual({}, tags.load_broader(Path(d) / "없다.json"))
            self.assertEqual([], tags.load_short_parents(Path(d) / "없다.json"))

    def test_a_two_letter_parent_from_the_table_catches_its_family(self):
        """두 글자 부모는 사람이 적었을 때만 쓴다.

        `min_len` 방벽은 **기계가 고른** 짧은 부모를 막으려고 있다 — 'AI' 가 아무
        태그나 빨아들이는 것. 사람이 적은 것은 판단이므로 예외로 둔다.

        실측 2026-08-14: '구글'(자식 29개)·'교육'(17)·'계정'(12)·'게임'(9) 처럼
        부모가 두 글자여서 막혀 있던 계열이 컸다 — 고립 태그 779 → 692.
        """
        threads = [{"id": "t-1", "tags": ["계정 공유"]},
                   {"id": "t-2", "tags": ["계정 전환"]}]
        added = tags.rollup_parent_tags(threads, broader={},
                                        short_parents=["계정"])
        self.assertEqual([("t-1", "계정"), ("t-2", "계정")], added)

    def test_without_the_table_a_two_letter_parent_is_refused(self):
        threads = [{"id": "t-1", "tags": ["계정 공유", "계정"]},
                   {"id": "t-2", "tags": ["계정 전환", "계정"]}]
        added = tags.rollup_parent_tags(threads, broader={}, short_parents=[])
        self.assertEqual([], added, "기계가 고른 두 글자 부모는 막혀 있어야 한다")

    def test_a_short_parent_needs_no_prior_use(self):
        # 아직 아무 보고서에도 없는 말도 부모가 된다 — 새 입구가 생긴다.
        threads = [{"id": "t-1", "tags": ["간편인증서"]}]
        tags.rollup_parent_tags(threads, broader={}, short_parents=["인증"])
        self.assertIn("인증", threads[0]["tags"])

    def test_a_short_parent_that_is_a_person_name_is_refused(self):
        threads = [{"id": "t-1", "tags": ["종원 수정판"]}]
        parts = {"participants": [{"nickname": "종원"}]}
        tags.rollup_parent_tags(threads, parts, broader={}, short_parents=["종원"])
        self.assertEqual(["종원 수정판"], threads[0]["tags"])

    def test_candidates_see_the_same_short_parents(self):
        # 붙이는 쪽과 알리는 쪽이 같은 판정을 봐야 한다 — 아니면 '이미 붙은 것'을
        # 후보로 또 알린다.
        threads = [{"id": "t-1", "tags": ["계정 공유"]}]
        self.assertEqual([], tags.broader_candidates(
            threads, {}, short_parents=["계정"]))
        self.assertEqual(["계정 공유"], [t for t, _ in tags.broader_candidates(
            threads, {}, short_parents=[])])

    def test_shipped_short_parents_are_all_short(self):
        """세 글자 이상은 여기가 아니라 broader 에 적는다 — 코드가 이미 잡는다."""
        for s in tags.load_short_parents():
            with self.subTest(tag=s):
                self.assertLess(len(tags.fold(s)), 3,
                                "'%s' 는 코드가 이미 부모로 쓴다" % s)

    def test_shipped_table_is_valid_and_does_not_name_people(self):
        table = tags.load_broader()
        self.assertTrue(table, "config/tag_broader.json 을 읽지 못했습니다")
        # 좁은 말이 두 부모를 가지면 어느 쪽이 붙을지 파일 순서에 달린다.
        raw = json.loads(tags.BROADER_PATH.read_text(encoding="utf-8"))["broader"]
        seen: dict[str, str] = {}
        for broad, narrows in raw.items():
            for n in narrows:
                key = tags.fold(n)
                prev = seen.get(key)
                self.assertIn(prev, (None, broad),
                              "'%s' 가 %s 와 %s 두 곳에 있습니다" % (n, prev, broad))
                seen[key] = broad

    def test_orphan_candidates_point_at_what_the_table_is_missing(self):
        threads = [{"id": "t-1", "tags": ["앱스스크립트", "혼자뿐인말"]},
                   {"id": "t-2", "tags": ["바이브코딩"]},
                   {"id": "t-3", "tags": ["바이브코딩"]}]
        rows = tags.broader_candidates(threads, self._table())
        names = [t for t, _ in rows]
        self.assertIn("혼자뿐인말", names)
        self.assertNotIn("앱스스크립트", names, "표로 부모를 얻은 것은 고립이 아니다")
        self.assertNotIn("바이브코딩", names, "두 번 쓰인 태그는 색인에 나온다")

    def test_orphan_candidates_leave_out_people_and_places(self):
        threads = [{"id": "t-1", "tags": ["김종원", "무지개노인복지관", "혼자뿐인말"]}]
        parts = {"participants": [{"nickname": "김종원"}]}
        rows = tags.broader_candidates(
            threads, {}, parts, places={tags.fold("무지개노인복지관")})
        self.assertEqual(["혼자뿐인말"], [t for t, _ in rows])


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
