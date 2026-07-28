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
 * **권한이 필요하다(2026-07-28 현재 없음).** 서비스 계정에
 * `firebaserules.rulesets.test` 권한이 있어야 하고, 지금은 403 이 온다. 콘솔에서
 * 서비스 계정에 `roles/firebaserules.admin` 을 주면 이 스크립트가 바로 돈다:
 *   https://console.cloud.google.com/iam-admin/iam?project=katok-crawling-project
 * (자바가 필요한 에뮬레이터 없이 규칙을 검증할 수 있는 유일한 길이라 남겨 둔다.
 *  그때까지는 규칙 변경을 사람이 화면에서 한 번 눌러 확인해야 한다.)
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

/** 멤버로 로그인한 요청의 auth 부분. 규칙의 isMember() 가 보는 것과 같게 맞춘다. */
function auth(email, claims) {
  return {
    uid: "uid-" + email,
    token: Object.assign(
      { email, email_verified: true, sub: "uid-" + email, firebase: { sign_in_provider: "google.com" } },
      claims || {}
    ),
  };
}

/** 테스트 한 건. `name` 은 우리가 읽기 위한 것이라 API 로 보내지 않는다
 *  (보내면 400 Unknown name — 실측 2026-07-28). */
function testCase(name, expectation, request) {
  return { name, expectation, request };
}

function forApi(c) {
  return { expectation: c.expectation, request: c.request };
}

const NOW = "2026-07-28T12:00:00Z";

/** preferences 문서에 쓰는 요청. */
function prefWrite(email, data, asEmail, claims) {
  return {
    method: "update",
    path: "/databases/(default)/documents/preferences/" + email,
    data,
    auth: auth(asEmail || email, claims === undefined ? { member: true } : claims),
    time: NOW,
  };
}

const CASES = [
  // ── '관심 주제 빠지기' 스위치가 실제로 저장되는가 ──
  testCase(
    "멤버가 수집 설정과 관심주제 숨김을 함께 저장한다",
    "ALLOW",
    prefWrite(MEMBER, { collection: "public", hideInterests: true, updatedAt: NOW })
  ),
  testCase(
    "관심주제 숨김을 끈 상태로도 저장된다",
    "ALLOW",
    prefWrite(MEMBER, { collection: "unpublished", hideInterests: false, updatedAt: NOW })
  ),
  // 예전 형태(두 필드)도 계속 되어야 한다 — 옛 화면이 남아 있을 수 있다
  testCase(
    "hideInterests 없이 예전 형태로도 저장된다",
    "ALLOW",
    prefWrite(MEMBER, { collection: "public", updatedAt: NOW })
  ),
  // ── 막아야 하는 것 ──
  testCase(
    "hideInterests 가 불리언이 아니면 막는다",
    "DENY",
    prefWrite(MEMBER, { collection: "public", hideInterests: "yes", updatedAt: NOW })
  ),
  testCase(
    "모르는 필드를 끼워 넣으면 막는다",
    "DENY",
    prefWrite(MEMBER, { collection: "public", hideInterests: true, updatedAt: NOW, admin: true })
  ),
  testCase(
    "남의 문서에는 쓰지 못한다",
    "DENY",
    prefWrite(OUTSIDER, { collection: "public", hideInterests: true, updatedAt: NOW }, MEMBER)
  ),
  testCase(
    "멤버 클레임이 없으면 막는다",
    "DENY",
    prefWrite(MEMBER, { collection: "public", hideInterests: true, updatedAt: NOW }, MEMBER, {})
  ),
  testCase(
    "collection 값이 목록에 없으면 막는다",
    "DENY",
    prefWrite(MEMBER, { collection: "secret", hideInterests: true, updatedAt: NOW })
  ),
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
