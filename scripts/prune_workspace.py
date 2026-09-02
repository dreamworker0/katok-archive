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
import json
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

# 서랍 스크린샷 폴더. kakao_drawer.ps1 이 매일 서랍 격자를 PrintWindow 로 찍어 여기에
# 둔다(-ShotDir 기본값). 폴더 자체는 LOGS_NEVER 에 있어 지우지 않지만, 안의 png 는
# 카톡 창 스크린샷과 같은 성질이다 — 대화의 사진·파일 목록이 찍혀 있고, 진단에
# 쓰이는 것은 어제 것뿐이다. 실측 2026-09-02: 322장 · 141MB 가 13일째 쌓여 있었고
# 마름질은 폴더째 건너뛰어 "지울 것 없음" 이라고 말했다.
DRAWER_SHOTS = "drawer"

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
    entries = sorted(LOGS.iterdir())
    drawer = LOGS / DRAWER_SHOTS
    if drawer.is_dir():
        # 폴더는 남기고 안의 스크린샷만 본다. 텍스트 로그는 여기에 없다.
        entries += sorted(p for p in drawer.iterdir()
                          if p.is_file() and p.suffix.lower() == ".png")
    for p in entries:
        if p.name in LOGS_NEVER:
            continue
        d = _date_in_name(p.name)
        if d is None:
            continue          # 날짜를 못 읽으면 손대지 않는다
        if p.suffix.lower() == ".png":
            limit, why = shot_days, ("서랍 스크린샷" if p.parent == drawer
                                     else "카톡 창 스크린샷")
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


# 보관본 경로를 들고 있는 원장들. 어느 하나라도 못 읽으면 마름질을 하지 않는다.
LEDGERS = ("images.jsonl", "files.jsonl", "downloaded-files.jsonl")

# 원본에서 다시 만들 수 있는 것. 원장이 안 가리키면 그냥 지운다
# (python -m scripts.build_thumbnails 가 필요할 때 다시 만든다).
DERIVED_DIRS = ("thumbs",)


def ledger_refs() -> set[str]:
    """원장들이 가리키는 `assets/…` 경로를 모두 긁어온다.

    구조를 훑는 이유: 경로가 한 자리에 있지 않다. `local_path` 말고도
    `assets[].local_path` · `assets[].thumb_path` 에 흩어져 있고, 한 메시지가
    사진 일곱 장을 갖는 경우가 흔하다. 특정 키만 읽으면 나머지가 '원장에 없는
    파일' 로 잘못 잡히는데, 그 실수의 대가가 사진 원본 삭제다.
    """
    refs: set[str] = set()

    def walk(o) -> None:
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str) and o.startswith("assets/"):
            refs.add(o.replace("\\", "/"))

    for name in LEDGERS:
        p = OUT / name
        if not p.is_file():
            continue
        for line in p.open(encoding="utf-8"):
            line = line.strip()
            if line:
                walk(json.loads(line))
    return refs


