/**
 * Firestore 보안 규칙을 **배포 전에** 검증한다.
 *
 * 규칙은 지금까지 배포한 뒤 화면에서 눌러 봐야 확인됐다. 그런데 규칙이 막으면
 * 저장이 조용히 실패하고, 화면은 "저장했습니다"라고 말한다 — 사람이 눌러 보기
 * 전까지 아무도 모른다(2026-07-28 '관심 주제 빠지기' 스위치가 그 상태였다).
 *
 * Firebase Security Rules API 의 test 엔드포인트가 규칙 원문을 그대로 평가해 준다.
 * 에뮬레이터(자바 필요)도, 사용자 계정도 필요 없다 — 서비스 계정 하나로 된다.
 *
 *   node scripts/test_rules.js
 *
 * 종료 코드 0 이면 모든 경우가 기대와 같다. 다르면 1 과 함께 어느 경우가 어긋났는지
 * 출력한다.
 *
 * 서비스 계정에 `firebaserules.rulesets.test` 권한이 필요하다. 2026-07-28 에는
 * 403 이 와서 이 스크립트가 돌지 못했고, 그동안 규칙 변경은 사람이 화면에서
 * 눌러 확인하는 수밖에 없었다. **2026-08-22 확인: 권한이 주어져 돈다.** 다시
 * 403 이 오면 콘솔에서 서비스 계정에 `roles/firebaserules.admin` 을 준다:
 *   https://console.cloud.google.com/iam-admin/iam?project=katok-crawling-project
 *
 * `firebase.json` 의 firestore predeploy 에 걸려 있다 — 규칙을 배포하려면 반드시
 * 이 검사를 지나야 한다. CI 에서는 돌지 않는다(서비스 계정 키가 필요하고, 그
 * 키를 깃허브에 두지 않는다). 그래서 배포 시점이 유일한 관문이고, 그래서 관문에
 * 걸어 두었다.
 *
 * 검사 범위: preferences 말고도 발행본 다섯 갈래(meta·threads·media·digests·graph),
 * chunks, myMessages, settings, messagesSource, members, claims, deletionRequests,
 * 그리고 마지막 catch-all. 예전에는 preferences 9건만 봤다.
 */
const fs = require("fs");
const path = require("path");
const { GoogleAuth } = require("google-auth-library");

const ROOT = path.resolve(__dirname, "..");
const KEY = path.join(ROOT, "serviceAccountKey.json");
const RULES = path.join(ROOT, "firestore.rules");
const PROJECT = JSON.parse(fs.readFileSync(KEY, "utf8")).project_id;

const MEMBER = "member@example.com";
const OUTSIDER = "nobody@example.com";

/** 로그인한 요청의 auth 부분.
 *
 *  **Firestore 규칙의 `isMember()` 는 커스텀 클레임을 보지 않는다** — `members`
 *  명부에 그 이메일 문서가 있는지 `exists()` 로 본다(저장소 규칙은 클레임을 쓰는데,
 *  두 방식이 서비스마다 다르다). 그래서 여기서는 클레임이 아니라 아래 `mocks()` 로
 *  명부에 있는지 없는지를 흉내 낸다.
 */
function auth(email) {
  return {
    uid: "uid-" + email,
    token: {
      email,
      email_verified: true,
      sub: "uid-" + email,
      firebase: { sign_in_provider: "google.com" },
    },
  };
}

/** 규칙 안의 exists()/get() 을 흉내 낸다. 검증 API 에는 실제 DB 가 없다. */
function mocks(email, isMember, role) {
  const p = "/databases/(default)/documents/members/" + email;
  return [
    { function: "exists", args: [{ exactValue: p }], result: { value: !!isMember } },
    {
      function: "get",
      args: [{ exactValue: p }],
      result: { value: { data: { role: role || "user" } } },
    },
  ];
}

/** 테스트 한 건. `name` 은 우리가 읽기 위한 것이라 API 로 보내지 않는다
 *  (보내면 400 Unknown name — 실측 2026-07-28). */
function testCase(name, expectation, request, functionMocks) {
  return { name, expectation, request, functionMocks };
}

function forApi(c) {
  const out = { expectation: c.expectation, request: c.request };
  if (c.functionMocks) out.functionMocks = c.functionMocks;
  return out;
}

const NOW = "2026-07-28T12:00:00Z";

/** preferences 문서에 쓰는 요청.
 *
 *  쓰려는 값은 `resource.data` 로 넘긴다 — 이 API 의 request 는 규칙 안의 `request`
 *  변수와 같은 모양이라, `data` 로 넘기면 규칙의 `request.resource.data` 가 없어서
 *  "Property resource is undefined" 가 난다(실측).
 */
