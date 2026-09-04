# -*- coding: utf-8 -*-
"""관계망 엣지에 **근거**를 붙인다 — 왜 그렇게 아는지 원문으로 되짚게.

왜 이 파일이 있나
    이 아카이브의 다른 층은 전부 원 출처로 되짚을 수 있게 만들었다. AI 보고서는
    '원 출처를 연 것만 단정' 하고(`topic_reports.AI_REPORT_RULES`), 보고서의
    사진·링크는 message id 로 자리를 가리키고(`sanitize_anchors`), 요지 태그는
    어느 주제와도 이어지지 않으면 화면에 내지 않는다(`build_digests`).

    **관계망만 예외였다.** 실측 2026-09-04: 엣지 560개에 근거 0. 화면에서 엣지를
    눌러도 왜 그렇게 아는지 갈 곳이 없고, 뜻이 틀린 엣지 — 스쳐 언급된 도구를
    `uses` 로 적은 것 — 를 걷어낼 방법도 없다. `ontology.apply` 는 **모양**이
    어긋난 것만 잡는다.

LLM 을 부르지 않는다
    근거는 원문에서 **찾는** 것이다. 모델에게 "이 관계의 근거를 찾아라" 고 물으면
    그럴듯한 message id 를 지어낼 수 있고, 그것은 근거의 반대다. 이 스크립트는
    계산만 한다.

무엇을 고치고 무엇을 안 고치는가
    고침    output/knowledge.json 의 엣지에 `evidence`·`by` 를 **덧붙인다**
    안 고침 엣지·노드를 지우거나 관계 이름을 바꾸는 일. 노드의 값·시점.
            보고서·원장(topics.json)·태그

    근거를 못 찾은 엣지도 **지우지 않는다.** 누적된 원장이고 그날 판단으로 과거를
    지우면 되돌릴 수 없다(`classify_unsorted.merge_graph` 와 같은 판단). 목록만
    내고 사람이 본다.

모양마다 규칙이 다르다 — 그리고 규칙 이름을 함께 남긴다
    어느 규칙이 찾은 근거인지 모르면 나중에 규칙을 고칠 때 무엇이 흔들리는지 알 수
    없다. 그래서 `by` 에 규칙 이름을 적는다.

      spoke-in     person → topic       그 사람이 그 분류에서 한 말
      named-it     person → app/tool    그 사람의 말 중 그 이름이 나온 것
      named-in     app/tool → topic     그 분류의 말 중 그 이름이 나온 것
      named-both   app/tool → app/tool  두 이름이 한 메시지에서 만난 것

    노드가 '나온 자리' 는 이름으로 찾은 것에 `config/node_tags.json` 으로 짝지은
    태그를 가진 주제의 말을 **더한** 것이다. 뒤쪽이 없으면 이름이 서술형인 앱은
    제 자리를 찾지 못한다. 그 길로 살아난 근거는 `by` 에 `+tagged` 가 붙는다.

짧은 이름은 뒷받침을 요구한다
    `query` 가 두 글자인 노드가 17개다 — `상담`·`게임`·`토론`·`엑셀` 같은 일반어다.
    실측해 보니 걸리는 수는 적었지만(`상담` 10회) **틀린 근거는 없는 근거보다
    나쁘다.** '상담' 이 든 아무 말이나 상담 도구의 근거로 서면, 그 링크를 눌러 본
    사람이 아카이브를 믿지 못하게 된다.

    그렇다고 세 글자 미만을 통째로 막으면 `슬랙`(30회)·`노션`·`애저`·`버셀` 처럼
    진짜 이름까지 잃는다. 그래서 **짧은 이름은 그 메시지가 속한 주제가 그 노드와
    이어질 때만** 근거로 인정한다(`linked_threads`).

사용
    python -m scripts.graph_evidence --report      # 모양별 표만 (원장에 안 쓴다)
    python -m scripts.graph_evidence --apply       # 원장에 덧붙인다 (백업 먼저)
    python -m scripts.graph_evidence --gaps        # 근거 못 찾은 엣지 문서
"""
from __future__ import annotations

