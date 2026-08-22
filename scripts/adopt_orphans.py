# -*- coding: utf-8 -*-
"""부모 없는 태그에 부모를 붙인다 — `config/tag_broader.json` 만 고친다.

왜 이 파일이 있나
    `build_site` 가 매 실행마다 같은 말을 한다: "부모도 없고 한 번만 쓰인 태그
    171개 — 검색 말고는 입구가 없습니다." 한 번만 쓰인 태그는 태그 목록에 나오지
    않고(`build_tag_index` 의 `min_count`), 부모까지 없으면 그 주제로 가는 길이
    검색뿐이다. 사실상 안 보이는 태그다.

    `broader_candidates` 가 목록은 내주지만 무엇의 자식인지는 사람 판단이다.
    'ESP32-S3-ETH + PoE' 가 인프라라는 것도, 'BE:PEOPLE' 이 당사자 지원 앱이라는
    것도 글자에 단서가 없다. 그래서 판단만 맡기고 표에 적는다.

    보고서는 한 글자도 안 고친다. 태그를 옮기는 것이 아니라 **넓은 태그를 덧붙이는**
    길을 표에 여는 것이다(`rollup_parent_tags`). 되돌리려면 표에서 그 줄을 지우면
    되고, 표는 git 이 추적한다.

부모는 이미 있는 것에서만 고른다
    새 넓은 태그를 만들지 않는다. 부모를 새로 지어내면 그 부모가 또 1회짜리가 되고,
    같은 빚을 한 층 위에서 다시 진다. 고를 수 있는 것은 표의 부모, 표의 갈래
    (`split_hints` 로 세운 것), 그리고 `short_parents` 다.

    **갈래를 부모로 줄 때는 그 태그가 '우리가 만든 것' 인지 봐야 한다.** 갈래는
    '앱 제작' 의 자식이라 위로 이어진다 — 남이 만든 사이트·플랫폼(레딧·connect.or.kr·
    aiforwelfare)이나 개념(관찰기록·채용 추천·홈페이지 통합)에 갈래를 붙이면 초대·
    모집·논문 대화가 '앱 제작' 으로 끌려간다. 실측 2026-08-21: 그렇게 24편이 새로
    들어왔고 여섯이 잘못이었다. 붙인 뒤 넓은 태그의 편수가 얼마나 늘었는지 보고,
    새로 들어온 편이 정말 그 이야기인지 확인해야 한다.

서식을 지킨다
    이 파일은 사람이 한 줄에 여러 개씩 적어 손으로 다듬은 것이다. json.dumps 로
    통째로 다시 쓰면 한 줄씩 펼쳐져 diff 가 158줄이 된다(실측 2026-08-21: 실제로
    그렇게 뭉갰다). 그래서 **바뀌는 배열만** 제자리에서 다시 쓴다. 아무것도 안
    바뀌면 파일은 한 바이트도 안 바뀐다.

사용
    python -m scripts.adopt_orphans                # 제안만 만든다
    python -m scripts.adopt_orphans --apply        # 표에 적는다 (호출 없음)
    python -m scripts.adopt_orphans --stats        # 고립 태그만 센다 (호출 없음)
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from scripts import tags as taglib
from scripts.llm import DEFAULT_MODEL, call_claude, parse_reply
from scripts.tag_surgery import shown
from scripts.topic_reports import apply_reports, load_reports

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
BROADER = ROOT / "config" / "tag_broader.json"
PROPOSAL = OUT / "adopt-proposal.json"

BATCH = 60          # 답이 한 줄씩(부모 이름)이라 가볍다
TIMEOUT_SEC = 300
NONE = "없음"

# 배열을 한 줄로 둘 수 있는 길이의 끝. 이 파일의 손 서식을 흉내낸다.
INLINE_MAX = 92
WRAP_AT = 84


# ---------------------------------------------------------------- 읽기

def orphan_tags() -> list[tuple[str, int]]:
    """`build_site` 가 세는 것과 같은 고립 태그 목록.

    같은 순서로 같은 것을 거쳐야 한다 — 제목에서 채우는 몫(`backfill_from_titles`)을
    빼먹으면 이미 부모를 얻은 태그가 고립으로 보인다.
    """
    topics = json.loads((OUT / "topics.json").read_text(encoding="utf-8"))
    parts = json.loads((OUT / "participants.json").read_text(encoding="utf-8"))
    threads = [dict(t) for t in topics["threads"]]
    apply_reports(threads, load_reports())
    taglib.attach_tags(threads, parts)
    knowledge = json.loads((OUT / "knowledge.json").read_text(encoding="utf-8"))
    labels = [n["label"] for n in knowledge.get("nodes", [])
              if n.get("type") in ("app", "tool") and n.get("label")]
    taglib.backfill_from_titles(threads, labels)
    places, _ = taglib.load_places()
    return taglib.broader_candidates(
        threads, taglib.load_broader(), parts, places,
        short_parents=taglib.load_short_parents())


def parent_choices(path: Path | None = None) -> list[str]:
    """부모로 고를 수 있는 넓은 태그. 이미 표에 있는 것뿐이다."""
    raw = json.loads((path or BROADER).read_text(encoding="utf-8"))
    broader = raw.get("broader") or {}
    out = list(broader)
    for kinds in (raw.get("split_hints") or {}).values():
        out += [k for k in kinds if k not in out]
    out += [s for s in (raw.get("short_parents") or []) if s not in out]
    return out


# ---------------------------------------------------------------- 프롬프트

def build_prompt(orphans: list[tuple[str, int]], parents: list[str]) -> str:
    rows = "\n".join("- %s" % p for p in parents)
    tags = "\n".join("- %s" % t for t, _ in orphans)
    return f"""아래 태그들은 딱 한 번만 쓰였고 부모가 없습니다. 태그 목록에 나오지 않고