function prefWrite(email, data, asEmail) {
  return {
    method: "update",
    path: "/databases/(default)/documents/preferences/" + email,
    resource: { data },
    auth: auth(asEmail || email),
    time: NOW,
  };
}

/* ── 아래 헬퍼들은 preferences 밖의 경로를 두드리기 위한 것 ──
 *
 * `prefWrite` 하나로는 발행본 읽기·목록·삭제를 표현할 수 없다. 규칙이 막는
 * 방식이 경로마다 달라서(read / list / create / delete) 방법을 골라 보낼 수
 * 있어야 한다.
 *
 * path 는 `threads/all` 처럼 짧게 적고 여기서 접두사를 붙인다 — 케이스마다
 * `/databases/(default)/documents/` 를 되풀이하면 무엇을 검사하는지가 안 보인다.
 */
const DOCS = "/databases/(default)/documents/";

/** 읽기 요청. `method` 는 'get'(문서 한 장) 또는 'list'(컬렉션 훑기).
 *
 *  규칙의 `allow read` 는 둘을 함께 허용하지만, myMessages·members·claims 는
 *  일부러 get 과 list 를 갈라 놓았다 — 본인 것 한 장은 봐도 목록은 못 본다.
 *  그 구분이 살아 있는지 보려면 방법을 따로 보내야 한다. */
function read(path, asEmail, method) {
  // list 는 **문서 패턴** 경로로 보내야 한다. 컬렉션 경로(`myMessages`)를 그대로
  // 주면 어느 match 블록에도 걸리지 않아 마지막 catch-all 이 막는다 — 규칙이
  // 제대로 막은 것처럼 보이지만 실은 검사하려던 `allow list` 를 건드리지도
  // 못한 것이다(실측 2026-08-22: '멤버는 못 훑는다' 가 이렇게 거짓 통과했고,
  // 같은 표기로 '관리자는 훑는다' 는 어긋나서야 드러났다).
  // 그래서 여기서 붙인다. 부르는 쪽은 컬렉션 이름만 준다.
  const p = method === "list" ? path + "/{document}" : path;
  return {
    method: method || "get",
    path: DOCS + p,
    auth: auth(asEmail),
    time: NOW,
  };
}

/** 쓰기 요청. `method` 는 'update'(기본) 또는 'create'. */
function write(path, data, asEmail, method) {
  return {
    method: method || "update",
    path: DOCS + path,
    resource: { data },
    auth: auth(asEmail),
    time: NOW,
  };
}

/** 삭제 요청. 규칙에서 delete 만 따로 허용/금지하는 경로가 둘 있다
 *  (claims 는 막고, deletionRequests 는 본인에게만 허용한다). */
function del(path, asEmail) {
  return { method: "delete", path: DOCS + path, auth: auth(asEmail), time: NOW };
}

/** 로그인하지 않은 요청. auth 를 아예 안 붙인다 — signedIn() 의 첫 조건이
 *  `request.auth != null` 이라 그것부터 걸려야 한다. */
function anon(path) {
  return { method: "get", path: DOCS + path, time: NOW };
}

/** 로그인은 했지만 이메일이 미인증인 요청. */
function unverified(path, asEmail) {
  const a = auth(asEmail);
  a.token.email_verified = false;
  return { method: "get", path: DOCS + path, auth: a, time: NOW };
}

/** 상한을 넘는 messageIds 목록을 만든다(규칙의 1000건 제한 검사용). */
function manyIds(n) {
  const out = [];
  for (let i = 0; i < n; i++) out.push("msg-" + String(i).padStart(6, "0"));
  return out;
}

const OTHER = "other@example.com";       // 남의 문서를 두드릴 때 쓰는 제3자
const ADMIN_ROLE = "admin";

const IN = mocks(MEMBER, true);          // 명부에 있는 멤버
const OUT = mocks(MEMBER, false);        // 명부에 없는 사람
// 관리자. isAdmin() 은 exists() 로 명부에 있는지 보고 get() 으로 role 을 읽으므로
// 목(mock) 둘을 함께 줘야 한다 — exists 만 주면 get 에서 규칙이 멈춘다.
const ADMIN = mocks(MEMBER, true, ADMIN_ROLE);

