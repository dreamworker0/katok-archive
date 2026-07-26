/**
 * 멤버 승인·권한 부여 (P2)
 *
 * 왜 Functions 가 필요한가
 *   Storage 규칙은 Firestore 를 읽을 수 없다. P1 에서는 그래서 멤버 이메일을
 *   storage.rules 에 박아 넣었고, 승인할 때마다 규칙을 재배포해야 했다. 브라우저는
 *   재배포를 할 수 없으니 승인이 늘 로컬 터미널 일이었다.
 *
 *   Custom Claims 로 바꾸면 규칙이 `request.auth.token.member == true` 한 줄이 되어
 *   멤버가 바뀌어도 재배포가 없다. 그리고 클레임은 Admin SDK 로만 붙일 수 있으므로
 *   그 일을 하는 서버 조각이 필요하다 — 이 파일이 그것이다.
 *
 * 여기 있는 것
 *   approveClaim  관리자: 신청 승인 → members 문서 + 클레임 + 신청서 정리
 *   rejectClaim   관리자: 신청 반려
 *   ensureClaim   본인: members 에 있는데 클레임이 없으면 스스로 받아간다
 *
 * ensureClaim 이 필요한 이유
 *   멤버는 웹 승인 말고도 여러 경로로 생긴다 — config/members.json 을 손으로 고치고
 *   업로더를 돌리는 기존 방식이 그대로 남아 있다. 그렇게 들어온 사람은 클레임이
 *   없어 이미지가 403 이 된다. 로그인할 때마다 본인이 확인해 받아가게 해서
 *   "어느 경로로 멤버가 됐든 결국 열린다"를 보장한다.
 */
const { onCall, HttpsError } = require("firebase-functions/v2/https");
const { setGlobalOptions } = require("firebase-functions/v2");
const admin = require("firebase-admin");

admin.initializeApp();
setGlobalOptions({ region: "asia-northeast3", maxInstances: 3 });

const db = () => admin.firestore();

/** 호출자가 로그인했고 이메일이 확인된 계정인지. */
function callerEmail(request) {
  const auth = request.auth;
  if (!auth || !auth.token || !auth.token.email) {
    throw new HttpsError("unauthenticated", "로그인이 필요합니다.");
  }
  if (auth.token.email_verified !== true) {
    throw new HttpsError("permission-denied", "이메일이 확인되지 않은 계정입니다.");
  }
  return String(auth.token.email).toLowerCase();
}

/** 관리자인지 members 문서로 확인한다.
 *  클레임의 admin 플래그를 믿지 않는다 — 권한을 내렸는데 토큰이 아직 안 바뀐
 *  사람이 승인 권한을 계속 쓰는 상황을 막아야 한다. */
async function requireAdmin(request) {
  const email = callerEmail(request);
  const snap = await db().collection("members").doc(email).get();
  if (!snap.exists || (snap.data() || {}).role !== "admin") {
    throw new HttpsError("permission-denied", "관리자만 할 수 있습니다.");
  }
  return email;
}

/** 이메일로 Auth 사용자를 찾아 클레임을 붙인다.
 *  한 번도 로그인한 적 없으면 계정이 없다 — 그때는 조용히 넘어간다.
 *  나중에 그 사람이 로그인하면 ensureClaim 이 대신 붙여준다. */
async function applyClaim(email, isAdmin) {
  let user;
  try {
    user = await admin.auth().getUserByEmail(email);
  } catch (e) {
    if (e.code === "auth/user-not-found") return { applied: false, reason: "로그인 이력 없음" };
    throw e;
  }
  await admin.auth().setCustomUserClaims(user.uid, { member: true, admin: !!isAdmin });
  return { applied: true, uid: user.uid };
}

function normalizeEmail(value) {
  const email = String(value || "").trim().toLowerCase();
  if (!email || email.indexOf("@") === -1) {
    throw new HttpsError("invalid-argument", "이메일이 올바르지 않습니다.");
  }
  return email;
}

exports.approveClaim = onCall(async (request) => {
  const admins = await requireAdmin(request);
  const email = normalizeEmail(request.data && request.data.email);
  const role = request.data && request.data.role === "admin" ? "admin" : "user";

  const claimSnap = await db().collection("claims").doc(email).get();
  const claimed = claimSnap.exists ? claimSnap.data() : null;
  const nickname = String(
    (request.data && request.data.nickname) || (claimed && claimed.nickname) || ""
  ).trim();

  if (!nickname) {
    throw new HttpsError("invalid-argument",
      "대화방 표시명이 없습니다. 신청서가 없으면 nickname 을 함께 보내야 합니다.");
  }

  await db().collection("members").doc(email).set(
    { email, name: nickname, nickname, role, approvedBy: admins, approvedAt: new Date().toISOString() },
    { merge: true }
  );
  const claim = await applyClaim(email, role === "admin");
  if (claimSnap.exists) await claimSnap.ref.delete();

  return { ok: true, email, nickname, role, claim };
});

exports.rejectClaim = onCall(async (request) => {
  await requireAdmin(request);
  const email = normalizeEmail(request.data && request.data.email);
  await db().collection("claims").doc(email).delete();
  return { ok: true, email };
});

/** 기존 멤버의 역할을 바꾼다 (관리자 지정·해제).
 *
 *  마지막 관리자는 내리지 못하게 막는다 — 관리자가 0명이 되면 웹으로는 아무도
 *  되돌릴 수 없고, 로컬 스크립트를 아는 사람만 복구할 수 있다.
 */
exports.setMemberRole = onCall(async (request) => {
  const caller = await requireAdmin(request);
  const email = normalizeEmail(request.data && request.data.email);
  const role = request.data && request.data.role === "admin" ? "admin" : "user";

  const ref = db().collection("members").doc(email);
  const snap = await ref.get();
  if (!snap.exists) {
    throw new HttpsError("not-found", "멤버가 아닙니다: " + email);
  }
  const current = (snap.data() || {}).role || "user";
  if (current === role) return { ok: true, email, role, changed: false };

  if (current === "admin" && role !== "admin") {
    const admins = await db().collection("members").where("role", "==", "admin").get();
    if (admins.size <= 1) {
      throw new HttpsError("failed-precondition",
        "마지막 관리자는 내릴 수 없습니다. 다른 사람을 먼저 관리자로 지정하세요.");
    }
  }

  await ref.set({ role, roleChangedBy: caller, roleChangedAt: new Date().toISOString() },
    { merge: true });
  const claim = await applyClaim(email, role === "admin");
  return { ok: true, email, role, changed: true, claim };
});

exports.ensureClaim = onCall(async (request) => {
  const email = callerEmail(request);
  const snap = await db().collection("members").doc(email).get();
  if (!snap.exists) {
    // 멤버가 아니면 클레임을 주지 않는다. 신청 화면으로 가야 한다.
    return { member: false };
  }
  const role = (snap.data() || {}).role || "user";
  const existing = (request.auth.token.member === true)
    && (request.auth.token.admin === (role === "admin"));
  if (existing) return { member: true, refreshed: false, role };

  await applyClaim(email, role === "admin");
  // 클라이언트는 getIdToken(true) 로 토큰을 새로 받아야 반영된다
  return { member: true, refreshed: true, role };
});
