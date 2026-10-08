#!/usr/bin/env node
/**
 * 관리자 명단이 바뀌면 디스코드로 알린다 (2026-10-08).
 *
 * 왜 필요한가
 *   관리자는 원본 전체(messagesSource)와 운영 설정을 읽고, 다른 사람을 승인·탈퇴시킨다.
 *   그런데 누가 관리자가 되어도 명부에 roleChangedBy 한 줄이 남을 뿐, 아무도 찾아가
 *   알려 주지 않았다. 관리자 계정 하나가 털려 공범을 관리자로 올려도 관리 탭을
 *   열어 보기 전에는 모른다. 은행권 사고(2026-09~10)에서 피해를 키운 것이 바로
 *   '늦게 안 것'이었다.
 *
 * 어디서 도는가
 *   refresh_watcher.js 가 이 PC 에 상주하며 Firestore 를 듣고 있다. 거기에 members
 *   (role == admin) 리스너를 하나 더 붙인다. 웹훅 주소는 이미 config/notify.json 에
 *   있고 이 PC 를 떠나지 않는다 — Functions 로 옮기면 웹훅을 클라우드 비밀값으로
 *   또 하나 두어야 한다.
 *
 *   PC 가 꺼져 있던 동안의 변화도 놓치지 않는다. 마지막으로 본 명단을
 *   output/admin-roster.json 에 적어 두고, 다시 붙을 때 그것과 비교한다.
 *   어느 경로로 바뀌었든(웹 관리 탭·approve_claims.js·members.json 업로드) 잡힌다.
 *
 * 알림에 무엇을 싣는가
 *   이메일은 앞 두 글자만 남기고 가린다. 알림 채널에 누가 있는지 이 코드는 모른다 —
 *   명부를 로그에서 뺀 것(ff77d09)과 같은 이유다. 본인은 앞 글자와 도메인, 구글
 *   이름으로 알아볼 수 있다.
 *
 *   이것은 보안 알림이라 notify_on 을 따르지 않는다. 웹훅만 있으면 늘 보낸다.
 *
 * 사용
 *   node scripts/admin_alert.js            # 지금 명단을 한 번 비교하고 끝
 *   node scripts/admin_alert.js --dry-run  # 보내지도 적지도 않고 무엇을 할지만
 */
const fs = require("fs");
const path = require("path");
const { loadNotifyConfig, sendNotice } = require("./report_run.js");

const ROOT = path.resolve(__dirname, "..");
const ROSTER = path.join(ROOT, "output", "admin-roster.json");

/** jwblue@sasw.or.kr → jw***@sasw.or.kr */
function maskEmail(email) {
  const s = String(email || "");
  const at = s.indexOf("@");
  if (at < 0) return "***";
  return s.slice(0, Math.min(2, at)) + "***" + s.slice(at);
}

/** members 문서 묶음 → { 이메일: { googleName, by, at } } */
function rosterFrom(docs) {
  const out = {};
  for (const d of docs) {
    const v = d.data() || {};
    out[d.id] = {
      googleName: v.googleName || "",
      by: v.roleChangedBy || v.approvedBy || "",
      at: v.roleChangedAt || v.approvedAt || "",
    };
  }
  return out;
}

/** 이전 명단과 지금 명단의 차이. 이전이 null 이면 첫 실행 — 기준만 잡는다. */
function diffAdmins(prev, cur) {
  if (!prev) return { first: true, added: [], removed: [] };
  const added = Object.keys(cur).filter((e) => !(e in prev)).sort();
  const removed = Object.keys(prev).filter((e) => !(e in cur)).sort();
  return { first: false, added, removed };
}

function buildAdminNotice(diff, cur, host) {
  const lines = ["\u{1F6A8} 카톡 아카이브 **관리자 명단이 바뀌었습니다**"];
  for (const e of diff.added) {
    const r = cur[e] || {};
    lines.push("➕ 관리자 추가: " + maskEmail(e) +
      (r.googleName ? " (" + r.googleName + ")" : "") +
      (r.by ? " — 처리: " + maskEmail(r.by) : "") +
      (r.at ? " · " + r.at : ""));
  }
  for (const e of diff.removed) {
    lines.push("➖ 관리자 해제·탈퇴: " + maskEmail(e));
  }
  lines.push("지금 관리자 " + Object.keys(cur).length + "명 · " + host);
  lines.push("본인이 한 일이 아니면 관리 탭에서 권한을 내리고, 그 계정의 비밀번호와 2단계 인증을 확인하세요.");
  return lines.join("\n");
}

