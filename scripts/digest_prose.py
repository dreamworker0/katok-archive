# -*- coding: utf-8 -*-
"""분류별 요지 산문을 다시 쓴다 — 첫 화면의 글을 사람 손에서 밤 갱신으로.

왜 이 파일이 있나
    아카이브의 첫 화면은 분류 열두 개의 요지 카드다. 그 카드의 headline·overview 는
    사람이 쓰는 글로 남겨 두었고(`docs/AUTOMATION.md` 가 '자동 아님' 으로 적어 둔
    자리), 그래서 **2026-07-28 에 멈췄다.** 그 뒤 주제가 59개 늘었고(+17%) 가장
    활발했던 8월이 통째로 첫 화면에서 빠졌다(실측 2026-09-04).

    분류·태그·보조 분류·AI 주석은 전부 밤마다 자동인데 요지만 예외였다. 구조가
    나쁜 것이 아니라 **갱신 체계가 없던 것**이 문제다.

낡은 것만 다시 쓴다
    매일 열두 편을 다시 쓰면 하룻밤에 $8~12 이 들고, 대개는 어제와 같은 글이 나온다.
    그래서 '낡음' 을 데이터로 정의한다(`topic_reports.DIGEST_STALE_*`): 정리한 뒤
    주제가 몇 개 쌓였나, 또는 며칠이 지났고 새 주제가 있나. 정리 시점은
    `as_of` 로 남기고 화면에도 보인다 — 낡음이 사람 눈에 보이면 사람이 안다.

    하룻밤 상한(`--limit`, 기본 3)이 있다. 열두 편이 한꺼번에 낡는 날(오늘이 그렇다)
    밤 갱신이 열두 번 부르지 않게 한다.

규칙 원본은 한 곳
    `topic_reports.DIGEST_RULES` 다. 프롬프트가 그것을 그대로 싣고 `validate` 가 같은
    상수를 본다. 규칙 글의 숫자는 상수에서 f-string 으로 받는다 — 글과 검사가 다른
    숫자를 보면 규칙이 취향이 된다.

무엇을 고치고 무엇을 안 고치는가
    고침    output/topic-digests.json 의 `digests[분류]` — 다시 쓴 분류만
    안 고침 원장(topics.json)·보고서·태그. 이 스크립트는 **읽기만** 한다

    실패하면 그 분류를 건너뛰고 옛 글을 남긴다. LLM 실패는 예상된 결과이고
    (`scripts/llm.py`), 요지 한 편을 못 써서 그날 밤 갱신이 멈춰서는 안 된다.

사용
    python -m scripts.digest_prose                     # 낡은 것만, 최대 3편
    python -m scripts.digest_prose --all               # 열두 편 전부
    python -m scripts.digest_prose --cat projects
    python -m scripts.digest_prose --dry-run           # 프롬프트만 (호출 없음)
    python -m scripts.digest_prose --all --model fable # 아카이브 전체를 요약하는 글
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

from scripts import jsonio
from scripts import ontology
from scripts import tags as taglib
from scripts.llm import DEFAULT_MODEL, TIMEOUT_SEC, call_claude, parse_reply
from scripts.tag_surgery import backup_dir, shown
from scripts.topic_reports import (
    DIGEST_HEADLINE_MAX,
    DIGEST_KEYWORDS,
    DIGEST_OVERVIEW_MAX,
    DIGEST_RULES,
    DIGEST_SECTION_FROM,
    DIGEST_STALE_DAYS,
    DIGEST_STALE_THREADS,
    load_reports,
)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
TOPICS = OUT / "topics.json"
MESSAGES = OUT / "messages.jsonl"
PARTICIPANTS = OUT / "participants.json"
SECONDARY = OUT / "secondary_categories.json"
DIGESTS = OUT / "topic-digests.json"

# 한 번의 밤 갱신에 다시 쓸 편 수. 열두 편이 한꺼번에 낡아도 하룻밤에 세 편이면
# 나흘에 한 바퀴다 — 첫 화면이 나흘 안에 따라잡는다.
NIGHTLY_LIMIT = 3


# ------------------------------------------------------------------ 낡음 판정

def select_stale(categories: list[dict], threads: list[dict], prose: dict,
                 today: date | None = None) -> list[str]:
    """다시 쓸 분류 id. 주제가 많이 쌓인 분류를 먼저 돌려준다.

    두 기준을 **또는** 으로 본다.

      · 정리 뒤 주제가 `DIGEST_STALE_THREADS` 개 이상 늘었다 — 내용이 바뀐 것
      · `DIGEST_STALE_DAYS` 일이 지났고 새 주제가 하나라도 있다 — 오래된 것

    두 번째 기준에 '새 주제가 하나라도' 를 붙인 이유: 조용한 분류(hwp 12개)는
    한 달이 지나도 쓸 말이 그대로다. 그것을 다시 쓰면 같은 글에 값을 치른다.

    `as_of` 가 없는 분류는 낡은 것으로 본다. 언제 쓴 글인지 모르면 낡았는지도 알
    수 없고, 모르는 것을 새것으로 치는 편이 위험하다(실측 2026-09-04: 열두 편
    전부가 `as_of` 없이 다섯 주 묵어 있었다).
    """
    today = today or date.today()
    counts: dict[str, int] = {}
    for t in threads:
        counts[t.get("category") or ""] = counts.get(t.get("category") or "", 0) + 1

    rows: list[tuple[int, str]] = []
    for c in categories:
        cid = c["id"]
        now = counts.get(cid, 0)
        if not now:
            # 소속 주제가 없는 분류는 쓸 재료가 없다. 낡음을 물을 일이 아니다 —
            # 주제 0개로 부르면 모델이 지어내는 수밖에 없다.
            continue
        p = prose.get(cid) or {}
        as_of = p.get("as_of") or {}
        if not p.get("overview") or not as_of.get("date"):
            rows.append((now, cid))
            continue
        grown = now - int(as_of.get("thread_count") or 0)
        if grown >= DIGEST_STALE_THREADS:
            rows.append((grown, cid))
            continue
        try:
            age = (today - date.fromisoformat(str(as_of["date"]))).days
        except ValueError:
            rows.append((now, cid))
            continue
        if age >= DIGEST_STALE_DAYS and grown > 0:
            rows.append((grown, cid))
    rows.sort(key=lambda r: (-r[0], r[1]))
    return [cid for _, cid in rows]


# -------------------------------------------------------------------- 프롬프트

def build_digest_prompt(cat: dict, threads: list[dict], reports: dict[str, dict],
                        facets: dict[str, str], vocabulary: list[str],
                        categories: list[dict] | None = None,
                        also_titles: list[str] | None = None,
                        dates: dict[str, str] | None = None) -> str:
    """무엇을 싣고 무엇을 안 싣는가가 이 함수의 판단이다.

    싣는 것    분류 라벨 열두 개 전체(이 분류의 자리를 알게), 소속 주제 전부의
              id·날짜·제목·요지·태그·갈래, 각 보고서 본문, 보조 분류로 걸린 곁
              주제의 **제목만**, 갈래 이름과 설명, 고를 수 있는 태그, 규칙.
    안 싣는 것 **원문 메시지.** 이 글은 보고서의 요약이고 보고서가 이미 원문의
              요약이다. 원문을 실으면 요지가 원문을 다시 요약하게 되고, 그러면
              보고서가 고른 것과 요지가 고른 것이 어긋난다.

    곁 주제를 제목만 싣는 이유: 보조 분류는 '여기서도 볼 만한 주제' 라 이 분류가
    무엇을 이야기하는 방인지 알려 주지만, 본문에 쓰면 다른 분류의 내용이 이 요지에
    실린다. 그래서 참고용이라고 못박는다.

    projects 는 보고서 106편 ≈ 52KB 로 한 호출에 들어간다(실측 2026-09-04).
    들어가지 않는 분류가 생기면 부르는 쪽이 보고서를 요지 한 줄로 대신한다.
    """
    dates = dates or {}
    cat_lines = "\n".join(
        "  %s%-16s %s" % ("→ " if c["id"] == cat["id"] else "  ", c["id"], c["label"])
        for c in (categories or [cat]))

    facet_lines = "\n".join(
        "- **%s** — %s" % (name, hint) if hint else "- **%s**" % name
        for name, hint in (facets or {}).items())
    facet_block = (
        f"""### 절로 쓸 갈래 (이 분류에는 갈래가 있습니다)
