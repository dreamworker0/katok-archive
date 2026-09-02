/* ============ 서비스 워커 — 앱 껍데기 오프라인 + 빠른 재방문 ============
 *
 * 이 워커는 배포본(hosting/)에만 실린다. 로컬 미리보기(site/)는 data.js 에 대화 전문을
 * 임베드하므로 캐시에 얹으면 개인정보가 디스크에 남는다. build_site.py 의 허용 목록에
 * 일부러 넣지 않았다.
 *
 * ── 무엇을 캐시하고 무엇을 안 하나 ──
 * 캐시함   : 앱 껍데기(html/css/js), 아이콘, UI 일러스트, 웹폰트. 전부 공개 자산이다.
 * 캐시 안 함: 대화·사진·인증. Firestore / Storage / Identity Toolkit / Functions 요청은
 *            fetch 핸들러에서 아예 손대지 않고 넘긴다(PRIVATE_HOSTS).
 *
 * 배포본이 공개돼도 개인정보가 새지 않는다는 것이 이 프로젝트의 전제다(build_hosting.py).
 * 캐시도 같은 선을 지킨다 — 껍데기만 저장하고 내용은 저장하지 않는다.
 *
 * ── 전략 ──
 * 화면 이동·코드(html/css/js) : 네트워크 우선, 실패하면 캐시.
 *     firebase.json 이 이 파일들에 no-cache 를 주는 뜻(항상 최신을 본다)을 그대로 따른다.
 *     캐시는 오프라인 대비용 사본일 뿐, 온라인에서는 앞서지 않는다.
 * 아이콘·일러스트·폰트      : 캐시 우선 + 뒤에서 갱신(stale-while-revalidate).
 *     그림은 자주 안 바뀌고, 한 판 늦게 반영돼도 읽는 데 문제가 없다.
 *
 * VERSION 을 올리면 이전 캐시를 전부 버린다. 코드는 네트워크 우선이라 평소에는 올릴
 * 필요가 없고, 캐시 구조나 전략을 바꿀 때만 올린다.
 */