const CASES = [
  // ── '관심 주제 빠지기' 스위치가 실제로 저장되는가 ──
  testCase(
    "멤버가 수집 설정과 관심주제 숨김을 함께 저장한다",
    "ALLOW",
    prefWrite(MEMBER, { collection: "public", hideInterests: true, updatedAt: NOW }),
    IN
  ),
  testCase(
    "관심주제 숨김을 끈 상태로도 저장된다",
    "ALLOW",
    prefWrite(MEMBER, { collection: "unpublished", hideInterests: false, updatedAt: NOW }),
    IN
  ),
  // 예전 형태(두 필드)도 계속 되어야 한다 — 옛 화면이 남아 있을 수 있다
  testCase(
    "hideInterests 없이 예전 형태로도 저장된다",
    "ALLOW",
    prefWrite(MEMBER, { collection: "public", updatedAt: NOW }),
    IN
  ),
  // ── 막아야 하는 것 ──
  testCase(
    "hideInterests 가 불리언이 아니면 막는다",
    "DENY",
    prefWrite(MEMBER, { collection: "public", hideInterests: "yes", updatedAt: NOW }),
    IN
  ),
  testCase(
    "모르는 필드를 끼워 넣으면 막는다",
    "DENY",
    prefWrite(MEMBER, { collection: "public", hideInterests: true, updatedAt: NOW, admin: true }),
    IN
  ),
  testCase(
    "남의 문서에는 쓰지 못한다",
    "DENY",
    prefWrite(OUTSIDER, { collection: "public", hideInterests: true, updatedAt: NOW }, MEMBER),
    IN
  ),
  testCase(
    "명부에 없는 사람은 막는다",
    "DENY",
    prefWrite(MEMBER, { collection: "public", hideInterests: true, updatedAt: NOW }),
    OUT
  ),
  testCase(
    "collection 값이 목록에 없으면 막는다",
    "DENY",
    prefWrite(MEMBER, { collection: "secret", hideInterests: true, updatedAt: NOW }),
    IN
  ),
  // updatedAt 을 서버 시각이 아닌 값으로 위조하면 막는다(규칙이 request.time 을 요구)
  testCase(
    "updatedAt 을 다른 시각으로 위조하면 막는다",
    "DENY",
    prefWrite(MEMBER, { collection: "public", hideInterests: true,
                        updatedAt: "2020-01-01T00:00:00Z" }),
    IN
  ),
  // ══════════════════════════════════════════════════════════════════════
  // 아래는 preferences 밖의 규칙들. 예전에는 `preferences` 9건만 봤다 —
  // 그때 고친 규칙이 그것뿐이었기 때문이다. 그런데 이 파일이 지키는 것은
  // "멤버 아닌 사람은 아카이브를 못 본다" 이고, 그 문장은 발행본 다섯 갈래와
  // myMessages·settings·members·claims·deletionRequests 에 흩어져 있다.
  // 한 곳만 검사하면 나머지 아홉 곳은 사람이 화면에서 눌러 보는 수밖에 없다.
  // ══════════════════════════════════════════════════════════════════════

  // ── 발행본 다섯 갈래: 멤버만 읽는다 ──
  //
  // 다섯을 모두 적는다. 규칙이 다섯 줄로 따로 쓰여 있어(공용 함수가 아니다)
  // 한 줄을 지우거나 오타를 내도 나머지 넷은 통과한다.
  ...["meta", "threads", "media", "digests", "graph"].flatMap((col) => [
    testCase(`${col}: 멤버는 읽는다`, "ALLOW", read(`${col}/x`, MEMBER), IN),
    testCase(`${col}: 명부에 없으면 못 읽는다`, "DENY", read(`${col}/x`, OUTSIDER), OUT),
    testCase(`${col}: 클라이언트 쓰기는 막힌다`, "DENY",
      write(`${col}/x`, { any: 1 }, MEMBER), IN),
  ]),

  // 로그인 자체가 없으면 막힌다 — signedIn() 이 첫 관문이다.
  testCase("로그인 없이는 발행본을 못 읽는다", "DENY", anon("threads/all")),
  // 이메일 미인증 계정도 막는다. 구글 로그인은 대개 인증되어 오지만,
  // 규칙이 email_verified 를 요구하는 것에는 이유가 있다 — 남의 이메일로
  // 계정을 만들어 명부에 걸리는 것을 막는다.
  testCase("이메일 미인증 계정은 못 읽는다", "DENY", unverified("threads/all", MEMBER), IN),

  // ── 옛 원문 청크: 되살아나도 아무도 못 읽는다 ──
  testCase("chunks 는 멤버도 못 읽는다", "DENY", read("chunks/c-1", MEMBER), IN),
  testCase("chunks 는 관리자도 못 읽는다", "DENY", read("chunks/c-1", MEMBER), ADMIN),

  // ── 내가 쓴 글: 본인과 관리자만 ──
  testCase("내 글은 본인이 읽는다", "ALLOW", read(`myMessages/${MEMBER}`, MEMBER), IN),
  testCase("남의 글은 못 읽는다", "DENY", read(`myMessages/${OTHER}`, MEMBER), IN),
  testCase("관리자는 남의 글도 읽는다(오탐 되돌릴 근거)", "ALLOW",
    read(`myMessages/${OTHER}`, MEMBER), ADMIN),
  // list 는 관리자만. 멤버가 목록을 받으면 방 전체의 원문을 훑을 수 있다.
  testCase("멤버는 내 글 컬렉션을 훑지 못한다", "DENY",
    read("myMessages", MEMBER, "list"), IN),
  testCase("관리자는 내 글 컬렉션을 훑는다", "ALLOW",
    read("myMessages", MEMBER, "list"), ADMIN),
  testCase("내 글에는 클라이언트가 쓰지 못한다", "DENY",
    write(`myMessages/${MEMBER}`, { items: [] }, MEMBER), IN),

  // ── 운영 설정: 관리자만 ──
  //
  // settings/refresh 에 멤버가 쓸 수 있으면 누구나 파이프라인을 돌린다.
  // settings/threads 를 멤버가 읽으면 '발행에서 뺀 주제' 목록이 새어 나간다.
  testCase("일반 멤버는 운영 설정을 못 읽는다", "DENY", read("settings/refresh", MEMBER), IN),
  testCase("관리자는 운영 설정을 읽는다", "ALLOW", read("settings/refresh", MEMBER), ADMIN),
  testCase("관리자도 운영 설정에 직접 쓰지는 못한다", "DENY",
    write("settings/refresh", { status: "queued" }, MEMBER), ADMIN),

  // ── 원본 메시지: 관리자 전용 ──
  testCase("멤버는 원본 메시지를 못 읽는다", "DENY", read("messagesSource/m-1", MEMBER), IN),
  testCase("관리자는 원본 메시지를 읽는다", "ALLOW", read("messagesSource/m-1", MEMBER), ADMIN),

  // ── 멤버 명부: 본인 문서와 관리자만 ──
  //
  // 명부가 새면 36명의 실명·소속이 통째로 나간다. 그래서 본인 문서 한 장만 본다.
  testCase("본인 명부 문서는 읽는다(역할 확인용)", "ALLOW", read(`members/${MEMBER}`, MEMBER), IN),
  testCase("남의 명부 문서는 못 읽는다", "DENY", read(`members/${OTHER}`, MEMBER), IN),
  testCase("멤버는 명부를 훑지 못한다", "DENY", read("members", MEMBER, "list"), IN),
  testCase("명부에 클라이언트가 쓰지 못한다", "DENY",
    write(`members/${MEMBER}`, { role: "admin" }, MEMBER), IN),

  // ── 열람 신청: 아직 멤버 아닌 사람이 쓸 수 있는 유일한 경로 ──
  //
  // 유일하게 열린 쓰기 경로라 가장 촘촘히 본다.
  testCase("비멤버가 본인 이름으로 신청한다", "ALLOW",
    write(`claims/${OUTSIDER}`, { nickname: "홍길동", requestedAt: NOW }, OUTSIDER, "create"),
    mocks(OUTSIDER, false)),
  testCase("표시명까지 함께 적어도 된다", "ALLOW",
    write(`claims/${OUTSIDER}`,
      { nickname: "홍길동", displayName: "홍길동(어딘가복지관)", requestedAt: NOW },
      OUTSIDER, "create"),
    mocks(OUTSIDER, false)),
  testCase("남의 이메일로는 신청하지 못한다", "DENY",
    write(`claims/${OTHER}`, { nickname: "홍길동", requestedAt: NOW }, OUTSIDER, "create"),
    mocks(OUTSIDER, false)),
  // 문서 ID 를 본인 이메일로 못박아 1인 1건이 된다. 그 못이 빠지면
  // 한 사람이 신청서를 무한히 만들어 관리 화면을 덮을 수 있다.
  testCase("한 글자 별명은 막는다", "DENY",
    write(`claims/${OUTSIDER}`, { nickname: "홍", requestedAt: NOW }, OUTSIDER, "create"),
    mocks(OUTSIDER, false)),
  testCase("정해진 필드 밖을 끼워 넣으면 막는다", "DENY",
    write(`claims/${OUTSIDER}`,
      { nickname: "홍길동", requestedAt: NOW, approved: true }, OUTSIDER, "create"),
    mocks(OUTSIDER, false)),
  testCase("신청 시각을 위조하면 막는다", "DENY",
    write(`claims/${OUTSIDER}`,
      { nickname: "홍길동", requestedAt: "2020-01-01T00:00:00Z" }, OUTSIDER, "create"),
    mocks(OUTSIDER, false)),
  // 철회·승인은 Admin SDK(approve_claims.js)로만 한다. 신청자가 스스로 지우면
  // 관리자가 대조하던 근거가 사라진다.
  testCase("신청서는 본인도 지우지 못한다", "DENY",
    del(`claims/${OUTSIDER}`, OUTSIDER), mocks(OUTSIDER, false)),

  // ── 삭제 요청: 본인 글만 ──
  testCase("멤버가 삭제 요청을 낸다", "ALLOW",
    write(`deletionRequests/${MEMBER}`,
      { messageIds: ["msg-000001"], allMessages: false, requestedAt: NOW }, MEMBER, "create"),
    IN),
  testCase("전부 지워 달라는 요청도 낸다", "ALLOW",
    write(`deletionRequests/${MEMBER}`,
      { messageIds: [], allMessages: true, requestedAt: NOW }, MEMBER, "create"),
    IN),
  testCase("남의 이름으로는 삭제 요청을 못 낸다", "DENY",
    write(`deletionRequests/${OTHER}`,
      { messageIds: [], allMessages: true, requestedAt: NOW }, MEMBER, "create"),
    IN),
  testCase("명부에 없는 사람은 삭제 요청을 못 낸다", "DENY",
    write(`deletionRequests/${MEMBER}`,
      { messageIds: [], allMessages: true, requestedAt: NOW }, MEMBER, "create"),
    OUT),
  // 1000건 상한 — 없으면 문서 하나로 적재를 밀어낼 수 있다.
  testCase("1000건을 넘는 목록은 막는다", "DENY",
    write(`deletionRequests/${MEMBER}`,
      { messageIds: manyIds(1001), allMessages: false, requestedAt: NOW }, MEMBER, "create"),
    IN),
  // 잘못 눌렀을 때 되돌릴 길은 있어야 한다.
  testCase("본인은 삭제 요청을 철회한다", "ALLOW",
    del(`deletionRequests/${MEMBER}`, MEMBER), IN),
  testCase("남의 삭제 요청은 철회하지 못한다", "DENY",
    del(`deletionRequests/${OTHER}`, MEMBER), IN),

  // ── 그 밖의 모든 경로는 막힌다 ──
  //
  // 마지막 catch-all 이 살아 있는지 본다. 새 컬렉션을 만들면서 규칙을 안 쓰면
  // 이 줄이 유일한 방벽이다.
  testCase("규칙에 없는 컬렉션은 못 읽는다", "DENY", read("whatever/x", MEMBER), IN),
  testCase("규칙에 없는 컬렉션에는 못 쓴다", "DENY",
    write("whatever/x", { a: 1 }, MEMBER), IN),
];

