#!/usr/bin/env node
/**
 * 멤버 명부에 구글 계정명(googleName)을 채운다. 한 번 돌리면 되는 보충용이다.
 *
 * 관리 탭은 굵은 글씨로 사람 이름을, 그 뒤에 연결된 카톡 표시명을 보여준다.
 * 이름은 승인할 때(신청서의 displayName)와 로그인할 때(ensureClaim) 채워지는데,
 * 그 전에 들어온 멤버는 비어 있다. Auth 계정의 displayName 으로 메운다.
 *
 * 한 번도 로그인하지 않은 사람은 Auth 계정이 없어 건너뛴다 — 첫 로그인에 채워진다.
 *
 * 사용
 *   node scripts/backfill_google_names.js --dry-run
 *   node scripts/backfill_google_names.js
 */
const fs = require("fs");
const admin = require("firebase-admin");

const KEY = require("./sa_key");
const PROJECT_ID = "katok-crawling-project";
const DRY = process.argv.slice(2).includes("--dry-run");

function init() {
  const credential = fs.existsSync(KEY)
    ? admin.credential.cert(require(KEY))
    : admin.credential.applicationDefault();
  admin.initializeApp({ credential, projectId: PROJECT_ID });
}

async function main() {
  init();
  const snap = await admin.firestore().collection("members").get();
  let filled = 0, same = 0, noAuth = 0, noName = 0;
  for (const doc of snap.docs) {
    let user;
    try {
      user = await admin.auth().getUserByEmail(doc.id);
    } catch (e) {
      if (e.code !== "auth/user-not-found") throw e;
      noAuth++;
      continue;
    }
    const name = String(user.displayName || "").trim().slice(0, 60);
    if (!name) { noName++; continue; }
    if (name === (doc.data() || {}).googleName) { same++; continue; }
    if (!DRY) await doc.ref.set({ googleName: name }, { merge: true });
    filled++;
  }
  // 이름·이메일은 찍지 않는다 — 이 출력은 로그로 남는다.
  console.log(`${DRY ? "[미리보기] " : ""}멤버 ${snap.size}명: 채움 ${filled} · 이미 같음 ${same}` +
    ` · 로그인 이력 없음 ${noAuth} · 구글 이름 없음 ${noName}`);
}

main().catch((e) => { console.error(e); process.exit(1); });
