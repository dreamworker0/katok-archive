#!/usr/bin/env node
/**
 * config/members.json 의 멤버에게 Custom Claims 를 붙인다.
 *
 * 왜 필요한가
 *   storage.rules 가 `request.auth.token.member == true` 로 바뀌면 클레임이 없는
 *   사람은 이미지가 403 이 된다. 규칙을 바꾸기 **전에** 이 스크립트를 돌려 기존
 *   멤버를 먼저 채워야 서비스가 끊기지 않는다.
 *
 *   평소에는 승인 Function(approveClaim)이 알아서 붙이므로 쓸 일이 없다.
 *   members.json 을 손으로 고쳤을 때, 그리고 클레임이 어긋났는지 볼 때 쓴다.
 *
 * 한 번도 로그인한 적 없는 사람은 Auth 계정이 없어 지금 붙일 수 없다.
 * 그 사람이 처음 로그인하면 ensureClaim Function 이 대신 붙여준다.
 *
 * 사용
 *   node scripts/sync_claims.js --dry-run   현재 상태만 확인
 *   node scripts/sync_claims.js             어긋난 것만 맞춤
 */
const fs = require("fs");
const path = require("path");
const admin = require("firebase-admin");

const ROOT = path.resolve(__dirname, "..");
const KEY = path.join(ROOT, "serviceAccountKey.json");
const MEMBERS = path.join(ROOT, "config", "members.json");
const PROJECT_ID = "katok-crawling-project";

const DRY = process.argv.slice(2).includes("--dry-run");

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

function loadMembers() {
  if (!fs.existsSync(MEMBERS)) {
    console.error("config/members.json 이 없습니다.");
    process.exit(1);
  }
  const raw = JSON.parse(fs.readFileSync(MEMBERS, "utf8"));
  return (raw.members || [])
    .map((m) => ({
      email: String(m.email || "").trim().toLowerCase(),
      role: m.role === "admin" ? "admin" : "user",
    }))
    .filter((m) => m.email);
}

async function main() {
  init();
  const members = loadMembers();
  console.log(`멤버 ${members.length}명 확인\n`);

  let fixed = 0, ok = 0, missing = 0;

  for (const m of members) {
    const want = { member: true, admin: m.role === "admin" };
    let user;
    try {
      user = await admin.auth().getUserByEmail(m.email);
    } catch (e) {
      if (e.code === "auth/user-not-found") {
        // 첫 로그인 때 ensureClaim 이 붙여준다 — 실패가 아니다
        console.log(`  - ${m.email}: 로그인 이력 없음 (첫 로그인 때 자동 부여)`);
        missing++;
        continue;
      }
      throw e;
    }

    const have = user.customClaims || {};
    if (have.member === want.member && have.admin === want.admin) {
      console.log(`  ○ ${m.email}: 이미 맞음 (${m.role})`);
      ok++;
      continue;
    }
    if (DRY) {
      console.log(`  → ${m.email}: ${JSON.stringify(have)} → ${JSON.stringify(want)}`);
    } else {
      await admin.auth().setCustomUserClaims(user.uid, want);
      console.log(`  ✎ ${m.email}: 클레임 부여 (${m.role})`);
    }
    fixed++;
  }

  console.log(
    `\n맞음 ${ok} / ${DRY ? "고칠 것" : "고침"} ${fixed} / 로그인 이력 없음 ${missing}`
  );
  if (DRY) console.log("--dry-run: 아무것도 바꾸지 않았습니다.");
  else if (fixed) console.log("해당 사용자는 다시 로그인하거나 새로고침해야 반영됩니다.");
}

main().catch((e) => {
  console.error("\n실패:", e.message);
  process.exit(1);
});
