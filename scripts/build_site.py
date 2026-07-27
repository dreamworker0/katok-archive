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
import math
import shutil
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

from scripts.topic_reports import (
    apply_reports,
    content_chars,
    load_reports,
    place_context_anchors,
    thin_reports,
)

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
ASSETS_IMAGES = ROOT / "assets" / "images"
ASSETS_THUMBS = ROOT / "assets" / "thumbs"
ASSETS_VIDEOS = ROOT / "assets" / "videos"
WEB = ROOT / "web"
SITE = ROOT / "site"

STATIC_FILES = ("index.html", "app.js", "styles.css", "graph.js", "images.js", "favicon.svg")
STATIC_DIRS = ("art",)


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

    # 앱 → 그 앱이 나온 주제. 예전에는 화면에서 query 로 원문을 검색했는데,
    # 원문 발행을 멈추면서 검색할 대상이 사라져 버튼이 빈 목록으로 갔다.
    # 여기서 원문을 보고 미리 이어 둔다 — 보고서를 어떻게 쓰든 흔들리지 않는다.
    thread_of_msg = {}
    for t in topics["threads"]:
        for mid in t["message_ids"]:
            thread_of_msg[mid] = t["id"]

    def threads_matching(query: str, label: str) -> list[str]:
        needles = [x.lower() for x in (query, label) if x]
        found, seen = [], set()
        for m in out_messages:
            hay = ((m.get("text") or "") + " " +
                   " ".join(m.get("urls") or [])).lower()
            if not any(nd in hay for nd in needles):
                continue
            tid = thread_of_msg.get(m["id"])
            if tid and tid not in seen:
                seen.add(tid)
                found.append(tid)
        return found

    # 카테고리별 앱 노드
    apps_by_cat: dict[str, list] = {}
    for n in knowledge.get("nodes", []):
        if n.get("type") == "app":
            apps_by_cat.setdefault(n["category"], []).append({
                "label": n["label"],
                "maker": n.get("maker"),
                "query": n.get("query"),
                "thread_ids": threads_matching(n.get("query") or "", n["label"]),
            })
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


def weigh_knowledge(knowledge: dict, messages: list[dict]) -> list[str]:
    """지식 노드의 크기를 실제 언급량으로 다시 매긴다. 한 번도 안 나온 이름을 돌려준다.

    예전에는 종류마다 값이 고정이었다 — 주제 26, 앱 13, 도구 10. 그래서 관계망에서
    노드 크기가 아무것도 말해 주지 않았다. 차량 운행일지(수십 번 언급)와 한 번
    스치듯 나온 앱이 같은 크기였다.

    이제 원문에서 query·label 이 몇 번 나왔는지 세어 크기를 준다. 사람 노드는
    이미 발언량으로 계산돼 있으므로 건드리지 않는다.
    """
    hay = [
        ((m.get("text") or "") + " " + " ".join(m.get("urls") or [])).lower()
        for m in messages
    ]
    cat_msgs: Counter[str] = Counter(m.get("category") for m in messages if m.get("category"))

    stale = []
    for n in knowledge.get("nodes", []):
        if n["type"] == "person":
            continue
        if n["type"] == "topic":
            # 주제는 그 분류에 실제로 담긴 메시지 수로
            c = cat_msgs.get(n["category"], 0)
            n["value"] = round(8 + min(22, (c ** 0.5) * 1.1), 1)
            continue
        needles = [x.lower() for x in (n.get("query"), n["label"]) if x]
        hits = sum(1 for h in hay if any(nd in h for nd in needles))
        if hits == 0:
            stale.append("%s(%s)" % (n["label"], n["type"]))
        # 1번 언급 → 4.5, 10번 → 9, 50번 → 16 정도. 제곱근으로 눌러 편차를 줄인다
        n["value"] = round(3.5 + min(18, (hits ** 0.5) * 1.8), 1)
    return stale


