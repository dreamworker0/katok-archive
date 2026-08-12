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

좁은 태그는 넓은 태그로도 찾히게 한다(`rollup_parent_tags`). 여기도 두 단계다 —
글자가 겹치는 것은 기계가('온톨로지 모델링' → '온톨로지'), 겹치지 않는 것은
`config/tag_broader.json` 표가 맡는다('앱스스크립트' → '구글 워크스페이스').
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALIAS_PATH = ROOT / "config" / "tag_aliases.json"
PLACES_PATH = ROOT / "config" / "tag_places.json"
BROADER_PATH = ROOT / "config" / "tag_broader.json"

# 지명·조직 **이름** 으로 보이는 꼴. 여기 걸린 것을 자동으로 빼지는 않는다.
#
# 이 방에서 '장애인복지관'·'거주시설'·'정신재활시설' 은 기관 종류가 아니라 이야기의
# 주제 그 자체다. 접미사만 보고 뺐다면 26개 중 6개가 그렇게 사라졌을 것이다(실측
# 2026-08-04). 반대로 '홍대입구'·'노원구' 같은 지명은 접미사로 못 잡는다 — 잡으려
# 들면 'AI리터러시'·'사례관리'·'프록시'까지 걸린다.
#
# 그래서 기계는 후보만 내놓고, 실제로 뺄 목록은 사람이 표(config/tag_places.json)에
# 적는다. tag_aliases.json 과 같은 방식이다 — 확실한 것만 기계가, 판단은 표로.
# '지사'·'지회' 는 넣지 않는다 — '사회복지사'·'대구 사회복지사' 가 걸린다(실측).
# 후보가 잘못 나오는 것은 사람의 시간을 먹는 일이므로 접미사는 아까워하지 않는다.
ORG_SUFFIXES = (
    "복지관", "복지재단", "협회", "센터", "재단", "시설", "공단", "구청", "시청",
    "도서관", "어린이집", "요양원", "병원", "대학교", "학교", "위원회", "연구원",
    "연구소", "본부",
)

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


def load_places(path: Path | None = None) -> tuple[set[str], set[str]]:
    """`config/tag_places.json` → (뺄 태그의 fold, 후보에서 지울 태그의 fold).

    표가 없어도 돌아간다 — 그때는 아무 태그도 빠지지 않고 후보만 보인다.
    이 파일은 커밋하지 않는다(예시는 tag_places.example.json). 특정 기관 이름이
    줄줄이 적히는 목록이고, 저장소는 공개다.
    """
    p = path or PLACES_PATH
    if not p.exists():
        return set(), set()
    raw = json.loads(p.read_text(encoding="utf-8"))
    return ({fold(t) for t in (raw.get("places") or []) if t},
            {fold(t) for t in (raw.get("not_places") or []) if t})


def load_broader(path: Path | None = None,
                 aliases: dict[str, str] | None = None) -> dict[str, str]:
    """`config/tag_broader.json` → {좁은 태그의 fold: 넓은 태그 표시 이름}.

    표에 적힌 넓은 태그도 통일표를 거친다 — 'Gemini' 라고 적어도 대표 표기
    '제미나이' 로 붙어야 색인이 둘로 갈리지 않는다(`backfill_from_titles` 와 같은
    이유다).

    표가 없어도 돌아간다. 그때는 글자가 겹치는 승격만 남는다.
    """
    p = path or BROADER_PATH
    if not p.exists():
        return {}
    aliases = aliases if aliases is not None else load_aliases()
    raw = json.loads(p.read_text(encoding="utf-8")).get("broader") or {}
    out: dict[str, str] = {}
    for broad, narrows in raw.items():
        broad = (broad or "").strip()
        if not broad:
            continue
        name = aliases.get(fold(broad), broad)
        for n in narrows or []:
            key = fold(n)
            # 자기 자신을 부모로 적은 줄은 버린다 — 무한히 돌지는 않지만(방문
            # 표시가 있다) 표를 읽는 사람을 헷갈리게 한다.
            if key and key != fold(name):
                out[key] = name
    return out


def _parent_lookup(threads: list[dict], participants: dict | None = None,
                   broader: dict[str, str] | None = None,
                   min_count: int = 2, min_len: int = 3):
    """태그 → 바로 위 태그들을 돌려주는 함수를 만든다.

    두 갈래를 한 자리에서 합친다. `rollup_parent_tags`(붙이는 쪽)와
    `broader_candidates`(못 붙은 것을 알리는 쪽)가 같은 판정을 봐야 하므로
    이 함수 하나만 둔다 — 갈라지면 '후보로 알려 준 태그가 실은 이미 붙어 있는'
    꼴이 된다.
    """
    counts: Counter[str] = Counter(
        t for th in threads for t in (th.get("tags") or []))
    people = person_names(participants or {})
    broader = broader if broader is not None else load_broader()

    base = [t for t, n in counts.items()
            if n >= min_count and len(fold(t)) >= min_len and t not in people]
    keys = {t: fold(t) for t in base}

    def parents(tag: str) -> list[str]:
        out: list[str] = []
        # 표가 먼저다. 사람이 적은 것이고, `min_count` 같은 방벽을 받지 않는다 —
        # 아직 한 번도 안 쓰인 넓은 태그를 새로 세우는 것이 이 표의 몫이다.
        named = broader.get(fold(tag))
        if named and named != tag and named not in people:
            out.append(named)
        ft = fold(tag)
        for b in base:
            if keys[b] != ft and keys[b] in ft and b not in out:
                out.append(b)
        return out

    return parents


