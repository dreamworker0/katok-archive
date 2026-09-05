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
 *   approveClaim    관리자: 신청 승인 → members 문서 + 클레임 + 신청서 정리
 *   rejectClaim     관리자: 신청 반려
 *   requestRefresh  관리자: '지금 갱신' — 실행이 아니라 요청만 적는다(아래 설명)
 *   ensureClaim     본인: members 에 있는데 클레임이 없으면 스스로 받아간다
 *
 * 동시 조작 (2026-09-05)
 *   관리자가 둘 이상이면 같은 문서를 동시에 고칠 수 있다. 판단과 쓰기는
 *   guards.js 로 옮겨 **트랜잭션 안에서** 한다. 여기 남은 것은 인증 확인과
 *   Auth 클레임처럼 트랜잭션 밖에서 해야 하는 일이다. 왜 그렇게 갈랐는지는
 *   guards.js 의 머리말에 적어 두었다.
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
const guards = require("./guards");

admin.initializeApp();
setGlobalOptions({ region: "asia-northeast3", maxInstances: 3 });

const db = () => admin.firestore();

/** guards.js 는 firebase 를 모른다. 그쪽 오류를 여기서 HttpsError 로 바꾼다. */
async function guarded(run) {
  try {
    return await run();
  } catch (e) {
    if (e instanceof guards.GuardError) throw new HttpsError(e.code, e.message);
    throw e;
  }
}

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

exports.approveClaim = onCall(async (request) => {
  const caller = await requireAdmin(request);
  // 명부·신청서 정리는 트랜잭션 안에서. 승인은 권한을 **올리기만** 한다 —
  // 화면의 승인 단추가 늘 보내는 "user" 로 기존 관리자가 내려가지 않는다
  // (guards.js 머리말 ③). 내리는 일은 setMemberRole 이 한다.
  const done = await guarded(() =>
    guards.approveClaim(db(), request.data, caller, new Date().toISOString()));
  // Auth 는 트랜잭션 **밖**이다. 여기서 끊겨도 ensureClaim 이 다음 로그인에 맞춘다.
  const claim = await applyClaim(done.email, done.role === "admin");

  return { ok: true, email: done.email, nicknames: done.nicknames, role: done.role, claim };
});

/** 표시명 연결을 다시 맞춘다.
 *
 *  카톡에서 이름을 바꿨거나, 승인할 때 엉뚱한 참여자에 붙였을 때 쓴다.
 *  연결이 어긋나면 '내 글 관리'에 남의 글이 보이거나 내 글이 안 보인다.
 */
exports.setMemberNicknames = onCall(async (request) => {
  const caller = await requireAdmin(request);
  const { email, nicknames } = await guarded(async () => ({
    email: guards.normalizeEmail(request.data && request.data.email),
    nicknames: guards.normalizeNicknames(request.data && request.data.nicknames),
  }));

  const ref = db().collection("members").doc(email);
  if (!(await ref.get()).exists) {
    throw new HttpsError("not-found", "멤버가 아닙니다: " + email);
  }
  await ref.set(
    {
      name: nicknames[0],
      nickname: nicknames[0],
      nicknames,
      nicknamesChangedBy: caller,
      nicknamesChangedAt: new Date().toISOString(),
    },
    { merge: true }
  );
  return { ok: true, email, nicknames };
});

exports.rejectClaim = onCall(async (request) => {
  await requireAdmin(request);
  const email = await guarded(async () => guards.normalizeEmail(request.data && request.data.email));
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
  // 세고-나서-쓰지 않는다. 둘이 동시에 서로를 내려도 관리자가 0명이 되지 않아야
  // 한다 — 확인과 쓰기가 한 트랜잭션 안에 있다 (guards.js 머리말 ②).
  const done = await guarded(() =>
    guards.setMemberRole(db(), request.data, caller, new Date().toISOString()));
  if (!done.changed) return { ok: true, ...done };
  // Auth 는 트랜잭션 밖이다 — 다시 도는 콜백 안에서 클레임을 붙이면 안 된다.
  const claim = await applyClaim(done.email, done.role === "admin");
  return { ok: true, ...done, claim };
});

/** 멤버 자격 회수(탈퇴 처리).
 *
 *  열람 권한만 거둔다. 그 사람이 걸어둔 **수집 거부·삭제 요청은 살려둔다** —
 *  권한을 회수한 것과 "내 글 내려달라"는 의사는 별개다.
 *
 *  살리려면 표시명을 남겨야 한다. 반영 파이프라인은 이메일→표시명을 멤버 명부에서
 *  찾는데, 멤버 문서가 사라지면 그 고리가 끊겨 요청이 조용히 무시된다. 그래서
 *  지우기 전에 표시명을 요청 문서에 박아둔다.
 */
