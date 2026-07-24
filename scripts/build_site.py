# -*- coding: utf-8 -*-
"""카카오톡 수집 데이터를 정적 아카이빙 사이트(site/)로 빌드한다.

입력: output/messages.jsonl, output/images.jsonl, output/participants.json,
      output/topics.json, web/{index.html,app.js,styles.css}, assets/images/**
출력: site/{index.html,app.js,styles.css,data.js,assets/images/**}

data.js 는 `window.ARCHIVE = {...}` 형태로 전체 데이터를 임베드한다. file:// 로
직접 열어도 fetch 없이 <script src> 로 로드되도록 하기 위함이다. 원본 output/·
assets/ 는 수정하지 않으며, 재실행 시 site/ 를 새로 만든다.
"""
from __future__ import annotations

import json
import shutil
from collections import Counter, OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
ASSETS_IMAGES = ROOT / "assets" / "images"
WEB = ROOT / "web"
SITE = ROOT / "site"

STATIC_FILES = ("index.html", "app.js", "styles.css", "graph.js", "images.js")


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _month(date: str) -> str:
    """'2026-05-11' -> '2026-05'"""
    return date[:7]


def build_digests(
    out_messages: list[dict],
    threads_meta: list[dict],
    topics: dict,
    knowledge: dict,
    digest_prose: dict,
) -> dict:
    """카테고리별 지식 문서를 조립한다: 요지 산문(digest_prose) + 파생 리소스
    (주요 앱·공유 링크·활발한 참여자·소속 스레드)."""
    prose = digest_prose.get("digests", {})
    # 카테고리별 앱 노드
    apps_by_cat: dict[str, list] = {}
    for n in knowledge.get("nodes", []):
        if n.get("type") == "app":
            apps_by_cat.setdefault(n["category"], []).append(
                {"label": n["label"], "maker": n.get("maker"), "query": n.get("query")}
            )
    # 카테고리별 링크·참여자
    links_by_cat: dict[str, list] = {}
    seen_url: dict[str, set] = {}
    nick_by_cat: dict[str, Counter] = {}
    for m in out_messages:
        cat = m.get("category")
        if not cat:
            continue
        nick_by_cat.setdefault(cat, Counter())[m["nickname"]] += 1
        for u in m.get("urls", []):
            s = seen_url.setdefault(cat, set())
            if u not in s:
                s.add(u)
                links_by_cat.setdefault(cat, []).append(
                    {"url": u, "nickname": m["nickname"], "date": m["date"], "msg_id": m["id"]}
                )
    threads_by_cat: dict[str, list] = {}
    for t in threads_meta:
        threads_by_cat.setdefault(t["category"], []).append(t)

    digests = {}
    for c in topics["categories"]:
        cid = c["id"]
        p = prose.get(cid, {})
        top_nicks = [
            {"nickname": nk, "count": n}
            for nk, n in nick_by_cat.get(cid, Counter()).most_common(8)
        ]
        digests[cid] = {
            "id": cid,
            "label": c["label"],
            "headline": p.get("headline", ""),
            "overview": p.get("overview", ""),
            "keywords": p.get("keywords", []),
            "apps": apps_by_cat.get(cid, []),
            "links": links_by_cat.get(cid, []),
            "participants": top_nicks,
            "threads": threads_by_cat.get(cid, []),
            "message_count": sum(t["count"] for t in threads_by_cat.get(cid, [])),
        }
    return digests


