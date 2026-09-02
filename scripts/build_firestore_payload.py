# -*- coding: utf-8 -*-
"""output/* → Firestore 적재용 페이로드(JSON) 생성.

네트워크를 쓰지 않는 순수 변환 단계라 테스트로 검증할 수 있다. 실제 업로드는
얇은 Node 스크립트(`scripts/upload_firestore.js`)가 이 페이로드를 읽어 수행한다.

생성물 (`firestore-payload/`)
  meta.json            아카이브 요약·카테고리·통계
  threads.json         스레드 요약 — 멤버가 보는 본문(원문 대신)
  media.json           사진·첨부 목록 — 멤버 읽기
  my-messages.json     멤버별 '내가 쓴 글' — 본인만 읽기
  digests.json         주제별 지식 문서
  graph.json           지식 그래프(노드·엣지 벌크 2문서)
  messages-source.json 원본 전체 — 관리자 전용(P2 개별 숨김에 사용)
  members.json         멤버 명부(소문자 이메일 키)
  images.json          업로드할 이미지 경로 목록
  exclusion-report.json 무엇이 왜 제외됐는지

제외 규칙(`output/exclusions.json`)은 build_data 이전에 적용해, 통계·주제·그래프·
요지의 파생 데이터가 모두 '제외된 뒤'의 사실만 반영하게 한다.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path

from scripts import build_site, member_requests, ontology, pii, scan_image_pii, warnlog

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
CONFIG = ROOT / "config"
PAYLOAD = ROOT / "firestore-payload"
ASSETS_IMAGES = ROOT / "assets" / "images"

# ────────────────────────── 제외 규칙 ──────────────────────────

def load_exclusions() -> dict:
    path = OUTPUT / "exclusions.json"
    if not path.exists():
        return {"exclude_people": [], "exclude_keywords": [],
                "exclude_message_ids": [], "drop_person_apps": True}
    raw = build_site._read_json(path)
    return {
        "exclude_people": list(raw.get("exclude_people") or []),
        "exclude_keywords": list(raw.get("exclude_keywords") or []),
        "exclude_message_ids": list(raw.get("exclude_message_ids") or []),
        "drop_person_apps": bool(raw.get("drop_person_apps", True)),
    }


def apply_exclusions(messages: list[dict], exclusions: dict) -> tuple[list[dict], dict]:
    """제외 규칙에 걸리는 메시지를 걸러내고, 무엇이 왜 빠졌는지 리포트를 만든다."""
    people = {p.strip() for p in exclusions["exclude_people"] if p.strip()}
    keywords = [k for k in exclusions["exclude_keywords"] if k]
    ids = set(exclusions["exclude_message_ids"])

    kept, dropped = [], []
    for m in messages:
        reason = None
        if m["nickname"] in people:
            reason = "person"
        elif m["id"] in ids:
            reason = "message_id"
        else:
            text = m.get("text") or ""
            for kw in keywords:
                if kw in text:
                    reason = "keyword:" + kw
                    break
        if reason:
            dropped.append({"id": m["id"], "nickname": m["nickname"],
                            "date": m["date"], "reason": reason})
        else:
            kept.append(m)

    report = {
        "excluded_people": sorted(people),
        "excluded_keywords": keywords,
        "excluded_message_ids": sorted(ids),
        "dropped_count": len(dropped),
        "dropped_by_reason": dict(Counter(d["reason"] for d in dropped)),
        "dropped": dropped,
        "kept_count": len(kept),
    }
    return kept, report


def prune_topics(topics: dict, kept_ids: set[str]) -> dict:
    """제외된 메시지를 스레드에서 빼고, 빈 스레드는 버린다."""
    out = dict(topics)
    threads = []
    for t in topics["threads"]:
        ids = [mid for mid in t["message_ids"] if mid in kept_ids]
        if not ids:
            continue
        nt = dict(t)
        nt["message_ids"] = ids
        nt["start_msg"], nt["end_msg"] = ids[0], ids[-1]
        threads.append(nt)
    out["threads"] = threads
    return out


def rebuild_participants(messages: list[dict]) -> dict:
    """제외 반영 후의 메시지에서 참여자 통계를 다시 만든다.

    participants.json 을 그대로 쓰면 제외된 사람의 옛 카운트가 남으므로 재계산한다.
    """
    rows: dict[str, dict] = {}
    for m in messages:
        nk = m["nickname"]
        r = rows.get(nk)
        if r is None:
            rows[nk] = {"nickname": nk, "message_count": 1,
                        "first_timestamp": m["timestamp"], "last_timestamp": m["timestamp"]}
        else:
            r["message_count"] += 1
            if m["timestamp"] < r["first_timestamp"]:
                r["first_timestamp"] = m["timestamp"]
            if m["timestamp"] > r["last_timestamp"]:
                r["last_timestamp"] = m["timestamp"]
    ordered = sorted(rows.values(), key=lambda r: r["message_count"], reverse=True)
    return {"participants": ordered}


def prune_knowledge(knowledge: dict, messages: list[dict], exclusions: dict) -> dict:
    """제외된 인물의 노드와, (옵션) 그 사람이 만든 앱 노드를 그래프에서 제거."""
    people = {p.strip() for p in exclusions["exclude_people"] if p.strip()}
    if not people:
        return knowledge
    drop = {"person:" + p for p in people}
    if exclusions["drop_person_apps"]:
        for n in knowledge.get("nodes", []):
            if n.get("type") == "app" and n.get("maker") in people:
                drop.add(n["id"])
    nodes = [n for n in knowledge.get("nodes", []) if n["id"] not in drop]
    ids = {n["id"] for n in nodes}
    edges = [e for e in knowledge.get("edges", [])
             if e["source"] in ids and e["target"] in ids]
    out = dict(knowledge)
    out["nodes"], out["edges"] = nodes, edges
    return out


# ────────────────────────── 페이로드 조립 ──────────────────────────

# ── 문서 크기 — 한 곳에서 정한다 ──
#
# Firestore 문서는 1MiB 가 한도다. 넘으면 적재가 실패하고, 그날 밤 갱신이 멈춘다.
# 이 한도에 닿은 적이 세 번이다 — 요약을 서술형으로 늘리며 스레드 문서가 10배
# 가까이 커진 날, AI 검증 주석이 늘어 따로 뺀 날(2026-08-27), 그리고 주제가
# 400개가 되며 threads/all 이 안전선을 2,851 바이트 넘어 밤 갱신이 멈춘 날
# (2026-09-01). 셋 다 "데이터가 늘었다" 는 이유였고, 셋 다 터진 뒤에 알았다.
#
# 그래서 규칙을 뒤집는다. **늘어나는 것은 나눠 담고, 나눌 수 없는 것은 80% 에서
# 미리 말한다.**
#
#   나눠 담는 것    threads · aiReports · media — 항목 목록이라 크기로 자를 수 있다.
#                   업로더(upload_firestore.js chunkDocs)가 CHUNK_BYTES 로 자르고,
#                   화면(boot.js)은 컬렉션 전체를 이어 붙인다. 총량이 커지는 것은
#                   더 이상 고장이 아니다. 남는 위험은 하나 — **항목 하나**가 문서
#                   한 장보다 큰 경우. 그것만 검사한다.
#   나눌 수 없는 것  meta/archive · graph/nodes · graph/edges · digests/{분류} ·
#                   myMessages/{이메일} — 화면이 문서 하나를 이름으로 읽는다.
#                   DOC_LIMIT 를 넘으면 검사가 막고, WARN_LIMIT(80%) 를 넘으면
#                   발행 로그에 미리 적는다. 하루 몇 KB 씩 크는 것들이라 80% 에서
#                   말하면 터지기 몇 주 전이다.
#
# `plan_documents` 가 위 규칙으로 "실제로 어떤 문서가 몇 바이트로 올라가는가" 를
# 계산한다. 발행 로그의 경고와 tests/test_firestore_payload.py 의 검사가 같은
# 함수를 읽는다 — 두 벌로 적으면 어긋난다.
DOC_LIMIT = 700_000                 # 검사가 막는 선. 1MiB 아래로 여유를 둔다
WARN_LIMIT = int(DOC_LIMIT * 0.8)   # 발행 로그가 미리 말하는 선
# 업로더가 나눠 담을 때 자르는 크기(upload_firestore.js CHUNK_BYTES 와 같은 값).
CHUNK_BYTES = 600 * 1024
# 나눠 담는 컬렉션이 이 문서 수를 넘으면 검사가 막는다. 문서 수가 곧 모두의 첫
# 화면 읽기 수라, 조용히 늘게 두지 않는다.
CHUNK_DOCS_MAX = 6
# 예전 이름 — 검사와 다른 모듈이 아직 부를 수 있다.
MY_MESSAGES_LIMIT = DOC_LIMIT
BUNDLE_LIMIT = DOC_LIMIT


def _nbytes(obj) -> int:
    return len(json.dumps(obj, ensure_ascii=False).encode("utf-8"))


def content_hash(*parts) -> str:
    """멤버가 첫 화면에 받는 번들(threads·aiReports·media·digests·graph)의 지문.

    화면(boot.js)은 meta/archive 한 장을 읽고 이 값이 IndexedDB 에 둔 것과 같으면
    나머지 번들을 다시 받지 않는다. 방문마다 약 3.5MB 를 다시 받던 것이 바뀐 날만
    받게 된다. meta 자체는 늘 받으므로(1회 읽기) 여기 넣지 않는다.

    가린 **뒤의** 값으로 만든다 — 가리기 규칙이 바뀌면 내용이 바뀐 것이고, 화면도
    다시 받아야 한다.
    """
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def chunk_items(items: list, cap: int = CHUNK_BYTES) -> list[list]:
    """항목을 크기 기준으로 나눈다 — upload_firestore.js 의 chunkDocs 와 같은 규칙.

    개수가 아니라 **바이트**로 나눈다. 편마다 길이가 제각각이라 개수로 자르면
    어떤 묶음은 텅 비고 어떤 묶음은 한도를 넘는다. 항목이 없으면 빈 묶음 하나를
    남긴다 — 컬렉션이 통째로 사라지면 화면이 '아직 적재되지 않았다' 와 '없다' 를
    구분하지 못한다.

    JS 쪽 JSON.stringify 와 파이썬 json.dumps 는 공백·이스케이프가 조금 다르다.
    그래서 여기 수치는 정확히 같지 않고 몇 바이트 어긋날 수 있다 — 검사가 한도에
    300KB 여유를 두는 이유다.
    """
    docs: list[list] = []
    cur: list = []
    size = 2                          # "[]"
    for it in items:
        n = _nbytes(it) + 1
        if cur and size + n > cap:
            docs.append(cur)
            cur, size = [], 2
        cur.append(it)
        size += n
    docs.append(cur)
    return docs


def plan_documents(payload: dict) -> list[dict]:
    """발행본이 Firestore 에 어떤 문서로 올라가는지 — 이름·바이트·나눠 담는지.

    upload_firestore.js 의 main() 과 같은 모양이어야 한다. 그쪽이 컬렉션을 하나
    더 나누거나 합치면 여기도 따라 고친다 — 그래야 검사와 경고가 실제를 본다.
    (관리자 전용인 messagesSource 와 명부 members 는 멤버의 첫 화면 읽기가 아니고
    문서마다 작아서 세지 않는다.)
    """
    docs: list[dict] = []

    def one(coll: str, doc_id: str, obj) -> None:
        docs.append({"collection": coll, "id": doc_id, "bytes": _nbytes(obj),
                     "chunked": False})

    def many(coll: str, items: list) -> None:
        for i, part in enumerate(chunk_items(items)):
            docs.append({"collection": coll, "id": "%03d" % i,
                         "bytes": _nbytes({"items": part}), "chunked": True,
                         "largest_item": max((_nbytes(it) for it in part), default=0)})

    one("meta", "archive", payload["meta"])
    many("threads", payload["threads"])
    many("aiReports", payload["ai_reports"])
    many("media", payload["media"])
    for cat, obj in payload["digests"].items():
        one("digests", cat, obj)
    one("graph", "nodes", {"items": payload["graph"]["nodes"]})
    one("graph", "edges", {"items": payload["graph"]["edges"]})
    for email, items in payload["my_messages"].items():
        one("myMessages", email, {"items": items})
    return docs


def size_warnings(docs: list[dict]) -> list[str]:
    """발행 로그에 적을 크기 경고. 비어 있으면 아무 문서도 80% 에 안 닿았다.

    나눌 수 없는 문서는 WARN_LIMIT 에서, 나눠 담는 컬렉션은 항목 하나가
    CHUNK_BYTES 의 80% 에 닿을 때와 문서 수가 상한에 다가갈 때 말한다.
    """
    out: list[str] = []
    per_coll: dict[str, list[dict]] = {}
    for d in docs:
        per_coll.setdefault(d["collection"], []).append(d)
    for coll, ds in per_coll.items():
        if ds[0]["chunked"]:
            biggest = max(d["largest_item"] for d in ds)
            if biggest > CHUNK_BYTES * 0.8:
                out.append("%s 의 항목 하나가 %dKB — 문서 한 장(%dKB)의 80%% 를 넘었습니다. "
                           "나눠 담아도 그 항목은 안 들어가게 됩니다."
                           % (coll, biggest // 1024, CHUNK_BYTES // 1024))
            if len(ds) >= CHUNK_DOCS_MAX - 1:
                out.append("%s 가 %d문서로 갈라집니다 — 상한 %d 에 가깝습니다. "
                           "CHUNK_BYTES 나 상한을 다시 보세요."
                           % (coll, len(ds), CHUNK_DOCS_MAX))
            continue
        for d in ds:
            if d["bytes"] > WARN_LIMIT:
                out.append("%s/%s 문서가 %dKB — 검사 한도(%dKB)의 80%% 를 넘었습니다. "
                           "닿기 전에 나눠 담을 길을 정하세요."
                           % (coll, d["id"], d["bytes"] // 1024, DOC_LIMIT // 1024))
    return out


def build_my_messages(messages: list[dict], members: list[dict]) -> dict[str, list[dict]]:
    """멤버별로 '본인이 쓴 글'만 모은다.

    본인 글은 본인에게 원문으로 보여야 한다 — 무엇을 지울지 고르려면 봐야 하고,
    자기 글을 보는 건 개인정보 문제가 아니다. 반대로 남의 원문은 아무도 못 본다.

    메시지 하나하나를 문서로 두고 규칙으로 거르는 방법도 있지만, 그러면 378건
    쓴 사람이 화면을 열 때마다 378회를 읽는다. 사람별로 한 문서에 묶으면 1회다.
    메시지는 한 사람에게만 속하므로 이렇게 나눠도 전체 용량은 같다.
    """
    by_nickname: dict[str, list[dict]] = {}
    for m in messages:
        by_nickname.setdefault(m["nickname"], []).append(m)

    out: dict[str, list[dict]] = {}
    for mem in members:
        items: list[dict] = []
        for name in mem["nicknames"]:
            items.extend(by_nickname.get(name, []))
        if not items:
            continue
        # 시각으로 정렬한다. ID 순이 아니다 — 옛 백업을 합치면(backfill_export)
        # 2025년 글이 큰 번호를 받아, ID 로 줄세우면 본인 글이 뒤죽박죽 보인다.
        items.sort(key=lambda x: (x.get("date") or "", x.get("time") or "", x["id"]))
        out[mem["email"]] = items
    return out


def load_members() -> list[dict]:
    path = CONFIG / "members.json"
    if not path.exists():
        return []
    raw = build_site._read_json(path)
    members = []
    seen = set()
    for m in raw.get("members", []):
        email = (m.get("email") or "").strip().lower()
        if not email or email in seen:
            continue
        seen.add(email)
        role = m.get("role") or "user"
        if role not in ("admin", "user"):
            role = "user"
        # 표시명은 여러 개일 수 있다. 카톡에서 이름을 바꾸면 그 시점부터 다른
        # 참여자로 잡히므로, 하나만 붙들면 그 사람 글의 절반이 사라진다.
        raw_list = m.get("nicknames")
        if not isinstance(raw_list, list) or not raw_list:
            raw_list = [m.get("nickname")] if m.get("nickname") else []
        nicknames = []
        for n in raw_list:
            n = (n or "").strip()
            if n and n not in nicknames:
                nicknames.append(n)
        members.append({
            "email": email,
            "name": m.get("name") or "",
            # 대표 표시명 (화면 표시·하위호환)
            "nickname": nicknames[0] if nicknames else "",
            "nicknames": nicknames,
            "role": role,
            # 대화에 참여하지 않는 운영 계정은 false. 표시명 대조 경고를 넘긴다
            # (check_member_nicknames 의 주석 참고). 기본은 참여하는 사람.
            "speaks": m.get("speaks") is not False,
        })
    return members


def check_member_nicknames(members: list[dict], participants: dict) -> list[str]:
    """멤버의 표시명이 실제 참여자 명단에 있는지 대조한다.

    구글 계정(이메일)과 카톡 표시명은 공유하는 식별자가 없어 자동 매칭이 불가능하다.
    사람이 관리 화면에서 고르는 값이므로, 발행 때마다 어긋남을 경고로 남긴다.

    아직 발언한 적 없는 사람은 명단에 없는 게 정상이다 — 경고는 "확인해보라"는
    뜻이지 오류가 아니다.

    다만 **원래 발언하지 않는 계정**도 있다. 카톡 수집을 위해 컴퓨터에 로그인해 둔
    계정('문가은')이 그렇다 — 이 계정은 대화에 참여하지 않으므로 명단에 영영 없고,
    그대로 두면 매일 밤 같은 경고가 뜬다. 늘 뜨는 경고는 곧 아무도 안 보는 경고가
    되므로, `config/members.json` 에서 `"speaks": false` 로 표시하면 넘어간다.
    """
    known = {p["nickname"] for p in participants.get("participants", [])}
    warnings = []
    for m in members:
        if m.get("speaks") is False:
            continue
        if not m["nicknames"]:
            warnings.append("%s: 표시명 미연결 (개인화 기능이 동작하지 않음)" % m["email"])
            continue
        missing = [n for n in m["nicknames"] if n not in known]
        if missing:
            warnings.append(
                "%s: 표시명 %s 이 참여자 명단에 없음 (아직 발언이 없거나 오타)"
                % (m["email"], ", ".join("'%s'" % n for n in missing))
            )
    return warnings


def build_payload() -> dict:
    messages_raw = build_site._read_jsonl(OUTPUT / "messages.jsonl")
    images = build_site._read_jsonl(OUTPUT / "images.jsonl")
    topics = build_site._read_json(OUTPUT / "topics.json")
    knowledge = build_site._read_json(OUTPUT / "knowledge.json")

    # 사람 노드 동기화가 build_site.main() 에만 있었다. 일일 갱신은 build_site 를
    # 거치지 않고 여기로 오므로, 새 사람이 처음 말한 날 그 사람의 노드가 없어
    # test_person_nodes_match_participants 가 깨지고 배포까지 멈춘다(2026-07-27
    # '배유나'). 제외 반영 전의 명단으로 맞춘다 — output/knowledge.json 은 제외 전
    # 원장이고, 발행본에서 빼는 일은 아래 prune_knowledge 가 따로 한다.
    participants_raw = build_site._read_json(OUTPUT / "participants.json")
    added = build_site.sync_person_nodes(knowledge, participants_raw, topics)
    # 종류·관계 표를 코드(scripts/ontology.py)로 맞추고, 모양이 어긋난 엣지를
    # 고친다. 사람 노드 동기화 **뒤에** 해야 한다 — 방금 만든 person→topic 엣지도
    # 검사 대상이고, 어긋난 옛 엣지가 그것과 겹치는지 봐야 한다.
    ontology.log(ontology.apply(knowledge))
    (OUTPUT / "knowledge.json").write_text(
        json.dumps(knowledge, ensure_ascii=False, indent=2), encoding="utf-8")
    if added:
        print("    사람 노드 %d명 추가: %s" % (len(added), ", ".join(added)))

    digest_prose = build_site._read_json(OUTPUT / "topic-digests.json")
    # 첨부 원본은 나중에 사람이 모아 넣는다. 없으면 없는 대로 발행한다.
    files_path = OUTPUT / "files.jsonl"
    files = build_site._read_jsonl(files_path) if files_path.exists() else []

    # 멤버가 웹에서 낸 요청을 손으로 쓴 제외 규칙 위에 얹는다. 삭제 요청은 반드시
    # 소유권을 확인한 뒤에 반영한다 — 보안 규칙만으로는 남의 글을 지우려는 요청을
    # 막을 수 없다. member_requests 모듈 설명 참고.
    exclusions = load_exclusions()

    # 관리자가 뺀 주제는 그 주제의 메시지를 전부 제외하는 것과 같다. 기존 제외
    # machinery 를 그대로 태우면 통계·그래프·요지까지 일관되게 빠진다.
    hidden_threads = set(member_requests.load_hidden_threads())
    if hidden_threads:
        hidden_ids = [
            mid for t in topics["threads"] if t["id"] in hidden_threads
            for mid in t["message_ids"]
        ]
        exclusions = dict(exclusions)
        exclusions["exclude_message_ids"] = list(
            set(exclusions.get("exclude_message_ids") or []) | set(hidden_ids)
        )

    requests = member_requests.load_requests()
    resolved = member_requests.verify_ownership(requests, messages_raw)
    exclusions = member_requests.merge_into_exclusions(exclusions, resolved)

    kept, report = apply_exclusions(messages_raw, exclusions)
    report["hidden_threads"] = sorted(hidden_threads)
    report["member_requests"] = {
        "applied_people": resolved["exclude_people"],
        "applied_message_ids": len(resolved["exclude_message_ids"]),
        "rejected": resolved["rejected"],
    }
    kept_ids = {m["id"] for m in kept}

    topics_pruned = prune_topics(topics, kept_ids)
    knowledge_pruned = prune_knowledge(knowledge, kept, exclusions)
    participants = rebuild_participants(kept)

    data = build_site.build_data(
        kept, images, participants, topics_pruned, knowledge_pruned, digest_prose, files,
        build_site.load_secondary(),
        set(member_requests.interest_opt_outs(requests)),
    )

    # 원문 청크는 더 이상 멤버에게 발행하지 않는다.
    #
    # 예전에는 chunks 문서에 메시지 본문이 그대로 실려 나갔고, 화면에 안 보여도
    # devtools 로 1,500건을 전부 읽을 수 있었다. 이 방의 가치는 대화 자체가 아니라
    # 그 안의 내용이므로, 스레드 요약과 결과물(링크·사진·첨부)만 발행한다.
    # 원문이 필요한 곳은 두 군데뿐이고 둘 다 따로 다룬다:
    #   - 관리자 전체 열람   messagesSource (규칙이 관리자만 허용)
    #   - 본인 글 관리       messagesSource 중 본인 표시명 것만 (클레임으로 판정)
    threads_pub = build_site.enrich_threads(data["threads"], data["messages"])

    # 개인정보가 찍힌 사진은 발행하지 않는다. 판정은 OCR 로 미리 해 둔 것을 읽는다
    # (scripts/ocr_images.ps1 → scripts/scan_image_pii.py). 판정 파일이 없으면
    # 아무것도 감추지 않는다 — 검사를 아직 안 돌렸다고 발행이 멈추면 안 된다.
    hidden_images = scan_image_pii.hidden_paths()
    media = build_site.hide_pii_media(
        build_site.build_media(data["messages"]), hidden_images)
    members = load_members()
    my_messages = {
        # 본인 글의 본문은 가리지 않지만, 사진은 본인 것도 발행되지 않는다 —
        # Storage 규칙은 '멤버냐'만 보므로 올리는 순간 방 전체에 보인다. 대신
        # 왜 안 보이는지 화면에 적힐 수 있게 표시를 남긴다(원본은 로컬에 있다).
        email: build_site.hide_pii_media(items, hidden_images)
        for email, items in build_my_messages(data["messages"], members).items()
    }

    # 발행본에 실제로 등장하는 이미지·동영상만 업로드 대상으로 삼는다
    used_images: list[str] = []
    seen_img = set()
    for m in data["messages"]:
        # 원본과 갤러리용 작은 사진을 함께 올린다. 화면은 칸에 작은 것을 걸고
        # 누를 때 원본을 받으므로, 둘 중 하나만 올라가면 그 자리가 비어 보인다.
        #
        # `videos` 를 빠뜨렸었다(2026-07-28 발견). 그래서 동영상은 칸에 미리보기만
        # 걸리고 눌러도 파일이 없어 재생되지 않았다 — 화면 코드는 정상이었고
        # 저장소에 파일이 올라간 적이 없었던 것이다.
        #
        # 감출 사진은 **여기서** 빠져야 한다. 화면 발행본(media)에서만 빼고 올려
        # 두면 Storage 주소를 아는 사람은 화면을 거치지 않고 그대로 받는다 —
        # 관심 주제 빠지기에서 배운 것과 같은 함정이다. 원본이 감춰지면 그 짝인
        # 작은 사진도 함께 빠져야 한다(같은 그림이라 글자가 그대로 남아 있다).
        srcs = m.get("images") or []
        thumbs = m.get("thumbs") or []
        paths = []
        for i, src in enumerate(srcs):
            if src in hidden_images:
                continue
            paths.append(src)
            if i < len(thumbs):
                paths.append(thumbs[i])
        # 동영상은 사진 목록과 짝이 아니다(images 가 비어 있다). 그 포스터까지
        # 잃지 않도록, 사진이 없는 메시지의 작은 사진은 그대로 올린다.
        if not srcs:
            paths += thumbs
        paths += m.get("videos") or []
        for p in paths:
            if p not in seen_img:
                seen_img.add(p)
                used_images.append(p)

    # 발행본에 남은 메시지의 첨부만 업로드한다 (제외된 글의 파일까지 올리지 않는다)
    used_files = [
        f["local_path"] for f in files if f["message_id"] in {m["id"] for m in data["messages"]}
    ]

    meta = {
        "chat_room": data["chat_room"],
        "categories": data["categories"],
        "stats": data["stats"],
        "media_count": len(media),
        "my_message_owners": len(my_messages),
        "message_count": len(data["messages"]),
        "thread_count": len(threads_pub),
        "image_count": len(used_images),
        "file_count": len(used_files),
        # 태그 입구용 색인. 스레드 문서마다 태그가 이미 들어 있지만, 태그 목록을
        # 화면에서 만들려면 스레드 전체를 훑어야 해서 meta 에 미리 담아 둔다.
        "tag_index": data["tag_index"],
        "interests": data["interests"],
        "node_types": data["knowledge"].get("node_types", []),
        "edge_types": data["knowledge"].get("edge_types", []),
        "excluded_count": report["dropped_count"],
        "schema_version": 1,
    }

    graph = {
        "nodes": data["knowledge"].get("nodes", []),
        "edges": data["knowledge"].get("edges", []),
    }

    # ── 개인정보 가리기 ──
    #
    # 모두가 보는 것(요약·보고서·요지·미디어·관계망·태그)에서만 가린다. 빼는 곳이
    # 둘 있다:
    #   my_messages     본인 글은 본인에게 원문으로 보여야 한다. 무엇을 지울지
    #                   고르려면 봐야 하고, 자기 연락처를 자기가 보는 건 문제가 아니다.
    #   messages_source 규칙이 관리자만 허용하는 원장이다. 여기까지 가리면 관리자가
    #                   "원래 뭐였나" 를 확인할 길이 없어져 오탐을 못 되돌린다.
    allow = pii.load_allow()
    # AI 보고서는 threads/all 에서 빼내 따로 담는다.
    #
    # 386편 중 7편에만 있는데 문서 전체가 그만큼 무거워진다. 이 방의 화면은
    # threads/all 을 **들어올 때마다** 통째로 읽으므로, 몇 편이 늘 때마다 모두의
    # 첫 화면이 느려지는 셈이다. 게다가 앞으로 늘어날 글이라 한 문서에 두면
    # 1MiB 한도까지 남은 여유를 이쪽이 다 먹는다(측정 2026-08-27: 편당 2.6KB,
    # 남은 여유로 139편이면 한도).
    ai_reports = []
    for t in threads_pub:
        if not t.get("ai_report"):
            continue
        ai_reports.append({
            "id": t["id"],
            "ai_report": t.pop("ai_report"),
            "ai_checked": t.pop("ai_checked", ""),
            "ai_models": t.pop("ai_models", ""),
        })
    for t in threads_pub:            # 보고서가 없는 쪽에 남은 빈 열쇠도 지운다
        t.pop("ai_checked", None)
        t.pop("ai_models", None)

    threads_pub, h1 = pii.mask_tree(threads_pub, allow)
    ai_reports, _hr = pii.mask_tree(ai_reports, allow)
    digests_pub, h2 = pii.mask_tree(data["digests"], allow)
    media, h3 = pii.mask_tree(media, allow)
    graph, h4 = pii.mask_tree(graph, allow)
    meta, h5 = pii.mask_tree(meta, allow)
    pii_hits = h1 + h2 + h3 + h4 + h5
    meta["content_hash"] = content_hash(threads_pub, ai_reports, media, digests_pub, graph)

    return {
        "meta": meta,
        "threads": threads_pub,
        "ai_reports": ai_reports,
        "media": media,
        "my_messages": my_messages,
        "digests": digests_pub,
        "graph": graph,
        "messages_source": messages_raw,
        "members": members,
        "member_warnings": check_member_nicknames(members, participants),
        "images": used_images,
        "files": used_files,
        "exclusion_report": report,
        "pii_hits": pii_hits,
    }


def write_payload(payload: dict) -> None:
    if PAYLOAD.exists():
        shutil.rmtree(PAYLOAD)
    PAYLOAD.mkdir(parents=True)

    def dump(name: str, obj) -> None:
        (PAYLOAD / name).write_text(
            json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )

    dump("meta.json", payload["meta"])
    dump("threads.json", payload["threads"])
    dump("ai-reports.json", payload["ai_reports"])
    dump("media.json", payload["media"])
    dump("my-messages.json", payload["my_messages"])
    dump("digests.json", payload["digests"])
    dump("graph.json", payload["graph"])
    dump("messages-source.json", payload["messages_source"])
    dump("members.json", payload["members"])
    dump("images.json", payload["images"])
    dump("files.json", payload["files"])
    (PAYLOAD / "exclusion-report.json").write_text(
        json.dumps(payload["exclusion_report"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    payload = build_payload()
    write_payload(payload)
    # 발행 진입점에서만 경고 상태를 남긴다 — 검사가 build_payload 를 불러도 안 바뀐다.
    warnlog.save()
    r = payload["exclusion_report"]
    m = payload["meta"]
    print(
        "페이로드 생성 완료: 원문 %d(비발행) / 스레드 %d / 미디어 %d / 노드 %d / 엣지 %d"
        % (m["message_count"], m["thread_count"], m["media_count"],
           len(payload["graph"]["nodes"]), len(payload["graph"]["edges"]))
    )
    if payload["files"]:
        print("첨부 파일 %d건 연결" % len(payload["files"]))
    print("멤버 %d명" % len(payload["members"]))
    # 문서 크기 — 무엇이 몇 문서로 올라가고, 어디가 한도에 다가가는지.
    # 나눠 담는 컬렉션은 총량이 커도 고장이 아니므로 문서 수만 적는다(문서 수가
    # 곧 모두의 첫 화면 읽기 수다). 나눌 수 없는 문서는 80% 에서 미리 말한다.
    docs = plan_documents(payload)
    summary = []
    for coll in ("threads", "aiReports", "media"):
        ds = [d for d in docs if d["collection"] == coll]
        summary.append("%s %dKB→%d문서" % (coll, sum(d["bytes"] for d in ds) // 1024, len(ds)))
    mine = [d for d in docs if d["collection"] == "myMessages"]
    if mine:
        summary.append("내 글 %d명분(최대 %dKB)"
                       % (len(mine), max(d["bytes"] for d in mine) // 1024))
    print("문서 %d개: %s" % (len(docs), " · ".join(summary)))
    for w in size_warnings(docs):
        print("[주의] " + w)
    hidden_shots = sum(m.get("pii_hidden") or 0 for m in payload["media"])
    if hidden_shots:
        print("개인정보가 찍힌 사진 %d장 발행 제외 (업로드 목록에서도 뺐습니다)"
              % hidden_shots)

    hits = payload["pii_hits"]
    if hits:
        certain = [h for h in hits if h.grade == "certain"]
        likely = [h for h in hits if h.grade == "likely"]
        print("개인정보 %d건 가림 (%s)" % (len(certain), pii.summarize(hits)))
        # 경고 등급은 사람이 봐야 한다 — 가리지 않았으므로 그대로 발행된다.
        for h in likely[:10]:
            print("[개인정보 확인] %s %s — 근처에 연락처를 뜻하는 말이 없어 "
                  "가리지 않았습니다. 개인정보면 config/pii_allow.json 반대편, 즉 "
                  "원문 제외 규칙을 쓰세요." % (h.kind, h.value))
    else:
        print("개인정보 검사: 가릴 것 없음")

    for w in payload["member_warnings"]:
        print("[닉네임 확인] %s" % w)
    if r["dropped_count"]:
        print("제외됨 %d건 %s" % (r["dropped_count"], r["dropped_by_reason"]))
    else:
        print("제외 규칙 적용 결과: 제외된 메시지 없음")

    if r["hidden_threads"]:
        print("발행 제외 주제 %d개: %s"
              % (len(r["hidden_threads"]), ", ".join(r["hidden_threads"][:5])))
    mr = r["member_requests"]
    if mr["applied_people"] or mr["applied_message_ids"]:
        print("멤버 요청 반영: 발행 제외 %d명, 개별 메시지 %d건"
              % (len(mr["applied_people"]), mr["applied_message_ids"]))
    for rej in mr["rejected"]:
        # 남의 글을 지우려는 요청은 조용히 넘기지 않는다
        print("[요청 거부] %s → %s (%s)" % (rej["email"], rej["message_id"], rej["reason"]))
    if not payload["members"]:
        print("[주의] config/members.json 이 없어 아무도 접근할 수 없는 규칙이 생성되었습니다.")


if __name__ == "__main__":
    main()
