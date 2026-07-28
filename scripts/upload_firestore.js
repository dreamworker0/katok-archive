#!/usr/bin/env node
/**
 * firestore-payload/ 를 Firestore·Storage 에 적재하는 얇은 업로더.
 *
 * 변환 로직은 파이썬(scripts/build_firestore_payload.py)이 이미 끝냈고, 이 파일은
 * 네트워크 I/O만 담당한다. Admin SDK 는 보안 규칙을 우회하므로 클라이언트 쓰기를
 * 전면 금지한 규칙과 공존한다.
 *
 * 준비
 *   npm install
 *   Firebase 콘솔 > 프로젝트 설정 > 서비스 계정 > 새 비공개 키 생성
 *     → serviceAccountKey.json 으로 저장 (git 제외됨)
 *
 * 바뀐 것만 올린다
 *   예전에는 매번 전부 다시 썼다. 새 글이 3건인 날에도 원문 1,509건을 통째로
 *   set 하고, 사진 41MB 를 다시 올렸다. 지금은 문서마다 해시를 대장
 *   (output/upload-state.json)에 적어 두고 달라진 것만 쓴다. 사진·첨부는 저장소
 *   목록을 한 번 받아 크기가 같으면 건너뛴다.
 *
 *   대장이 원격과 어긋나면 안 쓰고 넘어가는 사고가 난다. 그래서
 *     - 대장이 없거나 깨졌거나 프로젝트가 다르면 자동으로 전량 모드
 *     - FULL_EVERY_DAYS 마다 한 번은 전량 모드로 맞춘다
 *     - 대장은 적재가 끝까지 성공한 뒤에만 쓴다. 중간에 실패하면 옛 대장이
 *       남아 다음 실행이 더 많이 쓴다 — 덜 쓰는 쪽이 아니라 더 쓰는 쪽으로 틀린다
 *     - --full 로 언제든 강제할 수 있다
 *
 * 사용
 *   node scripts/upload_firestore.js              # 바뀐 것만 적재
 *   node scripts/upload_firestore.js --full       # 전량 적재 + 대장 다시 만들기
 *   node scripts/upload_firestore.js --dry-run    # 계획만 출력
 *   node scripts/upload_firestore.js --skip-images
 *   node scripts/upload_firestore.js --keep-orphans   # 발행에서 빠진 사진·첨부를 지우지 않음
 */
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const admin = require("firebase-admin");

const ROOT = path.resolve(__dirname, "..");
const PAYLOAD = path.join(ROOT, "firestore-payload");
const KEY = path.join(ROOT, "serviceAccountKey.json");
const STATE_PATH = path.join(ROOT, "output", "upload-state.json");
const PROJECT_ID = "katok-crawling-project";
const BUCKET = "katok-crawling-project.firebasestorage.app";
const STATE_VERSION = 1;
const FULL_EVERY_DAYS = 7;

const args = process.argv.slice(2);
const DRY = args.includes("--dry-run");
const SKIP_IMAGES = args.includes("--skip-images");
const KEEP_ORPHANS = args.includes("--keep-orphans");
const FORCE_FULL = args.includes("--full");
const BATCH_LIMIT = 450; // Firestore 배치 상한 500 아래로 여유

function readPayload(name) {
  const p = path.join(PAYLOAD, name);
  if (!fs.existsSync(p)) {
    throw new Error(`페이로드 없음: ${name} — 먼저 python -m scripts.build_firestore_payload`);
  }
  return JSON.parse(fs.readFileSync(p, "utf8"));
}

function credentialHelp() {
  return (
    "인증 정보를 찾지 못했습니다. 아래 중 하나를 준비하세요.\n\n" +
    "  (A) 서비스 계정 키 — 권장\n" +
    "      Firebase 콘솔 > 프로젝트 설정 > 서비스 계정 > 새 비공개 키 생성\n" +
    `      → ${KEY} 로 저장 (git 제외됨)\n\n` +
    "  (B) gcloud 애플리케이션 기본 자격증명\n" +
    "      gcloud auth application-default login\n"
  );
}

