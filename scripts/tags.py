# -*- coding: utf-8 -*-
"""태그(보고서 keywords) 표기 통일과 태그 색인.

보고서 314편에 태그 1,343개가 붙어 있는데 표기가 갈린다 — '바이브코딩'과
'바이브 코딩', 'AI Studio'와 'AI 스튜디오'가 따로 세어져 태그로 찾을 때 절반만
나온다. 원본 보고서는 손대지 않고(사람이 쓴 글이다) **발행할 때만** 합친다.

두 단계로 합친다.

1. 기계적: 대소문자·공백·하이픈·마침표 차이는 자동으로 한 덩어리. 표시 이름은
   그 덩어리에서 가장 많이 쓰인 표기를 고른다. 표에 적지 않아도 되는 몫이다.
2. 사람 판단: 말 자체가 다른 같은 것('Gemini' = '제미나이')은
   `config/tag_aliases.json` 표를 따른다.

사람 이름 태그는 따로 표시해 둔다(`people`) — 사람은 참여자 화면에서 찾는 것이
맞고, 주제 태그 입구에 이름이 섞이면 프로파일링처럼 보인다.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALIAS_PATH = ROOT / "config" / "tag_aliases.json"

_FOLD = re.compile(r"[\s\-_.]+")


def fold(tag: str) -> str:
    """비교용 열쇠. 'AI Studio' 와 'ai-studio' 가 같아진다."""
    return _FOLD.sub("", (tag or "").strip()).lower()


def load_aliases(path: Path | None = None) -> dict[str, str]:
    """표기 통일표 → {변형의 fold: 대표 표기}. 대표 표기 자신도 넣는다."""
    p = path or ALIAS_PATH
    if not p.exists():
        return {}
    raw = json.loads(p.read_text(encoding="utf-8")).get("aliases") or {}
    out: dict[str, str] = {}
    for canon, variants in raw.items():
        out[fold(canon)] = canon
        for v in variants or []:
            out[fold(v)] = canon
    return out


def build_tag_map(raw_tags: list[str], aliases: dict[str, str] | None = None
                  ) -> dict[str, str]:
    """말뭉치 전체의 태그 → 표시 이름. 원본 태그를 열쇠로 하는 표를 돌려준다."""
    aliases = aliases if aliases is not None else load_aliases()

    # 1단계: fold 가 같은 것끼리 묶고, 가장 많이 쓰인 표기를 대표로.
    groups: dict[str, Counter] = defaultdict(Counter)
    for t in raw_tags:
        t = (t or "").strip()
        if t:
            groups[fold(t)][t] += 1
    display: dict[str, str] = {}
    for key, spellings in groups.items():
        best = sorted(spellings.items(), key=lambda kv: (-kv[1], len(kv[0]), kv[0]))[0][0]
        display[key] = best

    # 2단계: 표에 있으면 표를 따른다.
    out: dict[str, str] = {}
    for key, best in display.items():
        out_name = aliases.get(key, best)
        for spelling in groups[key]:
            out[spelling] = out_name
    return out


def canonical_tags(tags: list[str], tag_map: dict[str, str]) -> list[str]:
    """한 스레드의 태그를 표시 이름으로 바꾼다. 순서 유지, 중복 제거."""
    out, seen = [], set()
    for t in tags or []:
        t = (t or "").strip()
        if not t:
            continue
        name = tag_map.get(t) or t
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def person_names(participants: dict) -> set[str]:
    """참여자 이름(괄호 소속 제외)의 모음. '김종원(○○관)' → '김종원' 도 넣는다."""
    names: set[str] = set()
    rows = participants.get("participants") if isinstance(participants, dict) else participants
    for p in rows or []:
        nick = p.get("nickname") if isinstance(p, dict) else str(p)
        if not nick:
            continue
        names.add(nick.strip())
        base = re.sub(r"\s*[(（].*?[)）]\s*$", "", nick).strip()
        if base:
            names.add(base)
    return names


def attach_tags(threads: list[dict], participants: dict | None = None,
                aliases: dict[str, str] | None = None) -> dict[str, str]:
    """스레드에 `tags`(표시 이름)를 붙이고 쓴 표를 돌려준다. 제자리에서 고친다."""
    raw = [t for th in threads for t in (th.get("keywords") or [])]
    tag_map = build_tag_map(raw, aliases)
    for th in threads:
        th["tags"] = canonical_tags(th.get("keywords") or [], tag_map)
    return tag_map


def build_tag_index(threads: list[dict], participants: dict | None = None,
                    min_count: int = 2) -> dict:
    """태그 입구용 색인.

    `min_count` 미만으로 쓰인 태그는 목록에서 빼고 수만 센다 — 314개 주제에
    한 번만 쓰인 태그가 850개다. 다 늘어놓으면 목록이 아니라 벽이 된다
    (검색으로는 여전히 찾을 수 있다).
    """
    people = person_names(participants or {})
    counts: Counter[str] = Counter()
    threads_of: dict[str, list[str]] = defaultdict(list)
    for th in threads:
        for name in th.get("tags") or []:
            counts[name] += 1
            threads_of[name].append(th["id"])

    rows = []
    for name, n in counts.items():
        if n < min_count:
            continue
        rows.append({
            "tag": name,
            "count": n,
            "person": name in people,
            "thread_ids": threads_of[name],
        })
    rows.sort(key=lambda r: (-r["count"], r["tag"]))
    return {
        "tags": rows,
        "min_count": min_count,
        "total_tags": len(counts),
        "hidden_tags": sum(1 for n in counts.values() if n < min_count),
    }
