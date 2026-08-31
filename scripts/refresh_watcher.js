#!/usr/bin/env node
/**
 * '지금 갱신' 감시 — 관리 탭 버튼과 이 PC 를 잇는 조각.
 *
 * 왜 이런 게 필요한가
 *   갱신의 본체(run_daily.ps1)는 카톡 창에 Ctrl+S 를 보내 대화를 내보내고 로컬
 *   output/ 을 고친다. 클라우드에는 카톡도 output/ 도 없으니 Functions 로 옮길 수
 *   없다. 그래서 웹은 settings/refresh 문서에 "갱신해 달라"고만 적고, 그 신호를
 *   받아 실제로 실행하는 일을 이 스크립트가 이 PC 에서 맡는다.
 *
 * 폴링이 아니라 리스너다
 *   onSnapshot 은 서버가 바뀔 때만 밀어준다. 30초마다 물어보는 폴링이면 하루 2,880
 *   읽기가 아무 일 없어도 나가고, 버튼을 눌러도 최대 30초를 기다린다. 리스너는
 *   읽기가 바뀔 때만 들고 반응이 즉각적이다.
 *
 * 상태를 어떻게 되쓰는가
 *   queued → running → done | failed | skipped | expired
 *   화면은 이 문서만 보고 있으므로, 여기서 적지 않은 것은 관리자가 알 수 없다.
 *   그래서 실패도 반드시 적는다 — 조용히 끝나면 "누른 게 먹었나?"가 되고,
 *   그게 이 기능에서 가장 나쁜 결말이다.
 *
 * 이 스크립트가 하지 않는 일
 *   - 요청을 만들지 않는다. 만드는 것은 requestRefresh Function 뿐이다.
 *   - 겹침을 스스로 막지 않는다. 실제 잠금은 run_daily.ps1 의 파일 핸들이다
 *     (23:40 스케줄 실행과도 겹칠 수 있어 잠금은 거기 있어야 한다).
 *
 * 사용
 *   node scripts/refresh_watcher.js
 *   node scripts/refresh_watcher.js --once      # 대기 중인 요청 하나만 처리하고 끝
 *   node scripts/refresh_watcher.js --dry-run   # 실행하지 않고 무엇을 할지만 출력
 */
const fs = require("fs");
const path = require("path");
const { spawn } = require("child_process");
const admin = require("firebase-admin");

const ROOT = path.resolve(__dirname, "..");
const KEY = path.join(ROOT, "serviceAccountKey.json");
const LOG_DIR = path.join(ROOT, "logs");
const PROJECT_ID = "katok-crawling-project";

const ARGV = process.argv.slice(2);
const ONCE = ARGV.includes("--once");
const DRY = ARGV.includes("--dry-run");

// 요청이 이만큼 묵으면 실행하지 않고 만료시킨다.
//
// PC 가 사흘 꺼져 있었다면, 켜지는 순간 사흘 전 요청이 되살아나 갑자기 카톡 창을
// 붙잡는 편이 더 놀랍다. 관리자는 그때 다시 누르면 된다.
const MAX_REQUEST_AGE_MS = 6 * 60 * 60 * 1000;

// 하트비트 — 화면이 "이 PC 가 듣고 있는가"를 판단하는 유일한 근거다.
// 5분마다 쓰면 하루 288회, 사실상 공짜다. 화면은 12분까지 살아 있는 것으로 본다.
const HEARTBEAT_MS = 5 * 60 * 1000;

// run_daily.ps1 이 겹침을 알릴 때 쓰는 종료 코드 (실패가 아니다)
const EXIT_ALREADY_RUNNING = 75;

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

function stamp() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ` +
    `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

/** 콘솔과 파일에 함께 남긴다. 무인 실행이라 콘솔은 아무도 안 본다. */
function say(message, level = "INFO") {
  const line = `[${stamp()}] ${level} ${message}`;
  console.log(line);
  try {
    if (!fs.existsSync(LOG_DIR)) fs.mkdirSync(LOG_DIR, { recursive: true });
    const d = new Date();
    const p = (n) => String(n).padStart(2, "0");
    const file = path.join(LOG_DIR,
      `refresh-${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}.log`);
    fs.appendFileSync(file, line + "\n", "utf8");
  } catch (e) {
    // 로그를 못 써도 감시는 계속해야 한다
  }
}

function millisOf(value) {
  if (!value) return null;
  if (typeof value.toMillis === "function") return value.toMillis();
  const t = Date.parse(String(value));
  return Number.isNaN(t) ? null : t;
}

