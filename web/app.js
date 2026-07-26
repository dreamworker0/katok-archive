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
  var state = { view: "summary", q: "", nick: "", graph: null, session: null,
                mine: null, admin: null };

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
    bindFiles(el.view);
  }
  function renderEntry(m, cont) {
    var inner;
    if (m.kind === "image") {
      if (m.image_pending) {
        inner = '<div class="img-pending">🖼 사진' + (m.image_count > 1 ? " " + m.image_count + "장" : "") + " (수집 대기)</div>";
      } else {
        var single = m.images.length === 1 ? " single" : "";
        inner = '<div class="imgs' + single + '">' +
          m.images.map(function (s) { return '<img data-img="' + esc(s) + '" alt="" />'; }).join("") + "</div>";
      }
    } else if (m.is_file_share) {
      // 원본을 구한 첨부만 내려받기 버튼이 된다. 나머지는 예전처럼 이름만 남는다 —
      // 눌러도 아무 일이 없는 링크보다 눌리지 않는 배지가 정직하다.
      var fname = (m.text || "").replace(/^파일:\s*/, "");
      if (m.file) {
        inner = '<button class="file-badge has-file" data-file="' + esc(m.file.path) +
          '" data-name="' + esc(m.file.name) + '">📎 ' + esc(m.file.name) +
          ' <span class="file-size">' + fmtSize(m.file.size) + '</span></button>';
      } else {
        inner = '<div class="file-badge">📎 ' + linkify(esc(fname)) + "</div>";
      }
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
      html.push('<figure data-jump="m-' + it.id + '"><img data-img="' + esc(it.src) +
        '" alt="" /><figcaption>' + esc(it.date) + " · " + esc(it.nick) + "</figcaption></figure>");
    });
    html.push("</div>");
    el.view.innerHTML = html.join("");
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
    var rows = MSGS.filter(function (m) { return m.is_file_share; });
    if (!rows.length) {
      el.view.innerHTML = '<p class="hint">공유된 파일이 없어요.</p>';
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

    var html = ['<p class="room-sub" style="margin:0 0 12px">공유된 파일 ' + rows.length +
      "개 · 원본 보관 " + have.length + "개" +
      (shown.length !== rows.length ? " · 표시 " + shown.length + "개" : "") + "</p>"];

    if (!shown.length) {
      html.push('<p class="hint">조건에 맞는 파일이 없어요.</p>');
    } else {
      html.push('<div class="files">');
      shown.forEach(function (m) {
        var name = m.file ? m.file.name : (m.text || "").replace(/^파일:\s*/, "");
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
          '<button class="btn ghost fc-jump" data-jump="m-' + m.id + '">대화</button>' +
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
    { id: "public", label: "공개",
      desc: "기본값입니다. 앞으로의 글도 아카이브에 담깁니다." },
    { id: "unpublished", label: "발행 제외",
      desc: "수집은 되지만 아카이브에 보이지 않습니다. 설정을 되돌리면 다시 보입니다." },
    { id: "none", label: "수집 거부",
      desc: "앞으로의 글을 아예 저장하지 않습니다. 되돌려도 그동안의 글은 복구할 수 없습니다." },
  ];

  /** 내 표시명 전부. 카톡에서 이름을 바꾼 사람은 여러 개다 —
   *  하나만 보면 그 사람 글의 절반이 '내 글'에서 사라진다. */
  function myNicknames() {
    var u = state.session && state.session.user;
    if (!u) return [];
    if (u.nicknames && u.nicknames.length) return u.nicknames;
    return u.nickname ? [u.nickname] : [];
  }

  function myMessages() {
    var names = myNicknames();
    if (!names.length) return [];
    return MSGS.filter(function (m) { return names.indexOf(m.nickname) !== -1; });
  }

  function canManageMine() {
    return !!(state.session && state.session.requests && myNicknames().length);
  }

  function mineRow(m, pending) {
    var body;
    if (m.kind === "image") body = "🖼 사진" + (m.image_count > 1 ? " " + m.image_count + "장" : "");
    else if (m.is_file_share) body = "📎 " + esc((m.text || "").replace(/^파일:\s*/, ""));
    else body = esc(m.text || "");

    return '<label class="mine-row' + (pending ? " pending" : "") + '">' +
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
      state.session.requests.load().then(
        function (data) { state.mine = data; if (state.view === "mine") renderMine(); },
        function (e) {
          el.view.innerHTML = '<p class="hint">설정을 불러오지 못했습니다: ' +
            esc(e.message || String(e)) + "</p>";
        }
      );
      return;
    }

    var names = myNicknames();
    var rows = myMessages();
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
      '<p class="mine-sub">대화방 표시명 <b>' + esc(names.join(", ")) + "</b> 으로 남긴 글 " +
      rows.length + "개입니다." +
      (names.length > 1 ? " (이름을 바꾸신 이력이 있어 여러 개가 묶여 있습니다.)" : "") +
      "</p>" +

      '<div class="mine-card">' +
      "<h3>앞으로의 수집</h3>" +
      '<div class="mine-modes">' + modes + "</div>" +
      '<button class="btn" id="saveMode">이 설정으로 저장</button>' +
      '<span class="mine-msg" id="modeMsg"></span>' +
      "</div>" +

      '<div class="mine-card">' +
      "<h3>이미 올린 글 내리기</h3>" +
      (pendingCount
        ? '<p class="mine-note">현재 <b>' + pendingCount + "개</b>를 내려달라고 요청해 두셨습니다. " +
          "아직 반영 전이라 철회할 수 있습니다.</p>"
        : '<p class="mine-note">내릴 글을 고르세요. 발행본에서 빠지며, ' +
          "되돌리려면 관리자에게 요청해야 합니다.</p>") +
      '<div class="mine-actions">' +
      '<button class="btn ghost" id="selAll">전체 선택</button> ' +
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
      "급하시면 관리자에게 말씀해 주세요.</p>" +
      "</section>";

    bindMineActions();
  }

  function bindMineActions() {
    var api = state.session.requests;
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
      // 되돌릴 수 없는 선택이므로 한 번 더 묻는다
      if (mode === "none" && !window.confirm(
        "수집 거부로 바꾸면 앞으로의 글이 저장되지 않습니다.\n" +
        "나중에 되돌려도 그동안의 글은 복구할 수 없습니다. 계속할까요?")) return;
      setMsg("modeMsg", "저장 중…");
      api.saveCollection(mode).then(
        function () { state.mine.collection = mode; setMsg("modeMsg", "저장했습니다."); },
        function (e) { setMsg("modeMsg", "저장 실패: " + (e.message || e)); }
      );
    };

    document.getElementById("selAll").onclick = function () {
      boxes().forEach(function (b) { b.checked = true; });
    };
    document.getElementById("selNone").onclick = function () {
      boxes().forEach(function (b) { b.checked = false; });
    };

    document.getElementById("submitDel").onclick = function () {
      var picked = boxes().filter(function (b) { return b.checked; });
      var ids = picked.map(function (b) { return b.getAttribute("data-mid"); });
      if (!ids.length) { setMsg("delMsg", "고른 글이 없습니다."); return; }

      var total = myMessages().length;
      var all = ids.length === total;
      // 1000개 제한은 보안 규칙에도 걸려 있다. 전체 선택이면 목록 대신 플래그로 보낸다.
      if (!all && ids.length > 1000) {
        setMsg("delMsg", "한 번에 1000개까지만 됩니다. 나눠서 요청해 주세요.");
        return;
      }
      if (!window.confirm(ids.length + "개의 글을 내려달라고 요청합니다.\n" +
                          "오늘 밤 반영되며, 그 전까지는 철회할 수 있습니다. 계속할까요?")) return;

      setMsg("delMsg", "요청하는 중…");
      api.saveDeletion(all ? [] : ids, all).then(
        function () {
          state.mine.deletion = { messageIds: all ? [] : ids, allMessages: all };
          renderMine();
        },
        function (e) { setMsg("delMsg", "요청 실패: " + (e.message || e)); }
      );
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
    var MODE_LABEL = { public: "공개", unpublished: "발행 제외", none: "수집 거부" };

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
        : '<p class="mine-note">모두 공개 설정입니다.</p>') +
      "</div>" +

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

    Array.prototype.forEach.call(el.view.querySelectorAll(".adm-member"), function (row) {
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
        if (!window.confirm(
              email + " 을 탈퇴 처리합니다.\n\n" +
              "· 대화·이미지·첨부를 더 이상 볼 수 없게 됩니다.\n" +
              (names
                ? "· 앞으로의 글도 수집하지 않습니다: " + names + "\n" +
                  "  (되돌려도 그동안의 글은 복구할 수 없습니다)\n"
                : "") +
              "· 이미 올라간 과거 글은 그대로 남습니다.\n" +
              "· 걸어둔 삭제 요청은 계속 반영됩니다.\n\n" +
              "계속할까요?")) return;
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
      };

      var btn = row.querySelector(".adm-role");
      btn.onclick = function () {
        var role = btn.getAttribute("data-role");
        var verb = role === "admin" ? "관리자로 지정" : "관리자에서 해제";
        if (!window.confirm(email + " 을 " + verb + "합니다. 계속할까요?")) return;
        var m = document.getElementById("roleMsg");
        if (m) m.textContent = "바꾸는 중…";
        state.session.admin.setRole(email, role).then(
          function () { state.admin = null; renderAdmin(); },
          function (e) { if (m) m.textContent = "실패: " + (e.message || String(e)); }
        );
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
        if (!participantIndex()[nickname] &&
            !window.confirm("'" + nickname + "' 은 참여자 명단에 없습니다.\n" +
                            "아직 발언이 없는 분이면 정상입니다. 계속할까요?")) return;
        say("승인 중…");
        // 표시명은 목록으로 보낸다. 나중에 이름이 바뀌면 여기에 덧붙인다.
        state.session.admin.approve(email, [nickname], "user").then(finish("승인"), fail);
      };
      row.querySelector('[data-act="reject"]').onclick = function () {
        if (!window.confirm(email + " 의 신청을 반려합니다. 계속할까요?")) return;
        say("반려 중…");
        state.session.admin.reject(email).then(finish("반려"), fail);
      };
    });
  }

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
    if (!s) { host.innerHTML = ""; return; }
    host.innerHTML =
      '<span class="chip" title="' + esc(s.user.email) + '">' +
      esc(s.user.name) + (s.role === "admin" ? " · 관리자" : "") + "</span>" +
      '<button class="icon-btn" id="signOutTop" title="로그아웃">로그아웃</button>';
    var b = document.getElementById("signOutTop");
    if (b) b.onclick = function () { s.signOut(); };
  }

  // ---------- 초기화 ----------
  function init(session) {
    // boot.js 가 Firestore 로드를 끝낸 뒤 호출하므로 여기서 다시 읽는다
    A = window.ARCHIVE || {};
    MSGS = A.messages || [];
    CATS = A.categories || [];
    STATS = A.stats || {};
    DIGESTS = A.digests || {};
    KNOW = A.knowledge || { nodes: [], edges: [] };
    CAT_LABEL = {}; CATS.forEach(function (c) { CAT_LABEL[c.id] = c.label; });

    state.session = session || null;
    renderSession();

    // '내 글 관리' 는 표시명이 연결된 로그인 사용자에게만 의미가 있다.
    // 로컬 미리보기(site/)에는 세션이 없으므로 탭 자체를 감춘다.
    var mineTab = el.tabs.querySelector('[data-view="mine"]');
    if (mineTab && !canManageMine()) mineTab.remove();
    var adminTab = el.tabs.querySelector('[data-view="admin"]');
    if (adminTab && !isAdmin()) adminTab.remove();
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
        // 첨부 탭은 자체 검색을 하므로 타임라인으로 튕기지 않는다
        if (state.view === "files") { render(); return; }
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

  // 보호모드(hosting)에서는 boot.js 가 로그인·데이터 로드를 끝낸 뒤 start() 를 부른다.
  // 로컬 미리보기(site/)에서는 data.js 가 이미 window.ARCHIVE 를 채워두므로 바로 시작.
  window.ArchiveApp = { start: init };
  if (window.ARCHIVE && window.ARCHIVE.messages) init(null);
})();
