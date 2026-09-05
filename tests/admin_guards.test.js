/**
 * 관리자 조작의 동시 실행 검사 — functions/guards.js 를 가짜 Firestore 위에서 돌린다.
 *
 *   node --test tests/admin_guards.test.js
 *
 * 왜 가짜인가: 에뮬레이터는 자바가 필요하고 서비스 계정 키는 깃허브에 두지 않는다.
 * 여기서 재는 것은 **판단**이다 — 읽은 것이 그 사이 바뀌면 다시 도는가, 마지막
 * 관리자가 0명이 될 수 있는가. 그것은 진짜 Firestore 없이도 잴 수 있다.
 *
 * 가짜는 진짜의 낙관적 동시성을 흉내 낸다. 트랜잭션이 읽은 문서·질의가 커밋 전에
 * 바뀌었으면 콜백을 처음부터 다시 돌린다. 진짜 Firestore 가 하는 일이 그것이다.
 */
const test = require("node:test");
const assert = require("node:assert/strict");
const guards = require("../functions/guards.js");

const NOW = "2026-09-05T12:00:00.000Z";

function fakeDb(seed) {
  const docs = new Map();      // "col/id" -> { data, rev }
  const colRev = new Map();    // "col" -> rev
  let rev = 0;
  const log = { attempts: 0, commits: 0, conflicts: 0 };

  const split = (key) => [key.slice(0, key.indexOf("/")), key.slice(key.indexOf("/") + 1)];

  function put(key, data) {
    rev += 1;
    docs.set(key, { data, rev });
    colRev.set(split(key)[0], rev);
  }
  function drop(key) {
    rev += 1;
    docs.delete(key);
    colRev.set(split(key)[0], rev);
  }
  Object.keys(seed || {}).forEach((k) => put(k, seed[k]));

  const snapOf = (key) => {
    const e = docs.get(key);
    return { id: split(key)[1], exists: !!e,
             data: () => (e ? structuredClone(e.data) : undefined) };
  };

  function queryGet(q) {
    const out = [];
    docs.forEach((e, key) => {
      if (split(key)[0] !== q.__col) return;
      if (q.__where && e.data[q.__where[0]] !== q.__where[2]) return;
      out.push(snapOf(key));
    });
    return { size: out.length, docs: out, empty: !out.length };
  }

  const db = {
    __log: log,
    __interleave: null,           // 트랜잭션 첫 읽기 뒤에 끼어드는 다른 관리자
    __docs: docs,
    __put: put,
    __drop: drop,
    __data: (key) => (docs.get(key) ? structuredClone(docs.get(key).data) : null),
    __admins: () => [...docs.entries()]
      .filter(([k, e]) => split(k)[0] === "members" && e.data.role === "admin")
      .map(([k]) => split(k)[1]).sort(),
    collection(name) {
      return {
        __col: name,
        doc: (id) => ({ __col: name, __id: id, __key: name + "/" + id }),
        where: (field, op, value) => ({ __col: name, __where: [field, op, value] }),
        get: async () => queryGet({ __col: name }),
      };
    },
    async runTransaction(fn) {
      for (let attempt = 0; attempt < 8; attempt++) {
        log.attempts += 1;
        const readDocs = new Map(), readCols = new Map(), writes = [];
        let first = true;
        const tx = {
          async get(target) {
            let res;
            if (target.__key) {
              readDocs.set(target.__key, (docs.get(target.__key) || { rev: -1 }).rev);
              res = snapOf(target.__key);
            } else {
              readCols.set(target.__col,
                colRev.has(target.__col) ? colRev.get(target.__col) : -1);
              res = queryGet(target);
            }
            if (first) {
              first = false;
              const h = db.__interleave;
              if (h) { db.__interleave = null; await h(); }
            }
            return res;
          },
          set(ref, data, opts) { writes.push(["set", ref, data, opts]); },
          delete(ref) { writes.push(["delete", ref]); },
        };
        const result = await fn(tx);

        // 읽은 것이 그 사이 바뀌었으면 커밋하지 않고 다시 돈다
        let stale = false;
        readDocs.forEach((r, key) => {
          if ((docs.get(key) || { rev: -1 }).rev !== r) stale = true;
        });
        readCols.forEach((r, col) => {
          if ((colRev.has(col) ? colRev.get(col) : -1) !== r) stale = true;
        });
        if (stale) { log.conflicts += 1; continue; }

        writes.forEach(([op, ref, data, opts]) => {
          if (op === "delete") return drop(ref.__key);
          const prev = opts && opts.merge && docs.get(ref.__key)
            ? docs.get(ref.__key).data : {};
          put(ref.__key, Object.assign({}, prev, data));
        });
        log.commits += 1;
        return result;
      }
      throw new Error("트랜잭션이 너무 많이 충돌했습니다");
    },
  };
  return db;
}