import argparse
import collections
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

from scripts import jsonio
from scripts import ontology
from scripts import tags as taglib
from scripts.tag_surgery import backup_dir, shown
from scripts.topic_reports import content_chars, load_reports

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
KNOWLEDGE = OUT / "knowledge.json"
TOPICS = OUT / "topics.json"
MESSAGES = OUT / "messages.jsonl"
PARTICIPANTS = OUT / "participants.json"

# 엣지 하나에 담을 근거 수. 어느 셋인가는 판단이므로 규칙으로 정해 둔다 —
# 가장 이른 것 · 가장 늦은 것 · 가장 긴 것. 처음과 끝은 기간을 말해 주고, 가장 긴
# 말은 내용을 말해 준다. 다 담으면 2,758건이 되어 원장이 근거 목록이 된다.
EVIDENCE_MAX = 3

# 이 길이 미만인 이름은 뒷받침 없이는 근거가 되지 못한다(위 docstring).
# 규칙은 ontology 에 있다 — 근거 찾기와 분류 확인이 같은 잣대를 써야 한다.
SHORT_NAME_CHARS = ontology.SHORT_NAME_CHARS
# 보고서 근거는 주제 단위라 한둘이면 족하다 — 같은 말을 여러 편에서 확인시킬 일이 없다.
EVIDENCE_REPORTS = 2


def message_context() -> dict:
    """근거를 찾는 데 필요한 것만 원문에서 뽑아 둔다.

    `hay`(본문+URL 을 소문자로)는 `build_site.weigh_knowledge` 가 노드 크기를 잴 때
    쓰는 것과 **같은 꼴**이다. 다른 방법으로 맞추면 크기와 근거가 서로 다른 것을
    세게 된다.
    """
    msgs = jsonio.read_jsonl(MESSAGES)
    topics = jsonio.read_json(TOPICS)
    thread_of = {mid: t["id"] for t in topics["threads"] for mid in t["message_ids"]}
    cat_of = {t["id"]: t["category"] for t in topics["threads"]}

    reports = load_reports()
    threads = [dict(t, keywords=(reports.get(t["id"]) or {}).get("keywords") or [],
                    title=(reports.get(t["id"]) or {}).get("title") or t.get("title") or "")
               for t in topics["threads"]]
    parts = jsonio.read_json(PARTICIPANTS) if PARTICIPANTS.is_file() else {}
    taglib.attach_tags(threads, parts)
    taglib.rollup_parent_tags(threads, parts)

    return {
        "ids": [m["id"] for m in msgs],
        "hay": [((m.get("text") or "") + " " + " ".join(m.get("urls") or [])).lower()
                for m in msgs],
        "dates": [m.get("date") or "" for m in msgs],
        "lens": [content_chars(m.get("text") or "") for m in msgs],
        "who": [m.get("nickname") or "" for m in msgs],
        "thread": [thread_of.get(m["id"]) for m in msgs],
        "cat": [cat_of.get(thread_of.get(m["id"])) for m in msgs],
        "threads": threads,
        "node_tags": ontology.load_node_tags(),
        "report_head": {tid: squeeze(" ".join([
            r.get("title") or "", r.get("summary") or "",
            " ".join(r.get("keywords") or [])])) for tid, r in reports.items()},
        "report_paras": {tid: [squeeze(x) for x in (r.get("report") or "").split("\n\n")
                               if x.strip()] for tid, r in reports.items()},
        "report_cat": dict(cat_of),
        "cat_label": {c["id"]: c.get("label") or c["id"]
                      for c in topics.get("categories", [])},
    }