아래 이름을 **그대로** 절 제목으로 쓰세요. 주제마다 어느 갈래인지 아래 목록의
`갈래:` 에 적혀 있습니다. 갈래를 못 받은 주제는 '그 밖' 입니다.

{facet_lines}
"""
        if facets else
        """### 절 (이 분류에는 갈래가 없습니다)
시기나 화두로 나누고, 제목은 짧게 지으세요.
""")

    blocks = []
    for t in threads:
        r = reports.get(t["id"]) or {}
        body = r.get("report") or t.get("report") or ""
        blocks.append(
            "#### %s  %s  대화 %d건\n제목: %s\n요지: %s\n태그: %s\n갈래: %s\n%s"
            % (t["id"], dates.get(t["id"], ""),
               t.get("count") or len(t.get("message_ids") or []),
               r.get("title") or t.get("title") or "",
               r.get("summary") or t.get("summary") or "",
               ", ".join(t.get("tags") or r.get("keywords") or []) or "(없음)",
               t.get("facet") or "그 밖",
               body or "(보고서 없음)")
        )
    thread_block = "\n\n".join(blocks)

    side = ("\n".join("- %s" % s for s in also_titles[:30])
            if also_titles else "  (없음)")

    return f"""사회복지 종사자들의 AI 활용 카카오톡 아카이브다. 분류마다 **요지 산문** 한 편이
