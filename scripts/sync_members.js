#!/usr/bin/env node
/**
 * Firestore 의 멤버 명부를 config/members.json 으로 내려받는다.
 *
 * 멤버 명부의 주인은 Firestore 다. 관리자 페이지(approveClaim/setMemberRole Function)와
 * approve_claims.js 가 Admin SDK 로 직접 쓴다.
 *
 * config/members.json 은 그 거울이다. 파이프라인이 오프라인에서 읽어야 하는 것들이
 * 있어 남겨둔다 — 닉네임 대조(발행 경고), 이메일→표시명 매핑(멤버 요청 반영),
 * 클레임 점검(sync_claims). 이 파일을 손으로 고쳐도 Firestore 로 올라가지 않는다.
 *
 * 왜 이렇게 나눴나
 *   예전에는 발행이 config/members.json 을 기준으로 members 컬렉션을 통째로
 *   동기화했다. 그러면 관리자 페이지에서 승인한 사람이 그 파일에 없어 '구문서'로
 *   판정되고 그날 밤 삭제된다 — 승인한 다음 날 조용히 권한이 사라진다.
 *   방향을 하나로 정리해 그 사고를 없앴다.
 *
 * 사용
 *   node scripts/sync_members.js
 *   node scripts/sync_members.js --dry-run
 */
const fs = require("fs");
const path = require("path");
const admin = require("firebase-admin");

const ROOT = path.resolve(__dirname, "..");
const KEY = path.join(ROOT, "serviceAccountKey.json");
const MEMBERS = path.join(ROOT, "config", "members.json");
const PROJECT_ID = "katok-crawling-project";

const DRY = process.argv.slice(2).includes("--dry-run");

const COMMENT = [
  "Firestore members 컬렉션의 로컬 거울. scripts/sync_members.js 가 만든다.",
  "여기를 손으로 고쳐도 Firestore 로 올라가지 않는다 — 명부의 주인은 Firestore 다.",
  "멤버를 바꾸려면 관리 탭에서 승인하거나 scripts/approve_claims.js 를 쓴다.",
  "파이프라인은 닉네임 대조·이메일→표시명 매핑에만 이 파일을 읽는다.",
  "예외: \"speaks\": false 는 Firestore 에 없는 로컬 표시다(대화에 안 나타나는 운영 계정).",
  "이 표시는 동기화 때 그대로 유지된다 — 지우면 매일 밤 닉네임 경고가 되살아난다.",
];

function init() {
  if (fs.existsSync(KEY)) {
    admin.initializeApp({
      credential: admin.credential.cert(require(KEY)),
      projectId: PROJECT_ID,
    });
    return;
  }
  try {
    admin.initializeApp({
      credential: admin.credential.applicationDefault(),
      projectId: PROJECT_ID,
    });
  } catch (e) {
    console.error(`인증 정보 없음. ${KEY} 를 두거나 gcloud ADC 를 설정하세요.`);
    process.exit(1);
  }
}

function readLocal() {
  if (!fs.existsSync(MEMBERS)) return [];
  try {
    return JSON.parse(fs.readFileSync(MEMBERS, "utf8")).members || [];
  } catch (e) {
    return [];
  }
}