/**
 * run_daily.ps1 을 돌리고 결과를 요약한다.
 *
 * 출력을 전부 붙들지 않는다 — 하루치 로그는 수백 줄이고 Firestore 문서에 넣을
 * 것도 아니다. 화면에 필요한 것은 넷뿐이다: 성공했는가, 새 글이 몇 건인가,
 * 그중 주제 분류가 몇 건 됐고 미분류가 몇 개 남았는가, 실패했다면 어느 단계에서인가.
 * 전체 로그는 logs\daily-*.log 에 이미 남는다.
 *
 * 숫자는 전부 ASCII 표식으로 받는다(NEW_MESSAGES / CLASSIFIED / UNSORTED). 한글
 * 로그는 콘솔 코드페이지에 따라 깨지고, 깨진 글자는 절대 매칭되지 않는다.
 */
function runDaily() {
  return new Promise((resolve) => {
    const args = [
      "-ExecutionPolicy", "Bypass",
      "-NoProfile",
      "-File", path.join("scripts", "run_daily.ps1"),
    ];
    const child = spawn("powershell.exe", args, {
      cwd: ROOT,
      windowsHide: true,
      // 콘솔을 물려주지 않는다. 자식이 창을 띄우면 카톡의 최상단을 빼앗아
      // Ctrl+S 가 엉뚱한 창으로 갈 수 있다.
      stdio: ["ignore", "pipe", "pipe"],
    });

    let newMessages = null;
    let classified = null;
    let unsorted = null;
    let lastStep = null;
    let lastError = null;
    let buffered = "";

    const eat = (chunk) => {
      buffered += chunk.toString("utf8");
      const lines = buffered.split(/\r?\n/);
      buffered = lines.pop();
      for (const line of lines) {
        // 새 메시지 수는 ASCII 표식으로 받는다. 한글 로그는 콘솔 코드페이지에
        // 따라 깨질 수 있고, 깨진 글자는 절대 매칭되지 않는다
        // (같은 이유로 run_daily.ps1 도 이 표식을 쓴다).
        const n = line.match(/NEW_MESSAGES=(\d+)/);
        if (n) newMessages = parseInt(n[1], 10);
        const c = line.match(/CLASSIFIED=(\d+)/);
        if (c) classified = parseInt(c[1], 10);
        const u = line.match(/UNSORTED=(\d+)/);
        if (u) unsorted = parseInt(u[1], 10);
        const step = line.match(/--- (.+?) ---/);
        if (step) lastStep = step[1];
        if (/ ERROR /.test(line)) lastError = line.replace(/^\[[^\]]*\]\s*/, "");
      }
    };
    child.stdout.on("data", eat);
    child.stderr.on("data", eat);

    child.on("error", (e) => {
      resolve({ code: -1, newMessages: null, lastStep, error: e.message });
    });
    child.on("close", (code) => {
      resolve({
        code,
        newMessages,
        classified,
        unsorted,
        lastStep,
        error: lastError || (buffered.trim() ? buffered.trim().slice(0, 300) : null),
      });
    });
  });
}

/**
 * 끝난 갱신을 화면에 뭐라고 말할 것인가.
 *
 * 예전에는 새 글이 있으면 무조건 "주제 분류는 '미분류'로 들어갑니다" 라고 했다.
 * 사람이 주 1회 재분류하던 시절의 문장이다. 지금은 run_daily 5단계가 그 자리에서
 * 분류하고 보고서까지 쓰므로, 대개 그 말은 **사실이 아니다** — 버튼을 누른 사람은
 * 화면이 시킨 대로 미분류를 찾으러 갔다가 아무것도 없는 것을 본다.
 * (run_daily 의 로그 줄은 2026-08-04 에 같은 이유로 이미 고쳤는데, 버튼 경로만
 *  옛 문장을 그대로 들고 있었다.)
 *
 * 그래서 세어 보고 말한다. 못 읽은 값에 대해서는 **아무 말도 하지 않는다** —
 * 모르는 것을 0 이나 '남았다' 로 지어내면 화면이 다시 거짓말을 한다.
 */
function doneMessage(n, classified, unsorted) {
  if (n === null) return "갱신을 마쳤습니다.";
  const parts = [n > 0
    ? `새 메시지 ${n} 건을 반영했습니다.`
    : "새 메시지가 없었습니다. 이미 최신입니다."];
  if (classified > 0) parts.push(`주제 분류 ${classified} 건.`);
  if (unsorted > 0) {
    parts.push(`아직 '미분류' 스레드 ${unsorted} 개가 남아 있습니다 — ` +
      "다음 갱신에서 이어 정리합니다.");
  }
  return parts.join(" ");
}