/** 자격증명이 실제로 쓸 수 있는지 미리 확인한다.
 *  ADC 는 initializeApp 시점에 실패하지 않고 첫 사용에서 터지므로,
 *  토큰을 한 번 받아보고 적재를 시작한다. */
async function verifyCredential() {
  try {
    await admin.app().options.credential.getAccessToken();
  } catch (e) {
    console.error("\n" + credentialHelp());
    process.exit(1);
  }
}

function init() {
  // 1순위: 서비스 계정 키 파일
  if (fs.existsSync(KEY)) {
    const sa = require(KEY);
    if (sa.project_id && sa.project_id !== PROJECT_ID) {
      console.error(
        `키의 프로젝트(${sa.project_id})가 대상(${PROJECT_ID})과 다릅니다. 확인하세요.`
      );
      process.exit(1);
    }
    admin.initializeApp({
      credential: admin.credential.cert(sa),
      storageBucket: BUCKET,
      projectId: PROJECT_ID,
    });
    console.log("인증: serviceAccountKey.json");
    return;
  }

  // 2순위: 애플리케이션 기본 자격증명
  //   GOOGLE_APPLICATION_CREDENTIALS 환경변수 또는
  //   gcloud auth application-default login 을 이미 해둔 경우
  try {
    admin.initializeApp({
      credential: admin.credential.applicationDefault(),
      storageBucket: BUCKET,
      projectId: PROJECT_ID,
    });
    console.log("인증: 애플리케이션 기본 자격증명(ADC)");
    return;
  } catch (e) {
    console.error("\n" + credentialHelp());
    process.exit(1);
  }
}

/* ---------- 대장(무엇을 이미 올렸는가) ---------- */

/** 키 순서가 달라도 같은 해시가 나오도록 정렬해 직렬화한다. */
function stableStringify(v) {
  if (v === null || typeof v !== "object") return JSON.stringify(v);
  if (Array.isArray(v)) return "[" + v.map(stableStringify).join(",") + "]";
  return "{" + Object.keys(v).sort().map(
    (k) => JSON.stringify(k) + ":" + stableStringify(v[k])
  ).join(",") + "}";
}

function docHash(data) {
  return crypto.createHash("sha1").update(stableStringify(data)).digest("hex").slice(0, 16);
}

/** 대장을 읽는다. 믿을 수 없으면 null — 부르는 쪽이 전량 모드로 간다. */
function loadState(file) {
  try {
    const s = JSON.parse(fs.readFileSync(file, "utf8"));
    if (s.state_version !== STATE_VERSION || s.project !== PROJECT_ID) return null;
    if (!s.collections || typeof s.collections !== "object") return null;
    return s;
  } catch (e) {
    return null;
  }
}

/** 마지막 전량 동기화가 오래됐으면 이번엔 전량으로 맞춘다. */
function staleState(state, now, days) {
  if (!state || !state.last_full) return true;
  const age = (now - Date.parse(state.last_full)) / 86400000;
  return !(age >= 0) || age >= days;
}

/** 무엇을 쓰고 무엇을 지울지 미리 셈한다. prev 가 없으면 전부 쓴다. */
function planWrites(prev, docs) {
  const next = {};
  const writes = [];
  docs.forEach((d) => {
    const { id, ...data } = d;
    const h = docHash(data);
    next[id] = h;
    if (!prev || prev[id] !== h) writes.push(d);
  });
  // prev 에만 있는 id 는 이번 발행에서 빠진 것 — 지운다
  const deletes = prev ? Object.keys(prev).filter((id) => !(id in next)) : [];
  return { writes, deletes, next, unchanged: docs.length - writes.length };
}

/** 컬렉션을 페이로드 상태로 동기화한다. 바뀐 문서만 쓴다.
 *
 *  full 이면 전부 쓰고, 대장에 없는 구문서까지 찾으려고 원격 목록을 한 번 읽는다.
 *  평소에는 대장이 지난 id 를 알고 있으므로 그 읽기(원문이면 1,500회)를 건너뛴다.
 */
