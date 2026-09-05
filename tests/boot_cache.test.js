// boot.js 를 가짜 Firestore·IndexedDB 위에서 실제로 돌려 본다.
//
// 왜 이렇게까지 하는가: 이 파일은 닫힌 IIFE 라 함수를 꺼내 부를 수 없고, 배포본은
// 구글 로그인이 있어야 열린다. 글자 검사(test_boot_cache.py)는 "캐시 코드가 있다"
// 까지만 말한다. 재방문에 Firestore 읽기가 실제로 줄었는지는 돌려 봐야 안다.
//
// 재는 것은 컬렉션·문서 읽기 횟수다 — 그것이 곧 비용이고 첫 화면 속도다.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SRC = fs.readFileSync(path.join(__dirname, "..", "web", "boot.js"), "utf8");
// vm 문맥의 배열·객체는 프로토타입이 달라 deepEqual 이 거절한다. 값만 견준다.
const plain = (x) => JSON.parse(JSON.stringify(x));

/* ── 가짜 IndexedDB. 이벤트 순서만 진짜와 같게 — get 의 result 가 채워진 뒤 tx 가 끝난다. ── */
function fakeIndexedDB(opts) {
  const stores = {};
  // exists: DB 자체는 있다. storeless: 그런데 그 안에 bundles 스토어가 없다 —
  // 버전이 같아 onupgradeneeded 가 다시 불리지 않는 상태(2026-09-02 실측).
  const st = { exists: !!(opts && opts.storeless), storeless: !!(opts && opts.storeless),
               opened: 0, closed: 0, deleted: 0 };
  const api = {
    _stores: stores,
    _state: st,
    open(name) {
      const req = {};
      setTimeout(() => {
        st.opened += 1;
        const db = {
          objectStoreNames: { contains: (s) => (opts && opts.vanish ? true : st.storeless ? false : !!stores[s]) },
          createObjectStore(s) { stores[s] = stores[s] || new Map(); },
          transaction(s, mode) {
            // 진짜 IDB 처럼 스토어가 없으면 여기서 던진다.
            if (st.storeless || !stores[s] || (opts && opts.vanish)) throw new Error("NotFoundError: " + s);
            const tx = {};
            const store = {
              // 진짜 IDB 처럼 success 전에 result 가 채워진다. 타이머로 늦추면 Windows 의
              // 타이머 해상도에서 tx.oncomplete 가 먼저 오는 날이 있다(4회 중 1회 깨졌다).
              get(k) { return { result: stores[s].get(k) }; },
              put(v, k) { stores[s].set(k, structuredClone(v)); return {}; },
              clear() { stores[s].clear(); return {}; },
            };
            tx.objectStore = () => store;
            setTimeout(() => tx.oncomplete && tx.oncomplete(), 2);
            return tx;
          },
          close() { st.closed += 1; },
        };
        req.result = db;
        if (!st.exists) { st.exists = true; req.onupgradeneeded && req.onupgradeneeded(); }
        req.onsuccess && req.onsuccess();
      }, 0);
      return req;
    },
    deleteDatabase(name) {
      const req = {};
      setTimeout(() => {
        st.deleted += 1;
        // stubborn: 삭제가 막히는 경우(다른 탭이 그 DB 를 붙들고 있을 때). 상태는 그대로다.
        if (opts && opts.stubborn) { req.onblocked && req.onblocked(); return; }
        st.exists = false;
        st.storeless = false;
        Object.keys(stores).forEach((k) => delete stores[k]);
        req.onsuccess && req.onsuccess();
      }, 0);
      return req;
    },
  };
  return api;
}

/* ── 가짜 Firestore. 컬렉션·문서 읽기를 센다. ── */
function fakeFirestore(data, reads, onRead) {
  // 진짜 SDK 처럼 스냅샷은 그 시점의 **복사본**이다. 참조를 그대로 주면 나중에
  // 바뀐 값이 이미 읽은 스냅샷에도 비쳐, 발행이 지나간 것을 알아채지 못한다.
  const snapOf = (id, d) => ({ id, exists: d !== undefined,
    data: () => (d === undefined ? d : structuredClone(d)) });
  return {
    collection(name) {
      return {
        get() {
          reads[name] = (reads[name] || 0) + 1;
          if (onRead) onRead(name, reads);
          const docs = Object.entries(data[name] || {}).map(([id, d]) => snapOf(id, d));
          return Promise.resolve({ forEach: (f) => docs.forEach(f) });
        },
        doc(id) {
          return {
            get() {
              reads[name] = (reads[name] || 0) + 1;
              if (onRead) onRead(name, reads);
              return Promise.resolve(snapOf(id, (data[name] || {})[id]));
            },
            set: () => Promise.resolve(), delete: () => Promise.resolve(),
            onSnapshot: () => () => {},
          };
        },
      };
    },
  };
}

