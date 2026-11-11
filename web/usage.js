/* ============ 사용 통계 (web/usage.js) ============
 *
 * 관리자 탭의 '사용 통계' 카드와, 그 재료를 남기는 기록기. 2026-11-01 만들었다.
 *
 * 무엇을 세나
 *   visit   들어올 때마다 한 번(로그인 뒤 화면이 뜬 때). 하루 방문자 수를 세려고
 *           이것에만 본인 이메일이 붙는다.
 *   view    메뉴를 누른 것(data-view). 첫 화면은 누르지 않아도 보이므로 누른 것만 센다.
 *   search  검색창에 친 말 — 다 친 말 하나에 한 번. 손을 멈춘 때(SEARCH_IDLE_MS)는
 *           쥐고만 있다가 Enter·창을 떠날 때·다른 말로 바꿀 때 보낸다. 이어 치는
 *           도중의 앞부분('다온' → '다온가 최근에…')은 따로 세지 않는다.
 *   ai      AI 단추 — 물어보기·다시 확인·답 속 근거·카드의 AI 보고서 펼치기.
 *
 * 합계만 본다(사용자 결정). 메뉴·검색어·AI 에는 이름을 붙이지 않고, 규칙이 그것을
 * 지킨다(firestore.rules usageEvents). 원본 한 건 한 건은 밤마다 PC 가 날짜별 합계로
 * 접어 settings/usage 에 두고 지운다(scripts/usage_rollup.js). 오늘 것은 아직
 * 원본이라 관리자 화면이 직접 읽어 합친다.
 *
 * 위쪽은 순수 함수(검사는 tests/usage.test.js — 합계 내는 PC 도 같은 함수를 쓴다),
 * 아래는 기록기(install, boot.js 가 부른다)와 대시보드(Dashboard, admin.js 가 부른다).
 * text.js 와 같은 방식으로 브라우저에서는 전역, node 에서는 require 로 쓴다.
 */