async function main() {
  init();
  const snap = await admin.firestore().collection("members").get();

  const members = snap.docs
    .map((d) => {
      const m = d.data() || {};
      // 표시명은 여러 개일 수 있다 (카톡에서 이름을 바꾸면 참여자가 갈린다).
      // 옛 문서는 nickname 하나만 갖고 있으므로 그것으로 채운다.
      const nicknames = Array.isArray(m.nicknames) && m.nicknames.length
        ? m.nicknames.filter(Boolean)
        : (m.nickname ? [m.nickname] : []);
      return {
        email: d.id,
        name: m.name || nicknames[0] || "",
        nickname: nicknames[0] || "",
        nicknames,
        role: m.role === "admin" ? "admin" : "user",
      };
    })
    .sort((a, b) => (a.email < b.email ? -1 : a.email > b.email ? 1 : 0));

  const before = readLocal();
  const beforeSet = new Set(before.map((m) => String(m.email || "").toLowerCase()));
  const afterSet = new Set(members.map((m) => m.email));

  // 로컬 전용 표시를 살려 둔다.
  //
  // `speaks: false` 는 Firestore 에 없는 필드다 — 카톡 수집을 위해 컴퓨터에 로그인해
  // 둔 계정처럼 '영영 대화에 안 나타나는 계정'을 표시해 매일 밤 같은 닉네임 경고가
  // 뜨는 것을 막는다. 그런데 이 거울은 Firestore 필드만으로 다시 만들어지므로,
  // 그대로 두면 그 표시가 동기화 한 번에 사라지고 경고가 되살아난다(실측 2026-07-29:
  // 표시가 지워져 안전장치 테스트가 실패했다).
  const localOnly = new Map(
    before
      .filter((m) => m && m.speaks === false)
      .map((m) => [String(m.email || "").toLowerCase(), false])
  );
  const carried = [];
  for (const m of members) {
    if (localOnly.has(m.email)) {
      m.speaks = false;
      carried.push(m.email);
    }
  }

  /* 명부 전체를 찍지 않는다 (2026-09-02).
   *
   * 예전에는 38명의 이메일과 실명을 매일 밤 일일 로그에 그대로 썼다. 로그는
   * 90일 보관이니 어느 날이든 logs\ 에 명부 사본이 마흔 벌 있었다. 저장소에는
   * 안 들어가지만, 개인정보를 가리느라 세 겹을 쌓은 파이프라인이 자기 로그에는
   * 그것을 흘리고 있었다. 운영자가 알아야 하는 것은 '누가 늘고 줄었나' 뿐이다 —
   * 그것만, 표시명으로 적는다. 이메일은 앞 두 글자만 남긴다.
   */
  const shortMail = (e) => {
    const [local, domain] = String(e).split("@");
    return (local || "").slice(0, 2) + "***@" + (domain || "");
  };
  const added = members.filter((m) => !beforeSet.has(m.email));
  const removed = before
    .map((m) => String(m.email || "").toLowerCase())
    .filter((email) => email && !afterSet.has(email));
  console.log(`Firestore 멤버 ${members.length}명 (관리자 ${members.filter((m) => m.role === "admin").length})`);
  for (const m of added) {
    console.log(`  + ${m.nicknames.length ? m.nicknames.join(", ") : "(표시명 없음)"}  ${m.role}  ${shortMail(m.email)}`);
  }
  for (const email of removed) {
    const old = before.find((m) => String(m.email || "").toLowerCase() === email) || {};
    console.log(`  - ${old.nickname || "(표시명 없음)"}  ${shortMail(email)} (Firestore 에 없어 거울에서 제거)`);
  }
  if (!added.length && !removed.length) console.log("  변동 없음");
  if (carried.length) console.log(`  (로컬 표시 유지: speaks=false ${carried.length}명)`);
  for (const email of localOnly.keys()) {
    if (!afterSet.has(email)) console.log(`  [주의] speaks=false 표시가 있던 ${shortMail(email)} 이 Firestore 에 없습니다`);
  }

  if (!members.length) {
    // 명부를 통째로 날리는 사고를 막는다. 정말 0명이면 Firestore 를 직접 확인할 일이다.
    console.error("\n[중단] Firestore 멤버가 0명입니다. 거울을 덮어쓰지 않았습니다.");
    process.exit(1);
  }
  if (DRY) {
    console.log("\n--dry-run: 파일을 쓰지 않았습니다.");
    return;
  }

  fs.writeFileSync(
    MEMBERS,
    JSON.stringify({ _comment: COMMENT, members }, null, 2) + "\n",
    "utf8"
  );
  console.log(`\nconfig/members.json 갱신 (${members.length}명)`);
}

main().catch((e) => {
  console.error("\n실패:", e.message);
  process.exit(1);
});
