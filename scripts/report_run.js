#!/usr/bin/env node
/**
 * 일일 갱신의 결과를 `settings/lastRun` 에 한 장으로 남긴다.
 *
 * 왜 필요한가 — 갱신 경로가 둘인데 한쪽만 화면에 보였다.
 *
 *   '지금 갱신' 버튼   refresh_watcher.js 가 settings/refresh 에 상태를 쓴다.
 *                      관리 탭이 실시간으로 읽어 "갱신 중…", "실패했습니다" 를 보여준다.
 *   매일 23:40 스케줄러  **아무것도 쓰지 않았다.** 성패가 logs\daily-*.log 에만 남았다.
 *
 * 그래서 야간 갱신이 사흘 내리 실패해도 화면은 조용했다. 사람이 로그를 열어 보기
 * 전까지 아무도 모른다. 2026-07-30 에 겪은 일이 정확히 그 꼴이었다 — 23:40 갱신이
 * 새 글 34건을 원장에 넣고 테스트 단계에서 멈췄는데, 다음 날 버튼을 눌러도 증분이
 * 0건이라 "마쳤습니다" 만 떴다. 그때는 `publish_state.py`(뒤처짐 자동 추격)로
 * **결과**를 고쳤다. 이 스크립트는 **알림**을 고친다 — 실패했다는 사실 자체가
 * 화면에 뜨게 한다.
 *
 * 쓰기는 Admin SDK 로 한다(규칙 우회). 클라이언트는 settings 에 쓸 수 없고,
 * 그래야 멤버 누구나 "어제 갱신 성공했음" 이라고 적어 넣지 못한다.
 *
 *   node scripts/report_run.js --status ok      --why "새 메시지 3건" --added 3
 *   node scripts/report_run.js --status skipped --why "발행 사유 없음"
 *   node scripts/report_run.js --status failed  --step 테스트 --exit 1
 *
 * **이 스크립트가 실패해도 갱신은 성공한 것이다.** 부르는 쪽(run_daily.ps1)이
 * 종료 코드를 무시한다 — 알림을 남기려는 코드가 그날 갱신을 실패로 만들어서는
 * 안 된다. 같은 이유로 여기서 예외를 삼키고 0 으로 끝낸다.
 */
const fs = require("fs");
const os = require("os");
const path = require("path");
const admin = require("firebase-admin");

const ROOT = path.resolve(__dirname, "..");
const KEY = path.join(ROOT, "serviceAccountKey.json");
const NOTIFY = path.join(ROOT, "config", "notify.json");

/* ── 밖으로 알리기 (2026-09-02) ──
 *
 * settings/lastRun 은 관리 탭을 **열어야** 보인다. 2026-08-02 하루가 통째로
 * 빠진 것도, 2026-09-01 밤이 테스트 단계에서 멈춘 것도, 아침에 로그를 열고서야
 * 알았다. 실패는 사람을 찾아가야 한다.
 *
 * config/notify.json 에 디스코드 웹훅 주소가 있으면 거기로 한 줄 보낸다. 파일이
 * 없으면 아무 일도 하지 않는다 — 이 기능이 없던 때와 똑같이 돈다. 웹훅 주소는
 * 아는 사람은 누구나 그 채널에 글을 쓸 수 있는 값이라 저장소에 넣지 않는다
 * (.gitignore, 예시는 config/notify.example.json).
 *
 * 기본은 failed 만 보낸다. 매일 '성공' 이 오면 그 채널은 곧 읽지 않는 채널이 되고,
 * 그러면 실패도 같이 묻힌다. 성공을 보고 싶으면 notify_on 에 "ok" 를 더한다.
 */
const NOTIFY_TIMEOUT_MS = 10_000;
const EMOJI = { ok: "\u{1F7E2}", skipped: "\u26AA", failed: "\u{1F534}" };