const USER = {
  email: "Member@Example.com", displayName: "멤버",
  getIdTokenResult: () => Promise.resolve({ claims: { member: true } }),
  getIdToken: () => Promise.resolve("tok"),
};

function archiveData(hash) {
  return {
    meta: { archive: { content_hash: hash, chat_room: "방", categories: [{ id: "projects", label: "프로젝트" }],
      stats: { totals: { messages: 3 } }, tag_index: null } },
    members: { "member@example.com": { nickname: "멤버", role: "user" } },
    threads: { "000": { items: [{ id: "t-002", title: "둘" }] }, "001": { items: [{ id: "t-001", title: "하나" }] } },
    media: { "000": { items: [{ id: "m-1" }] } },
    graph: { nodes: { items: [{ id: "n" }] }, edges: { items: [] } },
    digests: { projects: { body: "요지" } },
    aiReports: { "000": { items: [{ id: "t-001", ai_report: "검증", ai_checked: "2026-09-02" }] } },
  };
}

/** 조건이 될 때까지 기다린다.
 *
 * 캐시 쓰기·비우기는 화면을 기다리지 않는다(fire-and-forget). 고정 시간으로 재면
 * 기계가 바쁜 밤에 우리가 먼저 재고 만다 — 2026-09-05 밤 갱신이 30ms 로 실패했다.
 */
async function settle(cond, why) {
  const deadline = Date.now() + 2000;
  while (!cond() && Date.now() < deadline) await new Promise((r) => setTimeout(r, 5));
  assert.ok(cond(), why);
}

/** 한 번의 방문. boot.js 를 새 문맥에서 돌리고 로그인 콜백을 부른다. */
async function visit(idb, data, onRead) {
  const reads = {};
  const got = { started: null, digests: null, ai: null };
  const element = () => ({ innerHTML: "", hidden: false, classList: { add() {}, remove() {} }, onclick: null });
  let authCb = null;
  const sandbox = {
    console: { warn() {}, log() {}, error() {} },
    setTimeout, clearTimeout,
    indexedDB: idb,
    document: { getElementById: element, querySelector: element },
    location: { reload() {} },
    FIREBASE_CONFIG: { storageBucket: "b" },
    ArchiveImages: { useStorage() {} },
    ArchiveApp: {
      start(session) { got.started = session; },
      attachDigests(d) { got.digests = d; },
      attachAiReports(items) { got.ai = items; },
    },
    firebase: {
      initializeApp() {},
      app: () => ({ functions: () => ({ httpsCallable: () => () => Promise.resolve({ data: {} }) }) }),
      auth: Object.assign(() => ({
        setPersistence() {},
        onAuthStateChanged(cb) { authCb = cb; },
        signOut() { got.signedOut = true; },
      }), { Auth: { Persistence: { LOCAL: "local" } } }),
      firestore: Object.assign(() => fakeFirestore(data, reads, onRead), { FieldValue: { serverTimestamp: () => 0 } }),
    },
  };
  sandbox.window = sandbox;
  vm.runInNewContext(SRC, sandbox, { filename: "boot.js" });
  assert.ok(authCb, "onAuthStateChanged 에 콜백이 걸려야 한다");
  authCb(USER);
  const deadline = Date.now() + 2000;
  while (!(got.started && got.digests && got.ai) && Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 5));
  }
  assert.ok(got.started, "앱이 시작돼야 한다");
  return { reads, got, sandbox };
}

const CORE = { threads: 1, media: 1, graph: 1 };
const REST = { digests: 1, aiReports: 1 };
const ALWAYS = { meta: 1, members: 1 };
// 조각을 받은 방문은 저장 전에 판이 그대로인지 한 번 더 묻는다 (flushCache)
const COLD = { meta: 2, members: 1 };

test("첫 방문: 조각 셋을 전부 서버에서 받는다 — 읽기 8회(저장 전 확인 1회 포함)", async () => {
  const { reads, got, sandbox } = await visit(fakeIndexedDB(), archiveData("h1"));
  assert.deepEqual(reads, { ...COLD, ...CORE, ...REST });
  assert.deepEqual(plain(sandbox.ARCHIVE.threads.map((t) => t.id)), ["t-001", "t-002"], "id 순으로 이어 붙인다");
  assert.equal(sandbox.ARCHIVE.media.length, 1);
  assert.deepEqual(plain(sandbox.ARCHIVE.lazy), { digests: true, aiReports: true });
  assert.deepEqual(plain(Object.keys(got.digests)), ["projects"]);
  assert.equal(got.ai.length, 1);
});

