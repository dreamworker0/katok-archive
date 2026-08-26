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
from datetime import date, timedelta
from pathlib import Path

from scripts import interests as interestlib
from scripts import jsonio
from scripts import ontology
from scripts import pii
from scripts import tags as taglib
from scripts.topic_reports import (
    apply_ai_reports,
    apply_reports,
    content_chars,
    load_ai_reports,
    load_reports,
    place_context_anchors,
    structure_gaps,
    thin_reports,
)

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
ASSETS_IMAGES = ROOT / "assets" / "images"
ASSETS_THUMBS = ROOT / "assets" / "thumbs"
ASSETS_VIDEOS = ROOT / "assets" / "videos"
WEB = ROOT / "web"
SITE = ROOT / "site"

STATIC_FILES = ("index.html", "app.js", "text.js", "styles.css", "graph.js",
                "images.js", "favicon.svg")
STATIC_DIRS = ("art",)


# 예전 이름을 그대로 남긴다 — 여덟 모듈과 테스트가 이 이름으로 부른다.
# 실제 구현은 scripts/jsonio.py 에 있다(그쪽 주석에 옮긴 이유가 있다).
_read_jsonl = jsonio.read_jsonl
_read_json = jsonio.read_json


def load_secondary(path: Path | None = None) -> dict:
    """보조 분류(주제 id → 분류 id 목록). 파일이 없으면 빈 표 — 없어도 발행된다."""
    p = path or (OUTPUT / "secondary_categories.json")
    if not p.exists():
        return {}
    return _read_json(p).get("secondary") or {}


def _month(date: str) -> str:
    """'2026-05-11' -> '2026-05'"""
    return date[:7]



# 카톡이 방에 올라온 파일을 붙들어 두는 기간.
#
# 실측 2026-08-20: 서랍의 파일 카드에 '유효기간' 이 찍혀 있고, 그 값이 공유일 + 14일
# 이었다(7건 전부 일치). 그리고 **유효기간 날짜에 닿으면 이미 못 받는다** — 유효기간이
# 그날이던 파일 3개와 하루 지난 1개가 모두 저장에 실패했고, 카톡이 '원본 파일이
# 만료된 일부 파일을 저장할 수 없습니다' 라고 알려 줬다. 그래서 경계는 >= 다.
FILE_RETENTION_DAYS = 14


def file_share_expired(share_date: str, today: date | None = None) -> bool:
    """원본을 못 구한 파일 공유가 **되살릴 수 없는 것**인지.

    '원본 없음' 하나로 뭉뚱그리면 읽는 사람이 '아직 안 올린 것' 으로 읽는다. 사진
    쪽에서 유실과 수집 대기를 이미 갈라 둔 것과 같은 이유다 — 대기라고 쓰면 언젠가
    채워질 것처럼 읽히고, 남은 일이 얼마인지 흐려진다.

    날짜를 못 읽으면 만료라고 하지 않는다. 모르는 것을 '영영 없다' 고 단정하는 쪽이
    더 나쁘다 — 아직 받을 수 있는 것을 포기하게 만든다.
    """
    if not share_date:
        return False
    try:
        shared = date.fromisoformat(str(share_date)[:10])
    except ValueError:
        return False
    return (today or date.today()) >= shared + timedelta(days=FILE_RETENTION_DAYS)