def linked_threads(node: dict, ctx: dict) -> set[str]:
    """이 노드를 **다룬** 주제들. `build_digests` 의 두 판정을 같은 뜻으로 쓴다.

    · `config/node_tags.json` 이 짝지어 둔 태그를 가진 주제 (사람이 적은 것)
    · 태그가 그 노드의 이름과 **똑같은** 주제
    · 제목에 그 이름이 든 주제 — 이 길만 세 글자 이상을 요구한다

    길이 방벽이 제목 쪽에만 있는 이유: 태그는 같은지 아닌지를 보므로 '상담' 태그와
    '상담' 노드가 같다는 판정이 짧아도 틀리지 않는다. 제목은 부분일치라서 '상담'
    두 글자가 '상담일지'·'상담실 예약' 을 다 끌어온다.

    노드의 `query` 는 쓰지 않는다 — 일반 도구명인 노드가 많아서 그것으로 판정하면
    앱스스크립트 이야기 전부가 특정 결과물을 '다룬 주제' 로 걸린다(`is_subject`
    docstring 의 실측: 1건 → 11건, 대부분 엉뚱했다).
    """
    keys = {taglib.fold(t) for t in (ctx["node_tags"].get(node["id"]) or [])}
    label = taglib.fold(node.get("label") or "")
    out = set()
    for t in ctx["threads"]:
        tags = {taglib.fold(x) for x in (t.get("tags") or [])}
        if ((keys and tags & keys)
                or (label and label in tags)
                or (len(label) >= SHORT_NAME_CHARS
                    and label in taglib.fold(t.get("title") or ""))):
            out.add(t["id"])
    return out


def mentions_of(node: dict, ctx: dict) -> list[int]:
    """그 노드의 이름이 나온 메시지 자리들.

    짧은 이름(일반어)은 그 메시지의 주제가 그 노드와 이어질 때만 센다.

    **짧아도 그것이 이름의 전부면 이름이다.** 방벽은 '상담'·'게임'·'토론' 처럼
    긴 이름에서 잘라 온 조각을 막으려는 것이다 — '상담 실시간 질문 안내 도구' 의
    query 가 '상담' 이면 상담 이야기 전부가 그 도구 언급이 된다. 그런데 길이만
    보면 두 글자가 통째로 이름인 것들이 같은 그물에 걸린다(노션·슬랙 같은 것).
    실측 2026-09-05: '슬랙' 30건을 찾아 놓고 버리고 있었다.
    """
    names = ontology.node_names(node)
    if not names:
        return []
    long_names = ontology.findable_names(node)
    short_names = [n for n in names if n not in long_names]
    backing = linked_threads(node, ctx) if short_names else set()

    out = []
    for i, h in enumerate(ctx["hay"]):
        if any(n in h for n in long_names):
            out.append(i)
        elif short_names and ctx["thread"][i] in backing and any(n in h for n in short_names):
            out.append(i)
    return out


def tagged_hits(node: dict, ctx: dict) -> list[int]:
    """`node_tags` 로 짝지은 주제의 메시지 자리들 — 이름으로 못 찾을 때의 두 번째 길."""
    keys = {taglib.fold(t) for t in (ctx["node_tags"].get(node["id"]) or [])}
    if not keys:
        return []
    tids = {t["id"] for t in ctx["threads"]
            if any(taglib.fold(x) in keys for x in (t.get("tags") or []))}
    return [i for i, tid in enumerate(ctx["thread"]) if tid in tids]


def squeeze(text: str) -> str:
    """띄어쓰기를 지운 소문자. 보고서를 볼 때만 쓴다.

    보고서는 사람이 다듬어 쓴 글이라 같은 것을 '차량 운행일지'·'차량운행일지' 로
    달리 적는다. 원문(카톡)에는 이 잣대를 쓰지 않는다 — 거기서는 띄어쓰기를 지우면
    낱말 경계가 무너져 엉뚱한 자리가 걸린다.
    """
    return re.sub(r"\s+", "", text.lower())


