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

test("queryTerms: 복수 '들'·'됐어' 같은 말끝도 뗀다", () => {
  assert.deepEqual(K.queryTerms("한글 문서 자동화는 어떤 도구들이 소개됐어?"),
                   ["한글", "문서", "자동화", "도구"]);
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

test("smartSearch: 말이 여럿이면 가장 많이 맞은 주제만 남긴다", () => {
  const r = K.smartSearch(THREADS, "한글 자동화 얘기 어디 있었지?", []);
  assert.deepEqual(r.threads.map((t) => t.id), ["t-1"]);
  assert.equal(r.partial, false);
  assert.equal(r.weak, false);
});

test("smartSearch: 다 맞는 주제가 없으면 partial 로 알린다", () => {
  const r = K.smartSearch(THREADS, "파이어베이스 마라톤", []);
  assert.deepEqual(r.threads.map((t) => t.id), ["t-3"]);
  assert.equal(r.partial, true);
});

test("smartSearch: 본문에서만 스친 말은 weak 로 알린다", () => {
  const thread = [{ id: "t-9", title: "모임 공지", summary: "", tags: [], participants: [],
    start_date: "2026-04-01", report: "마라톤 이야기가 잠깐 나왔다", ai_report: "" }];
  const r = K.smartSearch(thread, "마라톤", []);
  assert.deepEqual(r.threads.map((t) => t.id), ["t-9"]);
  assert.equal(r.weak, true);
});

test("smartSearch: 이름은 찾을 말이 아니라 사람 거르기로 쓴다", () => {
  const r = K.smartSearch(THREADS, "다라 파이어베이스", ["가나", "다라"]);
  assert.deepEqual(r.people, ["다라"]);
  assert.deepEqual(r.terms, ["파이어베이스"]);
  assert.deepEqual(r.threads.map((t) => t.id), ["t-3"]);
});

test("answerHtml: 머리말·굵게·목록만 살리고 나머지는 글자로 남긴다", () => {
  const esc = T.esc;
  const h = K.answerHtml("핵심은 **rhwp** 예요.\n\n**주의할 점**\n둘이 있어요.\n- 첫째\n- 둘째", esc);
  assert.equal(h, "<p>핵심은 <strong>rhwp</strong> 예요.</p>" +
    '<p class="ai-answer__sub">주의할 점</p><p>둘이 있어요.</p><ul><li>첫째</li><li>둘째</li></ul>');
  // '#' 제목으로 써도 머리말이 된다
  assert.match(K.answerHtml("## 써 본 반응\n좋았다", esc), /^<p class="ai-answer__sub">써 본 반응<\/p>/);
});

test("answerHtml: AI 답에 태그가 섞여도 새 태그가 생기지 않는다", () => {
  const h = K.answerHtml('**<img src=x onerror=alert(1)>** 와 [링크](javascript:x) 와 **짝 없는', T.esc);
  assert.doesNotMatch(h, /<img|<a /);
  assert.match(h, /<strong>&lt;img src=x onerror=alert\(1\)&gt;<\/strong>/);
  assert.match(h, /\[링크\]\(javascript:x\)/);   // 링크는 글자 그대로
  assert.doesNotMatch(h, /\*\*/);                  // 짝 없는 별표는 지운다
});

test("answerHtml: 백틱으로 감싼 명령어는 code 로", () => {
  assert.equal(K.answerHtml("`claude -p` 로 돌린다", T.esc), "<p><code>claude -p</code> 로 돌린다</p>");
});

test("answerHtml: 혼자 선 자리표 줄은 빈 자리가 되고, 문장 속 자리표는 글자다", () => {
  const h = K.answerHtml("설명.\n![[msg-000385]]\n![[link:msg-000006]]\n문장 ![[msg-1]] 속", T.esc);
  assert.match(h, /<div class="md-anchor" data-anchor="msg-000385"><\/div>/);
  assert.match(h, /<div class="md-link-anchor" data-link-anchor="msg-000006"><\/div>/);
  assert.equal((h.match(/md-anchor/g) || []).length, 1);
});

test("answerHtml: '확인할 점' 머리말부터 끝까지를 검증 상자로 떼어 놓는다", () => {
  const h = K.answerHtml("바로 답.\n\n**확인할 점**\n\n- 하나\n- 둘", T.esc);
  assert.match(h, /^<p>바로 답\.<\/p><div class="ai-answer__check">/);
  assert.match(h, /🔎 확인할 점/);
  assert.match(h, /<ul><li>하나<\/li><li>둘<\/li><\/ul><\/div>$/);
  // 뒤에 다른 머리말이 오면 상자는 거기서 닫힌다
  const h2 = K.answerHtml("**확인할 점**\n- 하나\n\n**덧붙임**\n끝", T.esc);
  assert.match(h2, /<\/ul><\/div><p class="ai-answer__sub">덧붙임<\/p>/);
  // 없으면 상자도 없다
  assert.doesNotMatch(K.answerHtml("**처음 소개**\n본문", T.esc), /ai-answer__check/);
});

test("verifyResultHtml: 출처는 http(s) 주소만 링크로, 글 속 태그는 글자로", () => {
  const h = K.verifyResultHtml({ body: "대체로 맞아요 <b>x</b>\n\n**✅ 확인됨**\n- 그대로예요 (출처 1)",
    sources: [{ n: 1, url: "https://a.example/page" }, { n: 2, url: "javascript:alert(1)" }],
    opened: 1, total: 3, finishedAt: "2026-10-30T12:05:00Z" }, T.esc);
  assert.match(h, /<a href="https:\/\/a\.example\/page" target="_blank" rel="noopener noreferrer">/);
  assert.doesNotMatch(h, /javascript:/);
  assert.match(h, /&lt;b&gt;x&lt;\/b&gt;/);
  assert.match(h, /찾은 출처 3곳 중 1곳 열림/);
  assert.match(h, /실제로 열어 본 출처만/);
});
