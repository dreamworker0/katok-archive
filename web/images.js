/* ============ 이미지 로더 — 로컬/보호모드 양쪽 지원 ============
 *
 * 로컬 미리보기(site/)에서는 상대경로를 그대로 쓰고,
 * 배포본(hosting/)에서는 Firebase Storage 에서 인증된 요청으로 받아온다.
 *
 * getDownloadURL() 은 토큰만 알면 누구나 열리는 공개 URL을 만들고 보안 규칙을
 * 우회하므로 쓰지 않는다. 대신 Storage REST 엔드포인트에
 *   Authorization: Firebase <idToken>
 * 를 붙여 요청한다 — 이 경로는 storage.rules 의 검사를 받는다.
 *
 * 화면에 들어올 때 받아오도록 IntersectionObserver 를 쓴다: 64장을 한꺼번에
 * 내려받지 않아 대역폭과 Storage 전송량을 아낀다.
 */
(function () {
  "use strict";

  var mode = "local";        // "local" | "storage"
  var bucket = null;
  var getToken = null;
  var pending = Object.create(null);  // path -> Promise<objectURL>

  /** boot.js 가 로그인 후 호출한다. opts: {bucket, getToken} */
  function useStorage(opts) {
    mode = "storage";
    bucket = opts.bucket;
    getToken = opts.getToken;
  }

  function objectPathFor(assetPath) {
    // assets/images/2026-05/x.png -> images/2026-05/x.png
    return assetPath.replace(/^assets\//, "");
  }

  function fetchProtected(assetPath) {
    var objectPath = objectPathFor(assetPath);
    var url =
      "https://firebasestorage.googleapis.com/v0/b/" +
      encodeURIComponent(bucket) +
      "/o/" +
      encodeURIComponent(objectPath) +
      "?alt=media";
    return getToken()
      .then(function (token) {
        return fetch(url, { headers: { Authorization: "Firebase " + token } });
      })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.blob();
      })
      .then(function (blob) {
        return URL.createObjectURL(blob);
      });
  }

  function resolve(assetPath) {
    if (mode === "local") return Promise.resolve(assetPath);
    if (!pending[assetPath]) {
      pending[assetPath] = fetchProtected(assetPath).catch(function (e) {
        delete pending[assetPath];   // 실패는 캐시하지 않아 재시도 가능
        throw e;
      });
    }
    return pending[assetPath];
  }

  var observer = null;
  function ensureObserver() {
    if (observer || !("IntersectionObserver" in window)) return;
    observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (en) {
          if (!en.isIntersecting) return;
          observer.unobserve(en.target);
          load(en.target);
        });
      },
      { rootMargin: "300px" }
    );
  }

  function load(img) {
    var p = img.getAttribute("data-img");
    if (!p || img.dataset.loaded === "1") return;
    img.dataset.loaded = "1";
    resolve(p).then(
      function (url) { img.src = url; },
      function (e) {
        img.dataset.loaded = "";
        img.classList.add("img-error");
        img.alt = "이미지를 불러올 수 없음";
        if (window.console) console.warn("이미지 로드 실패:", p, e && e.message);
      }
    );
  }

  /** scope 안의 data-img 이미지를 지연 로딩 대상으로 등록 */
  function observe(scope) {
    ensureObserver();
    var imgs = (scope || document).querySelectorAll("img[data-img]");
    Array.prototype.forEach.call(imgs, function (img) {
      if (img.dataset.loaded === "1") return;
      if (observer) observer.observe(img);
      else load(img);
    });
  }

  window.ArchiveImages = {
    useStorage: useStorage,
    observe: observe,
    urlFor: resolve,
    get mode() { return mode; },
  };
})();
