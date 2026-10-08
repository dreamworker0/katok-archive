// 관리자 명단 변화 알림 — admin_alert.js.
//
// 왜 검사하는가: 이 코드는 관리자가 바뀌는 드문 날에만 의미 있게 돈다. 잘못 고쳐도
// 평소에는 아무 일도 없어 보이고, 정작 누가 몰래 관리자가 된 날 조용하다.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const aa = require("../scripts/admin_alert.js");

const CFG = { url: "https://discord.com/api/webhooks/1/abc", on: ["failed"] };
const quiet = () => {};

function tmpRoster() {
  return path.join(fs.mkdtempSync(path.join(os.tmpdir(), "roster-")), "admin-roster.json");
}

function fakeDocs(map) {
  return Object.keys(map).map((id) => ({ id, data: () => map[id] }));
}

test("이메일은 앞 두 글자와 도메인만 남긴다", () => {
  assert.equal(aa.maskEmail("someone@example.org"), "so***@example.org");
  assert.equal(aa.maskEmail("a@b.c"), "a***@b.c");
  assert.equal(aa.maskEmail("not-an-email"), "***");
});

test("첫 실행은 기준만 잡고 알리지 않는다", async () => {
  const file = tmpRoster();
  let sent = 0;
  const r = await aa.checkRoster({ "a@x.org": {} },
    { file, cfg: CFG, send: async () => { sent++; }, say: quiet });
  assert.equal(r.first, true);
  assert.equal(sent, 0);
  assert.ok(fs.existsSync(file));
});

test("관리자가 늘면 알리고, 이메일 원문은 싣지 않는다", async () => {
  const file = tmpRoster();
  await aa.checkRoster({ "boss@x.org": {} }, { file, cfg: CFG, say: quiet, send: async () => {} });

  let text = "";
  const cur = aa.rosterFrom(fakeDocs({
    "boss@x.org": { role: "admin" },
    "intruder@evil.org": { role: "admin", googleName: "누군가", roleChangedBy: "boss@x.org" },
  }));
  const r = await aa.checkRoster(cur,
    { file, cfg: CFG, say: quiet, host: "PC", send: async (_c, t) => { text = t; } });

  assert.deepEqual(r.added, ["intruder@evil.org"]);
  assert.equal(r.sent, true);
  assert.match(text, /관리자 추가: in\*\*\*@evil\.org \(누군가\)/);
  assert.ok(!text.includes("intruder@"), "이메일 원문이 알림에 들어갔다");
  assert.ok(!text.includes("boss@"), "처리한 사람 이메일 원문이 알림에 들어갔다");
});

test("관리자가 줄어도 알린다", async () => {
  const file = tmpRoster();
  await aa.checkRoster({ "a@x.org": {}, "b@x.org": {} }, { file, cfg: CFG, say: quiet, send: async () => {} });
  let text = "";
  const r = await aa.checkRoster({ "a@x.org": {} },
    { file, cfg: CFG, say: quiet, send: async (_c, t) => { text = t; } });
  assert.deepEqual(r.removed, ["b@x.org"]);
  assert.match(text, /해제·탈퇴: b\*\*\*@x\.org/);
});

test("그대로면 아무것도 보내지 않는다", async () => {
  const file = tmpRoster();
  await aa.checkRoster({ "a@x.org": {} }, { file, cfg: CFG, say: quiet, send: async () => {} });
  let sent = 0;
  await aa.checkRoster({ "a@x.org": { googleName: "이름만 바뀜" } },
    { file, cfg: CFG, say: quiet, send: async () => { sent++; } });
  assert.equal(sent, 0);
});

test("보내기에 실패하면 기준을 고치지 않아 다음에 다시 보낸다", async () => {
  const file = tmpRoster();
  await aa.checkRoster({ "a@x.org": {} }, { file, cfg: CFG, say: quiet, send: async () => {} });

  const cur = { "a@x.org": {}, "b@x.org": {} };
  const fail = await aa.checkRoster(cur,
    { file, cfg: CFG, say: quiet, send: async () => { throw new Error("HTTP 500"); } });
  assert.equal(fail.sent, false);

  let sent = 0;
  const retry = await aa.checkRoster(cur,
    { file, cfg: CFG, say: quiet, send: async () => { sent++; } });
  assert.deepEqual(retry.added, ["b@x.org"]);
  assert.equal(sent, 1);
});

test("dry-run 은 보내지도 기준을 적지도 않는다", async () => {
  const file = tmpRoster();
  await aa.checkRoster({ "a@x.org": {} }, { file, dry: true, say: quiet });
  assert.ok(!fs.existsSync(file));
});