exports.removeMember = onCall(async (request) => {
  const caller = await requireAdmin(request);
  const email = await guarded(async () => guards.normalizeEmail(request.data && request.data.email));

  if (email === caller) {
    throw new HttpsError("failed-precondition",
      "본인은 탈퇴 처리할 수 없습니다. 다른 관리자에게 부탁하세요.");
  }

  const snap = await db().collection("members").doc(email).get();
  if (!snap.exists) throw new HttpsError("not-found", "멤버가 아닙니다: " + email);

  const data = snap.data() || {};
  // 미리 걸러낸다 — 어차피 거절될 요청이 아래의 부작용(수집 거부 기록)을 남기지
  // 않게 한다. 확정은 아래 guards.removeMember 가 트랜잭션 안에서 다시 한다.
  if ((data.role || "user") === "admin" && !(await guards.countOtherAdmins(db(), email))) {
    throw new HttpsError("failed-precondition", "마지막 관리자는 탈퇴 처리할 수 없습니다.");
  }

  const nicknames = Array.isArray(data.nicknames) && data.nicknames.length
    ? data.nicknames
    : (data.nickname ? [data.nickname] : []);

  // 탈퇴하면 앞으로의 글도 수집하지 않는다. 나간 사람의 말을 계속 모으는 건
  // 열람 권한을 거둔 것과 앞뒤가 맞지 않는다.
  //
  // 과거 글은 건드리지 않는다 — 그건 '삭제 요청'이라는 별개의 의사표시다.
  // 수집 거부는 되돌려도 그 기간이 비므로, 화면에서 미리 알린 뒤에만 부른다.
  const stopCollecting = request.data && request.data.stopCollecting === false
    ? false
    : true;
  if (stopCollecting && nicknames.length) {
    await db().collection("preferences").doc(email).set(
      {
        collection: "none",
        nicknames,
        updatedAt: new Date(),
        stoppedBy: caller,
      },
      { merge: true }
    );
  }

  // 남은 의사표시에 표시명을 박아둔다 (Admin SDK 라 규칙 제한을 받지 않는다).
  // 멤버 문서가 사라지면 이메일→표시명 고리가 끊겨 요청이 조용히 무시된다.
  const kept = [];
  for (const name of ["preferences", "deletionRequests"]) {
    const doc = db().collection(name).doc(email);
    const s = await doc.get();
    if (!s.exists) continue;
    const d = s.data() || {};
    const meaningful = name === "preferences"
      ? (d.collection && d.collection !== "public")
      : true;
    if (!meaningful) continue;
    if (nicknames.length) await doc.set({ nicknames }, { merge: true });
    kept.push(name);
  }

  // 지우는 것만 트랜잭션이다. 위의 표시명 박아두기는 **먼저** 끝나 있어야 한다 —
  // 멤버 문서가 사라지면 이메일→표시명 고리가 끊긴다.
  //
  // 여기서 거절되는 경우(그 사이 다른 관리자가 나머지 관리자를 내렸다)에는 이미
  // 수집 거부가 기록된 채로 멤버는 남는다. 드물고, 틀리는 방향이 안전한 쪽이다
  // (덜 모으는 쪽). 화면에서 되돌릴 수 있다.
  await guarded(() => guards.removeMember(db(), email, { expectNicknames: nicknames }));

  let claimCleared = false;
  try {
    const user = await admin.auth().getUserByEmail(email);
    await admin.auth().setCustomUserClaims(user.uid, { member: false, admin: false });
    claimCleared = true;
  } catch (e) {
    if (e.code !== "auth/user-not-found") throw e;
  }

  return {
    ok: true, email, nicknames, claimCleared,
    stoppedCollecting: stopCollecting && nicknames.length > 0,
    keptRequests: kept, removedBy: caller,
  };
});

/** 주제(스레드) 하나를 발행에서 빼거나 되돌린다.
 *
 *  뺀 주제는 발행본에서 사라지므로 관리자에게도 안 보인다 — 목록을 따로 들고
 *  있지 않으면 되돌릴 방법이 없어진다. 그래서 제목까지 함께 적어둔다.
 */
