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
      return '<div class="thread-line" data-start="t-' + esc(t.id) + '"><b>' + esc(t.title) +
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
      el.view.innerHTML = pickBar + '<p class="hint">해당하는 주제가 없어요.</p>';
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
    var rep = t.report || "", inline = [], rest = [], seen = {};
    (t.links || []).forEach(function (l) {
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
    return { inline: inline, rest: rest };
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
  function detailBlock(t, inlineLinks) {
    if (!t.report) return "";
    var open = !!state.q;
    var n = mediaOf(t.id).length;
    return '<div class="tc-detail' + (open ? " on" : "") + '" data-tid="' + esc(t.id) + '">' +
      '<div class="tc-detail-bar">' +
      '<button class="tc-toggle" type="button">' +
      (open ? "간단히" : "보고서 읽기") + "</button>" +
      '<button class="tc-dl" type="button" title="이 보고서를 .md 파일로 저장합니다">' +
      "⬇ .md</button></div>" +
      '<div class="tc-detail-body md">' +
      highlightText(linkifyHosts(renderMarkdown(t.report), inlineLinks), state.q) +
      (n ? '<div class="tc-media" data-media="' + esc(t.id) + '"></div>' : "") +
      "</div></div>";
  }

  /** 이 주제에서 오간 사진·첨부. 보고서에 손으로 적지 않고 여기서 찾는다. */
  function mediaOf(tid) {
    return MEDIA.filter(function (m) { return m.thread_id === tid; });
  }

  /* 보고서에 그날 오간 사진·첨부를 붙인다.
   *
   * 펼칠 때 채운다. 165개 카드의 이미지를 미리 다 걸어 두면 Storage 인증
   * 요청이 한꺼번에 나간다. data-filled 로 두 번 채우는 것을 막는다.
   */
  function fillMedia(box) {
    var host = box.querySelector(".tc-media");
    if (!host || host.getAttribute("data-filled")) return;
    var rows = mediaOf(host.getAttribute("data-media"));
    if (!rows.length) return;
    host.setAttribute("data-filled", "1");

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
    host.innerHTML = "<h4>이 주제에서 오간 사진·첨부</h4>" +
      (imgs.length ? '<div class="imgs">' + imgs.join("") + "</div>" : "") +
      (files.length ? '<div class="tcf-list">' + files.join("") + "</div>" : "");
    bindImages(host);
    bindFiles(host);
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
    var blob = new Blob([head + t.report + "\n"], { type: "text/markdown;charset=utf-8" });
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
      detailBlock(t, lk.inline) +
      (people ? '<div class="tc-people">' + people + "</div>" : "") +
      (links ? '<div class="tc-links">' + links + more + "</div>" : "") +
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
        b.textContent = on ? "간단히" : "보고서 읽기";
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
        if (!window.confirm(
              "'" + title + "' 을 발행에서 뺍니다.\n\n" +
              "오늘 밤 갱신부터 아무에게도 보이지 않습니다.\n" +
              "원본은 남아 있고, 관리 탭에서 되돌릴 수 있습니다.\n\n" +
              "계속할까요?")) return;
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
    if (!items.length) { el.view.innerHTML = '<p class="hint">표시할 이미지가 없어요.</p>'; return; }
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
    // 최근 첨부부터
    shown.sort(function (a, b) { return mediaKey(b).localeCompare(mediaKey(a)); });

    var html = ['<p class="room-sub" style="margin:0 0 12px">공유된 파일 ' + rows.length +
      "개 · 원본 보관 " + have.length + "개" +
      (shown.length !== rows.length ? " · 표시 " + shown.length + "개" : "") + "</p>"];

    if (!shown.length) {
      html.push('<p class="hint">조건에 맞는 파일이 없어요.</p>');
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
      '<p class="hint" style="text-align:left;padding:6px 0 0;font-size:12px">' +
      "이 칸은 <b>본인에게만</b> 보입니다. 다른 사람의 기록은 볼 수 없습니다.</p></div>";
  }
  function numCell(v, k) {
    return '<div class="my-num"><div class="v">' + v + '</div><div class="k">' + esc(k) + "</div></div>";
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
      if (!window.confirm(
            ids.length + "개를 내려달라고 요청합니다." +
            (kept.length ? " (다른 탭에서 이미 고른 " + kept.length + "개 포함)" : "") +
            "\n사진·첨부는 저장소에서도 지워집니다.\n" +
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
  // 원문(messages)은 더 이상 싣지 않는다. 스레드 요약이 있으면 데이터가 준비된 것이다.
  if (window.ARCHIVE && window.ARCHIVE.threads) init(null);
})();