async function main() {
  const client = await new GoogleAuth({
    keyFile: KEY,
    scopes: ["https://www.googleapis.com/auth/cloud-platform"],
  }).getClient();

  const res = await client.request({
    url: `https://firebaserules.googleapis.com/v1/projects/${PROJECT}:test`,
    method: "POST",
    data: {
      source: { files: [{ name: "firestore.rules", content: fs.readFileSync(RULES, "utf8") }] },
      testSuite: { testCases: CASES.map(forApi) },
    },
  });

  const results = (res.data && res.data.testResults) || [];
  let bad = 0;
  results.forEach((r, i) => {
    const name = CASES[i].name;
    const want = CASES[i].expectation;
    const ok = r.state === "SUCCESS";
    if (!ok) bad++;
    console.log(`  ${ok ? "통과" : "어긋남"} · ${want.padEnd(5)} · ${name}`);
    if (!ok && r.debugMessages) r.debugMessages.forEach((m) => console.log("      " + m));
  });
  const issues = (res.data && res.data.issues) || [];
  issues.forEach((i) => console.log(`  [규칙 경고] ${i.description}`));

  console.log(`\n규칙 검증: ${results.length - bad}/${results.length} 통과`);
  process.exit(bad ? 1 : 0);
}

main().catch((e) => {
  console.error("규칙 검증 실패:", (e.response && JSON.stringify(e.response.data)) || e.message);
  process.exit(1);
});