test("재방문(같은 지문): meta 와 본인 문서만 — 읽기 2회, 내용은 같다", async () => {
  const idb = fakeIndexedDB();
  const first = await visit(idb, archiveData("h1"));
  const second = await visit(idb, archiveData("h1"));
  assert.deepEqual(second.reads, ALWAYS);
  assert.deepEqual(plain(second.sandbox.ARCHIVE.threads), plain(first.sandbox.ARCHIVE.threads));
  assert.deepEqual(plain(second.got.digests), plain(first.got.digests));
  assert.deepEqual(plain(second.got.ai), plain(first.got.ai));
});

test("지문이 바뀐 날(밤 갱신 뒤): 전부 다시 받는다", async () => {
  const idb = fakeIndexedDB();
  await visit(idb, archiveData("h1"));
  const data = archiveData("h2");
  data.threads["001"].items[0].title = "고쳐진 하나";
  const again = await visit(idb, data);
  assert.deepEqual(again.reads, { ...COLD, ...CORE, ...REST });
  assert.equal(again.sandbox.ARCHIVE.threads[0].title, "고쳐진 하나");
});

test("지문이 없는 옛 발행본: 캐시에 두지 않아 다음에도 서버에서 받는다", async () => {
  const idb = fakeIndexedDB();
  await visit(idb, archiveData(undefined));
  const again = await visit(idb, archiveData(undefined));
  // 지문이 없으면 손에 들지도 않으므로 되묻지도 않는다
  assert.deepEqual(again.reads, { ...ALWAYS, ...CORE, ...REST });
});

test("로그아웃하면 캐시를 비운다 — 다음 사람은 서버에서 받는다", async () => {
  const idb = fakeIndexedDB();
  const { got } = await visit(idb, archiveData("h1"));
  got.started.signOut();
  await settle(() => got.signedOut === true && idb._stores.bundles.size === 0,
    "로그아웃은 캐시를 비운 뒤 끝나야 한다");
  const again = await visit(idb, archiveData("h1"));
  assert.deepEqual(again.reads, { ...COLD, ...CORE, ...REST });
});

/* ── 스토어 없는 DB (2026-09-02 실측) ──
 *
 * 배포본에서 실제로 겪었다. `archive-bundles` 가 버전 1 로 있는데 그 안에 `bundles`
 * 스토어가 없으면, 열기는 성공하고 transaction 마다 NotFoundError 가 난다. 버전이
 * 같아 onupgradeneeded 가 다시 불리지 않으니 스스로 낫지 못했다 — 그 브라우저는
 * 매 방문 3.5MB 를 다시 받으면서 콘솔에만 "번들 캐시를 읽지 못했습니다" 를 쌓았다.
 * 사람이 손으로 지우려 해도, 실패한 연결을 닫지 않아 삭제가 blocked 로 멈췄다.
 */
test("스토어 없는 옛 DB 는 지우고 다시 만든다 — 캐시가 되살아난다", async () => {
  const idb = fakeIndexedDB({ storeless: true });
  const first = await visit(idb, archiveData("h1"));
  // 첫 방문은 어차피 서버에서 받는다. 중요한 것은 그 뒤에 캐시가 남았는가다.
  assert.deepEqual(first.reads, { ...COLD, ...CORE, ...REST });
  assert.ok(idb._state.deleted >= 1, "망가진 DB 를 지웠어야 한다");
  await settle(() => idb._stores.bundles && idb._stores.bundles.size >= 3,
    "고친 DB 에 조각 셋이 남아야 한다");
  assert.deepEqual([...idb._stores.bundles.keys()].sort(), ["aiReports", "core", "digests"]);
  const second = await visit(idb, archiveData("h1"));
  assert.deepEqual(second.reads, ALWAYS, "재방문은 meta·members 만 읽어야 한다");
  assert.equal(idb._state.opened, idb._state.closed, "연 만큼 닫아야 한다");
});

test("지우지도 못하면 서버에서 받아 화면은 뜬다 — 연결은 새지 않는다", async () => {
  const idb = fakeIndexedDB({ storeless: true, stubborn: true });
  const { reads, got } = await visit(idb, archiveData("h1"));
  assert.deepEqual(reads, { ...COLD, ...CORE, ...REST });
  assert.equal(got.ai.length, 1, "캐시가 죽어도 화면은 채워져야 한다");
  await settle(() => idb._state.opened === idb._state.closed, "연 만큼 닫아야 한다");
});

test("열고 나서 스토어가 사라져도 연결을 닫는다 — 삭제가 막히지 않는다", async () => {
  const idb = fakeIndexedDB({ vanish: true });
  const { reads } = await visit(idb, archiveData("h1"));
  assert.deepEqual(reads, { ...COLD, ...CORE, ...REST });
  await settle(() => idb._state.opened === idb._state.closed, "연 만큼 닫아야 한다");
});

