/* ============ 태그 화면 (web/tags.js) ============
 *
 * app.js 에서 떼어냈다(2026-09-02). 태그 구름과 이름 좁히기, 최대 셋까지 겹쳐 보기.
 * 약 140줄.
 *
 * 떼어내는 방식은 admin.js·stats.js·mine.js 와 같다 — 팩토리 하나에 공유하는 것만
 * 넘긴다. init() 에서 다시 읽히는 데이터 전역은 값이 아니라 읽는 함수(ctx.data())로,
 * 다른 조각의 함수는 늦게 읽는 함수(ctx.stats())로 받는다.
 *
 * 돌려주는 것: renderTags.
 */
(function () {
  "use strict";

  window.ArchiveTags = function (ctx) {
    var state = ctx.state, el = ctx.el, esc = ctx.esc, emptyState = ctx.emptyState,
        tagFold = ctx.tagFold, pickThreads = ctx.pickThreads, writeHash = ctx.writeHash;

    /* ---------- 태그 입구 ----------
     *
     * 분류 12개로는 묻히는 화제가 있다 — 'clasp' 이야기는 다섯 군데 흩어져 있고
     * 어느 분류에도 'clasp' 이라 적혀 있지 않다. 보고서 태그를 한자리에 모아 그
     * 길을 낸다. 표기가 갈린 태그는 발행할 때 이미 합쳐 두었다(scripts/tags.py).
     *
     * 한 번만 쓰인 태그 800여 개는 목록에 올리지 않는다. 다 늘어놓으면 목록이
     * 아니라 벽이 되고, 그 태그는 어차피 주제 하나로만 이어진다(검색으로 찾는다).
     */
    /** 고른 태그들이 **모두** 붙은 주제. 하나도 안 골랐으면 null. */
    function tagPickIds() {
      var picked = state.tagPick || [];
      if (!picked.length) return null;
      var sets = picked.map(function (t) { return ctx.data().TAG_THREADS[tagFold(t)] || []; });
      return sets[0].filter(function (id) {
        return sets.every(function (s) { return s.indexOf(id) !== -1; });
      });
    }

    function renderTags() {
      // 사람 이름과 지명·기관 이름은 구름에서 빼고 아래에 따로 모은다. 태그 구름은
      // '무엇을 이야기했나' 의 자리다 — 누가·어디는 참여자 필터와 보고서 본문 몫이다.
      // 기관 계정이 방에 있으면 그 이름은 참여자이면서 기관이다('○○복지관' 계정).
      // 그럴 때는 사람 쪽이 아니라 지명·기관 쪽에 둔다 — 표에 적은 사람의 판단이
      // 참여자 이름에서 자동으로 뽑은 것보다 낫다.
      var rows = (ctx.data().TAGIDX.tags || []).filter(function (r) { return !r.person && !r.place; });
      var people = (ctx.data().TAGIDX.tags || []).filter(function (r) { return r.person && !r.place; });
      var places = (ctx.data().TAGIDX.tags || []).filter(function (r) { return r.place; });
      if (!rows.length) {
        el.view.innerHTML = emptyState("search", "아직 모인 태그가 없어요",
          "주제 보고서에 태그가 붙으면 이곳에 모입니다.");
        return;
      }
      var picked = state.tagPick || (state.tagPick = []);
      var full = picked.length >= ctx.TAG_PICK_MAX;
      var hitIds = tagPickIds() || [];
      var max = rows[0].count;

      function chip(r) {
        var on = picked.indexOf(r.tag) !== -1;
        // 지금 고른 것들과 함께 붙은 주제가 없으면 눌러도 빈 목록이다 — 미리 막는다.
        var dead = !on && picked.length &&
          !hitIds.some(function (id) {
            return (ctx.data().TAG_THREADS[tagFold(r.tag)] || []).indexOf(id) !== -1;
          });
        // 많이 쓰인 태그가 눈에 먼저 들어오게 글자 크기를 조금 키운다(1.0~1.5배).
        var scale = (1 + 0.5 * (r.count - 1) / Math.max(1, max - 1)).toFixed(2);
        return '<button class="tag-chip' + (on ? " on" : "") + '" data-tag="' +
          esc(r.tag) + '" style="font-size:' + scale + 'em"' +
          (dead || (full && !on) ? " disabled" : "") + '>' +
          esc(r.tag) + '<span class="tag-n">' + r.count + "</span></button>";
      }

      /* 고른 태그와 결과 수를 늘 보여 준다. 고르는 동안 몇 건인지 모르면 '보기'를
       * 눌러야 알게 되고, 0건이면 헛수고가 된다. */
      var bar = "";
      if (picked.length) {
        bar = '<div class="tag-bar">' +
          picked.map(function (t) {
            return '<button class="tag-chip on" data-unpick="' + esc(t) + '">' +
              esc(t) + '<span class="tag-n">×</span></button>';
          }).join("") +
          '<span class="tag-bar-n">' +
          (hitIds.length ? "주제 " + hitIds.length + "개"
                         : "함께 붙은 주제가 없습니다") + "</span>" +
          (hitIds.length ? '<button class="btn" id="tagGo">보기</button>' : "") +
          '<button class="btn ghost" id="tagClear">비우기</button></div>';
      }

      var html = [
        '<div class="gal-head"><p class="room-sub">태그 ' + rows.length +
        "개 · 최대 " + ctx.TAG_PICK_MAX +
        "개까지 골라 겹치는 주제를 볼 수 있습니다</p></div>",
        bar,
        '<label class="tag-search"><span class="sr-only">태그 검색</span>' +
        '<input id="tagFilter" type="search" placeholder="태그 이름으로 좁히기" ' +
        'autocomplete="off" /><span class="tag-hits" id="tagHits"></span></label>',
        '<div class="tag-cloud" id="tagCloud">' + rows.map(chip).join("") + "</div>",
      ];
      if (ctx.data().TAGIDX.hidden_tags) {
        html.push('<p class="doc-note">한 주제에서만 쓰인 태그 ' + ctx.data().TAGIDX.hidden_tags +
          "개는 목록에서 뺐습니다 — 위 검색창이 아니라 화면 위쪽 검색으로 찾을 수 있어요.</p>");
      }
      if (people.length) {
        html.push('<div class="doc-section"><h4>👤 사람 이름으로 붙은 태그</h4>' +
          '<p class="doc-note">사람은 참여자 필터로 찾는 편이 정확합니다.</p>' +
          '<div class="tag-cloud small">' + people.map(chip).join("") + "</div></div>");
      }
      if (places.length) {
        html.push('<div class="doc-section"><h4>📍 지명·기관 이름으로 붙은 태그</h4>' +
          '<p class="doc-note">어디서 있었던 일인지는 보고서 본문이 말해 줍니다.</p>' +
          '<div class="tag-cloud small">' + places.map(chip).join("") + "</div></div>");
      }
      el.view.innerHTML = html.join("");

      // 누르면 고른다(바로 넘어가지 않는다). 두세 개 겹쳐 보려면 골라야 하기 때문에,
      // 한 개짜리도 같은 길로 간다 — 두 규칙이 섞이면 무엇이 일어날지 알 수 없다.
      Array.prototype.forEach.call(el.view.querySelectorAll("[data-tag]"), function (b) {
        b.onclick = function () {
          var tag = b.getAttribute("data-tag");
          var at = picked.indexOf(tag);
          if (at !== -1) picked.splice(at, 1);
          else if (picked.length < ctx.TAG_PICK_MAX) picked.push(tag);
          // 고른 태그를 주소에 남긴다 — 새로고침해도 남고, 링크로 줄 수 있다.
          writeHash(true);
          renderTags();
        };
      });
      Array.prototype.forEach.call(el.view.querySelectorAll("[data-unpick]"), function (b) {
        b.onclick = function () {
          var at = picked.indexOf(b.getAttribute("data-unpick"));
          if (at !== -1) picked.splice(at, 1);
          writeHash(true);
          renderTags();
        };
      });
      var go = document.getElementById("tagGo");
      if (go) {
        go.onclick = function () {
          pickThreads(hitIds, picked.map(function (t) { return "#" + t; }).join(" + "),
                      "tag");
        };
      }
      var clear = document.getElementById("tagClear");
      if (clear) {
        clear.onclick = function () {
          state.tagPick = []; writeHash(true); renderTags();
        };
      }
      var input = document.getElementById("tagFilter");
      var hits = document.getElementById("tagHits");
      if (input) {
        input.oninput = function () {
          // 표기 차이를 무시해 맞춘다 — '바이브 코딩' 이라 쳐도 '바이브코딩' 이 나온다.
          var q = tagFold(input.value);
          var shown = 0;
          Array.prototype.forEach.call(el.view.querySelectorAll(".tag-chip"), function (b) {
            var hit = !q || tagFold(b.getAttribute("data-tag")).indexOf(q) !== -1;
            b.hidden = !hit;
            if (hit) shown++;
          });
          if (hits) {
            hits.textContent = !q ? ""
              : (shown ? shown + "개" : "맞는 태그가 없습니다");
          }
        };
      }
    }

    /** 주제 정렬 키 — 같은 날 주제가 여럿이라 시각까지 봐야 순서가 맞는다. */

    return { renderTags: renderTags };
  };
})();
