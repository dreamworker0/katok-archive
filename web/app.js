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
                mine: null, admin: null, gview: "grid", tsort: "desc", pick: null };
  try {
    var savedG = localStorage.getItem("gallery-view");
    if (savedG === "list" || savedG === "grid") state.gview = savedG;
    var savedS = localStorage.getItem("thread-sort");
    if (savedS === "asc" || savedS === "desc") state.tsort = savedS;
  } catch (e) { /* 프라이빗 모드 등 — 기본값으로 간다 */ }

  // ---------- 유틸 ----------
  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  var URL_RE = /(https?:\/\/[^\s]+)/g;
  function linkify(escaped) {
    return escaped.replace(URL_RE, function (u) {
      return '<a href="' + u + '" target="_blank" rel="noopener noreferrer">' + u + "</a>";
    });
  }
  function highlightText(html, q) {
    if (!q) return html;
    var parts = html.split(/(<[^>]+>)/);
    var re = new RegExp("(" + q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "ig");
    for (var i = 0; i < parts.length; i++) {
      if (parts[i] && parts[i][0] !== "<") parts[i] = parts[i].replace(re, "<mark>$1</mark>");
    }
    return parts.join("");
  }
  function hashHue(s) { var h = 0; for (var i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 360; return h; }
  function avatarStyle(n) { return "background:hsl(" + hashHue(n) + ",42%,50%)"; }
  function initial(n) { var x = (n || "?").replace(/\s*\(.*\)\s*$/, "").trim(); return x ? x.charAt(0) : "?"; }
  function fmtSize(bytes) {
    if (!bytes) return "";
    if (bytes < 1024 * 1024) return Math.max(1, Math.round(bytes / 1024)) + " KB";
    return (bytes / 1024 / 1024).toFixed(1) + " MB";
  }
  var WD = ["일", "월", "화", "수", "목", "금", "토"];
  function fmtDate(d) {
    var p = d.split("-"), dt = new Date(+p[0], +p[1] - 1, +p[2]);
    return p[0] + "년 " + (+p[1]) + "월 " + (+p[2]) + "일 (" + WD[dt.getDay()] + ")";
  }

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
      html.push('<button data-goto="doc-' + c.id + '"><span class="swatch" style="background:' +
        colorFor(c.id) + '"></span>' + esc(c.label) + " · " + (d.message_count || 0) + "</button>");
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
      b.onclick = function () {
        var t = document.getElementById(b.getAttribute("data-goto"));
        if (t) t.scrollIntoView({ behavior: "smooth", block: "start" });
      };
    });
    bindDocActions(el.view);
  }

  function renderDoc(cid, d) {
    var col = colorFor(cid);
    var apps = (d.apps || []).map(function (a) {
      var ids = (a.thread_ids || []).join(",");
      return '<button class="app-item" data-pick="' + esc(ids) + '" data-label="' +
        esc(a.label) + '" data-q="' + esc(a.query || a.label) + '">' +
        '<span class="an">' + esc(a.label) + "</span>" +
        (a.maker ? '<span class="am">' + esc(a.maker) + "</span>" : "") +
        (a.thread_ids && a.thread_ids.length
          ? '<span class="an-n">주제 ' + a.thread_ids.length + "개</span>" : "") +
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
    var kw = (d.keywords || []).map(function (k) { return '<span class="chip">' + esc(k) + "</span>"; }).join("");
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

    return '<article class="doc" id="doc-' + cid + '" style="--c:' + col + '">' +
      '<div class="doc-head"><span class="doc-bar"></span>' +
      '<h2 class="doc-title">' + esc(d.label) + "</h2>" +
      '<span class="doc-meta">' + (d.message_count || 0) + "개 메시지 · " + (d.threads || []).length + "개 주제</span></div>" +
      (d.headline ? '<p class="doc-headline">' + esc(d.headline) + "</p>" : "") +
      '<p class="doc-overview">' + esc(d.overview || "") + "</p>" +
      (kw ? '<div class="doc-kw">' + kw + "</div>" : "") +
      (apps ? '<div class="doc-section"><h4>🧩 주요 결과물</h4><div class="app-list">' + apps + "</div></div>" : "") +
      (people ? '<div class="doc-section"><h4>👥 활발한 참여자</h4><div class="people-row">' + people + "</div></div>" : "") +
      (linkHtml ? '<div class="doc-section"><h4>🔗 공유 링크</h4><div class="link-list">' + linkHtml + "</div></div>" : "") +
      (threads ? '<div class="doc-section thread-list"><h4>🧵 소속 대화 주제 ' + threadList.length +
        "개</h4>" + threads + "</div>" : "") +
      "</article>";
  }

  function bindDocActions(scope) {
    Array.prototype.forEach.call(scope.querySelectorAll(".app-item"), function (b) {
      b.onclick = function () {
        // 예전에는 결과물 이름으로 원문을 검색했는데, 원문 발행을 멈추면서
        // 검색 대상이 사라져 빈 목록으로 갔다. 지금은 빌드 때 이어 둔 주제로
        // 바로 간다. 이어진 주제가 없을 때만 옛 방식으로 물러선다.
        var ids = (b.getAttribute("data-pick") || "").split(",").filter(Boolean);
        if (ids.length) pickThreads(ids, b.getAttribute("data-label"));
        else runSearch(b.getAttribute("data-q"));
      };
    });
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
      onSelect: function (node) {
        if (!node) { panel.classList.remove("on"); return; }
        fillNodePanel(node);
        panel.classList.add("on");
      },
    });
  }

  function fillNodePanel(node) {
    var body = document.getElementById("npBody");
    var typeMap = { topic: "주제", app: "앱·결과물", tool: "도구·기술", person: "사람" };
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
    body.innerHTML = '<h4>' + esc(node.label) + "</h4>" +
      '<div class="np-type">' + typeMap[node.type] + "</div>" + rows +
      '<div class="np-actions">' + actions + "</div>";
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
      var hay = (t.title + " " + t.summary + " " + (t.report || "") + " " +
                 (t.keywords || []).join(" ") + " " + (t.participants || []).join(" ") +
                 " " + t.start_date + " " + (t.links || []).map(function (l) {
                   return l.url; }).join(" ")).toLowerCase();
      if (hay.indexOf(q) === -1) return false;
    }
    return true;
  }

  /** 결과물 하나에 딸린 주제만 추린다. 검색어가 아니라 ID 로 고르므로
   *  보고서를 어떻게 고쳐 쓰든 결과가 흔들리지 않는다. */
  function pickThreads(ids, label) {
    state.pick = { ids: ids, label: label };
    state.q = ""; state.nick = "";
    el.search.value = ""; el.filter.value = "";
    setView("timeline");
  }

  /** 주제 정렬 키 — 같은 날 주제가 여럿이라 시각까지 봐야 순서가 맞는다. */
  function threadKey(t) {
    return (t.start_date || "") + " " + (t.start_time || "");
  }

  function renderTimeline() {
    var rows = THREADS.filter(threadMatches);
    var pickBar = state.pick
      ? '<div class="pick-bar">🧩 <b>' + esc(state.pick.label) + "</b> 이(가) 나온 주제 " +
        rows.length + '개만 보고 있습니다 <button class="btn ghost" id="pickClear">' +
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

  /* ---------- 마크다운 ----------
   *
   * 보고서 원본이 .md 라서 화면에서도 마크다운을 그린다. 라이브러리를 쓰지
   * 않는 이유는 두 가지다. 필요한 문법이 소제목·목록·표·인용·강조뿐이고,
   * 무엇보다 남이 쓴 파서에 원문을 통과시키면 어디서 HTML 이 새는지 알기
   * 어렵다. 여기서는 **가장 먼저 전부 이스케이프**하고 그 위에 규칙을
   * 얹으므로, 본문에 <script> 가 들어 있어도 글자로만 나온다.
   */
  function mdInline(s) {
    var h = esc(s);
    h = h.replace(/`([^`]+)`/g, '<code>$1</code>');
    h = h.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    h = h.replace(/==([^=]+)==/g, '<mark class="key">$1</mark>');
    // 링크는 http/https 만 통과시킨다. javascript: 를 막기 위함이다.
    h = h.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
    return h;
  }

  function mdRow(line) {
    var cells = line.replace(/^\||\|$/g, "").split("|");
    return cells.map(function (c) { return c.trim(); });
  }

  /* 본문에 이미 적힌 주소를 링크로 만든다.
   *
   * 보고서를 쓰다 보면 "urimal.vercel.app 을 공개했다"처럼 주소를 글 안에
   * 적게 된다. 그런데 같은 링크가 카드 아래 목록에도 또 나와서 두 번 보였다.
   * ==내용 중에 나오면 내용 중에 넣는 것이 낫다== — 본문에서 링크로 걸고
   * 아래 목록에서는 뺀다.
   *
   * 이미 <a> 나 <code> 안에 있는 글자는 건드리지 않는다. 태그 경계를 세어
   * 판단하므로 링크 안의 링크나 코드 속 주소가 깨지지 않는다.
   */
  function linkifyHosts(html, map) {
    if (!map || !map.length) return html;
    var parts = html.split(/(<[^>]+>)/);
    var depth = 0;
    for (var i = 0; i < parts.length; i++) {
      var p = parts[i];
      if (!p) continue;
      if (p[0] === "<") {
        if (/^<(a|code)\b/i.test(p)) depth++;
        else if (/^<\/(a|code)>/i.test(p)) depth = Math.max(0, depth - 1);
        continue;
      }
      if (depth) continue;
      map.forEach(function (m) {
        if (p.indexOf(m.host) === -1) return;
        p = p.split(m.host).join(
          '<a href="' + esc(m.url) + '" target="_blank" rel="noopener noreferrer">' +
          esc(m.host) + "</a>");
      });
      parts[i] = p;
    }
    return parts.join("");
  }

  /** 링크의 호스트. www 는 떼어 본문 표기와 맞춘다. */
  function hostOf(url) {
    var m = /^https?:\/\/([^/?#]+)/.exec(String(url || ""));
    return m ? m[1].replace(/^www\./, "") : "";
  }

  /** 본문에 주소가 적힌 링크와 그렇지 않은 링크로 가른다. */
  function splitLinks(t) {
    var rep = t.report || "", inline = [], context = [], rest = [], seen = {};
    var contextIds = {};
    rep.replace(/^!\[\[link:([A-Za-z0-9_-]+)\]\]\s*$/gm, function (all, id) {
      contextIds[id] = 1;
      return all;
    });
    (t.links || []).forEach(function (l) {
      if (l.id && contextIds[l.id]) {
        context.push(l);
        return;
      }
      var h = hostOf(l.url);
      if (h && rep.indexOf(h) !== -1 && !seen[h]) {
        seen[h] = 1;
        inline.push({ host: h, url: l.url });
      } else {
        rest.push(l);
      }
    });
    // 긴 호스트를 먼저 바꿔야 짧은 것이 긴 것 안을 잘라먹지 않는다
    inline.sort(function (a, b) { return b.host.length - a.host.length; });
    return { inline: inline, context: context, rest: rest };
  }

  function renderMarkdown(src) {
    var lines = String(src || "").replace(/\r\n/g, "\n").split("\n");
    var out = [], i = 0;
    function flushPara(buf) {
      if (buf.length) out.push("<p>" + mdInline(buf.join(" ")) + "</p>");
      buf.length = 0;
    }
    var para = [];
    while (i < lines.length) {
      var ln = lines[i];

      if (!ln.trim()) { flushPara(para); i++; continue; }

      var linkAnchor = /^!\[\[link:([A-Za-z0-9_-]+)\]\]$/.exec(ln.trim());
      if (linkAnchor) {
        flushPara(para);
        out.push('<div class="md-link-anchor" data-link-anchor="' +
          esc(linkAnchor[1]) + '"></div>');
        i++; continue;
      }

      /* 사진·첨부 자리표 — `![[msg-000123]]` 한 줄.
       *
       * 보고서 끝에 사진을 몰아 두면 "무슨 얘기 중에 올라온 것"인지가 사라진다.
       * 본문을 쓸 때 그 대목 뒤에 자리표를 남겨 두면, 화면이 media 발행본에서
       * 같은 message id 를 찾아 그 자리에 끼운다. 사람이 두 군데를 맞춰 적는
       * 것이 아니라 자리만 가리키므로 어긋날 여지가 없다. */
      var an = /^!\[\[\s*([A-Za-z0-9_-]+)\s*\]\]$/.exec(ln.trim());
      if (an) {
        flushPara(para);
        out.push('<div class="md-anchor" data-anchor="' + esc(an[1]) + '"></div>');
        i++; continue;
      }

      var h = /^(#{1,6})\s+(.*)$/.exec(ln);
      if (h) {
        flushPara(para);
        var lv = Math.min(6, h[1].length + 2);   // ## → h4, 카드 안이므로 낮춘다
        out.push("<h" + lv + ">" + mdInline(h[2]) + "</h" + lv + ">");
        i++; continue;
      }

      if (/^(---|\*\*\*)\s*$/.test(ln)) { flushPara(para); out.push("<hr />"); i++; continue; }

      // 표 — 두 번째 줄이 구분선이어야 표로 본다
      if (ln.indexOf("|") !== -1 && /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(lines[i + 1] || "")) {
        flushPara(para);
        var head = mdRow(ln), body = [];
        i += 2;
        while (i < lines.length && lines[i].indexOf("|") !== -1 && lines[i].trim()) {
          body.push(mdRow(lines[i])); i++;
        }
        out.push('<div class="md-table"><table><thead><tr>' +
          head.map(function (c) { return "<th>" + mdInline(c) + "</th>"; }).join("") +
          "</tr></thead><tbody>" +
          body.map(function (r) {
            return "<tr>" + r.map(function (c) {
              return "<td>" + mdInline(c) + "</td>"; }).join("") + "</tr>";
          }).join("") + "</tbody></table></div>");
        continue;
      }

      var b = /^\s*([-*]|\d+\.)\s+(.*)$/.exec(ln);
      if (b) {
        flushPara(para);
        var ordered = /\d/.test(b[1]), items = [];
        while (i < lines.length) {
          var m2 = /^\s*([-*]|\d+\.)\s+(.*)$/.exec(lines[i]);
          if (!m2) break;
          items.push("<li>" + mdInline(m2[2]) + "</li>");
          i++;
        }
        out.push((ordered ? "<ol>" : "<ul>") + items.join("") + (ordered ? "</ol>" : "</ul>"));
        continue;
      }

      if (/^>\s?/.test(ln)) {
        flushPara(para);
        var q = [];
        while (i < lines.length && /^>\s?/.test(lines[i])) {
          q.push(lines[i].replace(/^>\s?/, "")); i++;
        }
        out.push("<blockquote>" + mdInline(q.join(" ")) + "</blockquote>");
        continue;
      }

      para.push(ln.trim());
      i++;
    }
    flushPara(para);
    return out.join("");
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

  function detailBlock(t, inlineLinks, contextualLinks) {
    if (!t.report) return "";
    var open = !!state.q;
    var n = mediaOf(t.id).length;
    var hasResources = n || contextualLinks.length;
    return '<div class="tc-detail' + (open ? " on" : "") + '" data-tid="' + esc(t.id) + '">' +
      '<div class="tc-detail-bar">' +
      '<button class="tc-toggle" type="button" aria-expanded="' + (open ? "true" : "false") + '">' +
      reportToggleIcon() + '<span class="tc-toggle-label">' +
      (open ? "보고서 접기" : "보고서 읽기") + "</span></button>" +
      '<button class="tc-dl" type="button" title="이 보고서를 .md 파일로 저장합니다">' +
      "⬇ .md</button></div>" +
      '<div class="tc-detail-body md">' +
      highlightText(linkifyHosts(renderMarkdown(t.report), inlineLinks), state.q) +
      (hasResources ? '<div class="tc-media" data-media="' + esc(t.id) + '"></div>' : "") +
      "</div></div>";
  }

  /** 이 주제에서 오간 사진·첨부. 보고서에 손으로 적지 않고 여기서 찾는다. */
  function mediaOf(tid) {
    return MEDIA.filter(function (m) { return m.thread_id === tid; });
  }

  /** 사진·첨부 한 묶음을 그린다. 본문 사이(inline)든 보고서 끝이든 모양은 같다. */
  function mediaHtml(rows, inline) {
    var imgs = [], files = [];
    rows.forEach(function (m) {
      if (m.kind === "image" && m.images) {
        m.images.forEach(function (src) {
          imgs.push('<img data-img="' + esc(src) + '" alt="" title="' +
            esc(m.nickname + " · " + m.date) + '" />');
        });
      } else if (m.kind === "file") {
        var nm = m.file ? m.file.name : (m.name || "");
        files.push('<div class="tcf">' + fileIcon(nm) +
          ' <span class="tcf-n">' + esc(nm) + "</span>" +
          '<span class="tcf-m">' + esc(m.nickname) + " · " + esc(m.date) + "</span>" +
          (m.file
            ? '<button class="btn ghost" data-file="' + esc(m.file.path) +
              '" data-name="' + esc(m.file.name) + '">받기</button>'
            : '<span class="fc-none">원본 없음</span>') + "</div>");
      }
    });
    var cap = "";
    if (inline && imgs.length) {
      var m0 = rows[0];
      cap = '<div class="mi-cap">🖼 ' + esc(m0.nickname) + " · " + esc(m0.date) +
        " " + esc(m0.time || "") + (imgs.length > 1 ? " · " + imgs.length + "장" : "") + "</div>";
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

    host.innerHTML = rest.length
      ? "<h4>이 주제에서 함께 공유된 자료</h4>" + mediaHtml(rest, false)
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
      ((t.keywords || []).length
        ? '<div class="tc-kw">' + t.keywords.map(function (k) {
            return '<button class="chip kw" data-kw="' + esc(k) + '">' +
              esc(k) + "</button>"; }).join("") + "</div>"
        : "") +
      detailBlock(t, lk.inline, lk.context) +
      (people ? '<div class="tc-people">' + people + "</div>" : "") +
      (links ? '<div class="tc-links"><p class="tc-links-label">' +
        "이 주제에서 함께 공유된 자료</p>" + links + more + "</div>" : "") +
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
  }

  function bindThreadCards(scope) {
    Array.prototype.forEach.call(scope.querySelectorAll(".kw"), function (b) {
      b.onclick = function () { runSearch(b.getAttribute("data-kw")); };
    });
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
        if (on) fillMedia(box);
      };
    });
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
      if (t) {
        t.scrollIntoView({ behavior: "smooth", block: "center" });
        t.style.background = "var(--accent-soft)"; t.style.borderRadius = "10px";
        setTimeout(function () { t.style.background = ""; }, 2600);
      }
    });
  }

  /** 사진·첨부 정렬 키. 같은 날 여러 건이라 시각까지 봐야 순서가 맞는다. */
  function mediaKey(m) { return (m.date || "") + " " + (m.time || ""); }

  // ---------- 갤러리 ----------
  function renderGallery() {
    var items = [];
    MEDIA.forEach(function (m) {
      if (m.kind !== "image" || !m.images || !m.images.length) return;
      if (state.nick && m.nickname !== state.nick) return;
      m.images.forEach(function (src) {
        items.push({ src: src, nick: m.nickname, date: m.date, time: m.time,
                     tid: m.thread_id });
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
      '<p class="room-sub">보관된 사진 ' + items.length + "장</p>",
      '<div class="gal-modes">',
      '<button class="gal-mode' + (list ? "" : " on") + '" data-gview="grid" title="바둑판">▦ 그리드</button>',
      '<button class="gal-mode' + (list ? " on" : "") + '" data-gview="list" title="목록">☰ 리스트</button>',
      "</div></div>",
      '<div class="gallery' + (list ? " as-list" : "") + '">'];
    items.forEach(function (it) {
      html.push('<figure data-jump="t-' + esc(it.tid || "") + '"><img data-img="' + esc(it.src) +
        '" alt="" /><figcaption>' + esc(it.date) + " · " + esc(it.nick) + "</figcaption></figure>");
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
            : '<span class="fc-none" title="원본을 구하지 못했습니다">원본 없음</span>') +
          '<button class="btn ghost fc-jump" data-jump="t-' + esc(m.thread_id || "") + '">주제</button>' +
          "</div></div>"
        );
      });
      html.push("</div>");
      if (have.length < rows.length) {
        html.push('<p class="hint" style="margin-top:14px">' +
          "‘원본 없음’은 카톡 내보내기에 파일이 들어 있지 않아 이름만 남은 것입니다. " +
          "가지고 계신 분이 관리자에게 보내주시면 연결됩니다.</p>");
      }
    }

    el.view.innerHTML = html.join("");
    Array.prototype.forEach.call(el.view.querySelectorAll(".fc-jump"), function (b) {
      b.onclick = function () { jumpToTimeline(b.getAttribute("data-jump")); };
    });
    bindFiles(el.view);
  }

  // ---------- 통계 ----------
  function bar(label, value, max, color) {
    var pct = max ? Math.round((value / max) * 100) : 0;
    return '<div class="bar-row"><span class="lab">' + esc(label) + '</span><span class="track">' +
      '<span class="fill" style="width:' + pct + "%" + (color ? ";--c:" + color : "") + '"></span></span>' +
      '<span class="val">' + value + "</span></div>";
  }
  function card(v, k) { return '<div class="stat-card"><div class="v">' + (v == null ? "-" : v) + '</div><div class="k">' + esc(k) + "</div></div>"; }
  /* ---------- 나의 기록 ----------
   *
   * 로그인한 본인이 이 방에 무엇을 남겼는지 정리해 보여 준다. 남의 것은
   * 보이지 않는다 — 참여자별 순위표를 없앤 것과 같은 이유다. 서로를 줄 세우면
   * 적게 쓴 사람이 위축된다. 대신 각자 자기 발자취를 본다.
   *
   * 발행본(threads·media)만으로 계산한다. 별도 조회가 없어 빠르고, 본인 원문을
   * 불러오지 않으므로 통계 탭에서 원문이 오갈 일도 없다.
   */
  function myFootprint() {
    var names = myNicknames();
    if (!names.length) return null;
    var mine = function (n) { return names.indexOf(n) !== -1; };

    var joined = THREADS.filter(function (t) {
      return (t.participants || []).some(mine);
    });
    if (!joined.length) return null;

    var byCat = {}, mates = {}, first = null, last = null;
    joined.forEach(function (t) {
      byCat[t.category] = (byCat[t.category] || 0) + 1;
      (t.participants || []).forEach(function (p) { if (!mine(p)) mates[p] = 1; });
      if (!first || t.start_date < first) first = t.start_date;
      if (!last || t.end_date > last) last = t.end_date;
    });
    var cats = Object.keys(byCat)
      .map(function (c) { return { id: c, label: CAT_LABEL[c] || c, n: byCat[c] }; })
      .sort(function (a, b) { return b.n - a.n; });

    var links = 0;
    THREADS.forEach(function (t) {
      (t.links || []).forEach(function (l) { if (mine(l.nickname)) links++; });
    });
    var photos = 0, files = 0;
    MEDIA.forEach(function (m) {
      if (!mine(m.nickname)) return;
      if (m.kind === "image") photos += (m.images ? m.images.length : m.count || 1);
      else files++;
    });

    var msgs = 0;
    (STATS.participants || []).forEach(function (p) {
      if (mine(p.nickname)) msgs += p.message_count;
    });

    return { names: names, msgs: msgs, joined: joined.length, total: THREADS.length,
             cats: cats, mates: Object.keys(mates).length,
             links: links, photos: photos, files: files, first: first, last: last };
  }

  /** 숫자에서 읽히는 것만 적는다. 근거 없는 칭찬은 넣지 않는다. */
  function myHighlights(f) {
    var out = [];
    var share = f.joined / Math.max(1, f.total);
    if (share >= 0.5) {
      out.push("이 방의 주제 <b>절반 이상</b>에 함께하셨습니다. 오간 이야기의 큰 줄기를 " +
        "곁에서 지켜본 셈입니다.");
    } else if (share >= 0.2) {
      out.push("전체 주제의 <b>" + Math.round(share * 100) + "%</b>에 함께하셨습니다.");
    }
    if (f.cats.length >= 5) {
      out.push("<b>" + f.cats.length + "개 분야</b>에 걸쳐 이야기하셨습니다. 한쪽에 머물지 " +
        "않고 폭넓게 오가셨습니다.");
    } else if (f.cats.length) {
      out.push("<b>" + f.cats[0].label + "</b>을(를) 중심으로 이야기하셨습니다.");
    }
    if (f.links >= 10) {
      out.push("자료 링크를 <b>" + f.links + "건</b> 나누셨습니다. 혼자 찾은 것을 " +
        "그때그때 꺼내 놓으신 기록입니다.");
    }
    if (f.photos + f.files >= 10) {
      out.push("사진과 파일을 <b>" + (f.photos + f.files) + "개</b> 올리셨습니다. " +
        "말로만 하지 않고 결과물을 보여 주셨습니다.");
    }
    if (f.mates >= 10) {
      out.push("<b>" + f.mates + "명</b>과 같은 자리에서 이야기하셨습니다.");
    }
    if (!out.length) {
      out.push("남기신 것이 이 방의 기록에 함께 담겨 있습니다.");
    }
    return out;
  }

  function myReport() {
    var f = myFootprint();
    if (!f) return "";
    var top = f.cats.slice(0, 4).map(function (c) {
      return '<span class="chip dot" style="--c:' + colorFor(c.id) + '">' +
        esc(c.label) + " " + c.n + "</span>";
    }).join("");
    return '<div class="panel mypanel">' +
      "<h3>나의 기록 — " + esc(f.names.join(", ")) + "</h3>" +
      '<p class="my-lead">' + esc(f.first) + " 부터 " + esc(f.last) + " 까지, " +
      "<b>" + f.joined + "개 주제</b>에 함께하며 <b>" + f.msgs + "건</b>을 남기셨습니다.</p>" +
      '<div class="my-nums">' +
      numCell(f.joined + " / " + f.total, "함께한 주제") +
      numCell(f.msgs, "남긴 메시지") +
      numCell(f.links, "나눈 링크") +
      numCell(f.photos, "올린 사진") +
      numCell(f.files, "올린 파일") +
      numCell(f.mates, "함께한 사람") +
      "</div>" +
      (top ? '<div class="my-cats">' + top + "</div>" : "") +
      "<ul class='my-notes'>" +
      myHighlights(f).map(function (s) { return "<li>" + s + "</li>"; }).join("") +
      "</ul>" +
      /* 성향·관심 이야기는 본인 원문이 있어야 쓸 수 있다. 통계 탭에서 원문을
         부르지 않는다는 원칙은 그대로 두고, 그 글이 있는 자리로 보낸다. */
      '<p class="my-more"><button class="btn ghost" id="goMine">' +
      "기록에서 읽히는 것 — 성향·관심 보고서 보기 →</button></p>" +
      '<p class="hint" style="text-align:left;padding:6px 0 0;font-size:12px">' +
      "이 칸은 <b>본인에게만</b> 보입니다. 다른 사람의 기록은 볼 수 없습니다.</p></div>";
  }
  function numCell(v, k) {
    return '<div class="my-num"><div class="v">' + v + '</div><div class="k">' + esc(k) + "</div></div>";
  }

  /* ---------- 나의 성향·관심 보고서 ----------
   *
   * 숫자만 늘어놓으면 "378건"이 무엇을 뜻하는지 알 수 없다. 방장이 짚었다 —
   * "너무 산술적이야." 그래서 센 값을 문장으로 옮긴다.
   *
   * 다만 세지 않은 것은 쓰지 않는다. 성격을 지어내지 않고, 기록에서 실제로
   * 읽히는 것만 적는다 — 문장마다 뒤에 센 숫자가 붙어 있다. 근거가 모자라면
   * 그 문장을 통째로 뺀다(임계값). 남을 평가하지 않는 것과 같은 이유로,
   * 이 보고서는 본인 원문이 있는 '나의 기록' 탭에서만 그린다.
   */
  var MY_SLOTS = [
    { from: 0, to: 6, label: "새벽(0~6시)" },
    { from: 6, to: 9, label: "아침(6~9시)" },
    { from: 9, to: 12, label: "오전(9~12시)" },
    { from: 12, to: 18, label: "낮(12~18시)" },
    { from: 18, to: 22, label: "저녁(18~22시)" },
    { from: 22, to: 24, label: "밤(22~24시)" },
  ];
  var MY_PAT = {
    ask: /[?？]|나요|까요|는지요|은지요|으실지|을지요|궁금|여쭤|물어봐|알려주실/,
    warm: /감사|고맙|축하|응원|환영|반갑|수고|화이팅|축하|기대/,
    praise: /멋지|대단|훌륭|좋네|좋습니|최고|굿|잘하[셨시]/,
    laugh: /ㅎㅎ|ㅋㅋ|\^\^|ㅠㅠ|~~/,
    guide: /하시면|하세요|해보세요|해보셔|누르|설치|설정|방법은|이렇게 하/,
    mention: /@\S/,
  };
  var MY_DAYS = ["일", "월", "화", "수", "목", "금", "토"];

  /** 메시지 번호 → 주제. 주제는 메시지 번호의 연속 구간이라 범위로 찾는다. */
  function threadRanges() {
    if (state.tRanges) return state.tRanges;
    var num = function (id) { return parseInt(String(id || "").replace(/\D/g, ""), 10) || 0; };
    state.tRanges = THREADS.map(function (t) {
      return { from: num(t.start_msg), to: num(t.end_msg), cat: t.category };
    }).filter(function (r) { return r.from; })
      .sort(function (a, b) { return a.from - b.from; });
    return state.tRanges;
  }

  /** 지식 그래프의 도구·결과물 이름을 찾을 말로 바꾼다. 'A(B)' 는 A 와 B 둘 다. */
  function myTermList() {
    if (state.myTerms) return state.myTerms;
    var out = [];
    (KNOW.nodes || []).forEach(function (n) {
      if (n.type !== "tool" && n.type !== "app") return;
      var words = [];
      String(n.query || n.label).split(/[·,]/).forEach(function (part) {
        var m = /^(.*?)\((.+?)\)\s*$/.exec(part.trim());
        if (m) { words.push(m[1].trim()); words.push(m[2].trim()); }
        else if (part.trim()) words.push(part.trim());
      });
      words = words.filter(function (w) { return w.length >= 2; });
      if (words.length) out.push({ label: n.label, words: words });
    });
    state.myTerms = out;
    return out;
  }

  /** 한 글에 그 이름이 나오는가. 영문 낱말은 다른 낱말 안에 박힌 것을 세지 않는다. */
  function mentions(text, words) {
    for (var i = 0; i < words.length; i++) {
      var w = words[i];
      if (/^[\x20-\x7e]+$/.test(w)) {
        var re = new RegExp("(^|[^A-Za-z0-9])" + w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") +
          "([^A-Za-z0-9]|$)", "i");
        if (re.test(text)) return true;
      } else if (text.indexOf(w) !== -1) return true;
    }
    return false;
  }

  function myTraits(items) {
    var t = {
      total: items.length, text: 0, image: 0, file: 0, urls: 0, chars: 0, shots: 0,
      long: 0, ask: 0, warm: 0, praise: 0, laugh: 0, guide: 0, mention: 0,
      weekend: 0, slots: [], months: {}, days: {}, cats: {}, terms: [],
      opened: 0, myIds: {},
    };
    MY_SLOTS.forEach(function () { t.slots.push(0); });
    var terms = myTermList().map(function (x) { return { label: x.label, words: x.words, n: 0 }; });
    var ranges = threadRanges();
    var num = function (id) { return parseInt(String(id || "").replace(/\D/g, ""), 10) || 0; };

    items.forEach(function (m) {
      t.myIds[m.id] = 1;
      var kind = mineKind(m);
      t[kind]++;
      t.urls += (m.urls || []).length;
      // 사진은 글 수가 아니라 장 수로 센다 — 한 번에 여러 장을 올린 글이 많다
      if (kind === "image") t.shots += (m.image_count || 1);

      var body = String(m.text || "");
      if (kind === "text") {
        t.chars += body.length;
        if (body.length >= 200) t.long++;
        if (MY_PAT.ask.test(body)) t.ask++;
        if (MY_PAT.warm.test(body)) t.warm++;
        if (MY_PAT.praise.test(body)) t.praise++;
        if (MY_PAT.laugh.test(body)) t.laugh++;
        if (MY_PAT.guide.test(body)) t.guide++;
        if (MY_PAT.mention.test(body)) t.mention++;
        /* 이름 세기에서 주소는 뺀다. github.com 링크를 붙인 것을 'GitHub 를 말했다'로
           세면 링크 공유가 관심사로 둔갑한다. 링크는 이미 따로 세고 있다. */
        var plain = body.replace(/https?:\/\/\S+/g, " ");
        terms.forEach(function (x) { if (mentions(plain, x.words)) x.n++; });
      }

      var hh = parseInt(String(m.time || "").slice(0, 2), 10);
      if (!isNaN(hh)) {
        for (var i = 0; i < MY_SLOTS.length; i++) {
          if (hh >= MY_SLOTS[i].from && hh < MY_SLOTS[i].to) { t.slots[i]++; break; }
        }
      }
      var d = String(m.date || "");
      if (d) {
        t.days[d] = (t.days[d] || 0) + 1;
        t.months[d.slice(0, 7)] = (t.months[d.slice(0, 7)] || 0) + 1;
        var wd = new Date(d + "T00:00:00").getDay();
        if (wd === 0 || wd === 6) t.weekend++;
      }

      /* 발행본 메시지에는 분야가 붙어 있다. 없으면(옛 문서) 번호 구간으로 찾는다. */
      var cat = m.category;
      if (!cat) {
        var n = num(m.id);
        for (var j = 0; j < ranges.length; j++) {
          if (n >= ranges[j].from && n <= ranges[j].to) { cat = ranges[j].cat; break; }
        }
      }
      if (cat) t.cats[cat] = (t.cats[cat] || 0) + 1;
    });

    THREADS.forEach(function (th) { if (t.myIds[th.start_msg]) t.opened++; });

    // 많이 쓴 사람일수록 한두 번 스친 이름은 관심사가 아니다. 글 수에 맞춰 문턱을 올린다.
    var need = Math.max(2, Math.round(t.text / 60));
    t.terms = terms.filter(function (x) { return x.n >= need; })
      .sort(function (a, b) { return b.n - a.n; });
    return t;
  }

  /** 나와 같은 주제에 자주 있었던 사람. 발행본의 참여자 목록만 본다. */
  function myMates(limit) {
    var names = myNicknames();
    var mine = function (n) { return names.indexOf(n) !== -1; };
    var by = {};
    THREADS.forEach(function (t) {
      var ps = t.participants || [];
      if (!ps.some(mine)) return;
      ps.forEach(function (p) { if (!mine(p)) by[p] = (by[p] || 0) + 1; });
    });
    return Object.keys(by).map(function (k) { return { name: k, n: by[k] }; })
      .sort(function (a, b) { return b.n - a.n; }).slice(0, limit);
  }

  function pct(a, b) { return b ? Math.round((a / b) * 100) : 0; }
  function topKey(obj) {
    var best = null;
    Object.keys(obj).forEach(function (k) { if (!best || obj[k] > obj[best]) best = k; });
    return best;
  }
  function ymLabel(ym) {
    var p = String(ym).split("-");
    return p[0] + "년 " + parseInt(p[1], 10) + "월";
  }
  function dLabel(d) {
    var p = String(d).split("-");
    return parseInt(p[1], 10) + "월 " + parseInt(p[2], 10) + "일(" +
      MY_DAYS[new Date(d + "T00:00:00").getDay()] + ")";
  }

  /** 문장 목록 → 섹션. 문장이 하나도 없으면 섹션 자체를 그리지 않는다. */
  function mySection(title, lines) {
    var ok = lines.filter(Boolean);
    if (!ok.length) return "";
    return '<div class="my-story"><h4>' + title + "</h4>" +
      ok.map(function (s) { return "<p>" + s + "</p>"; }).join("") + "</div>";
  }

  function myTraitReport(items) {
    if (!items || items.length < 5) return "";
    var t = myTraits(items);
    var n = t.total, txt = t.text || 1;

    /* 언제 — 시간대는 가장 두드러진 하나만. 고르게 흩어져 있으면 그렇게 적는다. */
    var si = 0;
    t.slots.forEach(function (v, i) { if (v > t.slots[si]) si = i; });
    var slotShare = pct(t.slots[si], n);
    var topMonth = topKey(t.months), topDay = topKey(t.days);
    var when = mySection("언제 쓰셨나", [
      slotShare >= 25
        ? "글은 <b>" + MY_SLOTS[si].label + "</b>에 가장 많았습니다 — " + n + "건 가운데 " +
          t.slots[si] + "건(" + slotShare + "%)이 이 시간대입니다."
        : "쓰신 시각이 하루에 고르게 흩어져 있습니다. 가장 많은 때가 " +
          MY_SLOTS[si].label + "이고 그마저 " + slotShare + "%입니다.",
      t.weekend >= 5
        ? "주말에도 <b>" + t.weekend + "건</b>(" + pct(t.weekend, n) + "%)을 남기셨습니다."
        : "",
      topMonth
        ? "가장 말이 많았던 달은 <b>" + ymLabel(topMonth) + "</b>(" + t.months[topMonth] +
          "건)이고, 하루에 가장 많이 쓴 날은 <b>" + dLabel(topDay) + "</b>(" +
          t.days[topDay] + "건)입니다."
        : "",
    ]);

    /* 무엇 — 도구·결과물 이름과, 방 전체와 견준 분야 쏠림 */
    // 이름 하나가 두 번 나온 것으로 관심사를 말할 수는 없다
    var top5 = (t.terms.length >= 2 || (t.terms[0] && t.terms[0].n >= 3))
      ? t.terms.slice(0, 5).map(function (x) {
          return "<b>" + esc(x.label) + "</b>(" + x.n + "번)";
        }).join(", ")
      : "";
    var roomTotal = 0, roomBy = {};
    (STATS.categories || []).forEach(function (c) { roomTotal += c.messages; roomBy[c.id] = c.messages; });
    var myCatTotal = 0;
    Object.keys(t.cats).forEach(function (k) { myCatTotal += t.cats[k]; });
    var over = Object.keys(t.cats).map(function (k) {
      return { id: k, n: t.cats[k], mine: t.cats[k] / (myCatTotal || 1),
               room: (roomBy[k] || 0) / (roomTotal || 1) };
    /* 비율만 보면 5%대 3% 같은 자잘한 차이가 1등으로 올라온다. 눈에 띄는 쏠림만
       말하려고 비(比)와 차(差)를 함께 걸고, 차이가 큰 것을 고른다. */
    }).filter(function (x) {
      return x.n >= 5 && x.room > 0 && x.mine / x.room >= 1.25 && x.mine - x.room >= 0.04;
    }).sort(function (a, b) { return (b.mine - b.room) - (a.mine - a.room); })[0];
    var myTop = Object.keys(t.cats).map(function (k) { return { id: k, n: t.cats[k] }; })
      .sort(function (a, b) { return b.n - a.n; });
    var what = mySection("무엇에 마음이 갔나", [
      top5 ? "글에 되풀이해 나온 이름은 " + top5 + "입니다." : "",
      myTop.length
        ? "가장 오래 머무신 자리는 <b>" + esc(CAT_LABEL[myTop[0].id] || myTop[0].id) +
          "</b>(" + myTop[0].n + "건, 내 글의 " + pct(myTop[0].n, myCatTotal) + "%)입니다."
        : "",
      over
        ? "이 방 전체와 견주면 <b>" + esc(CAT_LABEL[over.id] || over.id) +
          "</b> 쪽으로 더 기울어 있습니다 — 내 글의 " + Math.round(over.mine * 100) +
          "%, 방 전체는 " + Math.round(over.room * 100) + "%."
        : "",
    ]);

    /* 어떻게 — 묻는지 건네는지, 길게 쓰는지, 어떤 말씨인지 */
    var give = t.urls + t.shots + t.file;
    var gaveWhat = [[t.urls, "링크 %건"], [t.shots, "사진 %장"], [t.file, "첨부 %개"]]
      .filter(function (g) { return g[0]; })
      .map(function (g) { return g[1].replace("%", g[0]); }).join(", ");
    /* 적게 쓴 사람에게 "답하는 쪽"이라고 단정하면 근거 없는 성격 규정이 된다.
       판단은 글이 충분히 쌓였을 때만 하고, 아니면 아예 말하지 않는다. */
    var askLine = "";
    if (pct(t.ask, txt) >= 15) {
      askLine = "묻는 말이 <b>" + t.ask + "건</b>(글의 " + pct(t.ask, txt) +
        "%)입니다. 먼저 물어서 이야기를 끌어내는 편입니다.";
    } else if (txt >= 30 && pct(t.ask, txt) <= 8) {
      askLine = "묻기보다 <b>답하고 알려주는</b> 쪽이 많았습니다. 묻는 말은 " + t.ask +
        "건(" + pct(t.ask, txt) + "%)에 그칩니다.";
    }
    var how = mySection("어떻게 말하셨나", [
      askLine,
      give >= 10
        ? gaveWhat + " — <b>무언가를 건네는 글</b>이 " + give + "번입니다."
        : "",
      "한 번 쓸 때 평균 <b>" + Math.round(t.chars / txt) + "자</b>였고" +
        (t.long ? ", 200자가 넘는 긴 글도 <b>" + t.long + "건</b> 있습니다." : "입니다.") +
        (t.long >= txt * 0.1 ? " 필요할 때는 길게 정리해 두는 편입니다." : ""),
      t.guide >= txt * 0.15
        ? "'이렇게 하세요' 식으로 <b>방법을 일러 주는 글</b>이 " + t.guide + "건(" +
          pct(t.guide, txt) + "%)입니다."
        : "",
      (t.warm + t.praise) >= txt * 0.15
        ? "고맙다·반갑다·멋지다 같은 <b>호응하는 말</b>이 " + (t.warm + t.praise) +
          "건에서 보입니다."
        : "",
      t.laugh >= txt * 0.3
        ? "ㅎㅎ·^^ 같은 표시가 <b>" + t.laugh + "건</b>(" + pct(t.laugh, txt) +
          "%)에 붙어 있습니다. 딱딱하지 않게 말하시는 편입니다."
        : "",
      t.opened >= 3
        ? "<b>" + t.opened + "개 주제</b>의 첫 말을 남기셨습니다 — 이야기를 여는 자리에 " +
          "자주 서 계셨습니다."
        : "",
    ]);

    /* 누구와 — 줄 세우지 않되, 자주 겹친 자리는 알려 준다 */
    var mates = myMates(3);
    var who = mySection("누구와 있었나", [
      mates.length
        ? "같은 주제에 가장 자주 함께 계셨던 분은 " + mates.map(function (m) {
            return "<b>" + esc(m.name) + "</b>(" + m.n + "개 주제)";
          }).join(", ") + "입니다."
        : "",
      t.mention >= 5
        ? "이름을 불러(@) 말을 건넨 글이 " + t.mention + "건입니다."
        : "",
    ]);

    if (!(when + what + how + who)) return "";
    return '<div class="mine-card my-profile">' +
      "<h3>기록에서 읽히는 것</h3>" +
      '<p class="mine-note">아래는 남기신 글을 세어 본 것입니다. ' +
      "세어지지 않는 것은 적지 않았습니다. 본인에게만 보입니다.</p>" +
      when + what + how + who + "</div>";
  }

  /** 여러 색이 쌓인 막대. 한 달 안에서 어떤 주제가 오갔는지 색으로 보인다. */
  function stackBar(label, segs, total, max) {
    var pct = max ? (total / max) * 100 : 0;
    var inner = segs.map(function (s) {
      return '<span class="seg" style="width:' + (s.n / total * 100) + "%;background:" +
        colorFor(s.id) + '" title="' + esc(s.label + " " + s.n) + '"></span>';
    }).join("");
    return '<div class="bar-row"><span class="lab">' + esc(label) + "</span>" +
      '<span class="track"><span class="fill stack" style="width:' + pct + '%">' +
      inner + "</span></span>" +
      '<span class="val">' + total + "</span></div>";
  }

  /** 월별 × 주제별 집계. 스레드의 시작 달을 그 스레드의 달로 본다. */
  function monthlyByCategory() {
    var by = {};
    THREADS.forEach(function (t) {
      var m = (t.start_date || "").slice(0, 7);
      if (!m) return;
      (by[m] = by[m] || {})[t.category] = (by[m][t.category] || 0) + (t.count || 0);
    });
    return Object.keys(by).sort().map(function (m) {
      var segs = Object.keys(by[m])
        .map(function (c) { return { id: c, label: CAT_LABEL[c] || c, n: by[m][c] }; })
        .sort(function (a, b) { return b.n - a.n; });
      return { month: m, segs: segs,
               total: segs.reduce(function (s, x) { return s + x.n; }, 0) };
    });
  }

  function renderStats() {
    var t = STATS.totals || {}, html = [];
    html.push('<div class="stat-cards">' + card(t.messages, "메시지") + card(t.participants, "참여자") +
      card((KNOW.nodes || []).length, "지식 노드") + card((KNOW.edges || []).length, "관계") +
      card(t.downloaded_images, "보관 사진") + card(t.urls, "링크") + "</div>");
    html.push('<p class="room-sub" style="margin:-6px 0 16px">기간 ' + esc(t.date_start || "") + " ~ " + esc(t.date_end || "") + "</p>");

    // 주제 분포를 먼저 — 이 방이 무엇을 이야기했는지가 먼저 보여야 한다
    var cs = (STATS.categories || []).slice().sort(function (a, b) { return b.messages - a.messages; });
    var maxC = cs.reduce(function (s, x) { return Math.max(s, x.messages); }, 1);
    html.push('<div class="panel"><h3>주제 분포</h3>' + cs.map(function (x) {
      return bar(x.label, x.messages, maxC, colorFor(x.id));
    }).join("") + "</div>");

    // 월별 활동은 주제 색을 쌓아 보여 준다. 그 달에 무엇이 오갔는지까지 읽힌다.
    var mc = monthlyByCategory();
    var maxM = mc.reduce(function (s, x) { return Math.max(s, x.total); }, 1);
    html.push('<div class="panel"><h3>월별 활동</h3>' +
      mc.map(function (x) { return stackBar(x.month, x.segs, x.total, maxM); }).join("") +
      '<p class="hint" style="padding:8px 0 0;text-align:left;font-size:12px">' +
      "막대의 색은 주제입니다. 마우스를 올리면 건수가 보입니다.</p></div>");

    html.push(myReport());
    el.view.innerHTML = html.join("");
    var go = document.getElementById("goMine");
    if (go) go.onclick = function () { setView("mine"); };
  }

  // ---------- 라이트박스 ----------
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
    var path = img.getAttribute("data-img");
    // 이미 받아둔 blob URL 이 있으면 그대로, 없으면 경로로 해석
    if (img.src) {
      el.lightboxImg.src = img.src;
    } else if (path && window.ArchiveImages) {
      window.ArchiveImages.urlFor(path).then(function (u) { el.lightboxImg.src = u; });
    }
    el.lightbox.classList.add("on");
  }
  function closeLightbox() { el.lightbox.classList.remove("on"); el.lightboxImg.src = ""; }

  /* ---------- 내 글 관리 ----------
   *
   * 이 화면이 있어야 "언제든 본인 글을 내릴 수 있습니다"를 말할 수 있고,
   * 그래야 멤버들에게 공개 동의를 구할 수 있다.
   *
   * 반영은 즉시가 아니다. 발행본을 다시 만들려면 스레드·요지·그래프까지 재생성해야
   * 해서 브라우저에서 할 수 있는 일이 아니다. 매일 23:40 자동화가 처리하며,
   * 화면에서도 그렇게 안내한다 — 눌렀는데 그대로면 고장으로 보이기 때문이다.
   */
  var COLLECTION_MODES = [
    { id: "public", label: "함께 공개",
      desc: "앞으로의 글을 멤버 아카이브에 함께 담습니다." },
    { id: "unpublished", label: "발행하지 않기",
      desc: "멤버 화면에서는 숨기지만 관리자에게는 운영 원본이 남습니다. 언제든 되돌릴 수 있어요." },
    { id: "none", label: "수집 중단",
      desc: "앞으로의 글을 저장하지 않습니다. 되돌려도 중단 기간의 글은 복구할 수 없습니다." },
  ];

  /** 내 표시명 전부. 카톡에서 이름을 바꾼 사람은 여러 개다 —
   *  하나만 보면 그 사람 글의 절반이 '내 글'에서 사라진다. */
  function myNicknames() {
    var u = state.session && state.session.user;
    if (!u) return [];
    if (u.nicknames && u.nicknames.length) return u.nicknames;
    return u.nickname ? [u.nickname] : [];
  }

  /** 내가 쓴 글 원문. 발행본에는 없고 본인 문서(myMessages/{이메일})에서 따로 받는다. */
  function myMessages() {
    return (state.mine && state.mine.items) || [];
  }

  function canManageMine() {
    return !!(state.session && state.session.requests && myNicknames().length);
  }

  /** 항목 종류 — 사진·첨부를 글과 섞어 두면 찾기 어렵다. */
  function mineKind(m) {
    if (m.kind === "image") return "image";
    if (m.is_file_share) return "file";
    return "text";
  }

  function mineRow(m, pending) {
    var kind = mineKind(m), body;

    if (kind === "image") {
      // 썸네일 없이 '사진'이라고만 쓰면 무엇을 지울지 고를 수가 없다.
      // 작은 썸네일만으로도 부족해서 — 클릭하면 원본 크기로 띄운다.
      body = m.images && m.images.length
        ? '<span class="mine-thumbs">' +
          m.images.map(function (src) {
            return '<img class="mine-thumb" data-img="' + esc(src) +
              '" alt="" title="클릭하면 크게 봅니다" />';
          }).join("") +
          '<span class="mine-zoom">클릭하면 크게 보기</span></span>'
        : '<span class="mine-muted">🖼 사진' +
          (m.image_count > 1 ? " " + m.image_count + "장" : "") + " (수집 대기)</span>";
    } else if (kind === "file") {
      // 파일은 이름만으로 내용을 알 수 없다. 열어보고 지울 수 있어야 한다.
      var fname = m.file ? m.file.name : (m.text || "").replace(/^파일:\s*/, "");
      body = '<span class="mine-file">' +
        '<span class="mf-icon">' + fileIcon(fname) + "</span>" +
        '<span class="mf-body"><span class="mf-name">' + esc(fname) + "</span>" +
        '<span class="mf-meta">' +
        (m.file ? fmtSize(m.file.size) + " · 원본 보관 중" : "원본을 구하지 못한 파일") +
        "</span></span>" +
        (m.file
          ? '<button type="button" class="btn ghost mf-open" data-file="' + esc(m.file.path) +
            '" data-name="' + esc(m.file.name) + '">열어보기</button>'
          : "") +
        "</span>";
    } else {
      body = esc(m.text || "");
    }

    return '<label class="mine-row mine-' + kind + (pending ? " pending" : "") + '">' +
      '<input type="checkbox" data-mid="' + esc(m.id) + '"' + (pending ? " checked" : "") + " />" +
      '<span class="mine-when">' + esc(m.date) + " " + esc(m.time) + "</span>" +
      '<span class="mine-text">' + body + "</span>" +
      (pending ? '<span class="mine-flag">내리는 중</span>' : "") +
      "</label>";
  }

  function renderMine() {
    if (!canManageMine()) {
      el.view.innerHTML =
        '<p class="hint">이 화면은 대화방 표시명이 연결된 계정에서만 쓸 수 있습니다.<br>' +
        "관리자에게 이름 연결을 요청해 주세요.</p>";
      return;
    }
    if (!state.mine) {
      el.view.innerHTML = '<p class="hint">설정을 불러오는 중…</p>';
      var api = state.session.requests;
      Promise.all([api.load(), api.loadMine()]).then(
        function (r) {
          state.mine = r[0];
          state.mine.items = r[1];
          if (state.view === "mine") renderMine();
        },
        function (e) {
          el.view.innerHTML = '<p class="hint">설정을 불러오지 못했습니다: ' +
            esc(e.message || String(e)) + "</p>";
        }
      );
      return;
    }

    var names = myNicknames();
    var all = myMessages();
    var counts = { text: 0, image: 0, file: 0 };
    all.forEach(function (m) { counts[mineKind(m)]++; });
    var filter = state.mineKind || "all";
    var rows = filter === "all"
      ? all
      : all.filter(function (m) { return mineKind(m) === filter; });
    var del = state.mine.deletion;
    var pendingAll = !!(del && del.allMessages);
    var pendingIds = {};
    if (del) (del.messageIds || []).forEach(function (id) { pendingIds[id] = true; });
    var pendingCount = pendingAll ? rows.length : Object.keys(pendingIds).length;

    var modes = COLLECTION_MODES.map(function (mo) {
      return '<label class="mine-mode' + (state.mine.collection === mo.id ? " on" : "") + '">' +
        '<input type="radio" name="collectionMode" value="' + mo.id + '"' +
        (state.mine.collection === mo.id ? " checked" : "") + " />" +
        '<span class="mine-mode-label">' + esc(mo.label) + "</span>" +
        '<span class="mine-mode-desc">' + esc(mo.desc) + "</span></label>";
    }).join("");

    el.view.innerHTML =
      '<section class="mine">' +
      '<h2 class="mine-title">내 글 관리</h2>' +
      '<p class="mine-sub">대화방 표시명 <b>' + esc(names.join(", ")) + "</b> 으로 남긴 " +
      "글 " + counts.text + " · 사진 " + counts.image + " · 첨부 " + counts.file + "개입니다." +
      (names.length > 1 ? " (이름을 바꾸신 이력이 있어 여러 개가 묶여 있습니다.)" : "") +
      "</p>" +

      myTraitReport(all) +

      '<div class="mine-card">' +
      "<h3>앞으로의 수집</h3>" +
      '<div class="mine-modes">' + modes + "</div>" +
      '<button class="btn" id="saveMode">이 설정으로 저장</button>' +
      '<span class="mine-msg" id="modeMsg"></span>' +
      "</div>" +

      '<div class="mine-card">' +
      "<h3>이미 올린 글·사진·첨부 내리기</h3>" +
      (pendingCount
        ? '<p class="mine-note">현재 <b>' + pendingCount + "개</b>를 내려달라고 요청해 두셨습니다. " +
          "아직 반영 전이라 철회할 수 있습니다.</p>"
        : '<p class="mine-note">아래 <b>사진</b>·<b>첨부</b> 탭에서 내가 올린 사진과 파일도 ' +
          "고를 수 있습니다. 사진은 눌러서 크게 보고, 첨부는 열어본 뒤 정하세요. " +
          "발행본에서 빠지며, 되돌리려면 관리자에게 요청해야 합니다.</p>") +
      '<div class="mine-tabs">' +
      [["all", "전체", all.length], ["text", "글", counts.text],
       ["image", "사진", counts.image], ["file", "첨부", counts.file]]
        .map(function (k) {
          return '<button class="mine-tab' + (filter === k[0] ? " on" : "") +
            '" data-kind="' + k[0] + '">' + k[1] + " " + k[2] + "</button>";
        }).join("") +
      "</div>" +
      '<div class="mine-actions">' +
      '<button class="btn ghost" id="selAll">' +
      (filter === "all" ? "전체 선택" : "이 목록 전체 선택") + "</button> " +
      '<button class="btn ghost" id="selNone">선택 해제</button> ' +
      '<button class="btn" id="submitDel">선택한 글 내리기</button> ' +
      (pendingCount ? '<button class="btn ghost" id="cancelDel">요청 철회</button>' : "") +
      '<span class="mine-msg" id="delMsg"></span>' +
      "</div>" +
      '<div class="mine-list">' +
      (rows.length
        ? rows.map(function (m) {
            return mineRow(m, pendingAll || !!pendingIds[m.id]);
          }).join("")
        : '<p class="hint">아직 남긴 글이 없습니다.</p>') +
      "</div></div>" +

      '<p class="mine-foot">요청은 매일 밤 23:40 자동 갱신 때 반영됩니다. ' +
      "사진·첨부는 저장소에서도 실제로 지워집니다. 급하시면 관리자에게 말씀해 주세요.</p>" +
      "</section>";

    bindMineActions();
  }

  function bindMineActions() {
    var api = state.session.requests;

    Array.prototype.forEach.call(el.view.querySelectorAll(".mine-tab"), function (b) {
      b.onclick = function () {
        state.mineKind = b.getAttribute("data-kind");
        renderMine();
      };
    });
    // 썸네일도 Storage 에서 인증 요청으로 받아온다
    bindImages(el.view);

    /* 행 전체가 <label> 이라 그냥 두면 사진을 눌러도 체크박스만 토글된다.
     * 무엇을 지울지 고르려면 먼저 봐야 하므로, 확대가 체크보다 우선이다. */
    Array.prototype.forEach.call(el.view.querySelectorAll(".mine-thumb"), function (img) {
      img.onclick = function (ev) {
        ev.preventDefault(); ev.stopPropagation();
        openLightbox(img);
      };
    });
    Array.prototype.forEach.call(el.view.querySelectorAll(".mf-open"), function (b) {
      b.addEventListener("click", function (ev) {
        ev.preventDefault(); ev.stopPropagation();
      });
    });
    bindFiles(el.view);
    var boxes = function () {
      return Array.prototype.slice.call(el.view.querySelectorAll("input[data-mid]"));
    };
    var setMsg = function (id, text) {
      var n = document.getElementById(id); if (n) n.textContent = text || "";
    };

    document.getElementById("saveMode").onclick = function () {
      var picked = el.view.querySelector('input[name="collectionMode"]:checked');
      if (!picked) return;
      var mode = picked.value;
      var save = function () {
        setMsg("modeMsg", "저장 중…");
        api.saveCollection(mode).then(
          function () { state.mine.collection = mode; setMsg("modeMsg", "저장했습니다."); },
          function (e) { setMsg("modeMsg", "저장 실패: " + (e.message || e)); }
        );
      };
      if (mode === "none") {
        confirmAction({
          title: "앞으로의 글 수집을 중단할까요?",
          description: "설정한 뒤부터 새 글이 저장되지 않습니다.\n" +
            "나중에 되돌려도 중단 기간의 글은 복구할 수 없습니다.",
          confirmLabel: "수집 중단",
        }, save);
      } else {
        save();
      }
    };

    document.getElementById("selAll").onclick = function () {
      boxes().forEach(function (b) { b.checked = true; });
    };
    document.getElementById("selNone").onclick = function () {
      boxes().forEach(function (b) { b.checked = false; });
    };

    document.getElementById("submitDel").onclick = function () {
      var ids = boxes().filter(function (b) { return b.checked; })
        .map(function (b) { return b.getAttribute("data-mid"); });

      // 종류 탭을 켜면 화면에 일부만 뜬다. 그대로 보내면 화면 밖에 있던 기존
      // 요청이 사라진다 — 사진을 고르는 사이 아까 고른 글이 취소되는 셈이다.
      var visible = {};
      boxes().forEach(function (b) { visible[b.getAttribute("data-mid")] = true; });
      var prev = state.mine.deletion;
      var kept = [];
      if (prev && !prev.allMessages) {
        kept = (prev.messageIds || []).filter(function (id) { return !visible[id]; });
      }
      ids = ids.concat(kept);

      if (!ids.length) { setMsg("delMsg", "고른 글이 없습니다."); return; }

      var total = myMessages().length;
      var all = ids.length === total;
      // 1000개 제한은 보안 규칙에도 걸려 있다. 전체 선택이면 목록 대신 플래그로 보낸다.
      if (!all && ids.length > 1000) {
        setMsg("delMsg", "한 번에 1000개까지만 됩니다. 나눠서 요청해 주세요.");
        return;
      }
      confirmAction({
        title: ids.length + "개의 기록을 내려달라고 요청할까요?",
        description: (kept.length ? "다른 탭에서 이미 고른 " + kept.length + "개도 포함됩니다.\n" : "") +
          "사진과 첨부는 저장소에서도 지워집니다.\n오늘 밤 반영 전까지는 철회할 수 있어요.",
        confirmLabel: "삭제 요청하기",
      }, function () {
        setMsg("delMsg", "요청하는 중…");
        api.saveDeletion(all ? [] : ids, all).then(
          function () {
            state.mine.deletion = { messageIds: all ? [] : ids, allMessages: all };
            renderMine();
          },
          function (e) { setMsg("delMsg", "요청 실패: " + (e.message || e)); }
        );
      });
    };

    var cancel = document.getElementById("cancelDel");
    if (cancel) cancel.onclick = function () {
      setMsg("delMsg", "철회하는 중…");
      api.clearDeletion().then(
        function () { state.mine.deletion = null; renderMine(); },
        function (e) { setMsg("delMsg", "철회 실패: " + (e.message || e)); }
      );
    };
  }

  /* ---------- 관리자 ----------
   *
   * 승인은 Cloud Function 이 한다. 클라이언트가 members 문서를 직접 못 쓰게 막아
   * 두었고(규칙에서 write: false), 이미지 권한인 Custom Claims 는 Admin SDK 로만
   * 붙일 수 있기 때문이다. 화면은 요청하고 결과를 보여주는 일만 한다.
   */
  function isAdmin() {
    return !!(state.session && state.session.admin);
  }

  function participantIndex() {
    var idx = {};
    (STATS.participants || []).forEach(function (p) { idx[p.nickname] = p; });
    return idx;
  }

  /** 참여자 목록 드롭다운.
   *
   *  관리 화면은 관리자만 보므로 명단을 그대로 노출해도 된다 — 신청 화면에서
   *  자유 입력을 쓰는 것과 이유가 다르다. 손으로 적으면 오타가 나고, 오타가 나면
   *  그 사람의 '내 글 관리'가 조용히 비어 버린다.
   *
   *  아직 발언한 적 없는 사람은 명단에 없으므로 직접 입력도 남겨둔다.
   */
  function participantSelect(selected, cls) {
    var opts = ['<option value="">— 참여자 선택 —</option>'];
    (STATS.participants || []).forEach(function (p) {
      opts.push('<option value="' + esc(p.nickname) + '"' +
        (p.nickname === selected ? " selected" : "") + ">" +
        esc(p.nickname) + " (" + p.message_count + ")</option>");
    });
    var custom = selected && !participantIndex()[selected];
    opts.push('<option value="__custom__"' + (custom ? " selected" : "") +
      ">직접 입력 (아직 발언 없음)</option>");
    return '<select class="' + cls + '">' + opts.join("") + "</select>" +
      '<input class="' + cls + '-text adm-nick" placeholder="대화방 표시명" value="' +
      esc(custom ? selected : "") + '"' + (custom ? "" : ' hidden') + " />";
  }

  function bindParticipantSelect(scope, cls) {
    var sel = scope.querySelector("." + cls);
    var txt = scope.querySelector("." + cls + "-text");
    if (!sel || !txt) return function () { return ""; };
    sel.onchange = function () {
      var custom = sel.value === "__custom__";
      txt.hidden = !custom;
      if (custom) txt.focus();
    };
    return function () {
      return sel.value === "__custom__" ? (txt.value || "").trim() : sel.value;
    };
  }

  function adminClaimRow(c, parts) {
    var hit = parts[c.nickname];
    var match = hit
      ? '<span class="ok">○ 참여자 ' + esc(c.nickname) + " · " + hit.message_count + "건</span>"
      : '<span class="bad">× 명단에 없음</span>';
    return '<div class="adm-row" data-email="' + esc(c.id) + '">' +
      '<div class="adm-main"><b>' + esc(c.nickname || "(이름 없음)") + "</b> " +
      '<span class="adm-mail">' + esc(c.id) + "</span></div>" +
      '<div class="adm-meta">' + match +
      (c.displayName ? ' · 구글 계정명 ' + esc(c.displayName) : "") + "</div>" +
      '<div class="adm-act">' +
      participantSelect(c.nickname || "", "adm-pick") +
      '<button class="btn" data-act="approve">승인</button> ' +
      '<button class="btn ghost" data-act="reject">반려</button>' +
      "</div></div>";
  }

  function renderAdmin() {
    if (!isAdmin()) {
      el.view.innerHTML = '<p class="hint">관리자만 볼 수 있습니다.</p>';
      return;
    }
    if (!state.admin) {
      el.view.innerHTML = '<p class="hint">불러오는 중…</p>';
      state.session.admin.load().then(
        function (d) { state.admin = d; if (state.view === "admin") renderAdmin(); },
        function (e) {
          el.view.innerHTML = '<p class="hint">불러오지 못했습니다: ' +
            esc(e.message || String(e)) + "</p>";
        }
      );
      return;
    }

    var d = state.admin;
    var parts = participantIndex();
    var MODE_LABEL = { public: "함께 공개", unpublished: "발행하지 않기", none: "수집 중단" };

    var pending = d.preferences.filter(function (p) {
      return p.collection && p.collection !== "public";
    });

    el.view.innerHTML =
      '<section class="adm">' +
      '<h2 class="mine-title">관리</h2>' +

      '<div class="mine-card"><h3>열람 신청 ' + d.claims.length + "건</h3>" +
      (d.claims.length
        ? d.claims.map(function (c) { return adminClaimRow(c, parts); }).join("")
        : '<p class="mine-note">대기 중인 신청이 없습니다.</p>') +
      '<p class="adm-msg" id="admMsg"></p></div>' +

      '<div class="mine-card"><h3>삭제 요청 ' + d.deletions.length + "건</h3>" +
      (d.deletions.length
        ? d.deletions.map(function (r) {
            var n = r.allMessages ? "본인 글 전체" : ((r.messageIds || []).length + "건");
            return '<div class="adm-line"><b>' + esc(r.id) + "</b> — " + esc(n) + "</div>";
          }).join("")
        : '<p class="mine-note">요청이 없습니다.</p>') +
      '<p class="mine-note">반영은 매일 23:40 자동 갱신 때 이뤄집니다. ' +
      "남의 글을 지우려는 요청은 반영 단계에서 걸러지고 로그에 남습니다.</p></div>" +

      '<div class="mine-card"><h3>수집 동의 — 기본값이 아닌 ' + pending.length + "명</h3>" +
      (pending.length
        ? pending.map(function (p) {
            return '<div class="adm-line"><b>' + esc(p.id) + "</b> — " +
              esc(MODE_LABEL[p.collection] || p.collection) + "</div>";
          }).join("")
        : '<p class="mine-note">모두 함께 공개 설정입니다.</p>') +
      "</div>" +

      '<div class="mine-card"><h3>발행에서 뺀 주제 ' +
      (d.hiddenThreads || []).length + "개</h3>" +
      ((d.hiddenThreads || []).length
        ? d.hiddenThreads.map(function (t) {
            return '<div class="adm-member" data-tid="' + esc(t.id) + '">' +
              '<div class="adm-main"><b>' + esc(t.title || t.id) + "</b> " +
              '<span class="adm-mail">' + esc(t.id) +
              (t.hiddenAt ? " · " + esc(String(t.hiddenAt).slice(0, 10)) : "") +
              "</span></div>" +
              '<div class="adm-act"><button class="btn ghost adm-unhide">되돌리기</button></div>' +
              "</div>";
          }).join("")
        : '<p class="mine-note">뺀 주제가 없습니다. 주제 흐름 탭의 카드에서 뺄 수 있습니다.</p>') +
      '<p class="mine-note">뺀 주제는 발행본에서 사라져 아무에게도 보이지 않습니다. ' +
      "원본은 남아 있어 되돌리면 다시 나옵니다. 반영은 오늘 밤 갱신 때입니다.</p>" +
      '<p class="adm-msg" id="hideMsg"></p></div>' +

      '<div class="mine-card"><h3>멤버 ' + d.members.length + "명</h3>" +
      d.members.map(function (m) {
        var names = (m.nicknames && m.nicknames.length)
          ? m.nicknames : (m.nickname ? [m.nickname] : []);
        var unlinked = names.filter(function (n) { return !parts[n]; });
        var isAdm = m.role === "admin";
        return '<div class="adm-member" data-email="' + esc(m.id) + '"' +
          ' data-names="' + esc(names.join(", ")) + '">' +
          '<div class="adm-main"><b>' +
          (names.length ? esc(names.join(", ")) : "(표시명 없음)") + "</b> " +
          '<span class="adm-mail">' + esc(m.id) + "</span>" +
          (isAdm ? ' <span class="adm-tag">관리자</span>' : "") +
          (unlinked.length
            ? ' <span class="bad">· ' + esc(unlinked.join(", ")) + " 은 아직 발언 없음</span>"
            : "") +
          "</div>" +
          '<div class="adm-act">' +
          '<button class="btn ghost adm-link">연결 편집</button> ' +
          '<button class="btn ghost adm-role" data-role="' + (isAdm ? "user" : "admin") +
          '">' + (isAdm ? "관리자 해제" : "관리자 지정") + "</button> " +
          '<button class="btn ghost adm-remove">탈퇴</button></div>' +
          '<div class="adm-link-panel" hidden>' +
          '<p class="mine-note">이 사람이 대화방에서 쓴 표시명을 모두 고릅니다. ' +
          "카톡에서 이름을 바꿨다면 옛 이름과 새 이름을 함께 묶어야 글이 온전히 보입니다.</p>" +
          '<div class="adm-nick-list">' +
          (STATS.participants || []).map(function (pp) {
            return '<label><input type="checkbox" value="' + esc(pp.nickname) + '"' +
              (names.indexOf(pp.nickname) !== -1 ? " checked" : "") + " /> " +
              esc(pp.nickname) + ' <span class="adm-mail">' + pp.message_count + "</span></label>";
          }).join("") + "</div>" +
          '<button class="btn adm-link-save">저장</button> ' +
          '<button class="btn ghost adm-link-cancel">취소</button>' +
          "</div></div>";
      }).join("") +
      '<p class="mine-note">‘참여자 명단과 연결 안 됨’ 은 그 표시명으로 남긴 글이 ' +
      "아직 없다는 뜻입니다. 대화방에서 한 번 발언하면 그날 밤 자동으로 연결됩니다." +
      "</p><p class=\"adm-msg\" id=\"roleMsg\"></p></div>" +
      "</section>";

    bindAdminActions();
  }

  function bindAdminActions() {
    var msg = document.getElementById("admMsg");
    var say = function (t) { if (msg) msg.textContent = t || ""; };

    Array.prototype.forEach.call(el.view.querySelectorAll("[data-tid] .adm-unhide"), function (b) {
      var row = b.closest("[data-tid]");
      b.onclick = function () {
        var tid = row.getAttribute("data-tid");
        var m = document.getElementById("hideMsg");
        if (m) m.textContent = "되돌리는 중…";
        state.session.admin.setThreadHidden(tid, "", false).then(
          function () { state.admin = null; renderAdmin(); },
          function (e) { if (m) m.textContent = "실패: " + (e.message || String(e)); }
        );
      };
    });

    Array.prototype.forEach.call(el.view.querySelectorAll(".adm-member[data-email]"), function (row) {
      var email = row.getAttribute("data-email");
      var panel = row.querySelector(".adm-link-panel");
      row.querySelector(".adm-link").onclick = function () { panel.hidden = !panel.hidden; };
      row.querySelector(".adm-link-cancel").onclick = function () { panel.hidden = true; };
      row.querySelector(".adm-link-save").onclick = function () {
        var picked = Array.prototype.slice
          .call(panel.querySelectorAll("input:checked"))
          .map(function (i) { return i.value; });
        if (!picked.length) {
          window.alert("표시명을 하나 이상 고르세요. 연결이 끊기면 '내 글 관리'가 비어 버립니다.");
          return;
        }
        var m = document.getElementById("roleMsg");
        if (m) m.textContent = "연결하는 중…";
        state.session.admin.setNicknames(email, picked).then(
          function () { state.admin = null; renderAdmin(); },
          function (e) { if (m) m.textContent = "실패: " + (e.message || String(e)); }
        );
      };

      row.querySelector(".adm-remove").onclick = function () {
        var m = document.getElementById("roleMsg");
        // 수집 중단은 되돌려도 그 기간이 영영 비므로, 어떤 이름이 멈추는지
        // 분명히 보여준 뒤에만 부른다.
        var names = row.getAttribute("data-names") || "";
        confirmAction({
          title: email + " 님을 탈퇴 처리할까요?",
          description: "대화·이미지·첨부 열람 권한이 사라집니다.\n" +
            (names ? "앞으로 수집하지 않을 표시명: " + names + "\n" : "") +
            "이미 올라간 과거 글은 남고, 기존 삭제 요청은 계속 반영됩니다.",
          confirmLabel: "탈퇴 처리",
        }, function () {
          if (m) m.textContent = "처리 중…";
          state.session.admin.removeMember(email).then(
            function (r) {
              state.admin = null;
              renderAdmin();
              var note = document.getElementById("roleMsg");
              if (note) {
                note.textContent = email + " 탈퇴 처리 완료." +
                  (r && r.stoppedCollecting ? " 앞으로의 글은 수집하지 않습니다." : "") +
                  " 수집 중단은 오늘 밤 갱신부터 적용됩니다.";
              }
            },
            function (e) { if (m) m.textContent = "실패: " + (e.message || String(e)); }
          );
        });
      };

      var btn = row.querySelector(".adm-role");
      btn.onclick = function () {
        var role = btn.getAttribute("data-role");
        var verb = role === "admin" ? "관리자로 지정" : "관리자에서 해제";
        confirmAction({
          title: email + " 님을 " + verb + "할까요?",
          description: role === "admin"
            ? "멤버 승인과 운영 설정을 바꿀 수 있는 권한이 생깁니다."
            : "관리 기능 접근 권한이 사라집니다.",
          confirmLabel: verb,
          tone: "neutral",
        }, function () {
          var m = document.getElementById("roleMsg");
          if (m) m.textContent = "바꾸는 중…";
          state.session.admin.setRole(email, role).then(
            function () { state.admin = null; renderAdmin(); },
            function (e) { if (m) m.textContent = "실패: " + (e.message || String(e)); }
          );
        });
      };
    });

    Array.prototype.forEach.call(el.view.querySelectorAll(".adm-row"), function (row) {
      var email = row.getAttribute("data-email");
      var pick = bindParticipantSelect(row, "adm-pick");

      var finish = function (verb) {
        return function () {
          say(email + " " + verb + " 완료. 목록을 새로 불러옵니다…");
          state.admin = null;
          renderAdmin();
        };
      };
      var fail = function (e) { say("실패: " + (e.message || String(e))); };

      row.querySelector('[data-act="approve"]').onclick = function () {
        var nickname = pick();
        if (nickname.length < 2) { say("연결할 참여자를 고르거나 표시명을 적어주세요."); return; }
        var approve = function () {
          say("승인 중…");
          // 표시명은 목록으로 보낸다. 나중에 이름이 바뀌면 여기에 덧붙인다.
          state.session.admin.approve(email, [nickname], "user").then(finish("승인"), fail);
        };
        if (!participantIndex()[nickname]) {
          confirmAction({
            title: "명단에 없는 표시명으로 승인할까요?",
            description: "'" + nickname + "'은 현재 참여자 명단에 없습니다.\n" +
              "아직 발언이 없는 멤버라면 그대로 승인해도 됩니다.",
            confirmLabel: "이대로 승인",
            tone: "neutral",
          }, approve);
        } else {
          approve();
        }
      };
      row.querySelector('[data-act="reject"]').onclick = function () {
        confirmAction({
          title: email + " 님의 신청을 반려할까요?",
          description: "이 신청은 대기 목록에서 사라집니다. 필요하면 다시 신청할 수 있어요.",
          confirmLabel: "신청 반려",
        }, function () {
          say("반려 중…");
          state.session.admin.reject(email).then(finish("반려"), fail);
        });
      };
    });
  }

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
      mobileTheme.innerHTML = themeIcon(next);
      mobileTheme.setAttribute("aria-label", label);
      mobileTheme.setAttribute("title", label);
    }
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
    var mark = '<span class="font-toggle__mark" aria-hidden="true">가</span>';
    [el.fontBtn, document.querySelector('[data-mobile-action="font"]')].forEach(
      function (btn) {
        if (!btn) return;
        btn.innerHTML = mark;
        btn.setAttribute("data-font-next", next.id);
        btn.setAttribute("aria-label", label);
        btn.setAttribute("title", label);
      }
    );
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
      '<button type="button" data-view="files">첨부파일</button>',
      '<button type="button" data-view="stats">통계</button>',
    ];
    if (isAdmin()) html.push('<button type="button" data-view="admin">관리자</button>');
    html.push('<button type="button" data-mobile-action="font"></button>');
    html.push('<button type="button" data-mobile-action="theme"></button>');
    if (state.session) html.push('<button type="button" data-mobile-action="signout">로그아웃</button>');
    el.mobileMore.innerHTML = html.join("");
    updateFontControls();
    updateThemeControls();
  }

  function setView(v) {
    if (state.graph && v !== "graph") { state.graph.destroy(); state.graph = null; }
    state.view = v;
    setNavigationState(v);
    setMobileMore(false);
    render();
  }
  function render() {
    if (state.view === "summary") renderSummary();
    else if (state.view === "graph") renderGraph();
    else if (state.view === "timeline") renderTimeline();
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
    KNOW = A.knowledge || { nodes: [], edges: [] };
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
        // 첨부 탭은 자체 검색을 하므로 타임라인으로 튕기지 않는다
        if (state.view === "files") { render(); return; }
        if (state.view !== "timeline") setView("timeline"); else render();
      }, 180);
    });
    el.filter.addEventListener("change", function () {
      state.nick = el.filter.value;
      if (state.nick) state.pick = null;
      if (state.view === "graph") setView("timeline"); else render();
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

    setNavigationState(state.view);
    render();
  }

  // 보호모드(hosting)에서는 boot.js 가 로그인·데이터 로드를 끝낸 뒤 start() 를 부른다.
  // 로컬 미리보기(site/)에서는 data.js 가 이미 window.ARCHIVE 를 채워두므로 바로 시작.
  window.ArchiveApp = { start: init };
  // 원문(messages)은 더 이상 싣지 않는다. 스레드 요약이 있으면 데이터가 준비된 것이다.
  if (window.ARCHIVE && window.ARCHIVE.threads) init(null);
})();
