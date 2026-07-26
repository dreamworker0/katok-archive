#!/usr/bin/env node
/**
 * 열람 신청(claims/) 조회·승인·반려 — 관리자 로컬 도구.
 *
 * 승인은 관리자 페이지에서도 할 수 있다. 이 스크립트는 그 대체가 아니라 보조다 —
 * 웹이 막혔을 때, 여러 건을 한 번에 처리할 때, 명단 대조를 자세히 보고 싶을 때 쓴다.
 *
 * Custom Claims 로 옮긴 뒤로 storage.rules 재배포는 필요 없다. 클레임만 붙이면
 * 이미지까지 곧바로 열린다.
 *
 * 사용
 *   node scripts/approve_claims.js                          신청 목록 (명단 대조 포함)
 *   node scripts/approve_claims.js --approve a@x.com        승인 + 발행까지
 *   node scripts/approve_claims.js --approve a@x.com,b@y.com
 *   node scripts/approve_claims.js --approve a@x.com --nickname "홍길동"
 *   node scripts/approve_claims.js --approve a@x.com --role admin
 *   node scripts/approve_claims.js --reject a@x.com         신청 삭제
 *   node scripts/approve_claims.js --remove a@x.com         탈퇴 (권한 회수 + 수집 중단)
 *   node scripts/approve_claims.js --remove a@x.com --keep-collecting
 *   node scripts/approve_claims.js --approve a@x.com --nickname "홍길동" --role admin
 *                                                           기존 멤버를 관리자로
 *   node scripts/approve_claims.js --approve a@x.com --no-publish
 *   node scripts/approve_claims.js --approve a@x.com --dry-run
 */
const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");
const admin = require("firebase-admin");

const ROOT = path.resolve(__dirname, "..");
const KEY = path.join(ROOT, "serviceAccountKey.json");
const MEMBERS = path.join(ROOT, "config", "members.json");
const PARTICIPANTS = path.join(ROOT, "output", "participants.json");
const PROJECT_ID = "katok-crawling-project";

// ────────────────────────── 인자 ──────────────────────────

function parseArgs(argv) {
  const out = { approve: [], reject: [], remove: [], nickname: null, role: "user",
                publish: true, dry: false, keepCollecting: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const list = (v) => String(v || "").split(",").map((s) => s.trim().toLowerCase()).filter(Boolean);
    if (a === "--approve") out.approve.push(...list(argv[++i]));
    else if (a === "--reject") out.reject.push(...list(argv[++i]));
    else if (a === "--remove") out.remove.push(...list(argv[++i]));
    else if (a === "--nickname") out.nickname = argv[++i];
    else if (a === "--role") out.role = argv[++i] === "admin" ? "admin" : "user";
    else if (a === "--no-publish") out.publish = false;
    else if (a === "--keep-collecting") out.keepCollecting = true;
    else if (a === "--dry-run") out.dry = true;
    else if (a === "--help" || a === "-h") out.help = true;
    else {
      console.error(`알 수 없는 옵션: ${a}`);
      process.exit(1);
    }
  }
  return out;
}

// ────────────────────────── 로컬 파일 ──────────────────────────

function readJson(p, fallback) {
  if (!fs.existsSync(p)) return fallback;
  return JSON.parse(fs.readFileSync(p, "utf8"));
}

function loadParticipants() {
  const raw = readJson(PARTICIPANTS, { participants: [] });
  const byNick = new Map();
  for (const p of raw.participants || []) byNick.set(p.nickname, p);
  return byNick;
}

/** 오타를 잡아주려는 느슨한 후보 찾기 — 부분 문자열 양방향. */
function similarNicknames(nickname, byNick) {
  const n = (nickname || "").trim();
  if (!n) return [];
  const hits = [];
  for (const known of byNick.keys()) {
    if (known === n) continue;
    if (known.includes(n) || n.includes(known)) hits.push(known);
  }
  return hits.slice(0, 5);
}

function loadMembersFile() {
  const raw = readJson(MEMBERS, null);
  if (raw) {
    if (!Array.isArray(raw.members)) raw.members = [];
    return raw;
  }
  return {
    _comment: [
      "실제 멤버 명부. .gitignore 되어 커밋되지 않는다.",
      "scripts/approve_claims.js 가 승인할 때 여기에 추가한다.",
    ],
    members: [],
  };
}

