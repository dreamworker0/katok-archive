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
 * 사용
 *   node scripts/upload_firestore.js              # 전체 적재
 *   node scripts/upload_firestore.js --dry-run    # 계획만 출력
 *   node scripts/upload_firestore.js --skip-images
 */
const fs = require("fs");
const path = require("path");
const admin = require("firebase-admin");

const ROOT = path.resolve(__dirname, "..");
const PAYLOAD = path.join(ROOT, "firestore-payload");
const KEY = path.join(ROOT, "serviceAccountKey.json");
const PROJECT_ID = "katok-crawling-project";
const BUCKET = "katok-crawling-project.firebasestorage.app";

const args = process.argv.slice(2);
const DRY = args.includes("--dry-run");
const SKIP_IMAGES = args.includes("--skip-images");
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

/** 컬렉션을 페이로드 상태로 동기화한다: 전부 set + 페이로드에 없는 문서 삭제. */
async function syncCollection(db, name, docs) {
  const ids = new Set(docs.map((d) => d.id));
  let written = 0;

  for (let i = 0; i < docs.length; i += BATCH_LIMIT) {
    const batch = db.batch();
    for (const d of docs.slice(i, i + BATCH_LIMIT)) {
      const { id, ...data } = d;
      batch.set(db.collection(name).doc(id), data);
    }
    await batch.commit();
    written += Math.min(BATCH_LIMIT, docs.length - i);
    process.stdout.write(`  ${name}: ${written}/${docs.length}\r`);
  }

  // 이전 적재에 있었지만 이번 페이로드에 없는 문서 제거 (재적재 멱등성)
  const existing = await db.collection(name).select().get();
  const stale = existing.docs.filter((d) => !ids.has(d.id));
  for (let i = 0; i < stale.length; i += BATCH_LIMIT) {
    const batch = db.batch();
    stale.slice(i, i + BATCH_LIMIT).forEach((d) => batch.delete(d.ref));
    await batch.commit();
  }
  console.log(
    `  ${name}: ${docs.length}건 적재${stale.length ? `, 구문서 ${stale.length}건 삭제` : ""}`
  );
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

/** 대화방에서 공유된 첨부 파일.
 *
 *  이미지와 달리 이미 올라간 것은 건너뛴다. 80MB 짜리 PDF 가 섞여 있어 매번 전부
 *  다시 올리면 일일 자동화가 느려지고 송신 비용도 든다. 크기가 같으면 같은 파일로
 *  본다 — 매니페스트가 sha256 을 들고 있지만 매번 원격 해시를 받아오는 편이 더 비싸다.
 */
async function uploadFiles(bucket, files) {
  let done = 0, skipped = 0;
  for (const rel of files) {
    const local = path.join(ROOT, rel);
    if (!fs.existsSync(local)) {
      console.warn(`  [건너뜀] 파일 없음: ${rel}`);
      continue;
    }
    const dest = rel.replace(/^assets\//, "");
    const size = fs.statSync(local).size;

    const [exists] = await bucket.file(dest).exists();
    if (exists) {
      const [meta] = await bucket.file(dest).getMetadata();
      if (Number(meta.size) === size) {
        skipped++;
        continue;
      }
    }

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

async function uploadImages(bucket, images) {
  let done = 0;
  for (const rel of images) {
    const local = path.join(ROOT, rel);
    if (!fs.existsSync(local)) {
      console.warn(`  [건너뜀] 파일 없음: ${rel}`);
      continue;
    }
    // assets/images/2026-05/x.png -> images/2026-05/x.png
    const dest = rel.replace(/^assets\//, "");
    const ext = path.extname(rel).toLowerCase();
    await bucket.upload(local, {
      destination: dest,
      metadata: {
        contentType: ext === ".png" ? "image/png" : "image/jpeg",
        cacheControl: "private, max-age=86400",
      },
    });
    done++;
    process.stdout.write(`  images: ${done}/${images.length}\r`);
  }
  console.log(`  images: ${done}건 업로드 (비공개 — 멤버만 접근)`);
}

async function main() {
  const meta = readPayload("meta.json");
  const chunks = readPayload("chunks.json");
  const threads = readPayload("threads.json");
  const digests = readPayload("digests.json");
  const graph = readPayload("graph.json");
  const source = readPayload("messages-source.json");
  const members = readPayload("members.json");
  const images = readPayload("images.json");
  const files = readPayload("files.json");

  const digestDocs = Object.keys(digests).map((k) => ({ id: k, ...digests[k] }));
  const sourceDocs = source.map((m) => ({ id: m.id, ...m }));
  const docCount = 1 + chunks.length + 1 + digestDocs.length + 2;
  console.log("적재 계획 (문서 수)");
  console.log(`  meta 1 / chunks ${chunks.length} / threads 1 (${threads.length}건 묶음)`);
  console.log(`  digests ${digestDocs.length} / graph 2`);
  console.log(`  members ${members.length}명 — 적재하지 않음 (Firestore 가 주인)`);
  console.log(`  messagesSource ${sourceDocs.length} (관리자 전용 원본)`);
  console.log(`  총 쓰기 ${docCount + sourceDocs.length}건`);
  console.log(`  → 멤버가 전체를 읽을 때: ${docCount + 1}회 읽기`);
  console.log(`  이미지 ${images.length}장 (Storage, 지연 로딩)`);
  console.log(`  첨부 파일 ${files.length}개 (Storage, 내려받기)`);

  if (!memberDocs.length) {
    console.warn("\n[주의] 멤버가 0명입니다. config/members.json 을 채우세요 — 아무도 로그인할 수 없습니다.");
  }
  if (DRY) {
    console.log("\n--dry-run: 실제 쓰기 없음");
    return;
  }

  init();
  await verifyCredential();
  const db = admin.firestore();

  console.log("\nFirestore 적재");
  await syncCollection(db, "meta", [{ id: "archive", ...meta, updatedAt: new Date().toISOString() }]);
  await syncCollection(db, "chunks", chunks);
  // 스레드는 165건이지만 전부 합쳐 58KB뿐이라 한 문서로 발행한다.
  // 개별 문서로 두면 전체 로드에 165회 읽기가 추가된다.
  await syncCollection(db, "threads", [{ id: "all", items: threads }]);
  await syncCollection(db, "digests", digestDocs);
  await syncCollection(db, "graph", [
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
  await syncCollection(db, "messagesSource", sourceDocs);

  if (!SKIP_IMAGES) {
    console.log("Storage 업로드");
    const bucket = admin.storage().bucket();
    await uploadImages(bucket, images);
    if (files.length) await uploadFiles(bucket, files);
  }

  console.log("\n완료. 다음: firebase deploy");
}

main().catch((e) => {
  console.error("\n실패:", e.message);
  process.exit(1);
});