def node_marks(node: dict) -> list[str]:
    """보고서에서 이 노드를 가리키는 말들(띄어쓰기 없는 소문자)."""
    return [squeeze(n) for n in ontology.findable_names(node)]


def from_reports(rule: str, src: dict, dst: dict, ctx: dict) -> list[str]:
    """원문에서 못 찾은 관계를 **보고서**에서 찾는다. 자리는 주제 id 다.

    왜 보고서인가: 이 아카이브에서 '무엇으로 만들었다' 는 보고서가 가장 또렷하게
    적는다. 원문에서는 앱 이야기와 도구 이야기가 이어지는 **다른** 메시지로 오가서,
    한 메시지 안만 보는 규칙은 그 관계를 볼 수 없다 — 실측 2026-09-05: 근거 없는
    엣지 153개 가운데 84개가 그 꼴이었다.

    왜 message id 가 아닌가: 두 이름이 한 메시지에 없으니 가리킬 한 줄이 없다.
    아무 줄이나 고르면 거짓 자리다. 보고서가 붙은 자리는 **주제**이고, 발행본의
    근거는 어차피 주제 id 다(`build_site.publish_edges`).

    ## 어디까지를 '함께 나왔다' 로 보나

    보고서 한 편 전체를 그릇으로 삼으면 안 된다. 긴 보고서에는 여러 이야기가 있고,
    한 사람과 한 도구가 **서로 다른 문단**에서 따로 나올 수 있다. 실측 2026-09-05:
    보고서 전체로 재면 57개가 붙는데, 읽어 보니 사람 쪽에 그런 것이 섞여 있었다.

      사람 → 물건   **한 문단** 안에서 만나야 한다. 보고서에는 여러 사람이 나오고,
                    '누가 무엇을 했다' 는 문단 단위로 적힌다.
      물건 → 물건   한 문단이거나, **한쪽이 제목·요약에 있으면** 된다. 보고서는
                    주제가 하나다 — 그 결과물이 제목에 있으면 본문의 도구는 그
                    이야기다. (제목에 없는 것은 떨어진다: 다른 주제의 보고서에
                    스쳐 나온 앱과 도구를 이어 붙이지 않는다.)
      물건 → 분류   그 분류의 보고서가 이름을 적었으면 된다.
      사람 → 분류   보지 않는다 — 원문으로 98%가 걸린다.
    """
    if rule == "spoke-in":
        return []
    marks_dst = node_marks(dst)
    hits = []
    for tid, paras in ctx["report_paras"].items():
        head = ctx["report_head"].get(tid, "")
        if rule == "named-in":
            if ctx["report_cat"].get(tid) != dst.get("category"):
                continue
            if any(m in head or any(m in p for p in paras) for m in node_marks(src)):
                hits.append(tid)
            continue
        if rule == "named-it":
            who = squeeze(src.get("label") or "")
            if who and any(who in p and any(m in p for m in marks_dst)
                           for p in [head] + paras):
                hits.append(tid)
            continue
        marks_src = node_marks(src)
        together = any(any(a in p for a in marks_src) and any(b in p for b in marks_dst)
                       for p in [head] + paras)
        subject = any(m in head for m in marks_src + marks_dst)
        named_both = (any(any(a in p for a in marks_src) for p in [head] + paras)
                      and any(any(b in p for b in marks_dst) for p in [head] + paras))
        if together or (subject and named_both):
            hits.append(tid)
    hits.sort()
    # 처음과 마지막 — `pick` 이 메시지에서 하는 것과 같은 뜻이다.
    return hits if len(hits) <= EVIDENCE_REPORTS else [hits[0], hits[-1]]


