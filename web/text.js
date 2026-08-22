/* ============ 글자·마크다운 다루기 ============
 *
 * app.js 에서 떼어낸 순수 함수들. 들어오는 값만 보고 돌려주는 값만 만든다 —
 * DOM 도 전역 상태도 건드리지 않는다.
 *
 * 왜 떼어냈나
 *     app.js 3,389줄 안에 있는 동안 이 함수들에는 **동작 검사가 하나도 없었다.**
 *     닫힌 IIFE 라 node 에서 부를 방법이 없었고, 그래서 `tests/test_ui_contract.py`
 *     가 파이썬에서 app.js 의 **소스 글자**를 정규식으로 훑는 방식을 썼다. 그것은
 *     "이 패턴이 파일에 있다"를 확인할 뿐, `renderMarkdown` 이 표를 제대로 그리는지
 *     `esc` 가 따옴표를 막는지는 보지 않는다.
 *
 *     여기 모인 것이 마침 가장 위험한 축이다 — 보고서 본문을 HTML 로 바꾸는 길
 *     전체가 이 안에 있다. 발행하는 것이 요약과 결과물뿐인 아카이브에서 보고서는
 *     유일한 기록이고, 그것을 그리는 코드가 검사 밖에 있었다.
 *
 * 검사는 `tests/text.test.js` (`npm test`).
 */
(function () {
  "use strict";

  /* 조각만 로마자인 태그를 위한 음역 대응. `scripts/tags.py` 의 TRANSLIT 과 같아야
   * 한다 — 발행 때 'Claude Code' 를 '클로드 코드' 로 합쳐 놓았으니, 카드 칩(사람이
   * 쓴 원래 표기)을 눌렀을 때 여기서도 같은 곳에 닿아야 태그가 열린다.
   * 어긋나면 태그 대신 글자 검색으로 떨어진다. tests/test_ui_contract.py 가 지킨다. */
  var TAG_TRANSLIT = {
    gemini: "제미나이", claude: "클로드", opus: "오퍼스", sonnet: "소네트",
    ontology: "온톨로지", playground: "플레이그라운드", modeling: "모델링",
    tutorial: "튜토리얼", workspace: "워크스페이스", studio: "스튜디오",
    code: "코드", pro: "프로", plus: "플러스", max: "맥스", flash: "플래시",
    github: "깃허브", youtube: "유튜브", python: "파이썬", discord: "디스코드",
    facebook: "페이스북", hackathon: "해커톤", agent: "에이전트",
    vercel: "버셀", firebase: "파이어베이스", cloudflare: "클라우드플레어",
    codex: "코덱스", perplexity: "퍼플렉시티", lovable: "러버블",
    azure: "애저", chatgpt: "챗gpt", google: "구글", notebooklm: "노트북lm"
  };

  function tagFold(s) {
    return String(s || "").trim().toLowerCase().split(/[\s\-_.]+/)
      .filter(Boolean)
      .map(function (p) { return TAG_TRANSLIT[p] || p; })
      .join("");
  }

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

  function msAgo(value) {
    if (!value) return null;
    var t = Date.parse(String(value));
    return isNaN(t) ? null : (Date.now() - t);
  }

  function agoText(value) {
    var ms = msAgo(value);
    if (ms === null) return "";
    if (ms < 60000) return "방금";
    var m = Math.floor(ms / 60000);
    if (m < 60) return m + "분 전";
    var h = Math.floor(m / 60);
    if (h < 24) return h + "시간 전";
    return Math.floor(h / 24) + "일 전";
  }

  var api = {
    tagFold: tagFold,
    esc: esc,
    linkify: linkify,
    highlightText: highlightText,
    hashHue: hashHue,
    initial: initial,
    fmtSize: fmtSize,
    fmtDate: fmtDate,
    mdInline: mdInline,
    mdRow: mdRow,
    hostOf: hostOf,
    splitLinks: splitLinks,
    linkifyHosts: linkifyHosts,
    renderMarkdown: renderMarkdown,
    msAgo: msAgo,
    agoText: agoText,
  };

  // 브라우저에서는 전역으로 (images.js 의 window.ArchiveImages, graph.js 의
  // window.KGraph 와 같은 방식 — 이 저장소의 프런트는 빌드 단계가 없다).
  if (typeof window !== "undefined") window.ArchiveText = api;
  // node 에서는 검사가 require 로 가져간다. 브라우저에는 module 이 없어 그냥 지나간다.
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})();
