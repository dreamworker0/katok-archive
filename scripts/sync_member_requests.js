#!/usr/bin/env node
/**
 * Firestore 의 멤버 요청(수집 동의·삭제 요청)을 로컬 파일로 내려받는다.
 *
 * 왜 중간 파일을 두는가
 *   실제 반영은 파이썬 파이프라인(수집·발행)이 한다. 파이프라인이 네트워크를 타면
 *   테스트할 수 없고 오프라인에서 돌릴 수도 없다. 그래서 네트워크는 이 스크립트가
 *   전담하고, 파이프라인은 output/member-requests.json 만 읽는다.
 *   (upload_firestore.js 가 페이로드만 올리는 것과 같은 구조다.)
 *
 * 여기서는 소유권을 검증하지 않는다 — 어떤 메시지가 누구 것인지는 messages.jsonl 을
 * 봐야 알 수 있고, 그건 파이썬 쪽 일이다. scripts/member_requests.py 를 볼 것.
 *
 * 사용
 *   node scripts/sync_member_requests.js
 *   node scripts/sync_member_requests.js --dry-run
 */
const fs = require("fs");
const path = require("path");
const admin = require("firebase-admin");

const ROOT = path.resolve(__dirname, "..");
const KEY = path.join(ROOT, "serviceAccountKey.json");
const MEMBERS = path.join(ROOT, "config", "members.json");
const OUT = path.join(ROOT, "output", "member-requests.json");
const PROJECT_ID = "katok-crawling-project";

const DRY = process.argv.slice(2).includes("--dry-run");

function init() {
  if (fs.existsSync(KEY)) {
    admin.initializeApp({
      credential: admin.credential.cert(require(KEY)),
      projectId: PROJECT_ID,
    });
    return;
  }
  try {
    admin.initializeApp({
      credential: admin.credential.applicationDefault(),
      projectId: PROJECT_ID,
    });
  } catch (e) {
    console.error(`인증 정보 없음. ${KEY} 를 두거나 gcloud ADC 를 설정하세요.`);
    process.exit(1);
  }
}

/** 이메일 → 대화방 표시명 목록. 이 대응이 없으면 요청을 메시지에 연결할 수 없다.
 *  한 사람이 표시명을 여러 개 가질 수 있다 (카톡에서 이름을 바꾼 경우). */
function nicknamesByEmail() {
  if (!fs.existsSync(MEMBERS)) return new Map();
  const raw = JSON.parse(fs.readFileSync(MEMBERS, "utf8"));
  const map = new Map();
  for (const m of raw.members || []) {
    const email = String(m.email || "").toLowerCase();
    if (!email) continue;
    const list = Array.isArray(m.nicknames) && m.nicknames.length
      ? m.nicknames.filter(Boolean)
      : (m.nickname ? [m.nickname] : []);
    if (list.length) map.set(email, list);
  }
  return map;
}

function isoOf(ts) {
  return ts && typeof ts.toDate === "function" ? ts.toDate().toISOString() : null;
}