const member = (role, nicknames) => ({ email: "x", role, nicknames: nicknames || ["가"] });

/* ══════ ① 주제 숨기기 — 변경 유실 ══════ */

/** 고치기 전의 방식 — 읽고, 고치고, 따로 쓴다.
 *  무엇을 잃어버렸는지 검사가 기억하게 그대로 남겨 둔다. */
async function unsafeSetThreadHidden(db, data, caller, now, meanwhile) {
  const cur = db.__data("settings/threads") || {};                   // ① 읽는다
  if (meanwhile) await meanwhile();                                  // ② 그 사이 남이 끝낸다
  const list = Array.isArray(cur.hidden) ? cur.hidden : [];
  const rest = list.filter((t) => t && t.id !== data.threadId);
  rest.push({ id: data.threadId, title: "", hiddenBy: caller, hiddenAt: now });
  db.__put("settings/threads", { hidden: rest, updatedAt: now });    // ③ 쓴다
  return { count: rest.length };
}

test("옛 방식: 두 관리자가 동시에 숨기면 한 명의 조작이 사라진다", async () => {
  const db = fakeDb({ "settings/threads": { hidden: [] } });
  // 갑이 읽은 뒤, 쓰기 전에 을이 끝낸다
  await unsafeSetThreadHidden(db, { threadId: "t-gap" }, "gap@x.com", NOW, async () => {
    await unsafeSetThreadHidden(db, { threadId: "t-eul" }, "eul@x.com", NOW);
  });
  const ids = db.__data("settings/threads").hidden.map((t) => t.id);
  assert.deepEqual(ids, ["t-gap"], "을의 조작이 사라졌다 — 이것이 고친 결함이다");
});

test("두 관리자가 서로 다른 주제를 동시에 숨겨도 둘 다 반영된다", async () => {
  const db = fakeDb({ "settings/threads": { hidden: [] } });
  db.__interleave = async () => {
    await guards.setThreadHidden(db, { threadId: "t-eul", title: "을 주제" }, "eul@x.com", NOW);
  };
  const done = await guards.setThreadHidden(db,
    { threadId: "t-gap", title: "갑 주제" }, "gap@x.com", NOW);

  const ids = db.__data("settings/threads").hidden.map((t) => t.id).sort();
  assert.deepEqual(ids, ["t-eul", "t-gap"], "둘 다 남아야 한다");
  assert.equal(done.count, 2);
  assert.ok(db.__log.conflicts >= 1, "충돌을 알아채고 다시 돌았어야 한다");
});

test("숨김 해제는 목록에서 뺀다. 없는 것을 빼도 탈 없다", async () => {
  const db = fakeDb({ "settings/threads": { hidden: [{ id: "t-1" }, { id: "t-2" }] } });
  await guards.setThreadHidden(db, { threadId: "t-1", hidden: false }, "gap@x.com", NOW);
  assert.deepEqual(db.__data("settings/threads").hidden.map((t) => t.id), ["t-2"]);
  const done = await guards.setThreadHidden(db, { threadId: "t-none", hidden: false }, "gap@x.com", NOW);
  assert.equal(done.count, 1);
});