exports.setThreadHidden = onCall(async (request) => {
  const caller = await requireAdmin(request);
  // 한 문서(settings/threads)에 목록을 담으므로 읽고-고쳐-쓰면 동시 조작이
  // 사라진다. 두 관리자가 서로 다른 주제를 동시에 숨겨도 둘 다 남아야 한다
  // (guards.js 머리말 ①).
  const done = await guarded(() =>
    guards.setThreadHidden(db(), request.data, caller, new Date().toISOString()));
  return { ok: true, ...done };
});

/* ---------- 지금 갱신 ----------
 *
 * 왜 갱신을 여기서 실행하지 않는가
 *   갱신의 본체는 카톡 창에 Ctrl+S 를 보내 대화를 내보내고, 로컬 output/ 을 고친 뒤
 *   발행하는 일이다. 클라우드에는 카톡도 output/ 도 없다. 그래서 이 함수는 "요청을
 *   적어두는" 일까지만 하고, 그 PC 에 상주하는 scripts/refresh_watcher.js 가
 *   settings/refresh 를 보고 있다가 받아서 실행한다.
 *
 *   따라서 버튼은 "갱신한다"가 아니라 "갱신하라고 남긴다"에 가깝다. PC 가 꺼져
 *   있으면 대기 상태로 남고, 오래 지나면 만료된다 — 화면이 그 사실을 그대로 보여준다.
 *
 * 겹쳐 돌지 못하게 막는 이유
 *   두 개가 동시에 발행에 들어가면 발행본이 반쪽 상태로 섞인다. 그래서 대기·진행
 *   중이면 새 요청을 거절한다. 다만 PC 가 꺼지거나 감시가 죽으면 상태가 영영
 *   '진행 중'으로 남을 수 있어, 오래된 것은 자동으로 놓아주고 force 로 강제 해제할
 *   길도 둔다. (run_daily.ps1 에도 파일 잠금이 있어 실제 동시 실행은 거기서 막힌다.)
 */

// 대기가 이만큼 지나면 'PC 가 못 받았다'로 보고 새 요청을 허용한다.
const REFRESH_QUEUE_STALE_MS = 30 * 60 * 1000;
// 실행이 이만큼 지나면 죽은 것으로 본다. 작업 스케줄러 시간 제한이 1시간이므로
// 그보다 넉넉히 잡아, 살아 있는 실행을 죽었다고 오판하지 않는다.
const REFRESH_RUN_STALE_MS = 90 * 60 * 1000;

/** ISO 문자열이든 Timestamp 든 밀리초로. 못 읽으면 null (= 아주 오래된 것으로 취급). */
function millisOf(value) {
  if (!value) return null;
  if (typeof value.toMillis === "function") return value.toMillis();
  const t = Date.parse(String(value));
  return Number.isNaN(t) ? null : t;
}

exports.requestRefresh = onCall(async (request) => {
  const caller = await requireAdmin(request);
  const force = !!(request.data && request.data.force === true);
  const ref = db().collection("settings").doc("refresh");
  const now = Date.now();

  const outcome = await db().runTransaction(async (tx) => {
    const snap = await tx.get(ref);
    const cur = snap.exists ? (snap.data() || {}) : {};
    const status = cur.status || "idle";
    const since = millisOf(status === "running" ? cur.startedAt : cur.requestedAt);
    const age = since === null ? Infinity : now - since;

    if (!force && status === "queued" && age < REFRESH_QUEUE_STALE_MS) {
      throw new HttpsError("failed-precondition",
        "이미 갱신을 요청해 두었습니다. PC 가 요청을 받으면 시작합니다.");
    }
    if (!force && status === "running" && age < REFRESH_RUN_STALE_MS) {
      throw new HttpsError("failed-precondition",
        "지금 갱신이 진행 중입니다. 끝난 뒤에 다시 눌러 주세요.");
    }

    // 감시 스크립트는 requestId 로 '이미 처리한 요청'을 가린다. 같은 값이 두 번
    // 나오면 재시작한 감시가 끝난 일을 또 돌리므로, 매번 새로 만든다.
    const requestId = "r-" + now;
    tx.set(ref, {
      requestId,
      status: "queued",
      requestedBy: caller,
      requestedAt: new Date().toISOString(),
      startedAt: null,
      finishedAt: null,
      exitCode: null,
      newMessages: null,
      message: "",
      // 무엇을 밀어냈는지 남긴다 — 강제 해제가 잦으면 감시가 불안한 것이다.
      tookOverFrom: (status === "queued" || status === "running") ? status : null,
    }, { merge: true });

    return { requestId, previous: status, previousAgeMs: age === Infinity ? null : age };
  });

  return { ok: true, ...outcome };
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