test("AI 주석이 안 열려도 화면은 뜬다 — 빈 목록으로 건넨다", async () => {
  const data = archiveData("h1");
  const idb = fakeIndexedDB();
  const reads = {};
  // aiReports 만 실패하는 Firestore
  const base = fakeFirestore(data, reads);
  const broken = { collection(name) {
    if (name !== "aiReports") return base.collection(name);
    return { get: () => Promise.reject(new Error("permission-denied")) };
  } };
  const got = { started: null, digests: null, ai: null };
  const element = () => ({ innerHTML: "", hidden: false, classList: { add() {}, remove() {} }, onclick: null });
  let authCb = null;
  const sandbox = {
    console: { warn() {}, log() {}, error() {} }, setTimeout, clearTimeout, indexedDB: idb,
    document: { getElementById: element, querySelector: element }, location: { reload() {} },
    FIREBASE_CONFIG: {}, ArchiveImages: { useStorage() {} },
    ArchiveApp: { start(s) { got.started = s; }, attachDigests(d) { got.digests = d; }, attachAiReports(i) { got.ai = i; } },
    firebase: {
      initializeApp() {}, app: () => ({ functions: () => ({ httpsCallable: () => () => Promise.resolve({ data: {} }) }) }),
      auth: Object.assign(() => ({ setPersistence() {}, onAuthStateChanged(cb) { authCb = cb; }, signOut() {} }),
        { Auth: { Persistence: { LOCAL: "local" } } }),
      firestore: Object.assign(() => broken, { FieldValue: { serverTimestamp: () => 0 } }),
    },
  };
  sandbox.window = sandbox;
  vm.runInNewContext(SRC, sandbox, { filename: "boot.js" });
  authCb(USER);
  const deadline = Date.now() + 2000;
  while (!(got.started && got.digests && got.ai) && Date.now() < deadline) await new Promise((r) => setTimeout(r, 5));
  assert.ok(got.started);
  assert.deepEqual(plain(got.ai), []);
  assert.ok(!idb._stores.bundles.has("aiReports"), "실패한 조각은 캐시에 두지 않는다");
});

/* ── 발행이 읽는 도중에 지나갔을 때 (2026-09-05) ──
 *
 * 적재는 이제 meta 를 마지막에 쓴다(upload_firestore.publishPlan). 그래도 한 번의
 * 방문 안에서는 조각이 갈릴 수 있다 — core 는 지난 판, digests 는 새 판. 그것을
 * 지문과 함께 캐시에 박으면 다음 방문에도 "최신이다" 로 판정되어 스스로 낫지
 * 못한다. 그래서 다 받은 뒤 판이 그대로인지 한 번 묻고, 갈렸으면 두지 않는다.
 */
test("받는 사이에 발행이 지나가면 캐시에 두지 않는다", async () => {
  const idb = fakeIndexedDB();
  const data = archiveData("h1");
  let published = false;
  // core 의 첫 컬렉션을 읽는 순간 밤 갱신이 끝나 새 판이 켜진다
  const first = await visit(idb, data, function (name) {
    if (name === "threads" && !published) {
      published = true;
      data.threads["001"].items[0].title = "고쳐진 하나";
      data.meta.archive.content_hash = "h2";
    }
  });
  assert.ok(first.got.started, "화면은 그대로 떠야 한다");
  await settle(() => (first.reads.meta || 0) >= 2, "저장 전에 판을 한 번 더 물어야 한다");
  await new Promise((r) => setTimeout(r, 20));
  assert.equal(idb._stores.bundles ? idb._stores.bundles.size : 0, 0,
    "판이 갈렸으므로 한 조각도 캐시에 두지 않는다");

  // 다음 방문은 서버에서 받아 새 판을 온전히 본다 — 스스로 나았다
  const again = await visit(idb, data);
  assert.deepEqual(again.reads, { ...COLD, ...CORE, ...REST });
  assert.equal(again.sandbox.ARCHIVE.threads[0].title, "고쳐진 하나");
  await settle(() => idb._stores.bundles && idb._stores.bundles.size === 3,
    "판이 그대로인 방문은 세 조각을 다 둔다");
});

test("판이 그대로면 세 조각을 함께 둔다 — 확인은 한 번뿐이다", async () => {
  const idb = fakeIndexedDB();
  const { reads } = await visit(idb, archiveData("h1"));
  assert.equal(reads.meta, 2, "처음 한 번, 저장 직전 한 번 — 조각마다 묻지 않는다");
  await settle(() => idb._stores.bundles && idb._stores.bundles.size === 3, "세 조각");
  assert.deepEqual([...idb._stores.bundles.keys()].sort(), ["aiReports", "core", "digests"]);
});