(function () {
  "use strict";

  var api = {};
  var KST_MS = 9 * 3600 * 1000;
  var DAY_MS = 24 * 3600 * 1000;

  // 메뉴 이름. 화면 단추 글자와 같게 둔다 — 대시보드를 보는 사람이 바로 알아보게.
  var VIEW_LABEL = {
    summary: "주제별 지식", timeline: "타임라인", graph: "관계망", tags: "태그",
    gallery: "갤러리", files: "첨부파일", stats: "통계", mine: "내 글 관리",
    admin: "관리자", help: "도움말",
  };
  var AI_LABEL = {
    ask: "AI에게 물어보기", verify: "지금 기준으로 다시 확인",
    cite: "답 속 근거 열기", report: "카드의 AI 보고서 펼치기",
  };

  /** 한국 시각 기준 날짜(YYYY-MM-DD). PC 가 23:40 에 합계를 내므로 UTC 로 자르면 안 된다. */
  function dayOf(ms) {
    return new Date(ms + KST_MS).toISOString().slice(0, 10);
  }

  function addDays(day, n) {
    return dayOf(Date.parse(day + "T00:00:00+09:00") + n * DAY_MS);
  }

  /** 검색어 정리. 두 글자 미만은 세지 않는다 — 치는 도중의 한 글자는 검색이 아니다. */
  function normTerm(q) {
    var s = String(q == null ? "" : q).replace(/\s+/g, " ").trim().toLowerCase();
    return s.length < 2 ? "" : s.slice(0, 40);
  }

  /** 두 검색어가 한 검색을 이어 친 것인가 — 짧은 쪽이 긴 쪽의 앞부분이면.
   *  한글은 치는 도중 끝 글자가 바뀌므로(갗 → 가초) 짧은 쪽 끝 한 글자는 보지 않는다.
   *  두 글자짜리는 그대로 본다 — '요금' 과 '요리' 는 다른 검색이다. */
  function sameSearch(a, b) {
    if (!a || !b) return false;
    var s = a.length <= b.length ? a : b, l = s === a ? b : a;
    var head = s.length > 2 ? s.slice(0, -1) : s;
    return l.indexOf(head) === 0;
  }

  /** 검색 한 번을 언제 셀지. note 는 손을 멈춘 때(아직 안 보냄), commit 은 다 쳤다고
   *  볼 때, clear 는 칸을 비운 때. 이어 치는 동안은 쥔 말을 바꿔 끼우기만 한다. */
  function SearchTracker(send) {
    var pending = "", last = "";
    function commit() {
      var q = pending;
      pending = "";
      // 같은 말을 이어서 다시 세지 않는다(Enter 뒤 손을 떼는 경우 등).
      if (!q || q === last) return;
      last = q;
      send(q);
    }
    return {
      note: function (q) {
        if (!q) return;          // 한 글자로 지워 가는 중 — 쥔 말을 그대로 둔다
        if (pending && !sameSearch(pending, q)) commit();
        pending = q;
      },
      commit: commit,
      clear: function () { commit(); last = ""; },
    };
  }

  function bump(map, key, n) { map[key] = (map[key] || 0) + (n || 1); }

  function topList(map, n) {
    return Object.keys(map).map(function (t) { return { t: t, n: map[t] }; })
      .sort(function (a, b) { return b.n - a.n || (a.t < b.t ? -1 : 1); })
      .slice(0, n);
  }

  /** 하루치 원본 → 그날 합계. 이름(by)은 방문자 수를 세는 데만 쓰고 남기지 않는다. */
  function summarize(events, topN) {
    var out = { visits: 0, visitors: 0, views: {}, ai: {}, searches: 0, terms: [] };
    var who = {}, terms = {};
    (events || []).forEach(function (e) {
      if (!e) return;
      if (e.type === "visit") { out.visits++; if (e.by) who[e.by] = true; }
      else if (e.type === "view" && e.key) bump(out.views, e.key);
      else if (e.type === "ai" && e.key) bump(out.ai, e.key);
      else if (e.type === "search" && e.key) { out.searches++; bump(terms, e.key); }
    });
    out.visitors = Object.keys(who).length;
    out.terms = topList(terms, topN || 50);
    return out;
  }

  /** 여러 날의 합계를 기간 하나로 묶는다. days 는 { 'YYYY-MM-DD': 하루 합계 }. */
  function combine(days, from, to) {
    var tot = { visits: 0, visitorDays: 0, activeDays: 0, views: {}, ai: {}, searches: 0,
                terms: [], series: [] };
    var terms = {};
    for (var d = from; d <= to; d = addDays(d, 1)) {
      var r = days[d];
      tot.series.push({ day: d, visits: r ? r.visits || 0 : 0, visitors: r ? r.visitors || 0 : 0 });
      if (!r) continue;
      tot.visits += r.visits || 0;
      tot.visitorDays += r.visitors || 0;
      if (r.visits) tot.activeDays++;
      tot.searches += r.searches || 0;
      Object.keys(r.views || {}).forEach(function (k) { bump(tot.views, k, r.views[k]); });
      Object.keys(r.ai || {}).forEach(function (k) { bump(tot.ai, k, r.ai[k]); });
      (r.terms || []).forEach(function (x) { bump(terms, x.t, x.n); });
    }
    tot.terms = topList(terms, 20);
    return tot;
  }

  api.VIEW_LABEL = VIEW_LABEL;
  api.AI_LABEL = AI_LABEL;
  api.dayOf = dayOf;
  api.addDays = addDays;
  api.normTerm = normTerm;
  api.sameSearch = sameSearch;
  api.SearchTracker = SearchTracker;
  api.summarize = summarize;
  api.combine = combine;

  /* ---------- 기록기 ---------- */

  var SEARCH_IDLE_MS = 2000;
  // 한 번 열어 둔 화면이 무엇에 걸려 끝없이 쓰지 않게. 보통 한 번에 수십 건이다.
  var MAX_PER_PAGE = 300;

  /** 화면 전체에 귀를 하나 단다. 각 화면 파일은 건드리지 않는다 — 셀 곳이 늘어도
   *  여기 한 곳만 고치면 된다. 쓰기가 실패해도(규칙 배포 전, 오프라인) 조용히 넘긴다:
   *  통계를 남기려는 코드가 화면을 방해해서는 안 된다. */
  var installed = false;
  function install(db, user) {
    // 로그아웃했다 다시 들어오면 boot.js 가 한 번 더 부른다 — 귀가 둘이면 두 번 센다.
    if (installed || !db || !user || !user.email || typeof document === "undefined") return;
    installed = true;
    var email = user.email.toLowerCase();
    var col = db.collection("usageEvents");
    var sent = 0;
    function send(doc) {
      if (sent >= MAX_PER_PAGE) return;
      sent++;
      doc.day = dayOf(Date.now());
      try { col.add(doc).catch(function () {}); } catch (e) { /* 넘긴다 */ }
    }

    send({ type: "visit", by: email });

    // 붙잡기 단계에서 듣는다 — 단추의 본래 처리가 aria-expanded 를 바꾸기 전에 본다.
    document.addEventListener("click", function (e) {
      var t = e.target;
      if (!t || !t.closest) return;
      var v = t.closest("[data-view]");
      if (v) { send({ type: "view", key: v.getAttribute("data-view").slice(0, 40) }); return; }
      if (t.closest("[data-ai-ask]")) { send({ type: "ai", key: "ask" }); return; }
      if (t.closest("[data-ai-verify]")) { send({ type: "ai", key: "verify" }); return; }
      if (t.closest("[data-ai-jump]")) { send({ type: "ai", key: "cite" }); return; }
      var r = t.closest(".tc-ai-toggle");
      // 접을 때는 세지 않는다 — 몇 번 '봤는지' 를 센다.
      if (r && r.getAttribute("aria-expanded") !== "true") send({ type: "ai", key: "report" });
    }, true);

    var box = document.getElementById("searchInput");
    if (!box) return;
    var track = SearchTracker(function (q) { send({ type: "search", key: q }); });
    var timer = null;
    function idle() { clearTimeout(timer); timer = null; track.note(normTerm(box.value)); }
    function finish() { if (timer) idle(); track.commit(); }
    box.addEventListener("input", function () {
      clearTimeout(timer); timer = null;
      if (!box.value.trim()) { track.clear(); return; }
      timer = setTimeout(idle, SEARCH_IDLE_MS);
    });
    box.addEventListener("keydown", function (e) { if (e.key === "Enter") finish(); });
    box.addEventListener("blur", finish);
    // 검색창에 손을 둔 채 탭을 닫거나 옮겨도 마지막 검색은 센다.
    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "hidden") finish();
    });
  }
  api.install = install;

  /* ---------- 대시보드 (관리자 탭) ---------- */

  var RANGES = [7, 30, 90];

  function Dashboard(ctx) {
    var state = ctx.state, esc = ctx.esc;
    var cache = null;      // { days, since, loadedAt }
    var range = 30;

    function bars(rows, labels, empty) {
      if (!rows.length) return '<p class="use-empty">' + esc(empty) + "</p>";
      var max = rows.reduce(function (s, x) { return Math.max(s, x.n); }, 1);
      return rows.map(function (x) {
        var pct = Math.round((x.n / max) * 100);
        return '<div class="bar-row"><span class="lab">' + esc(labels ? labels[x.t] || x.t : x.t) +
          '</span><span class="track"><span class="fill" style="width:' + pct + '%"></span></span>' +
          '<span class="val">' + x.n + "</span></div>";
      }).join("");
    }

    function mapRows(map, labels, keepAll) {
      var keys = keepAll ? Object.keys(labels) : Object.keys(map);
      return keys.map(function (k) { return { t: k, n: map[k] || 0 }; })
        .filter(function (x) { return keepAll || x.n > 0; })
        .sort(function (a, b) { return b.n - a.n; });
    }

    function shortDay(d) { return Number(d.slice(5, 7)) + "/" + Number(d.slice(8, 10)); }

    /** 날마다 접속 — 한 계열이라 범례 없이 제목이 이름이다. 마우스를 올리면 그날 숫자. */
    function columns(series) {
      var max = series.reduce(function (s, x) { return Math.max(s, x.visits); }, 0);
      if (!max) return '<p class="use-empty">이 기간에는 접속 기록이 없어요.</p>';
      var cols = series.map(function (x) {
        var h = x.visits ? Math.max(3, Math.round((x.visits / max) * 100)) : 0;
        var tip = shortDay(x.day) + " · 접속 " + x.visits + "회 · " + x.visitors + "명";
        return '<span class="use-col" title="' + esc(tip) + '" aria-label="' + esc(tip) + '">' +
          '<span class="use-col__bar" style="height:' + h + '%"></span></span>';
      }).join("");
      var mid = series[Math.floor(series.length / 2)].day;
      return '<div class="use-cols" role="img" aria-label="날마다 접속 횟수, 가장 많은 날 ' + max + '회">' +
        '<span class="use-cols__max">' + max + "</span>" + cols + "</div>" +
        '<div class="use-axis"><span>' + shortDay(series[0].day) + "</span><span>" + shortDay(mid) +
        "</span><span>" + shortDay(series[series.length - 1].day) + "</span></div>";
    }

    function body() {
      var today = dayOf(Date.now());
      var from = addDays(today, -(range - 1));
      // 세기 시작한 날보다 앞은 '0' 이 아니라 '모름' 이다 — 평균을 끌어내리지 않게 자른다.
      if (cache.since && cache.since > from) from = cache.since;
      var t = combine(cache.days, from, today);
      var aiTotal = Object.keys(t.ai).reduce(function (s, k) { return s + t.ai[k]; }, 0);
      var avg = Math.round((t.visitorDays / t.series.length) * 10) / 10;
      var seg = RANGES.map(function (n) {
        return '<button type="button" class="use-range' + (n === range ? " on" : "") +
          '" data-use-range="' + n + '" aria-pressed="' + (n === range) + '">' + n + "일</button>";
      }).join("");
      return '<div class="use-head"><h3>사용 통계</h3><div class="use-ranges">' + seg + "</div></div>" +
        '<div class="stat-cards">' +
          ctx.card(t.visits, "접속") + ctx.card(avg, "하루 평균 방문자") +
          ctx.card(t.searches, "검색") + ctx.card(aiTotal, "AI 단추") +
        "</div>" +
        '<div class="panel"><h3>날마다 접속</h3>' + columns(t.series) + "</div>" +
        '<div class="panel"><h3>자주 쓰는 메뉴</h3>' +
          bars(mapRows(t.views, VIEW_LABEL), VIEW_LABEL, "아직 누른 메뉴가 없어요.") +
          '<p class="use-note">첫 화면(주제별 지식)은 들어오면 바로 보이므로 메뉴를 누른 횟수만 셉니다.</p></div>' +
        '<div class="panel"><h3>AI 단추</h3>' +
          bars(mapRows(t.ai, AI_LABEL, true), AI_LABEL, "") + "</div>" +
        '<div class="panel"><h3>많이 찾은 검색어</h3>' +
          bars(t.terms, null, "아직 검색 기록이 없어요.") + "</div>" +
        '<p class="use-note">누가 무엇을 했는지는 남기지 않고 합계만 셉니다(하루 방문자 수만 사람 단위). ' +
          "오늘 것은 바로 반영되고, 지난 날은 밤 갱신 때 날짜별 합계로 접힙니다." +
          (cache.since ? " " + esc(cache.since) + "부터 셉니다." : "") + "</p>";
    }

    function paint() {
      var host = document.getElementById("admUsage");
      if (!host) return;
      if (!cache) { host.innerHTML = "<h3>사용 통계</h3><p class=\"use-empty\">불러오는 중…</p>"; return; }
      if (cache.error) {
        host.innerHTML = "<h3>사용 통계</h3><p class=\"use-empty\">불러오지 못했습니다: " +
          esc(cache.error) + "</p>";
        return;
      }
      host.innerHTML = body();
      Array.prototype.forEach.call(host.querySelectorAll("[data-use-range]"), function (b) {
        b.onclick = function () { range = Number(b.getAttribute("data-use-range")); paint(); };
      });
    }

    /** 관리자 탭을 그릴 때마다 부른다. 1분 안이면 다시 읽지 않는다. */
    function render() {
      var admin = state.session && state.session.admin;
      if (!admin || !admin.usage) return;
      if (cache && !cache.error && Date.now() - cache.loadedAt < 60 * 1000) { paint(); return; }
      cache = null;
      paint();
      var today = dayOf(Date.now());
      // 접히지 않은 원본은 가장 긴 보기(90일)만큼 거슬러 읽는다. 예전엔 14일뿐이라
      // PC 가 2주 넘게 꺼져 있던 동안의 날이 30·90일 보기에서 0 으로 나왔다(2026-11-11
      // 외부 평가 지적). 읽는 양은 늘지 않는다 — 접힌 날의 원본은 이미 지워져 있어,
      // 걸리는 것은 아직 안 접힌 날뿐이다.
      admin.usage(addDays(today, -(RANGES[RANGES.length - 1] - 1))).then(function (r) {
        var days = Object.assign({}, (r.summary && r.summary.days) || {});
        // 아직 접히지 않은 날(오늘, PC 가 꺼져 있던 날)은 원본에서 바로 합친다.
        var raw = {};
        (r.events || []).forEach(function (e) { (raw[e.day] = raw[e.day] || []).push(e); });
        Object.keys(raw).forEach(function (d) { if (!days[d]) days[d] = summarize(raw[d]); });
        var known = Object.keys(days).sort();
        cache = { days: days, since: known[0] || "", loadedAt: Date.now() };
        paint();
      }, function (e) {
        cache = { error: e && e.message ? e.message : String(e), loadedAt: Date.now() };
        paint();
      });
    }

    return { render: render };
  }
  api.Dashboard = Dashboard;

  if (typeof window !== "undefined") window.ArchiveUsage = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})();
