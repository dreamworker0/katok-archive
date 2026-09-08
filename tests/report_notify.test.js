// 밤 갱신 실패를 밖으로 알리는 조각 — report_run.js 의 알림 부분.
//
// 왜 검사하는가: 이 코드는 실패한 밤에만 돈다. 평소에는 한 줄도 실행되지 않으니
// 잘못 고쳐도 몇 주 뒤 실패한 밤에야 드러나고, 그날은 알림이 가장 필요한 날이다.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

// require 만으로 main() 이 돌면 검사가 Firestore 를 두드린다. 그래서 진입 가드가 있다.
const rr = require("../scripts/report_run.js");

function tmpJson(obj) {
  const p = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "notify-")), "notify.json");
  fs.writeFileSync(p, JSON.stringify(obj), "utf8");
  return p;
}

test("설정 파일이 없으면 알리지 않는다 — 기능이 없던 때와 같게", () => {
  delete process.env.KATOK_NOTIFY_WEBHOOK;
  assert.equal(rr.loadNotifyConfig(path.join(os.tmpdir(), "없는파일.json")), null);
});

test("디스코드 웹훅 주소만 받는다 — 엉뚱한 곳으로 로그를 보내지 않는다", () => {
  delete process.env.KATOK_NOTIFY_WEBHOOK;
  assert.equal(rr.loadNotifyConfig(tmpJson({ discord_webhook: "https://example.com/x" })), null);
  const cfg = rr.loadNotifyConfig(tmpJson({ discord_webhook: "https://discord.com/api/webhooks/1/abc" }));
  assert.ok(cfg);
  assert.deepEqual(cfg.on, ["failed"]);
});

test("notify_on 을 적으면 그대로 따른다", () => {
  const cfg = rr.loadNotifyConfig(tmpJson({
    discord_webhook: "https://discord.com/api/webhooks/1/abc", notify_on: ["failed", "ok"],
  }));
  assert.deepEqual(cfg.on, ["failed", "ok"]);
});

test("환경 변수가 파일보다 앞선다", () => {
  process.env.KATOK_NOTIFY_WEBHOOK = "https://discord.com/api/webhooks/9/env";
  try {
    const cfg = rr.loadNotifyConfig(tmpJson({ discord_webhook: "https://discord.com/api/webhooks/1/abc" }));
    assert.equal(cfg.url, "https://discord.com/api/webhooks/9/env");
  } finally {
    delete process.env.KATOK_NOTIFY_WEBHOOK;
  }
});

test("실패 알림에는 단계·exit·로그 경로·다시 돌리는 법이 있다", () => {
  const text = rr.buildNotice({
    status: "failed", trigger: "scheduled", lastStep: "테스트", exitCode: 1,
    finishedAt: "2026-09-01T14:52:57.000Z", host: "PC",
  }, "logs\\daily-20260901.log");
  assert.match(text, /실패/);
  assert.match(text, /'테스트' 단계/);
  assert.match(text, /exit 1/);
  assert.match(text, /daily-20260901\.log/);
  assert.match(text, /지금 갱신/);
  assert.ok(text.length < 1900, "디스코드 한도(2000자) 안");
});

test("실패 알림은 '왜' 까지 싣는다 — 단계 이름만으로는 로그를 열어야 안다", () => {
  // 실측 2026-09-08: 알림에 "'테스트' 단계 (exit 1)" 만 있었고, 로그를 열어도
  // 꼬리 490줄이 검사가 찍은 발행 경고라 실패 줄이 안 보였다.
  const text = rr.buildNotice({
    status: "failed", trigger: "scheduled", lastStep: "테스트", exitCode: 1,
    reason: "FAIL: test_shared_documents_carry_no_maskable_pii\nFAILED (failures=2)",
    finishedAt: "2026-09-01T14:52:57.000Z", host: "PC",
  }, "logs\ndaily-20260901.log");
  assert.match(text, /FAIL: test_shared_documents/);
  assert.match(text, /FAILED \(failures=2\)/);
  assert.ok(text.length < 1900, "디스코드 한도(2000자) 안");
});

test("사유가 없으면 사유 줄도 없다 — 빈 상자를 보이지 않는다", () => {
  const text = rr.buildNotice({
    status: "failed", trigger: "scheduled", lastStep: "테스트", exitCode: 1,
    finishedAt: "2026-09-01T14:52:57.000Z", host: "PC",
  }, "");
  assert.ok(!text.includes("```"), "사유가 없는데 코드 상자가 들어갔다");
});


test("성공·건너뜀도 문장이 다르다 — 같은 글이면 채널이 읽히지 않는다", () => {
  const ok = rr.buildNotice({ status: "ok", trigger: "scheduled", why: "새 메시지 3건",
    finishedAt: "2026-09-01T14:52:57.000Z", host: "PC" }, "");
  const sk = rr.buildNotice({ status: "skipped", trigger: "scheduled", why: "발행 사유 없음",
    finishedAt: "2026-09-01T14:52:57.000Z", host: "PC" }, "");
  assert.match(ok, /마침/);
  assert.match(ok, /새 메시지 3건/);
  assert.match(sk, /건너뜀/);
  assert.notEqual(ok, sk);
});

test("오늘 로그 경로는 run_daily.ps1 이 쓰는 이름과 같다", () => {
  assert.equal(rr.todayLogPath(new Date(2026, 8, 2, 8, 0, 0)), "logs\\daily-20260902.log");
});
