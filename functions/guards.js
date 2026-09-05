/**
 * 관리자 조작의 **동시 실행 안전장치** (2026-09-05)
 *
 * 왜 따로 뺐는가
 *   index.js 는 firebase-functions·firebase-admin 을 불러온다. 그것을 검사에서
 *   불러오려면 functions/node_modules 가 있어야 하는데, CI 는 뿌리에서
 *   `npm ci --omit=dev` 만 한다 — functions 쪽은 설치되지 않는다. 그래서
 *   **의존성이 하나도 없는 이 파일**로 판단 로직만 옮겼다. 검사(tests/
 *   admin_guards.test.js)는 가짜 Firestore 를 물려 이 파일만 돌린다.
 *   index.js 는 이것을 부르고 오류를 HttpsError 로 바꾸는 일만 한다.
 *
 * 무엇을 고쳤는가
 *   ① setThreadHidden 이 `settings/threads` 한 문서를 읽고-고쳐-썼다. 두 관리자가
 *      서로 다른 주제를 동시에 숨기면 나중 것이 먼저 것을 덮어써 **한 명의 조작이
 *      사라졌다**. 화면은 둘 다 "숨겼습니다" 라고 말한다.
 *   ② 마지막 관리자 보호가 세고-나서-쓰는 방식이었다. 둘이 동시에 서로를 내리면
 *      둘 다 "다른 관리자가 있다" 를 보고 통과해 **관리자가 0명**이 될 수 있었다.
 *      그 상태는 웹으로 되돌릴 수 없다.
 *   ③ approveClaim 이 이미 멤버인 사람에게도 돌 수 있는데, 화면의 승인 단추가 늘
 *      보내는 role="user" 를 그대로 받아 **기존 관리자를 조용히 내렸다** —
 *      마지막 관리자 보호를 우회하는 길이었다. 신청서는 멤버도 다시 낼 수
 *      있으므로(규칙이 막지 않는다) 닿을 수 있는 길이다. 이제 승인은 권한을
 *      올리기만 한다 — 내리는 일은 setMemberRole 한 곳에서만 한다.
 *
 * 원칙
 *   Auth(setCustomUserClaims) 같은 **바깥 부작용은 트랜잭션 안에 넣지 않는다.**
 *   트랜잭션 콜백은 충돌하면 다시 돈다 — 그 안에서 클레임을 붙이면 여러 번 붙는다.
 *   Firestore 가 확정된 뒤에 바깥일을 한다. 그 사이에서 끊기면 Firestore 만 바뀐
 *   상태가 남는데, 그것은 ensureClaim 이 다음 로그인에 스스로 맞춘다.
 */

/** 부르는 쪽(index.js)이 HttpsError 로 바꿔 던진다. */
class GuardError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "GuardError";
    this.code = code;
  }
}

function normalizeEmail(value) {
  const email = String(value || "").trim().toLowerCase();
  if (!email || email.indexOf("@") === -1) {
    throw new GuardError("invalid-argument", "이메일이 올바르지 않습니다.");
  }
  return email;
}

/** 대화방 표시명 목록을 정리한다.
 *
 *  한 사람이 표시명을 여러 개 가질 수 있다 — 카톡에서 이름을 바꾸면 그 시점을
 *  기준으로 참여자가 둘로 갈리기 때문이다. 하나만 잡으면 내 글의 절반이 사라진다.
 */
function normalizeNicknames(value, fallback) {
  let list = Array.isArray(value) ? value : (value ? [value] : []);
  if (!list.length && fallback) list = [fallback];
  const out = [];
  for (const raw of list) {
    const n = String(raw || "").trim();
    if (n && n.length <= 40 && out.indexOf(n) === -1) out.push(n);
  }
  if (!out.length) throw new GuardError("invalid-argument", "대화방 표시명이 없습니다.");
  if (out.length > 10) {
    throw new GuardError("invalid-argument", "표시명은 10개까지만 묶을 수 있습니다.");
  }
  return out;
}

/** 주지 않았으면 null — '기존 역할을 그대로 둔다' 는 뜻이다. */
function wantedRole(value) {
  if (value === "admin") return "admin";
  if (value === "user") return "user";
  return null;
}