def pick(idx: list[int], ctx: dict, cap: int = EVIDENCE_MAX) -> list[int]:
    """가장 이른 것 · 가장 늦은 것 · 가장 긴 것. 원장 순서로 돌려준다.

    겹치면 채워지는 만큼만 담는다 — 억지로 셋을 만들려고 아무 것이나 넣지 않는다.
    """
    if not idx:
        return []
    by_date = sorted(idx, key=lambda i: (ctx["dates"][i], i))
    chosen = {by_date[0], by_date[-1], max(idx, key=lambda i: (ctx["lens"][i], -i))}
    return sorted(chosen)[:cap]


def rule_for(src_type: str, dst_type: str) -> str:
    if src_type == "person":
        return "spoke-in" if dst_type == "topic" else "named-it"
    return "named-in" if dst_type == "topic" else "named-both"


def find_evidence(edge: dict, nodes: dict, ctx: dict,
                  cache: dict) -> tuple[list[str], str]:
    """(근거 message id 들, 규칙 이름). 못 찾으면 ([], 규칙 이름).

    한 노드가 '나온 자리' 는 두 길의 합이다 — 이름이 나온 메시지(`mentions_of`)와
    사람이 짝지어 둔 태그를 가진 주제의 메시지(`tagged_hits`). 뒤쪽은 이름이
    서술형인 앱이 제 자리를 찾는 유일한 길이다.

    **두 길을 합쳐 놓고 규칙을 걸어야 한다.** 처음에는 규칙이 비었을 때만 태그
    길로 물러섰는데, 그러면 `app uses tool` 에서 출발 앱의 주제 메시지가 **도착
    도구가 나오지 않아도** 근거가 됐다. 그건 관계를 보여 주지 않는 근거다.
    합쳐 두면 '그 앱을 다룬 주제에서 누군가 그 도구를 말한 자리' 가 걸린다 —
    그것은 실제로 그 관계를 보여 준다.
    """
    src, dst = nodes.get(edge.get("source")), nodes.get(edge.get("target"))
    if not src or not dst:
        return [], ""
    rule = rule_for(src["type"], dst["type"])

    def where(n):
        """그 노드가 나온 자리들. 이름으로 찾은 것 + 표로 이은 주제의 말."""
        if n["id"] not in cache:
            by_name = mentions_of(n, ctx)
            extra = [i for i in tagged_hits(n, ctx) if i not in set(by_name)]
            cache[n["id"]] = (sorted(by_name + extra), set(extra))
        return cache[n["id"]]

    tagged_only: set[int] = set()
    if rule == "spoke-in":
        hits = [i for i, w in enumerate(ctx["who"])
                if w == src["label"] and ctx["cat"][i] == dst.get("category")]
    elif rule == "named-it":
        idx, tagged_only = where(dst)
        hits = [i for i in idx if ctx["who"][i] == src["label"]]
    elif rule == "named-in":
        idx, tagged_only = where(src)
        hits = [i for i in idx if ctx["cat"][i] == dst.get("category")]
    else:
        a, ta = where(src)
        b, tb = where(dst)
        other = set(b)
        hits = [i for i in a if i in other]
        tagged_only = ta | tb

    if not hits:
        # 원문에 자리가 없으면 보고서를 본다. 좁은 자리를 먼저 쓰고, 없을 때만.
        tids = from_reports(rule, src, dst, ctx)
        if tids:
            return tids, rule + "+report"
        return [], rule
    chosen = pick(hits, ctx)
    # 표로 이어 살아난 자리가 섞였으면 남긴다 — 어느 판정이었는지 알아야
    # 나중에 규칙을 고칠 때 무엇이 흔들리는지 안다.
    if any(i in tagged_only for i in chosen):
        rule += "+tagged"
    return [ctx["ids"][i] for i in chosen], rule


