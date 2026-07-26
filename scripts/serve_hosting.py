# -*- coding: utf-8 -*-
"""배포본(hosting/)을 로컬에서 그대로 열어 보는 정적 서버.

설치형(PWA) 동작은 보안 컨텍스트에서만 켜진다. localhost 는 여기 해당하므로 서비스
워커·설치·오프라인을 배포 전에 확인할 수 있다.

`python -m http.server` 를 쓰지 않는 이유:
  - .webmanifest 의 MIME 을 모른다. firebase.json 이 주는 값과 같게 맞춰야 확인이
    의미가 있다.
  - sw.js 를 캐시하면 다음 확인 때 낡은 워커가 잡힌다. no-cache 를 준다.

Firebase Hosting 예약 URL(/__/firebase/...)은 여기 없으므로 404 다. 로그인 게이트는
못 지나가지만, 껍데기 캐시·오프라인 대체·매니페스트·아이콘은 그대로 확인된다.
(서비스 워커의 SHELL_OPTIONAL 이 실패해도 설치가 되도록 만든 이유가 이것이다.)

  python -m scripts.serve_hosting [포트]
"""
from __future__ import annotations

import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOSTING = ROOT / "hosting"

DEFAULT_PORT = 8900

# firebase.json 의 헤더와 같은 뜻으로 맞춘다.
NO_CACHE_SUFFIXES = (".js", ".css", ".html", ".webmanifest")


class HostingHandler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".webmanifest": "application/manifest+json",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
    }

    def end_headers(self):
        path = self.path.split("?", 1)[0]
        if path.endswith(NO_CACHE_SUFFIXES) or path.endswith("/"):
            self.send_header("Cache-Control", "no-cache")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin-allow-popups")
        super().end_headers()

    def log_message(self, fmt, *args):  # 404 만 보고 나머지는 조용히
        if args and str(args[1]).startswith("4"):
            sys.stderr.write("  %s %s\n" % (args[1], args[0]))


def main() -> None:
    if not HOSTING.is_dir():
        raise SystemExit("hosting/ 이 없습니다. 먼저: python -m scripts.build_hosting")
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    handler = partial(HostingHandler, directory=str(HOSTING))
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print("hosting/ 서빙 중: http://127.0.0.1:%d (Ctrl+C 로 종료)" % port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n종료")


if __name__ == "__main__":
    main()