async function syncCollection(db, name, docs, opts) {
  const o = opts || {};
  const prev = o.full ? null : (o.prev || null);
  const plan = planWrites(prev, docs);
  let written = 0;

  for (let i = 0; i < plan.writes.length; i += BATCH_LIMIT) {
    const batch = db.batch();
    for (const d of plan.writes.slice(i, i + BATCH_LIMIT)) {
      const { id, ...data } = d;
      batch.set(db.collection(name).doc(id), data);
    }
    await batch.commit();
    written += Math.min(BATCH_LIMIT, plan.writes.length - i);
    process.stdout.write(`  ${name}: ${written}/${plan.writes.length}\r`);
  }

  let stale = plan.deletes.slice();
  if (prev === null) {
    // 대장을 믿을 수 없는 상황 — 원격을 훑어 페이로드에 없는 문서를 찾는다
    const ids = new Set(docs.map((d) => d.id));
    const existing = await db.collection(name).select().get();
    existing.docs.forEach((d) => { if (!ids.has(d.id) && stale.indexOf(d.id) === -1) stale.push(d.id); });
  }
  for (let i = 0; i < stale.length; i += BATCH_LIMIT) {
    const batch = db.batch();
    stale.slice(i, i + BATCH_LIMIT).forEach((id) => batch.delete(db.collection(name).doc(id)));
    await batch.commit();
  }

  console.log(
    `  ${name}: ${plan.writes.length}건 적재` +
    (plan.unchanged ? `, ${plan.unchanged}건 그대로` : "") +
    (stale.length ? `, 구문서 ${stale.length}건 삭제` : "")
  );
  return plan.next;
}

const FILE_TYPES = {
  ".pdf": "application/pdf",
  ".html": "text/html; charset=utf-8",
  ".md": "text/markdown; charset=utf-8",
  ".txt": "text/plain; charset=utf-8",
  ".zip": "application/zip",
  ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  ".hwp": "application/x-hwp",
  ".hwpx": "application/haansofthwpx",
};

/** 저장소에 이미 무엇이 있는지 한 번에 받아 둔다.
 *
 *  파일마다 exists()+getMetadata() 를 부르면 왕복이 파일 수만큼 난다. 목록은 어차피
 *  고아 정리(pruneOrphans)에서도 필요하므로 한 번 받아 둘로 쓴다.
 */
async function remoteIndex(bucket, prefix) {
  const [objects] = await bucket.getFiles({ prefix });
  const size = new Map();
  objects.forEach((o) => size.set(o.name, Number((o.metadata || {}).size)));
  return { size, objects };
}

/** 올릴 것과 건너뛸 것을 가른다. 크기가 같으면 같은 파일로 본다 —
 *  매니페스트가 sha256 을 들고 있지만 매번 원격 해시를 받아오는 편이 더 비싸다. */