부모도 없으니, 그 주제로 가는 길이 검색뿐입니다. 사실상 안 보이는 태그입니다.

각 태그에 **넓은 태그 하나**를 붙여 주세요. 좁은 태그를 바꾸는 것이 아니라, 넓은
태그로도 찾히게 하는 것입니다 — 'Table_Cleaner' 의 정확함을 잃지 않으면서
'문서 처리 도구' 로도 찾히게 됩니다.

### 고를 수 있는 넓은 태그 (이 중에서만)
{rows}
- **{NONE}** — 위 어디에도 안 맞을 때. 억지로 넣지 마세요.

### 어떻게 고르나
- **그 말이 무엇의 한 종류인가**로 고르세요. 'ESP32-S3-ETH + PoE' 는 인프라의
  한 종류, 'BE:PEOPLE' 은 당사자 지원 앱의 한 종류입니다.
- 목록에 없는 넓은 태그를 **새로 만들지 마세요.** 새 부모를 지어내면 그 부모가 또
  한 번짜리가 되어, 같은 문제를 한 층 위에서 다시 만듭니다.
- 여러 곳에 걸치면 **더 좁은 쪽**을 고르세요. '당사자 지원 앱' 과 '앱 제작' 중에는
  '당사자 지원 앱' 입니다(그쪽이 앱 제작의 자식이라 위로도 이어집니다).
- 사람 이름·기관 이름·지명은 **{NONE}** 으로 두세요. 그건 태그 구름의 자리가 아닙니다.
- 잘 모르면 {NONE} 입니다. 틀린 부모는 없는 부모보다 나쁩니다 — 넓은 태그를 눌렀을 때
  관계없는 주제가 섞입니다.

### 부모를 붙일 태그
{tags}

답은 JSON 만. 다른 말은 붙이지 마세요. 열쇠는 태그, 값은 넓은 태그 하나입니다.
{len(orphans)}개 전부에 답해야 합니다.