def plan_unreferenced() -> tuple[list[tuple[Path, str]], list[tuple[Path, int]]]:
    """(지울 것, 남길 것) — 원장이 가리키지 않는 보관본 파일.

    실측 2026-08-22: `assets/videos` 8개 중 4개가 원장에 없었고, 그 넷은 원장이
    가리키는 다른 넷과 **바이트 단위로 같았다**. 옛 백업을 합칠 때 이미 있던
    동영상이 새 image_id 로 한 번 더 들어온 흔적이다. 용량(15MB)은 사소하지만
    Storage 에도 두 벌 올라가고, 갤러리에 같은 영상이 두 번 보일 수 있다.

    자산 중복 마름질(--assets)과 다르다. 그쪽은 '보관본 밖의 덤프' 를 보고,
    여기는 **보관본 안에서 아무도 안 가리키는 것** 을 본다.

    지우는 기준은 같은 원칙이다 — 내용이 다른 데 남아 있으면 지우고, 이 파일에만
    있으면 지우지 않는다. 축소판은 예외로, 원본에서 다시 만들 수 있어 늘 지운다.
    """
    refs = ledger_refs()
    # **원장을 못 읽었으면 아무것도 지우지 않는다.** 이 함수는 "원장에 없으면
    # 지운다" 로 판정하므로, refs 가 비면 보관본 전체가 지울 것이 된다.
    # 사진 335장·첨부 21개를 한 번에 날리는 길이 여기 있다.
    if not refs:
        print("  원장을 읽지 못했습니다 — 아무것도 지우지 않습니다.")
        return [], []

    doomed: list[tuple[Path, str]] = []
    unique: list[tuple[Path, int]] = []
    pending: list[Path] = []          # 원본 계열의 미참조 파일 (해시로 판정할 것)
    matched = 0                        # 원장과 맞은 파일 수 (아래 안전장치가 본다)

    for name in ARCHIVE_DIRS + DERIVED_DIRS:
        d = ASSETS / name
        if not d.is_dir():
            continue
        for p in sorted(x for x in d.rglob("*") if x.is_file()):
            # **저장소 기준 상대 경로로 견준다.** `ASSETS` 는 절대 경로이므로
            # `p.as_posix()` 를 그대로 쓰면 `D:/apps/…/assets/images/x.jpg` 가 되어
            # 원장의 `assets/images/x.jpg` 와 영영 안 맞는다. 실측 2026-08-22:
            # 그 상태로 돌렸더니 보관본 684개(649MB) 전부가 '원장에 없음' 으로
            # 잡혔다 — 기본이 '계획만' 이어서 살았다.
            rel = p.relative_to(ROOT).as_posix()
            if rel in refs:
                matched += 1
                continue
            if name in DERIVED_DIRS:
                doomed.append((p, "원장에 없는 축소판 (다시 만들 수 있음)"))
            else:
                pending.append(p)

    # 안전장치: 원장에 경로가 있는데 디스크의 어느 파일과도 안 맞으면, 그것은
    # 보관본이 비었다는 뜻이 아니라 견주는 방식이 어긋났다는 뜻이다. 위 실측이
    # 정확히 그 꼴이었으므로, 그때 멈추게 한다.
    if matched == 0 and (doomed or pending):
        print("  원장의 경로가 디스크의 어느 파일과도 맞지 않습니다 — "
              "견주는 방식이 어긋난 것으로 보고 아무것도 지우지 않습니다.")
        return [], []

    if pending:
        # 원장이 가리키는 파일들의 해시. 미참조 파일이 있을 때만 계산한다
        # (보관본 전체를 해시하는 일이라 몇십 초 걸린다).
        kept = {_sha256(ROOT / r) for r in refs if (ROOT / r).is_file()}
        for p in pending:
            if _sha256(p) in kept:
                doomed.append((p, "원장에 없음 · 같은 내용이 보관본에 있음"))
            else:
                unique.append((p, p.stat().st_size))
    return doomed, unique


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
    ap.add_argument("--unreferenced", action="store_true",
                    help="보관본 안에서 원장이 가리키지 않는 파일을 훑는다")
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

    if args.unreferenced:
        print("[원장이 안 가리키는 보관본]")
        doomed, unique = plan_unreferenced()
        total += remove(doomed, args.apply, "미참조")
        if unique:
            mb = sum(n for _, n in unique) / 1e6
            print("  -- 지우지 않은 것 %d개 · %.1fMB --" % (len(unique), mb))
            print("     원장이 안 가리키는데 같은 내용이 어디에도 없습니다.")
            print("     원장에서 빠진 것일 수 있습니다 — 확인해 보세요.")
            for p, n in sorted(unique, key=lambda x: -x[1]):
                print("     %7.1fMB  %s" % (n / 1e6, shown(p)))
    else:
        print("[원장이 안 가리키는 보관본] 건너뜀 — 보려면 --unreferenced")

    print()
    print("합계 %.1fMB %s" % (total / 1e6, "지웠습니다" if args.apply else "지울 수 있습니다"))
    if not args.apply and total:
        print("실제로 지우려면 --apply 를 주세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