def place_candidates(threads: list[dict], places: set[str] | None = None,
                     not_places: set[str] | None = None) -> list[tuple[str, int]]:
    """표에 아직 없는 지명·조직 이름 후보. (태그, 쓰인 횟수) 를 많은 순으로.

    사람이 훑어보고 `places`(뺄 것) 또는 `not_places`(주제로 남길 것)로 옮기면
    다음부터 후보에 안 나온다. 한 번 판단한 것을 또 묻지 않는 것이 요점이다.
    """
    places = places or set()
    not_places = not_places or set()
    counts: Counter[str] = Counter(
        t for th in threads for t in (th.get("tags") or th.get("keywords") or []))
    rows = []
    for tag, n in counts.items():
        key = fold(tag)
        if key in places or key in not_places:
            continue
        s = (tag or "").strip()
        if any(s.endswith(sfx) and len(s) > len(sfx) for sfx in ORG_SUFFIXES):
            rows.append((tag, n))
    rows.sort(key=lambda r: (-r[1], r[0]))
    return rows


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
                       min_count: int = 2, min_len: int = 3,
                       broader: dict[str, str] | None = None
                       ) -> list[tuple[str, str]]:
    """좁은 태그에 넓은 태그를 덧붙인다. 붙인 (주제 id, 태그) 목록.

    'MS 온톨로지 플레이그라운드' 주제의 태그는 '온톨로지 모델링'인데 앞서 쌓인
    '온톨로지' 3건과 만나지 못했다 — 표기 통일은 공백·대소문자만 보므로
    '온톨로지모델링' 과 '온톨로지' 는 남남이다. 그래서 태그 하나짜리 고립 주제가
    된다(실측: 1,047개 태그가 1건뿐이다).

    좁은 태그를 넓은 태그로 **바꾸지** 않고 넓은 태그를 **덧붙인다**. '온톨로지
    모델링'의 정확함을 잃지 않으면서 '온톨로지'로도 찾힌다.

    부모는 두 갈래에서 온다.

    1. 글자가 겹치는 것 — 기계가 찾는다. 여기에는 방벽이 둘 있다. 부모는
       `min_count` 건 이상 쓰인 태그만(한 번 쓰인 말이 부모가 되면 아무 말이나
       부모가 된다), 그리고 fold 길이 `min_len` 이상('AI'·'앱' 이 온 태그의
       부모가 되는 것을 막는다).
    2. 글자가 겹치지 않는 것 — `config/tag_broader.json` 표. 이쪽은 원리적으로
       기계가 못 한다. '앱스스크립트' 가 '구글 워크스페이스' 에 든다는 것도,
       'AWS' 가 '클라우드' 라는 것도 글자에 단서가 없다(실측 2026-08-12:
       부모를 못 얻은 1회짜리 태그가 843개다).

    부모의 부모까지 올라간다. 표와 글자 판정이 섞여도 이어진다 — 'Gemma 3 27B'
    는 표로 'AI 모델'에 닿고, '클라우드' 는 표로 '인프라'에 닿는다.

    사람 이름은 부모로 쓰지 않는다. 이름 태그는 참여자 화면 몫이고(`person`),
    '김종원' 이 '김종원 수정판'을 빨아들여도 얻는 것이 없다.
    """
    parents = _parent_lookup(threads, participants, broader, min_count, min_len)

    added: list[tuple[str, str]] = []
    for th in threads:
        own = list(th.get("tags") or [])
        have = set(own)
        # 넓힌 태그에서 또 넓힐 수 있으므로 훑으며 늘려 간다. `seen` 이 있어
        # 표가 돌아가게(A→B→A) 적혀 있어도 멈춘다.
        queue, seen = list(own), set(own)
        while queue:
            tag = queue.pop(0)
            for p in parents(tag):
                if p in seen:
                    continue
                seen.add(p)
                queue.append(p)
                if p not in have:
                    th.setdefault("tags", []).append(p)
                    have.add(p)
                    added.append((th["id"], p))
    return added


