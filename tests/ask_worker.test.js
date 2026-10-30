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
  assert.doesNotMatch(p, /!\[\[/);
});