/** 요청을 잡는다. queued 이고 아직 안 잡은 것일 때만 running 으로 바꾼다.
 *
 *  트랜잭션으로 하는 이유: 감시가 두 개 떠 있으면(로그온 시작이 중복 등록되는 실수는
 *  흔하다) 둘이 같은 요청을 잡아 카톡을 동시에 조작한다. 먼저 쓴 쪽만 이긴다. */
async function claim(ref, requestId) {
  return admin.firestore().runTransaction(async (tx) => {
    const snap = await tx.get(ref);
    const cur = snap.exists ? (snap.data() || {}) : {};
    if (cur.status !== "queued" || cur.requestId !== requestId) return false;
    tx.set(ref, {
      status: "running",
      startedAt: new Date().toISOString(),
      message: "PC 에서 갱신을 시작했습니다.",
    }, { merge: true });
    return true;
  });
}

async function finish(ref, requestId, fields) {
  await ref.set({
    ...fields,
    requestId,
    finishedAt: new Date().toISOString(),
  }, { merge: true });
}

async function handle(ref, data) {
  const requestId = data.requestId;
  const age = (() => {
    const at = millisOf(data.requestedAt);
    return at === null ? Infinity : Date.now() - at;
  })();

  if (age > MAX_REQUEST_AGE_MS) {
    const hours = Math.round(age / 3600000);
    say(`요청 ${requestId} 은 ${hours}시간 전 것 — 만료 처리합니다.`, "WARN");
    await finish(ref, requestId, {
      status: "expired",
      message: `${hours}시간 전 요청이라 실행하지 않았습니다. 다시 눌러 주세요.`,
    });
    return;
  }

  if (DRY) {
    say(`[dry-run] 요청 ${requestId} (${data.requestedBy}) 을 실행할 차례입니다.`);
    return;
  }

  if (!(await claim(ref, requestId))) {
    say(`요청 ${requestId} 은 다른 쪽이 먼저 잡았습니다 — 넘어갑니다.`);
    return;
  }

  say(`갱신 시작 — 요청 ${requestId} (${data.requestedBy})`);
  const r = await runDaily();

  if (r.code === 0) {
    const n = r.newMessages;
    say(`갱신 완료 — 새 메시지 ${n === null ? "?" : n} 건`);
    await finish(ref, requestId, {
      status: "done",
      exitCode: 0,
      newMessages: n,
      classified: r.classified,
      unsorted: r.unsorted,
      message: doneMessage(n, r.classified, r.unsorted),
    });
    return;
  }

  if (r.code === EXIT_ALREADY_RUNNING) {
    say("이미 다른 갱신이 돌고 있어 건너뛰었습니다.", "WARN");
    await finish(ref, requestId, {
      status: "skipped",
      exitCode: r.code,
      message: "이미 갱신이 돌고 있어 건너뛰었습니다. 끝난 뒤 다시 눌러 주세요.",
    });
    return;
  }

  say(`갱신 실패 (exit ${r.code}) — 단계: ${r.lastStep || "?"}`, "ERROR");
  await finish(ref, requestId, {
    status: "failed",
    exitCode: r.code,
    newMessages: r.newMessages,
    message: [
      r.lastStep ? `'${r.lastStep}' 단계에서 멈췄습니다.` : "갱신이 실패했습니다.",
      r.error ? String(r.error).slice(0, 300) : "",
      "카톡 방 창이 열려 있고 화면이 잠겨 있지 않은지 확인하세요.",
    ].filter(Boolean).join(" "),
  });
}

