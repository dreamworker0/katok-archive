/* ============ 내 글 관리 (web/mine.js) ============
 *
 * app.js 에서 떼어냈다(2026-09-02). 본인이 쓴 글을 원문으로 보고, 무엇을 지울지
 * 고르고, 수집 동의를 정하는 화면 — 약 380줄. 이 화면이 있어야 "언제든 본인 글을
 * 내릴 수 있습니다" 를 말할 수 있다.
 *
 * 공유하는 것은 ctx 로 받는다. STATS 는 init() 에서 다시 읽히므로 ctx.data() 로,
 * 통계 쪽 조각(card·myTraitReport)은 ctx.stats() 로 늦게 받는다(순환).
 * 나머지는 text.js 순수 함수와 app.js 의 공용 조각(확인 대화상자·사진/첨부 묶기·
 * 라이트박스)이다.
 *
 * 돌려주는 것: canManageMine · mineKind · myNicknames · renderMine.
 */
(function () {
  "use strict";

  window.ArchiveMine = function (ctx) {
    var state = ctx.state, el = ctx.el, esc = ctx.esc, agoText = ctx.agoText, msAgo = ctx.msAgo,
        fmtSize = ctx.fmtSize, confirmAction = ctx.confirmAction, bindFiles = ctx.bindFiles,
        bindImages = ctx.bindImages, fileIcon = ctx.fileIcon, openLightbox = ctx.openLightbox;

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

    /** 항목 종류 — 사진·동영상·첨부를 글과 섞어 두면 찾기 어렵다.
     *
     * 동영상이 없던 동안 내 동영상은 "동영상" 이라는 **글 한 줄**로 보였다.
     * 무엇을 지울지 고르려면 봐야 하는데, 볼 것이 없으니 고를 수가 없었다. */
    function mineKind(m) {
      if (m.kind === "image") return "image";
      if (m.kind === "video") return "video";
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
            m.images.map(function (src, i) {
              var th = (m.thumbs || m.images)[i] || src;
              return '<img class="mine-thumb" data-img="' + esc(th) +
                '" data-full="' + esc(src) +
                '" alt="" title="클릭하면 크게 봅니다" />';
            }).join("") +
            '<span class="mine-zoom">클릭하면 크게 보기</span></span>'
          : m.pii_hidden
          // 개인정보가 찍혀 발행에서 뺀 사진. 본인 것이라도 올라가지 않는다 —
          // Storage 규칙은 '멤버냐'만 보므로 올리면 방 전체에 보인다. '수집 대기'로
          // 보이면 언젠가 채워질 것처럼 읽히므로 이유를 적는다.
          ? '<span class="mine-muted">🔒 사진' +
            (m.pii_hidden > 1 ? " " + m.pii_hidden + "장" : "") +
            " (개인정보가 있어 발행하지 않았습니다)</span>"
          : '<span class="mine-muted">🖼 사진' +
            (m.image_count > 1 ? " " + m.image_count + "장" : "") +
            // 유실은 기다려도 오지 않는다. 대기라고 쓰면 언젠가 채워질 것처럼 읽힌다.
            (m.image_lost ? " (원본 없음)" : " (수집 대기)") + "</span>";
      } else if (kind === "video") {
        // 사진과 같은 자리·같은 조작. 칸에는 포스터를 걸고 누르면 재생한다
        // (openLightbox 가 data-video 를 보고 <video> 로 연다).
        body = m.videos && m.videos.length
          ? '<span class="mine-thumbs">' +
            m.videos.map(function (src, i) {
              var th = (m.thumbs || [])[i] || src;
              return '<span class="im-video"><img class="mine-thumb" data-img="' + esc(th) +
                '" data-full="' + esc(src) + '" data-video="1"' +
                ' alt="" title="클릭하면 재생합니다" /><span class="play">▶</span></span>';
            }).join("") +
            '<span class="mine-zoom">클릭하면 재생</span></span>'
          : '<span class="mine-muted">🎬 동영상' +
            // 유실은 기다려도 오지 않는다. 대기라고 쓰면 언젠가 채워질 것처럼 읽힌다.
            (m.image_lost ? " (원본 없음)" : " (수집 대기)") + "</span>";
      } else if (kind === "file") {
        // 파일은 이름만으로 내용을 알 수 없다. 열어보고 지울 수 있어야 한다.
        var fname = m.file ? m.file.name : (m.text || "").replace(/^파일:\s*/, "");
        body = '<span class="mine-file">' +
          '<span class="mf-icon">' + fileIcon(fname) + "</span>" +
          '<span class="mf-body"><span class="mf-name">' + esc(fname) + "</span>" +
          '<span class="mf-meta">' +
          (m.file
            ? fmtSize(m.file.size) + " · 원본 보관 중"
            : m.file_expired
              ? "만료돼 원본을 구할 수 없는 파일"
              : "원본 수집 대기 중인 파일") +
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
      var counts = { text: 0, image: 0, video: 0, file: 0 };
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
        "글 " + counts.text + " · 사진 " + counts.image +
        (counts.video ? " · 동영상 " + counts.video : "") +
        " · 첨부 " + counts.file + "개입니다." +
        (names.length > 1 ? " (이름을 바꾸신 이력이 있어 여러 개가 묶여 있습니다.)" : "") +
        "</p>" +

        ctx.stats().myTraitReport(all) +

        '<div class="mine-card">' +
        "<h3>앞으로의 수집</h3>" +
        '<div class="mine-modes">' + modes + "</div>" +
        '<button class="btn" id="saveMode">이 설정으로 저장</button>' +
        '<span class="mine-msg" id="modeMsg"></span>' +
        /* 한 글만 빼고 싶을 때 쓰는 방법. 이걸 안 알려주면 "수집 중단" 말고는 길이
         * 없는 줄 알게 된다. 소급되지 않는다는 단서를 반드시 같이 적는다 —
         * 이미 보낸 글도 빠지는 줄 알면 안 빠진 걸 나중에 알게 된다.
         * (규칙: scripts/collection_policy.py) */
        '<p class="mine-note mine-keyword">' +
        "설정과 별개로, 카카오톡에서 <b>메시지 본문에 " +
        '<code class="mine-kbd">[제외]</code> 를 넣으면</b> 그 글은 처음부터 ' +
        "수집하지 않습니다. 전각 <code class=\"mine-kbd\">［제외］</code> 도 " +
        "같이 인식합니다.<br />" +
        "다만 <b>앞으로 보내는 글에만</b> 적용됩니다. 이미 보낸 글은 " +
        "아래에서 골라 내려 주세요." +
        "</p>" +
        "</div>" +

        /* 관심 주제 화면에서 빠지기.
         * 화면에서만 감추는 것이 아니라 발행 데이터에서 빠진다 — 감추기만 하면
         * 브라우저 개발자도구로 그대로 읽힌다. 반영은 다음 밤 갱신 때. */
        '<div class="mine-card">' +
        "<h3>사람별 관심 주제</h3>" +
        '<p class="mine-note">통계 화면에 <b>사람마다 관심 화제</b>를 정리해 보여줍니다. ' +
        "내 이름이 거기 나오지 않게 할 수 있습니다. 끄면 발행 데이터에서 아예 빠집니다 " +
        "(내가 쓴 글 자체는 그대로 남습니다).</p>" +
        '<label class="mine-toggle"><input type="checkbox" id="hideInterests"' +
        (state.mine.hideInterests ? " checked" : "") + " /> " +
        "<span>관심 주제 화면에 내 이름 내지 않기</span></label> " +
        '<button class="btn" id="saveInterests">저장</button>' +
        '<span class="mine-msg" id="intMsg"></span>' +
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
        // 동영상 탭은 올린 사람에게만 뜬다. 늘 0인 탭을 모두에게 두면 눌러 보고서야
        // 없다는 것을 알게 되고, 그런 탭이 대부분이다.
        [["all", "전체", all.length], ["text", "글", counts.text],
         ["image", "사진", counts.image]]
          .concat(counts.video ? [["video", "동영상", counts.video]] : [])
          .concat([["file", "첨부", counts.file]])
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

      var saveInt = document.getElementById("saveInterests");
      if (saveInt) {
        saveInt.onclick = function () {
          var box = document.getElementById("hideInterests");
          var hide = !!(box && box.checked);
          setMsg("intMsg", "저장 중…");
          api.savePreferences(state.mine.collection, hide).then(
            function () {
              state.mine.hideInterests = hide;
              setMsg("intMsg", hide
                ? "저장했습니다 — 다음 밤 갱신에서 빠집니다."
                : "저장했습니다.");
            },
            function (e) { setMsg("intMsg", "저장 실패: " + (e.message || e)); }
          );
        };
      }

      document.getElementById("saveMode").onclick = function () {
        var picked = el.view.querySelector('input[name="collectionMode"]:checked');
        if (!picked) return;
        var mode = picked.value;
        var save = function () {
          setMsg("modeMsg", "저장 중…");
          api.savePreferences(mode, state.mine.hideInterests).then(
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

    return { canManageMine: canManageMine, mineKind: mineKind, myNicknames: myNicknames,
             renderMine: renderMine };
  };
})();
