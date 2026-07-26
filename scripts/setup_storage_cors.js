#!/usr/bin/env node
/**
 * Storage 버킷에 CORS 설정을 적용한다. (1회성 설정, 멤버 변경과 무관)
 *
 * 왜 필요한가
 *   Firebase Storage 는 API 오류 응답(403 등)에는 CORS 헤더를 붙이지만,
 *   실제 객체 다운로드(200 + 본문)에는 **버킷 CORS 설정이 없으면 붙이지 않는다.**
 *   그래서 브라우저가 성공 응답을 차단하고 fetch 는 "Failed to fetch" 로 실패한다.
 *   (SDK 의 getBlob() 을 쓰더라도 같은 설정이 필요하다.)
 *
 * 보안
 *   CORS 는 "어느 웹페이지가 응답을 읽을 수 있는가"만 정한다. 누가 파일을
 *   읽을 수 있는지는 여전히 storage.rules 가 결정하므로, 이 설정이 공개로
 *   바꾸는 것은 아니다.
 *
 * 사용: node scripts/setup_storage_cors.js [--show]
 */
const fs = require("fs");
const path = require("path");
const admin = require("firebase-admin");

const ROOT = path.resolve(__dirname, "..");
const KEY = path.join(ROOT, "serviceAccountKey.json");
const BUCKET = "katok-crawling-project.firebasestorage.app";

// 아카이브를 서비스하는 출처만 허용한다. 커스텀 도메인을 붙이면 여기에 추가.
const ORIGINS = [
  // 주 주소
  "https://sw-ai-archive.web.app",
  // 예전 주소 — 공유된 링크가 남아 있어 계속 살려둔다
  "https://katok-crawling-project.web.app",
  "https://katok-crawling-project.firebaseapp.com",
  "http://localhost:5000",
  "http://127.0.0.1:5000",
];

const CORS = [
  {
    origin: ORIGINS,
    method: ["GET", "HEAD"],
    responseHeader: ["Content-Type", "Content-Length", "Content-Range", "Range", "Authorization"],
    maxAgeSeconds: 3600,
  },
];

async function main() {
  if (!fs.existsSync(KEY)) {
    console.error("serviceAccountKey.json 이 필요합니다.");
    process.exit(1);
  }
  admin.initializeApp({
    credential: admin.credential.cert(require(KEY)),
    storageBucket: BUCKET,
  });
  const bucket = admin.storage().bucket();

  if (process.argv.includes("--show")) {
    const [meta] = await bucket.getMetadata();
    console.log("현재 CORS 설정:");
    console.log(JSON.stringify(meta.cors || [], null, 2));
    return;
  }

  await bucket.setCorsConfiguration(CORS);
  const [meta] = await bucket.getMetadata();
  console.log("CORS 설정 적용 완료:");
  (meta.cors || []).forEach((c) => {
    console.log("  출처:", (c.origin || []).join(", "));
    console.log("  메서드:", (c.method || []).join(", "));
  });
  console.log("\n주의: 접근 권한은 여전히 storage.rules 가 결정합니다 (공개 아님).");
}

main().catch((e) => {
  console.error("실패:", e.message);
  if (/permission|forbidden/i.test(e.message)) {
    console.error(
      "\n서비스 계정에 Storage 관리 권한이 필요합니다.\n" +
      "콘솔 > IAM 에서 firebase-adminsdk 계정에 'Storage 관리자'를 부여하거나,\n" +
      "gcloud 로: gcloud storage buckets update gs://" + BUCKET +
      ' --cors-file=cors.json'
    );
  }
  process.exit(1);
});
