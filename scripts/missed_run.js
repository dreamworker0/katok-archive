#!/usr/bin/env node
/**
 * 밤 갱신이 '아예 안 돈 날' 을 알린다 (2026-11-01).
 *
 * 왜 필요한가
 *   실패는 이미 알린다 — run_daily.ps1 이 멈추면 report_run.js 가 디스코드로 보낸다.
 *   그런데 그것은 run_daily 가 **끝까지 와서 말할 수 있을 때** 뿐이다. 말할 기회조차
 *   없는 꼴이 셋 있다.
 *     - 예약 작업이 뜨지 않았다(꺼짐·트리거 사라짐·계정 문제).
 *     - 실행 시간 제한(2시간)에 걸려 윈도우가 프로세스를 죽였다 — Report-Run 에
 *       닿기 전이라 lastRun 도 알림도 없다.
 *     - powershell 자체가 죽었다.
 *   셋 다 조용하다. 2026-08-02 하루가 통째로 빠진 것도 아침에 로그를 열고서야 알았다.
 *
 * 어떻게 보는가
 *   report_run.js 는 성공·건너뜀·실패 어느 쪽이든 settings/lastRun.finishedAt 을 쓴다.
 *   그것이 27시간 넘게 그대로면 '돌지 않았다' 고 본다. 밤 갱신은 23:40 에 떠서
 *   시간 제한(2시간) 안에, 늦어도 01:40 에 끝나므로 정상인 날의 간격은 26시간을
 *   넘지 않는다.
 *   지금 돌고 있으면(run_daily.lock 이 잡혀 있으면) 말하지 않는다 — 따라잡기 중이다.
 *
 * 어디서 도는가
 *   refresh_watcher.js 에 얹는다. 이 PC 에 늘 떠 있는 것이 그것뿐이고, 웹훅도 이미
 *   config/notify.json 에 있다(admin_alert.js 와 같은 이유).
 *
 *   **PC 가 꺼져 있는 동안은 알리지 못한다** — 감시도 함께 꺼지기 때문이다. 다시
 *   켜지면 놓친 갱신은 예약 작업이 따라잡고(StartWhenAvailable), 그래도 기록이 오래
 *   비어 있으면 그때 알린다. 켜진 직후의 따라잡기와 겹치지 않게 첫 확인은 늦춘다.
 *
 * 같은 공백을 두 번 알리지 않는다
 *   알린 lastRun.finishedAt 을 output/missed-run-alert.json 에 적는다. 갱신이 한 번
 *   돌면 finishedAt 이 바뀌므로 다음 공백은 다시 알린다. 알림을 못 보냈으면 적지
 *   않는다 — 다음 확인에서 다시 보낸다(admin_alert.checkRoster 와 같은 원칙).
 *
 * 사용
 *   node scripts/missed_run.js            # 지금 한 번 확인하고 끝
 *   node scripts/missed_run.js --dry-run  # 보내지도 적지도 않고 판정만
 */
const fs = require("fs");
const os = require("os");
const path = require("path");
const { loadNotifyConfig, sendNotice } = require("./report_run.js");

const ROOT = path.resolve(__dirname, "..");
const LOG_DIR = path.join(ROOT, "logs");
const LOCK = path.join(LOG_DIR, "run_daily.lock");
const STATE = path.join(ROOT, "output", "missed-run-alert.json");

// 이만큼 기록이 없으면 '안 돌았다'. 정상 간격은 길어야 26시간(23:45 끝 → 다음 밤
// 시간 제한 끝인 01:40 끝)이라 한 시간을 더 둔다. 실행 제한을 늘리면 이것도 늘릴 것.
const MISSED_AFTER_MS = 27 * 60 * 60 * 1000;
// 얼마나 자주 보는가. 문서 하나 읽기라 값이 없다.
const CHECK_EVERY_MS = 30 * 60 * 1000;
// 감시가 막 떴을 때는 기다린다 — 로그온 직후 예약 작업이 놓친 갱신을 따라잡기 시작할
// 틈을 준다. 그 사이에 확인하면 따라잡기가 잠금을 잡기 전이라 헛알림이 된다.
const FIRST_CHECK_AFTER_MS = 15 * 60 * 1000;

