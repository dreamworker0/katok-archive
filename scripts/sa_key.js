/**
 * 서비스 계정 키가 어디 있는지 — 한 곳에서 정한다.
 *
 * 예전에는 프로젝트 폴더 맨 위(serviceAccountKey.json)에 두었다. 두 가지가 걸렸다.
 *   1. 이 폴더에서 AI 도구(claude -p · agy)를 돌린다. 프롬프트에는 단톡방 글이
 *      그대로 들어가고, agy 는 도구를 끌 수 없어 폴더 안 파일을 읽는다(실측
 *      2026-10-03). 키가 옆에 있으면 '키 파일을 읽어 적어라' 한 줄이 위험해진다.
 *   2. 폴더 권한을 물려받아 이 PC 의 다른 계정 그룹(CodexSandboxUsers 등)도 읽고
 *      고칠 수 있었다. 이 키는 Firestore·Storage 규칙을 모두 건너뛴다.
 *
 * 그래서 프로젝트 밖, 본인만 읽는 폴더로 옮겼다. 찾는 순서:
 *   KATOK_SA_KEY 환경변수 → %USERPROFILE%\.katok-archive\serviceAccountKey.json
 *   → 프로젝트 폴더(예전 자리 — 아직 안 옮긴 PC 를 위해 남긴다)
 * 어디에도 없으면 첫 번째 후보를 돌려준다. 부르는 쪽은 늘 하던 대로 exists 를 보고
 * 없으면 gcloud ADC 로 넘어간다.
 */
const fs = require("fs");
const os = require("os");
const path = require("path");

const candidates = [
  process.env.KATOK_SA_KEY,
  path.join(os.homedir(), ".katok-archive", "serviceAccountKey.json"),
  path.join(__dirname, "..", "serviceAccountKey.json"),
].filter(Boolean);

module.exports = candidates.find((p) => fs.existsSync(p)) || candidates[0];