test("같은 주제를 두 번 숨겨도 목록에 한 번만 들어간다", async () => {
  const db = fakeDb({ "settings/threads": { hidden: [] } });
  await guards.setThreadHidden(db, { threadId: "t-1" }, "gap@x.com", NOW);
  const done = await guards.setThreadHidden(db, { threadId: "t-1" }, "eul@x.com", NOW);
  assert.equal(done.count, 1);
  assert.equal(db.__data("settings/threads").hidden[0].hiddenBy, "eul@x.com");
});

test("잘못된 주제 ID 는 거부한다", async () => {
  const db = fakeDb({});
  for (const bad of ["", "   ", "t 1", "t/1", "../x", "가나다", "a".repeat(61), null]) {
    await assert.rejects(() => guards.setThreadHidden(db, { threadId: bad }, "gap@x.com", NOW),
      (e) => e instanceof guards.GuardError && e.code === "invalid-argument",
      "거부해야 한다: " + JSON.stringify(bad));
  }
  assert.equal(db.__data("settings/threads"), null, "거부된 요청은 아무것도 쓰지 않는다");
});

test("발행 제외가 상한을 넘으면 거부한다", async () => {
  const many = [];
  for (let i = 0; i < guards.HIDDEN_LIMIT; i++) many.push({ id: "t-" + i });
  const db = fakeDb({ "settings/threads": { hidden: many } });
  await assert.rejects(() => guards.setThreadHidden(db, { threadId: "t-new" }, "gap@x.com", NOW),
    (e) => e.code === "failed-precondition");
  // 상한에 닿아도 **빼는 것**은 되어야 한다 — 되돌릴 길이 막히면 안 된다
  const done = await guards.setThreadHidden(db, { threadId: "t-0", hidden: false }, "gap@x.com", NOW);
  assert.equal(done.count, guards.HIDDEN_LIMIT - 1);
});

/* ══════ ② 마지막 관리자 보호 ══════ */

test("마지막 관리자는 내릴 수 없다", async () => {
  const db = fakeDb({ "members/gap@x.com": member("admin"), "members/eul@x.com": member("user") });
  await assert.rejects(
    () => guards.setMemberRole(db, { email: "gap@x.com", role: "user" }, "gap@x.com", NOW),
    (e) => e.code === "failed-precondition");
  assert.deepEqual(db.__admins(), ["gap@x.com"]);
});

test("동시에 서로를 내려도 관리자가 0명이 되지 않는다", async () => {
  const db = fakeDb({
    "members/gap@x.com": member("admin"),
    "members/eul@x.com": member("admin"),
  });
  // 갑이 을을 내리려고 읽은 직후, 을이 갑을 내리는 데 성공한다
  db.__interleave = async () => {
    await guards.setMemberRole(db, { email: "gap@x.com", role: "user" }, "eul@x.com", NOW);
  };
  await assert.rejects(
    () => guards.setMemberRole(db, { email: "eul@x.com", role: "user" }, "gap@x.com", NOW),
    (e) => e.code === "failed-precondition",
    "다시 돌아 '이제 내가 마지막이다' 를 보고 멈춰야 한다");
  assert.deepEqual(db.__admins(), ["eul@x.com"], "한 명은 남는다");
});

test("관리자가 둘이면 한 명을 내릴 수 있다", async () => {
  const db = fakeDb({
    "members/gap@x.com": member("admin"), "members/eul@x.com": member("admin"),
  });
  const done = await guards.setMemberRole(db, { email: "eul@x.com", role: "user" }, "gap@x.com", NOW);
  assert.equal(done.changed, true);
  assert.deepEqual(db.__admins(), ["gap@x.com"]);
  assert.equal(db.__data("members/eul@x.com").roleChangedBy, "gap@x.com");
});

