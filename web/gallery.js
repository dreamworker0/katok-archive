/* ============ 갤러리·자료 화면 (web/gallery.js) ============
 *
 * app.js 에서 떼어냈다(2026-09-02). 사진·동영상 격자, 첨부 파일 목록, 그리고 둘이
 * 함께 쓰는 라이트박스와 사진·첨부 묶기(bindImages·bindFiles). 내 글 화면도 이
 * 묶기와 라이트박스를 빌려 쓴다(app.js 가 넘겨 준다). 약 240줄.
 *
 * 떼어내는 방식은 admin.js·stats.js·mine.js 와 같다 — 팩토리 하나에 공유하는 것만
 * 넘긴다. init() 에서 다시 읽히는 데이터 전역은 값이 아니라 읽는 함수(ctx.data())로,
 * 다른 조각의 함수는 늦게 읽는 함수(ctx.stats())로 받는다.
 *
 * 돌려주는 것: renderGallery · renderFiles · fileIcon · bindFiles · bindImages · openLightbox · closeLightbox.
 */
(function () {
  "use strict";

  window.ArchiveGallery = function (ctx) {
    var state = ctx.state, el = ctx.el, esc = ctx.esc, emptyState = ctx.emptyState,
        fmtSize = ctx.fmtSize, jumpToTimeline = ctx.jumpToTimeline;

    function mediaKey(m) { return (m.date || "") + " " + (m.time || ""); }

    // ---------- 갤러리 ----------
    function renderGallery() {
      var items = [];
      // 개인정보가 찍혀 발행에서 뺀 사진 수. 갤러리에는 자리표를 수십 개 늘어놓지
      // 않고(그 자체가 소음이다) 머리에 한 줄로 알린다 — 숫자가 안 맞는 이유는
      // 어딘가에 적혀 있어야 한다.
      var hiddenShots = 0;
      ctx.data().MEDIA.forEach(function (m) {
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
      var rows = ctx.data().MEDIA.filter(function (m) { return m.kind === "file"; });
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

    return { renderGallery: renderGallery, renderFiles: renderFiles, fileIcon: fileIcon, bindFiles: bindFiles, bindImages: bindImages, openLightbox: openLightbox, closeLightbox: closeLightbox };
  };
})();