def build_data(
    messages: list[dict],
    images: list[dict],
    participants: dict,
    topics: dict,
    knowledge: dict | None = None,
    digest_prose: dict | None = None,
) -> dict:
    """수집 데이터를 화면 렌더링용 단일 딕셔너리로 조립한다."""
    # 이미지 메시지 → 다운로드된 로컬 경로 매핑
    image_by_id = {img["image_id"]: img for img in images}

    # 메시지 → 스레드/카테고리 매핑
    msg_thread: dict[str, dict] = {}
    for thread in topics["threads"]:
        for mid in thread["message_ids"]:
            msg_thread[mid] = thread

    downloaded_assets = 0
    out_messages = []
    for m in messages:
        item = {
            "id": m["id"],
            "date": m["date"],
            "time": m["time"],
            "nickname": m["nickname"],
            "text": m.get("text") or "",
            "kind": m["kind"],
            "urls": m.get("urls") or [],
            "is_file_share": bool(m.get("is_file_share")),
        }
        thread = msg_thread.get(m["id"])
        if thread:
            item["thread_id"] = thread["id"]
            item["category"] = thread["category"]

        if m["kind"] == "image":
            img = image_by_id.get(m.get("image_id"))
            paths = []
            if img:
                for asset in img.get("assets", []):
                    lp = asset.get("local_path")
                    if lp:
                        # 원본 경로는 'assets/images/...' → 사이트 기준 상대경로 그대로 사용
                        paths.append(lp.replace("\\", "/"))
            item["images"] = paths
            item["image_pending"] = len(paths) == 0
            item["image_count"] = (
                m.get("image_count")
                or (img.get("expected_asset_count") if img else None)
                or 1
            )
            downloaded_assets += len(paths)

        out_messages.append(item)

    # ── 통계 ──
    per_nick = OrderedDict()
    for p in participants.get("participants", []):
        per_nick[p["nickname"]] = {
            "nickname": p["nickname"],
            "message_count": p.get("message_count", 0),
            "first_timestamp": p.get("first_timestamp"),
            "last_timestamp": p.get("last_timestamp"),
            "text": 0,
            "image": 0,
            "file": 0,
        }
    month_counter: Counter[str] = Counter()
    url_total = 0
    for m in messages:
        month_counter[_month(m["date"])] += 1
        url_total += len(m.get("urls") or [])
        row = per_nick.get(m["nickname"])
        if row is None:
            row = per_nick.setdefault(
                m["nickname"],
                {"nickname": m["nickname"], "message_count": 0, "first_timestamp": None,
                 "last_timestamp": None, "text": 0, "image": 0, "file": 0},
            )
        if m["kind"] in ("text", "image", "file"):
            row[m["kind"]] += 1

    participant_stats = sorted(
        per_nick.values(), key=lambda r: r["message_count"], reverse=True
    )
    monthly = [
        {"month": mth, "count": month_counter[mth]} for mth in sorted(month_counter)
    ]

    # 카테고리별 스레드/메시지 분포
    cat_labels = {c["id"]: c["label"] for c in topics["categories"]}
    cat_threads: Counter[str] = Counter()
    cat_messages: Counter[str] = Counter()
    for thread in topics["threads"]:
        cat_threads[thread["category"]] += 1
        cat_messages[thread["category"]] += len(thread["message_ids"])
    category_stats = [
        {
            "id": c["id"],
            "label": c["label"],
            "threads": cat_threads.get(c["id"], 0),
            "messages": cat_messages.get(c["id"], 0),
        }
        for c in topics["categories"]
    ]

    kind_counter = Counter(m["kind"] for m in messages)

    # 스레드 요약(타임라인/주제별 뷰용). message_ids 는 유지하되 화면에서 참조.
    threads_meta = []
    for t in topics["threads"]:
        ids = t["message_ids"]
        threads_meta.append(
            {
                "id": t["id"],
                "category": t["category"],
                "title": t["title"],
                "summary": t.get("summary", ""),
                "start_msg": ids[0],
                "end_msg": ids[-1],
                "count": len(ids),
            }
        )
    # 스레드별 참여자·기간 계산
    msg_index = {m["id"]: m for m in out_messages}
    for tmeta, t in zip(threads_meta, topics["threads"]):
        ids = t["message_ids"]
        nicks = []
        seen = set()
        for mid in ids:
            nk = msg_index[mid]["nickname"]
            if nk not in seen:
                seen.add(nk)
                nicks.append(nk)
        tmeta["participants"] = nicks
        tmeta["start_date"] = msg_index[ids[0]]["date"]
        tmeta["end_date"] = msg_index[ids[-1]]["date"]

    knowledge = knowledge or {"nodes": [], "edges": [], "node_types": [], "edge_types": []}
    digests = build_digests(
        out_messages, threads_meta, topics, knowledge, digest_prose or {}
    )

    return {
        "chat_room": topics.get("chat_room", "카카오톡 아카이브"),
        "generated_from": {
            "messages": len(messages),
            "participants": len(participant_stats),
            "downloaded_images": downloaded_assets,
        },
        "categories": topics["categories"],
        "messages": out_messages,
        "threads": threads_meta,
        "digests": digests,
        "knowledge": {
            "nodes": knowledge.get("nodes", []),
            "edges": knowledge.get("edges", []),
            "node_types": knowledge.get("node_types", []),
            "edge_types": knowledge.get("edge_types", []),
        },
        "stats": {
            "totals": {
                "messages": len(messages),
                "participants": len(participant_stats),
                "urls": url_total,
                "files": kind_counter.get("file", 0),
                "images": kind_counter.get("image", 0),
                "downloaded_images": downloaded_assets,
                "date_start": messages[0]["date"] if messages else None,
                "date_end": messages[-1]["date"] if messages else None,
            },
            "participants": participant_stats,
            "monthly": monthly,
            "categories": category_stats,
            "kinds": dict(kind_counter),
        },
        "_labels": cat_labels,
    }


def write_site(data: dict) -> None:
    if SITE.exists():
        shutil.rmtree(SITE)
    SITE.mkdir(parents=True)

    # data.js
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    (SITE / "data.js").write_text(
        "window.ARCHIVE = " + payload + ";\n", encoding="utf-8"
    )

    # 정적 파일 복사
    for name in STATIC_FILES:
        shutil.copyfile(WEB / name, SITE / name)

    # 이미지 복사 (다운로드된 것만 존재)
    if ASSETS_IMAGES.exists():
        dest = SITE / "assets" / "images"
        shutil.copytree(ASSETS_IMAGES, dest)


def main() -> None:
    messages = _read_jsonl(OUTPUT / "messages.jsonl")
    images = _read_jsonl(OUTPUT / "images.jsonl")
    participants = _read_json(OUTPUT / "participants.json")
    topics = _read_json(OUTPUT / "topics.json")
    knowledge = _read_json(OUTPUT / "knowledge.json")
    digest_prose = _read_json(OUTPUT / "topic-digests.json")

    data = build_data(messages, images, participants, topics, knowledge, digest_prose)
    write_site(data)

    t = data["stats"]["totals"]
    print(
        f"site/ 생성 완료 · 메시지 {t['messages']} · 참여자 {t['participants']} · "
        f"다운로드 이미지 {t['downloaded_images']} · 스레드 {len(data['threads'])}"
    )


if __name__ == "__main__":
    main()