test("역할이 이미 같으면 쓰지 않는다 — Auth 도 건드릴 일이 없다", async () => {
  const db = fakeDb({ "members/gap@x.com": member("admin") });
  const done = await guards.setMemberRole(db, { email: "gap@x.com", role: "admin" }, "gap@x.com", NOW);
  assert.deepEqual(done, { email: "gap@x.com", role: "admin", changed: false });
  assert.equal(db.__data("members/gap@x.com").roleChangedAt, undefined);
});

test("멤버가 아니면 not-found, 이메일이 엉터리면 invalid-argument", async () => {
  const db = fakeDb({ "members/gap@x.com": member("admin") });
  await assert.rejects(() => guards.setMemberRole(db, { email: "none@x.com" }, "gap@x.com", NOW),
    (e) => e.code === "not-found");
  for (const bad of ["", "골뱅이없음", null, undefined, 42]) {
    await assert.rejects(() => guards.setMemberRole(db, { email: bad }, "gap@x.com", NOW),
      (e) => e.code === "invalid-argument");
  }
});

/* ══════ ③ 승인이 관리자를 조용히 내리던 길 ══════ */

test("옛 결함: 승인은 role 을 안 주면 기존 관리자를 user 로 내렸다", async () => {
  const db = fakeDb({
    "members/gap@x.com": member("admin"),
    "claims/gap@x.com": { nickname: "갑" },
  });
  // 이제는 role 을 주지 않으면 **기존 역할을 그대로 둔다**
  const done = await guards.approveClaim(db, { email: "gap@x.com" }, "gap@x.com", NOW);
  assert.equal(done.role, "admin", "말하지 않은 것을 바꾸지 않는다");
  assert.deepEqual(db.__admins(), ["gap@x.com"]);
  assert.equal(db.__data("claims/gap@x.com"), null, "신청서는 정리한다");
});

test("승인은 권한을 내리지 않는다 — 관리자가 둘이어도 마찬가지다", async () => {
  const db = fakeDb({
    "members/gap@x.com": member("admin"),
    "members/eul@x.com": member("admin"),
    "claims/eul@x.com": { nickname: "을" },
  });
  // 화면의 승인 단추는 늘 "user" 를 보낸다. 그것으로 관리자가 내려가면 안 된다.
  const done = await guards.approveClaim(db,
    { email: "eul@x.com", role: "user" }, "gap@x.com", NOW);
  assert.equal(done.role, "admin");
  assert.equal(done.roleKept, true, "무엇을 지켰는지 알려준다");
  assert.deepEqual(db.__admins(), ["eul@x.com", "gap@x.com"]);
});

test("승인으로 관리자를 올리는 것은 된다", async () => {
  const db = fakeDb({
    "members/gap@x.com": member("admin"),
    "claims/new@x.com": { nickname: "새사람" },
  });
  const done = await guards.approveClaim(db,
    { email: "new@x.com", role: "admin" }, "gap@x.com", NOW);
  assert.equal(done.role, "admin");
  assert.deepEqual(db.__admins(), ["gap@x.com", "new@x.com"]);
});

test("새 사람 승인: user 로 들어가고 표시명은 신청서에서 가져온다", async () => {
  const db = fakeDb({
    "members/gap@x.com": member("admin"),
    "claims/new@x.com": { nickname: "새사람" },
  });
  const done = await guards.approveClaim(db, { email: "new@x.com" }, "gap@x.com", NOW);
  assert.equal(done.role, "user");
  assert.deepEqual(done.nicknames, ["새사람"]);
  assert.equal(done.wasMember, false);
  const doc = db.__data("members/new@x.com");
  assert.equal(doc.nickname, "새사람");
  assert.equal(doc.approvedBy, "gap@x.com");
  assert.equal(db.__data("claims/new@x.com"), null);
});

test("표시명이 하나도 없으면 승인하지 않는다", async () => {
  const db = fakeDb({ "members/gap@x.com": member("admin") });
  await assert.rejects(() => guards.approveClaim(db, { email: "new@x.com" }, "gap@x.com", NOW),
    (e) => e.code === "invalid-argument");
  assert.equal(db.__data("members/new@x.com"), null);
});

