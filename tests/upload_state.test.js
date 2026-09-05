/**
 * 증분 적재 검사 — "바뀐 것만 쓴다"가 실제로 지켜지는지, 그리고 어긋났을 때
 * 덜 쓰는 쪽이 아니라 더 쓰는 쪽으로 틀리는지 확인한다.
 *
 *   node --test tests/
 */
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");

const up = require("../scripts/upload_firestore.js");

/* Firestore 대신 쓰는 가짜 db. 무엇을 쓰고 지웠는지, 원격 목록을 몇 번 읽었는지 센다. */
function fakeDb(seed) {
  const store = new Map(seed || []);
  const log = { writes: [], deletes: [], selects: 0 };
  return {
    store, log,
    collection(name) {
      return {
        doc: (id) => ({ __name: name, __id: id }),
        select: () => ({
          get: async () => {
            log.selects++;
            return {
              docs: [...store.keys()]
                .filter((k) => k.startsWith(name + "/"))
                .map((k) => ({ id: k.slice(name.length + 1) })),
            };
          },
        }),
      };
    },
    batch() {
      const ops = [];
      return {
        set: (ref, data) => ops.push(["set", ref, data]),
        delete: (ref) => ops.push(["delete", ref]),
        commit: async () => {
          for (const [op, ref, data] of ops) {
            const key = ref.__name + "/" + ref.__id;
            if (op === "set") { store.set(key, data); log.writes.push(key); }
            else { store.delete(key); log.deletes.push(key); }
          }
        },
      };
    },
  };
}

const quiet = (fn) => async (...a) => {
  const orig = console.log, w = process.stdout.write.bind(process.stdout);
  console.log = () => {};
  process.stdout.write = () => true;
  try { return await fn(...a); } finally { console.log = orig; process.stdout.write = w; }
};

test("stableStringify: 키 순서가 달라도 같은 해시", () => {
  assert.equal(up.docHash({ a: 1, b: [1, { x: 1, y: 2 }] }), up.docHash({ b: [1, { y: 2, x: 1 }] , a: 1 }));
  assert.notEqual(up.docHash({ a: 1 }), up.docHash({ a: 2 }));
});

test("planWrites: 대장이 없으면 전부 쓴다", () => {
  const p = up.planWrites(null, [{ id: "a", v: 1 }, { id: "b", v: 2 }]);
  assert.equal(p.writes.length, 2);
  assert.equal(p.deletes.length, 0);
  assert.equal(p.unchanged, 0);
});

test("planWrites: 안 바뀐 것은 안 쓰고, 빠진 것은 지운다", () => {
  const first = up.planWrites(null, [{ id: "a", v: 1 }, { id: "b", v: 2 }]);
  const second = up.planWrites(first.next, [{ id: "a", v: 1 }, { id: "b", v: 99 }, { id: "c", v: 3 }]);
  assert.deepEqual(second.writes.map((d) => d.id), ["b", "c"]);
  assert.equal(second.unchanged, 1);
  const third = up.planWrites(second.next, [{ id: "a", v: 1 }]);
  assert.deepEqual(third.deletes.sort(), ["b", "c"]);
  assert.equal(third.writes.length, 0);
});

test("planUploads: 크기가 같으면 건너뛰고, 없으면 알린다", () => {
  const remote = new Map([["images/a.png", 10], ["images/b.png", 999]]);
  const local = { "assets/images/a.png": 10, "assets/images/b.png": 20, "assets/images/c.png": 30 };
  const plan = up.planUploads(Object.keys(local).concat("assets/images/gone.png"), remote,
    (rel) => (rel in local ? local[rel] : null));
  assert.deepEqual(plan.skip, ["assets/images/a.png"]);
  assert.deepEqual(plan.put, ["assets/images/b.png", "assets/images/c.png"]);
  assert.deepEqual(plan.missing, ["assets/images/gone.png"]);
});