function saveMembersFile(doc) {
  fs.writeFileSync(MEMBERS, JSON.stringify(doc, null, 2) + "\n", "utf8");
}

// ────────────────────────── Firebase ──────────────────────────

function init() {
  if (fs.existsSync(KEY)) {
    const sa = require(KEY);
    if (sa.project_id && sa.project_id !== PROJECT_ID) {
      console.error(`키의 프로젝트(${sa.project_id})가 대상(${PROJECT_ID})과 다릅니다.`);
      process.exit(1);
    }
    admin.initializeApp({ credential: admin.credential.cert(sa), projectId: PROJECT_ID });
    return;
  }
  try {
    admin.initializeApp({
      credential: admin.credential.applicationDefault(),
      projectId: PROJECT_ID,
    });
  } catch (e) {
    console.error(
      "인증 정보를 찾지 못했습니다.\n" +
      `  (A) 서비스 계정 키를 ${KEY} 로 저장하거나\n` +
      "  (B) gcloud auth application-default login"
    );
    process.exit(1);
  }
}

async function fetchClaims(db) {
  const snap = await db.collection("claims").orderBy("requestedAt").get();
  return snap.docs.map((d) => {
    const data = d.data() || {};
    let at = "";
    if (data.requestedAt && typeof data.requestedAt.toDate === "function") {
      at = data.requestedAt.toDate().toISOString().slice(0, 16).replace("T", " ");
    }
    return {
      email: d.id,
      nickname: data.nickname || "",
      displayName: data.displayName || "",
      requestedAt: at,
    };
  });
}

// ────────────────────────── 출력 ──────────────────────────

function listClaims(claims, byNick, memberEmails) {
  if (!claims.length) {
    console.log("열람 신청이 없습니다.");
    return;
  }
  console.log(`열람 신청 ${claims.length}건\n`);
  claims.forEach((c, i) => {
    console.log(`  ${i + 1}) ${c.email}`);
    console.log(`     적어낸 이름 : ${c.nickname}`);
    if (c.displayName) console.log(`     구글 계정명 : ${c.displayName}`);
    if (c.requestedAt) console.log(`     신청 시각   : ${c.requestedAt} (UTC)`);

    const hit = byNick.get(c.nickname);
    if (hit) {
      console.log(`     명단 대조   : ○ 참여자 '${hit.nickname}' (메시지 ${hit.message_count}건, 마지막 ${hit.last_timestamp.slice(0, 10)})`);
    } else {
      const near = similarNicknames(c.nickname, byNick);
      console.log(
        `     명단 대조   : × 참여자 명단에 없음` +
        (near.length ? ` — 비슷한 이름: ${near.join(", ")}` : "")
      );
    }
    if (memberEmails.has(c.email)) {
      console.log("     상태        : 이미 멤버 (신청서만 남아 있음 → --reject 로 정리)");
    }
    console.log("");
  });
  console.log("승인:  node scripts/approve_claims.js --approve <이메일>");
  console.log("반려:  node scripts/approve_claims.js --reject  <이메일>");
  console.log("이름을 고쳐서 승인하려면 --nickname \"정확한이름\" 을 함께 준다.");
}

// ────────────────────────── 발행 ──────────────────────────

function run(cmd, args) {
  console.log(`\n$ ${cmd} ${args.join(" ")}`);
  const r = spawnSync(cmd, args, { cwd: ROOT, stdio: "inherit", shell: true });
  if (r.status !== 0) {
    console.error(`\n실패: ${cmd} (종료 코드 ${r.status})`);
    console.error("members.json 은 이미 갱신되었습니다. 원인을 고친 뒤 아래를 직접 실행하세요.");
    console.error("  python -m scripts.build_firestore_payload");
    console.error("  node scripts/upload_firestore.js --skip-images");
    process.exit(1);
  }
}

/** 발행본을 다시 만든다. 멤버 문서는 여기서 올라가지 않는다 —
 *  명부의 주인은 Firestore 이고, writeMember 가 이미 직접 썼다. */
function publish() {
  run("python", ["-m", "scripts.build_firestore_payload"]);
  run("node", ["scripts/upload_firestore.js", "--skip-images"]);
}

/** Firestore 멤버 문서를 직접 쓴다.
 *  발행 단계에 기대면 웹에서 승인한 사람과 어긋나 사고가 난다. */