def survey(knowledge: dict, ctx: dict) -> dict:
    """엣지마다 근거를 찾아 본다. **원장을 고치지 않는다.**"""
    nodes = {n["id"]: n for n in knowledge.get("nodes", [])}
    cache: dict[str, list[int]] = {}
    rows = []
    for e in knowledge.get("edges", []):
        ids, rule = find_evidence(e, nodes, ctx, cache)
        src, dst = nodes.get(e.get("source")), nodes.get(e.get("target"))
        rows.append({
            "edge": e,
            "shape": "%s -%s-> %s" % (
                src["type"] if src else "?", e.get("type"),
                dst["type"] if dst else "?"),
            "evidence": ids,
            "by": rule,
        })
    return {"rows": rows, "nodes": nodes}


def report(rows: list[dict]) -> None:
    shape = collections.Counter(r["shape"] for r in rows)
    found = collections.Counter(r["shape"] for r in rows if r["evidence"])
    by = collections.Counter(r["by"] for r in rows if r["evidence"])
    print("%-34s %5s %11s" % ("엣지 모양", "전체", "근거 찾음"))
    for key in sorted(shape, key=lambda x: -shape[x]):
        print("%-34s %5d %5d(%3.0f%%)"
              % (key, shape[key], found[key], 100 * found[key] / shape[key]))
    total, got = sum(shape.values()), sum(found.values())
    print("%-34s %5d %5d(%3.0f%%)" % ("합", total, got, 100 * got / total))
    print("\n규칙별: %s" % " · ".join("%s %d" % kv for kv in by.most_common()))


def apply_evidence(knowledge: dict, rows: list[dict],
                   day: str) -> tuple[int, Path | None]:
    """찾은 근거를 엣지에 덧붙인다. 여러 번 돌려도 같다.

    근거를 못 찾은 엣지에는 `evidence` 키를 **아예 만들지 않는다.** 빈 배열을 넣으면
    화면이 '근거가 있다' 고 믿고 빈 목록을 그린다 — `weigh_knowledge.span` 이 빈
    날짜를 안 넣는 것과 같은 이유다.

    **바뀐 것이 없으면 원장을 쓰지 않는다** — 백업도 만들지 않는다. 내용이 같아도
    다시 쓰면 파일 시각이 바뀌고, `publish_state` 는 `knowledge.json` 의 시각을
    보고 발행할지 정한다. 밤마다 돌리는 칸에서 그러면 조용한 날에도 발행이 돈다.
    바뀐 것이 없을 때 돌려주는 백업 경로는 None 이다.
    """
    changed = 0
    for r in rows:
        e = r["edge"]
        if r["evidence"]:
            if e.get("evidence") != r["evidence"] or e.get("by") != r["by"]:
                changed += 1
            e["evidence"] = r["evidence"]
            e["by"] = r["by"]
        else:
            if "evidence" in e or "by" in e:
                changed += 1
            e.pop("evidence", None)
            e.pop("by", None)
    if not changed:
        return 0, None
    backup = backup_dir("graph", day)
    if KNOWLEDGE.is_file():
        shutil.copy2(KNOWLEDGE, backup / KNOWLEDGE.name)
    jsonio.write_json(KNOWLEDGE, knowledge)
    return changed, backup


def gap_reason(edge: dict, nodes: dict, ctx: dict, cache: dict) -> str:
    """왜 근거를 못 찾았나.

    이유가 정확해야 한다. 사람이 훑고 무엇을 할지 정하는 문서이고, '이름이 서술형'
    과 '한 메시지에서 만나지 않는다' 는 **다른 일을 하라는 말**이다 — 앞의 것은
    `node_tags` 표를 채우면 풀리고, 뒤의 것은 그 관계가 정말 성립하는지 사람이
    원문을 봐야 하는 일이다.
    """
    src, dst = nodes.get(edge.get("source")), nodes.get(edge.get("target"))
    if not src or not dst:
        return "엣지가 없는 노드를 가리킨다"

    for n in (src, dst):
        if n["type"] not in ("app", "tool"):
            continue
        if n["id"] not in cache:
            by_name = mentions_of(n, ctx)
            extra = [i for i in tagged_hits(n, ctx) if i not in set(by_name)]
            cache[n["id"]] = (sorted(by_name + extra), set(extra))
        if not cache[n["id"]][0]:
            return "원문에 이름이 한 번도 안 나오고 표로도 이어지지 않는다 (%s)" % n["label"]

    rule = rule_for(src["type"], dst["type"])
    if rule == "named-both":
        return "두 이름이 한 메시지에서 만나지 않는다"
    if rule == "named-it":
        return "그 사람의 말에는 그 이름이 안 나온다"
    if rule == "named-in":
        return "그 분류의 말에는 그 이름이 안 나온다"
    return "그 사람이 그 분류에서 한 말이 없다"


