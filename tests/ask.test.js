/**
 * web/ask.js — 물어보기 칸이 질문을 찾을 말로 바꾸고 주제를 고르는 순수 함수.
 *
 * 화면은 tests/test_ui_contract.py 와 미리보기로 본다. 여기서는 '무엇이 걸리고
 * 무엇이 안 걸리나' 만 본다 — 실측에서 틀렸던 것들을 그대로 적어 두었다.
 */
const test = require("node:test");
const assert = require("node:assert");
const K = require("../web/ask.js");
const T = require("../web/text.js");

const THREADS = [
  { id: "t-1", title: "한글 표 자동화 도구 공유", summary: "hwpx 표를 채우는 도구",
    tags: ["한글", "자동화"], participants: ["가나"], start_date: "2026-01-01",
    report: "", ai_report: "" },
  { id: "t-2", title: "제미나이 3 성능 비교", summary: "두 모델을 나란히 돌림",
    tags: ["제미나이"], participants: ["다라"], start_date: "2026-02-01",
    report: "자동화 이야기도 잠깐 나왔다", ai_report: "" },
  { id: "t-3", title: "파이어베이스 요금", summary: "Blaze 요금제로 옮긴 이야기",
    tags: ["파이어베이스"], participants: ["가나", "다라"], start_date: "2026-03-01",
    report: "", ai_report: "" },
];

test("queryTerms: 조사·묻는 말끝·흔한 말을 떼고 남긴다", () => {
  assert.deepEqual(K.queryTerms("한글 자동화 얘기 어디 있었지?"), ["한글", "자동화"]);
  assert.deepEqual(K.queryTerms("파이어베이스는 요금이 얼마였지"), ["파이어베이스", "요금"]);
  // 동사 끝: '비교한' → '비교'
  assert.deepEqual(K.queryTerms("제미나이 비교한 거"), ["제미나", "비교"]);
});

test("queryTerms: 두 글자 '글을'·'님이' 는 묻는 말이라 버린다", () => {
  assert.deepEqual(K.queryTerms("내 글을 내리고 싶어요"), []);
  assert.deepEqual(K.queryTerms("님이 올린"), []);
});

test("queryTerms: 명사 끝의 '지' 는 말끝이 아니다", () => {
  assert.deepEqual(K.queryTerms("이미지 메시지"), ["이미지", "메시지"]);
});

test("rankThreads: 제목에 맞은 주제가 본문에만 스친 주제보다 앞선다", () => {
  const rows = K.rankThreads(THREADS, ["자동화"], []);
  assert.equal(rows[0].thread.id, "t-1");
  // t-2 는 보고서 본문에서만 걸렸다 — 남기되 strong 은 0 이다(화면이 따로 다룬다).
  const t2 = rows.find((r) => r.thread.id === "t-2");
  assert.equal(t2.strong, 0);
});

test("rankThreads: 사람 이름이 있으면 그 사람이 참여한 주제만", () => {
  const rows = K.rankThreads(THREADS, [], ["다라"]);
  assert.deepEqual(rows.map((r) => r.thread.id).sort(), ["t-2", "t-3"]);
});

test("rankThreads: 아무것도 안 맞으면 빈 목록", () => {
  assert.deepEqual(K.rankThreads(THREADS, ["마라톤"], []), []);
});

test("matchGuides: 말 경계를 넘어 걸리지 않는다('한글 자동화' 는 '글자' 가 아니다)", () => {
  const list = K.guides(3);
  assert.deepEqual(K.matchGuides("한글 자동화 얘기", list), []);
  assert.equal(K.matchGuides("글자를 크게 하려면?", list)[0].id, "font");
  // 띄어 쓴 열쇠말은 붙여 써도 걸린다.
  assert.equal(K.matchGuides("홈화면에 깔려면", list)[0].id, "install");
});

test("guides: 태그 개수 한도는 넘겨받은 값을 쓴다", () => {
  const tags = K.guides(7).find((g) => g.id === "tags");
  assert.match(tags.a, /최대 7개/);
});

test("tagHits: 이어진 말을 붙여 태그를 찾고, 말 경계는 넘지 않는다", () => {
  const tags = [{ tag: "앱 제작", count: 9 }, { tag: "글자", count: 2 }, { tag: "파이어베이스", count: 5 }];
  assert.deepEqual(K.tagHits("앱 제작 얘기 찾아줘", tags, T.tagFold).map((r) => r.tag), ["앱 제작"]);
  assert.deepEqual(K.tagHits("한글 자동화", tags, T.tagFold), []);
  assert.deepEqual(K.tagHits("파이어베이스는 비싸?", tags, T.tagFold).map((r) => r.tag), ["파이어베이스"]);
});

test("isHowTo: 사용법을 묻는 말투", () => {
  assert.equal(K.isHowTo("글자를 크게 하려면?"), true);
  assert.equal(K.isHowTo("파이어베이스 요금"), false);
});
