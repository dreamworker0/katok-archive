/* ============ 관리자 화면 (web/admin.js) ============
 *
 * app.js 에서 떼어냈다(2026-09-02). app.js 는 한 파일 3,416줄이었고, 그 가운데
 * 560줄이 관리자만 보는 화면이었다 — 열람 신청 승인, 삭제 요청 처리, '지금 갱신',
 * 야간 갱신 결과 카드. 멤버 서른일곱 명은 한 번도 실행하지 않는 코드가 모두의
 * 파일 6분의 1 을 차지했다.
 *
 * 떼어내는 방식은 text.js 와 같다 — 전역에 팩토리 하나를 두고, app.js 가 자기
 * 안쪽 값을 넘겨 준다. 이 화면이 app.js 와 실제로 공유하는 것은 일곱 가지뿐이다:
 *
 *   state · el          화면 상태와 DOM 손잡이 (같은 객체를 나눠 쓴다 — 바꿔치지 않는다)
 *   esc · agoText · msAgo   text.js 의 순수 함수
 *   confirmAction · card    app.js 의 공용 조각(확인 대화상자, 통계 카드 틀)
 *   stats()             STATS 는 init() 에서 **다시 읽힌다**(보호모드에서는 로드 시점에
 *                       비어 있다). 값을 넘기면 영원히 빈 것을 들고 있으므로 읽는
 *                       함수를 넘긴다 — web/app.js init() 의 주석과 같은 함정이다.
 *
 * 돌려주는 것은 셋 — isAdmin · renderAdmin · unwatchRefresh. app.js 가 이 셋만 부른다.
 *
 * 순서: text.js → admin.js → app.js. app.js 가 로드 시점에 window.ArchiveAdmin 을
 * 부르므로 반드시 앞에 와야 한다(index.html · index.hosting.html · sw.js 의 목록,
 * build_hosting.FILES · build_site.STATIC_FILES 가 함께 움직인다 — 검사가 지킨다).
 */