function normalizeThreadId(value) {
  const id = String(value || "").trim();
  if (!/^[A-Za-z0-9_-]{1,60}$/.test(id)) {
    throw new GuardError("invalid-argument", "주제 ID 가 올바르지 않습니다.");
  }
  return id;
}

const HIDDEN_LIMIT = 500;

/** 이 사람 말고 관리자가 또 있는가. 없으면 내리지도 지우지도 못한다.
 *
 *  트랜잭션 안에서 **읽기로** 확인한다. 이 질의의 결과가 읽기 집합에 들어가므로,
 *  그 사이 다른 트랜잭션이 관리자 문서를 건드리면 여기가 다시 돌아 새 사실로
 *  다시 판단한다. 세고-나서-쓰던 예전 방식이 놓치던 자리다.
 */
async function requireAnotherAdmin(db, tx, email, what) {
  const admins = await tx.get(db.collection("members").where("role", "==", "admin"));
  const others = admins.docs.filter((d) => d.id !== email);
  if (!others.length) {
    throw new GuardError("failed-precondition",
      "마지막 관리자는 " + what + " 다른 사람을 먼저 관리자로 지정하세요.");
  }
  return others.length;
}

/** 트랜잭션 밖에서 미리 세어 본다 — 부작용을 만들기 전에 흔한 경우를 걸러낸다.
 *  이것만 믿지 않는다. 확정은 트랜잭션 안의 requireAnotherAdmin 이 한다. */
async function countOtherAdmins(db, email) {
  const admins = await db.collection("members").where("role", "==", "admin").get();
  return admins.docs.filter((d) => d.id !== email).length;
}

/* ---------- 주제 숨기기 ---------- */

/** 목록에서 주제 하나를 빼고, 숨기는 경우라면 새로 넣는다. 순수 함수. */
function nextHiddenList(list, threadId, hidden, entry) {
  const rest = (Array.isArray(list) ? list : []).filter((t) => t && t.id !== threadId);
  if (!hidden) return rest;
  if (rest.length >= HIDDEN_LIMIT) {
    throw new GuardError("failed-precondition", "발행 제외 주제가 너무 많습니다.");
  }
  return rest.concat([Object.assign({ id: threadId }, entry)]);
}

/** 발행에서 뺀 주제 목록을 고친다. **한 문서를 여럿이 고치므로 트랜잭션이다.** */
async function setThreadHidden(db, data, caller, now) {
  const threadId = normalizeThreadId(data && data.threadId);
  const hidden = !(data && data.hidden === false);
  const title = String((data && data.title) || "").slice(0, 120);
  const ref = db.collection("settings").doc("threads");

  return db.runTransaction(async (tx) => {
    const snap = await tx.get(ref);
    const cur = snap.exists ? (snap.data() || {}) : {};
    const next = nextHiddenList(cur.hidden, threadId, hidden,
      { title, hiddenBy: caller, hiddenAt: now });
    tx.set(ref, { hidden: next, updatedAt: now }, { merge: true });
    return { threadId, hidden, count: next.length };
  });
}

/* ---------- 역할 ---------- */

/** 기존 멤버의 역할을 바꾼다. Auth 클레임은 **부르는 쪽이** 나중에 붙인다. */
async function setMemberRole(db, data, caller, now) {
  const email = normalizeEmail(data && data.email);
  const role = wantedRole(data && data.role) || "user";
  const ref = db.collection("members").doc(email);

  return db.runTransaction(async (tx) => {
    const snap = await tx.get(ref);
    if (!snap.exists) throw new GuardError("not-found", "멤버가 아닙니다: " + email);
    const current = (snap.data() || {}).role || "user";
    if (current === role) return { email, role, changed: false };
    if (current === "admin") await requireAnotherAdmin(db, tx, email, "내릴 수 없습니다.");
    tx.set(ref, { role, roleChangedBy: caller, roleChangedAt: now }, { merge: true });
    return { email, role, changed: true };
  });
}