/* ══════ ④ 탈퇴 ══════ */

test("마지막 관리자는 탈퇴 처리할 수 없다", async () => {
  const db = fakeDb({ "members/gap@x.com": member("admin"), "members/eul@x.com": member("user") });
  await assert.rejects(() => guards.removeMember(db, "gap@x.com", {}),
    (e) => e.code === "failed-precondition");
  assert.ok(db.__data("members/gap@x.com"));
});

test("동시에 관리자를 내리고 지워도 0명이 되지 않는다", async () => {
  const db = fakeDb({
    "members/gap@x.com": member("admin"), "members/eul@x.com": member("admin"),
  });
  // 을을 지우려고 읽은 직후, 다른 관리자가 갑을 내린다
  db.__interleave = async () => {
    await guards.setMemberRole(db, { email: "gap@x.com", role: "user" }, "eul@x.com", NOW);
  };
  await assert.rejects(() => guards.removeMember(db, "eul@x.com", {}),
    (e) => e.code === "failed-precondition");
  assert.deepEqual(db.__admins(), ["eul@x.com"]);
});

test("일반 멤버는 지워진다", async () => {
  const db = fakeDb({ "members/gap@x.com": member("admin"), "members/eul@x.com": member("user") });
  const done = await guards.removeMember(db, "eul@x.com", {});
  assert.deepEqual(done, { email: "eul@x.com", role: "user" });
  assert.equal(db.__data("members/eul@x.com"), null);
});

test("지우는 사이 표시명이 바뀌었으면 멈춘다 — 박아둔 이름이 낡았다", async () => {
  const db = fakeDb({
    "members/gap@x.com": member("admin"),
    "members/eul@x.com": member("user", ["옛이름"]),
  });
  db.__interleave = async () => {
    db.__put("members/eul@x.com", member("user", ["새이름"]));
  };
  await assert.rejects(() => guards.removeMember(db, "eul@x.com", { expectNicknames: ["옛이름"] }),
    (e) => e.code === "aborted");
  assert.ok(db.__data("members/eul@x.com"), "지우지 않았다");
});

test("없는 멤버를 지우면 not-found", async () => {
  const db = fakeDb({ "members/gap@x.com": member("admin") });
  await assert.rejects(() => guards.removeMember(db, "none@x.com", {}),
    (e) => e.code === "not-found");
});

/* ══════ ⑤ 입력 다듬기 ══════ */

test("표시명 정리: 공백·중복·빈 것을 걸러내고 상한을 지킨다", () => {
  assert.deepEqual(guards.normalizeNicknames([" 가 ", "가", "", "나"]), ["가", "나"]);
  assert.deepEqual(guards.normalizeNicknames("가"), ["가"]);
  assert.deepEqual(guards.normalizeNicknames(null, "기본"), ["기본"]);
  assert.deepEqual(guards.normalizeNicknames(["a".repeat(41), "짧다"]), ["짧다"]);
  assert.throws(() => guards.normalizeNicknames([]), (e) => e.code === "invalid-argument");
  assert.throws(() => guards.normalizeNicknames(["a".repeat(41)]), (e) => e.code === "invalid-argument");
  const eleven = Array.from({ length: 11 }, (_, i) => "이름" + i);
  assert.throws(() => guards.normalizeNicknames(eleven), (e) => e.code === "invalid-argument");
});

test("이메일은 소문자로 맞춘다 — 문서 ID 가 소문자다", () => {
  assert.equal(guards.normalizeEmail("  Member@Example.COM "), "member@example.com");
  assert.throws(() => guards.normalizeEmail("골뱅이없음"), (e) => e.code === "invalid-argument");
});

test("역할은 말한 것만 받는다 — 나머지는 '그대로 두라'는 뜻", () => {
  assert.equal(guards.wantedRole("admin"), "admin");
  assert.equal(guards.wantedRole("user"), "user");
  [undefined, null, "", "superadmin", 1, true].forEach(
    (v) => assert.equal(guards.wantedRole(v), null));
});
