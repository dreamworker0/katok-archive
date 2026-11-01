/**
 * 적재 전 인증 확인 검사 — 네트워크 탓과 자격증명 탓을 가르는지 본다.
 *
 * 왜 이 검사가 있는가 (실측 2026-09-12 00:00:59)
 *   이 PC 의 DNS 가 30초쯤 먹통이 되어 oauth2.googleapis.com 을 풀지 못했고,
 *   21분을 돌고 온 밤 갱신이 마지막 적재 단계에서 죽었다. 그런데 로그에 남은
 *   말은 "인증 정보를 찾지 못했습니다 — 새 비공개 키를 생성하세요" 였다.
 *   키는 멀쩡했다. 그 직전 23:40 과 직후 00:01:27 에 **같은 키로** Firestore
 *   읽기·쓰기가 됐고, 윈도우 이벤트 로그에는 같은 시각 네이버·구글·슬랙이
 *   한꺼번에 이름 확인에 실패한 DNS 오류(ID 1014)가 남아 있었다.
 *
 *   안내를 따랐다면 멀쩡한 키를 갈아 끼우며 엉뚱한 곳을 뒤졌을 것이다.
 *   그래서 두 가지를 지킨다 — 일시적 네트워크 장애는 기다렸다 다시 해보고,
 *   끝내 실패하면 **진짜 이유**를 말한다.
 *
 *   node --test tests/
 */
const test = require("node:test");
const assert = require("node:assert");

const up = require("../scripts/upload_firestore.js");
const { looksLikeNetwork, CRED_RETRY_WAITS_MS } = up;

/** code 가 붙은 오류를 만든다 (node 가 실제로 던지는 모양). */
function err(message, code, causeCode) {
  const e = new Error(message);
  if (code) e.code = code;
  if (causeCode) e.cause = Object.assign(new Error("cause"), { code: causeCode });
  return e;
}

test("실측한 그 오류 — DNS 가 구글을 못 풀었다 — 는 네트워크로 본다", () => {
  assert.strictEqual(
    looksLikeNetwork(err("getaddrinfo EAI_AGAIN oauth2.googleapis.com", "EAI_AGAIN")),
    true
  );
});

test("흔한 네트워크 오류들을 네트워크로 본다", () => {
  for (const [msg, code] of [
    ["getaddrinfo ENOTFOUND oauth2.googleapis.com", "ENOTFOUND"],
    ["socket hang up", "ECONNRESET"],
    ["connect ECONNREFUSED 142.250.0.1:443", "ECONNREFUSED"],
    ["connect ETIMEDOUT", "ETIMEDOUT"],
    ["connect EHOSTUNREACH", "EHOSTUNREACH"],
    ["connect ENETUNREACH", "ENETUNREACH"],
  ]) {
    assert.strictEqual(looksLikeNetwork(err(msg, code)), true, `${code} 를 놓쳤다`);
  }
});

test("code 가 cause 안에 숨어 있어도 찾는다", () => {
  const e = err("Getting metadata from plugin failed", null, "ENOTFOUND");
  assert.strictEqual(looksLikeNetwork(e), true);
});

test("진짜 자격증명 오류는 네트워크로 보지 않는다", () => {
  // 이것을 네트워크로 오인하면, 키가 썩었는데 67초를 헛되이 기다린 뒤
  // "연결을 확인하세요" 라고 엉뚱한 안내를 하게 된다.
  for (const [msg, code] of [
    ['invalid_grant: Invalid JWT Signature.', null],
    ["error:0909006C:PEM routines:get_name:no start line", null],
    ["Service account key is invalid", null],
    ["The caller does not have permission", "PERMISSION_DENIED"],
  ]) {
    assert.strictEqual(looksLikeNetwork(err(msg, code)), false, `'${msg}' 를 네트워크로 봤다`);
  }
});

test("오류가 없거나 모양이 이상해도 터지지 않는다", () => {
  for (const bad of [null, undefined, {}, new Error("")]) {
    assert.strictEqual(looksLikeNetwork(bad), false);
  }
});

test("재시도가 실측한 끊김보다 오래 버틴다", () => {
  // 2026-09-12 의 끊김은 00:00:51~00:01:23 로 약 32초였다. 재시도 예산이
  // 그보다 짧아지면 같은 사고를 또 못 넘긴다 — 줄이려는 변경을 여기서 막는다.
  const total = CRED_RETRY_WAITS_MS.reduce((a, b) => a + b, 0) / 1000;
  assert.ok(total >= 60, `재시도 예산이 ${total}초뿐이다 — 실측 32초 끊김에 여유가 없다`);
});

test("재시도 간격이 점점 늘어난다", () => {
  // 촘촘히 다섯 번 두드리는 것은 기다리는 것이 아니다.
  for (let i = 1; i < CRED_RETRY_WAITS_MS.length; i++) {
    assert.ok(
      CRED_RETRY_WAITS_MS[i] > CRED_RETRY_WAITS_MS[i - 1],
      `${i}번째 간격이 앞보다 길지 않다`
    );
  }
});