function loadNotifyConfig(file) {
  const p = file || NOTIFY;
  let cfg = {};
  try {
    cfg = JSON.parse(fs.readFileSync(p, "utf8")) || {};
  } catch (e) {
    cfg = {};
  }
  // 환경 변수가 있으면 파일보다 앞선다 — 작업 스케줄러에서 시험할 때 파일을 안 건드린다.
  const url = process.env.KATOK_NOTIFY_WEBHOOK || cfg.discord_webhook || "";
  if (!/^https:\/\/(discord\.com|discordapp\.com)\/api\/webhooks\//.test(url)) return null;
  const on = Array.isArray(cfg.notify_on) && cfg.notify_on.length ? cfg.notify_on : ["failed"];
  return { url, on };
}

/** 디스코드 한 줄. 로그 경로까지 적어 아침에 어디를 열지 바로 알게 한다. */
function buildNotice(doc, logPath) {
  const when = new Date(doc.finishedAt).toLocaleString("ko-KR", { hour12: false });
  const head = EMOJI[doc.status] + " 카톡 아카이브 " +
    (doc.trigger === "scheduled" ? "밤 갱신" : "갱신");
  const lines = [];
  if (doc.status === "failed") {
    lines.push(head + " **실패** — " + (doc.lastStep ? "'" + doc.lastStep + "' 단계" : "단계 불명") +
      (doc.exitCode !== null && doc.exitCode !== undefined ? " (exit " + doc.exitCode + ")" : ""));
    lines.push("고친 뒤 관리 탭 '지금 갱신' 을 누르거나 `powershell -File scripts\\run_daily.ps1 -SkipExport` 로 다시 돌립니다.");
  } else if (doc.status === "skipped") {
    lines.push(head + " 건너뜀 — " + (doc.why || "올릴 것이 없었습니다"));
  } else {
    lines.push(head + " 마침" + (doc.why ? " — " + doc.why : ""));
  }
  lines.push(when + " · " + doc.host + (logPath ? " · " + logPath : ""));
  return lines.join("\n");
}

async function sendNotice(cfg, text) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), NOTIFY_TIMEOUT_MS);
  try {
    const r = await fetch(cfg.url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ content: text.slice(0, 1900) }),
      signal: ctl.signal,
    });
    if (!r.ok) throw new Error("HTTP " + r.status);
    console.log("디스코드 알림 보냄");
  } finally {
    clearTimeout(timer);
  }
}

/** 오늘의 일일 로그 경로 — 알림에 적어 보낸다. 없으면 빈 문자열. */
function todayLogPath(now) {
  const d = now || new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return "logs\\daily-" + d.getFullYear() + pad(d.getMonth() + 1) + pad(d.getDate()) + ".log";
}

/** `--status ok --step 테스트` 꼴을 읽는다. 값 없는 마지막 인자도 견딘다. */
function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (!a.startsWith("--")) continue;
    const key = a.slice(2);
    const next = argv[i + 1];
    if (next === undefined || next.startsWith("--")) out[key] = true;
    else { out[key] = next; i++; }
  }
  return out;
}

const VALID = ["ok", "skipped", "failed"];

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const status = String(args.status || "");
  if (VALID.indexOf(status) === -1) {
    console.error(`--status 는 ${VALID.join("|")} 중 하나여야 합니다 (받은 값: ${status || "없음"})`);
    process.exit(2);
  }

  const n = (v) => (v === undefined || v === true ? null : Number(v));
  const s = (v) => (v === undefined || v === true ? null : String(v));

  const doc = {
    status,
    // 자동화가 남기는 것임을 못박는다. 버튼 경로는 settings/refresh 를 쓰므로
    // 이 문서에 섞이지 않지만, 손으로 돌린 갱신도 여기에 쌓이기 때문이다.
    trigger: s(args.trigger) || "scheduled",
    finishedAt: new Date().toISOString(),
    exitCode: n(args.exit),
    // 실패한 단계 이름. 로그를 열지 않고도 어디서 멈췄는지 보여주는 값이다.
    lastStep: s(args.step),
    // 무엇 때문에 발행했는가(또는 왜 건너뛰었는가).
    why: s(args.why),
    added: n(args.added),
    host: os.hostname(),
  };

  // 화면 기록과 바깥 알림은 서로 독립이다 — 한쪽이 실패해도 다른 쪽은 간다.
  // Firestore 가 안 닿는 날(키 만료·네트워크)이 바로 알림이 가장 필요한 날이다.
  try {
    admin.initializeApp({
      credential: admin.credential.cert(JSON.parse(fs.readFileSync(KEY, "utf8"))),
    });
    // merge 로 쓴다 — 나중에 다른 곳에서 이 문서에 필드를 더할 수 있게 둔다.
    await admin.firestore().collection("settings").doc("lastRun").set(doc, { merge: true });
    console.log(`settings/lastRun 기록: ${status}${doc.lastStep ? " @ " + doc.lastStep : ""}`);
  } catch (e) {
    console.error("settings/lastRun 기록 실패(무시하고 계속):", e.message);
  }

  const cfg = loadNotifyConfig();
  if (cfg && cfg.on.indexOf(status) !== -1) {
    try {
      await sendNotice(cfg, buildNotice(doc, todayLogPath()));
    } catch (e) {
      console.error("디스코드 알림 실패(무시하고 계속):", e.message);
    }
  }
}

module.exports = { parseArgs, loadNotifyConfig, buildNotice, todayLogPath, VALID };

if (require.main === module) {
  main().catch((e) => {
    // 삼킨다. 위 주석 참고 — 알림 실패가 갱신 실패로 번지면 안 된다.
    console.error("기록·알림 실패(무시하고 계속):", e.message);
    process.exit(0);
  });
}