def broader_candidates(threads: list[dict], broader: dict[str, str] | None = None,
                       participants: dict | None = None,
                       places: set[str] | None = None,
                       min_count: int = 2, min_len: int = 3
                       ) -> list[tuple[str, int]]:
    """부모를 하나도 못 얻은 고립 태그. (태그, 쓰인 횟수) 를 많은 순으로.

    `min_count` 미만으로 쓰인 태그는 태그 색인 목록에 나오지 않는다
    (`build_tag_index`). 부모까지 없으면 그 주제로 가는 입구가 검색 말고는 없다 —
    사실상 안 보이는 태그다. 그 목록을 보여 주면 `config/tag_broader.json` 에
    무엇을 적을지가 정해진다.

    `place_candidates` 와 같은 방식이다: 기계는 후보만 내놓고 판단은 표로 간다.
    한 번 표에 적은 것은 부모를 얻으므로 다음부터 후보에 안 나온다.

    **승격 전에** 불러야 한다 — `rollup_parent_tags` 가 부모를 붙인 뒤에는
    무엇이 고립이었는지 알 수 없다.
    """
    parents = _parent_lookup(threads, participants, broader, min_count, min_len)
    people = person_names(participants or {})
    places = places or set()
    counts: Counter[str] = Counter(
        t for th in threads for t in (th.get("tags") or []))

    rows = [(t, n) for t, n in counts.items()
            if n < min_count and t not in people and fold(t) not in places
            and not parents(t)]
    rows.sort(key=lambda r: (-r[1], r[0]))
    return rows


def vocabulary(threads: list[dict], participants: dict | None = None,
               places: set[str] | None = None, min_count: int = 2,
               limit: int = 180) -> list[tuple[str, int]]:
    """보고서를 쓸 때 '여기서 고르라' 고 보여줄 공통 태그. (표시 이름, 횟수).

    태그가 1,224종인데 1,090종이 한 번만 쓰였다(실측 2026-08-04). 뿌리는 표기
    차이가 아니라 **보고서마다 태그를 새로 지어낸 것**이다 — 공통 어휘가 없으면
    같은 이야기가 매번 다른 말로 붙고, 태그로 찾으면 절반만 나온다.

    사후 봉합(표기 통일·승격)으로는 1회짜리의 약 10%만 구제된다는 것을 실측했다.
    그래서 만들 때 고르게 한다. 이미 두 번 이상 쓰인 말만 보여주는 것이 요점이다 —
    한 번 쓰인 말까지 보여주면 그 목록이 곧 지어낸 말들의 목록이 된다.

    사람 이름·지명은 넣지 않는다. 태그 구름에서 빼는 것과 같은 이유이고, 어휘로
    보여주면 다음 보고서가 그 이름을 또 태그로 쓴다.

    `config/tag_broader.json` 의 **넓은 태그는 횟수와 무관하게 넣고 잘라내지도
    않는다.** 사람이 '이것이 이 방의 공통 어휘다' 라고 적어 둔 말이고, 고르게 하려고
    적은 것이다. 승격(`rollup_parent_tags`)은 이미 붙은 태그를 사후에 넓히는 것뿐이라
    보고서가 처음부터 넓은 말을 고르게 하지는 못한다 — 그 몫이 여기다.
    """
    people = person_names(participants or {})
    places = places or set()
    raw = [t for th in threads for t in (th.get("keywords") or [])]
    tag_map = build_tag_map(raw)
    counts: Counter[str] = Counter()
    for th in threads:
        for name in canonical_tags(th.get("keywords") or [], tag_map):
            counts[name] += 1

    def keeps(name: str) -> bool:
        return name not in people and fold(name) not in places

    rows = [(name, n) for name, n in counts.items()
            if n >= min_count and keeps(name)]
    rows.sort(key=lambda r: (-r[1], r[0]))
    rows = rows[:limit]

    have = {fold(name) for name, _ in rows}
    extra = [(b, counts.get(b, 0)) for b in sorted(set(load_broader().values()))
             if fold(b) not in have and keeps(b)]
    return rows + extra


def build_tag_index(threads: list[dict], participants: dict | None = None,
                    min_count: int = 2, places: set[str] | None = None) -> dict:
    """태그 입구용 색인.

    `min_count` 미만으로 쓰인 태그는 목록에서 빼고 수만 센다 — 314개 주제에
    한 번만 쓰인 태그가 850개다. 다 늘어놓으면 목록이 아니라 벽이 된다
    (검색으로는 여전히 찾을 수 있다).

    지명·조직 이름은 `place` 로 표시한다. 사람 이름(`person`)과 같은 몫이다 —
    '어디서 열렸나'는 보고서 본문이 말하고, 태그 구름은 무엇을 이야기했나를 위한
    자리다. 표시만 하므로 검색으로는 그대로 찾힌다.
    """
    people = person_names(participants or {})
    places = places or set()
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
            "place": fold(name) in places,
            "thread_ids": threads_of[name],
        })
    rows.sort(key=lambda r: (-r["count"], r["tag"]))
    return {
        "tags": rows,
        "min_count": min_count,
        "total_tags": len(counts),
        "hidden_tags": sum(1 for n in counts.values() if n < min_count),
    }