test("loadState: 없거나 깨졌거나 딴 프로젝트면 null (→ 전량 모드)", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "upstate-"));
  const p = (n) => path.join(dir, n);
  assert.equal(up.loadState(p("없다.json")), null);
  fs.writeFileSync(p("깨짐.json"), "{ 이건 json 이 아니다");
  assert.equal(up.loadState(p("깨짐.json")), null);
  fs.writeFileSync(p("남의것.json"), JSON.stringify(
    { state_version: up.STATE_VERSION, project: "other-project", collections: {} }));
  assert.equal(up.loadState(p("남의것.json")), null);
  fs.writeFileSync(p("옛버전.json"), JSON.stringify(
    { state_version: up.STATE_VERSION + 1, project: "katok-crawling-project", collections: {} }));
  assert.equal(up.loadState(p("옛버전.json")), null);
  fs.writeFileSync(p("정상.json"), JSON.stringify(
    { state_version: up.STATE_VERSION, project: "katok-crawling-project", collections: { a: {} } }));
  assert.ok(up.loadState(p("정상.json")));
});

test("staleState: 오래되면 전량으로 되돌린다", () => {
  const now = Date.parse("2026-07-26T00:00:00Z");
  assert.equal(up.staleState(null, now, 7), true);
  assert.equal(up.staleState({ last_full: "2026-07-25T00:00:00Z" }, now, 7), false);
  assert.equal(up.staleState({ last_full: "2026-07-10T00:00:00Z" }, now, 7), true);
  assert.equal(up.staleState({ last_full: "엉터리" }, now, 7), true);
});

test("syncCollection: 두 번째 실행은 바뀐 문서만 쓰고 목록을 읽지 않는다",
  quiet(async () => {
    const db = fakeDb();
    const docs1 = [{ id: "m1", t: "가" }, { id: "m2", t: "나" }, { id: "m3", t: "다" }];
    const state1 = await up.syncCollection(db, "messagesSource", docs1, { full: true });
    assert.equal(db.log.writes.length, 3);
    assert.equal(db.log.selects, 1, "전량 모드는 구문서를 찾으려 목록을 읽는다");

    db.log.writes.length = 0; db.log.selects = 0;
    const docs2 = docs1.concat([{ id: "m4", t: "라" }]);
    const state2 = await up.syncCollection(db, "messagesSource", docs2,
      { full: false, prev: state1 });
    assert.deepEqual(db.log.writes, ["messagesSource/m4"], "새 글 1건만 쓴다");
    assert.equal(db.log.selects, 0, "대장이 있으면 목록을 읽지 않는다");

    db.log.writes.length = 0;
    await up.syncCollection(db, "messagesSource", docs2, { full: false, prev: state2 });
    assert.equal(db.log.writes.length, 0, "바뀐 게 없으면 한 건도 쓰지 않는다");
  }));

test("syncCollection: 발행에서 빠진 문서는 대장만으로도 지운다", quiet(async () => {
  const db = fakeDb();
  const s1 = await up.syncCollection(db, "digests", [{ id: "a", v: 1 }, { id: "b", v: 2 }],
    { full: true });
  db.log.writes.length = 0; db.log.deletes.length = 0; db.log.selects = 0;
  await up.syncCollection(db, "digests", [{ id: "a", v: 1 }], { full: false, prev: s1 });
  assert.deepEqual(db.log.deletes, ["digests/b"]);
  assert.equal(db.log.selects, 0);
  assert.equal(db.store.has("digests/b"), false);
}));

test("중간에 실패해 대장이 남지 않으면, 다음 실행이 더 많이 쓴다(덜 쓰지 않는다)",
  quiet(async () => {
    const db = fakeDb();
    const docs = [{ id: "m1", t: "가" }, { id: "m2", t: "나" }];
    await up.syncCollection(db, "messagesSource", docs, { full: true });
    // 대장을 저장하기 전에 터진 상황 = prev 가 옛것(없음)
    db.log.writes.length = 0;
    await up.syncCollection(db, "messagesSource", docs, { full: false, prev: null });
    assert.equal(db.log.writes.length, 2, "다시 쓴다 — 빠뜨리는 것보다 낫다");
  }));

test("전량 모드는 대장에 없는 원격 구문서까지 지운다", quiet(async () => {
  const db = fakeDb([["digests/유령", { v: 0 }]]);
  await up.syncCollection(db, "digests", [{ id: "a", v: 1 }], { full: true });
  assert.deepEqual(db.log.deletes, ["digests/유령"]);
}));

