# -*- coding: utf-8 -*-
"""output/* → Firestore 적재용 페이로드(JSON) 생성.

네트워크를 쓰지 않는 순수 변환 단계라 테스트로 검증할 수 있다. 실제 업로드는
얇은 Node 스크립트(`scripts/upload_firestore.js`)가 이 페이로드를 읽어 수행한다.

생성물 (`firestore-payload/`)
  meta.json            아카이브 요약·카테고리·통계
  chunks.json          발행본 메시지 청크(기본 100건/문서) — 멤버 읽기
  threads.json         주제 스레드
  digests.json         주제별 지식 문서
  graph.json           지식 그래프(노드·엣지 벌크 2문서)
  messages-source.json 원본 전체 — 관리자 전용(P2 개별 숨김에 사용)
  members.json         멤버 명부(소문자 이메일 키)
  images.json          업로드할 이미지 경로 목록
  exclusion-report.json 무엇이 왜 제외됐는지

부수 효과
  storage.rules        config/storage.rules.template + 멤버 목록으로 생성

제외 규칙(`output/exclusions.json`)은 build_data 이전에 적용해, 통계·주제·그래프·
요지의 파생 데이터가 모두 '제외된 뒤'의 사실만 반영하게 한다.
"""
from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path

from scripts import build_site

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
CONFIG = ROOT / "config"
PAYLOAD = ROOT / "firestore-payload"
ASSETS_IMAGES = ROOT / "assets" / "images"

CHUNK_SIZE = 100


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

def chunk_messages(messages: list[dict], size: int = CHUNK_SIZE) -> list[dict]:
    """메시지를 청크 문서로 나눈다.

    문서당 1건씩 두면 전체 로드에 1,500회 읽기가 들지만, 100건씩 묶으면 ~16회로
    줄어든다. 과거 대화는 불변이라 청크가 적합하다.
    """
    chunks = []
    for i in range(0, len(messages), size):
        part = messages[i:i + size]
        seq = len(chunks)
        chunks.append({
            "id": "c%04d" % seq,
            "seq": seq,
            "count": len(part),
            "first_msg": part[0]["id"],
            "last_msg": part[-1]["id"],
            "date_start": part[0]["date"],
            "date_end": part[-1]["date"],
            "messages": part,
        })
    return chunks


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
        members.append({"email": email, "name": m.get("name") or "", "role": role})
    return members


def render_storage_rules(members: list[dict]) -> str:
    """멤버 목록을 박아 넣은 storage.rules 텍스트를 만든다."""
    template = (CONFIG / "storage.rules.template").read_text(encoding="utf-8")
    if members:
        lines = ",\n".join('          "%s"' % m["email"] for m in members)
    else:
        # 멤버가 없으면 아무도 통과하지 못하는 목록(빈 허용목록)을 넣는다.
        lines = '          "__no_member_configured__"'
    return template.replace("__MEMBER_EMAILS__", lines)


def build_payload() -> dict:
    messages_raw = build_site._read_jsonl(OUTPUT / "messages.jsonl")
    images = build_site._read_jsonl(OUTPUT / "images.jsonl")
    topics = build_site._read_json(OUTPUT / "topics.json")
    knowledge = build_site._read_json(OUTPUT / "knowledge.json")
    digest_prose = build_site._read_json(OUTPUT / "topic-digests.json")

    exclusions = load_exclusions()
    kept, report = apply_exclusions(messages_raw, exclusions)
    kept_ids = {m["id"] for m in kept}

    topics_pruned = prune_topics(topics, kept_ids)
    knowledge_pruned = prune_knowledge(knowledge, kept, exclusions)
    participants = rebuild_participants(kept)

    data = build_site.build_data(
        kept, images, participants, topics_pruned, knowledge_pruned, digest_prose
    )

    chunks = chunk_messages(data["messages"])
    members = load_members()

    # 발행본에 실제로 등장하는 이미지만 업로드 대상으로 삼는다
    used_images: list[str] = []
    seen_img = set()
    for m in data["messages"]:
        for p in m.get("images", []) or []:
            if p not in seen_img:
                seen_img.add(p)
                used_images.append(p)

    meta = {
        "chat_room": data["chat_room"],
        "categories": data["categories"],
        "stats": data["stats"],
        "chunk_count": len(chunks),
        "chunk_size": CHUNK_SIZE,
        "message_count": len(data["messages"]),
        "thread_count": len(data["threads"]),
        "image_count": len(used_images),
        "node_types": data["knowledge"].get("node_types", []),
        "edge_types": data["knowledge"].get("edge_types", []),
        "excluded_count": report["dropped_count"],
        "schema_version": 1,
    }

    return {
        "meta": meta,
        "chunks": chunks,
        "threads": data["threads"],
        "digests": data["digests"],
        "graph": {
            "nodes": data["knowledge"].get("nodes", []),
            "edges": data["knowledge"].get("edges", []),
        },
        "messages_source": messages_raw,
        "members": members,
        "images": used_images,
        "exclusion_report": report,
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
    dump("chunks.json", payload["chunks"])
    dump("threads.json", payload["threads"])
    dump("digests.json", payload["digests"])
    dump("graph.json", payload["graph"])
    dump("messages-source.json", payload["messages_source"])
    dump("members.json", payload["members"])
    dump("images.json", payload["images"])
    (PAYLOAD / "exclusion-report.json").write_text(
        json.dumps(payload["exclusion_report"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # storage.rules 생성 (멤버 허용목록 주입)
    (ROOT / "storage.rules").write_text(
        render_storage_rules(payload["members"]), encoding="utf-8"
    )


def main() -> None:
    payload = build_payload()
    write_payload(payload)
    r = payload["exclusion_report"]
    m = payload["meta"]
    print(
        "페이로드 생성 완료: 메시지 %d / 청크 %d / 스레드 %d / 노드 %d / 엣지 %d / 이미지 %d"
        % (m["message_count"], m["chunk_count"], m["thread_count"],
           len(payload["graph"]["nodes"]), len(payload["graph"]["edges"]),
           m["image_count"])
    )
    print("멤버 %d명, storage.rules 생성" % len(payload["members"]))
    if r["dropped_count"]:
        print("제외됨 %d건 %s" % (r["dropped_count"], r["dropped_by_reason"]))
    else:
        print("제외 규칙 적용 결과: 제외된 메시지 없음")
    if not payload["members"]:
        print("[주의] config/members.json 이 없어 아무도 접근할 수 없는 규칙이 생성되었습니다.")


if __name__ == "__main__":
    main()
