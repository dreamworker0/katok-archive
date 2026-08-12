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