(function () {
  "use strict";

  window.ArchiveAdmin = function (ctx) {
    var state = ctx.state, el = ctx.el, esc = ctx.esc, confirmAction = ctx.confirmAction,
        card = ctx.card, agoText = ctx.agoText, msAgo = ctx.msAgo;

    function isAdmin() {
      return !!(state.session && state.session.admin);
    }

    function participantIndex() {
      var idx = {};
      (ctx.stats().participants || []).forEach(function (p) { idx[p.nickname] = p; });
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
      (ctx.stats().participants || []).forEach(function (p) {
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

    /* ---------- 지금 갱신 ----------
     *
     * 버튼은 갱신을 '실행'하지 않는다. requestRefresh 가 settings/refresh 에 요청을
     * 적고, 그 PC 에 상주하는 감시 스크립트가 받아 run_daily.ps1 을 돌린다. 갱신의
     * 본체가 카톡 창을 조작하는 일이라 클라우드에서는 할 수 없기 때문이다.
     *
     * 그래서 화면이 반드시 보여줘야 하는 것이 둘 있다.
     *   1. PC 가 듣고 있는가 — 아니면 눌러도 아무 일이 없다. 하트비트로 판단한다.
     *   2. 지금 어느 단계인가 — 몇 분 걸리는 일이라 상태가 안 보이면 관리자는
     *      새로고침을 반복하고, 결국 "먹었나?" 하며 또 누른다.
     */

    // 감시 스크립트는 5분마다 하트비트를 쓴다. 두 번 놓칠 여유를 준다.
    var WATCHER_ALIVE_MS = 12 * 60 * 1000;



    function watcherAlive(r) {
      var ms = msAgo(r && r.watcherSeenAt);
      return ms !== null && ms < WATCHER_ALIVE_MS;
    }

    /** 상태가 '멈춰 있는' 것으로 보이는가 — 강제 해제 버튼을 낼지 정한다.
     *
     *  PC 가 꺼지거나 감시가 죽으면 문서가 영영 대기·진행 중으로 남는다. 되돌릴 길이
     *  없으면 관리자는 콘솔을 열어 문서를 손으로 고쳐야 한다.
     */
    function refreshStuck(r) {
      if (!r) return false;
      if (r.status === "queued") {
        return !watcherAlive(r) || msAgo(r.requestedAt) > 30 * 60 * 1000;
      }
      if (r.status === "running") {
        return !watcherAlive(r) || msAgo(r.startedAt) > 90 * 60 * 1000;
      }
      return false;
    }

    /* 매일 밤 스케줄러가 돈 결과를 한 줄로 보여준다.
     *
     * 왜 필요한가: 이 카드는 지금까지 '지금 갱신' 버튼만 비췄다. 야간 갱신은
     * Firestore 에 아무것도 쓰지 않아, 사흘 내리 실패해도 화면은 조용했고
     * logs\daily-*.log 를 열어 보기 전까지 아무도 몰랐다.
     *
     * 조용한 날과 실패한 날을 반드시 구분해 보여준다. 둘 다 '새 소식 없음' 으로
     * 보이면 이 줄이 있으나 마나다 — 그래서 건너뛴 날도 status 를 남긴다.
     *
     * 하루가 넘도록 아무 기록이 없으면 그것도 알린다. 스케줄러 자체가 꺼졌거나
     * PC 가 며칠 꺼져 있던 경우인데, '마지막 결과' 만 보여주면 그 상태가 옛
     * 성공으로 남아 계속 초록으로 보인다.
     */
    var LASTRUN_STALE_MS = 36 * 60 * 60 * 1000;   // 23:40 실행 + 반나절 여유

    function lastRunLine(lr) {
      if (!lr) {
        return '<p class="mine-note">야간 갱신 기록이 아직 없습니다.</p>';
      }
      var ms = msAgo(lr.finishedAt);
      var when = agoText(lr.finishedAt);
      var stale = ms === null || ms > LASTRUN_STALE_MS;

      if (lr.status === "failed") {
        return '<p class="rf-warn">야간 갱신이 실패했습니다' +
          (lr.lastStep ? " — <b>" + esc(lr.lastStep) + "</b> 단계" : "") +
          (lr.exitCode ? " (exit " + esc(lr.exitCode) + ")" : "") +
          (when ? " · " + esc(when) : "") +
          ". 원본은 그대로 있으니 고친 뒤 다시 돌리면 됩니다 — " +
          "자세한 것은 PC 의 logs\\daily-*.log 에 있습니다.</p>";
      }
      if (stale) {
        return '<p class="rf-warn">야간 갱신이 하루가 넘도록 돌지 않았습니다' +
          (when ? " (마지막 " + esc(when) + ")" : "") +
          ". PC 가 켜져 있는지, 작업 스케줄러가 살아 있는지 보세요.</p>";
      }
      // why 는 run_daily 가 적은 발행 사유("새 메시지 3건, 분류 2건")다. 그것이
      // 있으면 added 를 따로 안 쓴다 — 같은 말을 두 번 하게 된다.
      var body = lr.status === "skipped"
        ? "야간 갱신 · 올릴 것이 없어 건너뜀"
        : "야간 갱신 · 마침";
      var detail = lr.why || (lr.added ? "새 글 " + lr.added + "건" : "");
      return '<p class="mine-note">' + esc(body) +
        (detail ? " · " + esc(detail) : "") +
        (when ? ' <span class="adm-mail">' + esc(when) + "</span>" : "") + "</p>";
    }

    function refreshCardBody(r) {
      var status = (r && r.status) || "idle";
      var busy = status === "queued" || status === "running";
      var alive = watcherAlive(r);

      var TONE = { done: "ok", failed: "bad", expired: "bad", skipped: "bad" };
      var HEAD = {
        idle: "아직 버튼으로 갱신한 기록이 없습니다.",
        queued: "요청을 남겼습니다 — PC 가 받으면 시작합니다.",
        running: "갱신하고 있습니다…",
        done: "갱신을 마쳤습니다.",
        failed: "갱신이 실패했습니다.",
        skipped: "갱신을 건너뛰었습니다.",
        expired: "요청이 만료됐습니다.",
      };

      var when = status === "running"
        ? (r && r.startedAt && "시작 " + agoText(r.startedAt))
        : (r && r.finishedAt && agoText(r.finishedAt));

      var html = [
        '<p class="rf-state ' + (TONE[status] || "") + '">' +
        (busy ? '<span class="rf-spin" aria-hidden="true"></span>' : "") +
        esc(HEAD[status] || status) +
        (when ? ' <span class="adm-mail">' + esc(when) + "</span>" : "") + "</p>",
      ];

      if (r && r.message) {
        html.push('<p class="mine-note">' + esc(r.message) + "</p>");
      }

      // PC 가 듣고 있는지는 대기 중일 때 가장 중요하다. 진행 중·끝난 뒤에는
      // 굳이 걱정시키지 않는다.
      if (!alive && (status === "idle" || status === "queued")) {
        html.push('<p class="rf-warn">이 아카이브를 갱신하는 PC 가 응답하지 않습니다' +
          (r && r.watcherSeenAt ? " (마지막 응답 " + esc(agoText(r.watcherSeenAt)) + ")" : "") +
          ". PC 가 켜져 있고 로그인된 상태여야 갱신이 시작됩니다. " +
          "요청은 남아 있으니 PC 가 깨어나면 이어서 실행됩니다.</p>");
      } else if (alive && status !== "running") {
        html.push('<p class="mine-note">PC 연결됨 · 마지막 응답 ' +
          esc(agoText(r.watcherSeenAt)) + "</p>");
      }

      // 야간 갱신 소식은 버튼 위에 둔다. 아래에 두면 설명문에 묻힌다.
      html.push(lastRunLine(state.lastRun));

      html.push('<div class="rf-act">' +
        '<button class="btn rf-go"' + (busy ? " disabled" : "") + ">" +
        (busy ? "갱신 중…" : "지금 갱신") + "</button>" +
        (refreshStuck(r)
          ? ' <button class="btn ghost rf-force">멈춘 상태 해제하고 다시 요청</button>'
          : "") +
        "</div>");

      // 분류는 더 이상 사람 일이 아니다.
      //
      // 이 문장은 사람이 주 1회 재분류하던 시절의 것이다. 그 뒤 주제 분류와 보고서
      // 쓰기가 갱신 안으로 들어왔는데(run_daily 5단계) 문구만 남아, 버튼을 누른
      // 사람은 그 자리에서 분류가 끝났는데도 미분류를 찾으러 가게 됐다. 화면이
      // 스스로에 대해 틀린 말을 하는 것이 이 카드에서 가장 나쁜 종류의 흠이다.
      //
      // 남는 경우가 아주 없지는 않다(LLM 장애, 한 번에 처리하는 상한). 그래서
      // '없다'고 단정하지 않고, 실제로 남았을 때는 위의 결과 줄이 몇 개인지 말한다.
      html.push('<p class="mine-note">카톡에서 대화를 내보내 새 글·사진·통계를 ' +
        "지금 반영하고, 새 글의 주제 분류와 요지까지 이어서 씁니다. " +
        "분류가 실패하거나 밀린 만큼만 ‘미분류’로 남고, 그것은 다음 갱신에서 " +
        "이어 정리합니다. PC 가 켜져 있고 카톡 방 창이 열려 있어야 합니다.</p>");

      html.push('<p class="adm-msg" id="rfMsg"></p>');
      return html.join("");
    }

    /** 카드만 다시 그린다. 관리 화면 전체를 그리면 열어둔 패널과 스크롤이 날아간다. */
    function renderRefreshCard() {
      var host = document.getElementById("admRefresh");
      if (!host) return;
      host.innerHTML = "<h3>지금 갱신</h3>" + refreshCardBody(state.refresh);

      var msg = document.getElementById("rfMsg");
      var go = host.querySelector(".rf-go");
      var force = host.querySelector(".rf-force");

      var send = function (isForce) {
        if (msg) msg.textContent = "요청하는 중…";
        if (go) go.disabled = true;
        state.session.admin.requestRefresh(isForce).then(
          function () { if (msg) msg.textContent = ""; },
          function (e) {
            if (msg) msg.textContent = "요청 실패: " + (e.message || String(e));
            if (go) go.disabled = false;
          }
        );
      };

      if (go) {
        go.onclick = function () {
          confirmAction({
            title: "지금 갱신할까요?",
            description: "카톡에서 대화를 내보내 새 글을 반영하고 다시 발행합니다. " +
              "몇 분 걸리고, 그동안 그 PC 의 카톡 창이 잠깐 조작됩니다.",
            confirmLabel: "갱신하기",
            tone: "neutral",
          }, function () { send(false); });
        };
      }
      if (force) {
        force.onclick = function () {
          confirmAction({
            title: "멈춘 상태를 해제할까요?",
            description: "진행 중으로 남은 기록을 밀어내고 새로 요청합니다. " +
              "실제로 갱신이 돌고 있었다면 PC 쪽 잠금이 막아 주므로 겹쳐 돌지는 않습니다.",
            confirmLabel: "해제하고 요청",
          }, function () { send(true); });
        };
      }
    }

    function watchRefresh() {
      watchLastRun();
      if (state.refreshUnsub) return;
      state.refreshUnsub = state.session.admin.watchRefresh(function (data, err) {
        if (err) {
          var m = document.getElementById("rfMsg");
          if (m) m.textContent = "상태를 읽지 못했습니다: " + (err.message || String(err));
          return;
        }
        state.refresh = data;
        renderRefreshCard();
      });
    }

    /* 야간 갱신 결과도 함께 듣는다.
     *
     * 실패해도 조용히 넘긴다 — 이것을 못 읽는 것이 '지금 갱신' 버튼을 막을 이유는
     * 없다. 문서가 아예 없을 수도 있다(이 기능이 들어오기 전에는 없었다). */
    function watchLastRun() {
      if (state.lastRunUnsub) return;
      if (!state.session.admin.watchLastRun) return;
      state.lastRunUnsub = state.session.admin.watchLastRun(function (data) {
        state.lastRun = data;
        renderRefreshCard();
      });
    }

    function unwatchRefresh() {
      if (state.lastRunUnsub) { state.lastRunUnsub(); state.lastRunUnsub = null; }
      if (!state.refreshUnsub) return;
      state.refreshUnsub();
      state.refreshUnsub = null;
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
      var MODE_LABEL = { public: "함께 공개", unpublished: "발행하지 않기", none: "수집 중단" };

      var pending = d.preferences.filter(function (p) {
        return p.collection && p.collection !== "public";
      });

      el.view.innerHTML =
        '<section class="adm">' +
        '<h2 class="mine-title">관리</h2>' +

        // 내용은 renderRefreshCard 가 채운다 — 상태가 실시간으로 바뀌므로
        // 관리 화면 전체와 다시 그리는 주기를 분리한다.
        '<div class="mine-card" id="admRefresh"></div>' +

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
        '<p class="mine-note">반영은 매일 23:40 자동 갱신 때, 또는 위 ‘지금 갱신’ 을 ' +
        "누를 때 이뤄집니다. " +
        "남의 글을 지우려는 요청은 반영 단계에서 걸러지고 로그에 남습니다.</p></div>" +

        '<div class="mine-card"><h3>수집 동의 — 기본값이 아닌 ' + pending.length + "명</h3>" +
        (pending.length
          ? pending.map(function (p) {
              return '<div class="adm-line"><b>' + esc(p.id) + "</b> — " +
                esc(MODE_LABEL[p.collection] || p.collection) + "</div>";
            }).join("")
          : '<p class="mine-note">모두 함께 공개 설정입니다.</p>') +
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
        "원본은 남아 있어 되돌리면 다시 나옵니다. " +
        "반영은 오늘 밤 갱신 때, 또는 위 ‘지금 갱신’ 을 누를 때입니다.</p>" +
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
            (ctx.stats().participants || []).map(function (pp) {
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

      renderRefreshCard();
      watchRefresh();
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
          confirmAction({
            title: email + " 님을 탈퇴 처리할까요?",
            description: "대화·이미지·첨부 열람 권한이 사라집니다.\n" +
              (names ? "앞으로 수집하지 않을 표시명: " + names + "\n" : "") +
              "이미 올라간 과거 글은 남고, 기존 삭제 요청은 계속 반영됩니다.",
            confirmLabel: "탈퇴 처리",
          }, function () {
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
          });
        };

        var btn = row.querySelector(".adm-role");
        btn.onclick = function () {
          var role = btn.getAttribute("data-role");
          var verb = role === "admin" ? "관리자로 지정" : "관리자에서 해제";
          confirmAction({
            title: email + " 님을 " + verb + "할까요?",
            description: role === "admin"
              ? "멤버 승인과 운영 설정을 바꿀 수 있는 권한이 생깁니다."
              : "관리 기능 접근 권한이 사라집니다.",
            confirmLabel: verb,
            tone: "neutral",
          }, function () {
            var m = document.getElementById("roleMsg");
            if (m) m.textContent = "바꾸는 중…";
            state.session.admin.setRole(email, role).then(
              function () { state.admin = null; renderAdmin(); },
              function (e) { if (m) m.textContent = "실패: " + (e.message || String(e)); }
            );
          });
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
          var approve = function () {
            say("승인 중…");
            // 표시명은 목록으로 보낸다. 나중에 이름이 바뀌면 여기에 덧붙인다.
            state.session.admin.approve(email, [nickname], "user").then(finish("승인"), fail);
          };
          if (!participantIndex()[nickname]) {
            confirmAction({
              title: "명단에 없는 표시명으로 승인할까요?",
              description: "'" + nickname + "'은 현재 참여자 명단에 없습니다.\n" +
                "아직 발언이 없는 멤버라면 그대로 승인해도 됩니다.",
              confirmLabel: "이대로 승인",
              tone: "neutral",
            }, approve);
          } else {
            approve();
          }
        };
        row.querySelector('[data-act="reject"]').onclick = function () {
          confirmAction({
            title: email + " 님의 신청을 반려할까요?",
            description: "이 신청은 대기 목록에서 사라집니다. 필요하면 다시 신청할 수 있어요.",
            confirmLabel: "신청 반려",
          }, function () {
            say("반려 중…");
            state.session.admin.reject(email).then(finish("반려"), fail);
          });
        };
      });
    }

    return { isAdmin: isAdmin, renderAdmin: renderAdmin, unwatchRefresh: unwatchRefresh };
  };
})();