def write_gaps(rows: list[dict], nodes: dict, ctx: dict, day: str) -> Path:
    """근거를 못 찾은 엣지 문서. 지우지 않는다 — 사람이 본다.

    `belongs` 는 따로 낸다. 그것은 대화에서 찾은 주장이 아니라 노드의 분류 칸을
    그대로 엣지로 옮긴 것이라, 근거를 물으면 분류가 어긋난 노드가 전부 '근거 없음'
    으로 나온다 — 못 찾은 것이 아니라 물음이 어긋난 것이다. 그래서 '왜 못 찾았나'
    표에서 빼고 '분류를 다시 볼 목록' 으로 돌린다.
    """
    path = OUT / ("graph-noevidence-%s.md" % day)
    gaps = [r for r in rows if not r["evidence"]]
    belongs = [r for r in gaps if r["edge"].get("type") == "belongs"]
    others = [r for r in gaps if r["edge"].get("type") != "belongs"]
    cache: dict[str, list[int]] = {}
    by_shape: dict[str, list[str]] = collections.defaultdict(list)
    for r in others:
        e = r["edge"]
        s, d = nodes.get(e["source"]), nodes.get(e["target"])
        by_shape[r["shape"]].append(
            "| %s | %s | %s | %s |" % (
                (s or {}).get("label", e["source"]), e.get("type"),
                (d or {}).get("label", e["target"]),
                gap_reason(e, nodes, ctx, cache)))

    cands = ontology.node_tag_candidates(
        list(nodes.values()), ctx["threads"], ctx["node_tags"],
        ontology.load_settled_nodes())

    body = ["# 근거를 못 찾은 관계 — %s" % day, "",
            "- 엣지 %d개 가운데 %d개. 그중 %d개는 `belongs` 라 아래 따로 뒀다."
            % (len(rows), len(gaps), len(belongs)),
            "- **지우지 않는다.** 누적된 원장이고, 그날 판단으로 과거를 지우면",
            "  되돌릴 수 없다. 이 문서는 사람이 훑는 목록이다.",
            "- 가장 빠른 길은 아래 `node_tags` 후보를 표에 적는 것이다 — 적으면",
            "  `python -m scripts.graph_evidence --report` 를 공짜로 다시 돌려",
            "  근거가 얼마나 늘었는지 볼 수 있다(LLM 호출이 없다).", ""]
    for shape in sorted(by_shape, key=lambda x: -len(by_shape[x])):
        body += ["## %s — %d개" % (shape, len(by_shape[shape])), "",
                 "| 출발 | 관계 | 도착 | 왜 못 찾았나 |", "|---|---|---|---|"]
        body += by_shape[shape] + [""]

    body += gaps_belongs_section(belongs, nodes, ctx)

    body += ["## `config/node_tags.json` 후보 %d개" % len(cands), "",
             "이름으로도 표로도 주제를 못 찾는 노드다. 짝지을 태그를 골라 적는다.",
             "잇지 않기로 정하는 것도 답이고, 그때는 `no_tag` 에 적는다.", "",
             "| 노드 | 라벨 | 후보 태그 |", "|---|---|---|"]
    body += ["| %s | %s | %s |" % (nid, label, " · ".join(c))
             for nid, label, c in cands] or ["| — | (없음) | — |"]
    path.write_text("\n".join(body) + "\n", encoding="utf-8")
    return path


