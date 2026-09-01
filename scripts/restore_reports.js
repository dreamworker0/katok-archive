#!/usr/bin/env node
/**
 * Firestore 에 발행된 보고서를 output/reports/*.md 로 되살린다.
 *
 * 왜 필요한가
 *   대화 데이터를 저장소에서 뺀 뒤(2026-07-26), 손으로 쓴 보고서 원본이 로컬 디스크
 *   한 곳에만 남았다. 디스크가 죽으면 45개가 사라진다. 다행히 보고서 본문은 발행
 *   과정에서 threads/all 문서에 통째로 실려 Firestore 에 올라가 있다 — 발행 부산물이
 *   결과적으로 원격 사본 노릇을 한다. 이 스크립트가 그 사본을 md 로 되돌린다.
 *
 *   물론 완전한 대체는 아니다. Firestore 에는 '마지막으로 발행한 판'만 있고 고친
 *   이력은 없다. 원본은 여전히 md 이고, 이 스크립트는 최후의 복구 수단이다.
 *
 * 사용
 *   node scripts/restore_reports.js --dry-run     # 무엇이 없고 무엇이 다른지만 본다
 *   node scripts/restore_reports.js               # 없는 파일만 만든다 (기존 파일 보존)
 *   node scripts/restore_reports.js --force       # 다른 파일까지 발행본으로 덮는다
 *   node scripts/restore_reports.js --out tmp/    # 다른 폴더에 풀어 눈으로 견줘 본다
 */
const fs = require("fs");
const path = require("path");
const admin = require("firebase-admin");

const ROOT = path.resolve(__dirname, "..");
const KEY = path.join(ROOT, "serviceAccountKey.json");
const PROJECT_ID = "katok-crawling-project";

const args = process.argv.slice(2);
const DRY = args.includes("--dry-run");
const FORCE = args.includes("--force");
const outIdx = args.indexOf("--out");
const OUT = outIdx !== -1 && args[outIdx + 1]
  ? path.resolve(ROOT, args[outIdx + 1])
  : path.join(ROOT, "output", "reports");

function init() {
  if (fs.existsSync(KEY)) {
    admin.initializeApp({
      credential: admin.credential.cert(require(KEY)),
      projectId: PROJECT_ID,
    });
    return;
  }
  try {
    admin.initializeApp({ credential: admin.credential.applicationDefault(), projectId: PROJECT_ID });
  } catch (e) {
    console.error("인증 정보를 찾지 못했습니다 — serviceAccountKey.json 또는 gcloud ADC 가 필요합니다.");
    process.exit(1);
  }
}

/** 프론트매터 + 본문. scripts/topic_reports.py 의 parse_report 가 읽는 형식 그대로다. */
function toMarkdown(t) {
  const one = (s) => String(s == null ? "" : s).replace(/\r?\n+/g, " ").trim();
  return ["---",
    "title: " + one(t.title),
    "summary: " + one(t.summary),
    "keywords: " + (t.keywords || []).map(one).join(", "),
    "---", "",
    String(t.report || "").trim(), ""].join("\n");
}

async function main() {
  init();
  /* 컬렉션 전체를 훑는다. `threads/all` 한 문서를 콕 집어 읽던 동안에는, 발행이
   * 나눠 담기로 바뀌면(2026-09-02) 이 복구 도구가 **아무것도 못 찾는다** — 없는
   * 문서를 보고 "아직 발행하지 않았다" 고 말한다. 되살리는 도구가 조용히 절반만
   * 되살리는 것은 더 나쁘다. 화면(boot.js)이 이미 이렇게 읽는다. */
  const snap = await admin.firestore().collection("threads").get();
  if (snap.empty) {
    console.error("threads 컬렉션이 비어 있습니다 — 아직 발행하지 않았거나 프로젝트가 다릅니다.");
    process.exit(1);
  }
  const all = [];
  snap.forEach((d) => { (d.data().items || []).forEach((t) => all.push(t)); });
  const items = all.filter((t) => t.report && String(t.report).trim());
  console.log(`발행본에서 보고서 ${items.length}개를 찾았습니다.`);
  if (!items.length) process.exit(1);

  fs.mkdirSync(OUT, { recursive: true });
  const made = [], same = [], diff = [];
  for (const t of items) {
    const file = path.join(OUT, t.id + ".md");
    const body = toMarkdown(t);
    if (!fs.existsSync(file)) {
      if (!DRY) fs.writeFileSync(file, body, "utf8");
      made.push(t.id);
      continue;
    }
    // 줄바꿈만 다른 것(CRLF)을 '다르다'고 하면 매번 시끄럽다
    const cur = fs.readFileSync(file, "utf8").replace(/\r\n/g, "\n");
    if (cur.trim() === body.trim()) { same.push(t.id); continue; }
    diff.push(t.id);
    if (FORCE && !DRY) fs.writeFileSync(file, body, "utf8");
  }

  console.log(`  새로 만듦 ${made.length} / 그대로 ${same.length} / 내용이 다름 ${diff.length}`);
  if (diff.length) {
    console.log("  다른 파일: " + diff.slice(0, 10).join(", ") + (diff.length > 10 ? " …" : ""));
    console.log(FORCE
      ? "  --force: 발행본으로 덮었습니다."
      : "  로컬 쪽이 더 최신일 수 있어 두었습니다. 발행본으로 되돌리려면 --force.");
  }
  if (DRY) console.log("--dry-run: 파일을 쓰지 않았습니다.");
  else console.log(`받은 곳: ${path.relative(ROOT, OUT) || "."}`);
}

main().catch((e) => {
  console.error("\n실패:", e.message);
  process.exit(1);
});
