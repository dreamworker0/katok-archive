# -*- coding: utf-8 -*-
"""실제 발행 데이터가 있어야 도는 검사를 가려낸다.

이 저장소의 검사는 두 종류가 섞여 있다.

  1. 로직 검사       어디서든 돈다. 코드가 규칙대로 동작하는지 본다.
  2. 정합성 검사     `output/` 의 실제 발행 데이터를 훑는다. 오늘 밤 올릴 것이
                     앞뒤가 맞는지 본다 — `run_daily.ps1` 8단계가 적재 **앞**에
                     두고 실패하면 그날 발행을 건너뛰는 그 관문이다.

둘이 한 덩어리로 묶여 있어 새로 clone 한 곳에서는 `unittest discover` 가 12건
에러로 시작했다(실측 2026-08-22). 데이터는 저장소에 없으니(그것이 설계다) 당연한
결과인데, 그 때문에 **공개 저장소에 CI 를 붙일 수 없었다** — 첫 실행부터 빨간불이라
"원래 저렇다"가 되면 검사가 신호이기를 그만둔다.

그래서 정합성 검사는 데이터가 없으면 건너뛴다. 단, 판단 기준을 원장 하나로만 둔다:

    output/messages.jsonl 이 있는가

있으면 관리자 컴퓨터이므로 **모든** 정합성 검사가 돌아야 한다. `topics.json` 같은
파일 하나가 없어진 것은 건너뛸 일이 아니라 터져야 할 일이다 — 그것이 곧 발행본이
깨졌다는 뜻이고, 조용히 건너뛰면 관문이 열린 채로 발행이 나간다. 그래서 여기서
보는 것은 딱 하나, "원장이 있는가"다.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "output" / "messages.jsonl"

#: 관리자 컴퓨터인가(= 실제 발행 데이터가 있는가).
AVAILABLE = LEDGER.exists()

REASON = ("실제 발행 데이터가 없습니다 (%s). 정합성 검사는 관리자 컴퓨터에서만 "
          "돕니다 — 대화 데이터는 저장소에 없습니다." % LEDGER.relative_to(ROOT))


def needs_real_data(obj):
    """정합성 검사임을 표시한다. 데이터가 없으면 건너뛴다.

    클래스에도 메서드에도 붙는다(`unittest.skipUnless` 가 둘 다 받는다).
    """
    return unittest.skipUnless(AVAILABLE, REASON)(obj)