async function writeMember(db, email, nickname, role) {
  // 표시명은 목록으로 둔다 — 카톡에서 이름을 바꾼 사람은 여러 개를 갖는다.
  // 기존 연결이 있으면 덮어쓰지 않고 합친다 (CLI 로 역할만 바꿀 때 연결이 날아가면 안 된다).
  const ref = db.collection("members").doc(email);
  const prev = await ref.get();
  const had = prev.exists ? (prev.data().nicknames || []) : [];
  const nicknames = [nickname, ...had].filter(
    (n, i, arr) => n && arr.indexOf(n) === i
  );
  await ref.set(
    { email, name: nicknames[0], nickname: nicknames[0], nicknames, role,
      approvedAt: new Date().toISOString() },
    { merge: true }
  );
}

/** Auth 계정에 클레임을 붙인다 — 이게 있어야 이미지가 열린다.
 *  한 번도 로그인한 적 없으면 계정이 없다. 그 경우 첫 로그인 때
 *  ensureClaim Function 이 대신 붙여주므로 실패로 보지 않는다. */
async function applyClaim(email, isAdmin) {
  try {
    const user = await admin.auth().getUserByEmail(email);
    await admin.auth().setCustomUserClaims(user.uid, { member: true, admin: !!isAdmin });
    console.log(`  클레임 부여: ${email} (${isAdmin ? "admin" : "user"})`);
  } catch (e) {
    if (e.code === "auth/user-not-found") {
      console.log(`  ${email}: 로그인 이력 없음 — 첫 로그인 때 자동 부여됩니다.`);
      return;
    }
    throw e;
  }
}

// ────────────────────────── 승인·반려 ──────────────────────────

function approve(args, claims, byNick) {
  const doc = loadMembersFile();
  const byEmail = new Map(
    doc.members.map((m) => [String(m.email || "").toLowerCase(), m])
  );
  const claimByEmail = new Map(claims.map((c) => [c.email, c]));

  let changed = 0;
  for (const email of args.approve) {
    const claim = claimByEmail.get(email);
    const nickname = (args.nickname || (claim && claim.nickname) || "").trim();

    if (!claim && !args.nickname) {
      console.error(`× ${email}: 신청서가 없습니다. --nickname 으로 이름을 직접 주세요.`);
      continue;
    }
    if (!nickname) {
      console.error(`× ${email}: 이름이 비어 있습니다.`);
      continue;
    }
    if (!byNick.has(nickname)) {
      const near = similarNicknames(nickname, byNick);
      console.warn(
        `! ${email}: '${nickname}' 은 참여자 명단에 없습니다` +
        (near.length ? ` (비슷한 이름: ${near.join(", ")})` : "") +
        " — 그대로 등록합니다."
      );
    }

    const existing = byEmail.get(email);
    if (existing) {
      existing.nickname = nickname;
      existing.name = existing.name || nickname;
      if (args.role === "admin") existing.role = "admin";
      console.log(`○ ${email}: 기존 멤버 정보를 갱신 (${nickname})`);
    } else {
      doc.members.push({ email: email, name: nickname, nickname: nickname, role: args.role });
      console.log(`○ ${email}: 멤버로 추가 (${nickname}, ${args.role})`);
    }
    changed++;
  }

  if (!changed) return 0;
  if (args.dry) {
    console.log("\n--dry-run: members.json 을 수정하지 않았습니다.");
    return 0;
  }
  saveMembersFile(doc);
  console.log(`\nconfig/members.json 갱신 — 총 ${doc.members.length}명`);
  return changed;
}

/** 멤버 자격 회수 — Firestore 문서 삭제 + 클레임 해제.
 *  둘 다 해야 한다. 문서만 지우면 이미지가 계속 열리고, 클레임만 지우면
 *  대화가 계속 열린다. */