def gaps_belongs_section(belongs: list[dict], nodes: dict, ctx: dict) -> list[str]:
    """`belongs` 빈칸은 '분류를 다시 볼 목록' 이다.

    판정 규칙은 `build_site.filed_elsewhere` 한 곳에 있다 — 밤 갱신 경고도 같은
    것을 쓴다. 여기서는 그 결과를 표로 낼 뿐이다.
    """
    if not belongs:
        return []
    from scripts import build_site      # 규칙은 한 곳에 — 순환 참조는 없다

    said = {n["id"]: seen for n, seen in build_site.filed_elsewhere(
        [nodes[r["edge"]["source"]] for r in belongs if r["edge"]["source"] in nodes],
        ctx["hay"], ctx["cat"], floor=1)}
    out = ["## 분류가 어긋나 보이는 노드 — `belongs` %d개" % len(belongs), "",
           "`belongs` 는 대화에서 찾은 주장이 아니다. 노드의 **분류 칸**을 그대로",
           "엣지로 옮긴 것이라, '그 분류의 말에 이 이름이 나오나' 를 물으면 분류가",
           "어긋난 노드가 전부 근거 없음으로 나온다 — 못 찾은 것이 아니라 물음이",
           "어긋난 것이다.", "",
           "**단정하지 않는다.** 도구의 분류는 '이것이 어떤 것인가' 이고 아래 분포는",
           "'어디서 이야기됐나' 다. 둘은 정당하게 다를 수 있다 — 깃허브 액션은",
           "인프라가 맞지만 사람들은 무언가 만들며 그 이름을 말한다.", "",
           "| 노드 | 지금 분류 | 실제로 이야기된 분류 |", "|---|---|---|"]
    seen_nodes = []
    for r in belongs:
        n = nodes.get(r["edge"]["source"])
        if not n or n["id"] in seen_nodes:
            continue
        seen_nodes.append(n["id"])
        got = said.get(n["id"])
        spread = (" · ".join("%s %d" % (ctx["cat_label"].get(c, c), v)
                             for c, v in got.most_common(3))
                  if got else "원문에 이름이 안 나온다 — 판단할 재료가 없다")
        out.append("| %s | %s | %s |" % (
            n["label"], ctx["cat_label"].get(n.get("category"), n.get("category")), spread))
    return out + [""]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--report", action="store_true", help="모양별 표만 (원장에 안 쓴다)")
    ap.add_argument("--apply", action="store_true", help="원장에 덧붙인다 (백업 먼저)")
    ap.add_argument("--gaps", action="store_true", help="근거 못 찾은 엣지 문서를 쓴다")
    ap.add_argument("--day", default=datetime.now().strftime("%Y%m%d"))
    args = ap.parse_args()

    knowledge = jsonio.read_json(KNOWLEDGE)
    ctx = message_context()
    got = survey(knowledge, ctx)
    rows, nodes = got["rows"], got["nodes"]
    report(rows)

    if args.gaps:
        path = write_gaps(rows, nodes, ctx, args.day)
        print("\n근거 못 찾은 관계 → %s" % shown(path))
    if args.apply:
        changed, backup = apply_evidence(knowledge, rows, args.day)
        if not changed:
            print("\n근거는 이미 다 붙어 있습니다 — 원장을 쓰지 않았습니다.")
        else:
            print("\n엣지 %d개를 고쳤습니다(근거를 덧붙임)." % changed)
            print("백업: %s/ (바꾸기 전 knowledge.json)" % shown(backup))
            print("다음: python -m scripts.build_site  → 테스트 → 발행")
    elif not args.gaps:
        print("\n원장은 한 글자도 안 바꿨습니다. 덧붙이려면 --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
