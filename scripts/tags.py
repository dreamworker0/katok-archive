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

좁은 태그는 넓은 태그로도 찾히게 한다(`rollup_parent_tags`) — 아래 설명 참조.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALIAS_PATH = ROOT / "config" / "tag_aliases.json"

_FOLD = re.compile(r"[\s\-_.]+")

# 조각만 로마자인 태그를 위한 음역 대응. 'Gemini 3 Pro' 와 '제미나이 3 프로' 는
# 같은 것인데 통일표는 태그 **전체**가 같을 때만 맞으므로 이런 조합을 한 줄씩
# 적어야 했다(버전이 늘 때마다 또 적어야 한다). 조각 단위로 대응시키면 표가
# 필요 없다 — 'Ontology-Playground' 가 '온톨로지'에 닿는 것도 이 몫이다.
#
# 조각(공백·하이픈으로 끊은 낱말) **전체**가 같을 때만 바꾼다. 'pro' → '프로' 를
# 글자 단위로 바꾸면 '프로젝트'·'프로그램'까지 건드린다.
TRANSLIT = {
    "gemini": "제미나이", "claude": "클로드", "opus": "오퍼스", "sonnet": "소네트",
    "ontology": "온톨로지", "playground": "플레이그라운드", "modeling": "모델링",
    "tutorial": "튜토리얼", "workspace": "워크스페이스", "studio": "스튜디오",
    "code": "코드", "pro": "프로", "plus": "플러스", "max": "맥스", "flash": "플래시",
    "github": "깃허브", "youtube": "유튜브", "python": "파이썬", "discord": "디스코드",
    "facebook": "페이스북", "hackathon": "해커톤", "agent": "에이전트",
    "vercel": "버셀", "firebase": "파이어베이스", "cloudflare": "클라우드플레어",
    "codex": "코덱스", "perplexity": "퍼플렉시티", "lovable": "러버블",
    "azure": "애저", "chatgpt": "챗gpt", "google": "구글", "notebooklm": "노트북lm",
}


def fold(tag: str) -> str:
    """비교용 열쇠. 'AI Studio' 와 'ai-studio' 가 같아진다.

    조각이 `TRANSLIT` 에 있으면 한글 표기로 맞춘 뒤 붙인다 — 'Claude Code' 와
    '클로드 코드'가 같아진다.
    """
    parts = [p for p in _FOLD.split((tag or "").strip().lower()) if p]
    return "".join(TRANSLIT.get(p, p) for p in parts)


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


def backfill_from_titles(threads: list[dict], labels: list[str],
                         aliases: dict[str, str] | None = None,
                         min_len: int = 3) -> list[tuple[str, str]]:
    """제목이 곧 그 화제인데 태그에 없으면 채운다. 채운 (주제 id, 태그) 목록.

    태그는 보고서마다 따로 지어졌고 공통 어휘가 없었다. 그래서 '차량 운행일지
    전체 코드 공개'의 태그가 오픈소스·깃허브·멀티테넌트뿐이고 정작
    '차량운행일지'가 없다 — 태그로 찾으면 이 주제가 빠진다(실측 42건).

    제목에 이름이 들어 있으면 그 주제는 그 화제를 **다루는** 것이다. 원문에
    스쳐 언급된 것과 다르다 — 제목은 사람이 그 대화를 무엇이라 불렀는지다.
    """
    aliases = aliases if aliases is not None else load_aliases()
    known = [l.strip() for l in labels if l and len(fold(l)) >= min_len]

    # 채워 넣는 이름도 통일표를 거쳐야 한다. 안 그러면 관계망의 '차량 운행일지'가
    # 통일해 둔 태그 '차량운행일지' 옆에 따로 서서 태그가 둘로 갈린다.
    display: dict[str, str] = {}
    for th in threads:
        for t in th.get("tags") or []:
            display.setdefault(fold(t), t)

    def resolve(label: str) -> str:
        key = fold(label)
        return aliases.get(key) or display.get(key) or label

    added: list[tuple[str, str]] = []
    for th in threads:
        title = fold(th.get("title") or "")
        have = {fold(t) for t in (th.get("tags") or [])}
        for label in known:
            key = fold(label)
            if key in title and key not in have:
                name = resolve(label)
                th.setdefault("tags", []).append(name)
                have.add(key)
                added.append((th["id"], name))
    return added


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


def rollup_parent_tags(threads: list[dict], participants: dict | None = None,
                       min_count: int = 2, min_len: int = 3
                       ) -> list[tuple[str, str]]:
    """좁은 태그에 넓은 태그를 덧붙인다. 붙인 (주제 id, 태그) 목록.

    'MS 온톨로지 플레이그라운드' 주제의 태그는 '온톨로지 모델링'인데 앞서 쌓인
    '온톨로지' 3건과 만나지 못했다 — 표기 통일은 공백·대소문자만 보므로
    '온톨로지모델링' 과 '온톨로지' 는 남남이다. 그래서 태그 하나짜리 고립 주제가
    된다(실측: 1,047개 태그가 1건뿐이다).

    좁은 태그를 넓은 태그로 **바꾸지** 않고 넓은 태그를 **덧붙인다**. '온톨로지
    모델링'의 정확함을 잃지 않으면서 '온톨로지'로도 찾힌다.

    두 가지 방벽을 둔다.

    * 부모는 `min_count` 건 이상 쓰인 태그만 — 한 번 쓰인 말이 부모가 되면
      아무 말이나 부모가 된다.
    * 부모는 fold 길이 `min_len` 이상 — 'AI'·'앱' 이 온 태그의 부모가 되는 것을
      막는다.

    사람 이름은 부모로 쓰지 않는다. 이름 태그는 참여자 화면 몫이고(`person`),
    '김종원' 이 '김종원 수정판'을 빨아들여도 얻는 것이 없다.
    """
    counts: Counter[str] = Counter(
        t for th in threads for t in (th.get("tags") or []))
    people = person_names(participants or {})
    base = [t for t, n in counts.items()
            if n >= min_count and len(fold(t)) >= min_len and t not in people]
    keys = {t: fold(t) for t in base}

    added: list[tuple[str, str]] = []
    for th in threads:
        own = list(th.get("tags") or [])
        have = set(own)
        for t in own:
            ft = fold(t)
            for b in base:
                if keys[b] != ft and keys[b] in ft and b not in have:
                    th["tags"].append(b)
                    have.add(b)
                    added.append((th["id"], b))
    return added


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