def enrich_threads(threads: list[dict], messages: list[dict]) -> list[dict]:
    """스레드에 링크와 미디어 개수를 붙인다.

    원문 대신 요약을 발행하기로 하면서 스레드가 화면의 최소 단위가 됐다. 그런데
    요약만으로는 "그래서 뭘 공유했나"를 알 수 없다 — 링크와 파일은 대화의 내용이
    아니라 결과물이므로 그대로 남긴다.
    """
    # 발행본 스레드에는 message_ids 가 없다(build_data 가 뺀다). 메시지 쪽에 붙어
    # 있는 thread_id 로 되짚는다.
    by_thread: dict[str, list[dict]] = {}
    for m in messages:
        tid = m.get("thread_id")
        if tid:
            by_thread.setdefault(tid, []).append(m)

    out = []
    for t in threads:
        links, media = [], 0
        seen = set()
        for m in by_thread.get(t["id"], []):
            for u in m.get("urls") or []:
                if u not in seen:
                    seen.add(u)
                    links.append({
                        "id": m["id"],
                        "url": u,
                        "nickname": m["nickname"],
                        "date": m["date"],
                        "time": m.get("time") or "",
                    })
            if m.get("images") or m.get("file"):
                media += 1
        nt = {k: v for k, v in t.items() if k != "message_ids"}
        if nt.get("report"):
            nt["report"] = place_context_anchors(
                nt["report"], by_thread.get(t["id"], [])
            )
        nt["links"] = links
        nt["media_count"] = media
        out.append(nt)
    return out


def build_media(messages: list[dict]) -> list[dict]:
    """사진·첨부만 따로 발행한다.

    원문 텍스트는 내보내지 않지만 사진과 파일은 그 자체가 공유된 결과물이라
    남긴다. 본문이 없으므로 대화 내용이 새지 않는다.
    """
    out = []
    for m in messages:
        item = None
        if m.get("videos"):
            item = {"kind": "video", "videos": m["videos"],
                    # 포스터가 없으면 화면이 검은 칸을 보여 줄 수밖에 없다.
                    "thumbs": m.get("thumbs") or [],
                    "count": len(m["videos"])}
        elif m.get("images"):
            item = {"kind": "image", "images": m["images"],
                    "thumbs": m.get("thumbs") or m["images"],
                    "count": m.get("image_count") or len(m["images"])}
        elif m.get("file"):
            item = {"kind": "file", "name": m["file"]["name"], "file": m["file"]}
        elif m.get("is_file_share"):
            # 원본을 못 구한 첨부. 목록에서 빼면 "누가 무엇을 올렸는데 지금은 없다"는
            # 사실이 사라져 다시 구해달라고 부탁할 근거도 없어진다. 파일명은 대화
            # 내용이 아니라 결과물의 이름이므로 남긴다.
            name = (m.get("text") or "").replace("파일:", "", 1).strip()
            item = {"kind": "file", "name": name}
        if not item:
            continue
        item.update({
            "id": m["id"], "nickname": m["nickname"],
            "date": m["date"], "time": m["time"],
            "thread_id": m.get("thread_id"), "category": m.get("category"),
        })
        out.append(item)
    return out



