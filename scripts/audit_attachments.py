# -*- coding: utf-8 -*-
"""대화에 올라온 첨부가 아카이브에 실제로 들어왔는가 — 결과로 대조한다.

왜 필요한가
    서랍 자동화(kakao_drawer.ps1)는 저장 뒤 뜨는 팝업을 OCR 해 '완료 N / 실패 M' 을
    로그에 남긴다. 그런데 그 숫자는 신호가 못 된다.
      - 실패는 거의 다 **만료 카드**다. 서랍은 한 화면을 통째로 골라 저장하므로
        유효기간이 지난 카드도 매일 밤 다시 골라지고 다시 실패한다(실측 2026-10-31:
        2화면 '완료 9 / 실패 6' = 화면 속 유효기간 ≤ 당일 카드 6개와 정확히 같다).
      - 숫자 자체가 자주 틀린다(못 읽어 -1, 17개 골랐는데 '완료 25').
    그래서 밤마다 WARN 이 9~20건씩 찍혔고, 진짜로 잃는 날이 와도 그 속에 묻힌다.

    물어야 할 것은 '팝업이 뭐라고 했나' 가 아니라 **'잃은 것이 있나'** 다. 그것은
    원장과 아카이브만 보면 안다.
      - 파일: 파일 공유 메시지('파일: 이름')에 같은 이름의 원본이 assets/files/ 에
        있는가 — build_file_manifest 의 missing 이 그 목록이다.
      - 사진·동영상: output/images.jsonl 의 그 메시지가 downloaded 인가.

무엇을 말하는가
    서랍의 첨부는 공유일 + 14일에 만료된다(그 날짜에 닿으면 이미 못 받는다).
      - **잃음**     만료일이 지났는데 없다. 되돌릴 수 없다.
      - **곧 만료**  만료까지 URGENT_DAYS 일 이하인데 아직 없다. 지금 손쓰면 된다.
      - **밀림**     여유는 있지만 공유한 지 STUCK_DAYS 일이 넘도록 아직 없다. 그 사이
                   밤 갱신이 한 번 이상 돌았는데 못 받았으니, 서랍 쪽이 고장 났을 수 있다.
      - 대기       그보다 여유가 있고 아직 하루가 안 됐다. 다음 밤에 받으면 된다.

    '밀림' 은 2026-11-15 에 더했다. 카톡 26.9.2(11-02)부터 파일 저장 전에 '친구가 아닌
    사용자가 보낸 파일…다운로드 받으시겠습니까?' 창이 떴고 서랍 스크립트가 그 창을 닫아
    (=취소) 13일 동안 파일이 하나도 안 받아졌다. 그동안 이 대조는 만료 사흘 전 것만
    외쳤으므로 나머지는 '대기 9' 로 조용했고, 사용자가 '오늘 올린 파일 왜 안 받았냐' 고
    물어서야 드러났다. 받을 수 있는데 하루 넘게 못 받았다면 그날 바로 알린다.
    자동 수집을 시작하기 전(COLLECT_SINCE)의 것은 따지지 않는다 — 그때 빠진 41건은
    서랍이 생기기 전 일이라 다시 받을 길이 없고, 매일 같은 목록을 읽게 할 뿐이다.

    잃은 것은 영영 그대로라 매일 다시 외치지 않는다. 만료된 지 FRESH_LOSS_DAYS 일
    안의 것만 WARN 으로 말하고, 나머지는 누계 한 줄로 둔다.

    run_daily.ps1 이 끝의 ASCII 표식(ATTACH_URGENT / ATTACH_LOST)을 읽어 관리 탭과
    디스코드로 올린다. 한글 줄은 콘솔 코드페이지에 따라 깨질 수 있어서다.

사용
    python -m scripts.audit_attachments
    python -m scripts.audit_attachments --today 2026-11-05   # 그날이라 치고
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

from scripts import build_file_manifest
from scripts.jsonio import read_jsonl

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"

# 서랍 자동 수집을 시작한 날 (kakao_drawer.ps1 첫 커밋). 그 전 것은 따지지 않는다.
COLLECT_SINCE = "2026-08-20"
# 공유일 + 이만큼이 유효기간이고, 그 날짜에 닿으면 이미 못 받는다(실측 2026-08-20).
EXPIRE_DAYS = 14
# 만료까지 이만큼 남았는데 아직 없으면 사람을 부른다. 밤마다 한 번 도니 사흘이면
# 자동으로 세 번 더 시도한 뒤이고, 사람이 손쓸 틈도 남는다.
URGENT_DAYS = 3
# 공유한 지 이만큼 지났는데 아직 없으면 '밀림'. 1 = 공유한 날 밤 갱신이 돌고 나서도
# 다음 날 밤까지 없다는 뜻이다(밤 23:40 뒤에 올라온 것도 그다음 밤엔 받는다).
STUCK_DAYS = 1
# 밀림 목록을 줄로 풀 때의 상한 — 사진이 수십 장 밀리면 나머지는 숫자로만.
STUCK_LINES = 10
# 만료된 지 이만큼 안의 것만 '새로 잃음' 으로 외친다.
FRESH_LOSS_DAYS = 3

MEDIA_KINDS = ("image", "video")


def _day(s: str) -> date:
    return date.fromisoformat(s[:10])


def audit(messages: list[dict], missing_files: set[str], images: list[dict],
          today: date) -> dict:
    """아직 없는 첨부를 잃음·곧 만료·대기로 가른다. 순수 함수다."""
    downloaded = {r["message_id"] for r in images if r.get("status") == "downloaded"}
    rows = []
    for m in messages:
        kind = m.get("kind")
        if m.get("date", "") < COLLECT_SINCE:
            continue
        if kind == "file":
            name = build_file_manifest.filename_of(m)
            if name not in missing_files:
                continue
        elif kind in MEDIA_KINDS:
            if m["id"] in downloaded:
                continue
            name = "동영상" if kind == "video" else "사진"
        else:
            continue
        expires = _day(m["date"]) + timedelta(days=EXPIRE_DAYS)
        rows.append({
            "id": m["id"], "kind": kind, "name": name, "date": m["date"],
            "expires": expires.isoformat(), "days_left": (expires - today).days,
            "age": (today - _day(m["date"])).days,
        })

    lost = [r for r in rows if r["days_left"] <= 0]
    return {
        "lost": lost,
        "fresh_lost": [r for r in lost if -r["days_left"] < FRESH_LOSS_DAYS],
        "urgent": [r for r in rows if 0 < r["days_left"] <= URGENT_DAYS],
        "stuck": [r for r in rows if r["days_left"] > URGENT_DAYS and r["age"] >= STUCK_DAYS],
        "waiting": [r for r in rows if r["days_left"] > URGENT_DAYS],
    }


def _line(r: dict) -> str:
    return "%s %s %s (공유 %s, 만료 %s)" % (r["id"], r["kind"], r["name"], r["date"], r["expires"])


def report(result: dict, before: int) -> list[tuple[str, str]]:
    """(수준, 줄) 목록. 수준은 INFO 아니면 WARN."""
    out: list[tuple[str, str]] = []
    for r in result["urgent"]:
        out.append(("WARN", "[첨부 대조] 곧 만료인데 아직 없음 — %d일 남음: %s" % (r["days_left"], _line(r))))
    for r in result["fresh_lost"]:
        out.append(("WARN", "[첨부 대조] 만료되어 잃음: " + _line(r)))
    stuck = sorted(result["stuck"], key=lambda r: (r["date"], r["id"]))
    for r in stuck[:STUCK_LINES]:
        out.append(("WARN", "[첨부 대조] 받을 수 있는데 %d일째 못 받음: %s" % (r["age"], _line(r))))
    if len(stuck) > STUCK_LINES:
        out.append(("WARN", "[첨부 대조] 받을 수 있는데 못 받은 것 %d건 더" % (len(stuck) - STUCK_LINES)))
    if result["urgent"]:
        out.append(("WARN", "[첨부 대조] 카카오톡 '채팅방 서랍' 창이 우리 방을 보고 열려 있는지 확인하고, "
                            "급하면 서랍에서 손으로 저장하세요(받은 파일 폴더로 가면 다음 갱신이 붙입니다)."))
    if stuck:
        out.append(("WARN", "[첨부 대조] 서랍 수집이 막혔을 수 있습니다 — logs/kakao-drawer-*.log 의 '팝업 글자' 줄을 보세요"
                            "(카톡이 업데이트되면 저장 전 확인 창이 바뀌곤 합니다)."))
    out.append(("INFO", "[첨부 대조] %s 이후 첨부: 곧 만료 %d · 밀림 %d · 대기 %d · 잃음 누계 %d건 (자동 수집 전 원본 없음 %d건은 따지지 않음)"
                % (COLLECT_SINCE, len(result["urgent"]), len(stuck), len(result["waiting"]), len(result["lost"]), before)))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="대화의 첨부가 아카이브에 들어왔는지 대조")
    ap.add_argument("--today", help="YYYY-MM-DD — 그날이라 치고 따진다")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    today = date.fromisoformat(args.today) if args.today else date.today()
    messages = read_jsonl(OUTPUT / "messages.jsonl")
    missing = set(build_file_manifest.build_manifest(messages)["missing"])
    images = read_jsonl(OUTPUT / "images.jsonl")

    result = audit(messages, missing, images, today)
    before = sum(1 for m in messages if m.get("kind") == "file" and m.get("date", "") < COLLECT_SINCE
                 and build_file_manifest.filename_of(m) in missing)
    for level, line in report(result, before):
        print(("WARN " if level == "WARN" else "") + line)
    print("ATTACH_URGENT=%d" % len(result["urgent"]))
    print("ATTACH_STUCK=%d" % len(result["stuck"]))
    print("ATTACH_LOST=%d" % len(result["fresh_lost"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
