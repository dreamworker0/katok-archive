# -*- coding: utf-8 -*-
"""원본 데이터를 이 디스크 밖에 둔다 — 다른 SSD(매일)와 구글 드라이브(주 1회).

왜 필요한가
    저장소는 코드만 담는다(2026-07-26 결정). 대화 원장·분류 상태·보고서 원본·사진과
    첨부 원본은 36명의 개인정보라 저장소에 넣지 않는다 — 그래서 D: 한 곳에만 있었다.
    Firestore 에 발행본이 있어 보고서는 restore_reports.js 로 되살릴 수 있지만,
    원장·분류 상태·보조 분류·사진 원본은 되살릴 길이 없다. 그리고 서랍의 첨부는
    공유 14일 뒤 만료되므로 **다시 받을 수도 없다.**

어디에 두는가 (2026-11-01 사용자 결정)
    - 매일   C:\\KatokArchiveBackup\\mirror  — 같은 PC 의 다른 SSD. 디스크 고장을 막는다.
             지우지 않고 더하기만 한다(robocopy /MIR 처럼 지움까지 따라가면, 실수로
             지운 것이 그날 밤 사본에서도 사라진다).
    - 주 1회 구글 드라이브 폴더(config/backup.json 의 cloud_dir)에 날짜별 zip, 최근
             KEEP_ZIPS 개만. 폴더 경로는 저장소에 적지 않는다 — 공유 드라이브 이름에
             실명이 들어가고, 이 저장소는 공개다(예시는 config/backup.example.json).
             PC 를 잃거나 랜섬웨어가 C:·D: 를 함께 잠가도 남는다. 지난 묶음이 남아
             있어 '망가진 것이 덮어써진' 경우에도 되돌릴 판이 있다.

무엇을 담는가
    output/ · assets/ · inbox/processed/(원본 내보내기 txt) · config/ · 루트의
    KakaoTalk_*.txt. **inbox/drawer/ 는 뺀다** — 서랍에서 받은 것을 날짜별로 쌓아 둔
    임시 보관함이고(7GB 넘음, 같은 파일이 날마다 반복), 알맹이는 assets/ 로 옮겨졌다.
    서비스 계정 키(%USERPROFILE%\\.katok-archive)는 담지 않는다 — Firebase 콘솔에서
    새로 만들 수 있고, 사본이 늘수록 새는 길도 는다. 같은 이유로 클라우드 묶음에서는
    웹훅 주소(config/notify.json)를 뺀다.

사용
    python -m scripts.backup_data              # 매일 사본 + (7일 지났으면) 클라우드 묶음
    python -m scripts.backup_data --no-cloud   # 매일 사본만
    python -m scripts.backup_data --dry-run    # 무엇을 할지만
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import zipfile
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MIRROR = Path(r"C:\KatokArchiveBackup\mirror")
BACKUP_CONFIG = ROOT / "config" / "backup.json"
ZIP_PREFIX = "katok-archive-"
KEEP_ZIPS = 4
ZIP_EVERY_DAYS = 7

SOURCES = ["output", "assets", "inbox/processed", "config"]
ROOT_GLOBS = ["KakaoTalk_*.txt"]
SKIP_DIRS = {"__pycache__"}
CLOUD_SKIP = {"config/notify.json"}
# 이미 압축된 것은 다시 줄지 않는다 — 시간만 든다.
STORE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".mov", ".zip", ".pdf",
             ".pptx", ".docx", ".xlsx", ".hwpx", ".mp3"}


def cloud_dir(config: Path = BACKUP_CONFIG) -> Path | None:
    """구글 드라이브 묶음을 둘 폴더. 설정이 없으면 None — 클라우드 묶음을 건너뛴다."""
    try:
        value = json.loads(config.read_text(encoding="utf-8")).get("cloud_dir")
    except (OSError, ValueError):
        return None
    return Path(value) if value else None


def collect(root: Path = ROOT) -> list[tuple[Path, str]]:
    """담을 파일 (실제 경로, 'output/messages.jsonl' 꼴 상대 경로)."""
    out: list[tuple[Path, str]] = []
    for rel in SOURCES:
        base = root / rel
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in filenames:
                p = Path(dirpath) / name
                out.append((p, p.relative_to(root).as_posix()))
    for pattern in ROOT_GLOBS:
        for p in sorted(root.glob(pattern)):
            if p.is_file():
                out.append((p, p.name))
    return out


def _same(src: Path, dst: Path) -> bool:
    try:
        a, b = src.stat(), dst.stat()
    except FileNotFoundError:
        return False
    # copy2 가 수정 시각을 옮겨 오므로 크기와 초 단위 시각이 같으면 같은 파일이다.
    return a.st_size == b.st_size and int(a.st_mtime) == int(b.st_mtime)


def mirror(items: list[tuple[Path, str]], dest: Path, dry_run: bool = False) -> dict:
    """바뀐 것만 dest 로 복사한다. 지우지 않는다."""
    copied = same = 0
    size = 0
    for src, rel in items:
        dst = dest / rel
        if _same(src, dst):
            same += 1
            continue
        copied += 1
        size += src.stat().st_size
        if dry_run:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return {"copied": copied, "same": same, "bytes": size}


def zips_in(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.glob(ZIP_PREFIX + "*.zip") if p.is_file())


def zip_due(folder: Path, today: date, every_days: int = ZIP_EVERY_DAYS) -> bool:
    """가장 최근 묶음이 every_days 일 넘게 지났거나 없으면 새로 만들 때다.

    요일로 정하지 않는다 — 그 요일에 PC 가 꺼져 있으면 2주를 건너뛴다."""
    existing = zips_in(folder)
    if not existing:
        return True
    stamp = existing[-1].stem[len(ZIP_PREFIX):]
    try:
        last = datetime.strptime(stamp, "%Y%m%d").date()
    except ValueError:
        return True
    return (today - last).days >= every_days


def write_zip(items: list[tuple[Path, str]], folder: Path, today: date) -> Path:
    """날짜별 zip 을 쓴다. 다 쓴 뒤에 이름을 바꿔, 반쯤 쓴 묶음이 '최신' 으로 보이지 않게 한다."""
    folder.mkdir(parents=True, exist_ok=True)
    final = folder / f"{ZIP_PREFIX}{today:%Y%m%d}.zip"
    partial = final.with_suffix(".zip.partial")
    with zipfile.ZipFile(partial, "w", allowZip64=True) as zf:
        for src, rel in items:
            method = zipfile.ZIP_STORED if src.suffix.lower() in STORE_EXT else zipfile.ZIP_DEFLATED
            zf.write(src, rel, compress_type=method)
    with zipfile.ZipFile(partial) as zf:
        if len(zf.namelist()) != len(items):
            raise RuntimeError("묶음에 담긴 수가 다릅니다: %d / %d" % (len(zf.namelist()), len(items)))
    os.replace(partial, final)
    return final


def prune_zips(folder: Path, keep: int = KEEP_ZIPS) -> list[Path]:
    old = zips_in(folder)[:-keep] if keep > 0 else []
    for p in old:
        p.unlink()
    return old


def _mb(n: int) -> str:
    return "%.1fMB" % (n / 1024 / 1024)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="원본 데이터를 C: 와 구글 드라이브에 백업")
    ap.add_argument("--no-cloud", action="store_true", help="매일 사본만 만든다")
    ap.add_argument("--force-cloud", action="store_true", help="7일이 안 됐어도 클라우드 묶음을 만든다")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    items = collect()
    total = sum(p.stat().st_size for p, _ in items)
    print("[백업] 대상 %d개 (%s)" % (len(items), _mb(total)))

    failed = False
    t0 = time.time()
    try:
        r = mirror(items, MIRROR, args.dry_run)
        print("[백업] C: 사본 — 새로·바뀐 것 %d개(%s) 복사, 그대로 %d개 (%.0f초) → %s"
              % (r["copied"], _mb(r["bytes"]), r["same"], time.time() - t0, MIRROR))
    except OSError as e:
        failed = True
        print("WARN [백업] C: 사본 실패: %s" % e)

    cloud = None if args.no_cloud else cloud_dir()
    if not args.no_cloud and cloud is None:
        failed = True
        print("WARN [백업] 구글 드라이브 폴더 설정이 없습니다 — config/backup.json 의 cloud_dir")
    if cloud is not None:
        today = date.today()
        if not cloud.is_dir():
            failed = True
            print("WARN [백업] 구글 드라이브 폴더(%s)가 없습니다 — 드라이브 앱이 로그인돼 있는지, "
                  "폴더 이름이 바뀌지 않았는지 보세요." % cloud)
        elif args.force_cloud or zip_due(cloud, today):
            cloud_items = [(p, rel) for p, rel in items if rel not in CLOUD_SKIP]
            if args.dry_run:
                print("[백업] 클라우드 묶음을 만들 차례입니다 (%d개) — dry-run" % len(cloud_items))
            else:
                t1 = time.time()
                try:
                    z = write_zip(cloud_items, cloud, today)
                    gone = prune_zips(cloud)
                    print("[백업] 구글 드라이브 묶음 %s (%s, %.0f초)%s"
                          % (z.name, _mb(z.stat().st_size), time.time() - t1,
                             (" · 지난 것 %d개 지움" % len(gone)) if gone else ""))
                except (OSError, RuntimeError, zipfile.BadZipFile) as e:
                    failed = True
                    print("WARN [백업] 구글 드라이브 묶음 실패: %s" % e)
        else:
            last = zips_in(cloud)[-1].name
            print("[백업] 구글 드라이브 묶음은 7일마다 — 최근 것: %s" % last)

    print("BACKUP_FAILED=%d" % (1 if failed else 0))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