/** 신청 승인. 이미 멤버인 사람에게도 돌 수 있다.
 *
 *  **승인은 권한을 올리기만 한다. 내리지는 않는다.**
 *
 *  예전에는 role 을 주지 않으면 'user' 로 봐서 기존 관리자를 조용히 내렸다.
 *  화면(web/admin.js)의 승인 단추는 늘 "user" 를 보내므로, 이미 멤버인 관리자가
 *  신청서를 다시 내면(규칙이 막지 않는다) 승인 한 번에 권한이 사라졌다 —
 *  마지막 관리자 보호를 우회하는 길이기도 했다.
 *
 *  내리는 일은 setMemberRole 한 곳에서만 한다. 거기에는 마지막 관리자 보호가
 *  있고, 관리 탭에 그 단추가 따로 있다. '승인' 이라고 쓰인 단추가 권한을 내리는
 *  일은 없어야 한다.
 */
async function approveClaim(db, data, caller, now) {
  const email = normalizeEmail(data && data.email);
  const asked = wantedRole(data && data.role);
  const memberRef = db.collection("members").doc(email);
  const claimRef = db.collection("claims").doc(email);

  return db.runTransaction(async (tx) => {
    const memberSnap = await tx.get(memberRef);
    const claimSnap = await tx.get(claimRef);
    const claimed = claimSnap.exists ? (claimSnap.data() || {}) : null;
    const current = memberSnap.exists ? ((memberSnap.data() || {}).role || "user") : null;
    // 올리기만 한다 — 이미 관리자면 무엇을 보내든 관리자로 남는다.
    const role = current === "admin" ? "admin" : (asked || current || "user");
    const nicknames = normalizeNicknames(
      (data && (data.nicknames || data.nickname)), claimed && claimed.nickname);

    tx.set(memberRef, {
      email,
      name: nicknames[0],
      // nickname 은 대표 표시명. 화면 표시와 하위호환용으로 남긴다.
      nickname: nicknames[0],
      nicknames,
      role,
      approvedBy: caller,
      approvedAt: now,
    }, { merge: true });
    if (claimSnap.exists) tx.delete(claimRef);
    return { email, nicknames, role, wasMember: memberSnap.exists,
             roleKept: current !== null && asked !== null && asked !== role };
  });
}

/* ---------- 탈퇴 ---------- */

/** 멤버 문서를 지운다. 표시명 박아두기·수집 거부·Auth 는 **부르는 쪽**이 한다.
 *
 *  지우는 것만 트랜잭션으로 감싼다. 나머지는 지우기 **전에** 끝나 있어야 한다 —
 *  멤버 문서가 사라지면 이메일→표시명 고리가 끊겨 남은 의사표시가 조용히 무시된다.
 */
async function removeMember(db, email, opts) {
  const ref = db.collection("members").doc(email);
  return db.runTransaction(async (tx) => {
    const snap = await tx.get(ref);
    if (!snap.exists) throw new GuardError("not-found", "멤버가 아닙니다: " + email);
    const d = snap.data() || {};
    if ((d.role || "user") === "admin") {
      await requireAnotherAdmin(db, tx, email, "탈퇴 처리할 수 없습니다.");
    }
    // 앞선 단계가 읽은 명부와 달라졌으면 멈춘다 — 그 사이 표시명이 바뀌었다면
    // 우리가 박아둔 표시명이 낡은 것이다.
    if (opts && opts.expectNicknames !== undefined) {
      const now = JSON.stringify(d.nicknames || (d.nickname ? [d.nickname] : []));
      if (now !== JSON.stringify(opts.expectNicknames)) {
        throw new GuardError("aborted", "처리 중 표시명이 바뀌었습니다. 다시 시도해 주세요.");
      }
    }
    tx.delete(ref);
    return { email, role: d.role || "user" };
  });
}

module.exports = {
  GuardError, HIDDEN_LIMIT,
  normalizeEmail, normalizeNicknames, normalizeThreadId, wantedRole,
  nextHiddenList, requireAnotherAdmin, countOtherAdmins,
  setThreadHidden, setMemberRole, approveClaim, removeMember,
};
