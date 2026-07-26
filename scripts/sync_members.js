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
      return {
        email: d.id,
        name: m.name || m.nickname || "",
        nickname: m.nickname || "",
        role: m.role === "admin" ? "admin" : "user",
      };
    })
    .sort((a, b) => (a.email < b.email ? -1 : a.email > b.email ? 1 : 0));

  const before = readLocal();
  const beforeSet = new Set(before.map((m) => String(m.email || "").toLowerCase()));
  const afterSet = new Set(members.map((m) => m.email));

  console.log(`Firestore 멤버 ${members.length}명`);
  for (const m of members) {
    const isNew = !beforeSet.has(m.email);
    console.log(
      `  ${isNew ? "+" : " "} ${m.email}  ${m.nickname || "(표시명 없음)"}  ${m.role}`
    );
  }
  for (const m of before) {
    const email = String(m.email || "").toLowerCase();
    if (!afterSet.has(email)) console.log(`  - ${email} (Firestore 에 없어 거울에서 제거)`);
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
