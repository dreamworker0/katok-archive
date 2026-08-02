# -*- coding: utf-8 -*-
"""발행본이 로컬보다 뒤처졌는지 본다 — 갱신의 네 번째 발행 사유.

왜 필요한가 (실측 2026-07-30)
  23:40 자동 갱신이 새 메시지 34건을 원장에 반영하고, 발행본까지 만든 뒤 테스트
  단계에서 멈췄다(고립 노드 하나 때문에). 원장에는 들어갔고 Firestore 에는 안 갔다.

  다음 날 관리 탭의 '지금 갱신' 을 눌렀더니 화면에 "갱신을 마쳤습니다" 가 떴는데
  타임라인은 그대로였다. 34건이 **이미 원장에 있으니** 증분은 0건이고, 발행 사유
  셋(새 메시지·멤버 요청·분류)이 모두 0이라 발행을 건너뛴 것이다. 버튼을 몇 번
  눌러도 결과가 같다 — 한 번 이 상태에 빠지면 사람이 손으로 발행하지 않는 한
  영영 안 올라간다.

  사유 셋은 모두 '이번 실행에서 새로 생긴 것' 을 본다. 그래서 지난 실행이 남긴
  빚을 아무도 보지 않았다. 이 모듈이 그 자리를 메운다 — **로컬이 마지막 적재보다
  새로운가.**

무엇과 무엇을 비교하는가
  `output/upload-state.json` 의 `updated_at` 이 마지막 **성공한** 적재 시각이다
  (upload_firestore.js 가 다 올린 뒤에만 쓴다). 그보다 나중에 바뀐 발행 입력이
  하나라도 있으면 발행할 것이 남아 있다는 뜻이다.

  새 표식 파일을 만들지 않는다. 적재 성공 시각은 이미 저 파일이 들고 있고, 상태를
  두 곳에 두면 언젠가 어긋난다.

모를 때는 발행하는 쪽으로 기운다
  적재 상태 파일이 없거나 못 읽으면 발행한다. 불필요한 발행은 손해가 없지만,
  올릴 것을 안 올리면 화면이 거짓말을 한다 — 파이프라인 전체가 쓰는 원칙이다.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from scripts import jsonio

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
UPLOAD_STATE = OUTPUT / "upload-state.json"

# 발행본에 실려 나가는 것들. 이 중 하나라도 마지막 적재보다 새로우면 발행한다.
#
# 원장·참여자·사진 목록은 타임라인·통계·갤러리가 되고, 주제·보고서·요지·관계망은
# 화면의 내용이 된다. 사진 개인정보 판정(image_pii.json)도 넣는다 — 감출 사진이
# 늘었는데 발행을 안 하면 이미 올라간 사진이 그대로 보인다.
WATCHED = (
    "messages.jsonl",
    "participants.json",
    "images.jsonl",
    "files.jsonl",
    "topics.json",
    "topic-digests.json",
    "knowledge.json",
    "secondary_categories.json",
    "image_pii.json",
)
# 보고서는 파일이 300개가 넘는다. 가장 최근 것 하나만 보면 된다.
REPORTS = "reports"


def last_upload_at() -> datetime | None:
    """마지막으로 적재가 성공한 시각. 모르면 None."""
    if not UPLOAD_STATE.exists():
        return None
    try:
        raw = jsonio.read_json(UPLOAD_STATE)
        stamp = str(raw.get("updated_at") or "")
        if not stamp:
            return None
        return datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except (ValueError, OSError):
        return None


def _mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def newer_inputs(since: datetime) -> list[tuple[str, datetime]]:
    """`since` 보다 나중에 바뀐 발행 입력. (이름, 바뀐 시각) 로 돌려준다."""
    out: list[tuple[str, datetime]] = []
    for name in WATCHED:
        p = OUTPUT / name
        if p.exists() and _mtime(p) > since:
            out.append((name, _mtime(p)))

    reports = OUTPUT / REPORTS
    if reports.is_dir():
        newest = max((_mtime(p) for p in reports.glob("*.md")), default=None)
        if newest is not None and newest > since:
            out.append((REPORTS + "/*.md", newest))

    return sorted(out, key=lambda x: x[1], reverse=True)


def check() -> tuple[bool, str]:
    """(발행할 것이 남았는가, 사람이 읽을 한 줄)."""
    since = last_upload_at()
    if since is None:
        # 출력에 em dash 를 쓰지 않는다. cp949 콘솔에서 UnicodeEncodeError 로
        # 죽는다 — 판단을 돕는 줄이 판단 자체를 없애서는 안 된다.
        return True, "마지막 적재 시각을 알 수 없습니다: 발행하는 쪽으로 봅니다."

    local = since.astimezone()
    newer = newer_inputs(since)
    if not newer:
        return False, "발행본이 최신입니다 (마지막 적재 %s)." % local.strftime("%Y-%m-%d %H:%M")

    names = ", ".join(
        "%s(%s)" % (n, t.astimezone().strftime("%m-%d %H:%M")) for n, t in newer[:5])
    return True, ("마지막 적재(%s) 뒤에 바뀐 것 %d개: %s"
                  % (local.strftime("%Y-%m-%d %H:%M"), len(newer), names))


def main() -> int:
    ap = argparse.ArgumentParser(
        description="발행본이 로컬보다 뒤처졌는지 확인 (run_daily.ps1 이 읽는다)")
    ap.parse_args()

    stale, line = check()
    print(line)
    # 위 줄은 사람이 읽는 것이고, 아래 표식은 run_daily.ps1 이 읽는다.
    # 콘솔 코드페이지에 한글이 깨져도 판단은 흔들리지 않아야 한다.
    print("PUBLISH_STALE=%d" % (1 if stale else 0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
