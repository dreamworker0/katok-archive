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
      named-both   app/tool → app/tool  두 이름이 한 메시지에 함께 나온 것
      tagged       (위가 비었을 때)      `config/node_tags.json` 으로 짝지은 태그를
                                        가진 주제의 말. 이름이 서술형인 앱이 제
                                        근거를 찾는 유일한 길이다

짧은 이름은 뒷받침을 요구한다
    `query` 가 두 글자인 노드가 17개다 — `상담`·`게임`·`토론`·`엑셀` 같은 일반어다.
    실측해 보니 걸리는 수는 적었지만(`상담` 10회) **틀린 근거는 없는 근거보다
    나쁘다.** '상담' 이 든 아무 말이나 상담 도구의 근거로 서면, 그 링크를 눌러 본
    사람이 아카이브를 믿지 못하게 된다.

    그렇다고 세 글자 미만을 통째로 막으면 `슬랙`(30회)·`노션`·`애저`·`버셀` 처럼
    진짜 이름까지 잃는다. 그래서 **짧은 이름은 그 메시지가 속한 주제가 그 노드와
    이어질 때만** 근거로 인정한다(`linked_threads`). 뒷받침이 붙은 것은 `by` 에
    `+thread` 를 달아 어느 판정이었는지 남긴다.

사용
    python -m scripts.graph_evidence --report      # 모양별 표만 (원장에 안 쓴다)
    python -m scripts.graph_evidence --apply       # 원장에 덧붙인다 (백업 먼저)
    python -m scripts.graph_evidence --gaps        # 근거 못 찾은 엣지 문서
"""
from __future__ import annotations

import argparse
import collections
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
SHORT_NAME_CHARS = 3


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
    """
    names = [x.lower() for x in (node.get("query"), node.get("label")) if x]
    if not names:
        return []
    long_names = [n for n in names if len(n) >= SHORT_NAME_CHARS]
    short_names = [n for n in names if len(n) < SHORT_NAME_CHARS]
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
    """(근거 message id 들, 규칙 이름). 못 찾으면 ([], 규칙 이름)."""
    src, dst = nodes.get(edge.get("source")), nodes.get(edge.get("target"))
    if not src or not dst:
        return [], ""
    rule = rule_for(src["type"], dst["type"])

    def mentions(n):
        if n["id"] not in cache:
            cache[n["id"]] = mentions_of(n, ctx)
        return cache[n["id"]]

    if rule == "spoke-in":
        hits = [i for i, w in enumerate(ctx["who"])
                if w == src["label"] and ctx["cat"][i] == dst.get("category")]
    elif rule == "named-it":
        hits = [i for i in mentions(dst) if ctx["who"][i] == src["label"]]
    elif rule == "named-in":
        hits = [i for i in mentions(src) if ctx["cat"][i] == dst.get("category")]
    else:
        other = set(mentions(dst))
        hits = [i for i in mentions(src) if i in other]

    if not hits:
        # 두 번째 길 — 사람이 짝지어 둔 태그로. 이름이 서술형인 앱의 유일한 길이다.
        side = dst if rule in ("named-it",) else src
        tagged = tagged_hits(side, ctx)
        if rule == "named-it":
            tagged = [i for i in tagged if ctx["who"][i] == src["label"]]
        elif rule == "named-in":
            tagged = [i for i in tagged if ctx["cat"][i] == dst.get("category")]
        if tagged:
            return [ctx["ids"][i] for i in pick(tagged, ctx)], "tagged"
        return [], rule

    # 뒷받침으로 살아난 짧은 이름이 섞였는지 표시한다 — 어느 판정이었는지 남긴다.
    return [ctx["ids"][i] for i in pick(hits, ctx)], rule


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


def apply_evidence(knowledge: dict, rows: list[dict], day: str) -> tuple[int, Path]:
    """찾은 근거를 엣지에 덧붙인다. 여러 번 돌려도 같다.

    근거를 못 찾은 엣지에는 `evidence` 키를 **아예 만들지 않는다.** 빈 배열을 넣으면
    화면이 '근거가 있다' 고 믿고 빈 목록을 그린다 — `weigh_knowledge.span` 이 빈
    날짜를 안 넣는 것과 같은 이유다.
    """
    backup = backup_dir("graph", day)
    if KNOWLEDGE.is_file():
        shutil.copy2(KNOWLEDGE, backup / KNOWLEDGE.name)
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
            cache[n["id"]] = mentions_of(n, ctx)
        if not cache[n["id"]]:
            return "원문에 이름이 한 번도 안 나온다 (%s)" % n["label"]

    rule = rule_for(src["type"], dst["type"])
    if rule == "named-both":
        return "두 이름이 한 메시지에서 만나지 않는다"
    if rule == "named-it":
        return "그 사람의 말에는 그 이름이 안 나온다"
    if rule == "named-in":
        return "그 분류의 말에는 그 이름이 안 나온다"
    return "그 사람이 그 분류에서 한 말이 없다"


def write_gaps(rows: list[dict], nodes: dict, ctx: dict, day: str) -> Path:
    """근거를 못 찾은 엣지 문서. 지우지 않는다 — 사람이 본다."""
    path = OUT / ("graph-noevidence-%s.md" % day)
    gaps = [r for r in rows if not r["evidence"]]
    cache: dict[str, list[int]] = {}
    by_shape: dict[str, list[str]] = collections.defaultdict(list)
    for r in gaps:
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
            "- 엣지 %d개 가운데 %d개." % (len(rows), len(gaps)),
            "- **지우지 않는다.** 누적된 원장이고, 그날 판단으로 과거를 지우면",
            "  되돌릴 수 없다. 이 문서는 사람이 훑는 목록이다.",
            "- 가장 빠른 길은 아래 `node_tags` 후보를 표에 적는 것이다 — 적으면",
            "  `python -m scripts.graph_evidence --report` 를 공짜로 다시 돌려",
            "  근거가 얼마나 늘었는지 볼 수 있다(LLM 호출이 없다).", ""]
    for shape in sorted(by_shape, key=lambda s: -len(by_shape[s])):
        body += ["## %s — %d개" % (shape, len(by_shape[shape])), "",
                 "| 출발 | 관계 | 도착 | 왜 못 찾았나 |", "|---|---|---|---|"]
        body += by_shape[shape] + [""]

    body += ["## `config/node_tags.json` 후보 %d개" % len(cands), "",
             "이름으로도 표로도 주제를 못 찾는 노드다. 짝지을 태그를 골라 적는다.",
             "잇지 않기로 정하는 것도 답이고, 그때는 `no_tag` 에 적는다.", "",
             "| 노드 | 라벨 | 후보 태그 |", "|---|---|---|"]
    body += ["| %s | %s | %s |" % (nid, label, " · ".join(c))
             for nid, label, c in cands] or ["| — | (없음) | — |"]
    path.write_text("\n".join(body) + "\n", encoding="utf-8")
    return path


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
        print("\n엣지 %d개를 고쳤습니다(근거를 덧붙임)." % changed)
        print("백업: %s/ (바꾸기 전 knowledge.json)" % shown(backup))
        print("다음: python -m scripts.build_site  → 테스트 → 발행")
    elif not args.gaps:
        print("\n원장은 한 글자도 안 바꿨습니다. 덧붙이려면 --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