{{"Table_Cleaner": "문서 처리 도구", "구현종": "{NONE}"}}"""


def ask(orphans: list[tuple[str, int]], parents: list[str], model: str,
        batch_size: int, timeout: int) -> dict[str, str]:
    out: dict[str, str] = {}
    total = (len(orphans) + batch_size - 1) // batch_size
    for n in range(total):
        chunk = orphans[n * batch_size:(n + 1) * batch_size]
        print("배치 %d/%d — 태그 %d개" % (n + 1, total, len(chunk)))
        reply = parse_reply(
            call_claude(build_prompt(chunk, parents), model, timeout, "부모 붙이기")
            or "")
        if not reply:
            print("  답을 받지 못해 이 배치는 건너뜁니다.")
            continue
        for tag, _ in chunk:
            if tag in reply and isinstance(reply[tag], str):
                out[tag] = reply[tag]
    return out


def screen(answers: dict[str, str], parents: list[str]) -> dict[str, list[str]]:
    """답을 부모 목록에 맞춰 걸러 {부모: [자식…]} 으로 모은다."""
    by_key = {taglib.fold(p): p for p in parents}
    out: dict[str, list[str]] = collections.defaultdict(list)
    for tag in sorted(answers):
        raw = (answers[tag] or "").strip()
        if not raw or taglib.fold(raw) == taglib.fold(NONE):
            continue
        parent = by_key.get(taglib.fold(raw))
        if not parent:
            print("  목록에 없는 부모 '%s' (%s) — 버립니다" % (raw, tag))
            continue
        if taglib.fold(parent) == taglib.fold(tag):
            continue
        out[parent].append(tag)
    return dict(out)


def kind_conflicts(additions: dict[str, list[str]], path: Path | None = None
                   ) -> list[tuple[str, str, str, str]]:
    """부모가 그 태그의 보고서가 이미 받은 갈래와 어긋나는 것. (보고서, 태그, 부모, 갈래)

    기계로 걸러낼 수 있는 유일한 어긋남이다. 'care-insight' 에 '업무 앱' 을 붙였는데
    그 태그가 붙은 t-074 는 이미 '실천 도구' 를 받았다면, 둘 중 하나가 틀린 것이다 —
    같은 것을 두 갈래로 부르는 셈이고, 넓은 태그를 눌렀을 때 관계없는 주제가 섞인다.

    실측 2026-08-21: 132개 중 9개가 여기 걸렸고 6개는 보고서 갈래가 옳았다. 나머지
    셋 중 둘은 부모를 버렸고('TMAP API' — API 는 만드는 사람의 작업환경이 아니다),
    하나는 둘 다 참이라 두었다('지하철 척척박사' 는 게임이면서 당사자용이다).

    고치지는 않는다. 어느 쪽이 옳은지는 보고서를 읽어야 아는 판단이다.
    """
    raw = json.loads((path or BROADER).read_text(encoding="utf-8"))
    kinds = {k for kk in (raw.get("split_hints") or {}).values() for k in kk}
    parent_of = {taglib.fold(c): p for p, cs in additions.items() for c in cs}
    out = []
    for tid, rep in sorted(load_reports().items()):
        own = [k for k in rep["keywords"] if k in kinds]
        if not own:
            continue
        for tag in rep["keywords"]:
            parent = parent_of.get(taglib.fold(tag))
            if parent in kinds and parent not in own:
                out.append((tid, tag, parent, own[0]))
    return out


# ---------------------------------------------------------------- 표에 쓰기

def render_array(key: str, items: list[str], indent: str) -> str:
    """이 파일의 손 서식대로 배열 한 줄(또는 여러 줄)을 만든다."""
    body = ", ".join(json.dumps(i, ensure_ascii=False) for i in items)
    one = '%s"%s": [%s]' % (indent, key, body)
    if len(one) <= INLINE_MAX:
        return "[%s]" % body
    inner = indent + "  "
    lines, cur = [], inner
    for i, item in enumerate(items):
        piece = json.dumps(item, ensure_ascii=False) + ("," if i < len(items) - 1 else "")
        if cur != inner and len(cur) + 1 + len(piece) > WRAP_AT:
            lines.append(cur)
            cur = inner
        cur += (" " if cur != inner else "") + piece
    lines.append(cur)
    return "[\n" + "\n".join(lines) + "\n" + indent + "]"


def add_children(text: str, additions: dict[str, list[str]]) -> tuple[str, list[str]]:
    """바뀌는 배열만 제자리에서 다시 쓴다. (새 본문, 새로 만든 부모 목록)

    통째로 다시 쓰지 않는 이유가 이 함수의 존재 이유다 — 이 파일은 사람이 한 줄에
    여러 개씩 적어 다듬은 것이고, json.dumps 로 되쓰면 diff 가 파일 전체로 번진다.
    """
    fresh: list[str] = []
    for parent, kids in additions.items():
        pat = re.compile(
            r'(\n([ \t]*)%s\s*:\s*)(\[[^\]]*\])' % re.escape(json.dumps(parent, ensure_ascii=False)))
        m = pat.search(text)
        if m:
            have = json.loads(m.group(3))
            keys = {taglib.fold(h) for h in have}
            merged = have + [k for k in kids if taglib.fold(k) not in keys]
            if merged == have:
                continue
            text = (text[:m.start(3)]
                    + render_array(parent, merged, m.group(2))
                    + text[m.end(3):])
            continue
        # 표에 없던 부모 — broader 의 맨 끝에 새로 만든다.
        tail = re.search(r'(\n(\s*)"[^"]+"\s*:\s*(?:\[[^\]]*\]|\{[^{}]*\}))(\s*\n\s*\}\s*\n\s*\}\s*)\Z',
                         text)
        if not tail:
            raise ValueError("broader 의 끝을 찾지 못했습니다 — 손으로 넣으세요")
        indent = tail.group(2)
        block = '%s"%s": %s' % (indent, parent, render_array(parent, kids, indent))
        text = text[:tail.end(1)] + ",\n" + block + text[tail.end(1):]
        fresh.append(parent)
    return text, fresh


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description="부모 없는 태그에 부모를 붙인다")
    ap.add_argument("--apply", action="store_true", help="표에 적는다 (호출 없음)")
    ap.add_argument("--stats", action="store_true", help="고립 태그만 센다 (호출 없음)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--batch", type=int, default=BATCH)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--timeout", type=int, default=TIMEOUT_SEC)
    ap.add_argument("--proposal", type=Path, default=PROPOSAL)
    args = ap.parse_args()

    if args.apply:
        if not args.proposal.is_file():
            print("제안 파일이 없습니다: %s" % shown(args.proposal))
            return 1
        proposal = json.loads(args.proposal.read_text(encoding="utf-8"))
        additions = proposal.get("additions") or {}
        if not additions:
            print("제안에 적을 것이 없습니다.")
            return 0
        text = BROADER.read_text(encoding="utf-8", newline="")
        new_text, fresh = add_children(text, additions)
        if new_text == text:
            print("표가 이미 그렇게 되어 있습니다.")
            return 0
        json.loads(new_text)      # 깨진 JSON 을 쓰지 않는다
        BROADER.write_text(new_text, encoding="utf-8", newline="")
        total = sum(len(v) for v in additions.values())
        print("부모 %d개에 자식 %d개를 붙였습니다." % (len(additions), total))
        if fresh:
            print("  새로 만든 부모: %s" % ", ".join(fresh))
        print("\n다음: python -m scripts.build_site  → 테스트 → 발행")
        return 0

    orphans = orphan_tags()
    parents = parent_choices()
    print("고립 태그 %d개 · 고를 수 있는 넓은 태그 %d개" % (len(orphans), len(parents)))
    if args.stats:
        print("  " + " · ".join(t for t, _ in orphans))
        return 0
    if not orphans:
        print("고립 태그가 없습니다.")
        return 0
    if args.limit:
        orphans = orphans[:args.limit]
        print("  --limit %d" % args.limit)

    answers = ask(orphans, parents, args.model, args.batch, args.timeout)
    if not answers:
        print("\n답을 하나도 받지 못했습니다.")
        return 1
    additions = screen(answers, parents)
    placed = sum(len(v) for v in additions.values())
    print("\n부모를 얻는 태그 %d개 / 그대로 남는 태그 %d개"
          % (placed, len(orphans) - placed))
    for parent in sorted(additions, key=lambda p: -len(additions[p])):
        print("  %-16s %2d개  %s" % (parent, len(additions[parent]),
                                     ", ".join(additions[parent])))

    clash = kind_conflicts(additions)
    if clash:
        print("\n보고서가 이미 받은 갈래와 어긋난 부모 %d개 — 적용 전에 보세요." % len(clash))
        print("(어느 쪽이 옳은지는 보고서를 읽어야 압니다. 제안 파일을 손으로 고치세요.)")
        for tid, tag, parent, kind in clash:
            print("  %s %-28s %s → 보고서 갈래는 %s" % (tid, tag, parent, kind))

    args.proposal.parent.mkdir(parents=True, exist_ok=True)
    args.proposal.write_text(
        json.dumps({"made": datetime.now().isoformat(timespec="seconds"),
                    "model": args.model, "answers": answers,
                    "additions": additions}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print("\n제안 → %s" % shown(args.proposal))
    print("표는 아직 안 고쳤습니다. 적용:")
    print("  python -m scripts.adopt_orphans --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
