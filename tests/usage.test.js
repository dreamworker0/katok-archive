/* 사용 통계 — 화면이 남기는 기록을 합치는 순수 함수와 밤마다 접는 스크립트.
 *
 * 화면(web/usage.js)과 PC(scripts/usage_rollup.js)가 같은 summarize 를 쓴다. 오늘 몫은
 * 화면이, 지난 날 몫은 PC 가 세므로 둘이 다르게 세면 어제와 오늘 숫자가 어긋난다.
 */
const test = require("node:test");
const assert = require("node:assert");
const U = require("../web/usage.js");
const { rollup } = require("../scripts/usage_rollup.js");

test("날짜는 한국 시각으로 자른다", () => {
  // UTC 2026-10-31 15:30 = KST 2026-11-01 00:30
  assert.strictEqual(U.dayOf(Date.UTC(2026, 9, 31, 15, 30)), "2026-11-01");
  assert.strictEqual(U.dayOf(Date.UTC(2026, 9, 31, 14, 59)), "2026-10-31");
  assert.strictEqual(U.addDays("2026-11-01", -1), "2026-10-31");
  assert.strictEqual(U.addDays("2026-12-31", 1), "2027-01-01");
});

test("검색어는 공백을 접고 두 글자 미만은 버린다", () => {
  assert.strictEqual(U.normTerm("  한글   자동화 "), "한글 자동화");
  assert.strictEqual(U.normTerm("Firebase"), "firebase");
  assert.strictEqual(U.normTerm("가"), "");
  assert.strictEqual(U.normTerm("가".repeat(60)).length, 40);
});

test("검색어: 이어 친 앞부분은 같은 검색으로 본다", () => {
  assert.ok(U.sameSearch("다온", "다온가 최근에 공유한 사회복지"));
  assert.ok(U.sameSearch("뭐야", "뭐야?"));
  assert.ok(U.sameSearch("사회복지 전공", "사회복지"));     // 지워 가는 중
  assert.ok(U.sameSearch("다온갗", "다온가초"));            // 한글 끝 글자가 바뀌는 중
  assert.ok(!U.sameSearch("요금", "요리"));
  assert.ok(!U.sameSearch("한글 자동화", "엑셀"));
});

test("검색어: 멈출 때마다가 아니라 다 친 말 하나만 센다", () => {
  const sent = [];
  const t = U.SearchTracker((q) => sent.push(q));
  // 2026-11-01 실제로 쌓인 순서 — 생각하며 멈춘 곳마다 따로 세던 것
  ["다온", "다온가 최근에 공유한 사회복지", "다온가 최근에 공유한 사회복지 전공",
   "다온가 최근에 공유한 사회복지 전공 관련 내용이 뭐야"].forEach((q) => t.note(q));
  assert.deepStrictEqual(sent, []);
  t.note("다온가 최근에 공유한 사회복지 전공 관련 내용이 뭐야?");
  t.commit();                                               // Enter
  assert.deepStrictEqual(sent, ["다온가 최근에 공유한 사회복지 전공 관련 내용이 뭐야?"]);
  t.commit();                                               // 이어서 창을 떠남
  assert.strictEqual(sent.length, 1);
});

test("검색어: 다른 말로 바꾸면 앞의 것을 보내고, 비우면 같은 말도 다시 센다", () => {
  const sent = [];
  const t = U.SearchTracker((q) => sent.push(q));
  t.note("요금"); t.note("한글 자동화");
  assert.deepStrictEqual(sent, ["요금"]);
  t.clear();
  assert.deepStrictEqual(sent, ["요금", "한글 자동화"]);
  t.note("요금"); t.commit();
  assert.deepStrictEqual(sent, ["요금", "한글 자동화", "요금"]);
  t.note(""); t.commit();                                   // 한 글자로 지운 때는 보낼 것 없음
  assert.strictEqual(sent.length, 3);
});

test("하루 합계: 방문자는 사람 수, 이메일은 남기지 않는다", () => {
  const r = U.summarize([
    { type: "visit", by: "a@x.com" }, { type: "visit", by: "a@x.com" },
    { type: "visit", by: "b@x.com" },
    { type: "view", key: "timeline" }, { type: "view", key: "timeline" },
    { type: "view", key: "stats" },
    { type: "ai", key: "ask" },
    { type: "search", key: "요금" }, { type: "search", key: "요금" },
    { type: "search", key: "한글" },
  ]);
  assert.strictEqual(r.visits, 3);
  assert.strictEqual(r.visitors, 2);
  assert.deepStrictEqual(r.views, { timeline: 2, stats: 1 });
  assert.deepStrictEqual(r.ai, { ask: 1 });
  assert.strictEqual(r.searches, 3);
  assert.deepStrictEqual(r.terms, [{ t: "요금", n: 2 }, { t: "한글", n: 1 }]);
  assert.ok(!JSON.stringify(r).includes("@x.com"));
});

test("기간 합계는 빈 날도 0 으로 채워 그린다", () => {
  const days = {
    "2026-10-30": U.summarize([{ type: "visit", by: "a" }, { type: "search", key: "요금" }]),
    "2026-11-01": U.summarize([{ type: "visit", by: "a" }, { type: "visit", by: "b" },
                               { type: "search", key: "요금" }, { type: "search", key: "한글" }]),
  };
  const t = U.combine(days, "2026-10-30", "2026-11-01");
  assert.deepStrictEqual(t.series.map((x) => x.visits), [1, 0, 2]);
  assert.strictEqual(t.visits, 3);
  assert.strictEqual(t.visitorDays, 3);
  assert.deepStrictEqual(t.terms[0], { t: "요금", n: 2 });
});

test("접기: 오늘 것은 두고 지난 날만 접는다", () => {
  const ev = [
    { id: "1", type: "visit", day: "2026-10-31", by: "a" },
    { id: "2", type: "view", day: "2026-10-31", key: "tags" },
    { id: "3", type: "visit", day: "2026-11-01", by: "a" },
  ];
  const r = rollup(ev, null, "2026-11-01");
  assert.deepStrictEqual(r.deleteIds, ["1", "2"]);
  assert.deepStrictEqual(r.folded, ["2026-10-31"]);
  assert.strictEqual(r.doc.days["2026-10-31"].visits, 1);
  assert.ok(!r.doc.days["2026-11-01"]);
  assert.strictEqual(r.doc.through, "2026-10-31");
});

test("접기: 이미 접은 날은 다시 세지 않고 남은 원본만 지운다", () => {
  const cur = { days: { "2026-10-31": U.summarize([{ type: "visit", by: "a" }]) } };
  const r = rollup([{ id: "9", type: "visit", day: "2026-10-31", by: "b" }], cur, "2026-11-01");
  assert.deepStrictEqual(r.folded, []);
  assert.deepStrictEqual(r.deleteIds, ["9"]);
  assert.strictEqual(r.doc.days["2026-10-31"].visits, 1);
});

test("접기: 아주 오래된 합계는 버린다", () => {
  const cur = { days: { "2020-01-01": { visits: 1 }, "2026-10-01": { visits: 2 } } };
  const r = rollup([], cur, "2026-11-01");
  assert.deepStrictEqual(Object.keys(r.doc.days), ["2026-10-01"]);
});
