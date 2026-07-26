# -*- coding: utf-8 -*-
"""수집 단계 정책 — 아카이브 '원본'에 아예 넣지 않을 메시지를 가려낸다.

제외에는 두 층이 있고, 되돌릴 수 있느냐가 다르다.

  수집 거부 (이 모듈)      원본 messages.jsonl 에 애초에 안 들어간다.
                           나중에 마음이 바뀌어도 그 기간은 복구할 수 없다.
                           내보낸 txt 를 다시 넣어야 하는데 카톡 대화방 이력이
                           남아 있어야 가능하다.

  발행 제외 (exclusions)   원본에는 남고 발행본에서만 빠진다.
                           설정을 되돌리면 다시 보인다. 관리자는 볼 수 있다.

기본 규칙은 **메시지 본문에 `[제외]` 를 넣으면 그 메시지는 수집하지 않는다** 이다.
글 쓰는 사람이 그 자리에서 결정할 수 있어 가장 손이 덜 간다.

한계 (문서화해 두는 편이 낫다)
  - 사진에는 본문이 없어 키워드를 붙일 수 없다. 사진은 사람/전체 설정으로 다룬다.
  - 이미 보낸 글에 소급 적용되지 않는다. 나중에 지우려면 '발행 제외'를 쓴다.
  - 키워드가 대화방에 그대로 보인다. 명시적이라는 장점이자 단점이다.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from scripts import build_site

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
POLICY_PATH = CONFIG / "collection-policy.json"

# 설정 파일이 없어도 동작하는 기본값. 전각 대괄호도 함께 받는다 —
# 모바일 자판에서 「［」가 섞여 들어오면 사용자는 제외한 줄 알고 넘어간다.
DEFAULT_KEYWORDS = ["[제외]", "［제외］"]


def load_policy() -> dict:
    """수집 정책을 읽는다. 파일이 없으면 기본 키워드만 적용한다."""
    if not POLICY_PATH.exists():
        return {"keywords": list(DEFAULT_KEYWORDS), "opt_out_people": []}
    raw = build_site._read_json(POLICY_PATH)
    keywords = raw.get("keywords")
    if keywords is None:
        keywords = list(DEFAULT_KEYWORDS)
    return {
        "keywords": [k for k in keywords if k],
        "opt_out_people": [p.strip() for p in (raw.get("opt_out_people") or []) if p.strip()],
    }


def rejection_reason(nickname: str, text: str | None, policy: dict) -> str | None:
    """수집하지 말아야 할 메시지면 이유를, 아니면 None 을 돌려준다."""
    if nickname in policy["opt_out_people"]:
        return "person"
    body = text or ""
    for kw in policy["keywords"]:
        if kw in body:
            return "keyword:" + kw
    return None


def filter_messages(messages, policy: dict):
    """파서가 낸 메시지에서 수집 대상만 남긴다.

    반환: (남긴 목록, 사유별 건수, 버린 항목 요약)
    버린 항목은 본문을 남기지 않는다 — 수집하지 않기로 한 글을 로그에 흘리면
    설정의 의미가 없어진다. 누가 언제 몇 건인지까지만 남긴다.
    """
    kept, dropped = [], []
    reasons = Counter()
    for msg in messages:
        reason = rejection_reason(msg.nickname, msg.text, policy)
        if reason:
            reasons[reason] += 1
            dropped.append({"nickname": msg.nickname, "timestamp": msg.timestamp,
                            "reason": reason})
        else:
            kept.append(msg)
    return kept, dict(reasons), dropped