(function () {
  "use strict";

  var VERSION = "v1";
  var SHELL_CACHE = "archive-shell-" + VERSION;
  var ASSET_CACHE = "archive-assets-" + VERSION;
  var FONT_CACHE = "archive-fonts-" + VERSION;
  var KEEP = [SHELL_CACHE, ASSET_CACHE, FONT_CACHE];

  /* 앱 껍데기. "/" 는 화면 이동이 오프라인일 때 되돌려줄 단일 진입점이다. */
  var SHELL_CORE = [
    "/",
    "styles.css",
    "firebase-config.js",
    "images.js",
    "graph.js",
    "text.js",
    "timeline.js",
    "summary.js",
    "graph-view.js",
    "tags.js",
    "gallery.js",
    "stats.js",
    "mine.js",
    "admin.js",
    "app.js",
    "boot.js",
    "pwa.js",
    "manifest.webmanifest"
  ];

  /* Firebase SDK. Hosting 예약 URL 이라 배포된 사이트에서만 존재한다 — 못 받아도
   * 설치를 실패시키지 않는다. 버전은 index.hosting.html 의 script 태그와 같아야
   * 하며, test_pwa_contract.py 가 두 곳이 어긋나지 않는지 지킨다. */
  var SHELL_OPTIONAL = [
    "/__/firebase/12.16.0/firebase-app-compat.js",
    "/__/firebase/12.16.0/firebase-auth-compat.js",
    "/__/firebase/12.16.0/firebase-firestore-compat.js",
    "/__/firebase/12.16.0/firebase-functions-compat.js"
  ];

  /* 아이콘과 게이트 일러스트. 오프라인에서도 로그인 화면이 제 모습이어야 한다. */
  var ASSET_CORE = [
    "favicon.svg",
    "icons/icon-192.png",
    "icons/icon-512.png",
    "icons/icon-maskable-512.png",
    "icons/apple-touch-icon.png",
    "art/archive-hero.webp",
    "art/state-pending.webp",
    "art/state-empty.webp",
    "art/state-search.webp"
  ];

  /* 대화·사진·인증이 흐르는 곳. 여기 요청은 캐시에 닿지 않는다. */
  var PRIVATE_HOSTS = [
    "firestore.googleapis.com",
    "firebasestorage.googleapis.com",
    "identitytoolkit.googleapis.com",
    "securetoken.googleapis.com",
    "cloudfunctions.net",
    "www.googleapis.com",
    "apis.google.com",
    "accounts.google.com"
  ];

  var FONT_HOSTS = ["fonts.googleapis.com", "fonts.gstatic.com"];

  /* 캐시에 "/" 조차 없는 첫 방문 직후 오프라인이 된 경우의 마지막 화면. */
  var OFFLINE_HTML =
    '<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8" />' +
    '<meta name="viewport" content="width=device-width, initial-scale=1" />' +
    "<title>연결이 끊겼어요</title><style>" +
    'body{margin:0;min-height:100vh;display:grid;place-items:center;background:#FBF6EE;' +
    'color:#3C332C;font-family:"Noto Sans KR",sans-serif;text-align:center;padding:24px}' +
    "h1{font-size:20px;margin:0 0 8px}p{margin:0;color:#706257;font-size:14px;line-height:1.7}" +
    "</style></head><body><div><h1>연결이 끊겼어요</h1>" +
    "<p>인터넷에 다시 연결되면 기록을 이어서 볼 수 있어요.<br />" +
    "저장된 대화는 로그인한 뒤에 받아옵니다.</p></div></body></html>";

  function isPrivate(url) {
    // Firebase 인증 핸들러는 같은 출처(/__/auth/...)에 있다 — 호스트만 봐서는 못 걸러진다.
    if (url.origin === self.location.origin) {
      return url.pathname.indexOf("/__/auth") === 0;
    }
    for (var i = 0; i < PRIVATE_HOSTS.length; i += 1) {
      var host = PRIVATE_HOSTS[i];
      if (url.host === host || url.host.slice(-(host.length + 1)) === "." + host) return true;
    }
    return false;
  }

  function isFontHost(host) {
    return FONT_HOSTS.indexOf(host) !== -1;
  }

  function isStaticAsset(pathname) {
    return /\.(?:png|svg|webp|ico|woff2?)$/i.test(pathname);
  }

  function isShellCode(pathname) {
    return /\.(?:js|css|html|webmanifest)$/i.test(pathname);
  }

  function isCacheable(response) {
    if (!response) return false;
    // no-cors 로 받은 폰트는 opaque 라서 status 가 0 이다. 들여다볼 수 없을 뿐 저장은 된다.
    if (response.type === "opaque") return true;
    return response.status === 200;
  }

  function putLater(cacheName, request, response) {
    var copy = response.clone();
    caches.open(cacheName).then(function (cache) {
      return cache.put(request, copy);
    }).catch(function () {});
  }

  function networkFirst(request, cacheName) {
    return fetch(request).then(function (response) {
      if (isCacheable(response)) putLater(cacheName, request, response);
      return response;
    }).catch(function () {
      return caches.match(request).then(function (hit) {
        // 캐시에도 없으면 네트워크 오류를 그대로 알린다. 빈 200 을 주면 스크립트가
        // 조용히 아무 일도 안 하는 상태가 되어 원인을 찾기 어려워진다.
        return hit || Response.error();
      });
    });
  }

  function navigationResponse(request) {
    return fetch(request).then(function (response) {
      // 어떤 경로로 들어와도 껍데기는 하나다 — 항상 "/" 자리에 갱신해 둔다.
      if (isCacheable(response)) putLater(SHELL_CACHE, "/", response);
      return response;
    }).catch(function () {
      return caches.match("/").then(function (hit) {
        if (hit) return hit;
        return new Response(OFFLINE_HTML, {
          status: 503,
          headers: { "Content-Type": "text/html; charset=utf-8" }
        });
      });
    });
  }

  function staleWhileRevalidate(request, cacheName) {
    return caches.open(cacheName).then(function (cache) {
      return cache.match(request).then(function (hit) {
        var fresh = fetch(request).then(function (response) {
          if (isCacheable(response)) cache.put(request, response.clone()).catch(function () {});
          return response;
        });
        if (hit) {
          fresh.catch(function () {});  // 뒤에서 조용히 갱신 — 실패해도 화면은 그대로
          return hit;
        }
        return fresh;
      });
    });
  }

  self.addEventListener("install", function (event) {
    event.waitUntil(Promise.all([
      caches.open(SHELL_CACHE).then(function (cache) {
        return cache.addAll(SHELL_CORE).then(function () {
          return Promise.all(SHELL_OPTIONAL.map(function (url) {
            return cache.add(url).catch(function () {});
          }));
        });
      }),
      caches.open(ASSET_CACHE).then(function (cache) {
        return cache.addAll(ASSET_CORE);
      })
    ]));
    // 여기서 skipWaiting 을 부르지 않는다. 보던 중에 코드가 바뀌면 화면이 어긋난다.
    // 새 버전은 pwa.js 가 안내하고, 사람이 새로고침을 누를 때 넘어간다.
  });

  self.addEventListener("activate", function (event) {
    event.waitUntil(
      caches.keys().then(function (names) {
        return Promise.all(names.map(function (name) {
          // 우리 것만 건드린다. 이름 규칙이 다른 캐시는 남의 것일 수 있다.
          if (name.indexOf("archive-") === 0 && KEEP.indexOf(name) === -1) {
            return caches.delete(name);
          }
          return null;
        }));
      }).then(function () {
        return self.clients.claim();
      })
    );
  });

  self.addEventListener("fetch", function (event) {
    var request = event.request;
    if (request.method !== "GET") return;  // 쓰기 요청은 손대지 않는다

    var url;
    try {
      url = new URL(request.url);
    } catch (e) {
      return;
    }
    if (url.protocol !== "http:" && url.protocol !== "https:") return;
    if (isPrivate(url)) return;  // 대화·사진·인증: 캐시 금지

    if (request.mode === "navigate") {
      event.respondWith(navigationResponse(request));
      return;
    }
    if (isFontHost(url.host)) {
      event.respondWith(staleWhileRevalidate(request, FONT_CACHE));
      return;
    }
    if (url.origin !== self.location.origin) return;  // 그 외 외부 요청은 그대로 통과

    if (isStaticAsset(url.pathname)) {
      event.respondWith(staleWhileRevalidate(request, ASSET_CACHE));
      return;
    }
    if (isShellCode(url.pathname)) {
      event.respondWith(networkFirst(request, SHELL_CACHE));
    }
  });

  self.addEventListener("message", function (event) {
    var data = event.data || {};
    if (data.type === "SKIP_WAITING") {
      self.skipWaiting();
      return;
    }
    if (data.type === "CLEAR_CACHES") {
      // 로그아웃 때 부른다. 껍데기만 들어 있어 지울 개인정보는 없지만, 공용 기기에서
      // "정리했다"가 말뿐이 아니게 실제로 비운다.
      event.waitUntil(
        caches.keys().then(function (names) {
          return Promise.all(names.map(function (name) {
            return name.indexOf("archive-") === 0 ? caches.delete(name) : null;
          }));
        })
      );
    }
  });
})();
