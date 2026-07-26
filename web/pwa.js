/* ============ PWA 껍데기 — 워커 등록 · 새 버전 안내 · 연결 상태 ============
 *
 * 배포본(hosting/)에서만 로드한다. 로컬 미리보기(site/)에는 넣지 않는다 —
 * 그쪽은 data.js 에 대화 전문이 들어 있어 캐시에 얹으면 안 된다.
 *
 * 새 버전을 발견해도 몰래 바꿔치지 않는다. 읽던 글이 사라지거나 화면이 어긋나는 게
 * 최신 코드보다 나쁘다. 대신 아래에 알림을 띄우고, 사람이 누를 때 넘어간다.
 */
(function () {
  "use strict";

  if (!("serviceWorker" in navigator)) return;

  var THEME_COLORS = { light: "#FBF6EE", dark: "#292521" };  // styles.css 의 --bg
  var registration = null;
  var reloading = false;

  /* ── 알림 한 줄 (새 버전 안내 / 오프라인 안내에 같이 쓴다) ── */

  var toast = null;

  function showToast(message, action) {
    if (!toast) {
      toast = document.createElement("div");
      toast.className = "pwa-toast";
      toast.setAttribute("role", "status");
      toast.setAttribute("aria-live", "polite");
      document.body.appendChild(toast);
    }
    toast.innerHTML = "";
    var text = document.createElement("p");
    text.className = "pwa-toast__text";
    text.textContent = message;
    toast.appendChild(text);
    if (action) {
      var button = document.createElement("button");
      button.className = "pwa-toast__action";
      button.type = "button";
      button.textContent = action.label;
      button.addEventListener("click", action.onClick);
      toast.appendChild(button);
    }
    toast.hidden = false;
  }

  function hideToast() {
    if (toast) toast.hidden = true;
  }

  /* ── 테마 색: 주소창·상태바를 화면과 같은 색으로 ── */

  function syncThemeColor() {
    var mode = document.documentElement.getAttribute("data-theme");
    var meta = document.querySelector('meta[name="theme-color"]');
    if (!meta) return;
    meta.setAttribute("content", THEME_COLORS[mode] || THEME_COLORS.light);
  }

  function watchTheme() {
    syncThemeColor();
    // app.js 가 html[data-theme] 을 바꾼다. 토글을 누를 때마다 따라가려면 지켜봐야 한다.
    if (typeof MutationObserver !== "function") return;
    new MutationObserver(syncThemeColor).observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"]
    });
  }

  /* ── 새 버전 ── */

  function promptUpdate(worker) {
    showToast("새 버전이 준비됐어요.", {
      label: "새로고침",
      onClick: function () {
        hideToast();
        worker.postMessage({ type: "SKIP_WAITING" });
      }
    });
  }

  function watchInstalling(worker) {
    if (!worker) return;
    worker.addEventListener("statechange", function () {
      // controller 가 있다는 건 이미 쓰고 있던 버전이 있다는 뜻 — 즉 첫 설치가 아니다.
      if (worker.state === "installed" && navigator.serviceWorker.controller) {
        promptUpdate(worker);
      }
    });
  }

  /* ── 로그아웃 정리 ── */

  function clearCaches() {
    if (!navigator.serviceWorker.controller) return Promise.resolve();
    navigator.serviceWorker.controller.postMessage({ type: "CLEAR_CACHES" });
    return Promise.resolve();
  }

  /* ── 연결 상태 ── */

  function watchConnection() {
    window.addEventListener("offline", function () {
      showToast("오프라인이에요. 저장된 화면만 보입니다.");
    });
    window.addEventListener("online", hideToast);
    if (navigator.onLine === false) {
      showToast("오프라인이에요. 저장된 화면만 보입니다.");
    }
  }

  /* ── 등록 ── */

  function register() {
    navigator.serviceWorker.register("/sw.js", { scope: "/" }).then(function (reg) {
      registration = reg;
      if (reg.waiting && navigator.serviceWorker.controller) promptUpdate(reg.waiting);
      watchInstalling(reg.installing);
      reg.addEventListener("updatefound", function () {
        watchInstalling(reg.installing);
      });
    }).catch(function (e) {
      // 워커가 없어도 앱은 온전히 돌아간다. 조용히 지나간다.
      if (window.console && console.warn) console.warn("서비스 워커 등록 실패", e);
    });

    navigator.serviceWorker.addEventListener("controllerchange", function () {
      if (reloading) return;
      reloading = true;
      window.location.reload();
    });
  }

  window.ArchivePWA = {
    clearCaches: clearCaches,
    update: function () { if (registration) registration.update(); }
  };

  watchTheme();
  watchConnection();
  if (document.readyState === "complete") register();
  else window.addEventListener("load", register);
})();
