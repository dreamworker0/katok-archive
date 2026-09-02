/* ============ 사회복지 바이브코딩 아카이브 · 앱 로직 ============ */
(function () {
  "use strict";
  var A = window.ARCHIVE || {};
  var THREADS = A.threads || [];
  var MEDIA = A.media || [];
  var CATS = A.categories || [];
  var STATS = A.stats || {};
  var DIGESTS = A.digests || {};
  var KNOW = A.knowledge || { nodes: [], edges: [] };
  var TAGIDX = A.tag_index || { tags: [], total_tags: 0, hidden_tags: 0, min_count: 2 };
  var THREAD_BY_ID = {}; THREADS.forEach(function (t) { THREAD_BY_ID[t.id] = t; });
  /* 태그 → 그 태그가 붙은 주제. 표기 차이(공백·대소문자)는 무시하고 맞춘다.
   * 발행 때 이미 통일했지만, 요지 산문의 태그는 사람이 따로 쓴 말이라 '차량
   * 운행일지'처럼 띄어쓰기가 다를 수 있다. */
  var TAG_THREADS = {};
  /* 글자·마크다운 다루기는 web/text.js 로 옮겼다.
   *
   * 여기 이름을 다시 묶어 두는 이유: 이 파일 안에서 `esc(...)` 로 부르는 곳이
   * 200군데가 넘는다. 전부 `T.esc(...)` 로 바꾸면 diff 가 그것으로만 가득 차서
   * 무엇이 실제로 달라졌는지 보이지 않는다. */
  var T = window.ArchiveText;
  var tagFold = T.tagFold;
  var esc = T.esc;
  var linkify = T.linkify;
  var highlightText = T.highlightText;
  var hashHue = T.hashHue;
  var initial = T.initial;
  var fmtSize = T.fmtSize;
  var fmtDate = T.fmtDate;
  var mdInline = T.mdInline;
  var mdRow = T.mdRow;
  var hostOf = T.hostOf;
  var splitLinks = T.splitLinks;
  var linkifyHosts = T.linkifyHosts;
  var renderMarkdown = T.renderMarkdown;
  var msAgo = T.msAgo;
  var agoText = T.agoText;

  // 태그를 한 번에 몇 개까지 겹쳐 볼 수 있나. 넷 이상 겹치면 거의 0건이 된다.
  var TAG_PICK_MAX = 3;
  THREADS.forEach(function (t) {
    (t.tags || t.keywords || []).forEach(function (k) {
      var key = tagFold(k);
      if (!TAG_THREADS[key]) TAG_THREADS[key] = [];
      if (TAG_THREADS[key].indexOf(t.id) === -1) TAG_THREADS[key].push(t.id);
    });
  });
  var CAT_LABEL = {}; CATS.forEach(function (c) { CAT_LABEL[c.id] = c.label; });

  // 카테고리 색 (그래프 클러스터·요약·통계 공용)
  var CAT_COLORS = {
    projects: "#3b6fe0", "ai-tools": "#8b5cf6", "ai-models": "#ec4899",
    hwp: "#f59e0b", infra: "#14b8a6", "welfare-practice": "#22c55e",
    "news-articles": "#06b6d4", events: "#f97316", members: "#94a3b8",
    community: "#eab308", governance: "#ef4444", chat: "#64748b",
  };
  function colorFor(cid) { return CAT_COLORS[cid] || "#3b6fe0"; }

  var el = {
    app: document.getElementById("appRoot"),
    view: document.getElementById("view"),
    tabs: document.getElementById("tabs"),
    mobileNav: document.getElementById("mobileNav"),
    mobileMore: document.getElementById("mobileMore"),
    mobileMoreButton: document.getElementById("mobileMoreButton"),
    search: document.getElementById("searchInput"),
    filter: document.getElementById("participantFilter"),
    roomTitle: document.getElementById("roomTitle"),
    roomSub: document.getElementById("roomSub"),
    signOut: document.getElementById("signOutTop"),
    themeBtn: document.getElementById("themeBtn"),
    fontBtn: document.getElementById("fontBtn"),
    lightbox: document.getElementById("lightbox"),
    lightboxImg: document.getElementById("lightboxImg"),
    lightboxClose: document.getElementById("lightboxClose"),
    confirmDialog: document.getElementById("confirmDialog"),
    confirmTitle: document.getElementById("confirmTitle"),
    confirmDesc: document.getElementById("confirmDesc"),
    confirmSubmit: document.getElementById("confirmSubmit"),
  };
  var state = { view: "summary", q: "", nick: "", graph: null, session: null,
                // 요지 화면에서 골라 온 주제(주소의 ?cat=)
                cat: "",
                mine: null, admin: null, gview: "grid", tsort: "desc", pick: null,
                // 태그 화면에서 고른 태그(최대 TAG_PICK_MAX 개)
                tagPick: [],
                // 갱신 상태와 그 구독 해제 함수 (관리자 전용)
                refresh: null, refreshUnsub: null,
                // 매일 밤 스케줄러가 돈 결과 (settings/lastRun)
                lastRun: null, lastRunUnsub: null };
  try {
    var savedG = localStorage.getItem("gallery-view");
    if (savedG === "list" || savedG === "grid") state.gview = savedG;
    var savedS = localStorage.getItem("thread-sort");
    if (savedS === "asc" || savedS === "desc") state.tsort = savedS;
  } catch (e) { /* 프라이빗 모드 등 — 기본값으로 간다 */ }

  function avatarStyle(n) { return "background:hsl(" + hashHue(n) + ",42%,50%)"; }

  function emptyState(kind, title, body, actionHtml) {
    var art = kind === "search" ? "state-search.webp" : "state-empty.webp";
    return '<section class="empty-state empty-state--' + esc(kind) + '">' +
      '<img class="empty-state__art" src="art/' + art +
      '" alt="" width="480" height="480" loading="lazy" />' +
      '<div class="empty-state__copy"><h2>' + esc(title) + "</h2>" +
      '<p>' + esc(body) + "</p>" +
      (actionHtml ? '<div class="empty-state__actions">' + actionHtml + "</div>" : "") +
      "</div></section>";
  }

  function confirmAction(options, onConfirm) {
    var dialog = el.confirmDialog;
    if (!dialog) return;
    var opener = document.activeElement;
    el.confirmTitle.textContent = options.title || "계속할까요?";
    el.confirmDesc.textContent = options.description || "";
    el.confirmSubmit.textContent = options.confirmLabel || "계속하기";
    el.confirmSubmit.classList.toggle("danger", options.tone !== "neutral");
    dialog.returnValue = "";
    dialog.onclose = function () {
      dialog.onclose = null;
      if (dialog.returnValue === "confirm") onConfirm();
      else if (opener && opener.focus) opener.focus();
    };
    dialog.showModal();
    el.confirmSubmit.focus();
  }

  // ---------- 주제별 지식 → web/summary.js ----------
  var SUMMARY = window.ArchiveSummary({
    data: appData, state: state, el: el, esc: esc, colorFor: colorFor, emptyState: emptyState,
    tagFold: tagFold, jumpToTimeline: jumpToTimeline, pickThreads: pickThreads,
    runSearch: runSearch, setView: setView, writeHash: writeHash,
    stats: function () { return STATSV; },
  });
  function renderSummary() { return SUMMARY.renderSummary(); }
  function bindKeywordChips(scope) { return SUMMARY.bindKeywordChips(scope); }


  // ---------- 관계망 → web/graph-view.js ----------
  var GRAPHV = window.ArchiveGraphView({
    data: appData, state: state, el: el, esc: esc, colorFor: colorFor,
    runSearch: runSearch, setView: setView, render: render,
    stats: function () { return STATSV; },
  });
  function renderGraph() { return GRAPHV.renderGraph(); }


  // ---------- 타임라인(주제 카드) → web/timeline.js ----------
  var TIMELINE = window.ArchiveTimeline({
    data: appData, state: state, el: el, esc: esc, colorFor: colorFor, emptyState: emptyState,
    confirmAction: confirmAction, fmtDate: fmtDate, highlightText: highlightText, hostOf: hostOf,
    linkifyHosts: linkifyHosts, renderMarkdown: renderMarkdown, splitLinks: splitLinks,
    bindFiles: bindFiles, bindImages: bindImages, bindKeywordChips: bindKeywordChips,
    fileIcon: fileIcon, isAdmin: isAdmin, render: render, setView: setView,
    stats: function () { return STATSV; },
  });
  function renderTimeline() { return TIMELINE.renderTimeline(); }
  function threadMatches(t) { return TIMELINE.threadMatches(t); }
  function pickThreads() { return TIMELINE.pickThreads.apply(null, arguments); }
  function jumpToTimeline(id) { return TIMELINE.jumpToTimeline(id); }
  function attachAiReports(items) { return TIMELINE.attachAiReports(items); }

  /** boot.js 가 요지를 받아 오면 부른다. 요지 화면을 보고 있었으면 다시 그린다. */
  function attachDigests(d) {
    DIGESTS = d || {};
    A.digests = DIGESTS;
    state.digestsPending = false;
    if (state.view === "summary") render();
  }


  // ---------- 태그 입구 → web/tags.js ----------
  var TAGSV = window.ArchiveTags({
    data: appData, state: state, el: el, esc: esc, emptyState: emptyState, tagFold: tagFold,
    pickThreads: pickThreads, writeHash: writeHash, TAG_PICK_MAX: TAG_PICK_MAX,
    stats: function () { return STATSV; },
  });
  function renderTags() { return TAGSV.renderTags(); }


  // ---------- 갤러리·자료·라이트박스 → web/gallery.js ----------
  var GALLERY = window.ArchiveGallery({
    data: appData, state: state, el: el, esc: esc, emptyState: emptyState, fmtSize: fmtSize,
    jumpToTimeline: jumpToTimeline, stats: function () { return STATSV; },
  });
  function renderGallery() { return GALLERY.renderGallery(); }
  function renderFiles() { return GALLERY.renderFiles(); }
  function fileIcon(name) { return GALLERY.fileIcon(name); }
  function bindFiles(scope) { return GALLERY.bindFiles(scope); }
  function bindImages(scope) { return GALLERY.bindImages(scope); }
  function openLightbox() { return GALLERY.openLightbox.apply(null, arguments); }
  function closeLightbox() { return GALLERY.closeLightbox(); }


  // ---------- 통계 → web/stats.js ----------
  // 데이터 전역은 init() 에서 다시 읽히므로 값이 아니라 읽는 함수를 준다.
  function appData() {
    return { A: A, THREADS: THREADS, MEDIA: MEDIA, CATS: CATS, STATS: STATS, DIGESTS: DIGESTS,
             KNOW: KNOW, TAGIDX: TAGIDX, THREAD_BY_ID: THREAD_BY_ID, TAG_THREADS: TAG_THREADS,
             CAT_LABEL: CAT_LABEL };
  }
  var STATSV = window.ArchiveStats({
    data: appData, state: state, el: el, esc: esc, colorFor: colorFor,
    avatarStyle: avatarStyle, initial: initial, setView: setView,
    mine: function () { return MINEV; },
  });
  function bar() { return STATSV.bar.apply(null, arguments); }
  function card() { return STATSV.card.apply(null, arguments); }
  function mentions(text, words) { return STATSV.mentions(text, words); }
  function myTraitReport() { return STATSV.myTraitReport.apply(null, arguments); }
  function renderStats() { return STATSV.renderStats(); }


  // ---------- 내 글 관리 → web/mine.js ----------
  var MINEV = window.ArchiveMine({
    data: appData, state: state, el: el, esc: esc, agoText: agoText, msAgo: msAgo,
    fmtSize: fmtSize, confirmAction: confirmAction, bindFiles: bindFiles, bindImages: bindImages,
    fileIcon: fileIcon, openLightbox: openLightbox, stats: function () { return STATSV; },
  });
  function canManageMine() { return MINEV.canManageMine(); }
  function mineKind() { return MINEV.mineKind.apply(null, arguments); }
  function myNicknames() { return MINEV.myNicknames(); }
  function renderMine() { return MINEV.renderMine(); }


  // ---------- 관리자 화면 → web/admin.js ----------
  // 관리자만 쓰는 560줄을 떼어냈다. 공유하는 것은 아래 일곱 가지뿐이라 그것만 넘긴다.
  // STATS 는 init() 에서 다시 읽히므로 값이 아니라 읽는 함수를 준다(파일 위쪽 주석 참고).
  var ADMIN = window.ArchiveAdmin({
    state: state, el: el, esc: esc, confirmAction: confirmAction, card: card,
    agoText: agoText, msAgo: msAgo, stats: function () { return STATS; },
  });
  function isAdmin() { return ADMIN.isAdmin(); }
  function renderAdmin() { return ADMIN.renderAdmin(); }


  // ---------- 검색·라우팅 ----------
  function runSearch(q) {
    state.q = q || ""; el.search.value = state.q;
    setView("timeline");
  }

  function setNavigationState(view) {
    Array.prototype.forEach.call(document.querySelectorAll("[data-view]"), function (control) {
      var active = control.getAttribute("data-view") === view;
      control.classList.toggle("active", active);
      if (active) control.setAttribute("aria-current", "page");
      else control.removeAttribute("aria-current");
    });
  }

  function setMobileMore(open) {
    if (!el.mobileMore || !el.mobileMoreButton) return;
    el.mobileMore.hidden = !open;
    el.mobileMoreButton.setAttribute("aria-expanded", open ? "true" : "false");
  }

  function trapFocus(container, event) {
    var controls = container.querySelectorAll(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled])'
    );
    if (!controls.length) return;
    var first = controls[0], last = controls[controls.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault(); last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault(); first.focus();
    }
  }

  function currentTheme() {
    var cur = document.documentElement.getAttribute("data-theme");
    if (cur) return cur;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark" : "light";
  }

  function themeIcon(mode) {
    if (mode === "dark") {
      return '<svg data-theme-icon="moon" aria-hidden="true" viewBox="0 0 24 24" ' +
        'fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" ' +
        'stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 ' +
        '7 7 0 0 0 21 12.79z"></path></svg>';
    }
    return '<svg data-theme-icon="sun" aria-hidden="true" viewBox="0 0 24 24" ' +
      'fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" ' +
      'stroke-linejoin="round"><circle cx="12" cy="12" r="4"></circle>' +
      '<path d="M12 2v2M12 20v2M4.93 4.93l1.42 1.42M17.66 17.66l1.41 1.41' +
      'M2 12h2M20 12h2M4.93 19.07l1.42-1.42M17.66 6.34l1.41-1.41"></path></svg>';
  }

  function updateThemeControls() {
    var next = currentTheme() === "dark" ? "light" : "dark";
    var label = next === "light" ? "라이트 모드로 전환" : "다크 모드로 전환";
    if (el.themeBtn) {
      el.themeBtn.innerHTML = themeIcon(next);
      el.themeBtn.setAttribute("aria-label", label);
      el.themeBtn.setAttribute("title", label);
    }
    var mobileTheme = document.querySelector('[data-mobile-action="theme"]');
    if (mobileTheme) {
      // 모바일 '더보기'는 라벨이 붙은 전체폭 행들의 목록이다. 거기에 아이콘만 있는
      // 작은 버튼을 끼우면 다른 물건처럼 보이고, 무엇인지 눌러봐야 안다.
      mobileTheme.innerHTML = mobileRow("다크 모드",
        currentTheme() === "dark" ? "켜짐" : "꺼짐");
      mobileTheme.setAttribute("aria-label", label);
      mobileTheme.setAttribute("title", label);
    }
  }

  /** 모바일 '더보기' 한 줄: 왼쪽에 이름, 오른쪽에 지금 값. 다른 항목과 같은
   *  전체폭 행이라 목록에서 튀지 않고, 열어보지 않아도 상태를 읽을 수 있다. */
  function mobileRow(name, value) {
    return '<span class="mm-label">' + esc(name) + "</span>" +
      '<span class="mm-value">' + esc(value) + "</span>";
  }

  function toggleTheme() {
    var next = currentTheme() === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("kakao-archive-theme", next); } catch (e) {}
    updateThemeControls();
  }

  /* ---------- 글자 크기 ----------
   *  읽는 사람 중에 작은 글씨가 힘든 분이 있다. 테마 토글과 같은 자리·같은 조작
   *  (누를 때마다 다음 단계)으로 두어 따로 배우지 않아도 되게 한다.
   *
   *  키우는 대상은 본문(보고서·주제 요약)뿐이다. 사이드바·버튼·통계까지 같이
   *  커지면 화면이 무너지고, 정작 읽을 자리는 좁아진다. 배율은 styles.css 의
   *  --reading-scale 이 맡는다.
   *
   *  `to` 를 label 과 따로 둔 이유: 라벨을 label 로 만들면 받침에 따라 조사가
   *  어긋난다("보통" + "로"). 갈 곳의 표기를 아예 적어 둔다. */
  var FONT_STEPS = [
    { id: "normal", label: "보통", to: "보통으로" },
    { id: "large", label: "크게", to: "크게로" },
    { id: "xlarge", label: "아주 크게", to: "아주 크게로" }
  ];

  function currentFontIndex() {
    var cur = document.documentElement.getAttribute("data-font");
    for (var i = 0; i < FONT_STEPS.length; i += 1) {
      if (FONT_STEPS[i].id === cur) return i;
    }
    return 0;
  }

  function updateFontControls() {
    var next = FONT_STEPS[(currentFontIndex() + 1) % FONT_STEPS.length];
    var now = FONT_STEPS[currentFontIndex()];
    // 테마 토글처럼 "누르면 어디로 가는지"를 알린다. 지금 크기도 같이 읽어 준다.
    var label = "글자 크기 " + next.to + " 전환 (지금 " + now.label + ")";
    // 사이드바는 40px 아이콘 자리라 '가' 를 다음 단계 크기로 보여 준다.
    // 모바일 '더보기'는 라벨 목록이라 같은 모양의 전체폭 행으로 준다.
    var mobileFont = document.querySelector('[data-mobile-action="font"]');
    [[el.fontBtn, '<span class="font-toggle__mark" aria-hidden="true">가</span>'],
     [mobileFont, mobileRow("글자 크기", now.label)]].forEach(function (pair) {
      var btn = pair[0];
      if (!btn) return;
      btn.innerHTML = pair[1];
      btn.setAttribute("data-font-next", next.id);
      btn.setAttribute("aria-label", label);
      btn.setAttribute("title", label);
    });
  }

  function applyFont(id) {
    document.documentElement.setAttribute("data-font", id);
    updateFontControls();
  }

  function cycleFont() {
    var next = FONT_STEPS[(currentFontIndex() + 1) % FONT_STEPS.length];
    applyFont(next.id);
    try { localStorage.setItem("kakao-archive-font", next.id); } catch (e) {}
  }

  function removeViewControls(view) {
    Array.prototype.forEach.call(
      document.querySelectorAll('[data-view="' + view + '"]'),
      function (control) { control.remove(); }
    );
  }

  function renderMobileMore() {
    if (!el.mobileMore) return;
    var html = [
      '<button type="button" data-view="graph">관계망</button>',
      '<button type="button" data-view="tags">태그</button>',
      '<button type="button" data-view="files">첨부파일</button>',
      '<button type="button" data-view="stats">통계</button>',
    ];
    if (isAdmin()) html.push('<button type="button" data-view="admin">관리자</button>');
    // 다른 항목과 같은 전체폭 행으로 둔다. 순서는 사이드바와 같다(글자 크기 다음 테마).
    html.push('<button type="button" data-mobile-action="font"></button>');
    html.push('<button type="button" data-mobile-action="theme"></button>');
    if (state.session) html.push('<button type="button" data-mobile-action="signout">로그아웃</button>');
    el.mobileMore.innerHTML = html.join("");
    updateFontControls();
    updateThemeControls();
  }

  /* ---------- 주소(URL) 라우팅 ----------
   *
   * 화면 상태가 주소에 없으면 F5 를 누르거나 뒤로 가기를 눌렀을 때 첫 화면으로
   * 돌아간다. 읽던 자리를 잃는 것은 물론이고, 남에게 "여기 봐"라고 링크를 줄
   * 수도 없다. 그래서 보고 있는 것을 주소에 적는다.
   *
   *   /tags?t=clasp,앱스스크립트     태그 두 개를 골라 둔 태그 화면
   *   /timeline?q=파이어베이스        검색 결과
   *   /timeline?nick=김종원           참여자로 좁힌 목록
   *
   * 처음에는 `#/tags` 처럼 해시로 했다. 정적 호스팅이라 `/tags` 로 새로고침하면
   * 서버가 그런 파일을 찾다가 404 를 내기 때문이다. 지금은 호스팅 규칙(rewrites)이
   * 없는 경로를 index.html 로 되돌리므로 `#` 이 필요 없다 — 사람에게 건네는
   * 링크이니 읽히는 편이 낫다. 옛 `#/...` 링크는 아래에서 새 주소로 넘겨준다.
   * (로컬 미리보기도 같게: scripts/serve_hosting.py 가 같은 되돌리기를 한다.)
   *
   * 추림(pick)은 주소에 담지 않는다 — 주제 ID 수십 개가 주소에 들어가고, 발행본이
   * 바뀌면 그 링크가 엉뚱한 것을 가리킨다. 태그로 고른 것은 태그 이름으로 담는다.
   */
  var routing = false;   // 주소를 우리가 바꿀 때 되읽기를 막는 표식

  function stateToPath() {
    var q = [];
    if (state.view === "tags" && (state.tagPick || []).length) {
      // 태그마다 따로 인코딩한다. 통째로 하면 쉼표가 %2C 로 변해 주소가 읽기
      // 어려워진다 — 사람에게 건네는 링크이므로 눈으로 읽히는 편이 낫다.
      q.push("t=" + state.tagPick.map(encodeURIComponent).join(","));
    }
    // 요지 화면은 주제별로 건넬 주소가 있어야 한다 — "프로젝트·결과물 부분 봐"
    // 라고 말하려면 링크가 있어야지, 들어가서 찾아 내려가라고 할 수는 없다.
    if (state.view === "summary" && state.cat) {
      q.push("cat=" + encodeURIComponent(state.cat));
    }
    if (state.q) q.push("q=" + encodeURIComponent(state.q));
    if (state.nick) q.push("nick=" + encodeURIComponent(state.nick));
    return "/" + state.view + (q.length ? "?" + q.join("&") : "");
  }

  function writeHash(replace) {
    var next = stateToPath();
    if (location.pathname + location.search === next) return;
    routing = true;
    try {
      if (replace && history.replaceState) history.replaceState(null, "", next);
      else if (history.pushState) history.pushState(null, "", next);
    } catch (e) { /* 주소를 못 바꿔도 화면은 돌아간다 */ }
    setTimeout(function () { routing = false; }, 0);
  }

  function parseQuery(search, out) {
    (search || "").replace(/^\?/, "").split("&").forEach(function (pair) {
      if (!pair) return;
      var eq = pair.indexOf("=");
      var k = decodeURIComponent(eq < 0 ? pair : pair.slice(0, eq));
      var v = eq < 0 ? "" : decodeURIComponent(pair.slice(eq + 1).replace(/\+/g, " "));
      if (k === "q") out.q = v;
      else if (k === "cat") out.cat = v;
      else if (k === "nick") out.nick = v;
      else if (k === "t") out.tags = v.split(",").filter(Boolean);
    });
    return out;
  }

  function parseHash() {
    var out = { view: "", q: "", nick: "", cat: "", tags: [] };
    // 옛 링크: #/tags?t=... — 새 주소로 넘겨준다(아래 applyHash 가 replaceState).
    var hash = (location.hash || "").replace(/^#\/?/, "");
    if (hash) {
      var hp = hash.split("?");
      out.view = decodeURIComponent(hp[0] || "").split("/")[0];
      out.legacy = true;
      return parseQuery(hp[1] || "", out);
    }
    var seg = (location.pathname || "/").split("/").filter(Boolean);
    if (!seg.length) return null;
    out.view = decodeURIComponent(seg[0]);
    return parseQuery(location.search, out);
  }

  /** 주소에 적힌 것을 화면에 적용한다. 아는 화면이 아니면 무시한다. */
  function applyHash() {
    var r = parseHash();
    if (!r || !r.view) return false;
    // 없는 탭(예: 로그인 안 한 사람의 '내 글 관리')으로 보내지 않는다.
    if (!document.querySelector('[data-view="' + r.view + '"]')) return false;
    state.view = r.view;
    state.q = r.q; state.nick = r.nick;
    state.cat = r.cat || "";
    state.pick = null;
    state.tagPick = r.tags.slice(0, TAG_PICK_MAX);
    if (el.search) el.search.value = state.q;
    if (el.filter) el.filter.value = state.nick;
    setNavigationState(state.view);
    render();
    // 옛 해시 링크로 들어왔으면 새 주소로 바꿔 둔다 — 다음 새로고침·공유부터
    // 깔끔한 주소가 되고, 히스토리에 옛 주소를 남기지 않는다.
    if (r.legacy) writeHash(true);
    return true;
  }

  function setView(v) {
    if (state.graph && v !== "graph") { state.graph.destroy(); state.graph = null; }
    // 관리 화면을 떠나면 갱신 상태 구독을 끊는다. 안 끊으면 다른 탭을 보는 동안에도
    // 리스너가 살아 있고, 관리 화면에 다시 들어올 때마다 하나씩 더 붙는다.
    if (v !== "admin") ADMIN.unwatchRefresh();
    if (v !== "summary") state.cat = "";
    state.view = v;
    setNavigationState(v);
    setMobileMore(false);
    writeHash();
    render();
  }
  function render() {
    if (state.view === "summary") renderSummary();
    else if (state.view === "graph") renderGraph();
    else if (state.view === "timeline") renderTimeline();
    else if (state.view === "tags") renderTags();
    else if (state.view === "gallery") renderGallery();
    else if (state.view === "files") renderFiles();
    else if (state.view === "stats") renderStats();
    else if (state.view === "mine") renderMine();
    else if (state.view === "admin") renderAdmin();
  }

  // 로그인한 사용자 표시 + 로그아웃 (보호모드에서만 세션이 주어진다)
  function renderSession() {
    var host = document.getElementById("sessionBox");
    if (!host) return;
    var s = state.session;
    if (!s) {
      host.innerHTML = "";
      if (el.signOut) {
        el.signOut.hidden = true;
        el.signOut.onclick = null;
      }
      return;
    }
    host.innerHTML =
      '<span class="sidebar-avatar" style="' + avatarStyle(s.user.name) +
      '" aria-hidden="true">' + esc(initial(s.user.name)) + "</span>" +
      '<span class="sidebar-identity"><strong class="sidebar-name" title="' +
      esc(s.user.email) + '">' + esc(s.user.name) + "</strong>" +
      '<span class="sidebar-role">' + (s.role === "admin" ? "관리자" : "멤버") +
      "</span></span>";
    if (el.signOut) {
      el.signOut.hidden = false;
      el.signOut.onclick = function () { s.signOut(); };
    }
  }

  // ---------- 초기화 ----------
  function init(session) {
    // boot.js 가 Firestore 로드를 끝낸 뒤 호출하므로 여기서 다시 읽는다
    A = window.ARCHIVE || {};
    THREADS = A.threads || [];
    MEDIA = A.media || [];
    CATS = A.categories || [];
    STATS = A.stats || {};
    DIGESTS = A.digests || {};
    // 보호모드에서는 요지가 화면 뒤에 온다(A.lazy). 로컬 미리보기(data.js)에는 다 있다.
    state.digestsPending = !!(A.lazy && A.lazy.digests);
    KNOW = A.knowledge || { nodes: [], edges: [] };
    TAGIDX = A.tag_index || { tags: [], total_tags: 0, hidden_tags: 0, min_count: 2 };
    // 파일 위쪽에서 만든 것은 보호모드에서 늘 비어 있다(그때는 ARCHIVE 가 없다).
    // 여기서 다시 만들지 않으면 태그 화면이 영원히 "아직 모인 태그가 없어요" 다.
    THREAD_BY_ID = {}; TAG_THREADS = {};
    THREADS.forEach(function (t) {
      THREAD_BY_ID[t.id] = t;
      (t.tags || t.keywords || []).forEach(function (k) {
        var key = tagFold(k);
        if (!TAG_THREADS[key]) TAG_THREADS[key] = [];
        if (TAG_THREADS[key].indexOf(t.id) === -1) TAG_THREADS[key].push(t.id);
      });
    });
    CAT_LABEL = {}; CATS.forEach(function (c) { CAT_LABEL[c.id] = c.label; });

    state.session = session || null;
    renderSession();

    // '내 글 관리' 는 표시명이 연결된 로그인 사용자에게만 의미가 있다.
    // 로컬 미리보기(site/)에는 세션이 없으므로 탭 자체를 감춘다.
    if (!canManageMine()) removeViewControls("mine");
    if (!isAdmin()) removeViewControls("admin");
    renderMobileMore();
    el.roomTitle.textContent = A.chat_room || "아카이브";
    var t = STATS.totals || {};
    el.roomSub.innerHTML =
      '<span class="room-sub__counts">' + esc(t.messages || 0) + "개 메시지 · " +
      esc(t.participants || 0) + "명</span>" +
      '<span class="room-sub__dates">' + esc(t.date_start || "") + " ~ " +
      esc(t.date_end || "") + "</span>";
    (STATS.participants || []).forEach(function (p) {
      var o = document.createElement("option");
      o.value = p.nickname; o.textContent = p.nickname + " (" + p.message_count + ")";
      el.filter.appendChild(o);
    });

    el.app.addEventListener("click", function (e) {
      var viewControl = e.target.closest("[data-view]");
      if (viewControl) {
        setView(viewControl.getAttribute("data-view"));
        return;
      }
      if (e.target.closest("#mobileMoreButton")) {
        setMobileMore(el.mobileMore.hidden);
        return;
      }
      var action = e.target.closest("[data-mobile-action]");
      if (action) {
        var kind = action.getAttribute("data-mobile-action");
        if (kind === "theme") toggleTheme();
        else if (kind === "font") cycleFont();
        else if (kind === "signout" && state.session) {
          state.session.signOut();
        }
        // 글자 크기는 결과를 바로 보고 더 키울지 정하게 열어 둔다.
        if (kind !== "font") setMobileMore(false);
        return;
      }
      if (!el.mobileMore.hidden && !e.target.closest("#mobileMore")) setMobileMore(false);
    });
    var timer;
    el.search.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(function () {
        state.q = el.search.value.trim();
        // 결과물로 추려 둔 상태에서 검색하면 결과가 없어 당황한다. 검색은
        // 전체에서 하는 게 자연스러우므로 추림을 푼다.
        if (state.q) state.pick = null;
        if (state.view === "graph" && state.graph) { state.graph.search(state.q); return; }
        // 검색어는 주소에 남긴다 — 새로고침해도 결과가 유지되고 링크로 줄 수 있다.
        // 글자를 칠 때마다 히스토리를 쌓으면 뒤로 가기가 한 글자씩 되돌아가므로
        // 같은 화면 안에서는 주소만 바꿔치기한다(replace).
        if (state.view === "files") { writeHash(true); render(); return; }
        if (state.view !== "timeline") setView("timeline");
        else { writeHash(true); render(); }
      }, 180);
    });
    el.filter.addEventListener("change", function () {
      state.nick = el.filter.value;
      if (state.nick) state.pick = null;
      if (state.view === "graph") setView("timeline");
      else { writeHash(); render(); }
    });
    el.lightbox.addEventListener("click", function (e) {
      if (e.target === el.lightbox || e.target === el.lightboxClose) closeLightbox();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        closeLightbox();
        if (!el.mobileMore.hidden) {
          setMobileMore(false);
          el.mobileMoreButton.focus();
        }
      } else if (e.key === "Tab" && !el.mobileMore.hidden) {
        trapFocus(el.mobileMore, e);
      }
    });

    var saved = null; try { saved = localStorage.getItem("kakao-archive-theme"); } catch (e) {}
    if (saved) document.documentElement.setAttribute("data-theme", saved);
    updateThemeControls();
    el.themeBtn.addEventListener("click", toggleTheme);

    var savedFont = null;
    try { savedFont = localStorage.getItem("kakao-archive-font"); } catch (e) {}
    // 저장된 값이 아는 단계일 때만 쓴다 — 예전 값이 남아 있어도 화면이 깨지지 않는다.
    applyFont(FONT_STEPS.some(function (s) { return s.id === savedFont; })
      ? savedFont : FONT_STEPS[0].id);
    if (el.fontBtn) el.fontBtn.addEventListener("click", cycleFont);

    /* 뒤로 가기·앞으로 가기. hashchange 와 popstate 를 모두 듣는다 — pushState 로
     * 바꾼 주소는 브라우저에 따라 popstate 만 오는 경우가 있다. 우리가 주소를
     * 바꾼 직후에는 `routing` 표식으로 되읽기를 건너뛴다(같은 화면을 두 번 그리지
     * 않게). */
    function onRouteChange() { if (!routing) applyHash(); }
    window.addEventListener("hashchange", onRouteChange);
    window.addEventListener("popstate", onRouteChange);

    setNavigationState(state.view);
    // 주소에 화면이 적혀 있으면 그리로 간다(F5·공유 링크). 없으면 첫 화면을 그리고
    // 주소에 적어 둔다 — 그래야 뒤로 가기가 아카이브 안에서 돈다.
    if (!applyHash()) {
      render();
      writeHash(true);
    }
  }

  // 보호모드(hosting)에서는 boot.js 가 로그인·데이터 로드를 끝낸 뒤 start() 를 부른다.
  // 로컬 미리보기(site/)에서는 data.js 가 이미 window.ARCHIVE 를 채워두므로 바로 시작.
  window.ArchiveApp = { start: init, attachDigests: attachDigests, attachAiReports: attachAiReports };
  // 원문(messages)은 더 이상 싣지 않는다. 스레드 요약이 있으면 데이터가 준비된 것이다.
  if (window.ARCHIVE && window.ARCHIVE.threads) init(null);
})();