function readRoster(file) {
  try {
    return JSON.parse(fs.readFileSync(file || ROSTER, "utf8")).admins || null;
  } catch (e) {
    return null;
  }
}

function writeRoster(cur, file) {
  const p = file || ROSTER;
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, JSON.stringify({ seenAt: new Date().toISOString(), admins: cur }, null, 2), "utf8");
}

/**
 * 명단 하나를 받아 비교하고, 바뀌었으면 알리고, 기준을 새로 적는다.
 *
 * 알림을 못 보냈으면 기준을 고치지 **않는다** — 다음 스냅샷(다시 붙을 때·PC 재시작)에
 * 같은 차이로 다시 시도한다. 기준부터 고치면 그 변화는 영영 알려지지 않는다.
 * 웹훅이 아예 없으면 보낼 길이 없으니 로그에만 남기고 기준을 고친다.
 */
async function checkRoster(cur, opts) {
  const o = opts || {};
  const say = o.say || ((m) => console.log(m));
  const send = o.send || sendNotice;
  const diff = diffAdmins(readRoster(o.file), cur);

  if (diff.first) {
    say(`관리자 명단 기준을 처음 적습니다 — ${Object.keys(cur).length}명.`);
    if (!o.dry) writeRoster(cur, o.file);
    return { ...diff, sent: false };
  }
  if (!diff.added.length && !diff.removed.length) return { ...diff, sent: false };

  const text = buildAdminNotice(diff, cur, o.host || require("os").hostname());
  say(`관리자 명단 변화 — 추가 ${diff.added.length}명, 해제 ${diff.removed.length}명.`, "WARN");
  if (o.dry) {
    say("[dry-run] 보낼 알림:\n" + text);
    return { ...diff, sent: false };
  }

  const cfg = o.cfg !== undefined ? o.cfg : loadNotifyConfig();
  if (!cfg) {
    say("디스코드 웹훅이 없어 알리지 못했습니다(config/notify.json).", "WARN");
    writeRoster(cur, o.file);
    return { ...diff, sent: false };
  }
  try {
    await send(cfg, text);
  } catch (e) {
    say(`관리자 변화 알림 실패 — 다음에 다시 보냅니다: ${e.message}`, "ERROR");
    return { ...diff, sent: false };
  }
  writeRoster(cur, o.file);
  return { ...diff, sent: true };
}

/** members 에서 관리자만 고르는 질의. 감시와 한 번 확인이 같은 것을 본다. */
function adminQuery(db) {
  return db.collection("members").where("role", "==", "admin");
}

module.exports = {
  maskEmail, rosterFrom, diffAdmins, buildAdminNotice, checkRoster, adminQuery, ROSTER,
};

if (require.main === module) {
  const admin = require("firebase-admin");
  const KEY = require("./sa_key");
  const DRY = process.argv.includes("--dry-run");
  admin.initializeApp({
    credential: fs.existsSync(KEY)
      ? admin.credential.cert(require(KEY))
      : admin.credential.applicationDefault(),
    projectId: "katok-crawling-project",
  });
  adminQuery(admin.firestore()).get()
    .then((snap) => checkRoster(rosterFrom(snap.docs), { dry: DRY }))
    .then((r) => {
      console.log(r.first ? "기준 저장" : (r.added.length || r.removed.length) ? "변화 있음" : "변화 없음");
    }, (e) => {
      console.error("관리자 명단 확인 실패:", e.message);
      process.exitCode = 1;
    })
    // process.exit() 로 끊지 않는다. 디스코드로 보낸(fetch) 직후 끊으면 Windows 의
    // Node 가 'UV_HANDLE_CLOSING' 단언으로 죽는다(실측 2026-10-08). 연결을 닫고
    // 저절로 끝나게 둔다.
    .finally(() => admin.app().delete());
}
