# -*- coding: utf-8 -*-
"""관계망의 스키마 — 어떤 종류가 있고, 어떤 관계가 성립하는가.

## 원본은 여기 하나다

예전에는 세 군데에 흩어져 있었다.

  · `output/knowledge.json` 의 `node_types`·`edge_types` — 발행본에 실려 화면까지
    내려가는데 **화면이 읽지 않았다**
  · `site/graph.js` 의 `TYPES` — 걸러내기 단추. 라벨이 위와 달랐다('앱' vs '앱·결과물')
  · `site/app.js` 의 `typeMap` — 노드 패널

보고서 규칙을 `topic_reports.REPORT_RULES` 한 곳으로 모은 것과 같은 이유다. 종류를
하나 더할 때 세 곳을 고쳐야 하면 언젠가 두 곳만 고친다.

## 관계에는 정의역과 치역이 있다

예전 검증은 '엣지 종류가 목록에 있나 · 양 끝 노드가 있나' 두 가지뿐이었다
(`classify_unsorted.merge_graph`). 종류 이름만 맞으면 무슨 모양이든 통과하므로
뜻이 안 되는 엣지가 원장에 남았다 — 실측 2026-08-12 에 `person -belongs-> topic`
두 건. `belongs` 는 '이 도구가 어느 주제에 속하나' 인데 사람이 분류에 속한다는
말이 되어 버렸다(그 뜻이라면 `interested` 다).

반대로 처음에 '이상해 보였던' 조합은 대부분 멀쩡했다. `person -interested-> tool`
32건은 '이 도구에 관심을 보였다' 로 `uses`(실제로 썼다) 와 다른 말이고,
`tool -uses-> tool` 은 스킬이 클로드 코드를 쓴다는 뜻이다. 그래서 치역은 넉넉히
잡고, **모양이 아예 성립하지 않는 것만** 막는다. 좁게 잡으면 LLM 이 알아낸 것을
버리게 된다.

## 고치는 것과 그대로 두는 것

모양이 어긋난 엣지는 **뜻이 하나로 정해질 때만** 관계 이름을 고친다. `person→topic`
에 성립하는 관계는 `interested` 하나이므로 고칠 수 있다. `person→tool` 은
`made`·`uses`·`interested` 가 다 성립하므로 무엇으로 쓴 것인지 알 수 없고, 그때는
고치지 않고 알린다 — 사람이 볼 일이다. 옛 엣지를 지우지 않는 것은 `merge_graph` 와
같은 이유다(누적된 원장이고, 그날 판단으로 과거를 지우면 되돌릴 수 없다).
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts import tags as taglib

ROOT = Path(__file__).resolve().parent.parent
NODE_TAGS_PATH = ROOT / "config" / "node_tags.json"

# 화면의 걸러내기 단추는 좁아서 `short`, 노드 패널은 `label` 을 쓴다. 라벨을 두 벌
# 두는 대신 한 노드 종류에 두 이름을 준다 — 갈라지지 않는다.
NODE_TYPES = [
    {"id": "topic", "label": "주제", "short": "주제"},
    {"id": "app", "label": "앱·결과물", "short": "앱"},
    {"id": "tool", "label": "도구·기술", "short": "도구"},
    {"id": "person", "label": "사람", "short": "사람"},
]

# domain = source 로 올 수 있는 종류, range = target 으로 올 수 있는 종류.
EDGE_TYPES = [
    {"id": "made", "label": "만든이",
     "domain": ["person"], "range": ["app", "tool"]},
    {"id": "uses", "label": "사용",
     "domain": ["person", "app", "tool"], "range": ["app", "tool"]},
    {"id": "belongs", "label": "주제",
     "domain": ["app", "tool"], "range": ["topic"]},
    {"id": "interested", "label": "관심",
     "domain": ["person"], "range": ["topic", "app", "tool"]},
]

_EDGE_BY_ID = {e["id"]: e for e in EDGE_TYPES}

# 분류 12개의 상위 묶음. 분류는 평평해서 'AI 코딩 도구'·'AI 모델' 을 한 덩어리로 볼
# 방법이 없었다. 사람별 관심 분야가 특히 그 때문에 비었다 — 주제 3~5개짜리 참여자는
# 12분면에서 표본이 너무 얇아, 실측 2026-08-12 에 32명 중 5명이 관심 분야가 0개였다.
#
# `chat`(일상·잡담)은 일부러 어느 묶음에도 넣지 않는다 — 아래 참고.
CATEGORY_GROUPS = [
    {"id": "group:building", "label": "만들기·기술",
     "categories": ["projects", "hwp", "infra"]},
    {"id": "group:ai", "label": "AI 도구·모델",
     "categories": ["ai-tools", "ai-models"]},
    {"id": "group:practice", "label": "실천·제도",
     "categories": ["welfare-practice", "governance"]},
    {"id": "group:community", "label": "모임·나눔",
     "categories": ["events", "members", "community", "news-articles"]},
]

# 분류가 아직 정해지지 않은 자리. 빠뜨린 것과 구분하려고 적어 둔다 —
# `test_every_category_belongs_to_a_group` 이 이 목록만 예외로 봐준다.
#
# 두 곳에서 쓰인다. 상위 묶음에 넣지 않고(`group_of` 가 None), 사람별 **관심 분야**
# 로도 내지 않는다. 이유가 하나다 — `chat` 은 '아직 안 정해졌다'는 뜻이어서 그 사람이
# 무엇에 관심이 있는지 말해 주지 않는다. `build_site.sync_person_nodes` 가 chat 을
# 대표 분류로 쓰지 않는 것과 같은 판단이다.
#
# 실측 2026-08-12: 이 걸림이 없을 때 발행본에서 세 사람이 '일상·잡담' 을 관심 분야로
# 달고 있었다(한 명은 lift 3.04 로 1순위였다). 사람을 평가하는 화면처럼 읽히지 않게
# 공들여 만든 자리에 그 말이 서면 안 된다.
PROVISIONAL_CATEGORIES = {"chat"}

_GROUP_OF = {c: g["id"] for g in CATEGORY_GROUPS for c in g["categories"]}
_GROUP_LABEL = {g["id"]: g["label"] for g in CATEGORY_GROUPS}


def group_of(category: str | None) -> str | None:
    """그 분류가 속한 묶음 id. 묶음이 없으면 None."""
    return _GROUP_OF.get(category or "")


def group_label(group_id: str | None) -> str:
    return _GROUP_LABEL.get(group_id or "", group_id or "")


def node_type_ids() -> set[str]:
    return {t["id"] for t in NODE_TYPES}


def edge_type_ids() -> set[str]:
    return set(_EDGE_BY_ID)


def is_valid(src_type: str | None, etype: str | None,
             dst_type: str | None) -> bool:
    """이 모양의 엣지가 성립하는가."""
    spec = _EDGE_BY_ID.get(etype or "")
    if not spec:
        return False
    return src_type in spec["domain"] and dst_type in spec["range"]


def fits(src_type: str | None, dst_type: str | None) -> list[str]:
    """이 모양(출발 종류 → 도착 종류)에 성립하는 관계들. 선언 순서대로."""
    return [e["id"] for e in EDGE_TYPES
            if src_type in e["domain"] and dst_type in e["range"]]


def repair(src_type: str | None, etype: str | None,
           dst_type: str | None) -> str | None:
    """어긋난 엣지의 관계 이름을 고쳐 준다. 정할 수 없으면 None.

    두 가지 경우에만 고친다.

    · 관계 이름을 알아본 것 — 모르는 이름은 무슨 뜻으로 쓴 것인지 알 수 없다.
    · 그 모양에 성립하는 관계가 **딱 하나** 인 것 — 여럿이면 고르는 것이 곧 추측이다.
    """
    if etype not in _EDGE_BY_ID:
        return None
    candidates = fits(src_type, dst_type)
    return candidates[0] if len(candidates) == 1 else None


def sync_types(knowledge: dict) -> bool:
    """원장의 `node_types`·`edge_types` 를 이 파일로 맞춘다. 달라졌으면 True.

    원장이 아니라 여기가 원본이므로 덮어쓴다. 발행본은 이 값을 그대로 화면에
    내려보내고, 화면은 걸러내기 단추와 노드 패널의 이름을 여기서 읽는다.
    """
    before = (knowledge.get("node_types"), knowledge.get("edge_types"))
    knowledge["node_types"] = [dict(t) for t in NODE_TYPES]
    knowledge["edge_types"] = [dict(t) for t in EDGE_TYPES]
    return before != (knowledge["node_types"], knowledge["edge_types"])


def apply(knowledge: dict) -> dict:
    """원장을 스키마에 맞춘다. 무엇을 했는지 보고서로 돌려준다.

    돌려주는 것:
      types_changed  종류 표가 갱신됐나
      repaired       [(source, target, 옛 관계, 새 관계)] 이름을 고친 엣지
      dropped        [(source, target, 옛 관계, 겹친 관계)] 고쳤더니 이미 있어서 지운 것
      invalid        [(source, 관계, target)] 뜻을 정할 수 없어 그대로 둔 것

    여러 번 돌려도 같다 — 고칠 것이 없으면 아무것도 하지 않는다.
    """
    changed = sync_types(knowledge)

    type_of = {n["id"]: n.get("type") for n in knowledge.get("nodes", [])}
    edges = knowledge.get("edges", [])
    seen = {(e.get("source"), e.get("target"), e.get("type")) for e in edges}

    repaired: list[tuple] = []
    dropped: list[tuple] = []
    invalid: list[tuple] = []
    drop_ids: set[int] = set()

    for e in edges:
        src, dst, etype = e.get("source"), e.get("target"), e.get("type")
        st, dt = type_of.get(src), type_of.get(dst)
        # 끊긴 엣지(없는 노드를 가리키는 것)는 여기서 판정하지 않는다 —
        # `test_edges_reference_existing_nodes` 의 몫이고, 종류를 모르니 고칠 수도 없다.
        if st is None or dt is None:
            continue
        if is_valid(st, etype, dt):
            continue
        fix = repair(st, etype, dt)
        if not fix:
            invalid.append((src, etype, dst))
            continue
        if (src, dst, fix) in seen:
            # 같은 뜻의 엣지가 이미 있다. 고치면 중복이 되므로 어긋난 쪽을 지운다.
            # 사람 노드는 `build_site.sync_person_nodes` 가 person→topic 을
            # interested 로 이미 만들어 두므로 이 길로 오는 것이 흔하다.
            drop_ids.add(id(e))
            dropped.append((src, dst, etype, fix))
            continue
        e["type"] = fix
        seen.discard((src, dst, etype))
        seen.add((src, dst, fix))
        repaired.append((src, dst, etype, fix))

    if drop_ids:
        knowledge["edges"] = [e for e in edges if id(e) not in drop_ids]

    return {"types_changed": changed, "repaired": repaired,
            "dropped": dropped, "invalid": invalid}


def log(report: dict) -> None:
    """`apply` 의 보고서를 사람이 읽는 줄로 찍는다. 할 말이 없으면 조용하다."""
    for src, dst, old, new in report.get("repaired") or []:
        print("[관계망] 모양이 어긋난 관계를 고침: %s -%s-> %s (%s 였다)"
              % (src, new, dst, old))
    for src, dst, old, new in report.get("dropped") or []:
        print("[관계망] 어긋난 관계를 지움: %s -%s-> %s (같은 뜻의 %s 가 이미 있다)"
              % (src, old, dst, new))
    if report.get("invalid"):
        print("[관계망] 뜻을 정할 수 없어 그대로 둔 관계 %d건 — 사람이 볼 일입니다: %s"
              % (len(report["invalid"]),
                 ", ".join("%s -%s-> %s" % x for x in report["invalid"][:5])))


def load_node_tags(path: Path | None = None) -> dict[str, list[str]]:
    """`config/node_tags.json` → {노드 id: 그 노드를 뜻하는 태그들}.

    관계망 노드와 태그는 같은 것을 두 벌로 관리한다 — 태그 '안티그래비티' 와
    `tool:antigravity` 는 같은 것인데 서로를 모른다. 그래서 화면은 **글자로 다시**
    잇는다(`build_site.is_subject`). 이름이 서술형인 결과물은 그 방법으로 못 이어져
    '다룬 주제' 가 0개가 된다 — 실측 2026-08-12 에 앱 78개 중 38개.

    표가 없어도 돌아간다. 그때는 예전처럼 이름 글자로만 잇는다.
    """
    p = path or NODE_TAGS_PATH
    if not p.exists():
        return {}
    raw = json.loads(p.read_text(encoding="utf-8")).get("node_tags") or {}
    out: dict[str, list[str]] = {}
    for node_id, names in raw.items():
        node_id = (node_id or "").strip()
        keep = [str(n).strip() for n in (names or []) if str(n).strip()]
        if node_id and keep:
            out[node_id] = keep
    return out


def load_settled_nodes(path: Path | None = None) -> set[str]:
    """`config/node_tags.json` 의 `no_tag` — 잇지 않기로 **정한** 노드.

    빠뜨린 것과 구분하려고 따로 적는다. 후보가 나오지만 그 후보로 이으면 안 되는
    경우가 있다 — 일반 도구명·개념·기관 이름뿐일 때다. 한 번 판단한 것을 또 묻지
    않는 것이 요점이고, `tag_places.json` 의 `not_places` 와 같은 몫이다.
    """
    p = path or NODE_TAGS_PATH
    if not p.exists():
        return set()
    raw = json.loads(p.read_text(encoding="utf-8")).get("no_tag") or []
    return {str(x).strip() for x in raw if str(x).strip()}


def node_tag_candidates(nodes: list[dict], threads: list[dict],
                        table: dict[str, list[str]] | None = None,
                        settled: set[str] | None = None,
                        types: tuple[str, ...] = ("app",), min_len: int = 3
                        ) -> list[tuple[str, str, list[str]]]:
    """표에 아직 없고 이름으로도 안 이어지는 노드. (노드 id, 라벨, 후보 태그들).

    후보는 라벨과 태그의 fold 가 한쪽을 품을 때 내놓고, 긴 것부터 보여준다 —
    긴 쪽이 그 물건의 이름일 확률이 높고, 짧은 것은 일반 도구명이기 쉽다.
    **고르는 것은 사람이다.** `place_candidates` 와 같은 몫이다.

    `settled`(= `no_tag`)에 적힌 노드는 내지 않는다. 잇기로 한 것과 잇지 않기로 한
    것이 둘 다 판단이 끝난 상태이므로 같이 빠져야 한다.
    """
    table = table or {}
    settled = settled or set()
    tag_names: dict[str, str] = {}
    for t in threads:
        for tg in t.get("tags") or []:
            key = taglib.fold(tg)
            if len(key) >= min_len:
                tag_names.setdefault(key, tg)

    rows = []
    for n in nodes:
        if n.get("type") not in types or n["id"] in table or n["id"] in settled:
            continue
        key = taglib.fold(n.get("label") or "")
        if len(key) < min_len or key in tag_names:
            continue        # 이름이 곧 태그면 예전 방법으로 이미 이어진다
        cand = [name for k, name in tag_names.items() if k in key or key in k]
        if cand:
            cand.sort(key=lambda c: (-len(taglib.fold(c)), c))
            rows.append((n["id"], n.get("label") or "", cand[:3]))
    rows.sort(key=lambda r: r[0])
    return rows


def prompt_rules() -> str:
    """분류 프롬프트에 넣을 관계 규칙. 표를 프롬프트에 옮겨 적지 않는다.

    프롬프트는 부탁이고 `merge_graph` 가 보장이지만, 부탁을 정확히 해야 버리는
    엣지가 줄어든다. 여기서 만들어 주면 표가 바뀔 때 프롬프트도 같이 바뀐다.
    """
    lines = [
        "- edge 는 아래 네 관계만 쓰고, **양 끝의 종류가 정해져 있습니다.**",
        "  표에 없는 모양은 버려집니다.",
    ]
    width = max(len(e["id"]) for e in EDGE_TYPES)
    for e in EDGE_TYPES:
        lines.append("  · %-*s %s → %s   (%s)"
                     % (width, e["id"], ", ".join(e["domain"]),
                        ", ".join(e["range"]), e["label"]))
    lines += [
        '  source/target 은 "person:닉네임", "app:...", "tool:...",'
        ' "topic:카테고리id".',
        "- '썼다'는 uses, '관심을 보였다'는 interested 입니다. 사람이 어느 분류에"
        " 관심이 있다는 뜻은 interested 이고, belongs 는 앱·도구가 어느 주제에",
        "  속하는지에만 씁니다.",
    ]
    return "\n".join(lines)
