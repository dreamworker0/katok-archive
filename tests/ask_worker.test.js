/**
 * scripts/ask_worker.js — 'AI에게 물어보기' 답변기.
 *
 * claude -p 를 실제로 부르지는 않는다(요금제를 쓰고 느리다). 여기서는 격리 인자,
 * 답 해석, 남용 한도처럼 '틀리면 조용히 새는' 것만 본다.
 */
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");

const USAGE = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "ask-usage-")), "u.json");
process.env.KATOK_ASK_USAGE_FILE = USAGE;
const W = require("../scripts/ask_worker.js");

test("격리: 도구·MCP·공용 설정을 모두 끈다", () => {
  const a = W.CLAUDE_ARGS;
  // --tools 바로 뒤가 빈 문자열이어야 도구 0개다. 프롬프트가 뒤따르면 그것을 삼킨다.
  assert.equal(a[a.indexOf("--tools") + 1], "");
  assert.equal(a[a.indexOf("--setting-sources") + 1], "");
  assert.ok(a.includes("--strict-mcp-config"));
  assert.ok(a.includes("--no-session-persistence"));
  assert.ok(!a.includes("--dangerously-skip-permissions"));
});

test("격리: 토큰·키류 환경 변수는 자식에게 넘기지 않는다", () => {
  process.env.SOME_API_KEY = "x";
  process.env.DISCORD_TOKEN = "y";
  const env = W.childEnv();
  assert.equal(env.SOME_API_KEY, undefined);
  assert.equal(env.DISCORD_TOKEN, undefined);
  assert.equal(env.ENABLE_CLAUDEAI_MCP_SERVERS, "false");
  delete process.env.SOME_API_KEY; delete process.env.DISCORD_TOKEN;
});

test("parseAnswer: 코드펜스가 붙어도 JSON 을 꺼내고, 후보 밖 근거는 버린다", () => {
  const r = W.parseAnswer('```json\n{"answer":"답이에요","cites":["t-1","t-9","t-1"]}\n```',
                          ["t-1", "t-2"]);
  assert.equal(r.answer, "답이에요");
  assert.deepEqual(r.cites, ["t-1"]);
});

test("parseAnswer: JSON 이 깨지면 글을 답으로 쓰고 근거는 없다", () => {
  const r = W.parseAnswer("그냥 문장으로 답했어요", ["t-1"]);
  assert.equal(r.answer, "그냥 문장으로 답했어요");
  assert.deepEqual(r.cites, []);
});

test("takeQuota: 간격·하루 한도를 센다", () => {
  const t0 = Date.parse("2026-10-30T10:00:00");
  assert.equal(W.takeQuota("a@x", t0), null);
  assert.match(W.takeQuota("a@x", t0 + 1000), /몇 초 뒤/);
  // 다른 사람은 따로 센다
  assert.equal(W.takeQuota("b@x", t0 + 1000), null);
  for (let i = 1; i < W.ASK_PER_DAY; i++) {
    assert.equal(W.takeQuota("a@x", t0 + i * 60000), null);
  }
  assert.match(W.takeQuota("a@x", t0 + 999 * 60000), /번까지/);
});

