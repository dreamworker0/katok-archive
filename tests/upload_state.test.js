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