async function main() {
  init();
  const db = admin.firestore();
  const nicknames = nicknamesByEmail();

  const [prefSnap, delSnap, settingsSnap] = await Promise.all([
    db.collection("preferences").get(),
    db.collection("deletionRequests").get(),
    db.collection("settings").doc("threads").get(),
  ]);

  // 관리자가 발행에서 뺀 주제. 멤버 요청과 함께 내려받아야 '조용한 날에도 발행'
  // 판정이 한 번에 이뤄진다 — 주제를 뺐는데 그날 대화가 없으면 반영이 밀린다.
  const hiddenThreads = (settingsSnap.exists && Array.isArray(settingsSnap.data().hidden)
    ? settingsSnap.data().hidden : [])
    .map((t) => String((t && t.id) || "")).filter(Boolean).sort();

  const rows = new Map();
  const ensure = (email) => {
    if (!rows.has(email)) {
      rows.set(email, {
        email,
        // 탈퇴한 사람은 명부에 없다. 그때는 요청 문서에 박아둔 표시명을 쓴다 —
        // 권한을 거둔 것과 "내 글 내려달라"는 의사는 별개이므로 계속 반영해야 한다.
        nicknames: nicknames.get(email) || [],
        collection: "public",
        hide_interests: false,
        delete_all: false,
        delete_message_ids: [],
        requested_at: null,
      });
    }
    return rows.get(email);
  };

  /** 탈퇴자는 명부에 없으므로 문서에 남겨둔 표시명으로 채운다. */
  const fillNames = (row, data) => {
    if (row.nicknames.length) return;
    if (Array.isArray(data.nicknames) && data.nicknames.length) {
      row.nicknames = data.nicknames.filter(Boolean);
      row.retired = true;
    }
  };

  prefSnap.forEach((d) => {
    const data = d.data() || {};
    const row = ensure(d.id);
    row.collection = data.collection || "public";
    // 관심 주제 화면에서 빠지겠다는 의사. 발행 단계에서 그 사람을 아예 안 싣는다.
    row.hide_interests = data.hideInterests === true;
    row.updated_at = isoOf(data.updatedAt);
    fillNames(row, data);
  });

  delSnap.forEach((d) => {
    const data = d.data() || {};
    const row = ensure(d.id);
    row.delete_all = data.allMessages === true;
    row.delete_message_ids = (data.messageIds || []).map(String);
    row.requested_at = isoOf(data.requestedAt);
    fillNames(row, data);
  });

  const requests = [...rows.values()];
  const unmapped = requests.filter((r) => !r.nicknames.length);

  const payload = {
    generated_at: new Date().toISOString(),
    requests: requests,
    hidden_threads: hiddenThreads,
  };

  console.log(`수집 동의 ${prefSnap.size}건 / 삭제 요청 ${delSnap.size}건 ` +
    `/ 발행 제외 주제 ${hiddenThreads.length}개`);
  for (const r of requests) {
    const bits = [];
    if (r.collection !== "public") bits.push(`동의=${r.collection}`);
    if (r.hide_interests) bits.push("관심주제 비공개");
    if (r.delete_all) bits.push("전체삭제");
    if (r.delete_message_ids.length) bits.push(`개별삭제 ${r.delete_message_ids.length}건`);
    if (bits.length) {
      console.log(`  ${r.nicknames.join("/") || r.email}: ${bits.join(", ")}` +
        (r.retired ? " (탈퇴자 — 의사표시는 계속 반영)" : ""));
    }
  }
  if (unmapped.length) {
    // 닉네임이 없으면 어느 메시지가 이 사람 것인지 알 수 없어 요청을 반영할 수 없다
    console.warn(
      `\n[주의] members.json 에 nickname 이 없어 반영할 수 없는 요청 ${unmapped.length}건: ` +
      unmapped.map((r) => r.email).join(", ")
    );
  }

  // 일일 자동화는 "새 메시지 0건이면 발행 생략"으로 동작한다. 그대로 두면 조용한
  // 날에 들어온 삭제 요청이 영영 반영되지 않으므로, 요청이 바뀌었는지 알려준다.
  const prev = readPayload(OUT);
  const changed = !prev ||
    canonical(prev.requests) !== canonical(requests) ||
    JSON.stringify(prev.hidden_threads || []) !== JSON.stringify(hiddenThreads);
  console.log(`요청 변경: ${changed ? "있음" : "없음"}`);
  // 위 줄은 사람이 읽는 것이고, 아래 표식은 run_daily.ps1 이 읽는다.
  //
  // 한글로 신호를 주면 안 되는 이유: Node 는 UTF-8 로 쓰는데 콘솔 코드페이지가
  // cp949 면 PowerShell 이 그 바이트를 cp949 로 읽어 글자가 깨진다. 그러면
  // `-match '요청 변경: 있음'` 이 영영 빗나가고, 조용한 날에 들어온 삭제 요청이
  // 발행되지 않은 채 묻힌다. ASCII 표식은 어느 코드페이지에서도 살아남는다.
  console.log(`REQUESTS_CHANGED=${changed ? 1 : 0}`);

  if (DRY) {
    console.log("\n--dry-run: 파일을 쓰지 않았습니다.");
    return;
  }
  fs.writeFileSync(OUT, JSON.stringify(payload, null, 2) + "\n", "utf8");
  console.log(`output/member-requests.json 갱신 (${requests.length}명)`);
}

function readPayload(p) {
  try {
    return JSON.parse(fs.readFileSync(p, "utf8"));
  } catch (e) {
    return null;
  }
}

/** generated_at 은 매번 바뀌므로 비교에서 뺀다. 키 순서도 고정한다. */
function canonical(requests) {
  if (!requests) return null;
  return JSON.stringify(
    [...requests]
      .map((r) => ({
        email: r.email,
        nicknames: [...(r.nicknames || [])].sort(),
        collection: r.collection || "public",
        hide_interests: !!r.hide_interests,
        delete_all: !!r.delete_all,
        delete_message_ids: [...(r.delete_message_ids || [])].sort(),
      }))
      .sort((a, b) => (a.email < b.email ? -1 : a.email > b.email ? 1 : 0))
  );
}

main().catch((e) => {
  console.error("\n실패:", e.message);
  process.exit(1);
});
