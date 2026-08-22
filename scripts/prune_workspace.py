# -*- coding: utf-8 -*-
"""작업 폴더를 마름질한다 — 로그·백업·자산 중복.

왜 필요한가
    무엇 하나 지우는 코드가 없어서 전부 쌓였다. 실측 2026-08-22:

        logs/                 43MB · 87개 파일
        logs/abort-*.png      14장 · 4.1MB — **카톡 창 스크린샷이다**
        output/backup-*/      8개 폴더
        assets/ 중복          766MB (아래 참고)

    이 중 급한 것은 용량이 아니라 `abort-*.png` 다. 자동화가 멈출 때 무슨 화면이었는지
    남기려고 찍은 것인데, 그 화면이 **카톡 대화창**이다. 즉 대화 내용이 담긴 이미지가
    평문으로 무기한 남는다. 가장 오래된 것이 2026-07-25 로 넉 주째였다. 발행본에서는
    사진 속 개인정보까지 OCR 로 걸러내면서 진단 스크린샷은 그대로 둔 셈이다.

기본은 지우지 않는다
    인자 없이 부르면 계획만 출력한다. 지우려면 --apply 를 준다. 이 스크립트가 지우는
    것은 대부분 다시 만들 수 없는 것들이라(로그는 그날의 유일한 기록이다) 실수로
    도는 쪽이 실수로 안 도는 쪽보다 나쁘다.

자산 중복은 따로, 그리고 조심스럽게
    --assets 는 `assets/staging` 과 카톡이 폴더째 내보낸 것들을 훑어, 이미
    보관본(images·videos·files)에 바이트 단위로 같은 파일이 있는 것만 지운다.
    해시로 판정하므로 파일명이 달라도 알아본다.

    이 조심스러움에는 이유가 있다. 실측 2026-08-22: 세 폴더 793MB 중 766MB 가
    중복이었지만, 나머지에 아카이브에 아예 없는 사진 1장(11.9MB)과 동영상
    1개(2.5MB)가 있었다. 폴더째 지웠으면 영구 소실이다. 그래서 중복이 아닌 파일은
    지우지 않고 목록으로 알린다 — 그건 마름질할 쓰레기가 아니라 아직 들여오지 못한
    자료다.

    해시를 다 계산하므로 1분 가까이 걸린다. 그래서 매일 밤 도는 축에는 넣지 않았다.

사용
    python -m scripts.prune_workspace                    # 계획만
    python -m scripts.prune_workspace --apply
    python -m scripts.prune_workspace --assets           # 자산까지 훑어 계획만
    python -m scripts.prune_workspace --assets --apply
    python -m scripts.prune_workspace --shots 30 --logs 180   # 보관 기간 바꾸기
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"
OUT = ROOT / "output"
ASSETS = ROOT / "assets"

# 카톡 창 스크린샷. 대화 내용이 담긴 이미지라 가장 짧게 둔다 — 진단에 쓰이는 것은
# 사실상 "어제 왜 멈췄나" 뿐이고, 넉 주 전 화면을 다시 볼 일은 없었다.
SHOT_DAYS = 14

# 텍스트 로그. 실패를 며칠 뒤에 알아차리는 일이 있어(야간 갱신은 조용히 실패했다)
# 넉넉히 둔다. 3.2MB 뿐이라 용량이 문제가 아니다.
LOG_DAYS = 90

# 수술 백업은 종류별로 최근 몇 개를 남기나. 되돌리는 데 필요한 것은 그 수술 직전이고,
# 두 세대 앞까지 있으면 잘못 되돌린 것도 다시 되돌릴 수 있다.
BACKUP_KEEP = 3

# 절대 지우지 않는 것 — 도는 중인 실행이 쓰는 파일과 폴더.
LOGS_NEVER = {"run_daily.lock", "drawer"}

# 보관본. 여기 있는 것과 같은 파일만 중복으로 본다.
ARCHIVE_DIRS = ("images", "videos", "files")

_DATE8 = re.compile(r"(20\d{6})")


def staging_dirs() -> list[Path]:
    """마름질 대상 — 수집 중간 덤프와 카톡이 폴더째 내보낸 것.

    폴더 이름을 넓게 잡는다. 카톡 내보내기 폴더명은 기기와 판마다 다르고
    (Chats/Chat, 대소문자까지) 좁게 잡으면 다음 폴더가 그물을 빠져나간다 —
    .gitignore 가 같은 함정에 두 번 빠졌다.
    """
    out = []
    if (ASSETS / "staging").is_dir():
        out.append(ASSETS / "staging")
    for p in sorted(ASSETS.glob("[Kk]akao[Tt]alk_*")):
        if p.is_dir():
            out.append(p)
    return out


def _date_in_name(name: str) -> date | None:
    """이름에 박힌 YYYYMMDD 를 읽는다.

    파일 시각(mtime)을 안 쓰는 이유가 있다 — 백신이나 백업 도구가 훑고 지나가면
    mtime 이 오늘로 바뀌어, 넉 주 전 스크린샷이 영영 안 지워진다.
    """
    m = _DATE8.search(name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%d").date()
    except ValueError:
        return None


def plan_logs(today: date, shot_days: int = SHOT_DAYS,
              log_days: int = LOG_DAYS) -> list[tuple[Path, str]]:
    """지울 로그 목록을 (경로, 이유) 로 돌려준다.

    이유를 함께 내는 것은 장식이 아니다. 왜 지우는지 안 보이면 사람이 이 목록을
    못 믿고, 못 믿으면 --apply 를 안 쓴다 — 그러면 이 스크립트는 없는 것과 같다.
    """
    if not LOGS.is_dir():
        return []
    doomed = []
    for p in sorted(LOGS.iterdir()):
        if p.name in LOGS_NEVER:
            continue
        d = _date_in_name(p.name)
        if d is None:
            continue          # 날짜를 못 읽으면 손대지 않는다
        if p.suffix.lower() == ".png":
            limit, why = shot_days, "카톡 창 스크린샷"
        elif p.is_file():
            limit, why = log_days, "로그"
        else:
            continue
        age = (today - d).days
        if age > limit:
            doomed.append((p, "%s · %d일 지남(보관 %d일)" % (why, age, limit)))
    return doomed


def plan_backups(keep: int = BACKUP_KEEP) -> list[tuple[Path, str]]:
    """종류별로 오래된 수술 백업. backup-<종류>-<날짜> 에서 종류를 갈라 센다."""
    if not OUT.is_dir():
        return []
    groups: dict[str, list[Path]] = {}
    for p in sorted(OUT.glob("backup-*")):
        if not p.is_dir():
            continue
        # backup-retag-20260821 → retag / backup-3a-20260728 → 3a
        stem = p.name[len("backup-"):]
        m = _DATE8.search(stem)
        kind = stem[:m.start()].rstrip("-") if m else stem
        groups.setdefault(kind, []).append(p)
    doomed = []
    for kind, paths in sorted(groups.items()):
        ordered = sorted(paths, key=lambda q: (_date_in_name(q.name) or date.min, q.name))
        drop = ordered[:-keep] if keep > 0 else ordered
        for p in drop:
            doomed.append((p, "%s 백업 · 최근 %d개만 남김" % (kind, keep)))
    return doomed


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def plan_assets() -> tuple[list[tuple[Path, str]], list[tuple[Path, int]]]:
    """(지울 중복, 남길 비중복) 을 돌려준다.

    비중복을 함께 돌려주는 것이 이 함수의 요점이다. 개수만 세어 "중복 766MB" 라고
    말하면 사람은 폴더째 지운다 — 그 안에 아카이브에 없는 사진이 있었다.
    """
    archived: set[str] = set()
    for name in ARCHIVE_DIRS:
        d = ASSETS / name
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            if p.is_file():
                archived.add(_sha256(p))

    dup: list[tuple[Path, str]] = []
    orphan: list[tuple[Path, int]] = []
    for d in staging_dirs():
        for p in sorted(x for x in d.rglob("*") if x.is_file()):
            if _sha256(p) in archived:
                dup.append((p, "보관본에 같은 파일 있음"))
            else:
                orphan.append((p, p.stat().st_size))
    return dup, orphan


def shown(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def _size(p: Path) -> int:
    if p.is_dir():
        return sum(x.stat().st_size for x in p.rglob("*") if x.is_file())
    return p.stat().st_size


def remove(doomed: list[tuple[Path, str]], apply: bool, label: str) -> int:
    """지운(또는 지울) 바이트 수를 돌려준다."""
    if not doomed:
        print("  %s: 마름질할 것이 없습니다." % label)
        return 0
    total = 0
    for p, why in doomed:
        n = _size(p)
        total += n
        print("  %s %-50s %7.1fMB  %s"
              % ("지움  " if apply else "지울것", shown(p), n / 1e6, why))
        if apply:
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
    print("  %s: %d개 · %.1fMB%s"
          % (label, len(doomed), total / 1e6, "" if apply else " (계획만)"))
    return total


def main() -> int:
    ap = argparse.ArgumentParser(description="작업 폴더 마름질 (기본은 계획만)")
    ap.add_argument("--apply", action="store_true", help="실제로 지운다")
    ap.add_argument("--assets", action="store_true",
                    help="자산 중복까지 훑는다 (해시 계산으로 1분 가까이 걸린다)")
    ap.add_argument("--shots", type=int, default=SHOT_DAYS,
                    help="카톡 창 스크린샷 보관 일수 (기본: %d)" % SHOT_DAYS)
    ap.add_argument("--logs", type=int, default=LOG_DAYS,
                    help="텍스트 로그 보관 일수 (기본: %d)" % LOG_DAYS)
    ap.add_argument("--backups", type=int, default=BACKUP_KEEP,
                    help="수술 백업을 종류별로 몇 개 남기나 (기본: %d)" % BACKUP_KEEP)
    args = ap.parse_args()

    total = 0
    print("[로그]")
    total += remove(plan_logs(date.today(), args.shots, args.logs), args.apply, "로그")
    print("[수술 백업]")
    total += remove(plan_backups(args.backups), args.apply, "백업")

    if args.assets:
        print("[자산 중복] 해시를 계산합니다…")
        dup, orphan = plan_assets()
        total += remove(dup, args.apply, "중복")
        if orphan:
            mb = sum(n for _, n in orphan) / 1e6
            print("  -- 지우지 않은 것 %d개 · %.1fMB --" % (len(orphan), mb))
            print("     보관본에 같은 파일이 없습니다. 마름질할 쓰레기가 아니라")
            print("     아직 들여오지 못한 자료입니다 — 확인해 보세요.")
            for p, n in sorted(orphan, key=lambda x: -x[1]):
                print("     %7.1fMB  %s" % (n / 1e6, shown(p)))
    else:
        print("[자산 중복] 건너뜀 — 보려면 --assets")

    print()
    print("합계 %.1fMB %s" % (total / 1e6, "지웠습니다" if args.apply else "지울 수 있습니다"))
    if not args.apply and total:
        print("실제로 지우려면 --apply 를 주세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
