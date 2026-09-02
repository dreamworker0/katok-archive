/* ============ 타임라인 — 주제 카드 (web/timeline.js) ============
 *
 * app.js 에서 떼어냈다(2026-09-02, 마지막 조각). 주제 카드 한 장의 모든 것이 여기
 * 있다 — 걸러내기(threadMatches·pickThreads), 정렬, 카드 본문, 사람 보고서와 AI 검증
 * 주석을 누를 때 채우는 일, 사진·첨부·링크를 본문 자리에 끼우는 일, .md 내려받기,
 * 그리고 화면이 뜬 뒤 도착한 AI 주석을 이미 그려진 카드에 끼워 넣는 일. 약 620줄.
 *
 * 떼어내는 방식은 다른 조각과 같다 — 팩토리에 공유하는 것만 넘긴다. 데이터 전역은
 * init() 에서 다시 읽히므로 읽는 함수(ctx.data())로, 통계 조각의 함수는 늦게 읽는
 * 함수(ctx.stats())로 받는다. 요지 화면의 태그 칩 묶기(bindKeywordChips)와 갤러리의
 * 사진·첨부 묶기(bindImages·bindFiles)는 app.js 의 위임 함수를 통해 받는다.
 *
 * attachDigests 는 여기 없다 — app.js 의 전역 DIGESTS 를 바꿔치는 일이라 그쪽에 남았다.
 *
 * 돌려주는 것: renderTimeline · pickThreads · jumpToTimeline · attachAiReports · threadMatches.
 */
(function () {
  "use strict";

  window.ArchiveTimeline = function (ctx) {
    var state = ctx.state, el = ctx.el, esc = ctx.esc, colorFor = ctx.colorFor,
        emptyState = ctx.emptyState, confirmAction = ctx.confirmAction, fmtDate = ctx.fmtDate,
        highlightText = ctx.highlightText, hostOf = ctx.hostOf, linkifyHosts = ctx.linkifyHosts,
        renderMarkdown = ctx.renderMarkdown, splitLinks = ctx.splitLinks,
        bindFiles = ctx.bindFiles, bindImages = ctx.bindImages, bindKeywordChips = ctx.bindKeywordChips,
        fileIcon = ctx.fileIcon, isAdmin = ctx.isAdmin, render = ctx.render, setView = ctx.setView;

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

    function threadKey(t) {
      return (t.start_date || "") + " " + (t.start_time || "");
    }

    function renderTimeline() {
      var rows = ctx.data().THREADS.filter(threadMatches);
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
        "개" + (rows.length !== ctx.data().THREADS.length ? " / 전체 " + ctx.data().THREADS.length : "") +
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
        var t = ctx.data().THREAD_BY_ID[box.getAttribute("data-tid")];
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


    /** boot.js 가 AI 검증 주석을 받아 오면 부른다. 스레드에 붙이고 보이는 카드에 단추를 끼운다. */
    function attachAiReports(items) {
      (items || []).forEach(function (r) {
        var t = ctx.data().THREAD_BY_ID[r.id];
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
      var t = ctx.data().THREADS.filter(function (x) { return x.id === tid; })[0];
      if (!t || !t.ai_report) return;
      wrap.setAttribute("data-filled", "1");
      wrap.innerHTML = aiReportBlock(t);
    }

    function fillReport(box) {
      var body = box.querySelector(".tc-detail-body");
      if (!body || body.getAttribute("data-filled")) return;
      var tid = box.getAttribute("data-tid");
      var t = ctx.data().THREADS.filter(function (x) { return x.id === tid; })[0];
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
      return ctx.data().MEDIA.filter(function (m) { return m.thread_id === tid; });
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
      var thread = ctx.data().THREADS.filter(function (t) { return t.id === tid; })[0];
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
        /^!\[\[link:([ctx.data().A-Za-z0-9_-]+)\]\]$/gm,
        function (all, id) {
          var links = (t.links || []).filter(function (x) { return x.id === id; });
          return links.map(function (l) {
            return "> 🔗 [" + hostOf(l.url) + "](" + l.url + ") — " +
              l.nickname + " · " + l.date + " " + (l.time || "");
          }).join("\n");
        }
      ).replace(/^!\[\[\s*([ctx.data().A-Za-z0-9_-]+)\s*\]\]$/gm,
        function (all, id) {
          var m = ctx.data().MEDIA.filter(function (x) { return x.id === id; })[0];
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
        esc(ctx.data().CAT_LABEL[t.category] || t.category) + "</span>" +
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
          var t = ctx.data().THREADS.filter(function (x) { return x.id === tid; })[0];
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

    return { renderTimeline: renderTimeline, pickThreads: pickThreads, jumpToTimeline: jumpToTimeline, attachAiReports: attachAiReports, threadMatches: threadMatches };
  };
})();