async function main() {
  init();
  const ref = admin.firestore().collection("settings").doc("refresh");

  // 한 번에 하나만 처리한다. 리스너는 running 으로 바꾼 내 쓰기 때문에도 다시
  // 불리므로, 처리 중에 들어온 알림은 흘려보내야 한다.
  let busy = false;
  const seen = new Set();

  // --dry-run 은 아무것도 쓰지 않는다. 하트비트도 쓰기다 — 확인해 보려고 돌린 것이
  // 화면에 "PC 연결됨"으로 뜨면, 실제로는 갱신을 받지 않는데 받는다고 보인다.
  //
  // 그리고 **듣고 있지 않는 동안에는 쓰지 않는다**. 리스너가 끊긴 채로 하트비트만
  // 계속 찍으면, 버튼이 먹지 않는데 화면에는 'PC 연결됨' 으로 보인다 — dry-run 을
  // 막아 둔 것과 똑같은 이유다.
  let listening = false;
  const beat = () => {
    if (DRY || !listening) return;
    ref.set({ watcherSeenAt: new Date().toISOString() }, { merge: true })
      .catch((e) => say(`하트비트 실패: ${e.message}`, "WARN"));
  };

  say(`감시 시작 (once=${ONCE} dry-run=${DRY})`);
  // 첫 하트비트는 첫 스냅샷에서 찍는다 — 그때가 실제로 듣기 시작한 순간이다.
  const timer = ONCE ? null : setInterval(beat, HEARTBEAT_MS);

  // 리스너가 끊겼을 때 어떻게 하는가 — 이 스크립트의 성패가 여기 있다.
  //
  // 예전에는 오류가 나면 그냥 끝냈다. '살아 있는 척하지 않는다'는 뜻은 맞았지만,
  // 예약 작업의 방아쇠가 **로그온 뿐**이라 한 번 죽으면 다음 로그온까지 되살아나지
  // 않았다. 실측 2026-08-20 08:53 "A backoff operation is already in progress." 로
  // 죽은 뒤, 관리 탭의 '지금 갱신' 이 이틀 동안 조용히 먹지 않았다. 주석에 적어 둔
  // 최악의 결말("누른 게 먹었나?")이 그대로 벌어진 것이다.
  //
  // 그래서 스스로 다시 붙는다. 간격을 늘려 가며(1초→5분) 무한히 시도한다 — 끝내는
  // 편이 더 위험하다. 못 듣는 동안 하트비트가 멈추므로 화면은 사실을 본다.
  const BACKOFF_MS = [1000, 2000, 5000, 15000, 30000, 60000, 120000, 300000];
  let attempt = 0;
  let retryTimer = null;
  let unsub = null;

  const stop = (code, why) => {
    say(why);
    if (unsub) unsub();
    if (timer) clearInterval(timer);
    if (retryTimer) clearTimeout(retryTimer);
    process.exit(code);
  };

  const onListenerError = (e) => {
    listening = false;
    if (unsub) { try { unsub(); } catch (_) { /* 이미 끊겼을 수 있다 */ } unsub = null; }
    // --once 는 사람이 확인용으로 돌리는 모드다. 매달려 재시도하면 확인이 안 된다.
    if (ONCE) { stop(1, `리스너 오류: ${e.message} — --once 이므로 종료합니다.`); return; }
    const wait = BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)];
    attempt += 1;
    say(`리스너 오류: ${e.message} — ${Math.round(wait / 1000)}초 뒤 다시 붙습니다 (${attempt}번째 시도).`, "WARN");
    retryTimer = setTimeout(subscribe, wait);
  };

  const subscribe = () => {
    retryTimer = null;
    unsub = ref.onSnapshot(async (snap) => {
      if (!listening) {
        listening = true;
        if (attempt > 0) say(`리스너 복구 — ${attempt}번 시도 끝에 다시 듣습니다.`);
        attempt = 0;
        beat();
      }
      const data = snap.exists ? (snap.data() || {}) : {};
      if (data.status !== "queued" || !data.requestId) {
        // --once 는 '지금 대기 중인 것 하나'만 본다. 없으면 기다리지 않고 끝낸다 —
        // 손으로 확인할 때 쓰는 모드라, 매달려 있으면 확인이 안 된다.
        if (ONCE && !busy) stop(0, "대기 중인 요청이 없습니다 — 종료합니다.");
        return;
      }
      if (busy || seen.has(data.requestId)) return;
      busy = true;
      // claim() 트랜잭션이 진짜 방어선이고 이 집합은 덧방어다. 오래 떠 있어도
      // 계속 자라지 않게 가끔 비운다.
      if (seen.size > 200) seen.clear();
      seen.add(data.requestId);
      try {
        await handle(ref, data);
      } catch (e) {
        say(`처리 중 오류: ${e.message}`, "ERROR");
        // 상태를 못 적으면 화면이 영영 '진행 중'으로 남는다. 한 번은 더 시도한다.
        try {
          await finish(ref, data.requestId, {
            status: "failed",
            message: "감시 스크립트에서 오류가 났습니다: " + e.message.slice(0, 200),
          });
        } catch (e2) {
          say(`상태 기록도 실패: ${e2.message}`, "ERROR");
        }
      } finally {
        busy = false;
        if (ONCE) stop(0, "--once 처리 완료 — 종료합니다.");
      }
    }, onListenerError);
  };

  subscribe();

  process.on("SIGINT", () => stop(0, "종료 신호 — 감시를 멈춥니다."));
  process.on("SIGTERM", () => stop(0, "종료 신호 — 감시를 멈춥니다."));
}

main().catch((e) => {
  say(`시작 실패: ${e.message}`, "ERROR");
  process.exit(1);
});