def build_digests(
    out_messages: list[dict],
    threads_meta: list[dict],
    topics: dict,
    knowledge: dict,
    digest_prose: dict,
    node_tags: dict[str, list[str]] | None = None,
) -> dict:
    """카테고리별 지식 문서를 조립한다: 요지 산문(digest_prose) + 파생 리소스
    (주요 앱·공유 링크·활발한 참여자·소속 스레드)."""
    prose = digest_prose.get("digests", {})
    node_tags = node_tags or {}

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

    # 결과물이 '주제인' 주제와 '스쳐 언급된' 주제를 가른다.
    #
    # 원문에 이름이 나오면 다 이어 놓았더니, 153건 중 그 결과물을 실제로 다룬 것은
    # 34건이고 119건은 대화 중에 스친 언급이었다('welfareai 커뮤니티' 11건 중 0건,
    # '팀 업무관리 시스템' 12건 중 1건). 그래서 눌러 보면 목록이 소음이 된다.
    # 좁혀 버리면 결과 0개짜리 버튼이 40개 생기므로(눌러도 빈 화면), 버리지 않고
    # 가른다 — 다룬 주제를 먼저 보여주고 스친 언급은 한 번 더 눌러야 나오게.
    meta_by_id = {t["id"]: t for t in threads_meta}

    def is_subject(tid: str, label: str) -> bool:
        """제목이나 태그가 그 결과물의 이름이면 '다룬 주제'로 본다.

        노드의 `query` 는 쓰지 않는다. 검색어가 '앱스스크립트'·'파이어베이스'
        처럼 일반 도구명인 노드가 많아서, 그것으로 판정하면 앱스스크립트 이야기
        전부가 '팀 업무관리 시스템을 다룬 주제'로 걸린다(실측 1건→11건, 대부분
        엉뚱했다). 이름이 서술형이어서('AI 토론 앱') 못 가려지는 결과물은 억지로
        가리지 않고 '언급'으로 정직하게 표시한다.
        """
        t = meta_by_id.get(tid)
        if not t:
            return False
        key = taglib.fold(label)
        if len(key) < 3:
            return False
        if any(taglib.fold(tg) == key for tg in (t.get("tags") or [])):
            return True
        return key in taglib.fold(t.get("title") or "")

    def tag_linked(node_id: str) -> list[str]:
        """`config/node_tags.json` 이 이 노드와 같다고 적어 둔 태그를 가진 주제들.

        글자로 짐작하는 것이 아니라 **사람이 짝지어 둔 것**이므로 곧바로
        '다룬 주제' 다. 이름이 서술형인 결과물('AI 토론 앱')이 제 주제를 찾는
        유일한 길이고, 원문에 이름이 한 번도 안 나오는 노드도 이 길로 살아난다.
        """
        keys = {taglib.fold(t) for t in (node_tags.get(node_id) or [])}
        if not keys:
            return []
        return [t["id"] for t in threads_meta
                if any(taglib.fold(tg) in keys for tg in (t.get("tags") or []))]

    apps_by_cat: dict[str, list] = {}
    for n in knowledge.get("nodes", []):
        if n.get("type") == "app":
            linked = tag_linked(n["id"])
            seen_linked = set(linked)
            # 표로 이은 것을 앞에 둔다 — 가장 확실한 근거다.
            ids = linked + [tid for tid in threads_matching(n.get("query") or "",
                                                            n["label"])
                            if tid not in seen_linked]
            subject = [tid for tid in ids
                       if tid in seen_linked or is_subject(tid, n["label"])]
            apps_by_cat.setdefault(n["category"], []).append({
                "label": n["label"],
                "maker": n.get("maker"),
                "query": n.get("query"),
                "thread_ids": ids,
                "subject_ids": subject,
                "mention_ids": [tid for tid in ids if tid not in set(subject)],
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
    # 보조 분류로 걸린 주제. 주 분류 목록과 **섞지 않는다** — 메시지 수 합계는
    # 주 분류로만 세야 전체 합이 맞는다(한 주제 = 한 분류가 통계의 전제다).
    also_by_cat: dict[str, list] = {}
    for t in threads_meta:
        threads_by_cat.setdefault(t["category"], []).append(t)
        for cid in t.get("also") or []:
            also_by_cat.setdefault(cid, []).append(t)

    # 요지 산문의 태그는 화면에서 눌러 그 화제의 주제로 가는 입구다. 그런데 그
    # 태그는 사람이 요지를 쓰면서 붙인 말이라, 어느 주제와도 이어지지 않는 조어가
    # 섞인다(실측: '망분리·보안', 'Gemini flash' 등 11개). 눌러서 빈 화면이 나오면
    # 고장으로 보이므로, 이어지지 않는 것은 화면에 내지 않고 여기서 알려 준다.
    tag_keys = {taglib.fold(tg) for t in threads_meta for tg in (t.get("tags") or [])}
    thread_text = " ".join(
        ((t.get("title") or "") + " " + (t.get("summary") or "") + " " +
         (t.get("report") or "")) for t in threads_meta
    ).lower()

    def keeps(word: str) -> bool:
        return taglib.fold(word) in tag_keys or word.lower() in thread_text

    dropped_kw: list[str] = []

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
            "keywords": [k for k in p.get("keywords", []) if keeps(k)],
            "apps": apps_by_cat.get(cid, []),
            "links": links_by_cat.get(cid, []),
            "participants": top_nicks,
            "threads": threads_by_cat.get(cid, []),
            "also_threads": [
                {"id": t["id"], "category": t["category"]}
                for t in also_by_cat.get(cid, [])
            ],
            "message_count": sum(t["count"] for t in threads_by_cat.get(cid, [])),
        }
        dropped_kw += ["%s:%s" % (cid, k) for k in p.get("keywords", []) if not keeps(k)]
    if dropped_kw:
        print("[요지 태그] 어느 주제와도 이어지지 않아 화면에서 뺀 %d개: %s"
              % (len(dropped_kw), ", ".join(dropped_kw)))
    return digests


def weigh_knowledge(knowledge: dict, messages: list[dict]) -> list[str]:
    """지식 노드의 크기와 **시점**을 원문에서 다시 매긴다. 한 번도 안 나온 이름을 돌려준다.

    예전에는 종류마다 값이 고정이었다 — 주제 26, 앱 13, 도구 10. 그래서 관계망에서
    노드 크기가 아무것도 말해 주지 않았다. 차량 운행일지(수십 번 언급)와 한 번
    스치듯 나온 앱이 같은 크기였다.

    이제 원문에서 query·label 이 몇 번 나왔는지 세어 크기를 준다.

    ## 시점을 함께 뽑는 이유

    관계망에는 시간이 없어서 **작년에 한 번 스친 도구와 어제까지 쓰는 도구가 나란히
    떠 있었다.** 실측 2026-08-14: '소라2' 는 2025-10-04 하루에 1회, '슬랙' 은
    2025-12-04 부터 2026-08-12 까지 28회다. 화면에서는 둘이 구별되지 않았다.

    원문을 훑는 이 루프가 이미 있으므로 첫·마지막 날짜는 거의 공짜로 나온다.
    `mentions`(횟수)도 함께 남긴다 — 크기(`value`)는 제곱근으로 눌러 놓아서
    거꾸로 세어 볼 수 없다.

    **엣지에는 시점을 붙이지 않는다.** 근거가 원문에만 있어서, 사람→앱·도구 엣지
    210개 중 154개에만 날짜가 나오고 사람→분류 89개와 앱→도구 등 174개는 근거가
    아예 없다(실측 2026-08-14: 473개 중 33%). 3분의 2가 빈 칸인 값은 화면이 믿고
    쓸 수 없고, 없는 것을 추정해 채우면 `is_subject` 에서 겪은 그 실수가 된다.

    사람 노드는 크기를 건드리지 않는다(발언량으로 이미 계산돼 있다). 시점은
    그 사람이 처음·마지막 말한 날로 붙인다 — '언제부터 방에 있었나' 다.
    """
    hay = [
        ((m.get("text") or "") + " " + " ".join(m.get("urls") or [])).lower()
        for m in messages
    ]
    dates = [m.get("date") or "" for m in messages]
    cat_msgs: Counter[str] = Counter(m.get("category") for m in messages if m.get("category"))

    def span(node: dict, idx: list[int]) -> None:
        """찾은 자리들의 첫·마지막 날짜를 붙인다. 못 찾았으면 아무것도 안 붙인다.

        빈 문자열을 넣지 않는 것이 중요하다 — 화면이 '날짜가 있다' 고 믿고 빈
        기간을 그리게 된다. 없으면 필드 자체가 없어야 한다.
        """
        days = sorted(d for d in (dates[i] for i in idx) if d)
        if days:
            node["first_seen"], node["last_seen"] = days[0], days[-1]
        else:
            node.pop("first_seen", None)
            node.pop("last_seen", None)

    # 사람은 발언 날짜로. 원문을 뒤질 필요가 없다.
    said_on: dict[str, list[int]] = defaultdict(list)
    for i, m in enumerate(messages):
        said_on[m.get("nickname") or ""].append(i)
    cat_on: dict[str, list[int]] = defaultdict(list)
    for i, m in enumerate(messages):
        if m.get("category"):
            cat_on[m["category"]].append(i)

    stale = []
    for n in knowledge.get("nodes", []):
        if n["type"] == "person":
            span(n, said_on.get(n["label"], []))
            continue
        if n["type"] == "topic":
            # 주제는 그 분류에 실제로 담긴 메시지 수로
            c = cat_msgs.get(n["category"], 0)
            n["value"] = round(8 + min(22, (c ** 0.5) * 1.1), 1)
            span(n, cat_on.get(n["category"], []))
            continue
        needles = [x.lower() for x in (n.get("query"), n["label"]) if x]
        idx = [i for i, h in enumerate(hay) if any(nd in h for nd in needles)]
        if not idx:
            stale.append("%s(%s)" % (n["label"], n["type"]))
        n["mentions"] = len(idx)
        span(n, idx)
        # 1번 언급 → 4.5, 10번 → 9, 50번 → 16 정도. 제곱근으로 눌러 편차를 줄인다
        n["value"] = round(3.5 + min(18, (len(idx) ** 0.5) * 1.8), 1)
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
            # 만료 여부를 함께 보낸다. build_media 는 필드를 골라 담으므로 여기서
            # 빠뜨리면 화면은 '만료' 와 '수집 대기' 를 구별할 수 없다.
            item = {"kind": "file", "name": name,
                    "file_expired": bool(m.get("file_expired"))}
        if not item:
            continue
        item.update({
            "id": m["id"], "nickname": m["nickname"],
            "date": m["date"], "time": m["time"],
            "thread_id": m.get("thread_id"), "category": m.get("category"),
        })
        out.append(item)
    return out



def hide_pii_media(media: list[dict], hidden: set[str]) -> list[dict]:
    """개인정보가 찍힌 사진을 발행본에서 빼고 '가려진 자리'만 남긴다.

    경로만 지우고 끝내면 갤러리에서 그 칸이 조용히 사라진다. 그러면 "여기 사진이
    있었는데 왜 없지" 를 아무도 알 수 없고, 고장과 구분되지 않는다. 몇 장이 가려졌
    는지 세어 두어 화면이 자리표를 그릴 수 있게 한다.

    작은 사진(thumbs)도 함께 뺀다 — 같은 그림을 줄인 것이라 글자가 그대로 남는다.

    `kind` 를 보지 않고 `images` 가 있는지만 본다. 미디어 목록과 '내 글' 목록이
    모양은 다르지만 사진을 담는 필드는 같아서, 한 함수로 둘 다 다룰 수 있다.
    본인 글에서도 같은 처리가 필요하다 — 감춘 사진은 올라가지도 않으므로, 그냥
    두면 본인 화면에서 404 로 깨져 보이고 왜 그런지 알 수 없다.
    """
    out = []
    for item in media:
        # 동영상은 OCR 대상이 아니다(프레임을 뜯어야 한다). 지금은 그대로 둔다.
        srcs = item.get("images") or []
        if not srcs:
            out.append(item)
            continue
        thumbs = item.get("thumbs") or srcs
        keep_src, keep_thumb, dropped = [], [], 0
        for i, src in enumerate(srcs):
            if src in hidden:
                dropped += 1
                continue
            keep_src.append(src)
            keep_thumb.append(thumbs[i] if i < len(thumbs) else src)
        if not dropped:
            out.append(item)
            continue
        ni = dict(item)
        ni["images"], ni["thumbs"] = keep_src, keep_thumb
        ni["pii_hidden"] = dropped
        out.append(ni)
    return out


def build_data(
    messages: list[dict],
    images: list[dict],
    participants: dict,
    topics: dict,
    knowledge: dict | None = None,
    digest_prose: dict | None = None,
    files: list[dict] | None = None,
    secondary: dict | None = None,
    hide_interests: set[str] | None = None,
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
        elif m["kind"] == "file":
            # 못 구한 이유를 갈라 둔다. 만료는 기다려도 오지 않는다 — 카톡에서는
            # 사라졌고, 가지고 있는 사람이 보내 주는 길만 남는다.
            item["file_expired"] = file_share_expired(m.get("date"))

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

    # 사람 보고서 옆에 기계가 쓴 검증 주석을 얹는다. 없으면 없는 대로 둔다 —
    # 전체 주제에 다 있어야 하는 글이 아니다.
    ai_n = apply_ai_reports(threads_meta, load_ai_reports())
    if ai_n:
        print("[AI보고서] %d개 주제에 얹었습니다" % ai_n)

    # 태그 표기를 통일해 `tags` 로 얹는다(보고서 원문은 손대지 않는다).
    taglib.attach_tags(threads_meta, participants)
    # 제목이 곧 그 화제인데 태그에 빠진 것을 채운다 — 관계망에 이미 이름이 있는
    # 앱·도구를 어휘로 쓴다. 태그로 찾을 때 그 주제가 새지 않게 하는 몫이다.
    known_labels = [
        n["label"] for n in (knowledge or {}).get("nodes", [])
        if n.get("type") in ("app", "tool") and n.get("label")
    ]
    filled = taglib.backfill_from_titles(threads_meta, known_labels)
    if filled:
        print("[태그] 제목에 있는데 빠졌던 태그 %d건 채움 (앞 5개: %s)"
              % (len(filled), ", ".join("%s←%s" % f for f in filled[:5])))
    # 지명·조직 이름은 태그 구름에서 뺀다(검색으로는 그대로 찾힌다). 뺄 목록은
    # 사람이 적은 표를 따르고, 표에 없는 후보만 알린다 — 기계가 정하면 이 방의
    # 주제인 '장애인복지관'·'거주시설' 까지 사라진다.
    places, not_places = taglib.load_places()
    cands = taglib.place_candidates(threads_meta, places, not_places)
    if cands:
        print("[태그] 지명·조직 이름 후보 %d개 — config/tag_places.json 에 넣을지 보세요 "
              "(앞 5개: %s)" % (len(cands), ", ".join(t for t, _ in cands[:5])))
    # 부모를 못 얻은 고립 태그를 **승격 전에** 센다. 승격한 뒤에는 무엇이 고립이었는지
    # 알 수 없다. 지명은 빼고 본다 — 그것은 tag_places.json 이 맡을 일이다.
    broader = taglib.load_broader()
    short_parents = taglib.load_short_parents()
    orphans = taglib.broader_candidates(threads_meta, broader, participants, places,
                                        short_parents=short_parents)
    # 좁은 태그에 넓은 태그를 덧붙인다 — '온톨로지 모델링' 주제가 '온톨로지'로도
    # 찾히게 하는 몫이다. 제목에서 채운 태그도 승격 대상이 되도록 뒤에 둔다.
    rolled = taglib.rollup_parent_tags(threads_meta, participants, broader=broader,
                                       short_parents=short_parents)
    if rolled:
        print("[태그] 넓은 태그 %d건 승격 (앞 5개: %s)"
              % (len(rolled), ", ".join("%s←%s" % r for r in rolled[:5])))
    if orphans:
        print("[태그] 부모도 없고 한 번만 쓰인 태그 %d개 — 검색 말고는 입구가 없습니다. "
              "config/tag_broader.json 에 넣을지 보세요 (앞 8개: %s)"
              % (len(orphans), ", ".join(t for t, _ in orphans[:8])))
    # 보조 분류 — 한 주제를 여러 분류에서 찾게 하는 곁길. 주 분류는 그대로 하나다.
    cat_ids = {c["id"] for c in topics["categories"]}
    for tmeta in threads_meta:
        also = [
            cid for cid in ((secondary or {}).get(tmeta["id"]) or [])
            if cid in cat_ids and cid != tmeta["category"]
        ]
        if also:
            tmeta["also"] = also

    raw_chars = {
        t["id"]: sum(content_chars(msg_index[m]["text"]) for m in t["message_ids"])
        for t in topics["threads"]
    }
    thin = thin_reports(threads_meta, raw_chars)
    if thin:
        print("[주의] 대화량에 비해 보고서가 얇은 주제 %d개 (앞 5개): %s"
              % (len(thin), ", ".join("%s(%d건 %d자<%d)" % x for x in thin[:5])))
    # 길게만 쓴 한 덩어리 산문을 잡는다. 분량 검사로는 안 걸리는 종류의 문제다.
    # 자료(사진·첨부·링크) 수를 함께 넘겨, 자료가 있는데 본문이 그 자리를 안 짚은
    # 보고서도 걸리게 한다 — 그것이 '자료가 하단에만 있어 읽기 불편한' 꼴이다.
    #
    # 자리표가 본문에 없어도 발행할 때 `place_context_anchors` 가 인용을 보고 일부를
    # 자동으로 끼운다. 그래서 검사도 **자동으로 끼운 뒤의 본문**을 봐야 한다 —
    # 원본만 보면 이미 잘 붙는 주제까지 위반으로 세어(실측 231개 vs 실제 140개)
    # 숫자가 겁만 주고 쓸모가 없어진다.
    asset_count: Counter[str] = Counter()
    msgs_by_thread: dict[str, list[dict]] = defaultdict(list)
    for m in out_messages:
        tid = m.get("thread_id")
        if not tid:
            continue
        msgs_by_thread[tid].append(m)
        if m.get("kind") in ("image", "file") or m.get("is_file_share"):
            asset_count[tid] += 1
        asset_count[tid] += len(m.get("urls") or [])
    gaps = structure_gaps([
        {**t,
         "asset_count": asset_count.get(t["id"], 0),
         "report": place_context_anchors(t.get("report") or "",
                                         msgs_by_thread.get(t["id"], []))}
        for t in threads_meta
    ])
    if gaps:
        print("[주의] 구조 규칙을 어긴 보고서 %d개 — 고치려면 "
              "`python -m scripts.classify_unsorted --rewrite-unstructured N` "
              "(앞 5개: %s)"
              % (len(gaps), ", ".join("%s(%d건 %s없음)" % g for g in gaps[:5])))

    knowledge = knowledge or {"nodes": [], "edges": []}
    # 화면의 걸러내기 단추와 노드 패널이 종류 이름을 이 표에서 읽는다. 원장이 없는
    # 첫 실행에도 표는 있어야 하므로 코드(scripts/ontology.py)에서 채운다.
    ontology.sync_types(knowledge)
    # 관계망 노드 크기를 실제 언급량으로 다시 매긴다
    stale = weigh_knowledge(knowledge, out_messages)
    if stale:
        print("[관계망] 원문에 한 번도 안 나오는 노드 %d개: %s"
              % (len(stale), ", ".join(stale[:12])))
    # 관계망 노드와 태그를 짝지어 둔 표. 없으면 예전처럼 이름 글자로만 잇는다.
    node_tags = ontology.load_node_tags()
    node_cands = ontology.node_tag_candidates(
        knowledge.get("nodes", []), threads_meta, node_tags,
        ontology.load_settled_nodes())
    if node_cands:
        print("[관계망] 이름으로 주제를 못 찾는 노드 %d개 — config/node_tags.json 에 "
              "짝지어 주세요 (앞 4개: %s)"
              % (len(node_cands),
                 "; ".join("%s←%s" % (nid, "|".join(c)) for nid, _, c in node_cands[:4])))
    digests = build_digests(
        out_messages, threads_meta, topics, knowledge, digest_prose or {}, node_tags
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
        "tag_index": taglib.build_tag_index(threads_meta, participants,
                                            places=places),
        "interests": interestlib.build_interests(
            threads_meta, topics["categories"], hide_interests,
            taglib.person_names(participants),
            # 분류 12개로 아무것도 안 나온 사람은 상위 묶음으로 한 번 더 본다.
            ontology.group_of, ontology.group_label,
            ontology.PROVISIONAL_CATEGORIES,
        ),
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


def write_site(data: dict, dest: Path | None = None) -> None:
    """미리보기 사이트를 만든다. `dest` 를 주면 그곳에 쓴다.

    `dest` 를 받는 이유: 이 함수는 **대상 폴더를 통째로 지우고** 다시 만든다.
    테스트가 인자 없이 부르면 사람이 보고 있던 진짜 `site/` 가 사라진다 —
    하루에 세 번 물렸다. 테스트는 임시 폴더를 준다.
    """
    site = dest or SITE
    if site.exists():
        shutil.rmtree(site)
    site.mkdir(parents=True)

    # data.js
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    (site / "data.js").write_text(
        "window.ARCHIVE = " + payload + ";\n", encoding="utf-8"
    )

    # 정적 파일 복사
    for name in STATIC_FILES:
        shutil.copyfile(WEB / name, site / name)
    for name in STATIC_DIRS:
        shutil.copytree(WEB / name, site / name)

    # 이미지 복사 (다운로드된 것만 존재)
    if ASSETS_IMAGES.exists():
        shutil.copytree(ASSETS_IMAGES, site / "assets" / "images")
    # 갤러리용 작은 사진. 빠뜨리면 미리보기에서 갤러리가 통째로 비어 보이는데,
    # 배포본은 Storage 에서 받으므로 로컬에서만 그렇다 — 알아채기 어렵다.
    if ASSETS_THUMBS.exists():
        shutil.copytree(ASSETS_THUMBS, site / "assets" / "thumbs")
    if ASSETS_VIDEOS.exists():
        shutil.copytree(ASSETS_VIDEOS, site / "assets" / "videos")


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
    # 종류·관계 표를 코드(scripts/ontology.py)로 맞추고, 모양이 어긋난 엣지를 고친다.
    # 사람 노드 동기화 **뒤에** 해야 한다 — 방금 만든 person→topic 엣지도 검사
    # 대상이고, 어긋난 옛 엣지가 그것과 겹치는지 봐야 한다.
    ontology.log(ontology.apply(knowledge))
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

    data = build_data(messages, images, participants, topics, knowledge, digest_prose,
                      files, load_secondary())
    # 화면은 원문이 아니라 스레드 요약과 결과물을 쓴다. 배포본과 같은 모양으로 맞춘다.
    data["threads"] = enrich_threads(data["threads"], data["messages"])
    # 미리보기도 배포본과 같은 정책으로 감춘다 — 다르면 미리보기로 확인한 것이
    # 배포될 모습이 아니게 된다. (판정 파일이 없으면 아무것도 감추지 않는다)
    from scripts import scan_image_pii
    data["media"] = hide_pii_media(build_media(data["messages"]),
                                   scan_image_pii.hidden_paths())
    hidden_shots = sum(m.get("pii_hidden") or 0 for m in data["media"])
    if hidden_shots:
        print("개인정보가 찍힌 사진 %d장 감춤" % hidden_shots)
    data.pop("messages", None)
    # 개인정보를 가린다. 원문(messages)을 뺀 **뒤에** 훑는 것이 중요하다 — 미리보기
    # 에는 본인 글 구분이 없으므로 남는 것은 모두 '모두가 보는 것' 이고, 배포본과
    # 같은 정책이 적용돼야 미리보기로 확인한 것이 곧 배포될 모습이 된다.
    data, hits = pii.mask_tree(data)
    if hits:
        print("개인정보 %d건 가림 (%s)"
              % (len([h for h in hits if h.grade == "certain"]), pii.summarize(hits)))
    write_site(data)

    t = data["stats"]["totals"]
    print(
        f"site/ 생성 완료 · 메시지 {t['messages']} · 참여자 {t['participants']} · "
        f"다운로드 이미지 {t['downloaded_images']} · 스레드 {len(data['threads'])}"
    )


if __name__ == "__main__":
    main()
