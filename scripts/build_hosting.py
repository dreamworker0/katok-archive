# -*- coding: utf-8 -*-
"""Firebase Hosting 배포용 `hosting/` 폴더를 만든다.

`site/`(로컬 미리보기, data.js 임베드)와 결정적으로 다른 점:
  - 대화 데이터를 담지 않는다. 로그인 후 Firestore 에서 받아온다.
  - 이미지를 담지 않는다. Storage 에서 인증된 요청으로 받아온다.
따라서 이 폴더는 공개돼도 개인정보가 노출되지 않는다 — 앱 껍데기일 뿐이다.
"""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
HOSTING = ROOT / "hosting"

# (원본 web/ 파일명, 배포본 파일명)
FILES = [
    ("index.hosting.html", "index.html"),
    ("styles.css", "styles.css"),
    ("app.js", "app.js"),
    ("graph.js", "graph.js"),
    ("images.js", "images.js"),
    ("boot.js", "boot.js"),
    ("firebase-config.js", "firebase-config.js"),
    ("favicon.svg", "favicon.svg"),
    # 설치형(PWA). 배포본에만 넣는다 — site/(로컬 미리보기)는 대화 전문을 임베드하므로
    # 캐시에 얹으면 개인정보가 디스크에 남는다. build_site.py 의 목록에는 없다.
    ("manifest.webmanifest", "manifest.webmanifest"),
    ("sw.js", "sw.js"),
    ("pwa.js", "pwa.js"),
]
STATIC_DIRS = ("art", "icons")

FORBIDDEN = ("data.js", "assets")


def main() -> None:
    if HOSTING.exists():
        shutil.rmtree(HOSTING)
    HOSTING.mkdir(parents=True)

    for src, dest in FILES:
        s = WEB / src
        if not s.exists():
            raise SystemExit("필요한 파일이 없습니다: %s" % s)
        shutil.copyfile(s, HOSTING / dest)
    for name in STATIC_DIRS:
        shutil.copytree(WEB / name, HOSTING / name)

    # 안전장치: 배포본에 데이터·이미지가 섞여 들어가지 않았는지 확인
    names = {p.name for p in HOSTING.rglob("*")}
    for bad in FORBIDDEN:
        if bad in names:
            raise SystemExit("배포본에 민감 데이터가 포함되었습니다: %s" % bad)

    total = sum(p.stat().st_size for p in HOSTING.rglob("*") if p.is_file())
    file_count = sum(1 for p in HOSTING.rglob("*") if p.is_file())
    print("hosting/ 생성 완료: 파일 %d개, %.1f KB (대화 데이터·이미지 미포함)"
          % (file_count, total / 1024))
    print("다음: firebase deploy --only hosting")


if __name__ == "__main__":
    main()
