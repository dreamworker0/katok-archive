/* ============ 주제별 지식(요지) 화면 (web/summary.js) ============
 *
 * app.js 에서 떼어냈다(2026-09-02). 첫 화면이다 — 분류마다 요지 산문 한 편과 결과물·
 * 링크·곁 주제를 펴 보이는 문서. 요지는 화면이 뜬 뒤에 오므로(boot.js loadRest)
 * 오기 전에는 '불러오는 중' 을 보인다. 약 270줄.
 *
 * 떼어내는 방식은 admin.js·stats.js·mine.js 와 같다 — 팩토리 하나에 공유하는 것만
 * 넘긴다. init() 에서 다시 읽히는 데이터 전역은 값이 아니라 읽는 함수(ctx.data())로,
 * 다른 조각의 함수는 늦게 읽는 함수(ctx.stats())로 받는다.
 *
 * 돌려주는 것: renderSummary · bindKeywordChips.
 */
(function () {
  "use strict";

  window.ArchiveSummary = function (ctx) {
    var state = ctx.state, el = ctx.el, esc = ctx.esc, colorFor = ctx.colorFor,
        emptyState = ctx.emptyState, tagFold = ctx.tagFold, jumpToTimeline = ctx.jumpToTimeline,
        pickThreads = ctx.pickThreads, runSearch = ctx.runSearch, setView = ctx.setView,
        writeHash = ctx.writeHash;

    // ---------- 주제별 지식(요약) ----------
    function renderSummary() {
      var totals = ctx.data().STATS.totals || {};
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
      ctx.data().CATS.forEach(function (c) {
        var d = ctx.data().DIGESTS[c.id]; if (!d) return;
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
      ctx.data().CATS.forEach(function (c) {
        var d = ctx.data().DIGESTS[c.id]; if (!d) return;
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
        return ctx.data().THREAD_BY_ID[a.id];
      }).filter(Boolean).sort(function (a, b) {
        return String(b.end_date || "").localeCompare(String(a.end_date || ""));
      });
      var also = alsoRows.map(function (t) {
        return '<div class="thread-line also" data-start="t-' + esc(t.id) + '"><b>' +
          esc(t.title) + '</b><span class="tl-home" style="--c:' + colorFor(t.category) +
          '">' + esc(ctx.data().CAT_LABEL[t.category] || t.category) + "</span>" +
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
      var ids = ctx.data().TAG_THREADS[tagFold(word)];
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

    return { renderSummary: renderSummary, bindKeywordChips: bindKeywordChips };
  };
})();
