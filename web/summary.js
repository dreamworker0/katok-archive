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

    // 폭 맞추기가 스스로 부른 toggle 을 '사람이 만졌다'로 세지 않게 하는 표시.
    var syncingFolds = false;

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
      ];
      /* 내비게이션을 상위 묶음으로 접는다.
       *
       * 열두 줄이 평평하게 늘어서 있으면 'AI 코딩 도구'와 'AI 모델'이 한 덩어리라는
       * 것을 알 수 없다. 묶음은 이미 코드에 있었고(ontology.CATEGORY_GROUPS) 관심
       * 분야 계산에만 쓰였다 — 화면이 안 쓴 것이 아까운 자리였다.
       *
       * 묶음 표는 발행 데이터에서 읽는다(A.groups). 화면에 하드코딩하면 온톨로지
       * 원본이 둘이 되고, 언젠가 한쪽만 고친다. 표가 없는 옛 발행본에서는 예전처럼
       * 평평한 한 줄로 그린다 — 화면이 비지 않는 편이 낫다. */
      var cats = ctx.data().CATS;
      var byId = {}; cats.forEach(function (c) { byId[c.id] = c; });
      var digestCount = 0;
      function navItem(c) {
        var d = ctx.data().DIGESTS[c.id]; if (!d) return "";
        digestCount++;
        return '<a class="cat-nav-item" href="/summary?cat=' + encodeURIComponent(c.id) +
          '" data-goto="doc-' + c.id + '" data-cat="' + esc(c.id) + '">' +
          '<span class="swatch" style="background:' + colorFor(c.id) + '"></span>' +
          esc(c.label) + " · " + (d.message_count || 0) + "</a>";
      }
      var groups = (ctx.data().A || {}).groups || [];
      if (groups.length) {
        var placed = {};
        html.push('<div class="cat-nav-groups">');
        groups.forEach(function (g) {
          var items = (g.categories || []).map(function (cid) {
            if (!byId[cid]) return "";
            placed[cid] = true;
            return navItem(byId[cid]);
          }).join("");
          if (!items) return;
          html.push('<div class="cat-nav-group"><h3>' + esc(g.label) + "</h3>" +
            '<div class="cat-nav">' + items + "</div></div>");
        });
        // 묶음에 없는 분류(ontology.PROVISIONAL_CATEGORIES — '아직 정해지지 않은
        // 자리')는 끝에 붙인다. 빠뜨리면 그 분류로 가는 입구가 사라진다.
        var rest = cats.filter(function (c) { return !placed[c.id]; })
          .map(navItem).join("");
        if (rest) {
          html.push('<div class="cat-nav-group"><h3>그 밖</h3>' +
            '<div class="cat-nav">' + rest + "</div></div>");
        }
        html.push("</div>");
      } else {
        html.push('<div class="cat-nav">' + cats.map(navItem).join("") + "</div>");
      }
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
      syncFacetFolds(el.view);
    }

    /** 갈래 접힘을 화면 폭에 맞춘다 — 데스크톱은 열림, 모바일은 접힘.
     *
     *  CSS 로는 못 한다. <details> 의 여닫힘은 `open` 속성이고, 열린 것을 CSS 로
     *  감추면 눌러도 안 열린다.
     *
     *  그림을 그린 직후에 재면 폭이 아직 0 인 경우가 있다(창이 늦게 자리를 잡을
     *  때 — 실측: 첫 그림에서 데스크톱인데도 전부 접혔다). 그래서 한 번 더,
     *  레이아웃이 끝난 다음 프레임에 잰다. 사람이 손으로 여닫은 뒤에는 건드리지
     *  않는다(`data-touched`) — 열어 둔 것을 다시 접으면 화면이 제멋대로 움직인다. */
    function syncFacetFolds(scope) {
      function apply() {
        if (!window.innerWidth) return;      // 아직 폭을 모른다. 다음 기회에.
        var wide = !window.matchMedia ||
                   window.matchMedia("(min-width: 761px)").matches;
        // 우리가 바꾸는 것도 toggle 을 부른다 — 그것까지 '사람이 만졌다'로 세면
        // 다음 프레임의 재기가 아무것도 못 고친다.
        syncingFolds = true;
        Array.prototype.forEach.call(scope.querySelectorAll(".facet-fold"),
          function (d) {
            if (d.getAttribute("data-touched")) return;
            d.open = wide;
          });
        syncingFolds = false;
      }
      apply();
      if (window.requestAnimationFrame) window.requestAnimationFrame(apply);
    }

    /** "· 정리 2026-09-04" — 그 뒤로 주제가 늘었으면 "· 그 뒤 +12" 까지.
     *
     *  낡음이 화면에 보이면 사람이 안다. 요지는 밤마다 낡은 것만 다시 쓰므로
     *  (scripts/digest_prose.py) 어느 분류가 며칠 뒤처져 있을 수 있고, 그것을
     *  숨기면 읽는 사람은 이 글이 오늘 것인 줄 안다. */
    function tidiedAt(d) {
      var as = d.as_of || {};
      if (!as.date) return "";
      var out = " · 정리 " + esc(as.date);
      var grown = (d.threads || []).length - (as.thread_count || 0);
      if (grown > 0) out += " · 그 뒤 +" + grown;
      return out;
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
      /* 갈래가 있으면 갈래가 접힘 단위다.
       *
       * projects 는 주제가 106개다. '10개 + 더보기' 규칙을 그대로 쓰면 앞의 열 개가
       * 최근 날짜순으로 뽑히고 나머지 96개가 한 상자에 들어간다 — 그 상자는 열어도
       * 벽이다. 갈래로 나누면 스물 남짓씩 일곱 덩어리가 되고, 덩어리마다 무엇이
       * 들어 있는지 소제목이 말해 준다.
       *
       * 그래서 갈래마다 다시 '10개 + 더보기'를 겹치지 않는다. 접힘이 두 층이 되면
       * 몇 번을 눌러야 목록이 다 보이는지 알 수 없다. */
      var threads = "";
      var facets = (d.facets || []).filter(function (f) {
        return (f.thread_ids || []).length;
      });
      if (facets.length) {
        var order = {};
        threadList.forEach(function (t, i) { order[t.id] = i; });
        threads = facets.map(function (f) {
          var rows = (f.thread_ids || []).map(function (id) {
            return ctx.data().THREAD_BY_ID[id];
          }).filter(Boolean).sort(function (a, b) {
            return (order[a.id] === undefined ? 1e9 : order[a.id]) -
                   (order[b.id] === undefined ? 1e9 : order[b.id]);
          });
          if (!rows.length) return "";
          // 열린 채로 그리고, 좁은 화면에서만 접는다(syncFacetFolds). 반대로 두면
          // 폭을 아직 모르는 첫 그림에서 목록이 통째로 접혀 사라진 것처럼 보인다.
          return '<details class="more-fold facet-fold" open><summary>' +
            esc(f.label) + " · " + rows.length + "</summary>" +
            rows.map(tl).join("") + "</details>";
        }).join("");
      } else {
        var threadTop = threadList.slice(0, 10), threadRest = threadList.slice(10);
        threads = threadTop.map(tl).join("");
        if (threadRest.length) {
          threads += '<details class="more-fold"><summary>대화 주제 ' + threadRest.length + "개 더</summary>" +
            threadRest.map(tl).join("") + "</details>";
        }
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
        '<span class="doc-meta">' + (d.message_count || 0) + "개 메시지 · " +
        (d.threads || []).length + "개 주제" + tidiedAt(d) + "</span></div>" +
        (d.headline ? '<p class="doc-headline">' + esc(d.headline) + "</p>" : "") +
        '<p class="doc-overview">' + esc(d.overview || "") + "</p>" +
        // 요지 산문의 절. 없으면 예전과 같다(주제가 적은 분류).
        (d.sections || []).map(function (s) {
          return '<h3 class="doc-sec">' + esc(s.title) + "</h3>" +
            '<p class="doc-sec-body">' + esc(s.body) + "</p>";
        }).join("") +
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
      // 사람이 여닫은 갈래는 폭 맞추기가 건드리지 않는다(syncFacetFolds).
      Array.prototype.forEach.call(scope.querySelectorAll(".facet-fold"), function (d) {
        d.addEventListener("toggle", function () {
          if (!syncingFolds) d.setAttribute("data-touched", "1");
        });
      });
    }

    return { renderSummary: renderSummary, bindKeywordChips: bindKeywordChips };
  };
})();