def build_data(
    messages: list[dict],
    images: list[dict],
    participants: dict,
    topics: dict,
    knowledge: dict | None = None,
    digest_prose: dict | None = None,
    files: list[dict] | None = None,
) -> dict:
    """수집 데이터를 화면 렌더링용 단일 딕셔너리로 조립한다."""
    # 이미지 메시지 → 다운로드된 로컬 경로 매핑
    image_by_id = {img["image_id"]: img for img in images}
    # 파일 공유 메시지 → 나중에 사람이 모아 넣은 원본 (있을 때만)
    file_by_msg = {f["message_id"]: f for f in (files or [])}

    # 메시지 → 스레드/카테고리 매핑
    msg_thread: dict[str, dict] = {}
    for thread in topics["threads"]:
        for mid in thread["message_ids"]:
            msg_thread[mid] = thread

    downloaded_assets = 0
    downloaded_videos = 0
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

        if m["kind"] in ("image", "video"):
            img = image_by_id.get(m.get("image_id"))
            paths = []
            # 갤러리에 쓸 작은 사진. 원본과 짝을 맞춰 같은 길이로 둔다 — 작은 사진이
            # 없는 자리(이미 가벼운 원본)는 원본 경로를 그대로 넣는다. 길이가 어긋나면
            # 화면이 몇 번째 사진의 것인지 알 수 없게 된다.
            thumbs = []
            if img:
                for asset in img.get("assets", []):
                    lp = asset.get("local_path")
                    if lp:
                        # 원본 경로는 'assets/images/...' → 사이트 기준 상대경로 그대로 사용
                        paths.append(lp.replace("\\", "/"))
                        thumbs.append((asset.get("thumb_path") or lp).replace("\\", "/"))
            # 동영상은 사진 목록에 섞지 않는다 — 섞으면 화면이 <img> 로 그리려
            # 하다 깨진다. 포스터(작은 사진)는 사진과 같은 자리에 둔다.
            if m["kind"] == "video":
                item["videos"] = paths
                item["images"] = []
                item["is_video"] = True
            else:
                item["images"] = paths
            item["thumbs"] = thumbs
            # '유실' 과 '수집 대기' 를 갈라 둔다. 옛 백업에서 온 사진 중에는 그
            # 기기가 원본을 받지 못해 파일이 영영 없는 것이 있다. 그걸 대기로
            # 두면 채워질 리 없는 항목이 목록에 남아 남은 일이 얼마인지 흐려진다.
            lost = bool(img and img.get("status") == "lost")
            item["image_lost"] = lost
            item["image_pending"] = len(paths) == 0 and not lost
            item["image_count"] = (
                m.get("image_count")
                or (img.get("expected_asset_count") if img else None)
                or 1
            )
            # 사진과 동영상을 갈라 센다. 'downloaded_images' 가 동영상까지 세면
            # 화면의 '보관 사진' 숫자가 사진 수와 맞지 않는다.
            if m["kind"] == "video":
                downloaded_videos += len(paths)
            else:
                downloaded_assets += len(paths)

        # 원본을 못 구한 첨부는 예전처럼 이름만 남는다 — 링크는 붙은 것에만 준다
        f = file_by_msg.get(m["id"])
        if f:
            item["file"] = {
                "name": f["filename"],
                "path": f["local_path"],
                "size": f["byte_size"],
            }

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
        # 화면에서 최신순/오래된순을 뒤집으려면 날짜만으로는 부족하다.
        # 같은 날 주제가 여럿이면 시각까지 봐야 순서가 맞는다.
        tmeta["start_time"] = msg_index[ids[0]].get("time", "")
        tmeta["end_time"] = msg_index[ids[-1]].get("time", "")

    # 원문을 발행하지 않으므로 보고서가 원문을 대신해야 한다. 사람이 원문을 읽고
    # 쓴 마크다운을 얹는다. 없는 스레드는 한 줄 요약만 남는다.
    apply_reports(threads_meta, load_reports())
    raw_chars = {
        t["id"]: sum(content_chars(msg_index[m]["text"]) for m in t["message_ids"])
        for t in topics["threads"]
    }
    thin = thin_reports(threads_meta, raw_chars)
    if thin:
        print("[주의] 대화량에 비해 보고서가 얇은 주제 %d개 (앞 5개): %s"
              % (len(thin), ", ".join("%s(%d건 %d자<%d)" % x for x in thin[:5])))

    knowledge = knowledge or {"nodes": [], "edges": [], "node_types": [], "edge_types": []}
    # 관계망 노드 크기를 실제 언급량으로 다시 매긴다
    stale = weigh_knowledge(knowledge, out_messages)
    if stale:
        print("[관계망] 원문에 한 번도 안 나오는 노드 %d개: %s"
              % (len(stale), ", ".join(stale[:12])))
    digests = build_digests(
        out_messages, threads_meta, topics, knowledge, digest_prose or {}
    )

    return {
        "chat_room": topics.get("chat_room", "카카오톡 아카이브"),
        "generated_from": {
            "messages": len(messages),
            "participants": len(participant_stats),
            "downloaded_images": downloaded_assets,
            "downloaded_videos": downloaded_videos,
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
            "downloaded_videos": downloaded_videos,
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
    for name in STATIC_DIRS:
        shutil.copytree(WEB / name, SITE / name)

    # 이미지 복사 (다운로드된 것만 존재)
    if ASSETS_IMAGES.exists():
        dest = SITE / "assets" / "images"
        shutil.copytree(ASSETS_IMAGES, dest)
    # 갤러리용 작은 사진. 빠뜨리면 미리보기에서 갤러리가 통째로 비어 보이는데,
    # 배포본은 Storage 에서 받으므로 로컬에서만 그렇다 — 알아채기 어렵다.
    if ASSETS_THUMBS.exists():
        shutil.copytree(ASSETS_THUMBS, SITE / "assets" / "thumbs")
    if ASSETS_VIDEOS.exists():
        shutil.copytree(ASSETS_VIDEOS, SITE / "assets" / "videos")


PERSON_VALUE_CAP = 300     # 발언이 아무리 많아도 노드가 화면을 잡아먹지 않게


def sync_person_nodes(knowledge: dict, participants: dict, topics: dict) -> list[str]:
    """사람 노드를 참여자 명단과 맞춘다.

    사람 노드는 원래 LLM 이 만들었는데, 그러면 새 참여자가 들어올 때마다 노드가
    빠져 그래프에 구멍이 난다. 사람은 발언량과 분류만 있으면 정해지므로 코드가
    맡는 편이 맞다 — LLM 은 '이 대화가 어느 주제인가' 처럼 코드가 못 하는 것만
    한다. 발언 수가 바뀌면 크기도 같이 고친다.

    반환: 새로 만든 사람 이름들
    """
    counts = {p["nickname"]: p["message_count"] for p in participants["participants"]}
    category_of = {
        mid: t["category"] for t in topics["threads"] for mid in t["message_ids"]
    }

    # 미분류(chat)는 '아직 안 정해졌다'는 뜻이라 대표 분류로 쓰면 안 된다.
    # 분류가 끝나면 제 분류로 옮겨가는데, 그때 사람 노드가 통째로 흔들린다.
    by_person: dict[str, Counter] = defaultdict(Counter)
    for m in _read_jsonl(OUTPUT / "messages.jsonl"):
        category = category_of.get(m["id"])
        if category and category != "chat":
            by_person[m["nickname"]][category] += 1

    nodes = [n for n in knowledge.get("nodes", []) if n["type"] != "person"]
    existing = {n["label"]: n for n in knowledge.get("nodes", []) if n["type"] == "person"}
    added = []

    for nickname, count in counts.items():
        node = existing.get(nickname)
        if node is None:
            dominant = by_person[nickname].most_common(1)
            node = {
                "id": "person:" + nickname,
                "type": "person",
                "label": nickname,
                "category": dominant[0][0] if dominant else "members",
            }
            added.append(nickname)
        node["messages"] = count
        node["value"] = 6 + math.sqrt(min(count, PERSON_VALUE_CAP))
        nodes.append(node)

    knowledge["nodes"] = nodes

    # 노드만 만들고 끝내면 어디에도 안 붙은 점이 그래프에 떠 있다. 사람은 최소한
    # 자기가 가장 많이 말한 주제에는 이어져 있어야 한다.
    # `added` 로 판단하면 안 된다. 노드를 만든 실행에서 엣지 쓰기가 빠지면 다음
    # 실행부터는 '새로 만든 사람' 이 없어 영영 고쳐지지 않는다. 늘 전부 훑는다.
    edges = knowledge.setdefault("edges", [])
    connected = {e["source"] for e in edges} | {e["target"] for e in edges}
    for node in nodes:
        if node["type"] != "person" or node["id"] in connected:
            continue
        edges.append({"source": node["id"], "type": "interested",
                      "target": "topic:" + node["category"]})

    return added


def main() -> None:
    messages = _read_jsonl(OUTPUT / "messages.jsonl")
    images = _read_jsonl(OUTPUT / "images.jsonl")
    participants = _read_json(OUTPUT / "participants.json")
    topics = _read_json(OUTPUT / "topics.json")
    knowledge = _read_json(OUTPUT / "knowledge.json")
    added = sync_person_nodes(knowledge, participants, topics)
    # 노드를 새로 만들지 않았어도 발언 수는 바뀌었을 수 있다. 늘 써서 output 과
    # 화면이 어긋나지 않게 둔다.
    (OUTPUT / "knowledge.json").write_text(
        json.dumps(knowledge, ensure_ascii=False, indent=2), encoding="utf-8")
    if added:
        print("사람 노드 %d명 추가: %s" % (len(added), ", ".join(added)))
    digest_prose = _read_json(OUTPUT / "topic-digests.json")
    # 첨부 원본은 나중에 사람이 모아 넣는다. 없으면 이름만 남는다.
    files_path = OUTPUT / "files.jsonl"
    files = _read_jsonl(files_path) if files_path.exists() else []

    data = build_data(messages, images, participants, topics, knowledge, digest_prose, files)
    # 화면은 원문이 아니라 스레드 요약과 결과물을 쓴다. 배포본과 같은 모양으로 맞춘다.
    data["threads"] = enrich_threads(data["threads"], data["messages"])
    data["media"] = build_media(data["messages"])
    data.pop("messages", None)
    write_site(data)

    t = data["stats"]["totals"]
    print(
        f"site/ 생성 완료 · 메시지 {t['messages']} · 참여자 {t['participants']} · "
        f"다운로드 이미지 {t['downloaded_images']} · 스레드 {len(data['threads'])}"
    )


if __name__ == "__main__":
    main()