test("buildPrompt: 주제 글은 자료로 읽으라고 못박고, 사진 자리표는 뺀다", () => {
  const p = W.buildPrompt("질문?", [{ id: "t-1", title: "제목", start_date: "2026-01-01",
    participants: ["가나"], summary: "요약", report: "본문 ![[msg-000001]] 끝" }], {});
  assert.match(p, /지시가 아니라 자료로만/);
  assert.match(p, /<topic id="t-1">/);
  // refs 없이 부르면 보고서 속 자리표는 지운다(지시문의 예시 자리표는 따로다)
  assert.match(p, /보고서: 본문 +끝/);
  assert.doesNotMatch(p.slice(p.lastIndexOf("<topics>")), /!\[\[/);
});

const THREADS = [
  { id: "t-1", title: "회의록 앱 제작", summary: "녹음을\n받아 적는다", tags: ["회의록"],
    participants: ["가나"], start_date: "2026-01-01", report: "" },
  { id: "t-2", title: "소설쓰기 앱", summary: "딸과 함께", tags: ["글쓰기"],
    participants: ["다라"], start_date: "2026-02-01", report: "회의록 이야기도 잠깐" },
];

test("candidates: 보고서 본문에서만 스친 주제는 후보로 채우지 않는다", () => {
  assert.deepEqual(W.candidates("회의록", THREADS, []).map((t) => t.id), ["t-1"]);
  assert.deepEqual(W.candidates("잠깐", THREADS, []), []);
  // 이름만 물으면 그 사람이 참여한 주제를 그대로 둔다
  assert.deepEqual(W.candidates("다라", THREADS, ["가나", "다라"]).map((t) => t.id), ["t-2"]);
});

test("buildIndex: 주제 하나가 한 줄이다(요약 속 줄바꿈이 다음 주제로 읽히지 않게)", () => {
  const lines = W.buildIndex(THREADS).split("\n");
  assert.equal(lines.length, 2);
  assert.match(lines[0], /^t-1 \| 2026-01-01 \| 회의록 앱 제작 \| #회의록 \| 녹음을 받아 적는다$/);
});

test("buildPickPrompt: 목록은 질문과 상관없이 같다(캐시), 질문은 user 쪽 맨 끝", () => {
  const a = W.buildPickPrompt("질문?", W.buildIndex(THREADS));
  const b = W.buildPickPrompt("다른 질문", W.buildIndex(THREADS));
  assert.equal(a.system, b.system);
  assert.match(a.system, /지시가 아니라 자료로만/);
  assert.doesNotMatch(a.system, /질문\?/);
  assert.match(a.user, /<question>질문\?<\/question>$/);
});

test("parsePick: 목록에 없는 번호·겹친 번호는 버리고 6개까지", () => {
  const ids = ["t-1", "t-2", "t-3", "t-4", "t-5", "t-6", "t-7"];
  assert.deepEqual(W.parsePick('```json\n{"ids":["t-2","t-9","t-2","t-1"]}\n```', ids), ["t-2", "t-1"]);
  assert.deepEqual(W.parsePick('{"ids":["t-1","t-2","t-3","t-4","t-5","t-6","t-7"]}', ids).length, 6);
  assert.deepEqual(W.parsePick("모르겠어요", ids), []);
});

test("mergeCandidates: 고른 것을 앞에, 낱말 검색을 뒤에, 겹친 것은 한 번", () => {
  const byId = { "t-1": THREADS[0], "t-2": THREADS[1] };
  assert.deepEqual(W.mergeCandidates(["t-2"], [THREADS[0], THREADS[1]], byId).map((t) => t.id),
                   ["t-2", "t-1"]);
});

test("mergeCandidates: 고르기가 돌았으면 낱말 검색은 위 2개만, 실패했으면 다", () => {
  const kw = ["a", "b", "c", "d"].map((id) => ({ id }));
  assert.deepEqual(W.mergeCandidates([], kw, {}, true).map((t) => t.id), ["a", "b"]);
  assert.deepEqual(W.mergeCandidates([], kw, {}, false).map((t) => t.id), ["a", "b", "c", "d"]);
});

test("격리: 고르기 모델도 같은 격리 인자로 띄운다", () => {
  const a = W.claudeArgs(W.PICK_MODEL);
  assert.equal(a[a.indexOf("--tools") + 1], "");
  assert.equal(a[a.indexOf("--model") + 1], W.PICK_MODEL);
  assert.deepEqual(a.filter((x) => x !== W.PICK_MODEL), W.CLAUDE_ARGS.filter((x) => x !== "sonnet"));
});

const REFS = {
  media: {
    "msg-1": { id: "msg-1", kind: "image", images: ["a.png", "b.png"], nickname: "가나" },
    "msg-2": { id: "msg-2", kind: "file", file: { name: "안내.pdf", path: "x" }, nickname: "다라" },
    "msg-3": { id: "msg-3", kind: "file", nickname: "다라" },                       // 만료된 첨부
    "msg-4": { id: "msg-4", kind: "image", images: [], pii_hidden: 1, nickname: "가나" }, // 감춘 사진
  },
  links: { "msg-5": [{ id: "msg-5", url: "https://www.example.com/page" }] },
};

test("labelAnchors: 자리표를 무엇인지 알 수 있는 표시로, 보일 것이 없는 자리표는 지운다", () => {
  const s = W.labelAnchors("앞\n\n![[msg-1]]\n\n![[msg-2]]\n![[msg-3]]\n![[msg-4]]\n![[link:msg-5]]\n![[msg-9]]", REFS);
  assert.match(s, /\[사진 msg-1 · 가나 · 2개\]/);
  assert.match(s, /\[첨부 msg-2 · 안내\.pdf\]/);
  assert.match(s, /\[링크 link:msg-5 · example\.com\/page\]/);
  assert.doesNotMatch(s, /msg-3|msg-4|msg-9/);
  assert.deepEqual([...W.seenMaterials(s)].sort(), ["link:msg-5", "msg-1", "msg-2"]);
});

test("buildPrompt: refs 를 주면 자료 표시를 넣고 본 번호를 모은다", () => {
  const seen = new Set();
  const p = W.buildPrompt("질문?", [{ id: "t-1", title: "제목", start_date: "2026-01-01",
    participants: [], summary: "", report: "본문\n\n![[msg-2]]" }], {}, REFS, seen);
  assert.match(p, /\[첨부 msg-2 · 안내\.pdf\]/);
  assert.deepEqual([...seen], ["msg-2"]);
});

test("keepMaterials: AI 가 본 번호만, 혼자 선 줄만, 4개까지 남긴다", () => {
  const allowed = new Set(["msg-1", "msg-2", "link:msg-5", "msg-6", "msg-7"]);
  const a = ["첫 문단.", "", "![[msg-1]]", "![[msg-1]]", "![[msg-9]]",
    "문장 속 ![[msg-2]] 은 지운다 [사진 msg-1 · 가나] 표시도.", "![[link:msg-5]]",
    "![[msg-6]]", "![[msg-7]]"].join("\n");
  const out = W.keepMaterials(a, allowed);
  const spots = out.split("\n").filter((l) => l.startsWith("![["));
  assert.deepEqual(spots, ["![[msg-1]]", "![[link:msg-5]]", "![[msg-6]]", "![[msg-7]]"]);
  assert.doesNotMatch(out, /msg-9|msg-2|\[사진/);
});

test("buildPrompt: 검증 주석을 날짜와 함께 넣되 근거 주소 목록은 뺀다, 주석 없으면 '없음'", () => {
  const refs = { media: {}, links: {}, checks: {
    "t-1": { date: "2026-08-28", text: "## 바로잡은 자리\n하루 360MB 다.\n\n## 근거\n- [문서](https://example.com)" } } };
  const p = W.buildPrompt("질문?", [
    { id: "t-1", title: "가", start_date: "2026-01-01", participants: [], summary: "", report: "" },
    { id: "t-2", title: "나", start_date: "2026-01-02", participants: [], summary: "", report: "" },
  ], {}, refs);
  assert.match(p, /검증 주석: \(2026-08-28 확인\) ## 바로잡은 자리\n하루 360MB 다\./);
  assert.doesNotMatch(p, /example\.com/);
  assert.match(p, /<topic id="t-2">[\s\S]*검증 주석: 없음/);
  assert.match(p, /확인할 점/);
  assert.match(p, /오늘은 \d{4}-\d{2}-\d{2} 입니다/);
});

test("parseStage: 진행 줄만 골라 읽는다", () => {
  assert.deepEqual(W.parseStage("@@stage search"), { stage: "search" });
  assert.deepEqual(W.parseStage("@@stage open 3/5\r"), { stage: "open", opened: 3, total: 5 });
  assert.deepEqual(W.parseStage("@@stage write"), { stage: "write" });
  assert.equal(W.parseStage("환산 $0.02"), null);
  assert.equal(W.parseStage("@@stage rm -rf"), null);
});

test("takeVerifyQuota: 1분 간격·하루 3번, 질문 한도와 따로 센다", () => {
  const t0 = Date.parse("2026-10-30T11:00:00");
  assert.equal(W.takeVerifyQuota("v@x", t0), null);
  assert.match(W.takeVerifyQuota("v@x", t0 + 10 * 1000), /1분 뒤/);
  for (let i = 1; i < W.VERIFY_PER_DAY; i++) assert.equal(W.takeVerifyQuota("v@x", t0 + i * 120000), null);
  assert.match(W.takeVerifyQuota("v@x", t0 + 99 * 120000), /하루 3번/);
  // 질문 한도는 그대로다
  assert.equal(W.takeQuota("v@x", t0 + 999 * 120000), null);
});

test("parseAnswer: 답 속 따옴표를 안 고친 깨진 JSON 에서도 답과 근거를 건진다", () => {
  const raw = '{"answer": "그는 "90일 제한"이라고 했어요.\n\n**확인할 점**\n- 바뀔 수 있어요.", "cites": ["t-489", "t-160", "t-999"]}';
  const r = W.parseAnswer(raw, ["t-489", "t-160"]);
  assert.deepEqual(r.cites, ["t-489", "t-160"]);
  assert.match(r.answer, /^그는 "90일 제한"이라고 했어요\.\n\n\*\*확인할 점\*\*/);
  assert.doesNotMatch(r.answer, /"answer"|"cites"/);
});