/* ── 화면 캐시의 지문 (2026-09-02 실측) ──
 *
 * 캐시 코드를 배포한 날, 발행본은 그 코드보다 먼저 만들어져 meta 에 content_hash 가
 * 없었다. boot.js 는 지문이 없으면 조용히 저장을 건너뛴다 — 캐시가 꺼진 채 반나절을
 * 돌았고 화면도 로그도 아무 말을 하지 않았다. 발행 사유는 데이터 변화만 보므로
 * 스스로 낫지도 않는다. 적재가 말해 주는 것이 유일한 신호다.
 */
test("발행본에 지문이 없으면 적재가 말한다", () => {
  assert.ok(up.cacheHashWarning({ thread_count: 400 }), "없으면 경고");
  assert.ok(up.cacheHashWarning({ content_hash: "" }), "빈 문자열도 없는 것");
  assert.ok(up.cacheHashWarning(null), "meta 자체가 없어도 경고");
  assert.match(up.cacheHashWarning({}), /build_firestore_payload/, "고치는 법을 적는다");
  assert.equal(up.cacheHashWarning({ content_hash: "36d0772617dabab5" }), null, "있으면 조용히");
});

/* ── 발행 순서와 캐시 오염 (2026-09-05) ──
 *
 * 화면(boot.js)은 meta.content_hash 를 조각 캐시의 지문으로 쓴다. 적재가 meta 를
 * 먼저 쓰면, 그 사이에 들어온 멤버는 **새 지문에 옛 데이터**를 캐시에 박는다 —
 * 다음 방문에도 지문이 같으니 스스로 낫지 못한다.
 *
 * 여기서 재는 것은 한 가지다: 적재가 도는 **어느 순간에 화면이 들어와도**, 새
 * 지문이 보인다면 내용도 새것이어야 한다.
 */
function payloadOf(mark) {
  return {
    meta: { content_hash: "h-" + mark, thread_count: 1 },
    threadDocs: [{ id: "000", items: [{ id: "t-1", title: mark }] }],
    aiDocs: [{ id: "000", items: [] }],
    mediaDocs: [{ id: "000", items: [] }],
    mineDocs: [{ id: "a@b.c", items: [{ id: "m-1", text: mark }] }],
    digestDocs: [{ id: "projects", body: mark }],
    graph: { nodes: [{ id: "n-" + mark }], edges: [] },
    sourceDocs: [{ id: "m-1", text: mark }],
    now: "2026-09-05T23:40:00.000Z",
  };
}

test("발행 계획: meta 가 마지막이다 — 새 판은 내용이 다 올라간 뒤에 켠다", () => {
  const plan = up.publishPlan(payloadOf("새것"));
  assert.equal(plan[plan.length - 1].name, "meta", "meta 는 반드시 마지막이다");
  assert.equal(plan.filter((s) => s.name === "meta").length, 1);
  // 화면이 읽는 것이 전부 meta 앞에 있어야 한다
  const names = plan.map((s) => s.name);
  ["threads", "aiReports", "media", "digests", "graph", "myMessages", "messagesSource"]
    .forEach((n) => assert.ok(names.indexOf(n) !== -1 && names.indexOf(n) < names.indexOf("meta"),
      n + " 은 meta 보다 먼저 써야 한다"));
  assert.equal(names.indexOf("members"), -1, "members 는 Firestore 가 주인이다");
  assert.equal(plan.find((s) => s.name === "meta").docs[0].updatedAt,
    "2026-09-05T23:40:00.000Z");
});

test("splitPlan: 켜는 단계(meta)를 앞 단계와 가른다", () => {
  const { before, activate } = up.splitPlan(up.publishPlan(payloadOf("새것")));
  assert.equal(activate.name, "meta");
  assert.equal(before.filter((s) => s.name === "meta").length, 0);
  assert.throws(() => up.splitPlan([{ name: "threads", docs: [] }]), /meta/);
});