async function removeMembers(db, args) {
  for (const email of args.remove) {
    const snap = await db.collection("members").doc(email).get();
    const data = snap.exists ? snap.data() : {};
    const nicknames = Array.isArray(data.nicknames) && data.nicknames.length
      ? data.nicknames
      : (data.nickname ? [data.nickname] : []);

    if (args.dry) {
      console.log(`(dry-run) ${email}: 탈퇴 처리 예정 (표시명 ${nicknames.join(", ") || "없음"})` +
        (args.keepCollecting ? " — 수집 유지" : " — 수집 중단"));
      continue;
    }

    // 탈퇴하면 앞으로의 글도 수집하지 않는다. 나간 사람의 말을 계속 모으는 건
    // 열람 권한을 거둔 것과 앞뒤가 맞지 않는다. (--keep-collecting 으로 끌 수 있다.
    // 계정을 잘못 연결했다가 되돌리는 경우처럼, 사람은 그대로 방에 있는 상황용.)
    if (args.keepCollecting) {
      console.log(`  ${email}: 수집은 계속합니다 (--keep-collecting)`);
    } else if (nicknames.length) {
      await db.collection("preferences").doc(email).set(
        { collection: "none", nicknames, updatedAt: new Date() },
        { merge: true }
      );
      console.log(`  ${email}: 수집 거부로 전환 (${nicknames.join(", ")})`);
    }

    // 걸어둔 의사표시에 표시명을 박아둔다. 멤버 문서가 사라지면 이메일→표시명
    // 고리가 끊겨, 권한만 거뒀을 뿐인데 "내 글 내려달라"가 조용히 취소된다.
    for (const name of ["preferences", "deletionRequests"]) {
      const ref = db.collection(name).doc(email);
      const s = await ref.get();
      if (!s.exists) continue;
      const d = s.data() || {};
      const meaningful = name === "preferences"
        ? (d.collection && d.collection !== "public")
        : true;
      if (meaningful && nicknames.length) {
        await ref.set({ nicknames }, { merge: true });
        console.log(`  ${email}: ${name} 유지 (표시명 ${nicknames.join(", ")})`);
      }
    }

    await db.collection("members").doc(email).delete();
    try {
      const user = await admin.auth().getUserByEmail(email);
      await admin.auth().setCustomUserClaims(user.uid, { member: false, admin: false });
      console.log(`× ${email}: 멤버 문서 삭제 + 클레임 해제`);
    } catch (e) {
      if (e.code !== "auth/user-not-found") throw e;
      console.log(`× ${email}: 멤버 문서 삭제 (Auth 계정 없음)`);
    }
  }
}

async function reject(db, args) {
  for (const email of args.reject) {
    if (args.dry) {
      console.log(`(dry-run) ${email}: 신청 삭제 예정`);
      continue;
    }
    await db.collection("claims").doc(email).delete();
    console.log(`× ${email}: 신청을 삭제했습니다.`);
  }
}

// ────────────────────────── main ──────────────────────────

function claimByEmailFor(claims, email) {
  return claims.find((c) => c.email === email) || null;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    console.log(fs.readFileSync(__filename, "utf8").split("*/")[0]);
    return;
  }

  const byNick = loadParticipants();
  if (!byNick.size) {
    console.warn("[주의] output/participants.json 이 없어 명단 대조를 건너뜁니다.\n");
  }

  init();
  const db = admin.firestore();
  const claims = await fetchClaims(db);

  if (!args.approve.length && !args.reject.length && !args.remove.length) {
    const doc = loadMembersFile();
    const memberEmails = new Set(
      doc.members.map((m) => String(m.email || "").toLowerCase())
    );
    listClaims(claims, byNick, memberEmails);
    return;
  }

  if (args.reject.length) await reject(db, args);
  if (args.remove.length) {
    await removeMembers(db, args);
    if (!args.dry) run("node", ["scripts/sync_members.js"]);
  }

  if (args.approve.length) {
    const changed = approve(args, claims, byNick);
    if (changed && !args.dry) {
      for (const email of args.approve) {
        const claim = claimByEmailFor(claims, email);
        const nickname = (args.nickname || (claim && claim.nickname) || "").trim();
        await writeMember(db, email, nickname, args.role);
        await applyClaim(email, args.role === "admin");
      }
      if (args.publish) {
        publish();
        // 발행이 끝난 뒤에 신청서를 지운다 — 중간에 실패하면 재시도할 수 있도록
        for (const email of args.approve) {
          await db.collection("claims").doc(email).delete().catch(() => {});
        }
        console.log("\n승인 완료. 신청자에게 새로고침을 안내하세요.");
      } else {
        console.log("\n--no-publish: 아래를 직접 실행해야 발행본에 반영됩니다.");
        console.log("  python -m scripts.build_firestore_payload");
        console.log("  node scripts/upload_firestore.js --skip-images");
      }
    }
  }
}

main().catch((e) => {
  console.error("\n실패:", e.message);
  process.exit(1);
});
