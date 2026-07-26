# -*- coding: utf-8 -*-
"""멤버가 웹에서 낸 요청(수집 동의·삭제)을 파이프라인이 쓸 형태로 바꾼다.

네트워크는 scripts/sync_member_requests.js 가 담당하고, 이 모듈은 그 결과 파일
(`output/member-requests.json`)만 읽는다. 덕분에 반영 로직을 테스트할 수 있다.

요청은 두 곳으로 갈린다.

  collection == "none"         수집 단계에서 막는다 (collection_policy)
  collection == "unpublished"  발행 단계에서 뺀다   (exclusions)
  삭제 요청                     발행 단계에서 해당 메시지만 뺀다

**소유권 검증이 이 모듈의 핵심이다.** 보안 규칙은 "본인 문서에만 쓴다"까지만
보장하고, 그 문서 안에 남의 메시지 ID 를 적는 것은 막지 못한다(규칙에서 다른
문서를 조회할 수 없다). 그래서 반영 직전에 messages.jsonl 과 대조해, 요청자
본인의 메시지가 아닌 ID 는 버리고 리포트에 남긴다.
"""
from __future__ import annotations

from pathlib import Path

from scripts import build_site

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
REQUESTS_PATH = OUTPUT / "member-requests.json"

VALID_MODES = ("public", "unpublished", "none")


def load_requests() -> list[dict]:
    """요청 파일을 읽는다. 없으면 빈 목록 — 아직 아무도 요청하지 않은 상태다."""
    if not REQUESTS_PATH.exists():
        return []
    raw = build_site._read_json(REQUESTS_PATH)
    rows = []
    for r in raw.get("requests", []):
        # 한 사람이 표시명을 여러 개 가질 수 있다 (카톡에서 이름을 바꾼 경우).
        raw_names = r.get("nicknames")
        if not isinstance(raw_names, list):
            raw_names = [r.get("nickname")] if r.get("nickname") else []
        nicknames = []
        for n in raw_names:
            n = (n or "").strip()
            if n and n not in nicknames:
                nicknames.append(n)
        if not nicknames:
            # 표시명이 없으면 어느 메시지가 이 사람 것인지 알 수 없다.
            # sync 스크립트가 이미 경고했으므로 여기서는 조용히 건너뛴다.
            continue
        mode = r.get("collection") or "public"
        if mode not in VALID_MODES:
            mode = "public"
        rows.append({
            "email": (r.get("email") or "").strip().lower(),
            "nicknames": nicknames,
            "collection": mode,
            "delete_all": bool(r.get("delete_all")),
            "delete_message_ids": [str(i) for i in (r.get("delete_message_ids") or [])],
        })
    return rows


def collection_opt_outs(requests: list[dict]) -> list[str]:
    """수집 자체를 거부한 사람의 대화방 표시명(쓰던 이름 전부)."""
    out = set()
    for r in requests:
        if r["collection"] == "none":
            out.update(r["nicknames"])
    return sorted(out)


def verify_ownership(requests: list[dict], messages: list[dict]) -> dict:
    """삭제 요청을 본인 메시지로만 좁힌다.

    반환
      exclude_people       발행에서 통째로 뺄 사람 (collection == "unpublished")
      exclude_message_ids  발행에서 뺄 개별 메시지
      rejected             본인 것이 아니어서 거부한 요청 (감사 로그용)
    """
    owner_of = {m["id"]: m["nickname"] for m in messages}
    ids_by_nickname: dict[str, list[str]] = {}
    for m in messages:
        ids_by_nickname.setdefault(m["nickname"], []).append(m["id"])

    exclude_people: set[str] = set()
    exclude_ids: set[str] = set()
    rejected: list[dict] = []

    for r in requests:
        names = r["nicknames"]

        if r["collection"] == "unpublished":
            exclude_people.update(names)

        # '전체 삭제'는 지금 시점의 내 글을 스냅샷으로 담는다. 앞으로 쓰는 글까지
        # 막는 설정이 아니다 — 그건 수집 동의(unpublished/none)가 할 일이다.
        if r["delete_all"]:
            for n in names:
                exclude_ids.update(ids_by_nickname.get(n, []))

        for mid in r["delete_message_ids"]:
            owner = owner_of.get(mid)
            if owner is None:
                rejected.append({"email": r["email"], "message_id": mid,
                                 "reason": "없는 메시지"})
            elif owner not in names:
                # 남의 글을 지우려는 요청. 규칙으로는 막을 수 없어 여기서 걸러낸다.
                rejected.append({"email": r["email"], "message_id": mid,
                                 "reason": "본인 메시지가 아님"})
            else:
                exclude_ids.add(mid)

    return {
        "exclude_people": sorted(exclude_people),
        "exclude_message_ids": sorted(exclude_ids),
        "rejected": rejected,
    }


def merge_into_exclusions(exclusions: dict, resolved: dict) -> dict:
    """손으로 쓴 exclusions.json 위에 멤버 요청을 얹는다.

    손으로 넣은 항목을 지우지 않는다 — 관리자가 별도 사유로 넣어둔 것일 수 있다.
    """
    out = dict(exclusions)
    out["exclude_people"] = sorted(
        set(exclusions.get("exclude_people") or []) | set(resolved["exclude_people"])
    )
    out["exclude_message_ids"] = sorted(
        set(exclusions.get("exclude_message_ids") or []) | set(resolved["exclude_message_ids"])
    )
    return out
