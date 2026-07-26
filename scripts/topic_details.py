"""주제 상세 요약 오버레이.

한 줄 요약(평균 31자)만으로는 원문 없이 내용을 알 수 없다는 지적에서 나왔다.
원문을 발행하지 않기로 한 이상 요약이 원문을 대신해야 하므로, 스레드마다
서술형 본문(detail)과 핵심 항목(points)을 따로 써서 얹는다.

topics.json 을 직접 고치지 않고 별도 파일로 두는 이유:
  - 증분 수집(ingest_incremental)이 topics.json 에 미분류 스레드를 계속 덧붙인다.
    같은 파일을 양쪽에서 만지면 손으로 쓴 요약이 덮여 날아간다.
  - 상세 요약은 사람이 원문을 읽고 쓴 것이라 재생성이 비싸다. 분리해 두면
    파이프라인을 몇 번을 다시 돌려도 남는다.

형식(output/topic-details.json):
    {"t-001": {"title": "...", "summary": "...",
               "detail": "...", "points": ["...", ...]}, ...}
title 과 summary 는 있으면 topics.json 의 값을 덮어쓴다(없으면 원래 값 유지).
"""

from __future__ import annotations

import json
from pathlib import Path

DETAILS_PATH = Path(__file__).resolve().parent.parent / "output" / "topic-details.json"


def load_details(path: Path | None = None) -> dict[str, dict]:
    """상세 요약을 읽는다. 파일이 없으면 빈 dict — 오버레이는 선택 사항이다."""
    p = path or DETAILS_PATH
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("topic-details.json 은 {스레드ID: {...}} 형태여야 합니다")
    return data


def apply_details(threads: list[dict], details: dict[str, dict]) -> int:
    """스레드 목록에 상세 요약을 얹는다. 얹은 개수를 돌려준다.

    threads 를 제자리에서 고친다. 오버레이에만 있고 스레드에는 없는 ID 는
    조용히 무시한다 — 주제가 합쳐지거나 사라져도 파이프라인이 멈추면 안 된다.
    """
    applied = 0
    for t in threads:
        d = details.get(t["id"])
        if not d:
            continue
        if d.get("title"):
            t["title"] = d["title"]
        if d.get("summary"):
            t["summary"] = d["summary"]
        if d.get("detail"):
            t["detail"] = d["detail"]
        if d.get("points"):
            t["points"] = list(d["points"])
        applied += 1
    return applied
