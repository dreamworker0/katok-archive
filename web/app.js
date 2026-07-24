/* ============ 사회복지 바이브코딩 아카이브 · 앱 로직 ============ */
(function () {
  "use strict";
  var A = window.ARCHIVE || {};
  var MSGS = A.messages || [];
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
    view: document.getElementById("view"),
    tabs: document.getElementById("tabs"),
    search: document.getElementById("searchInput"),
    filter: document.getElementById("participantFilter"),
    roomTitle: document.getElementById("roomTitle"),
    roomSub: document.getElementById("roomSub"),
    themeBtn: document.getElementById("themeBtn"),
    lightbox: document.getElementById("lightbox"),
    lightboxImg: document.getElementById("lightboxImg"),
    lightboxClose: document.getElementById("lightboxClose"),
  };
  var state = { view: "summary", q: "", nick: "", graph: null };

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
  var WD = ["일", "월", "화", "수", "목", "금", "토"];
  function fmtDate(d) {
    var p = d.split("-"), dt = new Date(+p[0], +p[1] - 1, +p[2]);
    return p[0] + "년 " + (+p[1]) + "월 " + (+p[2]) + "일 (" + WD[dt.getDay()] + ")";
  }

  // ---------- 주제별 지식(요약) ----------
  function renderSummary() {
    var html = ['<div class="cat-nav">'];
    CATS.forEach(function (c) {
      var d = DIGESTS[c.id]; if (!d) return;
      html.push('<button data-goto="doc-' + c.id + '"><span class="swatch" style="background:' +
        colorFor(c.id) + '"></span>' + esc(c.label) + " · " + (d.message_count || 0) + "</button>");
    });
    html.push("</div>");
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
      return '<button class="app-item" data-q="' + esc(a.query || a.label) + '">' +
        '<span class="an">' + esc(a.label) + "</span>" +
        (a.maker ? '<span class="am">' + esc(a.maker) + "</span>" : "") + "</button>";
    }).join("");
    var links = (d.links || []);
    var linkTop = links.slice(0, 10), linkRest = links.slice(10);
    function lk(l) {
      return '<a href="' + esc(l.url) + '" target="_blank" rel="noopener noreferrer">' + esc(l.url) +
        '</a><span class="lk-meta">' + esc(l.nickname) + " · " + esc(l.date) + "</span>";
    }
    var linkHtml = linkTop.map(function (l) { return "<div>" + lk(l) + "</div>"; }).join("");
    if (linkRest.length) {
      linkHtml += "<details><summary>공유 링크 " + linkRest.length + "개 더</summary>" +
        linkRest.map(function (l) { return "<div>" + lk(l) + "</div>"; }).join("") + "</details>";
    }
    var people = (d.participants || []).map(function (p) {
      return '<button class="chip" data-nick="' + esc(p.nickname) + '">' + esc(p.nickname) +
        " <span style=\"color:var(--ink-faint)\">" + p.count + "</span></button>";
    }).join("");
    var kw = (d.keywords || []).map(function (k) { return '<span class="chip">' + esc(k) + "</span>"; }).join("");
    var threads = (d.threads || []).map(function (t) {
      var range = t.start_date === t.end_date ? t.start_date : t.start_date + " ~ " + t.end_date;
      return '<div class="thread-line" data-start="m-' + t.start_msg + '"><b>' + esc(t.title) +
        '</b><span class="tl-date">' + esc(range) + '</span><span class="tl-n">💬 ' + t.count + "</span></div>";
    }).join("");

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
      (threads ? '<details class="thread-toggle"><summary>소속 대화 주제 ' + (d.threads || []).length +
        "개</summary>" + threads + "</details>" : "") +
      "</article>";
  }

  function bindDocActions(scope) {
    Array.prototype.forEach.call(scope.querySelectorAll(".app-item"), function (b) {
      b.onclick = function () { runSearch(b.getAttribute("data-q")); };
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

  // ---------- 타임라인 ----------
  function matches(m) {
    if (state.nick && m.nickname !== state.nick) return false;
    if (state.q) {
      var q = state.q.toLowerCase();
      if ((m.text + " " + m.nickname + " " + m.date + " " + m.time).toLowerCase().indexOf(q) === -1) return false;
    }
    return true;
  }
  function renderTimeline() {
    var rows = MSGS.filter(matches);
    if (!rows.length) { el.view.innerHTML = '<p class="hint">검색 결과가 없어요.</p>'; return; }
    var html = [], lastDate = null, lastNick = null;
    for (var i = 0; i < rows.length; i++) {
      var m = rows[i];
      if (m.date !== lastDate) {
        html.push('<div class="date-sep">' + esc(fmtDate(m.date)) + "</div>");
        lastDate = m.date; lastNick = null;
      }
      var cont = m.nickname === lastNick;
      lastNick = m.nickname;
      html.push(renderEntry(m, cont));
    }
    el.view.innerHTML = html.join("");
    bindImages(el.view);
  }
  function renderEntry(m, cont) {
    var inner;
    if (m.kind === "image") {
      if (m.image_pending) {
        inner = '<div class="img-pending">🖼 사진' + (m.image_count > 1 ? " " + m.image_count + "장" : "") + " (수집 대기)</div>";
      } else {
        var single = m.images.length === 1 ? " single" : "";
        inner = '<div class="imgs' + single + '">' +
          m.images.map(function (s) { return '<img loading="lazy" src="' + esc(s) + '" alt="" />'; }).join("") + "</div>";
      }
    } else if (m.is_file_share) {
      inner = '<div class="file-badge">📎 ' + linkify(esc(m.text.replace(/^파일:\s*/, ""))) + "</div>";
    } else {
      inner = '<div class="entry-text">' + highlightText(linkify(esc(m.text)), state.q) + "</div>";
    }
    var cat = m.category ? '<span class="cat" style="--c:' + colorFor(m.category) + '">#' +
      esc(CAT_LABEL[m.category] || m.category) + "</span>" : "";
    return '<div class="entry' + (cont ? " cont" : "") + '" id="m-' + m.id + '" style="--c:' +
      colorFor(m.category) + '">' +
      '<div class="avatar" style="' + avatarStyle(m.nickname) + '">' + esc(initial(m.nickname)) + "</div>" +
      '<div class="entry-body">' +
      (cont ? "" : '<div class="entry-head"><span class="nm">' + esc(m.nickname) + '</span><span class="tm">' +
        esc(m.time) + "</span>" + cat + "</div>") +
      inner + "</div></div>";
  }

  function jumpToTimeline(anchor) {
    state.q = ""; state.nick = ""; el.search.value = ""; el.filter.value = "";
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

  // ---------- 갤러리 ----------
  function renderGallery() {
    var items = [];
    MSGS.forEach(function (m) {
      if (m.kind === "image" && m.images && m.images.length) {
        if (state.nick && m.nickname !== state.nick) return;
        m.images.forEach(function (src) { items.push({ src: src, nick: m.nickname, date: m.date, id: m.id }); });
      }
    });
    if (!items.length) { el.view.innerHTML = '<p class="hint">표시할 이미지가 없어요.</p>'; return; }
    var html = ['<p class="room-sub" style="margin:0 0 12px">보관된 사진 ' + items.length + "장</p>", '<div class="gallery">'];
    items.forEach(function (it) {
      html.push('<figure data-jump="m-' + it.id + '"><img loading="lazy" src="' + esc(it.src) +
        '" alt="" /><figcaption>' + esc(it.date) + " · " + esc(it.nick) + "</figcaption></figure>");
    });
    html.push("</div>");
    el.view.innerHTML = html.join("");
    Array.prototype.forEach.call(el.view.querySelectorAll("figure"), function (fig) {
      fig.querySelector("img").onclick = function () { openLightbox(this.src); };
      fig.querySelector("figcaption").onclick = function () { jumpToTimeline(fig.getAttribute("data-jump")); };
    });
  }

  // ---------- 통계 ----------
  function bar(label, value, max, color) {
    var pct = max ? Math.round((value / max) * 100) : 0;
    return '<div class="bar-row"><span class="lab">' + esc(label) + '</span><span class="track">' +
      '<span class="fill" style="width:' + pct + "%" + (color ? ";--c:" + color : "") + '"></span></span>' +
      '<span class="val">' + value + "</span></div>";
  }
  function card(v, k) { return '<div class="stat-card"><div class="v">' + (v == null ? "-" : v) + '</div><div class="k">' + esc(k) + "</div></div>"; }
  function renderStats() {
    var t = STATS.totals || {}, html = [];
    html.push('<div class="stat-cards">' + card(t.messages, "메시지") + card(t.participants, "참여자") +
      card((KNOW.nodes || []).length, "지식 노드") + card((KNOW.edges || []).length, "관계") +
      card(t.downloaded_images, "보관 사진") + card(t.urls, "링크") + "</div>");
    html.push('<p class="room-sub" style="margin:-6px 0 16px">기간 ' + esc(t.date_start || "") + " ~ " + esc(t.date_end || "") + "</p>");

    var ps = STATS.participants || [], top = ps.slice(0, 15);
    var restN = ps.slice(15).reduce(function (s, p) { return s + p.message_count; }, 0);
    var maxP = top.length ? top[0].message_count : 1;
    var pb = top.map(function (p) { return bar(p.nickname, p.message_count, maxP, "var(--accent)"); }).join("");
    if (restN) pb += bar("그 외 " + (ps.length - 15) + "명", restN, maxP, "var(--ink-faint)");
    html.push('<div class="panel"><h3>참여자별 메시지 (상위 15)</h3>' + pb + "</div>");

    var mo = STATS.monthly || [], maxM = mo.reduce(function (s, x) { return Math.max(s, x.count); }, 1);
    html.push('<div class="panel"><h3>월별 활동</h3>' + mo.map(function (x) { return bar(x.month, x.count, maxM, "var(--accent)"); }).join("") + "</div>");

    var cs = (STATS.categories || []).slice().sort(function (a, b) { return b.messages - a.messages; });
    var maxC = cs.reduce(function (s, x) { return Math.max(s, x.messages); }, 1);
    html.push('<div class="panel"><h3>주제 분포</h3>' + cs.map(function (x) {
      return bar(x.label, x.messages, maxC, colorFor(x.id));
    }).join("") + "</div>");
    el.view.innerHTML = html.join("");
  }

  // ---------- 라이트박스 ----------
  function bindImages(scope) {
    Array.prototype.forEach.call(scope.querySelectorAll(".imgs img"), function (img) {
      img.onclick = function () { openLightbox(img.src); };
    });
  }
  function openLightbox(src) { el.lightboxImg.src = src; el.lightbox.classList.add("on"); }
  function closeLightbox() { el.lightbox.classList.remove("on"); el.lightboxImg.src = ""; }

  // ---------- 검색·라우팅 ----------
  function runSearch(q) {
    state.q = q || ""; el.search.value = state.q;
    setView("timeline");
  }
  function setView(v) {
    if (state.graph && v !== "graph") { state.graph.destroy(); state.graph = null; }
    state.view = v;
    Array.prototype.forEach.call(el.tabs.children, function (tab) {
      tab.classList.toggle("active", tab.getAttribute("data-view") === v);
    });
    render();
  }
  function render() {
    if (state.view === "summary") renderSummary();
    else if (state.view === "graph") renderGraph();
    else if (state.view === "timeline") renderTimeline();
    else if (state.view === "gallery") renderGallery();
    else if (state.view === "stats") renderStats();
  }

  // ---------- 초기화 ----------
  function init() {
    el.roomTitle.textContent = A.chat_room || "아카이브";
    var t = STATS.totals || {};
    el.roomSub.textContent = (t.messages || 0) + "개 메시지 · " + (t.participants || 0) + "명 · " +
      (t.date_start || "") + " ~ " + (t.date_end || "");
    (STATS.participants || []).forEach(function (p) {
      var o = document.createElement("option");
      o.value = p.nickname; o.textContent = p.nickname + " (" + p.message_count + ")";
      el.filter.appendChild(o);
    });

    el.tabs.addEventListener("click", function (e) {
      var tab = e.target.closest(".tab"); if (tab) setView(tab.getAttribute("data-view"));
    });
    var timer;
    el.search.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(function () {
        state.q = el.search.value.trim();
        if (state.view === "graph" && state.graph) { state.graph.search(state.q); return; }
        if (state.view !== "timeline") setView("timeline"); else render();
      }, 180);
    });
    el.filter.addEventListener("change", function () {
      state.nick = el.filter.value;
      if (state.view === "graph") setView("timeline"); else render();
    });
    el.lightbox.addEventListener("click", function (e) {
      if (e.target === el.lightbox || e.target === el.lightboxClose) closeLightbox();
    });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeLightbox(); });

    var saved = null; try { saved = localStorage.getItem("kakao-archive-theme"); } catch (e) {}
    if (saved) document.documentElement.setAttribute("data-theme", saved);
    el.themeBtn.addEventListener("click", function () {
      var cur = document.documentElement.getAttribute("data-theme");
      var isDark = cur === "dark" || (!cur && window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
      var next = isDark ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      try { localStorage.setItem("kakao-archive-theme", next); } catch (e) {}
    });

    render();
  }
  init();
})();
