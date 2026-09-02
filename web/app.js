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

  // ---------- 주제별 지식(요약) ----------
  function renderSummary() {
    var totals = STATS.totals || {};
    // 요지는 화면이 뜬 뒤에 온다(boot.js loadRest). 오기 전에 이 화면에 들어서면
    // 비어 있다고 말하지 않고 기다린다 — attachDigests 가 오면 다시 그린다.
    if (state.digestsPending) {
      el.view.innerHTML = emptyState("archive", "요지를 불러오는 중…",
        "주제별 요지 산문을 받고 있습니다. 잠시만 기다려 주세요.");
      return;
    }
    var html = [
      '<section class="archive-welcome">' +
      '<div class="archive-welcome__copy">' +
      '<p class="eyebrow">우리의 아카이브</p>' +
      '<h1>함께 나눈 이야기를<br>천천히 다시 만나요</h1>' +
      '<p>' + esc(totals.messages || 0) + "개의 기록과 " +
      esc(totals.participants || 0) + "명의 이야기를 주제별로 모았습니다.</p>" +
      '</div><img class="archive-welcome__art" src="art/archive-hero.webp" ' +
      'alt="" width="1280" height="800" /></section>',
      '<div class="cat-nav">',
    ];
    var digestCount = 0;
    CATS.forEach(function (c) {
      var d = DIGESTS[c.id]; if (!d) return;
      digestCount++;
      html.push('<a class="cat-nav-item" href="/summary?cat=' + encodeURIComponent(c.id) +
        '" data-goto="doc-' + c.id + '" data-cat="' + esc(c.id) + '">' +
        '<span class="swatch" style="background:' + colorFor(c.id) + '"></span>' +
        esc(c.label) + " · " + (d.message_count || 0) + "</a>");
    });
    html.push("</div>");
    if (!digestCount) {
      html.push(emptyState("archive", "아직 모인 기록이 없어요",
        "새로운 이야기가 정리되면 이곳에서 가장 먼저 만날 수 있습니다."));
    }
    CATS.forEach(function (c) {
      var d = DIGESTS[c.id]; if (!d) return;
      html.push(renderDoc(c.id, d));
    });
    el.view.innerHTML = html.join("");
    Array.prototype.forEach.call(el.view.querySelectorAll("[data-goto]"), function (b) {
      b.onclick = function (ev) {
        // 새 탭·다른 창으로 여는 몸짓은 가로채지 않는다 — 링크로 둔 뜻이 없어진다.
        if (ev && (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.button === 1)) return;
        if (ev && ev.preventDefault) ev.preventDefault();
        var t = document.getElementById(b.getAttribute("data-goto"));
        if (!t) return;
        state.cat = b.getAttribute("data-cat") || "";
        writeHash();
        // 모바일에서는 카드가 접혀 있다. 찾아간 주제를 닫힌 채로 두면 "눌렀는데
        // 아무것도 없네"가 된다 — 골라서 온 것이니 열어 준다.
        setDocOpen(t, true);
        t.scrollIntoView({ behavior: "smooth", block: "start" });
      };
    });
    // 주제 제목 링크 — 위쪽 단추와 같은 일을 한다.
    Array.prototype.forEach.call(el.view.querySelectorAll(".doc-link"), function (a) {
      a.onclick = function (ev) {
        if (ev && (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.button === 1)) return;
        if (ev && ev.preventDefault) ev.preventDefault();
        var cid = a.getAttribute("data-cat");
        state.cat = cid;
        writeHash();
        var t = document.getElementById("doc-" + cid);
        if (!t) return;
        setDocOpen(t, true);
        t.scrollIntoView({ behavior: "smooth", block: "start" });
      };
    });
    // 주소에 cat 이 실려 들어온 경우 — 그 주제를 펴고 그 자리로 데려간다.
    if (state.cat) {
      var target = document.getElementById("doc-" + state.cat);
      if (target) {
        setDocOpen(target, true);
        target.scrollIntoView({ block: "start" });
      }
    }
    bindDocActions(el.view);
  }

  function renderDoc(cid, d) {
    var col = colorFor(cid);
    var apps = (d.apps || []).map(function (a) {
      /* 다룬 주제와 스친 언급을 나눠 적는다. 누르면 다룬 주제만 보여주고, 스친
       * 언급은 목록 위 안내줄에서 한 번 더 눌러야 나온다(소음을 접는다). */
      var subject = a.subject_ids || a.thread_ids || [];
      var all = a.thread_ids || [];
      var mentions = Math.max(0, all.length - subject.length);
      var bits = [];
      if (subject.length) bits.push("주제 " + subject.length);
      if (mentions) bits.push("언급 " + mentions);
      return '<button class="app-item" data-pick="' +
        esc((subject.length ? subject : all).join(",")) + '" data-pick-all="' +
        esc(all.join(",")) + '" data-kind="' +
        // 다룬 주제를 못 가린 결과물은 '언급'이라고 정직하게 말한다. 언급 목록을
        // '다룬 주제'라고 적으면 안내문이 거짓말이 된다.
        (subject.length ? "subject" : "mention") +
        '" data-label="' + esc(a.label) + '" data-q="' +
        esc(a.query || a.label) + '">' +
        '<span class="an">' + esc(a.label) + "</span>" +
        (a.maker ? '<span class="am">' + esc(a.maker) + "</span>" : "") +
        (bits.length ? '<span class="an-n">' + bits.join(" · ") + "</span>" : "") +
        "</button>";
    }).join("");
    var links = (d.links || []);
    var linkTop = links.slice(0, 3), linkRest = links.slice(3);
    function lk(l) {
      return '<a href="' + esc(l.url) + '" target="_blank" rel="noopener noreferrer">' + esc(l.url) +
        '</a><span class="lk-meta">' + esc(l.nickname) + " · " + esc(l.date) + "</span>";
    }
    var linkHtml = linkTop.map(function (l) { return "<div>" + lk(l) + "</div>"; }).join("");
    if (linkRest.length) {
      linkHtml += '<details class="more-fold"><summary>공유 링크 ' + linkRest.length + "개 더</summary>" +
        linkRest.map(function (l) { return "<div>" + lk(l) + "</div>"; }).join("") + "</details>";
    }
    var people = (d.participants || []).map(function (p) {
      return '<button class="chip" data-nick="' + esc(p.nickname) + '">' + esc(p.nickname) +
        " <span style=\"color:var(--ink-faint)\">" + p.count + "</span></button>";
    }).join("");
    // 요지의 태그도 누르면 그 화제의 주제만 보이게 한다. 장식으로 두면 눌러
    // 보고 아무 일도 안 일어나는데, 태그처럼 생긴 것은 누르게 되어 있다.
    var kw = (d.keywords || []).map(function (k) {
      return '<button class="chip kw" data-kw="' + esc(k) + '" ' +
        'title="이 태그가 붙은 주제만 보기">' + esc(k) + "</button>";
    }).join("");
    // 최근 대화가 위로 오도록 끝난 날짜 기준 내림차순. 날짜는 YYYY-MM-DD라 문자열 비교로 충분하다.
    var threadList = (d.threads || []).slice().sort(function (a, b) {
      return String(b.end_date || "").localeCompare(String(a.end_date || "")) ||
        String(b.start_date || "").localeCompare(String(a.start_date || ""));
    });
    function tl(t) {
      var range = t.start_date === t.end_date ? t.start_date : t.start_date + " ~ " + t.end_date;
      return '<div class="thread-line" data-start="t-' + esc(t.id) + '"><b>' + esc(t.title) +
        '</b><span class="tl-date">' + esc(range) + '</span><span class="tl-n">💬 ' + t.count + "</span></div>";
    }
    var threadTop = threadList.slice(0, 10), threadRest = threadList.slice(10);
    var threads = threadTop.map(tl).join("");
    if (threadRest.length) {
      threads += '<details class="more-fold"><summary>대화 주제 ' + threadRest.length + "개 더</summary>" +
        threadRest.map(tl).join("") + "</details>";
    }

    /* 여기 소속은 아니지만 이 분류를 찾아온 사람이 볼 만한 주제(보조 분류).
     * 위 목록과 섞지 않는다 — 이 분류의 메시지 수는 소속 주제만 센 값이고,
     * 섞으면 화면의 숫자와 목록이 어긋난다. 원래 어디 소속인지 함께 적어 둔다. */
    var alsoRows = (d.also_threads || []).map(function (a) {
      return THREAD_BY_ID[a.id];
    }).filter(Boolean).sort(function (a, b) {
      return String(b.end_date || "").localeCompare(String(a.end_date || ""));
    });
    var also = alsoRows.map(function (t) {
      return '<div class="thread-line also" data-start="t-' + esc(t.id) + '"><b>' +
        esc(t.title) + '</b><span class="tl-home" style="--c:' + colorFor(t.category) +
        '">' + esc(CAT_LABEL[t.category] || t.category) + "</span>" +
        '<span class="tl-n">💬 ' + t.count + "</span></div>";
    }).join("");

    /* 모바일에서는 이 아래를 접는다. 12개 주제가 전부 펼쳐지면 첫 화면이 25화면
     * 분량(20,375px)이 되어 아무도 끝까지 보지 않는다. 무엇이 들어 있는지 세어
     * 버튼에 적어 둔다 — 열어봐야 아는 상자는 안 열어보게 된다.
     *
     * 주제 개수는 세지 않는다: 카드 우상단 doc-meta 가 이미 "N개 주제" 를 적고
     * 있어서 같은 숫자가 위아래로 두 번 나온다. 접었을 때 어디에도 안 보이는
     * 것만 센다. */
    var counts = [];
    if ((d.apps || []).length) counts.push("결과물 " + d.apps.length);
    if (links.length) counts.push("링크 " + links.length);
    if (alsoRows.length) counts.push("곁 주제 " + alsoRows.length);

    var body =
      (kw ? '<div class="doc-kw">' + kw + "</div>" : "") +
      (apps ? '<div class="doc-section"><h4>🧩 주요 결과물</h4>' +
        '<p class="doc-note">누르면 그 결과물을 <b>다룬 주제</b>를 봅니다. ' +
        "'언급'은 다른 이야기 중에 스쳐 나온 횟수로, 목록에서 한 번 더 눌러야 " +
        "보입니다.</p>" +
        '<div class="app-list">' + apps + "</div></div>" : "") +
      (people ? '<div class="doc-section"><h4>👥 활발한 참여자</h4><div class="people-row">' + people + "</div></div>" : "") +
      (linkHtml ? '<div class="doc-section"><h4>🔗 공유 링크</h4><div class="link-list">' + linkHtml + "</div></div>" : "") +
      (threads ? '<div class="doc-section thread-list"><h4>🧵 소속 대화 주제 ' + threadList.length +
        "개</h4>" + threads + "</div>" : "") +
      /* 접어 둔다. 소속 주제 목록 아래에 곁 주제 44개가 그대로 펼쳐지면, 찾아온
       * 분류의 목록이 어디서 끝나는지 알 수 없다 — 곁길은 찾을 때만 열면 된다. */
      (also ? '<div class="doc-section thread-list">' +
        '<details class="more-fold"><summary>↔️ 여기서도 볼 만한 주제 ' +
        alsoRows.length + '개</summary><p class="doc-note">다른 분류에 속하지만 ' +
        '이 주제도 함께 다룬 대화입니다.</p>' + also + "</details></div>" : "");

    return '<article class="doc" id="doc-' + cid + '" style="--c:' + col + '">' +
      '<div class="doc-head"><span class="doc-bar"></span>' +
      // a 로 두어야 오른쪽 단추의 '링크 주소 복사'·새 탭 열기가 먹는다.
      // 화면 안에서는 기본 동작을 막고 상태만 바꾼다(새로고침이 아니다).
      '<h2 class="doc-title"><a class="doc-link" href="/summary?cat=' +
      encodeURIComponent(cid) + '" data-cat="' + esc(cid) + '">' +
      esc(d.label) + "</a></h2>" +
      '<span class="doc-meta">' + (d.message_count || 0) + "개 메시지 · " + (d.threads || []).length + "개 주제</span></div>" +
      (d.headline ? '<p class="doc-headline">' + esc(d.headline) + "</p>" : "") +
      '<p class="doc-overview">' + esc(d.overview || "") + "</p>" +
      (body
        ? '<button class="doc-toggle" type="button" aria-expanded="false" ' +
          'aria-controls="docbody-' + cid + '">' +
          '<span class="doc-toggle-icon" aria-hidden="true"></span>' +
          '<span class="doc-toggle-label">자세히 보기</span>' +
          (counts.length ? '<span class="doc-toggle-hint">' + counts.join(" · ") + "</span>" : "") +
          "</button>" +
          '<div class="doc-body" id="docbody-' + cid + '">' + body + "</div>"
        : "") +
      "</article>";
  }

  /** 주제 카드를 펼치거나 접는다. 데스크톱은 CSS 가 항상 펼쳐 두므로 여기 상태는
   *  모바일에서만 눈에 보인다. */
  function setDocOpen(doc, open) {
    if (!doc) return;
    doc.classList.toggle("open", open);
    var btn = doc.querySelector(".doc-toggle");
    if (!btn) return;
    btn.setAttribute("aria-expanded", open ? "true" : "false");
    var label = btn.querySelector(".doc-toggle-label");
    if (label) label.textContent = open ? "접기" : "자세히 보기";
  }

  /** 태그 칩을 눌렀을 때.
   *
   *  그 말이 실제 태그면 태그가 붙은 주제만 ID 로 골라낸다 — 글자 검색은 보고서
   *  본문에 스쳐 지나간 것까지 걸려서 "이게 왜 나오지"가 된다. 태그가 아닌 말
   *  (요지 산문에만 나오는 표현)은 그때만 글자 검색으로 넘긴다. */
  function openKeyword(word) {
    var ids = TAG_THREADS[tagFold(word)];
    if (ids && ids.length) pickThreads(ids, "#" + word, "tag");
    else runSearch(word);
  }

  function bindKeywordChips(scope) {
    Array.prototype.forEach.call(scope.querySelectorAll("[data-kw]"), function (b) {
      b.onclick = function (e) {
        e.stopPropagation();
        openKeyword(b.getAttribute("data-kw"));
      };
    });
  }

  function bindDocActions(scope) {
    Array.prototype.forEach.call(scope.querySelectorAll(".doc-toggle"), function (b) {
      b.onclick = function () {
        var doc = b.parentNode;
        setDocOpen(doc, !doc.classList.contains("open"));
      };
    });
    Array.prototype.forEach.call(scope.querySelectorAll(".app-item"), function (b) {
      b.onclick = function () {
        // 예전에는 결과물 이름으로 원문을 검색했는데, 원문 발행을 멈추면서
        // 검색 대상이 사라져 빈 목록으로 갔다. 지금은 빌드 때 이어 둔 주제로
        // 바로 간다. 이어진 주제가 없을 때만 옛 방식으로 물러선다.
        var ids = (b.getAttribute("data-pick") || "").split(",").filter(Boolean);
        var all = (b.getAttribute("data-pick-all") || "").split(",").filter(Boolean);
        if (ids.length) {
          pickThreads(ids, b.getAttribute("data-label"),
                      b.getAttribute("data-kind") || "subject",
                      all.length > ids.length ? all : null);
        } else {
          runSearch(b.getAttribute("data-q"));
        }
      };
    });
    bindKeywordChips(scope);
    Array.prototype.forEach.call(scope.querySelectorAll("[data-nick]"), function (b) {
      b.onclick = function () {
        el.filter.value = b.getAttribute("data-nick"); state.nick = el.filter.value;
        setView("timeline");
      };
    });
    Array.prototype.forEach.call(scope.querySelectorAll(".thread-line"), function (b) {
      b.onclick = function () { jumpToTimeline(b.getAttribute("data-start")); };
    });
  }

  // ---------- 관계망 ----------
  function renderGraph() {
    el.view.innerHTML =
      '<div class="graph-wrap"><div id="gmount"></div>' +
      '<div class="node-panel" id="nodePanel"><button class="np-close" id="npClose">×</button>' +
      '<div id="npBody"></div></div></div>';
    var panel = document.getElementById("nodePanel");
    document.getElementById("npClose").onclick = function () { panel.classList.remove("on"); };

    state.graph = window.KGraph.render(document.getElementById("gmount"), {
      nodes: KNOW.nodes, edges: KNOW.edges, colorFor: colorFor, catLabel: CAT_LABEL,
      // 노드 종류 표는 발행본이 준다 — 원본은 scripts/ontology.py 다.
      nodeTypes: KNOW.node_types,
      onSelect: function (node) {
        if (!node) { panel.classList.remove("on"); return; }
        fillNodePanel(node);
        panel.classList.add("on");
      },
    });
  }

  function fillNodePanel(node) {
    var body = document.getElementById("npBody");
    /* 종류 이름은 발행본의 표에서 읽는다(원본은 scripts/ontology.py). 예전에는
     * 여기와 graph.js 에 따로 적혀 있어서 같은 종류가 '앱·결과물' 과 '앱' 으로
     * 갈렸다. 표가 없는 옛 캐시에서는 id 를 그대로 보여준다 — 빈칸보다 낫다. */
    var typeMap = {};
    (KNOW.node_types || []).forEach(function (t) { typeMap[t.id] = t.label || t.id; });
    var rows = "", actions = "";
    if (node.type === "person") {
      rows = '<div class="np-row">메시지 ' + (node.messages || 0) + "개 · 주로 <b>" +
        esc(CAT_LABEL[node.category] || "") + "</b></div>";
      actions = '<button class="btn" data-act="nick" data-v="' + esc(node.label) + '">이 사람만 보기</button>';
    } else if (node.type === "topic") {
      rows = '<div class="np-row">주제 클러스터의 중심</div>';
      actions = '<button class="btn" data-act="doc" data-v="' + esc(node.category) + '">지식 문서 보기</button>';
    } else if (node.type === "app") {
      rows = '<div class="np-row">만든이 <b>' + esc(node.maker || "-") + "</b><br>주제 " +
        esc(CAT_LABEL[node.category] || "") + "</div>";
      actions = '<button class="btn" data-act="q" data-v="' + esc(node.query || node.label) + '">타임라인에서 보기</button>';
    } else {
      rows = '<div class="np-row">주제 ' + esc(CAT_LABEL[node.category] || "") + "</div>";
      actions = '<button class="btn" data-act="q" data-v="' + esc(node.query || node.label) + '">타임라인에서 보기</button>';
    }
    /* 언제 오간 이야기인가. 관계망에는 시간이 없어서 작년에 한 번 스친 도구와
     * 어제까지 쓰는 도구가 나란히 떠 있었다. 흐리게 하거나 걸러내지는 않는다 —
     * 새 시각 언어를 만들기 전에 사실만 적어 둔다. 날짜가 없는 노드(원문에 이름이
     * 한 번도 안 나온 것)는 이 줄을 아예 내지 않는다. */
    var when = "";
    if (node.first_seen) {
      var span = node.first_seen === node.last_seen
        ? node.first_seen
        : node.first_seen + " ~ " + node.last_seen;
      when = '<div class="np-row np-when">' + esc(span) +
        (node.mentions ? " · " + node.mentions + "회 언급" : "") + "</div>";
    }
    body.innerHTML = '<h4>' + esc(node.label) + "</h4>" +
      '<div class="np-type">' + esc(typeMap[node.type] || node.type || "") + "</div>" + rows +
      when + '<div class="np-actions">' + actions + "</div>";
    Array.prototype.forEach.call(body.querySelectorAll("[data-act]"), function (b) {
      b.onclick = function () {
        var v = b.getAttribute("data-v");
        if (b.getAttribute("data-act") === "nick") { el.filter.value = v; state.nick = v; setView("timeline"); }
        else if (b.getAttribute("data-act") === "q") { runSearch(v); }
        else if (b.getAttribute("data-act") === "doc") {
          setView("summary");
          requestAnimationFrame(function () {
            var t = document.getElementById("doc-" + v);
            if (t) t.scrollIntoView({ behavior: "smooth", block: "start" });
          });
        }
      };
    });
  }

  /* ---------- 주제 흐름 (옛 타임라인) ----------
   *
   * 원문을 한 줄씩 늘어놓지 않는다. 이 방의 가치는 오간 말이 아니라 그 안의
   * 내용이고, 원문을 뿌리면 devtools 로 전부 읽히기까지 한다. 대신 스레드 요약을
   * 시간순으로 보여주고, 결과물(링크·사진·첨부)은 그대로 붙인다.
   */
  function threadMatches(t) {
    if (state.pick && state.pick.ids.indexOf(t.id) === -1) return false;
    if (state.nick && (t.participants || []).indexOf(state.nick) === -1) return false;
    if (state.q) {
      var q = state.q.toLowerCase();
      // AI 보고서 본문도 찾는 대상이다 — 'Blaze'·'KWCAG' 처럼 사람 보고서에는
      // 없고 검증 주석에만 있는 말이 적지 않다.
      var hay = (t.title + " " + t.summary + " " + (t.report || "") + " " +
                 (t.ai_report || "") + " " +
                 (t.keywords || []).join(" ") + " " + (t.participants || []).join(" ") +
                 " " + t.start_date + " " + (t.links || []).map(function (l) {
                   return l.url; }).join(" ")).toLowerCase();
      if (hay.indexOf(q) === -1) return false;
    }
    return true;
  }

  /** 결과물 하나에 딸린 주제만 추린다. 검색어가 아니라 ID 로 고르므로
   *  보고서를 어떻게 고쳐 쓰든 결과가 흔들리지 않는다. */
  function pickThreads(ids, label, kind, moreIds) {
    state.pick = { ids: ids, label: label, kind: kind || "mention",
                   moreIds: moreIds || null };
    state.q = ""; state.nick = "";
    el.search.value = ""; el.filter.value = "";
    setView("timeline");
  }

  /* ---------- 태그 입구 ----------
   *
   * 분류 12개로는 묻히는 화제가 있다 — 'clasp' 이야기는 다섯 군데 흩어져 있고
   * 어느 분류에도 'clasp' 이라 적혀 있지 않다. 보고서 태그를 한자리에 모아 그
   * 길을 낸다. 표기가 갈린 태그는 발행할 때 이미 합쳐 두었다(scripts/tags.py).
   *
   * 한 번만 쓰인 태그 800여 개는 목록에 올리지 않는다. 다 늘어놓으면 목록이
   * 아니라 벽이 되고, 그 태그는 어차피 주제 하나로만 이어진다(검색으로 찾는다).
   */
  /** 고른 태그들이 **모두** 붙은 주제. 하나도 안 골랐으면 null. */
  function tagPickIds() {
    var picked = state.tagPick || [];
    if (!picked.length) return null;
    var sets = picked.map(function (t) { return TAG_THREADS[tagFold(t)] || []; });
    return sets[0].filter(function (id) {
      return sets.every(function (s) { return s.indexOf(id) !== -1; });
    });
  }

  function renderTags() {
    // 사람 이름과 지명·기관 이름은 구름에서 빼고 아래에 따로 모은다. 태그 구름은
    // '무엇을 이야기했나' 의 자리다 — 누가·어디는 참여자 필터와 보고서 본문 몫이다.
    // 기관 계정이 방에 있으면 그 이름은 참여자이면서 기관이다('○○복지관' 계정).
    // 그럴 때는 사람 쪽이 아니라 지명·기관 쪽에 둔다 — 표에 적은 사람의 판단이
    // 참여자 이름에서 자동으로 뽑은 것보다 낫다.
    var rows = (TAGIDX.tags || []).filter(function (r) { return !r.person && !r.place; });
    var people = (TAGIDX.tags || []).filter(function (r) { return r.person && !r.place; });
    var places = (TAGIDX.tags || []).filter(function (r) { return r.place; });
    if (!rows.length) {
      el.view.innerHTML = emptyState("search", "아직 모인 태그가 없어요",
        "주제 보고서에 태그가 붙으면 이곳에 모입니다.");
      return;
    }
    var picked = state.tagPick || (state.tagPick = []);
    var full = picked.length >= TAG_PICK_MAX;
    var hitIds = tagPickIds() || [];
    var max = rows[0].count;

    function chip(r) {
      var on = picked.indexOf(r.tag) !== -1;
      // 지금 고른 것들과 함께 붙은 주제가 없으면 눌러도 빈 목록이다 — 미리 막는다.
      var dead = !on && picked.length &&
        !hitIds.some(function (id) {
          return (TAG_THREADS[tagFold(r.tag)] || []).indexOf(id) !== -1;
        });
      // 많이 쓰인 태그가 눈에 먼저 들어오게 글자 크기를 조금 키운다(1.0~1.5배).
      var scale = (1 + 0.5 * (r.count - 1) / Math.max(1, max - 1)).toFixed(2);
      return '<button class="tag-chip' + (on ? " on" : "") + '" data-tag="' +
        esc(r.tag) + '" style="font-size:' + scale + 'em"' +
        (dead || (full && !on) ? " disabled" : "") + '>' +
        esc(r.tag) + '<span class="tag-n">' + r.count + "</span></button>";
    }

    /* 고른 태그와 결과 수를 늘 보여 준다. 고르는 동안 몇 건인지 모르면 '보기'를
     * 눌러야 알게 되고, 0건이면 헛수고가 된다. */
    var bar = "";
    if (picked.length) {
      bar = '<div class="tag-bar">' +
        picked.map(function (t) {
          return '<button class="tag-chip on" data-unpick="' + esc(t) + '">' +
            esc(t) + '<span class="tag-n">×</span></button>';
        }).join("") +
        '<span class="tag-bar-n">' +
        (hitIds.length ? "주제 " + hitIds.length + "개"
                       : "함께 붙은 주제가 없습니다") + "</span>" +
        (hitIds.length ? '<button class="btn" id="tagGo">보기</button>' : "") +
        '<button class="btn ghost" id="tagClear">비우기</button></div>';
    }

    var html = [
      '<div class="gal-head"><p class="room-sub">태그 ' + rows.length +
      "개 · 최대 " + TAG_PICK_MAX +
      "개까지 골라 겹치는 주제를 볼 수 있습니다</p></div>",
      bar,
      '<label class="tag-search"><span class="sr-only">태그 검색</span>' +
      '<input id="tagFilter" type="search" placeholder="태그 이름으로 좁히기" ' +
      'autocomplete="off" /><span class="tag-hits" id="tagHits"></span></label>',
      '<div class="tag-cloud" id="tagCloud">' + rows.map(chip).join("") + "</div>",
    ];
    if (TAGIDX.hidden_tags) {
      html.push('<p class="doc-note">한 주제에서만 쓰인 태그 ' + TAGIDX.hidden_tags +
        "개는 목록에서 뺐습니다 — 위 검색창이 아니라 화면 위쪽 검색으로 찾을 수 있어요.</p>");
    }
    if (people.length) {
      html.push('<div class="doc-section"><h4>👤 사람 이름으로 붙은 태그</h4>' +
        '<p class="doc-note">사람은 참여자 필터로 찾는 편이 정확합니다.</p>' +
        '<div class="tag-cloud small">' + people.map(chip).join("") + "</div></div>");
    }
    if (places.length) {
      html.push('<div class="doc-section"><h4>📍 지명·기관 이름으로 붙은 태그</h4>' +
        '<p class="doc-note">어디서 있었던 일인지는 보고서 본문이 말해 줍니다.</p>' +
        '<div class="tag-cloud small">' + places.map(chip).join("") + "</div></div>");
    }
    el.view.innerHTML = html.join("");

    // 누르면 고른다(바로 넘어가지 않는다). 두세 개 겹쳐 보려면 골라야 하기 때문에,
    // 한 개짜리도 같은 길로 간다 — 두 규칙이 섞이면 무엇이 일어날지 알 수 없다.
    Array.prototype.forEach.call(el.view.querySelectorAll("[data-tag]"), function (b) {
      b.onclick = function () {
        var tag = b.getAttribute("data-tag");
        var at = picked.indexOf(tag);
        if (at !== -1) picked.splice(at, 1);
        else if (picked.length < TAG_PICK_MAX) picked.push(tag);
        // 고른 태그를 주소에 남긴다 — 새로고침해도 남고, 링크로 줄 수 있다.
        writeHash(true);
        renderTags();
      };
    });
    Array.prototype.forEach.call(el.view.querySelectorAll("[data-unpick]"), function (b) {
      b.onclick = function () {
        var at = picked.indexOf(b.getAttribute("data-unpick"));
        if (at !== -1) picked.splice(at, 1);
        writeHash(true);
        renderTags();
      };
    });
    var go = document.getElementById("tagGo");
    if (go) {
      go.onclick = function () {
        pickThreads(hitIds, picked.map(function (t) { return "#" + t; }).join(" + "),
                    "tag");
      };
    }
    var clear = document.getElementById("tagClear");
    if (clear) {
      clear.onclick = function () {
        state.tagPick = []; writeHash(true); renderTags();
      };
    }
    var input = document.getElementById("tagFilter");
    var hits = document.getElementById("tagHits");
    if (input) {
      input.oninput = function () {
        // 표기 차이를 무시해 맞춘다 — '바이브 코딩' 이라 쳐도 '바이브코딩' 이 나온다.
        var q = tagFold(input.value);
        var shown = 0;
        Array.prototype.forEach.call(el.view.querySelectorAll(".tag-chip"), function (b) {
          var hit = !q || tagFold(b.getAttribute("data-tag")).indexOf(q) !== -1;
          b.hidden = !hit;
          if (hit) shown++;
        });
        if (hits) {
          hits.textContent = !q ? ""
            : (shown ? shown + "개" : "맞는 태그가 없습니다");
        }
      };
    }
  }

  /** 주제 정렬 키 — 같은 날 주제가 여럿이라 시각까지 봐야 순서가 맞는다. */
  function threadKey(t) {
    return (t.start_date || "") + " " + (t.start_time || "");
  }

  function renderTimeline() {
    var rows = THREADS.filter(threadMatches);
    /* 두 길이 서로 다른 규칙으로 돈다. 라벨이 같으면 무엇을 보고 있는지 알 수
     * 없다 — '차량 운행일지'가 결과물 버튼으로는 6개(원문에 언급된 것), 태그로는
     * 5개(태그가 붙은 것)로 다르게 나오는데 안내문이 같았다. */
    var pickHead = "";
    if (state.pick) {
      if (state.pick.kind === "tag") {
        // 라벨에 '#' 이 이미 들어 있다(여러 개면 '#a + #b').
        pickHead = "🏷️ 태그 <b>" + esc(state.pick.label) + "</b> 가 붙은 주제 ";
      } else if (state.pick.kind === "subject") {
        pickHead = "🧩 <b>" + esc(state.pick.label) + "</b> 를 다룬 주제 ";
      } else {
        pickHead = "🧩 <b>" + esc(state.pick.label) +
          "</b> 이(가) 대화에 나온 주제(스쳐 언급 포함) ";
      }
    }
    var pickBar = state.pick
      ? '<div class="pick-bar">' + pickHead +
        rows.length + '개만 보고 있습니다 ' +
        (state.pick.moreIds
          ? '<button class="btn ghost" id="pickMore">스쳐 언급된 것까지 ' +
            state.pick.moreIds.length + "개 보기</button> " : "") +
        '<button class="btn ghost" id="pickClear">' +
        "전체 보기</button></div>"
      : "";
    if (!rows.length) {
      el.view.innerHTML = pickBar + emptyState("search", "조건에 맞는 이야기를 찾지 못했어요",
        "검색어를 조금 줄이거나 참여자 필터를 비우고 다시 살펴보세요.");
      bindPickClear();
      return;
    }

    // 최신 것부터 보는 게 기본이다 — 어제 무슨 얘기가 오갔는지가 가장 궁금하다.
    var desc = state.tsort !== "asc";
    rows = rows.slice().sort(function (a, b) {
      var ka = threadKey(a), kb = threadKey(b);
      if (ka === kb) return 0;
      return (ka < kb ? -1 : 1) * (desc ? -1 : 1);
    });

    var html = [pickBar, '<div class="gal-head">',
      '<p class="room-sub">주제 ' + rows.length +
      "개" + (rows.length !== THREADS.length ? " / 전체 " + THREADS.length : "") +
      " · 대화 원문은 보관만 하고 공개하지 않습니다</p>",
      '<div class="gal-modes">',
      '<button class="gal-mode' + (desc ? " on" : "") + '" data-tsort="desc">↓ 최신순</button>',
      '<button class="gal-mode' + (desc ? "" : " on") + '" data-tsort="asc">↑ 오래된순</button>',
      "</div></div>"];
    var lastDate = null;
    rows.forEach(function (t) {
      if (t.start_date !== lastDate) {
        html.push('<div class="date-sep">' + esc(fmtDate(t.start_date)) + "</div>");
        lastDate = t.start_date;
      }
      html.push(renderThreadCard(t));
    });
    el.view.innerHTML = html.join("");
    bindPickClear();
    Array.prototype.forEach.call(el.view.querySelectorAll("[data-tsort]"), function (b) {
      b.onclick = function () {
        state.tsort = b.getAttribute("data-tsort");
        try { localStorage.setItem("thread-sort", state.tsort); } catch (e) { /* 무시 */ }
        renderTimeline();
      };
    });
    bindThreadCards(el.view);
    // 검색 중이면 카드가 펼쳐진 채로 그려지므로 사진·첨부도 함께 채운다
    Array.prototype.forEach.call(el.view.querySelectorAll(".tc-detail.on"), fillMedia);
  }







  /* 대화 보고서.
   *
   * 원문을 발행하지 않기로 한 이상 보고서가 원문을 대신해야 한다. 목록을
   * 훑을 때는 방해가 되므로 접어 두고, 검색 중이면 어디가 걸렸는지 보이도록
   * 펼쳐 둔다. 사진·첨부는 media 발행본에서 thread_id 로 찾아 붙인다.
   */
  function reportToggleIcon() {
    return '<svg class="tc-toggle-icon" aria-hidden="true" viewBox="0 0 24 24" ' +
      'fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" ' +
      'stroke-linejoin="round"><path d="M6 3h9l3 3v15H6z"></path>' +
      '<path d="M14 3v4h4M9 12h6M9 16h6"></path></svg>';
  }

  /* 사람 보고서 단추와 눈에 띄게 달라야 한다 — 같은 문서 아이콘을 쓰면 같은 글의
     다른 판처럼 보인다. 확인·대조를 뜻하는 겹친 표시로 둔다. */
  function aiToggleIcon() {
    return '<svg class="tc-toggle-icon" aria-hidden="true" viewBox="0 0 24 24" ' +
      'fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" ' +
      'stroke-linejoin="round"><path d="M4 7h9M4 12h5M4 17h7"></path>' +
      '<path d="M13.5 16.5l2.5 2.5 5-5.5"></path></svg>';
  }

  function detailBlock(t, contextualLinks) {
    if (!t.report) return "";
    var open = !!state.q;
    // 걸린 말이 AI 보고서에만 있으면 그쪽을 펴 두어야 한다. 카드가 결과에 떴는데
    // 어디가 걸렸는지 안 보이면 고장으로 읽힌다. 반대로 사람 보고서에 걸린
    // 검색까지 AI 쪽을 열면 안 본다고 한 글이 매번 따라 나온다.
    var aiOpen = !!(state.q && t.ai_report &&
      t.ai_report.toLowerCase().indexOf(state.q.toLowerCase()) !== -1);
    var n = mediaOf(t.id).length;
    var hasResources = n || contextualLinks.length;
    return '<div class="tc-detail' + (open ? " on" : "") + (aiOpen ? " ai-on" : "") +
      '" data-tid="' + esc(t.id) + '">' +
      '<div class="tc-detail-bar">' +
      '<button class="tc-toggle" type="button" aria-expanded="' + (open ? "true" : "false") + '">' +
      reportToggleIcon() + '<span class="tc-toggle-label">' +
      (open ? "보고서 접기" : "보고서 읽기") + "</span></button>" +
      // AI 보고서는 **있는 카드에만** 단추가 뜬다. 없는 카드에 회색 단추를 두면
      // 눌러 보고서야 없다는 것을 알게 되고, 그런 단추가 대부분이다.
      (t.ai_report ? aiToggleButton(aiOpen) : "") +
      '<button class="tc-dl" type="button" title="이 보고서를 .md 파일로 저장합니다">' +
      "⬇ .md</button></div>" +
      // 본문은 비워 둔다 — 읽겠다고 누른 카드만 fillReport() 가 채운다.
      '<div class="tc-detail-body md"' + (hasResources ? ' data-res="1"' : "") +
      "></div>" +
      (t.ai_report ? '<div class="tc-ai-body-wrap"></div>' : "") +
      "</div>";
  }

  /* 보고서 본문은 '읽겠다'고 할 때 비로소 만든다.
   *
   * 목록에 들어서는 순간 359장 전부의 마크다운을 HTML 로 바꿔 넣어 두었는데,
   * 정작 읽는 것은 한두 장이다. 문서가 10만 px 로 자라 있으면 접힌 카드
   * 하나를 펼치는 것만으로도 문서 전체가 다시 레이아웃되어 브라우저가 멈춘다.
   * 만들지 않은 것은 레이아웃할 것도 없다.
   */
  /* 기계가 쓴 검증 주석. 사람 보고서 아래에 **테두리를 두른 채로** 붙인다.
   *
   * 섞어 쓰지 않는 것이 요점이다. 이 방의 말은 사람이 한 말이고, 여기 적힌 것은
   * 그 말을 기계 둘이 맞춰 본 결과다. 둘을 한 흐름으로 읽히게 두면 누가 한
   * 말인지 알 수 없어진다.
   */
  function aiToggleButton(aiOpen) {
    return '<button class="tc-ai-toggle" type="button" aria-expanded="' +
      (aiOpen ? "true" : "false") + '" ' +
      'title="이 대화를 두 AI 가 따로 검증한 결과입니다">' +
      aiToggleIcon() + '<span class="tc-ai-toggle-label">' +
      (aiOpen ? "AI 보고서 접기" : "AI 보고서") + "</span></button>";
  }

  function bindAiToggle(b) {
    b.onclick = function () {
      var box = b.parentNode.parentNode;
      var on = box.classList.toggle("ai-on");
      var label = b.querySelector(".tc-ai-toggle-label");
      if (label) label.textContent = on ? "AI 보고서 접기" : "AI 보고서";
      b.setAttribute("aria-expanded", on ? "true" : "false");
      if (on) fillAiReport(box);
    };
  }

  /* AI 검증 주석은 화면이 뜬 뒤에 온다(boot.js loadRest). 그때 이미 그려진 카드에
   * 단추를 **끼워 넣는다** — 화면을 다시 그리면 사람이 읽던 자리와 펼친 카드가
   * 날아간다. 단추가 없는 카드 중 주석이 생긴 것만 손댄다. */
  function patchAiButtons(scope) {
    Array.prototype.forEach.call(scope.querySelectorAll(".tc-detail[data-tid]"), function (box) {
      if (box.querySelector(".tc-ai-toggle")) return;
      var t = THREAD_BY_ID[box.getAttribute("data-tid")];
      if (!t || !t.ai_report) return;
      var toggle = box.querySelector(".tc-toggle");
      if (!toggle) return;
      toggle.insertAdjacentHTML("afterend", aiToggleButton(false));
      var wrap = document.createElement("div");
      wrap.className = "tc-ai-body-wrap";
      box.appendChild(wrap);
      bindAiToggle(box.querySelector(".tc-ai-toggle"));
    });
  }

  /** boot.js 가 요지를 받아 오면 부른다. 요지 화면을 보고 있었으면 다시 그린다. */
  function attachDigests(d) {
    DIGESTS = d || {};
    A.digests = DIGESTS;
    state.digestsPending = false;
    if (state.view === "summary") render();
  }

  /** boot.js 가 AI 검증 주석을 받아 오면 부른다. 스레드에 붙이고 보이는 카드에 단추를 끼운다. */
  function attachAiReports(items) {
    (items || []).forEach(function (r) {
      var t = THREAD_BY_ID[r.id];
      if (!t) return;
      t.ai_report = r.ai_report;
      t.ai_checked = r.ai_checked;
      t.ai_models = r.ai_models;
    });
    if (state.view === "timeline" && el.view) patchAiButtons(el.view);
  }

  function aiReportBlock(t) {
    if (!t.ai_report) return "";
    var meta = [];
    if (t.ai_models) meta.push(esc(t.ai_models));
    if (t.ai_checked) meta.push(esc(t.ai_checked) + " 확인");
    return '<section class="tc-ai" aria-label="AI 검증 보고서">' +
      '<div class="tc-ai-head">' +
      '<span class="tc-ai-badge">AI 검증</span>' +
      (meta.length ? '<span class="tc-ai-meta">' + meta.join(" · ") + "</span>" : "") +
      "</div>" +
      '<div class="tc-ai-body md">' +
      highlightText(renderMarkdown(t.ai_report), state.q) + "</div>" +
      '<p class="tc-ai-foot">사람이 쓴 위 보고서를 두 AI 가 따로 검토해 ' +
      '<strong>합의한 것만</strong> 적었습니다. 기계의 말이니 그대로 인용하기 전에 ' +
      '원 출처를 한 번 확인해 주세요.</p></section>';
  }

  /* AI 보고서도 누를 때 비로소 만든다. 사람 보고서와 같은 이유다 — 목록에
     들어서자마자 전부 마크다운을 HTML 로 바꿔 두면 펼치는 것만으로 멈춘다. */
  function fillAiReport(box) {
    var wrap = box.querySelector(".tc-ai-body-wrap");
    if (!wrap || wrap.getAttribute("data-filled")) return;
    var tid = box.getAttribute("data-tid");
    var t = THREADS.filter(function (x) { return x.id === tid; })[0];
    if (!t || !t.ai_report) return;
    wrap.setAttribute("data-filled", "1");
    wrap.innerHTML = aiReportBlock(t);
  }

  function fillReport(box) {
    var body = box.querySelector(".tc-detail-body");
    if (!body || body.getAttribute("data-filled")) return;
    var tid = box.getAttribute("data-tid");
    var t = THREADS.filter(function (x) { return x.id === tid; })[0];
    if (!t) return;
    body.setAttribute("data-filled", "1");
    body.innerHTML =
      highlightText(linkifyHosts(renderMarkdown(t.report), splitLinks(t).inline), state.q) +
      (body.getAttribute("data-res")
        ? '<div class="tc-media" data-media="' + esc(t.id) + '"></div>' : "");
    fillMedia(box);
  }

  /* 검색 중에는 카드가 펼쳐진 채로 그려진다(어디가 걸렸는지 보여야 한다). 그
   * 145장을 한꺼번에 채우면 검색어를 한 글자 칠 때마다 멈추므로, 화면에
   * 다가온 것부터 채운다. */
  var reportObserver = null;

  /* 펴진 것을 채운다 — 사람 보고서든 AI 보고서든, 열려 있는 쪽만. */
  function fillOpenPanels(box) {
    if (box.classList.contains("on")) fillReport(box);
    if (box.classList.contains("ai-on")) fillAiReport(box);
  }

  function observeOpenReports(scope) {
    var boxes = scope.querySelectorAll(".tc-detail.on, .tc-detail.ai-on");
    if (!boxes.length) return;
    if (!("IntersectionObserver" in window)) {
      Array.prototype.forEach.call(boxes, fillOpenPanels);
      return;
    }
    if (!reportObserver) {
      reportObserver = new IntersectionObserver(function (entries) {
        entries.forEach(function (en) {
          if (!en.isIntersecting) return;
          reportObserver.unobserve(en.target);
          fillOpenPanels(en.target);
        });
      }, { rootMargin: "400px" });
    }
    // 지금 눈에 들어와 있는 것은 관찰자를 기다리지 않고 바로 채운다 — 검색 결과
    // 첫 화면이 빈 채로 한 박자 늦게 나타나면 고장으로 보인다.
    var reach = window.innerHeight * 1.5;
    Array.prototype.forEach.call(boxes, function (b) {
      if (b.getBoundingClientRect().top < reach) fillOpenPanels(b);
      else reportObserver.observe(b);
    });
  }

  /** 이 주제에서 오간 사진·첨부. 보고서에 손으로 적지 않고 여기서 찾는다. */
  function mediaOf(tid) {
    return MEDIA.filter(function (m) { return m.thread_id === tid; });
  }

  /** 사진·첨부 한 묶음을 그린다. 본문 사이(inline)든 보고서 끝이든 모양은 같다. */
  function mediaHtml(rows, inline) {
    var imgs = [], files = [];
    rows.forEach(function (m) {
      /* 동영상. 칸에는 포스터만 걸고 원본은 눌러서 받는다 — 보고서를 펼치기만
       * 해도 16MB 가 내려오면 안 된다. 라이트박스가 data-video 를 보고 <video>
       * 로 연다(갤러리와 같은 길). 이 가지가 없던 동안 동영상은 자리표를 채우지
       * 못해 제목만 남고 아래가 비었다(2026-08-31 t-426). */
      if (m.kind === "video" && m.videos) {
        var vth = m.thumbs || [];
        m.videos.forEach(function (src, i) {
          imgs.push('<span class="im-video"><img data-img="' + esc(vth[i] || src) +
            '" data-full="' + esc(src) + '" data-video="1" alt="" title="' +
            esc(m.nickname + " · " + m.date) + '" /><span class="play">▶</span></span>');
        });
      } else if (m.kind === "image" && m.images) {
        var th = m.thumbs || m.images;
        m.images.forEach(function (src, i) {
          // 칸에는 작은 사진, 누르면 원본(data-full)
          imgs.push('<img data-img="' + esc(th[i] || src) +
            '" data-full="' + esc(src) + '" alt="" title="' +
            esc(m.nickname + " · " + m.date) + '" />');
        });
        // 개인정보가 찍혀 발행에서 뺀 사진. 칸을 아예 없애면 "여기 사진이 있었는데"
        // 를 알 수 없고 고장과 구분되지 않으므로, 왜 없는지 적은 자리를 남긴다.
        for (var h = 0; h < (m.pii_hidden || 0); h++) {
          imgs.push('<div class="img-hidden" title="' +
            esc(m.nickname + " · " + m.date) +
            '"><span>🔒</span><small>개인정보가 있어<br />감춘 사진</small></div>');
        }
      } else if (m.kind === "file") {
        var nm = m.file ? m.file.name : (m.name || "");
        files.push('<div class="tcf">' + fileIcon(nm) +
          ' <span class="tcf-n">' + esc(nm) + "</span>" +
          '<span class="tcf-m">' + esc(m.nickname) + " · " + esc(m.date) + "</span>" +
          (m.file
            ? '<button class="btn ghost" data-file="' + esc(m.file.path) +
              '" data-name="' + esc(m.file.name) + '">받기</button>'
            : m.file_expired
              ? '<span class="fc-gone" title="카톡 보관 기간(14일)이 지나 서랍에서 사라졌습니다">만료됨</span>'
              : '<span class="fc-none" title="아직 받지 못했습니다 — 밤마다 다시 받아 옵니다">수집 대기</span>')
          + "</div>");
      }
    });
    var cap = "";
    if (inline && imgs.length) {
      var m0 = rows[0];
      // 동영상을 '사진 1장' 이라고 적으면 글이 화면과 다른 말을 한다.
      var vid = m0.kind === "video";
      cap = '<div class="mi-cap">' + (vid ? "🎬 " : "🖼 ") + esc(m0.nickname) + " · " +
        esc(m0.date) + " " + esc(m0.time || "") +
        (imgs.length > 1 ? " · " + imgs.length + (vid ? "편" : "장") : "") + "</div>";
    }
    return (imgs.length ? '<div class="imgs' + (inline && imgs.length === 1 ? " single" : "") + '">' +
        imgs.join("") + "</div>" + cap : "") +
      (files.length ? '<div class="tcf-list">' + files.join("") + "</div>" : "");
  }

  function contextualLinkHtml(rows) {
    return rows.map(function (l) {
      var host = hostOf(l.url) || "외부 링크";
      return '<a class="context-link-card" href="' + esc(l.url) + '" target="_blank" ' +
        'rel="noopener noreferrer">' +
        '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' +
        '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path>' +
        '<path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path>' +
        "</svg>" +
        '<span class="context-link-copy"><strong>' + esc(host) + "</strong>" +
        '<span class="context-link-url">' + esc(l.url) + "</span>" +
        '<span class="context-link-meta">' + esc(l.nickname || "") + " · " +
        esc(l.date || "") + (l.time ? " " + esc(l.time) : "") + "</span></span></a>";
    }).join("");
  }

  /* 보고서에 문맥 링크와 그날 오간 사진·첨부를 붙인다.
   *
   * 본문에 링크 자리표(![[link:msg-…]])와 미디어 자리표(![[msg-…]])가 있으면
   * 그 자리에 끼우고, 자리표가 없는 미디어만 보고서 끝으로 모은다.
   *
   * 펼칠 때 채운다. 165개 카드의 이미지를 미리 다 걸어 두면 Storage 인증
   * 요청이 한꺼번에 나간다. data-filled 로 두 번 채우는 것을 막는다.
   */
  function fillMedia(box) {
    var host = box.querySelector(".tc-media");
    if (!host || host.getAttribute("data-filled")) return;
    var tid = host.getAttribute("data-media");
    var rows = mediaOf(tid);
    var thread = THREADS.filter(function (t) { return t.id === tid; })[0];
    host.setAttribute("data-filled", "1");

    var linkAnchors = {};
    Array.prototype.forEach.call(box.querySelectorAll(".md-link-anchor"), function (a) {
      linkAnchors[a.getAttribute("data-link-anchor")] = a;
    });
    var linksByMessage = {};
    (thread && thread.links || []).forEach(function (l) {
      if (linkAnchors[l.id]) (linksByMessage[l.id] || (linksByMessage[l.id] = [])).push(l);
    });
    Object.keys(linksByMessage).forEach(function (id) {
      linkAnchors[id].innerHTML = contextualLinkHtml(linksByMessage[id]);
    });

    var anchors = {};
    Array.prototype.forEach.call(box.querySelectorAll(".md-anchor"), function (a) {
      anchors[a.getAttribute("data-anchor")] = a;
    });

    var rest = [];
    rows.forEach(function (m) {
      var a = anchors[m.id];
      if (a) a.innerHTML = mediaHtml([m], true);
      else rest.push(m);
    });

    /* 일부는 본문 사이에, 일부는 아래에 남으면 임의로 갈라 놓은 것처럼 보인다.
     * 실제 기준은 '본문이 그 자료를 다뤘는가'다 — 그러니 그렇게 적는다. */
    var someInline = rows.length > rest.length;
    host.innerHTML = rest.length
      ? "<h4>" + (someInline ? "본문에서 다루지 않은 자료" : "이 주제에서 함께 공유된 자료") +
        "</h4>" + mediaHtml(rest, false)
      : "";
    bindImages(box);
    bindFiles(box);
  }

  /** 보고서를 .md 로 내려받는다. 화면에 보이는 것이 곧 파일이다. */
  function downloadReport(t) {
    var head = ["---",
      "title: " + t.title,
      "summary: " + (t.summary || ""),
      "keywords: " + (t.keywords || []).join(", "),
      "date: " + t.start_date + (t.end_date !== t.start_date ? " ~ " + t.end_date : ""),
      "participants: " + (t.participants || []).join(", "),
      "messages: " + (t.count || 0),
      "---", ""].join("\n");
    /* 자리표는 화면에서만 사진으로 부풀 뿐, 파일에 그대로 두면 뜻 모를 기호가
       된다. 무엇이 그 자리에 있었는지 한 줄로 적어 남긴다. */
    var body = String(t.report || "").replace(
      /^!\[\[link:([A-Za-z0-9_-]+)\]\]$/gm,
      function (all, id) {
        var links = (t.links || []).filter(function (x) { return x.id === id; });
        return links.map(function (l) {
          return "> 🔗 [" + hostOf(l.url) + "](" + l.url + ") — " +
            l.nickname + " · " + l.date + " " + (l.time || "");
        }).join("\n");
      }
    ).replace(/^!\[\[\s*([A-Za-z0-9_-]+)\s*\]\]$/gm,
      function (all, id) {
        var m = MEDIA.filter(function (x) { return x.id === id; })[0];
        if (!m) return "";
        var what = m.kind === "file"
          ? "📎 " + (m.name || (m.file && m.file.name) || "첨부")
          : "🖼 사진" + (m.images && m.images.length > 1 ? " " + m.images.length + "장" : "");
        return "> " + what + " — " + m.nickname + " · " + m.date + " " + (m.time || "");
      });
    var blob = new Blob([head + body + "\n"], { type: "text/markdown;charset=utf-8" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = t.id + "-" + String(t.title).replace(/[\\/:*?"<>|]/g, "") + ".md";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
  }

  function renderThreadCard(t) {
    var col = colorFor(t.category);
    var people = (t.participants || []).map(function (n) {
      return '<button class="chip" data-nick="' + esc(n) + '">' + esc(n) + "</button>";
    }).join("");
    // 본문에 주소가 적힌 링크는 본문에서 걸고, 아래 목록에는 나머지만 남긴다
    var lk = splitLinks(t);
    var links = lk.rest.slice(0, 6).map(function (l) {
      return '<div class="tc-link"><a href="' + esc(l.url) + '" target="_blank" ' +
        'rel="noopener noreferrer">' + esc(l.url) + "</a></div>";
    }).join("");
    var more = lk.rest.length > 6
      ? '<div class="tc-more">링크 ' + (lk.rest.length - 6) + "개 더</div>" : "";
    var range = t.start_date === t.end_date
      ? t.start_date : t.start_date + " ~ " + t.end_date;

    return '<article class="tcard" id="t-' + esc(t.id) + '" style="--c:' + col + '">' +
      '<div class="tc-head">' +
      '<span class="cat" style="--c:' + col + '">#' +
      esc(CAT_LABEL[t.category] || t.category) + "</span>" +
      '<span class="tc-meta">' + esc(range) + " · 대화 " + (t.count || 0) + "건" +
      (t.media_count ? " · 사진·첨부 " + t.media_count : "") + "</span></div>" +
      '<h3 class="tc-title">' + highlightText(esc(t.title), state.q) + "</h3>" +
      '<p class="tc-summary">' + highlightText(esc(t.summary || ""), state.q) + "</p>" +
      // 원본(`keywords`)이 아니라 발행 때 통일·승격한 `tags` 를 보여준다. '온톨로지
      // 모델링' 주제를 '온톨로지' 로 찾아 들어왔는데 카드에 '온톨로지' 가 없으면
      // "이게 왜 여기 있지" 가 된다. 표기도 카드마다 갈리지 않는다.
      (function () {
        var kws = t.tags || t.keywords || [];
        return kws.length
          ? '<div class="tc-kw">' + kws.map(function (k) {
              return '<button class="chip kw" data-kw="' + esc(k) + '">' +
                esc(k) + "</button>"; }).join("") + "</div>"
          : "";
      }()) +
      detailBlock(t, lk.context) +
      (people ? '<div class="tc-people">' + people + "</div>" : "") +
      (links ? '<div class="tc-links"><p class="tc-links-label">' +
        // 본문에 이미 걸린 링크가 있으면, 아래 목록은 '본문이 안 다룬 것'이다.
        ((lk.inline.length || lk.context.length)
          ? "본문에서 다루지 않은 링크"
          : "이 주제에서 함께 공유된 자료") +
        "</p>" + links + more + "</div>" : "") +
      // 관리자에게만 보인다. 잡담 주제를 보다가 그 자리에서 뺄 수 있어야 한다.
      (isAdmin()
        ? '<div class="tc-admin"><button class="btn ghost tc-hide" data-tid="' +
          esc(t.id) + '" data-title="' + esc(t.title) + '">발행 제외</button></div>'
        : "") +
      "</article>";
  }

  function bindPickClear() {
    var b = document.getElementById("pickClear");
    if (b) b.onclick = function () { state.pick = null; render(); };
    var more = document.getElementById("pickMore");
    if (more) {
      more.onclick = function () {
        // 접어 두었던 '스쳐 언급'까지 펼친다. 되돌릴 필요는 없다 — 좁은 쪽으로
        // 다시 가려면 결과물 버튼을 다시 누르면 된다.
        pickThreads(state.pick.moreIds, state.pick.label, "mention");
      };
    }
  }

  function bindThreadCards(scope) {
    // 주제 카드의 태그도 같은 규칙으로 — 태그면 정확히, 아니면 글자 검색.
    bindKeywordChips(scope);
    observeOpenReports(scope);
    Array.prototype.forEach.call(scope.querySelectorAll(".tc-dl"), function (b) {
      b.onclick = function () {
        var tid = b.parentNode.parentNode.getAttribute("data-tid");
        var t = THREADS.filter(function (x) { return x.id === tid; })[0];
        if (t) downloadReport(t);
      };
    });
    Array.prototype.forEach.call(scope.querySelectorAll(".tc-toggle"), function (b) {
      b.onclick = function () {
        var box = b.parentNode.parentNode;
        var on = box.classList.toggle("on");
        var label = b.querySelector(".tc-toggle-label");
        if (label) label.textContent = on ? "보고서 접기" : "보고서 읽기";
        b.setAttribute("aria-expanded", on ? "true" : "false");
        if (on) fillReport(box);
      };
    });
    // 사람 보고서와 **따로** 여닫는다. 둘을 묶으면 AI 보고서만 보려는 사람이
    // 원문 요약을 지나쳐 스크롤해야 한다.
    Array.prototype.forEach.call(scope.querySelectorAll(".tc-ai-toggle"), bindAiToggle);
    Array.prototype.forEach.call(scope.querySelectorAll("[data-nick]"), function (b) {
      b.onclick = function () {
        el.filter.value = b.getAttribute("data-nick");
        state.nick = el.filter.value;
        render();
      };
    });
    Array.prototype.forEach.call(scope.querySelectorAll(".tc-hide"), function (b) {
      b.onclick = function () {
        var tid = b.getAttribute("data-tid"), title = b.getAttribute("data-title");
        confirmAction({
          title: "이 주제를 발행하지 않을까요?",
          description: "'" + title + "'은 오늘 밤 갱신부터 멤버 화면에서 사라집니다.\n" +
            "관리자에게는 운영 원본이 남습니다. 관리 탭에서 다시 발행할 수 있어요.",
          confirmLabel: "발행하지 않기",
        }, function () {
          b.disabled = true;
          b.textContent = "처리 중…";
          state.session.admin.setThreadHidden(tid, title, true).then(
            function () { b.textContent = "제외됨 (오늘 밤 반영)"; },
            function (e) {
              b.disabled = false;
              b.textContent = "발행 제외";
              window.alert("실패: " + (e.message || String(e)));
            }
          );
        });
      };
    });
  }

  /** 스레드 카드로 이동. 원문이 없으므로 메시지가 아니라 주제 단위로 간다. */
  function jumpToTimeline(anchor) {
    // 필터가 남아 있으면 목적지가 걸러져 아무 데도 못 간다. 전부 푼다.
    state.q = ""; state.nick = ""; state.pick = null;
    el.search.value = ""; el.filter.value = "";
    setView("timeline");
    requestAnimationFrame(function () {
      var t = document.getElementById(anchor);
      if (!t) return;
      t.scrollIntoView({ behavior: "smooth", block: "center" });
      /* 화면 밖 카드의 높이는 어림값이다(styles.css 의 content-visibility). 부드럽게
       * 굴러가는 동안 실제 높이가 드러나 목적지가 밀리므로, 멈춘 뒤 한 번 더 맞춘다.
       * 굴러가는 중에 끼어들면 애니메이션과 서로 밀어내므로, 스크롤이 멎은 것을
       * 확인하고서 손을 댄다. */
      var was = -1, tries = 0;
      var settle = setInterval(function () {
        var now = window.scrollY;
        if (++tries > 12) { clearInterval(settle); return; }
        if (now !== was) { was = now; return; }
        clearInterval(settle);
        var r = t.getBoundingClientRect();
        if (r.top < 0 || r.bottom > window.innerHeight) t.scrollIntoView({ block: "center" });
      }, 180);
      t.style.background = "var(--accent-soft)"; t.style.borderRadius = "10px";
      setTimeout(function () { t.style.background = ""; }, 2600);
    });
  }

  /** 사진·첨부 정렬 키. 같은 날 여러 건이라 시각까지 봐야 순서가 맞는다. */
  function mediaKey(m) { return (m.date || "") + " " + (m.time || ""); }

  // ---------- 갤러리 ----------
  function renderGallery() {
    var items = [];
    // 개인정보가 찍혀 발행에서 뺀 사진 수. 갤러리에는 자리표를 수십 개 늘어놓지
    // 않고(그 자체가 소음이다) 머리에 한 줄로 알린다 — 숫자가 안 맞는 이유는
    // 어딘가에 적혀 있어야 한다.
    var hiddenShots = 0;
    MEDIA.forEach(function (m) {
      if (state.nick && m.nickname !== state.nick) return;
      // 동영상도 갤러리에 있다(2026-07-27 부터 수집). 칸에는 포스터를 걸고,
      // 누를 때 원본을 받는다 — 목록만 훑어도 15MB 씩 빠지면 안 된다.
      hiddenShots += m.pii_hidden || 0;
      var srcs = m.kind === "video" ? m.videos : m.images;
      if (!srcs || !srcs.length) return;
      var th = m.thumbs || [];
      srcs.forEach(function (src, i) {
        items.push({ src: th[i] || src, full: src, nick: m.nickname,
                     date: m.date, time: m.time, tid: m.thread_id,
                     video: m.kind === "video" });
      });
    });
    if (!items.length) {
      el.view.innerHTML = emptyState("gallery", "아직 모아 둔 사진이 없어요",
        "대화 속 사진이 보관되면 날짜와 사람별로 이곳에 차곡차곡 나타납니다.");
      return;
    }
    // 최근 것부터. 어제 무엇이 올라왔는지가 가장 궁금하다.
    items.sort(function (a, b) { return mediaKey(b).localeCompare(mediaKey(a)); });
    var list = state.gview === "list";
    var html = ['<div class="gal-head">',
      '<p class="room-sub">보관된 사진 ' + items.length + "장" +
        (hiddenShots ? ' <span class="gal-hidden">🔒 개인정보가 있어 감춘 사진 ' +
          hiddenShots + "장은 빠져 있습니다</span>" : "") + "</p>",
      '<div class="gal-modes">',
      '<button class="gal-mode' + (list ? "" : " on") + '" data-gview="grid" title="바둑판">▦ 그리드</button>',
      '<button class="gal-mode' + (list ? " on" : "") + '" data-gview="list" title="목록">☰ 리스트</button>',
      "</div></div>",
      '<div class="gallery' + (list ? " as-list" : "") + '">'];
    items.forEach(function (it) {
      html.push('<figure' + (it.video ? ' class="is-video"' : "") +
        ' data-jump="t-' + esc(it.tid || "") + '"><img data-img="' + esc(it.src) +
        '" data-full="' + esc(it.full || it.src) + '"' +
        (it.video ? ' data-video="1"' : "") +
        ' alt="" />' + (it.video ? '<span class="play">▶</span>' : "") +
        '<figcaption>' + esc(it.date) + " · " + esc(it.nick) + "</figcaption></figure>");
    });
    html.push("</div>");
    el.view.innerHTML = html.join("");
    Array.prototype.forEach.call(el.view.querySelectorAll(".gal-mode"), function (b) {
      b.onclick = function () {
        state.gview = b.getAttribute("data-gview");
        try { localStorage.setItem("gallery-view", state.gview); } catch (e) { /* 무시 */ }
        renderGallery();
      };
    });
    Array.prototype.forEach.call(el.view.querySelectorAll("figure"), function (fig) {
      fig.querySelector("img").onclick = function () { openLightbox(this); };
      fig.querySelector("figcaption").onclick = function () { jumpToTimeline(fig.getAttribute("data-jump")); };
    });
    bindImages(el.view);
    bindFiles(el.view);
  }

  /* ---------- 첨부 파일 ----------
   *
   * 원본을 못 구한 것도 함께 보여준다. 목록에서 빠뜨리면 "누가 무엇을 올렸는데
   * 지금은 없다"는 사실 자체가 사라져, 다시 구해달라고 부탁할 근거도 없어진다.
   */
  var FILE_ICONS = {
    pdf: "📕", zip: "🗜", docx: "📘", xlsx: "📗", pptx: "📙",
    html: "🌐", md: "📝", txt: "📝", hwp: "📄", hwpx: "📄",
  };
  function fileIcon(name) {
    var ext = (name.split(".").pop() || "").toLowerCase();
    return FILE_ICONS[ext] || "📄";
  }

  function renderFiles() {
    var rows = MEDIA.filter(function (m) { return m.kind === "file"; });
    if (!rows.length) {
      el.view.innerHTML = emptyState("files", "아직 보관된 파일이 없어요",
        "대화에서 나눈 문서와 자료가 생기면 잊지 않도록 이곳에 모아 둡니다.");
      return;
    }
    var have = rows.filter(function (m) { return m.file; });
    // 못 구한 것을 '만료' 와 '수집 대기' 로 갈라 센다. 뭉뚱그리면 남은 일이 얼마인지
    // 알 수 없다 — 만료는 아무리 기다려도 줄지 않는다.
    var gone = rows.filter(function (m) { return !m.file && m.file_expired; });
    var q = state.q.toLowerCase();
    var shown = rows.filter(function (m) {
      if (state.nick && m.nickname !== state.nick) return false;
      if (!q) return true;
      var name = m.file ? m.file.name : (m.text || "");
      return (name + " " + m.nickname + " " + m.date).toLowerCase().indexOf(q) !== -1;
    });
    // 최근 첨부부터
    shown.sort(function (a, b) { return mediaKey(b).localeCompare(mediaKey(a)); });

    var html = ['<p class="room-sub" style="margin:0 0 12px">공유된 파일 ' + rows.length +
      "개 · 원본 보관 " + have.length + "개" +
      (gone.length ? " · 만료 " + gone.length + "개" : "") +
      (shown.length !== rows.length ? " · 표시 " + shown.length + "개" : "") + "</p>"];

    if (!shown.length) {
      html.push(emptyState("search", "조건에 맞는 파일을 찾지 못했어요",
        "검색어를 줄이거나 참여자 필터를 비우고 다시 살펴보세요."));
    } else {
      html.push('<div class="files">');
      shown.forEach(function (m) {
        var name = m.file ? m.file.name : (m.name || "");
        html.push(
          '<div class="file-card' + (m.file ? "" : " no-src") + '">' +
          '<span class="fc-icon">' + fileIcon(name) + "</span>" +
          '<div class="fc-body">' +
          '<div class="fc-name" title="' + esc(name) + '">' + esc(name) + "</div>" +
          '<div class="fc-meta">' + esc(m.nickname) + " · " + esc(m.date) +
          (m.file ? " · " + fmtSize(m.file.size) : "") + "</div></div>" +
          '<div class="fc-act">' +
          (m.file
            ? '<button class="btn ghost fc-dl" data-file="' + esc(m.file.path) +
              '" data-name="' + esc(m.file.name) + '">받기</button>'
            : m.file_expired
              ? '<span class="fc-gone" title="카톡이 파일을 14일만 보관해 서랍에서 사라졌습니다">만료됨</span>'
              : '<span class="fc-none" title="아직 받지 못했습니다 — 밤마다 다시 받아 옵니다">수집 대기</span>') +
          '<button class="btn ghost fc-jump" data-jump="t-' + esc(m.thread_id || "") + '">주제</button>' +
          "</div></div>"
        );
      });
      html.push("</div>");
      // 지금 화면에 없는 딱지는 설명하지 않는다. '수집 대기' 가 0건인 날에 그 말을
      // 풀이하면 읽는 사람이 없는 것을 찾는다.
      var pending = rows.length - have.length - gone.length;
      if (have.length < rows.length) {
        var note = [];
        if (pending) {
          note.push("‘수집 대기’는 아직 받지 못한 것입니다 — 밤마다 자동으로 다시 받아 옵니다.");
        }
        if (gone.length) {
          note.push("‘만료됨’은 카톡이 파일을 14일만 보관해 서랍에서 사라진 것이라 " +
            "자동으로는 채워지지 않습니다. 가지고 계신 분이 관리자에게 보내주시면 연결됩니다.");
        }
        html.push('<p class="hint" style="margin-top:14px">' + note.join(" ") + "</p>");
      }
    }

    el.view.innerHTML = html.join("");
    Array.prototype.forEach.call(el.view.querySelectorAll(".fc-jump"), function (b) {
      b.onclick = function () { jumpToTimeline(b.getAttribute("data-jump")); };
    });
    bindFiles(el.view);
  }

  // ---------- 통계 → web/stats.js ----------
  // 데이터 전역은 init() 에서 다시 읽히므로 값이 아니라 읽는 함수를 준다.
  function appData() {
    return { A: A, THREADS: THREADS, MEDIA: MEDIA, STATS: STATS, KNOW: KNOW, CAT_LABEL: CAT_LABEL };
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


  function bindFiles(scope) {
    Array.prototype.forEach.call(scope.querySelectorAll("[data-file]"), function (b) {
      b.onclick = function () {
        var fpath = b.getAttribute("data-file"), name = b.getAttribute("data-name");
        var label = b.innerHTML;
        // 80MB 짜리도 있어 몇 초씩 걸린다. 아무 반응이 없으면 고장으로 보인다.
        b.disabled = true;
        b.innerHTML = "📎 내려받는 중…";
        window.ArchiveImages.download(fpath, name).then(
          function () { b.disabled = false; b.innerHTML = label; },
          function (e) {
            b.disabled = false;
            b.innerHTML = label;
            window.alert("내려받지 못했습니다: " + (e && e.message ? e.message : e));
          }
        );
      };
    });
  }

  function bindImages(scope) {
    Array.prototype.forEach.call(scope.querySelectorAll(".imgs img"), function (img) {
      img.onclick = function () { openLightbox(img); };
    });
    // 보호모드에서는 화면에 들어올 때 인증 요청으로 받아온다
    if (window.ArchiveImages) window.ArchiveImages.observe(scope);
  }
  function openLightbox(img) {
    // 크게 볼 때는 원본이어야 한다. 화면의 칸에 걸린 것은 갤러리용 작은 사진이라
    // 그 blob 을 그대로 띄우면 흐리게 보인다. data-full 이 원본 경로다.
    var full = img.getAttribute("data-full");
    var path = img.getAttribute("data-img");

    // 동영상은 여기서 비로소 원본을 받는다. 갤러리에서는 포스터만 걸려 있었다.
    if (img.getAttribute("data-video") && full && window.ArchiveImages) {
      el.lightboxImg.style.display = "none";
      var v = ensureLightboxVideo();
      /* `""` 로 두면 안 된다 — 인라인 스타일이 사라져 CSS 의 기본값
       * `#lightboxVideo { display: none }` 이 다시 이긴다. 그러면 요소는 숨은 채
       * 재생돼 **소리는 나고 화면은 안 보인다**(2026-07-28 실측). */
      v.style.display = "block";
      v.removeAttribute("src");
      v.poster = img.src || "";
      el.lightbox.classList.add("on");
      window.ArchiveImages.urlFor(full).then(function (u) {
        v.src = u;
        v.play().catch(function () { /* 자동재생을 막는 브라우저는 눌러서 본다 */ });
      });
      return;
    }
    el.lightboxImg.style.display = "";
    var vv = document.getElementById("lightboxVideo");
    if (vv) { vv.pause(); vv.removeAttribute("src"); vv.style.display = "none"; }

    if (full && window.ArchiveImages) {
      // 원본이 뜨기 전까지는 작은 사진을 보여 준다 — 빈 화면보다 낫다
      if (img.src) el.lightboxImg.src = img.src;
      window.ArchiveImages.urlFor(full).then(function (u) { el.lightboxImg.src = u; });
    } else if (img.src) {
      el.lightboxImg.src = img.src;
    } else if (path && window.ArchiveImages) {
      window.ArchiveImages.urlFor(path).then(function (u) { el.lightboxImg.src = u; });
    }
    el.lightbox.classList.add("on");
  }
  /** 라이트박스에 동영상 자리를 만든다(처음 필요할 때 한 번). */
  function ensureLightboxVideo() {
    var v = document.getElementById("lightboxVideo");
    if (v) return v;
    v = document.createElement("video");
    v.id = "lightboxVideo";
    v.controls = true;
    v.playsInline = true;
    v.preload = "none";
    el.lightboxImg.parentNode.insertBefore(v, el.lightboxImg.nextSibling);
    return v;
  }
  function closeLightbox() {
    el.lightbox.classList.remove("on");
    el.lightboxImg.src = "";
    // 닫을 때 src 를 비우지 않으면 동영상이 뒤에서 계속 내려온다
    var v = document.getElementById("lightboxVideo");
    if (v) { v.pause(); v.removeAttribute("src"); v.load(); }
  }

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