function millisOf(value) {
  if (!value) return null;
  if (typeof value.toMillis === "function") return value.toMillis();
  const t = Date.parse(String(value));
  return Number.isNaN(t) ? null : t;
}

/** run_daily 가 지금 돌고 있는가. 잠금 파일을 공유 없이(FileShare None) 쥐고 있으므로
 *  열어 보면 안다 — 잡혀 있으면 EBUSY·EPERM 이 난다. 파일이 없으면 돈 적이 없는 것이다. */
function isRunning(lockPath) {
  let fd = null;
  try {
    fd = fs.openSync(lockPath || LOCK, "r+");
    return false;
  } catch (e) {
    return e.code === "EBUSY" || e.code === "EPERM" || e.code === "EACCES";
  } finally {
    if (fd !== null) fs.closeSync(fd);
  }
}

/** 가장 최근 일일 로그 — 알림에 '어디를 열지' 를 적는다. 없으면 null. */
function latestDailyLog(logDir) {
  const dir = logDir || LOG_DIR;
  let names = [];
  try {
    names = fs.readdirSync(dir).filter((n) => /^daily-\d{8}\.log$/.test(n)).sort();
  } catch (e) {
    return null;
  }
  if (!names.length) return null;
  const name = names[names.length - 1];
  try {
    return { name, mtime: fs.statSync(path.join(dir, name)).mtimeMs };
  } catch (e) {
    return { name, mtime: null };
  }
}

/**
 * 알릴 것인가. 순수 함수다 — 시각·잠금·기록을 모두 받아서 판정만 한다.
 *
 * key 는 '어느 공백인가' 를 가리킨다. 마지막 기록의 finishedAt 이고, 기록이 아예
 * 없으면 'none'. 이미 알린 key 면 다시 알리지 않는다.
 */
function judge({ lastRun, now, running, alertedFor }) {
  const at = millisOf(lastRun && lastRun.finishedAt);
  const key = at === null ? "none" : String(lastRun.finishedAt);
  const gapMs = at === null ? null : now - at;
  const base = { key, gapMs, at };
  if (running) return { ...base, missed: false, why: "running" };
  if (gapMs !== null && gapMs <= MISSED_AFTER_MS) return { ...base, missed: false, why: "fresh" };
  if (alertedFor === key) return { ...base, missed: true, notify: false, why: "already" };
  return { ...base, missed: true, notify: true, why: "missed" };
}

function fmt(ms) {
  return new Date(ms).toLocaleString("ko-KR", { hour12: false });
}

function buildMissedNotice(v, lastRun, log, host) {
  const lines = [];
  if (v.at === null) {
    lines.push("⏰ 카톡 아카이브 밤 갱신 **기록이 하나도 없습니다** (settings/lastRun).");
  } else {
    const hours = Math.floor(v.gapMs / 3600000);
    lines.push("⏰ 카톡 아카이브 밤 갱신이 **" + hours + "시간째 돌지 않았습니다**.");
    lines.push("마지막 기록: " + fmt(v.at) + " · " + (lastRun.status || "?") +
      (lastRun.lastStep ? " @ " + lastRun.lastStep : ""));
  }
  if (log) {
    lines.push("가장 최근 로그: logs\\" + log.name + (log.mtime ? " (마지막 수정 " + fmt(log.mtime) + ")" : ""));
  }
  lines.push("짚어 볼 곳: 작업 스케줄러 '카톡아카이브-일일갱신' 의 지난 실행 결과 · " +
    "로그가 중간에 끊겼다면 2시간 실행 제한에 걸렸을 수 있음 · " +
    "로그는 끝까지 갔는데 이 알림이 왔다면 기록만 못 남긴 것(네트워크).");
  lines.push("다시 돌리기: 관리 탭 '지금 갱신' 또는 `powershell -File scripts\\run_daily.ps1`");
  lines.push(host);
  return lines.join("\n");
}