function planUploads(rels, remoteSize, localSize) {
  const put = [], skip = [], missing = [];
  rels.forEach((rel) => {
    const size = localSize(rel);
    if (size == null) { missing.push(rel); return; }
    const dest = rel.replace(/^assets\//, "");
    if (remoteSize.get(dest) === size) skip.push(rel);
    else put.push(rel);
  });
  return { put, skip, missing };
}

function localSizeOf(rel) {
  const local = path.join(ROOT, rel);
  return fs.existsSync(local) ? fs.statSync(local).size : null;
}

/** 대화방에서 공유된 첨부 파일. 80MB 짜리 PDF 가 섞여 있어 매번 전부 다시 올리면
 *  일일 자동화가 느려지고 송신 비용도 든다. */
async function uploadFiles(bucket, files, remoteSize) {
  const plan = planUploads(files, remoteSize, localSizeOf);
  plan.missing.forEach((rel) => console.warn(`  [건너뜀] 파일 없음: ${rel}`));
  let done = 0;
  const skipped = plan.skip.length;
  for (const rel of plan.put) {
    const local = path.join(ROOT, rel);
    const dest = rel.replace(/^assets\//, "");
    const size = fs.statSync(local).size;

    await bucket.upload(local, {
      destination: dest,
      resumable: size > 5 * 1024 * 1024,
      metadata: {
        contentType: FILE_TYPES[path.extname(rel).toLowerCase()] || "application/octet-stream",
        cacheControl: "private, max-age=86400",
        // 브라우저가 열지 않고 내려받게 한다 (html 첨부가 실행되면 곤란하다)
        contentDisposition: "attachment",
      },
    });
    done++;
    process.stdout.write(`  files: ${done} 올림 (${path.basename(rel)})\n`);
  }
  console.log(`  files: ${done}건 업로드, ${skipped}건 이미 있음`);
}

/** 발행본에서 빠진 사진·첨부를 Storage 에서도 지운다.
 *
 *  "내 사진 내려주세요"를 처리했는데 파일이 저장소에 그대로 있으면 반쪽이다.
 *  발행본에 없으면 앱에서 경로를 알 수 없지만, 남아 있다는 사실 자체가 약속을
 *  지키지 않은 것이다.
 *
 *  되돌릴 수 없는 삭제이므로 안전장치를 둔다. 발행 목록이 비어 있으면(빌드 실패나
 *  매니페스트 누락일 수 있다) 아무것도 지우지 않는다 — 그 상태로 정리하면 전부
 *  날아간다.
 */
async function pruneOrphans(bucket, prefix, keepPaths, label, listed) {
  const keep = new Set(keepPaths.map((p) => p.replace(/^assets\//, "")));
  if (!keep.size) {
    console.warn(`  [건너뜀] ${label} 발행 목록이 비어 있어 정리하지 않습니다.`);
    return;
  }
  const objects = listed || (await bucket.getFiles({ prefix }))[0];
  const orphans = objects.filter((o) => !keep.has(o.name));
  if (!orphans.length) {
    console.log(`  ${label}: 정리할 것 없음 (보관 ${keep.size}건)`);
    return;
  }
  for (const o of orphans) {
    await o.delete();
    console.log(`  ${label} 삭제: ${o.name}`);
  }
  console.log(`  ${label}: ${orphans.length}건 삭제, ${keep.size}건 보관`);
}

/** 사진. 첨부와 마찬가지로 이미 같은 크기로 올라가 있으면 건너뛴다 —
 *  예전에는 매일 밤 41MB 를 통째로 다시 올렸다. */
async function uploadImages(bucket, images, remoteSize) {
  const plan = planUploads(images, remoteSize, localSizeOf);
  plan.missing.forEach((rel) => console.warn(`  [건너뜀] 파일 없음: ${rel}`));
  let done = 0;
  for (const rel of plan.put) {
    // assets/images/2026-05/x.png -> images/2026-05/x.png
    const dest = rel.replace(/^assets\//, "");
    const ext = path.extname(rel).toLowerCase();
    // 갤러리용 작은 사진은 webp 다. 타입을 틀리게 주면 브라우저가 그림으로 읽지 않는다.
    // 동영상도 이 목록으로 올라간다 — mp4 를 image/jpeg 로 올리면 재생되지 않는다.
    const TYPES = {
      ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif",
      ".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm",
    };
    await bucket.upload(path.join(ROOT, rel), {
      destination: dest,
      metadata: {
        contentType: TYPES[ext] || "image/jpeg",
        cacheControl: "private, max-age=86400",
      },
    });
    done++;
    process.stdout.write(`  images: ${done}/${plan.put.length}\r`);
  }
  console.log(`  images: ${done}건 업로드, ${plan.skip.length}건 이미 있음 ` +
    "(비공개 — 멤버만 접근)");
}

async function main() {
  const meta = readPayload("meta.json");
  const media = readPayload("media.json");
  const mine = readPayload("my-messages.json");
  const threads = readPayload("threads.json");
  const digests = readPayload("digests.json");
  const graph = readPayload("graph.json");
  const source = readPayload("messages-source.json");
  const members = readPayload("members.json");
  const images = readPayload("images.json");
  const files = readPayload("files.json");

  const digestDocs = Object.keys(digests).map((k) => ({ id: k, ...digests[k] }));
  const sourceDocs = source.map((m) => ({ id: m.id, ...m }));
  const mineDocs = Object.keys(mine).map((email) => ({ id: email, items: mine[email] }));
  /* 이번 실행이 전량인지 먼저 정한다 — 계획 출력에도 그대로 쓴다. */
  const prevState = loadState(STATE_PATH);
  const needFull = FORCE_FULL || !prevState || staleState(prevState, Date.now(), FULL_EVERY_DAYS);
  const fullWhy = FORCE_FULL ? "--full"
    : !prevState ? "대장 없음·읽을 수 없음"
    : "마지막 전량 동기화가 " + FULL_EVERY_DAYS + "일 지남";

  const docCount = 1 + 1 + 1 + digestDocs.length + 2;   // meta·threads·media·digests·graph
  console.log("적재 계획 (문서 수)");
  console.log(`  meta 1 / threads 1 (${threads.length}건 묶음) / media 1 (${media.length}건 묶음)`);
  console.log(`  digests ${digestDocs.length} / graph 2`);
  console.log(`  members ${members.length}명 — 적재하지 않음 (Firestore 가 주인)`);
  console.log(`  myMessages ${mineDocs.length}명분 (본인만 읽음)`);
  console.log(`  messagesSource ${sourceDocs.length} (관리자 전용 원본)`);
  console.log(`  → 멤버가 전체를 읽을 때: ${docCount + 1}회 읽기`);
  console.log(`  이미지 ${images.length}장 (Storage, 지연 로딩)`);
  console.log(`  첨부 파일 ${files.length}개 (Storage, 내려받기)`);

  if (needFull) {
    console.log(`  방식: 전량 (${fullWhy}) — 쓰기 ${docCount + sourceDocs.length}건`);
  } else {
    // 대장과 견줘 실제로 몇 건이 바뀌는지 미리 알려 준다 (dry-run 의 값어치)
    const changed =
      planWrites(prevState.collections.threads, [{ id: "all", items: threads }]).writes.length +
      planWrites(prevState.collections.media, [{ id: "all", items: media }]).writes.length +
      planWrites(prevState.collections.myMessages, mineDocs).writes.length +
      planWrites(prevState.collections.digests, digestDocs).writes.length +
      planWrites(prevState.collections.messagesSource, sourceDocs).writes.length;
    console.log(`  방식: 변경분만 (대장 ${prevState.updated_at || "?"} 기준) — ` +
      `meta 1 + 그래프 최대 2 + 바뀐 문서 ${changed}건`);
  }

  if (!members.length) {
    // 거울이 비었을 뿐 Firestore 명부는 멀쩡할 수 있다. 닉네임 대조만 못 하게 된다.
    console.warn("\n[주의] 로컬 거울(config/members.json)이 비어 있습니다. " +
      "node scripts/sync_members.js 로 Firestore 에서 끌어오세요.");
  }
  if (DRY) {
    console.log("\n--dry-run: 실제 쓰기 없음");
    return;
  }

  init();
  await verifyCredential();
  const db = admin.firestore();

  console.log("\nFirestore 적재" + (needFull ? ` — 전량 (${fullWhy})` : " — 변경분만"));
  const prev = (name) => (prevState && prevState.collections[name]) || null;
  const nextState = { state_version: STATE_VERSION, project: PROJECT_ID, collections: {} };
  const sync = async (name, docs) => {
    nextState.collections[name] = await syncCollection(db, name, docs,
      { full: needFull, prev: prev(name) });
  };

  // meta 의 updatedAt 은 매번 달라진다. 마지막 발행 시각을 남기는 자리라 그대로 둔다 (1건).
  await sync("meta", [{ id: "archive", ...meta, updatedAt: new Date().toISOString() }]);
  // 스레드 요약이 멤버가 보는 본문이다. 165건이지만 합쳐 83KB뿐이라 한 문서로
  // 발행한다 — 개별 문서로 두면 전체 로드에 165회 읽기가 추가된다.
  await sync("threads", [{ id: "all", items: threads }]);
  await sync("media", [{ id: "all", items: media }]);
  await sync("myMessages", mineDocs);
  // chunks 는 더 이상 발행하지 않는다. 예전 적재분을 지운다.
  await sync("chunks", []);
  await sync("digests", digestDocs);
  await sync("graph", [
    { id: "nodes", items: graph.nodes },
    { id: "edges", items: graph.edges },
  ]);
  // members 는 여기서 동기화하지 않는다.
  //
  // 멤버 명부의 주인은 Firestore 다 — 관리자 페이지(approveClaim Function)와
  // approve_claims.js 가 Admin SDK 로 직접 쓴다. 예전처럼 config/members.json 을
  // 기준으로 동기화하면, 웹에서 승인한 사람이 그 파일에 없어 '구문서'로 판정되고
  // 그날 밤 발행에서 조용히 삭제된다. 승인한 다음 날 권한이 사라지는 셈이다.
  //
  // config/members.json 은 로컬 거울이다. scripts/sync_members.js 가 Firestore
  // 에서 끌어와 갱신하고, 파이프라인은 닉네임 대조용으로만 읽는다.
  await sync("messagesSource", sourceDocs);

  if (!SKIP_IMAGES) {
    console.log("Storage 업로드");
    const bucket = admin.storage().bucket();
    // 목록을 한 번 받아 '건너뛸지'와 '고아인지'에 함께 쓴다
    const imgRemote = await remoteIndex(bucket, "images/");
    // 갤러리용 작은 사진은 thumbs/ 밑에 따로 있다. 이 목록을 안 받으면 '이미 있음'
    // 판정을 못 해 매일 밤 312장을 다시 올린다.
    const thumbRemote = await remoteIndex(bucket, "thumbs/");
    const fileRemote = await remoteIndex(bucket, "files/");
    const imgSize = new Map([...imgRemote.size, ...thumbRemote.size]);
    await uploadImages(bucket, images, imgSize);
    if (files.length) await uploadFiles(bucket, files, fileRemote.size);

    // 발행본에서 빠진 것은 저장소에서도 지운다 (삭제 요청·수집 거부 반영)
    if (KEEP_ORPHANS) {
      console.log("  --keep-orphans: 저장소 정리를 건너뜁니다.");
    } else {
      await pruneOrphans(bucket, "images/", images, "images", imgRemote.objects);
      await pruneOrphans(bucket, "thumbs/", images, "thumbs", thumbRemote.objects);
      await pruneOrphans(bucket, "files/", files, "files", fileRemote.objects);
    }
  }

  /* 대장은 여기까지 다 성공했을 때만 쓴다. 중간에 터지면 옛 대장이 남고, 다음
     실행은 이미 올린 것까지 다시 쓴다 — 덜 쓰는 쪽이 아니라 더 쓰는 쪽으로 틀린다. */
  nextState.updated_at = new Date().toISOString();
  nextState.last_full = needFull ? nextState.updated_at
    : (prevState && prevState.last_full) || nextState.updated_at;
  fs.mkdirSync(path.dirname(STATE_PATH), { recursive: true });
  fs.writeFileSync(STATE_PATH, JSON.stringify(nextState) + "\n", "utf8");

  console.log("\n완료. 다음: firebase deploy");
}

module.exports = { stableStringify, docHash, planWrites, planUploads, loadState, staleState,
                   syncCollection, STATE_VERSION, STATE_PATH };

if (require.main === module) {
  main().catch((e) => {
    console.error("\n실패:", e.message);
    process.exit(1);
  });
}
