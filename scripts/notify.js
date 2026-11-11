#!/usr/bin/env node
/**
 * 디스코드로 한 줄 보낸다 — 갱신이 성공했어도 사람이 알아야 할 일이 있을 때.
 *
 * report_run.js 의 알림은 갱신의 성패에 묶여 있다(notify_on 기본 failed). 그런데
 * 갱신은 멀쩡히 끝났어도 사람을 불러야 하는 날이 있다 — 첨부가 곧 만료되는데 아직
 * 못 받았을 때(audit_attachments.py). 관리 탭에만 남기면 2026-08-22~25 처럼 나흘을
 * 모르고 지나간다.
 *
 * 같은 웹훅·같은 설정을 쓴다. 실패와 같은 갈래로 보고 notify_on 에 failed 가 있을
 * 때만 보낸다. 보내기에 실패해도 0 으로 끝난다 — 알림이 갱신을 실패로 만들면 안 된다.
 *
 *   node scripts/notify.js --text "📎 ..."
 */
const os = require("os");
const { loadNotifyConfig, sendNotice, parseArgs } = require("./report_run.js");

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const text = typeof args.text === "string" ? args.text.trim() : "";
  if (!text) {
    console.error("--text 가 비었습니다.");
    return;
  }
  const cfg = loadNotifyConfig();
  if (!cfg || cfg.on.indexOf("failed") === -1) {
    console.log("디스코드 웹훅이 없거나 failed 알림이 꺼져 있어 보내지 않았습니다.");
    return;
  }
  await sendNotice(cfg, text + "\n" + os.hostname());
}

// process.exit() 로 끊지 않는다. 디스코드로 보낸(fetch) 직후 끊으면 Windows 의 Node 가
// 'UV_HANDLE_CLOSING' 단언으로 죽는다(admin_alert.js 실측 2026-10-08). 종료 코드만
// 0 으로 정해 두고 저절로 끝나게 둔다 — 실패해도 갱신을 실패로 만들지 않는다.
main().catch((e) => {
  console.error("디스코드 알림 실패(무시하고 계속):", e.message);
}).finally(() => { process.exitCode = 0; });