function readState(file) {
  try {
    return JSON.parse(fs.readFileSync(file || STATE, "utf8")).alertedFor || null;
  } catch (e) {
    return null;
  }
}

function writeState(key, file) {
  const p = file || STATE;
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, JSON.stringify({ alertedFor: key, at: new Date().toISOString() }, null, 2), "utf8");
}

/** 한 번 확인한다. lastRun 은 Firestore 에서 읽어 넘긴다(시험에서 바꿔 끼우려고). */
async function checkOnce(lastRun, opts) {
  const o = opts || {};
  const say = o.say || ((m) => console.log(m));
  const send = o.send || sendNotice;
  const v = judge({
    lastRun,
    now: o.now !== undefined ? o.now : Date.now(),
    running: o.running !== undefined ? o.running : isRunning(o.lock),
    alertedFor: readState(o.file),
  });
  if (!v.notify) return { ...v, sent: false };

  const text = buildMissedNotice(v, lastRun || {}, o.log !== undefined ? o.log : latestDailyLog(o.logDir),
    o.host || os.hostname());
  say("밤 갱신 기록이 오래 비었습니다 — " +
    (v.gapMs === null ? "기록 없음" : Math.floor(v.gapMs / 3600000) + "시간"), "WARN");
  if (o.dry) {
    say("[dry-run] 보낼 알림:\n" + text);
    return { ...v, sent: false };
  }

  // 밤 갱신 실패와 같은 갈래로 본다 — notify_on 에 failed 가 있을 때 보낸다.
  const cfg = o.cfg !== undefined ? o.cfg : loadNotifyConfig();
  if (!cfg || cfg.on.indexOf("failed") === -1) {
    say("디스코드 웹훅이 없거나 failed 알림이 꺼져 있어 알리지 못했습니다(config/notify.json).", "WARN");
    writeState(v.key, o.file);
    return { ...v, sent: false };
  }
  try {
    await send(cfg, text);
  } catch (e) {
    say(`갱신 공백 알림 실패 — 다음 확인에서 다시 보냅니다: ${e.message}`, "ERROR");
    return { ...v, sent: false };
  }
  writeState(v.key, o.file);
  return { ...v, sent: true };
}

function lastRunRef(db) {
  return db.collection("settings").doc("lastRun");
}

/** refresh_watcher.js 가 부른다. 읽기에 실패하면 넘기고 다음 확인을 기다린다. */
function start(db, { say, dry = false } = {}) {
  const check = async () => {
    try {
      const snap = await lastRunRef(db).get();
      await checkOnce(snap.exists ? snap.data() : null, { say, dry });
    } catch (e) {
      say(`갱신 공백 확인 실패(다음에 다시): ${e.message}`, "WARN");
    }
  };
  setTimeout(() => {
    check();
    setInterval(check, CHECK_EVERY_MS);
  }, FIRST_CHECK_AFTER_MS);
}

module.exports = {
  judge, isRunning, latestDailyLog, buildMissedNotice, checkOnce, start,
  MISSED_AFTER_MS, STATE,
};

if (require.main === module) {
  const admin = require("firebase-admin");
  const KEY = require("./sa_key");
  const DRY = process.argv.includes("--dry-run");
  admin.initializeApp({
    credential: fs.existsSync(KEY)
      ? admin.credential.cert(require(KEY))
      : admin.credential.applicationDefault(),
  });
  lastRunRef(admin.firestore()).get()
    .then((snap) => {
      const lr = snap.exists ? snap.data() : null;
      return checkOnce(lr, { dry: DRY }).then((v) => {
        console.log(`판정: ${v.why} · 마지막 기록 ${lr && lr.finishedAt ? lr.finishedAt : "없음"}` +
          (v.gapMs !== null ? ` · ${(v.gapMs / 3600000).toFixed(1)}시간 전` : ""));
      });
    })
    .then(() => process.exit(0))
    .catch((e) => { console.error("확인 실패:", e.message); process.exit(1); });
}
