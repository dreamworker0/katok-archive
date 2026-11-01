// 밤 갱신 공백 알림 — missed_run.js.
//
// 왜 검사하는가: 이 코드는 갱신이 빠진 드문 날에만 의미 있게 돈다. 잘못 고쳐도
// 평소에는 아무 일도 없어 보이고, 정작 갱신이 빠진 날 조용하다. 반대로 헛알림이
// 잦으면 그 채널은 곧 읽지 않는 채널이 되어 진짜 실패 알림까지 묻힌다.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const mr = require("../scripts/missed_run.js");

const CFG = { url: "https://discord.com/api/webhooks/1/abc", on: ["failed"] };
const quiet = () => {};
const H = 3600000;
const NOW = Date.parse("2026-11-02T03:00:00+09:00");

function tmpDir(prefix) {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}
function tmpState() {
  return path.join(tmpDir("missed-"), "missed-run-alert.json");
}
function lastRunAgo(hours, extra) {
  return { finishedAt: new Date(NOW - hours * H).toISOString(), status: "ok", ...extra };
}
function opts(file, sent, extra) {
  return {
    file, now: NOW, running: false, log: null, host: "pc", cfg: CFG, say: quiet,
    send: async (cfg, text) => { sent.push(text); }, ...extra,
  };
}

test("정상인 날의 간격(25시간)은 알리지 않는다", () => {
  const v = mr.judge({ lastRun: lastRunAgo(25), now: NOW, running: false, alertedFor: null });
  assert.equal(v.missed, false);
  assert.equal(v.why, "fresh");
});

test("26시간을 넘으면 알린다", () => {
  const v = mr.judge({ lastRun: lastRunAgo(27), now: NOW, running: false, alertedFor: null });
  assert.equal(v.missed, true);
  assert.equal(v.notify, true);
});

test("지금 돌고 있으면 기록이 오래돼도 말하지 않는다 — 따라잡기 중이다", () => {
  const v = mr.judge({ lastRun: lastRunAgo(72), now: NOW, running: true, alertedFor: null });
  assert.equal(v.missed, false);
  assert.equal(v.why, "running");
});

test("기록이 아예 없어도 알린다", () => {
  const v = mr.judge({ lastRun: null, now: NOW, running: false, alertedFor: null });
  assert.equal(v.notify, true);
  assert.equal(v.key, "none");
});

test("같은 공백은 한 번만 알리고, 갱신이 한 번 돌면 다음 공백은 다시 알린다", async () => {
  const file = tmpState();
  const sent = [];
  const lr = lastRunAgo(30);
  assert.equal((await mr.checkOnce(lr, opts(file, sent))).sent, true);
  assert.equal((await mr.checkOnce(lr, opts(file, sent))).sent, false);
  assert.equal(sent.length, 1);

  const next = lastRunAgo(28, { finishedAt: new Date(NOW - 28 * H + 60000).toISOString() });
  assert.equal((await mr.checkOnce(next, opts(file, sent))).sent, true);
  assert.equal(sent.length, 2);
});

test("보내기에 실패하면 적지 않는다 — 다음 확인에서 다시 보낸다", async () => {
  const file = tmpState();
  const lr = lastRunAgo(30);
  const r = await mr.checkOnce(lr, opts(file, [], { send: async () => { throw new Error("HTTP 500"); } }));
  assert.equal(r.sent, false);
  assert.equal(fs.existsSync(file), false);

  const sent = [];
  assert.equal((await mr.checkOnce(lr, opts(file, sent))).sent, true);
});

test("failed 알림을 꺼 둔 설정이면 보내지 않는다", async () => {
  const sent = [];
  const r = await mr.checkOnce(lastRunAgo(30), opts(tmpState(), sent, { cfg: { url: CFG.url, on: ["ok"] } }));
  assert.equal(r.sent, false);
  assert.equal(sent.length, 0);
});

test("dry-run 은 보내지도 적지도 않는다", async () => {
  const file = tmpState();
  const sent = [];
  await mr.checkOnce(lastRunAgo(30), opts(file, sent, { dry: true }));
  assert.equal(sent.length, 0);
  assert.equal(fs.existsSync(file), false);
});

test("알림에 몇 시간째인지, 마지막 상태, 어디를 열지가 실린다", () => {
  const lr = lastRunAgo(30, { status: "failed", lastStep: "테스트" });
  const v = mr.judge({ lastRun: lr, now: NOW, running: false, alertedFor: null });
  const text = mr.buildMissedNotice(v, lr, { name: "daily-20261031.log", mtime: NOW - 30 * H }, "pc");
  assert.match(text, /30시간째/);
  assert.match(text, /failed @ 테스트/);
  assert.match(text, /daily-20261031\.log/);
  assert.match(text, /카톡아카이브-일일갱신/);
});

test("잠금 파일이 없으면 돌고 있지 않은 것이다", () => {
  assert.equal(mr.isRunning(path.join(tmpDir("lock-"), "run_daily.lock")), false);
});

test("가장 최근 일일 로그를 고른다 — 다른 로그는 무시한다", () => {
  const dir = tmpDir("logs-");
  for (const n of ["daily-20261030.log", "daily-20261031.log", "refresh-20261101.log"]) {
    fs.writeFileSync(path.join(dir, n), "x");
  }
  assert.equal(mr.latestDailyLog(dir).name, "daily-20261031.log");
  assert.equal(mr.latestDailyLog(tmpDir("empty-")), null);
});