있고, 그것이 이 아카이브의 첫 화면이다. '{cat["label"]}' 분류의 요지를 다시 쓴다.

### 이 분류의 자리 (화살표가 지금 쓸 분류)
{cat_lines}

{facet_block}
### 규칙
{DIGEST_RULES}

### 고를 수 있는 말 (keywords 는 여기서만)
{" · ".join(vocabulary) or "(없음)"}

### 곁 주제 — 보조 분류로 여기 걸린 것들의 제목 (참고만. 본문에 쓰지 마세요)
{side}

### 소속 주제 {len(threads)}개와 그 보고서
{thread_block}

### 답
JSON 만. 설명·코드펜스 없이.

{{"headline": "...",
 "overview": "...",
 "sections": [{{"title": "업무 앱", "body": "..."}}],
 "keywords": ["...", "..."]}}"""


# -------------------------------------------------------------------- 걸러내기

def validate(obj, vocabulary: list[str], thread_count: int
             ) -> tuple[dict | None, list[str]]:
    """(쓸 수 있는 글, 어긴 것들). 어긴 것이 있으면 첫 값은 None.

    어긴 편은 **그 분류만 버리고 옛 글을 남긴다.** 보고서에서 규칙 미달을 다루는
    방식과 같다 — 낡은 글이 규칙을 어긴 글보다 낫고, 다음 실행이 다시 쓴다.

    keywords 는 다르다. 어휘 밖 하나 때문에 편 전체를 버리면 나머지 일곱 개를
    함께 잃는다. 그래서 어휘 밖은 **버리고 나아간다**(발행에서도 이어지지 않는
    태그를 화면에서 빼는 것과 같은 판단, `build_site.build_digests`).
    """
    bad: list[str] = []
    if not isinstance(obj, dict):
        return None, ["JSON 이 아니다"]

    headline = str(obj.get("headline") or "").strip()
    overview = str(obj.get("overview") or "").strip()
    if not headline:
        bad.append("headline 이 없다")
    elif len(headline) > DIGEST_HEADLINE_MAX:
        bad.append("headline %d자 > %d자" % (len(headline), DIGEST_HEADLINE_MAX))
    if not overview:
        bad.append("overview 가 없다")
    elif len(overview) > DIGEST_OVERVIEW_MAX:
        bad.append("overview %d자 > %d자" % (len(overview), DIGEST_OVERVIEW_MAX))

    sections = []
    for s in obj.get("sections") or []:
        if not isinstance(s, dict):
            continue
        title = str(s.get("title") or "").strip()
        body = str(s.get("body") or "").strip()
        if title and body:
            sections.append({"title": title, "body": body})
    if thread_count >= DIGEST_SECTION_FROM and not sections:
        bad.append("주제 %d개(%d개 이상)인데 절이 없다"
                   % (thread_count, DIGEST_SECTION_FROM))

    keys = {taglib.fold(v) for v in vocabulary}
    keywords, outside, seen = [], [], set()
    for k in obj.get("keywords") or []:
        name = str(k or "").strip()
        if not name or taglib.fold(name) in seen:
            continue
        seen.add(taglib.fold(name))
        (keywords if not keys or taglib.fold(name) in keys else outside).append(name)
    keywords = keywords[:DIGEST_KEYWORDS[1]]
    if len(keywords) < DIGEST_KEYWORDS[0]:
        bad.append("keywords %d개 < %d개%s"
                   % (len(keywords), DIGEST_KEYWORDS[0],
                      (" (어휘 밖 버림: %s)" % ", ".join(outside)) if outside else ""))
    if bad:
        return None, bad
    if outside:
        print("  어휘 밖 keywords %d개를 버립니다: %s" % (len(outside), ", ".join(outside)))
    return {"headline": headline, "overview": overview,
            "sections": sections, "keywords": keywords}, []


# ------------------------------------------------------------------ 읽기·쓰기

def load_state() -> dict:
    """발행이 보는 것과 같은 상태를 만든다.

    태그는 `build_site.build_data` 와 같은 순서로 얹는다(보고서 → 표기 통일 →
    승격). 어휘와 갈래를 그 상태에서 재야 화면에 보이는 것과 같아진다 —
    `retag_reports.load_state` 와 같은 이유다.
    """
    topics = jsonio.read_json(TOPICS)
    threads = topics["threads"]
    reports = load_reports()
    participants = jsonio.read_json(PARTICIPANTS) if PARTICIPANTS.is_file() else {}
    places, _ = taglib.load_places()

    for th in threads:
        r = reports.get(th["id"])
        if r:
            th["keywords"] = r["keywords"]
            th["title"] = r["title"]
            th["summary"] = r["summary"]
        th["count"] = len(th.get("message_ids") or [])
    taglib.attach_tags(threads, participants)
    taglib.rollup_parent_tags(threads, participants)

    when: dict[str, str] = {}
    if MESSAGES.is_file():
        day_of = {m["id"]: m.get("date") or ""
                  for m in jsonio.read_jsonl(MESSAGES)}
        for th in threads:
            days = sorted(d for d in (day_of.get(m) for m in th["message_ids"]) if d)
            if days:
                when[th["id"]] = days[0]

    secondary = ((jsonio.read_json(SECONDARY).get("secondary") or {})
                 if SECONDARY.is_file() else {})
    prose = ((jsonio.read_json(DIGESTS).get("digests") or {})
             if DIGESTS.is_file() else {})

    return {
        "categories": topics["categories"],
        "threads": threads,
        "reports": reports,
        "dates": when,
        "secondary": secondary,
        "prose": prose,
        "vocabulary": [n for n, _ in taglib.vocabulary(threads, participants, places)],
    }


def facets_for(cid: str) -> dict[str, str]:
    """이 분류의 갈래와 설명. 갈래가 없는 분류는 빈 표."""
    parent = ontology.CATEGORY_FACETS.get(cid)
    return taglib.load_split_hints(parent) if parent else {}


def write_digests(prose: dict, changed: dict[str, dict], day: str) -> Path:
    """다시 쓴 분류만 갈아 끼우고 파일을 다시 쓴다. 쓰기 전에 백업한다.

    파일을 통째로 다시 쓰지만 손대지 않은 분류의 값은 한 글자도 안 바뀐다 —
    읽은 그대로의 객체를 그대로 다시 적는다. 열쇠 순서도 유지되므로 git diff 와
    같은 눈으로 볼 때 바뀐 분류만 보인다.
    """
    backup = backup_dir("digests", day)
    if DIGESTS.is_file():
        shutil.copy2(DIGESTS, backup / DIGESTS.name)
    doc = jsonio.read_json(DIGESTS) if DIGESTS.is_file() else {}
    digests = doc.get("digests")
    if not isinstance(digests, dict):
        digests = {}
    digests.update(changed)
    doc["digests"] = digests
    jsonio.write_json(DIGESTS, doc)
    prose.update(changed)
    return backup


def rewrite(cid: str, state: dict, model: str, timeout: int,
            dry_run: bool = False) -> dict | None:
    """한 분류의 요지를 다시 쓴다. 못 쓰면 None — 그 분류는 옛 글을 지닌다."""
    cat = next(c for c in state["categories"] if c["id"] == cid)
    facets = facets_for(cid)
    keys = taglib.facet_keys(ontology.CATEGORY_FACETS[cid], list(facets)) \
        if facets else {}
    mine = [t for t in state["threads"] if t.get("category") == cid]
    for t in mine:
        t["facet"] = taglib.facet_of(t.get("tags") or [], keys) if keys else None

    also = [t.get("title") or "" for t in state["threads"]
            if cid in (state["secondary"].get(t["id"]) or [])
            and t.get("category") != cid]

    prompt = build_digest_prompt(
        cat, mine, state["reports"], facets, state["vocabulary"],
        categories=state["categories"], also_titles=also, dates=state["dates"])
    print("  %s(%s) — 주제 %d개 · 프롬프트 %d자"
          % (cat["label"], cid, len(mine), len(prompt)))
    if dry_run:
        return None

    reply = parse_reply(call_claude(prompt, model, timeout, "요지 산문") or "")
    obj, bad = validate(reply, state["vocabulary"], len(mine))
    if not obj:
        print("  [규칙 미달] %s — %s. 옛 글을 그대로 둡니다." % (cid, " / ".join(bad)))
        return None
    obj["as_of"] = {
        "date": date.today().isoformat(),
        "thread_count": len(mine),
        "last_thread_id": mine[-1]["id"] if mine else "",
    }
    print("    headline: %s" % obj["headline"])
    if obj["sections"]:
        print("    절: %s" % " · ".join(s["title"] for s in obj["sections"]))
    return obj


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--all", action="store_true", help="낡음을 보지 않고 열두 편 전부")
    ap.add_argument("--cat", help="쉼표로 나눈 분류 id — 이것만")
    ap.add_argument("--limit", type=int, default=NIGHTLY_LIMIT,
                    help="한 번에 다시 쓸 편 수 (0=제한 없음, 기본 %d)" % NIGHTLY_LIMIT)
    ap.add_argument("--dry-run", action="store_true",
                    help="프롬프트만 만들어 보고 만다 (호출 없음)")
    ap.add_argument("--stats", action="store_true", help="낡은 분류만 센다 (호출 없음)")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--timeout", type=int, default=TIMEOUT_SEC)
    args = ap.parse_args()

    state = load_state()
    labels = {c["id"]: c["label"] for c in state["categories"]}
    valid = list(labels)

    if args.cat:
        want = [c.strip() for c in args.cat.split(",") if c.strip()]
        unknown = [c for c in want if c not in labels]
        if unknown:
            print("없는 분류: %s" % ", ".join(unknown))
            return 1
        todo = want
        print("고른 분류 %d개: %s" % (len(todo), ", ".join(todo)))
    elif args.all:
        todo = valid
        print("열두 편 전부 다시 씁니다 (%d개)." % len(todo))
    else:
        todo = select_stale(state["categories"], state["threads"], state["prose"])
        print("낡은 분류 %d/%d개: %s"
              % (len(todo), len(valid), ", ".join(todo) or "(없음)"))

    if args.limit and len(todo) > args.limit:
        print("  --limit %d — 앞에서 %d개만 봅니다(나머지는 다음 실행이 이어서)."
              % (args.limit, args.limit))
        todo = todo[:args.limit]
    if args.stats or not todo:
        return 0

    changed: dict[str, dict] = {}
    for cid in todo:
        got = rewrite(cid, state, args.model, args.timeout, args.dry_run)
        if got:
            changed[cid] = got

    if args.dry_run:
        print("\n호출하지 않았습니다. 프롬프트만 만들어 보았습니다.")
        return 0
    if not changed:
        print("\n다시 쓴 편이 없습니다 — 파일을 손대지 않습니다.")
        return 1

    backup = write_digests(state["prose"], changed, datetime.now().strftime("%Y%m%d"))
    print("\n요지 %d편을 다시 썼습니다: %s"
          % (len(changed), ", ".join(labels[c] for c in changed)))
    print("백업: %s/ (바꾸기 전 topic-digests.json)" % shown(backup))
    print("다음: python -m scripts.build_site  → 테스트 → 발행")
    return 0


if __name__ == "__main__":
    sys.exit(main())
