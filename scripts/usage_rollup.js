/**
 * 사용 기록을 날짜별 합계로 접는다 — 관리 탭 '사용 통계' 의 지난 날 몫.
 *
 * 화면은 접속·메뉴·검색어·AI 단추를 한 건씩 usageEvents 에 남긴다(web/usage.js).
 * 그대로 두면 관리자가 통계를 열 때마다 수천 건을 읽고, 접속 기록에 붙은 이메일도
 * 계속 남는다. 그래서 어제까지의 원본을 날짜별 합계 하나(settings/usage 의 days)로
 * 접고 원본은 지운다. 오늘 것은 아직 모이는 중이라 건드리지 않는다.
 *
 * 두 번 돌려도 안전하다. 이미 합계가 있는 날은 다시 세지 않고 남은 원본만 지운다 —
 * 합계를 쓴 뒤 지우다 멈췄다면 남은 것은 이미 센 것이다. 합계를 쓰기 전에 멈췄다면
 * 원본이 그대로라 다음 번에 처음부터 센다. (합계 문서는 한 번에 통째로 쓴다.)
 *
 * 합계 내는 함수는 화면과 같은 것(web/usage.js summarize)을 쓴다 — 오늘 몫은 화면이,
 * 지난 날 몫은 여기서 같은 식으로 센다.
 *
 * run_daily.ps1 이 맨 앞에서 부른다(내보내기가 실패해도 접히게). 실패해도 갱신은 계속한다.
 *
 *   node scripts/usage_rollup.js            # 접고 지운다
 *   node scripts/usage_rollup.js --dry-run  # 몇 건을 어느 날로 접을지만 보인다
 */
const fs = require("fs");
const path = require("path");
const admin = require("firebase-admin");

const KEY = require("./sa_key");   // 프로젝트 밖으로 옮겼다 — sa_key.js 참고
const USAGE = require(path.join(__dirname, "..", "web", "usage.js"));

// 합계 문서는 1MiB 를 넘으면 안 된다. 하루 1~2KB 라 400일이면 넉넉하다.
const KEEP_DAYS = 400;
const BATCH = 400;

/**
 * 원본을 기존 합계에 접는다(순수 함수 — tests/usage.test.js).
 * events 는 [{ id, type, day, key?, by? }], cur 는 settings/usage 문서(없으면 null).
 * 돌려주는 것: { doc: 새 합계 문서, deleteIds: 지울 원본, folded: 새로 센 날들 }
 */
function rollup(events, cur, today) {
  const days = Object.assign({}, (cur && cur.days) || {});
  const byDay = {};
  const deleteIds = [];
  for (const e of events) {
    if (!e.day || e.day >= today) continue;
    deleteIds.push(e.id);
    (byDay[e.day] = byDay[e.day] || []).push(e);
  }
  const folded = [];
  for (const d of Object.keys(byDay).sort()) {
    if (days[d]) continue;   // 이미 접었다 — 남은 원본은 지난번에 지우다 멈춘 것
    days[d] = USAGE.summarize(byDay[d], 50);
    folded.push(d);
  }
  const cutoff = USAGE.addDays(today, -KEEP_DAYS);
  for (const d of Object.keys(days)) if (d < cutoff) delete days[d];
  const known = Object.keys(days).sort();
  return {
    doc: { days, through: known[known.length - 1] || "", updatedAt: new Date().toISOString() },
    deleteIds,
    folded,
  };
}

function init() {
  if (fs.existsSync(KEY)) {
    admin.initializeApp({ credential: admin.credential.cert(require(KEY)) });
    return;
  }
  admin.initializeApp({ credential: admin.credential.applicationDefault() });
}

async function main() {
  const dry = process.argv.includes("--dry-run");
  init();
  const db = admin.firestore();
  const today = USAGE.dayOf(Date.now());
  const snap = await db.collection("usageEvents").where("day", "<", today).get();
  const events = snap.docs.map((d) => Object.assign({ id: d.id }, d.data()));
  const ref = db.collection("settings").doc("usage");
  const cur = await ref.get();
  const r = rollup(events, cur.exists ? cur.data() : null, today);

  // 내일보다 뒤 날짜는 화면이 쓸 수 없는 값이다 — 규칙이 '오늘 무렵' 만 받게 되기
  // 전(2026-11-11)에 들어온 것일 수 있다. 위 질의('오늘보다 앞선 날')로는 영영
  // 안 잡히므로 따로 찾아 합계에 넣지 않고 지운다.
  const tomorrow = USAGE.addDays(today, 1);
  const futureSnap = await db.collection("usageEvents").where("day", ">", tomorrow).get();
  const futureIds = futureSnap.docs.map((d) => d.id);

  const line = `사용 기록 ${events.length}건 · 새로 접은 날 ${r.folded.length}일` +
    (r.folded.length ? ` (${r.folded[0]} ~ ${r.folded[r.folded.length - 1]})` : "") +
    (futureIds.length ? ` · 미래 날짜 ${futureIds.length}건` : "");
  if (dry) { console.log("[dry-run] " + line); return; }

  await deleteAll(db, futureIds);
  if (!events.length) { console.log(line); return; }

  await ref.set(r.doc);
  await deleteAll(db, r.deleteIds);
  console.log(line + ` · 원본 ${r.deleteIds.length + futureIds.length}건 지움`);
}

async function deleteAll(db, ids) {
  for (let i = 0; i < ids.length; i += BATCH) {
    const b = db.batch();
    ids.slice(i, i + BATCH).forEach((id) => b.delete(db.collection("usageEvents").doc(id)));
    await b.commit();
  }
}

module.exports = { rollup, KEEP_DAYS };

if (require.main === module) {
  // 끝나면 연결을 닫는다(2026-11-11) — 안 닫으면 gRPC 핸들이 남아 늦게 끝난다
  main()
    .then(() => admin.app().delete().catch(() => {}))
    .catch((e) => {
      console.error("사용 기록 접기 실패:", e.message || e);
      process.exit(1);
    });
}