test("적재 도중 어느 순간에 들어와도, 새 지문이면 내용도 새것이다", quiet(async () => {
  const db = fakeDb();
  // 지난 판을 통째로 올려 둔다
  const state = {};
  for (const s of up.publishPlan(payloadOf("옛것"))) {
    state[s.name] = await up.syncCollection(db, s.name, s.docs, { full: true });
  }
  const hashOf = () => (db.store.get("meta/archive") || {}).content_hash;
  const titleOf = () => ((db.store.get("threads/000") || {}).items || [{}])[0].title;
  const digestOf = () => (db.store.get("digests/projects") || {}).body;
  assert.equal(hashOf(), "h-옛것");

  // 새 판을 적재하며 **한 단계마다** 화면이 들어온 셈 치고 들여다본다
  const seen = [];
  for (const s of up.publishPlan(payloadOf("새것"))) {
    await up.syncCollection(db, s.name, s.docs, { full: false, prev: state[s.name] });
    seen.push({ after: s.name, hash: hashOf(), title: titleOf(), digest: digestOf() });
  }

  for (const look of seen) {
    if (look.hash === "h-새것") {
      assert.equal(look.title, "새것",
        look.after + " 까지 쓴 시점: 새 지문인데 주제가 옛것이다 — 캐시가 오염된다");
      assert.equal(look.digest, "새것",
        look.after + " 까지 쓴 시점: 새 지문인데 요지가 옛것이다 — 캐시가 오염된다");
    }
  }
  // 켜기 전까지는 내내 옛 지문이어야 한다 (= 지난 판을 그대로 보여준다)
  assert.deepEqual(seen.slice(0, -1).map((s) => s.hash).filter((h) => h !== "h-옛것"), [],
    "meta 를 쓰기 전에는 지문이 바뀌면 안 된다");
  assert.equal(seen[seen.length - 1].hash, "h-새것", "마지막에 켠다");
}));

test("중간에 실패하면 지난 판이 그대로 남는다 — 재실행이 안전하다", quiet(async () => {
  const db = fakeDb();
  const state = {};
  for (const s of up.publishPlan(payloadOf("옛것"))) {
    state[s.name] = await up.syncCollection(db, s.name, s.docs, { full: true });
  }

  // 새 판을 쓰다가 digests 에서 터진다
  const next = up.publishPlan(payloadOf("새것"));
  await assert.rejects(async () => {
    for (const s of next) {
      if (s.name === "digests") throw new Error("네트워크가 끊겼다");
      await up.syncCollection(db, s.name, s.docs, { full: false, prev: state[s.name] });
    }
  }, /네트워크/);
  assert.equal((db.store.get("meta/archive") || {}).content_hash, "h-옛것",
    "켜지 않았으므로 멤버는 지난 판을 본다");

  // 다시 돌린다 — 대장을 저장하지 못했으므로 prev 는 옛것 그대로다
  db.log.writes.length = 0;
  for (const s of next) {
    await up.syncCollection(db, s.name, s.docs, { full: false, prev: state[s.name] });
  }
  assert.equal((db.store.get("meta/archive") || {}).content_hash, "h-새것");
  assert.equal(((db.store.get("threads/000") || {}).items || [{}])[0].title, "새것");
  assert.ok(!db.log.writes.includes("aiReports/000"),
    "이미 올라간 문서는 해시가 같아 다시 쓰지 않는다");
}));

/* ── '내 글' 문서와 표시명 연결 (2026-09-05) ──
 *
 * 관리자가 연결을 고치면 setMemberNicknames 가 그 자리에서 myMessages 를 지운다.
 * 그러면 다음 발행이 다시 채워야 하는데, 대장은 **페이로드의 해시**만 본다 —
 * 새로 묶은 표시명에 글이 한 건도 없으면 items 가 그대로라 해시도 그대로고,
 * 지워진 문서는 전량 동기화(7일)까지 비어 있게 된다.
 *
 * 그래서 문서에 '어떤 표시명으로 모았는지' 를 함께 싣는다.
 */
test("연결이 바뀌면 글 목록이 그대로여도 '내 글' 문서를 다시 쓴다", () => {
  const items = [{ id: "m-1", text: "같은 글" }];
  const before = { id: "a@x.com", items: items, nicknames: ["옛이름"] };
  const after = { id: "a@x.com", items: items, nicknames: ["옛이름", "새이름"] };
  assert.notEqual(up.docHash({ items: before.items, nicknames: before.nicknames }),
    up.docHash({ items: after.items, nicknames: after.nicknames }),
    "표시명이 달라지면 해시도 달라져야 다시 쓴다");

  const first = up.planWrites(null, [before]);
  const second = up.planWrites(first.next, [after]);
  assert.deepEqual(second.writes.map((d) => d.id), ["a@x.com"]);

  // 연결도 글도 그대로면 다시 쓰지 않는다 — 증분 적재의 값어치는 지킨다
  const third = up.planWrites(second.next, [after]);
  assert.equal(third.writes.length, 0);
});
