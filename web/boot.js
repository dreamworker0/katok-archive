/* ============ 부팅 — 로그인 게이트 + Firestore 로더 ============
 *
 * 흐름
 *   1) Google 로그인 (Auth)
 *   2) members/{내이메일} 문서 조회
 *        있음   → 3)
 *        없음   → claims/{내이메일} 조회 → 신청 폼 또는 "승인 대기 중" 화면
 *   3) meta/archive + chunks + threads + digests + graph 로드 → window.ARCHIVE 조립
 *   4) 이미지 로더를 Storage 모드로 전환하고 앱 시작
 *
 * 데이터를 정적 파일(data.js)로 내려주지 않는 것이 이 단계의 핵심이다. 대화 전문은
 * 로그인하고 멤버 명부에 있는 사람에게만 전송된다.
 */
(function () {
  "use strict";

  var CFG = window.FIREBASE_CONFIG;
  var el = {
    gate: document.getElementById("gate"),
    gateBody: document.getElementById("gateBody"),
    app: document.getElementById("appRoot"),
  };

  function show(html) {
    el.gateBody.innerHTML = html;
  }

  function gateSignIn(message) {
    show(
      '<h2 class="gate-title">사회복지 바이브코딩 아카이브</h2>' +
      '<p class="gate-desc">' +
      (message || "구성원만 열람할 수 있습니다. Google 계정으로 로그인해 주세요.") +
      "</p>" +
      '<button class="btn gate-btn" id="signInBtn">Google로 로그인</button>'
    );
    document.getElementById("signInBtn").onclick = signIn;
  }

  function gateError(title, detail, opts) {
    show(
      '<h2 class="gate-title">' + title + "</h2>" +
      '<p class="gate-desc">' + detail + "</p>" +
      '<button class="btn ghost gate-btn" id="signOutBtn">다른 계정으로 로그인</button>' +
      (opts && opts.retry
        ? ' <button class="btn gate-btn" id="retryBtn">다시 시도</button>'
        : "")
    );
    bindSignOut();
    var rt = document.getElementById("retryBtn");
    if (rt) rt.onclick = function () { location.reload(); };
  }

  function gateLoading(msg) {
    show('<div class="gate-spinner"></div><p class="gate-desc">' + msg + "</p>");
  }

  function bindSignOut() {
    var so = document.getElementById("signOutBtn");
    if (so) so.onclick = function () { firebase.auth().signOut(); };
  }

  /* ---------- 열람 신청 ---------- */

  /** 신청 폼. 참여자 명단은 보여주지 않고 본인이 직접 적게 한다. */
  function gateClaim(user, prefill, warn) {
    show(
      '<h2 class="gate-title">열람 신청</h2>' +
      '<p class="gate-desc"><b>' + escapeHtml(user.email) + "</b> 으로 로그인했습니다.<br>" +
      "대화방에서 쓰시는 이름을 적어주세요. 관리자가 확인한 뒤 열어드립니다.</p>" +
      (warn ? '<p class="gate-warn">' + warn + "</p>" : "") +
      '<input class="gate-input" id="claimNick" type="text" maxlength="40" ' +
      'autocomplete="off" placeholder="대화방 표시 이름" value="' +
      escapeHtml(prefill || "") + '" />' +
      '<button class="btn gate-btn" id="claimBtn">신청하기</button> ' +
      '<button class="btn ghost gate-btn" id="signOutBtn">다른 계정으로 로그인</button>' +
      '<p class="gate-foot">적어주신 이름은 관리자에게만 보입니다.</p>'
    );
    var input = document.getElementById("claimNick");
    document.getElementById("claimBtn").onclick = function () { submitClaim(user, input.value); };
    input.onkeydown = function (e) { if (e.key === "Enter") submitClaim(user, input.value); };
    input.focus();
    bindSignOut();
  }

  function submitClaim(user, raw) {
    var nickname = (raw || "").trim();
    if (nickname.length < 2) {
      gateClaim(user, nickname, "이름을 2자 이상 적어주세요.");
      return;
    }
    gateLoading("신청을 보내는 중…");

    var data = {
      nickname: nickname,
      // 규칙이 서버 시각만 허용한다 (위조 방지)
      requestedAt: firebase.firestore.FieldValue.serverTimestamp(),
    };
    // 관리자가 명단과 대조할 때의 힌트
    if (user.displayName) data.displayName = user.displayName.slice(0, 60);

    firebase.firestore().collection("claims").doc(user.email.toLowerCase()).set(data).then(
      function () { gatePending(user, nickname); },
      function (e) {
        gateClaim(user, nickname,
          "신청을 보내지 못했습니다: " + escapeHtml(e.message || String(e)));
      }
    );
  }

  function gatePending(user, nickname) {
    show(
      '<h2 class="gate-title">승인 대기 중</h2>' +
      '<p class="gate-desc"><b>' + escapeHtml(nickname) + "</b> 님으로 신청이 접수되었습니다.<br>" +
      "관리자가 확인하면 바로 열람할 수 있습니다.</p>" +
      '<button class="btn gate-btn" id="retryBtn">다시 확인</button> ' +
      '<button class="btn ghost gate-btn" id="editBtn">이름 수정</button> ' +
      '<button class="btn ghost gate-btn" id="signOutBtn">다른 계정으로 로그인</button>'
    );
    document.getElementById("retryBtn").onclick = function () { location.reload(); };
    document.getElementById("editBtn").onclick = function () { gateClaim(user, nickname, ""); };
    bindSignOut();
  }

  function signIn() {
    var provider = new firebase.auth.GoogleAuthProvider();
    provider.setCustomParameters({ prompt: "select_account" });
    gateLoading("로그인 창을 확인해 주세요…");
    firebase.auth().signInWithPopup(provider).catch(function (e) {
      if (e && e.code === "auth/popup-blocked") {
        // 팝업이 막히면 리디렉트로 우회 (카톡 인앱 브라우저 등)
        firebase.auth().signInWithRedirect(provider);
        return;
      }
      if (e && e.code === "auth/popup-closed-by-user") {
        gateSignIn("로그인이 취소되었습니다. 다시 시도해 주세요.");
        return;
      }
      gateSignIn("로그인에 실패했습니다: " + (e && e.message ? e.message : e));
    });
  }

  /** Firestore 에서 아카이브를 조립한다. */
  function loadArchive(db) {
    gateLoading("아카이브를 불러오는 중…");

    return db.collection("meta").doc("archive").get().then(function (metaSnap) {
      if (!metaSnap.exists) throw new Error("아카이브가 아직 적재되지 않았습니다.");
      var meta = metaSnap.data();

      return Promise.all([
        db.collection("threads").get(),   // threads/all 1문서
        db.collection("media").get(),     // media/all 1문서
        db.collection("digests").get(),
        db.collection("graph").get(),     // graph/nodes, graph/edges
      ]).then(function (res) {
        var threadSnap = res[0], mediaSnap = res[1],
            digestSnap = res[2], graphSnap = res[3];

        // 스레드·미디어는 각각 한 문서에 묶여 있다(읽기 절약)
        var threads = [];
        threadSnap.forEach(function (d) {
          var items = d.data().items;
          if (items) threads = threads.concat(items);
        });
        threads.sort(function (a, b) { return a.id < b.id ? -1 : a.id > b.id ? 1 : 0; });

        var media = [];
        mediaSnap.forEach(function (d) {
          var items = d.data().items;
          if (items) media = media.concat(items);
        });

        var digests = {};
        digestSnap.forEach(function (d) { digests[d.id] = d.data(); });

        var graph = { nodes: [], edges: [] };
        graphSnap.forEach(function (d) {
          if (d.id === "nodes") graph.nodes = d.data().items || [];
          if (d.id === "edges") graph.edges = d.data().items || [];
        });

        window.ARCHIVE = {
          chat_room: meta.chat_room,
          categories: meta.categories || [],
          stats: meta.stats || {},
          threads: threads,
          media: media,
          digests: digests,
          knowledge: {
            nodes: graph.nodes,
            edges: graph.edges,
            node_types: meta.node_types || [],
            edge_types: meta.edge_types || [],
          },
        };
        return meta;
      });
    });
  }

  /** 앱에 넘길 요청 API.
   *
   *  앱 로직이 Firebase 를 직접 부르지 않게 여기서 감싼다. 로컬 미리보기(site/)는
   *  세션 자체가 없어 이 객체도 없고, 그래서 '내 글 관리' 탭이 뜨지 않는다.
   */
  function makeRequestApi(db, user) {
    var email = user.email.toLowerCase();
    var prefs = db.collection("preferences").doc(email);
    var dels = db.collection("deletionRequests").doc(email);
    var stamp = function () { return firebase.firestore.FieldValue.serverTimestamp(); };

    return {
      /** 내가 쓴 글 원문. 사람별로 한 문서라 읽기 1회다. */
      loadMine: function () {
        return db.collection("myMessages").doc(email).get().then(function (d) {
          return d.exists ? (d.data().items || []) : [];
        });
      },
      load: function () {
        return Promise.all([prefs.get(), dels.get()]).then(function (r) {
          var p = r[0].exists ? r[0].data() : {};
          var d = r[1].exists ? r[1].data() : null;
          return {
            collection: p.collection || "public",
            deletion: d
              ? { messageIds: d.messageIds || [], allMessages: d.allMessages === true }
              : null,
          };
        });
      },
      saveCollection: function (mode) {
        return prefs.set({ collection: mode, updatedAt: stamp() });
      },
      saveDeletion: function (messageIds, allMessages) {
        return dels.set({
          messageIds: messageIds || [],
          allMessages: !!allMessages,
          requestedAt: stamp(),
        });
      },
      clearDeletion: function () { return dels.delete(); },
    };
  }

  /** 관리자 화면이 쓰는 API. 관리자가 아니면 만들지 않는다. */
  function makeAdminApi(db, user) {
    // Functions 는 배포 리전과 맞춰야 한다 (functions/index.js 의 setGlobalOptions)
    var fns = firebase.app().functions("asia-northeast3");
    var call = function (name, data) {
      return fns.httpsCallable(name)(data || {}).then(function (r) { return r.data; });
    };
    var rows = function (name) {
      return db.collection(name).get().then(function (snap) {
        var out = [];
        snap.forEach(function (d) { out.push(Object.assign({ id: d.id }, d.data())); });
        return out;
      });
    };

    return {
      load: function () {
        return Promise.all([
          rows("claims"), rows("members"), rows("preferences"), rows("deletionRequests"),
        ]).then(function (r) {
          return { claims: r[0], members: r[1], preferences: r[2], deletions: r[3] };
        });
      },
      approve: function (email, nicknames, role) {
        return call("approveClaim", { email: email, nicknames: nicknames, role: role });
      },
      setNicknames: function (email, nicknames) {
        return call("setMemberNicknames", { email: email, nicknames: nicknames });
      },
      removeMember: function (email) { return call("removeMember", { email: email }); },
      reject: function (email) { return call("rejectClaim", { email: email }); },
      setRole: function (email, role) {
        return call("setMemberRole", { email: email, role: role });
      },
    };
  }

  /** members 에는 있는데 토큰에 클레임이 없으면 받아온다.
   *
   *  멤버는 관리자 페이지 말고도 여러 경로로 생긴다 — members.json 을 손으로 고치고
   *  업로더를 돌리는 기존 방식이 그대로 남아 있다. 그렇게 들어온 사람은 클레임이 없어
   *  이미지가 403 이 된다. 로그인할 때마다 확인해 "어느 경로로 멤버가 됐든 결국
   *  열린다"를 보장한다. 실패해도 대화는 볼 수 있으므로 진행을 막지 않는다.
   */
  function ensureClaim(user) {
    return user.getIdTokenResult().then(function (res) {
      if (res.claims && res.claims.member === true) return res.claims;
      var fns = firebase.app().functions("asia-northeast3");
      return fns.httpsCallable("ensureClaim")({}).then(function (r) {
        if (!r.data || !r.data.refreshed) return res.claims || {};
        // 새 클레임은 토큰을 강제로 다시 받아야 반영된다
        return user.getIdToken(true).then(function () {
          return user.getIdTokenResult().then(function (fresh) { return fresh.claims; });
        });
      });
    }).catch(function (e) {
      // 이미지가 안 열릴 수는 있어도 대화는 봐야 한다
      if (window.console) console.warn("클레임 확인 실패:", e && e.message);
      return {};
    });
  }

  function start(user, member) {
    // 이미지는 Storage 보호 모드로 (로그인 토큰 첨부 요청)
    window.ArchiveImages.useStorage({
      bucket: CFG.storageBucket,
      getToken: function () { return user.getIdToken(); },
    });

    el.gate.classList.add("hidden");
    el.app.classList.remove("hidden");
    window.ArchiveApp.start({
      user: {
        email: user.email,
        // 아카이브에서는 대화방 표시명이 가장 알아보기 쉽다
        name: member.nickname || member.name || user.displayName || user.email,
        // 아카이브 참여자 표시명 — "내 글" 같은 개인화의 열쇠.
        // 카톡에서 이름을 바꾼 사람은 여러 개를 갖는다.
        nickname: member.nickname || "",
        nicknames: (member.nicknames && member.nicknames.length)
          ? member.nicknames
          : (member.nickname ? [member.nickname] : []),
      },
      role: member.role || "user",
      signOut: function () { firebase.auth().signOut(); },
      requests: makeRequestApi(firebase.firestore(), user),
      admin: member.role === "admin"
        ? makeAdminApi(firebase.firestore(), user)
        : null,
    });
  }

  function onSignedIn(user) {
    if (!user.email) {
      gateError("이메일 정보 없음", "Google 계정으로 다시 로그인해 주세요.");
      return;
    }
    gateLoading("접근 권한을 확인하는 중…");
    var db = firebase.firestore();
    var email = user.email.toLowerCase();

    db.collection("members").doc(email).get().then(
      function (snap) {
        if (!snap.exists) {
          // 아직 멤버가 아니다 — 신청했는지 보고 폼 또는 대기 화면으로
          db.collection("claims").doc(email).get().then(
            function (claim) {
              if (claim.exists) gatePending(user, (claim.data() || {}).nickname || "");
              else gateClaim(user, "", "");
            },
            function (e) {
              gateClaim(user, "",
                "신청 상태를 확인하지 못했습니다: " + escapeHtml(e.message || String(e)));
            }
          );
          return;
        }
        var member = snap.data();
        // 이미지 권한(Custom Claims)을 먼저 확인한 뒤 아카이브를 연다
        ensureClaim(user).then(function () { return loadArchive(db); }).then(
          function () { start(user, member); },
          function (e) {
            gateError("아카이브를 불러오지 못했습니다", escapeHtml(e.message || String(e)),
              { retry: true });
          }
        );
      },
      function (e) {
        // 규칙 거부(permission-denied)도 여기로 온다
        gateError(
          "접근 권한이 없습니다",
          "구성원 명부 확인에 실패했습니다: " + escapeHtml(e.message || String(e))
        );
      }
    );
  }

  // 속성값(value="...")에도 그대로 쓰므로 따옴표까지 막는다
  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function init() {
    if (!window.firebase || !firebase.initializeApp) {
      show(
        '<h2 class="gate-title">SDK 로드 실패</h2>' +
        '<p class="gate-desc">Firebase SDK를 불러오지 못했습니다. ' +
        "네트워크를 확인하고 새로고침해 주세요.</p>"
      );
      return;
    }
    firebase.initializeApp(CFG);

    // 로그인 상태 유지 (탭을 닫아도 유지)
    firebase.auth().setPersistence(firebase.auth.Auth.Persistence.LOCAL);

    firebase.auth().onAuthStateChanged(function (user) {
      if (user) onSignedIn(user);
      else {
        el.app.classList.add("hidden");
        el.gate.classList.remove("hidden");
        gateSignIn();
      }
    });
  }

  init();
})();
