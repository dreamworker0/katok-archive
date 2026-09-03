# -*- coding: utf-8 -*-
"""너무 넓어진 태그를 갈래로 가른다 — 보고서의 `keywords` 한 줄만 바꾼다.

왜 이 파일이 있나
    유산 태그를 다시 고르니 태그가 뭉쳤다(1회짜리 947종 → 186종). 그런데 뭉치면
    반대쪽 문제가 생긴다 — '앱 제작' 하나에 71편이 달렸다(실측 2026-08-21).
    입구가 있어도 71개를 늘어놓으면 그 안에서 다시 헤맨다.

    넓은 태그를 없애는 것이 답은 아니다. '이 방이 앱을 만드는 이야기를 한다'는 것은
    사실이고, 그 입구는 있어야 한다. 그래서 **가른다** — 갈래를 `broader` 의 자식으로
    두면 넓은 태그를 눌렀을 때 여전히 71편이 다 나오고, 갈래 일곱 개가 새 입구로
    생긴다.

    같은 일이 또 온다. 실측 2026-08-21: 'AI 모델' 90 · '구글' 87 ·
    '구글 워크스페이스' 73 · 'AI 코딩 도구' 72. 그래서 이 태그 전용 코드로 쓰지 않고
    태그 이름을 받는다.

갈래를 어디에 적나 — `config/tag_broader.json` 한 곳
    `broader` 에 부모 → 자식으로 적고, `split_hints` 에 갈래마다 한 줄 설명을 적는다.
    설명은 프롬프트에 그대로 실린다 — 이름만으로 갈리지 않는 경계('실천 도구'와
    '업무 앱'의 차이)를 사람이 여기서 말해 준다.

    이 스크립트는 갈래를 스스로 정하지 않는다. 무엇으로 가를지는 이 방의 일을 아는
    사람의 판단이고(사회복지 쪽 축이다), 코드가 정하면 그 판단이 코드에 숨는다.

무엇을 고치고 무엇을 안 고치는가
    고침    output/reports/*.md 의 `keywords:` 줄에서 **넓은 태그를 갈래로 바꾼다**
    안 고침 본문·제목·요지, 그 밖의 모든 것

    넓은 태그를 지우고 갈래를 넣는 이유: 태그는 한 편에 6개까지고 이미 5개인 편이
    많다. 덧붙이면 넘친다. 그리고 넓은 태그는 승격(`rollup_parent_tags`)이 다시
    붙여 주므로 적어 둘 필요가 없다 — 좁게 적고 넓은 것은 승격에 맡기는 것이
    이 저장소의 방식이다.

    `scripts.retag_reports.replace_keywords_line` 을 그대로 쓴다. 이 폴더는 CRLF 고,
    줄바꿈을 건드리면 diff 가 파일 전체로 번진다. 그 함정을 두 번 구현하지 않는다.

반대쪽 일 — 갈래를 **채우는** 모드(`--fill-category`)
    가르고 나면 남는 것이 있다. projects 주제 106개 중 63개만 갈래를 얻었고 43개는
    갈래가 없다(실측 2026-09-04). 갈래로 묶어 보이는 화면과 갈래로 절을 나누는 요지
    산문은 그 43개를 '그 밖' 으로 밀어낸다 — 106개 중 43개가 '그 밖' 이면 묶은 것이
    아니다.

    그래서 같은 갈래 표·같은 프롬프트 골격으로 방향만 뒤집는다. 대상은 '그 분류에
    속하고 갈래 태그를 하나도 안 가진 주제' 이고, 넓은 태그를 갈래로 **바꾸는** 것이
    아니라 갈래를 **덧붙인다**(태그가 6개면 어휘 밖 1회짜리 하나를 갈래로 바꾼다).

    2026-08-21 의 `adopt_orphans` 사고를 되풀이하지 않는 이유가 대상에 있다. 그때는
    고립 태그에 부모를 붙였더니 초대·논문 대화가 '앱 제작' 으로 끌려왔다 — 태그 하나만
    보고 판단했기 때문이다. 여기 대상은 **이미 projects 인 주제**다. 이 방의 사람이
    '프로젝트·결과물' 로 분류해 둔 것이므로 '무엇을 위해 만든 것인가' 를 묻는 것이
    성립한다. 그래도 모델이 '없음' 을 고를 수 있게 두고, 그때는 붙이지 않는다 —
    협업 경험담·구상만 있는 대화는 갈래가 없는 것이 맞다.

사용
    python -m scripts.split_tag --tag "앱 제작"            # 제안만 만든다
    python -m scripts.split_tag --tag "앱 제작" --apply    # 제안을 적용한다
    python -m scripts.split_tag --tag "앱 제작" --stats    # 몇 편인지만 센다

    python -m scripts.split_tag --tag "앱 제작" --fill-category projects
    python -m scripts.split_tag --tag "앱 제작" --fill-category projects --apply
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from datetime import datetime
from pathlib import Path

from scripts import jsonio
from scripts import tags as taglib
from scripts.llm import DEFAULT_MODEL, call_claude, parse_reply
from scripts.tag_surgery import apply_keyword_changes, backup_dir, shown
from scripts.topic_reports import TAG_COUNT_MAX, load_reports

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
BROADER = ROOT / "config" / "tag_broader.json"

# 한 번에 물어볼 보고서 수. 답이 한 줄씩(갈래 이름)이라 태그를 다시 고르는 일보다
# 가볍다. 그래도 본문을 다 실으므로 이 정도로 둔다.
BATCH = 20
TIMEOUT_SEC = 300

# 갈래를 못 고르겠다는 답. 그 편은 넓은 태그를 그대로 지닌다 — 억지로 넣으면
# 갈래가 '무엇을 위한 앱인가'를 말하지 못하게 된다.
NONE = "없음"


def load_kinds(tag: str, path: Path | None = None,
               hinted_only: bool = False) -> dict[str, str]:
    """`config/tag_broader.json` 에서 이 태그의 갈래와 설명을 읽는다.

    갈래는 `broader[tag]` 에 있어야 한다 — 거기 없으면 갈라내도 넓은 태그가 그것을
    되찾지 못해서, 갈라낸 편들이 넓은 입구에서 사라진다. 그건 가르는 것이 아니라
    잃는 것이다.

    `hinted_only` 는 `split_hints` 에 설명이 적힌 것만 갈래로 본다. 시간이 지나면
    `broader[tag]` 에는 갈래가 아닌 자식이 섞인다 — '앱 제작' 아래에 'C#'·'파워앱스'
    처럼 **결과물·도구 이름**이 좁은 태그로 들어와 있다(실측 2026-09-04: 자식 15개
    중 갈래는 7개). 그것을 갈래로 내놓으면 '이 대화는 C# 갈래' 같은 답이 오고,
    묶음이 아니라 목록이 된다. 설명이 적혀 있다는 것이 곧 '사람이 갈래로 세운 것'
    이라는 표시다.
    """
    p = path or BROADER
    raw = json.loads(p.read_text(encoding="utf-8"))
    children = [c for c in (raw.get("broader") or {}).get(tag, []) if str(c).strip()]
    if not children:
        raise SystemExit(
            "'%s' 의 갈래가 %s 의 broader 에 없습니다.\n"
            "먼저 무엇으로 가를지 그 파일에 적으세요 — 코드가 정할 일이 아닙니다."
            % (tag, shown(p))
        )
    hints = (raw.get("split_hints") or {}).get(tag) or {}
    if hinted_only:
        children = [c for c in children if str(hints.get(c, "")).strip()]
        if not children:
            raise SystemExit(
                "'%s' 의 갈래 설명이 %s 의 split_hints 에 없습니다.\n"
                "갈래마다 한 줄 설명을 적으세요 — 그것이 갈래와 좁은 태그를 가릅니다."
                % (tag, shown(p))
            )
    return {c: str(hints.get(c, "")).strip() for c in children}


# 갈래 판정은 `scripts/tags.py` 에 있다 — 발행(`build_site.build_digests`)도 같은
# 판정을 봐야 하고, 그쪽이 이 스크립트를(= `llm.call_claude` 를) 끌고 들어갈 이유는
# 없다. 이름만 남긴다(`build_site._read_json` 과 같은 방식).
facet_keys = taglib.facet_keys


def targets(reports: dict[str, dict], tag: str) -> list[str]:
    """그 태그를 **직접** 지닌 보고서. 승격으로 얻은 것은 md 에 없으니 대상이 아니다."""
    key = taglib.fold(tag)
    return sorted(t for t, r in reports.items()
                  if any(taglib.fold(k) == key for k in r["keywords"]))


def fill_targets(reports: dict[str, dict], threads: list[dict], category: str,
                 keys: dict[str, set[str]]) -> list[str]:
    """그 분류에 속하고 **갈래를 하나도 안 가진** 주제. 원장 순서로.

    넓은 태그('앱 제작')를 가졌는지는 보지 않는다. 그것을 가진 편은 `--tag` 모드가
    갈라 주는 몫이고, 여기서 찾는 것은 어느 쪽으로도 갈래가 없는 편이다.
    """
    have = set().union(*keys.values()) if keys else set()
    out = []
    for th in threads:
        if th.get("category") != category:
            continue
        kw = (reports.get(th["id"]) or {}).get("keywords") or []
        if not any(taglib.fold(k) in have for k in kw):
            out.append(th["id"])
    return out


def build_prompt(items: list[dict], tag: str, kinds: dict[str, str]) -> str:
    lines = []
    for name, hint in kinds.items():
        lines.append("- **%s** — %s" % (name, hint) if hint else "- **%s**" % name)
    menu = "\n".join(lines)

    blocks = []
    for it in items:
        blocks.append(
            "[%s]\n제목: %s\n요지: %s\n태그: %s\n본문:\n%s"
            % (it["id"], it["title"], it["summary"],
               ", ".join(it["keywords"]), it["report"])
        )
    ids = ", ".join(it["id"] for it in items)

    return f"""아래 보고서 {len(items)}편은 모두 '{tag}' 태그를 달고 있습니다. 한 태그에
너무 많이 몰려서, 눌러도 목록이 벽처럼 쏟아집니다. 그래서 **갈래를 하나씩 골라**
주는 일입니다. 본문·제목·요지·다른 태그는 고치지 않습니다.

### 갈래 (이 중에서 **딱 하나**)
{menu}
- **{NONE}** — 위 어디에도 안 맞을 때만. 억지로 넣지 마세요.

### 어떻게 고르나
- **무엇을 위한 것인가**로 고르세요. 무엇으로 만들었나(안티그래비티·러버블·
  앱스스크립트)가 아니라, **누가 무엇에 쓰는 것인가**가 기준입니다.
- 여러 갈래에 걸치면 **그 대화의 중심**을 고르세요. 곁가지로 잠깐 나온 쪽이
  아니라, 이 보고서가 주로 이야기하는 것입니다.
- 본문을 읽고 판단하세요. 태그는 참고만 하세요 — 태그가 부실해서 가르는 것입니다.

--- 보고서 ---
{"\n\n".join(blocks)}
--- 끝 ---

답은 JSON 만. 다른 말은 붙이지 마세요. 열쇠는 보고서 id, 값은 갈래 이름 하나입니다.
{len(items)}편 전부({ids})에 답해야 합니다.

{{"t-012": "업무 앱"}}"""


def build_fill_prompt(items: list[dict], tag: str, kinds: dict[str, str],
                      category_label: str) -> str:
    """갈래를 **채우는** 프롬프트. 고르는 규칙은 가르는 쪽과 같은 문장을 쓴다.

    두 프롬프트가 다른 말로 같은 것을 물으면 결과가 갈라진다 — 이미 갈래를 받은
    63편과 이제 받을 43편이 다른 기준으로 나뉘면, 묶어 보이는 화면에서 그 어긋남이
    그대로 드러난다.
    """
    lines = []
    for name, hint in kinds.items():
        lines.append("- **%s** — %s" % (name, hint) if hint else "- **%s**" % name)
    menu = "\n".join(lines)

    blocks = []
    for it in items:
        blocks.append(
            "[%s]\n제목: %s\n요지: %s\n태그: %s\n본문:\n%s"
            % (it["id"], it["title"], it["summary"],
               ", ".join(it["keywords"]) or "(없음)", it["report"])
        )
    body = "\n\n".join(blocks)
    ids = ", ".join(it["id"] for it in items)

    return f"""아래 보고서 {len(items)}편은 모두 '{category_label}' 로 분류된 대화인데,
'{tag}' 의 갈래 태그가 하나도 없습니다. 그래서 갈래로 묶어 보이는 화면에서 전부
'그 밖' 으로 밀립니다. **갈래를 하나씩 골라** 주는 일입니다. 본문·제목·요지는
고치지 않습니다.

### 갈래 (이 중에서 **딱 하나**)
{menu}
- **{NONE}** — 위 어디에도 안 맞을 때만. 억지로 넣지 마세요.

### 어떻게 고르나
- **무엇을 위한 것인가**로 고르세요. 무엇으로 만들었나(안티그래비티·러버블·
  앱스스크립트)가 아니라, **누가 무엇에 쓰는 것인가**가 기준입니다.
- 여러 갈래에 걸치면 **그 대화의 중심**을 고르세요. 곁가지로 잠깐 나온 쪽이
  아니라, 이 보고서가 주로 이야기하는 것입니다.
- **만든 이야기가 아니면 '{NONE}' 입니다.** 협업 경험담·구상·후기처럼 결과물이
  없는 대화는 갈래가 없는 것이 맞습니다. 그런 편에 갈래를 붙이면 그 갈래를
  누른 사람이 찾던 것을 못 찾습니다.
- 본문을 읽고 판단하세요. 태그는 참고만 하세요 — 태그가 부실해서 채우는 것입니다.

--- 보고서 ---
{body}
--- 끝 ---

답은 JSON 만. 다른 말은 붙이지 마세요. 열쇠는 보고서 id, 값은 갈래 이름 하나입니다.
{len(items)}편 전부({ids})에 답해야 합니다.

{{"t-012": "업무 앱"}}"""


def screen_fill(reports: dict[str, dict], answers: dict[str, str],
                kinds: dict[str, str], vocab: list[str],
                counts: collections.Counter | None = None,
                max_tags: int = TAG_COUNT_MAX) -> dict[str, dict]:
    """답을 제안으로 만든다 — 갈래를 **덧붙이거나** 한 자리를 바꾼다. 호출하지 않는다.

    태그는 한 편에 `max_tags` 개까지다(`topic_reports.TAG_COUNT_MAX`). 자리가
    남으면 덧붙이고, 꽉 찼으면 **어휘 밖이고 한 번만 쓰인** 태그 하나를 갈래로
    바꾼다 — 그 태그는 태그 목록에도 안 나오고 부모도 없어서, 사실상 그 편에만
    있는 말이다(`tags.build_tag_index` 의 `min_count`). 그런 태그가 없으면
    건너뛰고 로그만 남긴다. 잘 붙은 태그를 갈래 자리 때문에 버리지는 않는다.

    뒤에서부터 고른다. keywords 의 순서에는 사람이 쓴 무게가 담겨 있어(앞이
    중심이다) 뒤가 가장 곁가지다.
    """
    by_key = {taglib.fold(k): k for k in kinds}
    vocab_keys = {taglib.fold(v) for v in vocab}
    counts = counts if counts is not None else tag_counts(reports)

    out: dict[str, dict] = {}
    for tid in sorted(answers):
        raw = (answers[tid] or "").strip()
        if not raw or taglib.fold(raw) == taglib.fold(NONE):
            print("  %s: 갈래를 못 고름 — 그대로 둡니다" % tid)
            continue
        kind = by_key.get(taglib.fold(raw))
        if not kind:
            print("  %s: 목록에 없는 갈래 '%s' — 손대지 않습니다" % (tid, raw))
            continue
        before = reports[tid]["keywords"]
        if any(taglib.fold(k) == taglib.fold(kind) for k in before):
            continue        # 이미 그 갈래가 있다
        if len(before) < max_tags:
            after, dropped = before + [kind], None
        else:
            spare = [k for k in before
                     if taglib.fold(k) not in vocab_keys
                     and counts.get(taglib.fold(k), 0) <= 1]
            if not spare:
                print("  %s: 태그가 %d개인데 바꿀 만한 것이 없습니다 — 건너뜁니다"
                      % (tid, len(before)))
                continue
            dropped = spare[-1]
            after = [kind if k == dropped else k for k in before]
        row = {"before": before, "after": after, "kind": kind}
        if dropped:
            row["dropped"] = dropped
        out[tid] = row
    return out


def tag_counts(reports: dict[str, dict]) -> collections.Counter:
    """태그 fold → 몇 편에 쓰였나. '1회짜리' 판정의 근거다."""
    return collections.Counter(
        taglib.fold(k) for r in reports.values() for k in r["keywords"])


def ask(reports: dict[str, dict], ids: list[str], tag: str, kinds: dict[str, str],
        model: str, batch_size: int, timeout: int, prompt_of=None,
        what: str = "태그 가르기") -> dict[str, str]:
    """배치로 나눠 물어 **다듬지 않은 답**을 모은다. 실패한 배치는 건너뛴다."""
    prompt_of = prompt_of or (lambda items: build_prompt(items, tag, kinds))
    out: dict[str, str] = {}
    total = (len(ids) + batch_size - 1) // batch_size
    for n in range(total):
        chunk = ids[n * batch_size:(n + 1) * batch_size]
        items = [dict(reports[t], id=t) for t in chunk]
        print("배치 %d/%d — %d편 (%s ~ %s)"
              % (n + 1, total, len(chunk), chunk[0], chunk[-1]))
        reply = parse_reply(
            call_claude(prompt_of(items), model, timeout, what) or "")
        if not reply:
            print("  답을 받지 못해 이 배치는 건너뜁니다 — 다음 실행이 다시 봅니다.")
            continue
        missing = [t for t in chunk if t not in reply]
        if missing:
            print("  답이 빠진 보고서 %d편: %s" % (len(missing), ", ".join(missing[:5])))
        for tid in chunk:
            if tid in reply and isinstance(reply[tid], str):
                out[tid] = reply[tid]
    return out


def screen(reports: dict[str, dict], answers: dict[str, str], tag: str,
           kinds: dict[str, str]) -> dict[str, dict]:
    """답을 갈래 목록에 맞춰 걸러 제안으로 만든다. 호출하지 않는다.

    갈래 이름이 목록에 없으면 그 편은 손대지 않는다. 여기서 너그러우면 목록에 없는
    갈래가 태그로 들어가고, 그것은 `broader` 의 자식이 아니므로 넓은 태그가 되찾지
    못한다 — 갈라낸 편이 넓은 입구에서 사라진다.
    """
    by_key = {taglib.fold(k): k for k in kinds}
    tag_key = taglib.fold(tag)
    out: dict[str, dict] = {}
    for tid in sorted(answers):
        raw = (answers[tid] or "").strip()
        if not raw or taglib.fold(raw) == taglib.fold(NONE):
            print("  %s: 갈래를 못 고름 — '%s' 를 그대로 둡니다" % (tid, tag))
            continue
        kind = by_key.get(taglib.fold(raw))
        if not kind:
            print("  %s: 목록에 없는 갈래 '%s' — 손대지 않습니다" % (tid, raw))
            continue
        before = reports[tid]["keywords"]
        # 넓은 태그가 있던 **그 자리**에 갈래를 넣는다. 순서에는 사람이 쓴 무게가
        # 담겨 있어(앞이 중심이다) 뒤로 밀면 그 뜻이 흐려진다.
        after, seen = [], set()
        for k in before:
            name = kind if taglib.fold(k) == tag_key else k
            if taglib.fold(name) not in seen:
                seen.add(taglib.fold(name))
                after.append(name)
        if after == before:
            continue
        out[tid] = {"before": before, "after": after, "kind": kind}
    return out


def apply_proposal(proposal: dict, day: str, kind: str = "split"
                   ) -> tuple[int, list[str], Path]:
    """제안대로 keywords 줄을 바꾼다. 바꾸기 전 md 와 태그는 백업 폴더에 남긴다."""
    backup = backup_dir(kind, day)
    done, failed = apply_keyword_changes(proposal["changes"], backup)
    return done, failed, backup


def category_label(category: str) -> str:
    """분류 id → 라벨. 원장을 못 읽으면 id 를 그대로 쓴다."""
    try:
        cats = jsonio.read_json(OUT / "topics.json").get("categories") or []
    except (OSError, ValueError):
        return category
    return next((c["label"] for c in cats if c.get("id") == category), category)


def main() -> int:
    ap = argparse.ArgumentParser(description="너무 넓어진 태그를 갈래로 가른다")
    ap.add_argument("--tag", required=True, help="가를 넓은 태그")
    ap.add_argument("--fill-category", metavar="분류id",
                    help="가르는 대신 **채운다** — 그 분류에서 갈래가 없는 주제에 갈래를 붙인다")
    ap.add_argument("--apply", action="store_true",
                    help="제안 파일을 읽어 md 를 바꾼다 (호출 없음)")
    ap.add_argument("--stats", action="store_true", help="몇 편인지만 센다 (호출 없음)")
    ap.add_argument("--rescreen", action="store_true",
                    help="제안에 담긴 답에 규칙을 다시 걸어 제안을 새로 쓴다 (호출 없음)")
    ap.add_argument("--limit", type=int, default=0, help="앞에서 이만큼만 (0=전부)")
    ap.add_argument("--batch", type=int, default=BATCH)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--timeout", type=int, default=TIMEOUT_SEC)
    ap.add_argument("--proposal", type=Path, default=None)
    args = ap.parse_args()

    fill = args.fill_category
    tag_slug = args.tag.replace(" ", "_")
    proposal_path = args.proposal or (OUT / (
        ("fill-proposal-%s-%s.json" % (fill, tag_slug)) if fill
        else ("split-proposal-%s.json" % tag_slug)))

    if args.apply:
        if not proposal_path.is_file():
            print("제안 파일이 없습니다: %s" % shown(proposal_path))
            return 1
        proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
        if not (proposal.get("changes") or {}):
            print("제안에 바꿀 것이 없습니다.")
            return 0
        done, failed, backup = apply_proposal(
            proposal, datetime.now().strftime("%Y%m%d"),
            "facet" if fill else "split")
        print("보고서 %d편의 keywords 줄을 바꿨습니다." % done)
        for f in failed:
            print("  못 바꿈 — %s" % f)
        print("\n백업: %s/ (바꾸기 전 md 와 태그)" % shown(backup))
        print("다음: python -m scripts.build_site  → 테스트 → 발행")
        return 0

    reports = load_reports()
    kinds = load_kinds(args.tag, hinted_only=bool(fill))
    if fill:
        threads = jsonio.read_json(OUT / "topics.json")["threads"]
        ids = fill_targets(reports, threads, fill,
                           facet_keys(args.tag, list(kinds)))
        label = category_label(fill)
        print("'%s' 주제 가운데 '%s' 갈래가 없는 것 %d편 · 갈래 %d개"
              % (label, args.tag, len(ids), len(kinds)))
    else:
        ids = targets(reports, args.tag)
        print("'%s' 를 직접 지닌 보고서 %d편 · 갈래 %d개"
              % (args.tag, len(ids), len(kinds)))
    for name, hint in kinds.items():
        print("  %-14s %s" % (name, hint))
    if args.stats:
        return 0
    if not ids:
        print("채울 것이 없습니다." if fill else "가를 것이 없습니다.")
        return 0

    if args.rescreen:
        old = json.loads(proposal_path.read_text(encoding="utf-8"))
        answers = old.get("answers") or {}
        if not answers:
            print("다시 걸 답이 없습니다: %s" % shown(proposal_path))
            return 1
        print("  답 %d편을 규칙에 다시 겁니다 (호출 없음)." % len(answers))
    else:
        if args.limit:
            ids = ids[:args.limit]
            print("  --limit %d — 앞에서 %d편만 봅니다." % (args.limit, len(ids)))
        answers = ask(
            reports, ids, args.tag, kinds, args.model, args.batch, args.timeout,
            prompt_of=((lambda items: build_fill_prompt(items, args.tag, kinds,
                                                        category_label(fill)))
                       if fill else None),
            what="갈래 채우기" if fill else "태그 가르기")
        if not answers:
            print("\n답을 하나도 받지 못했습니다.")
            return 1

    if fill:
        # 어휘는 화면이 보는 것과 같게 잰다 — `retag_reports.load_state` 와 같은 꼴.
        threads = jsonio.read_json(OUT / "topics.json")["threads"]
        for th in threads:
            r = reports.get(th["id"])
            if r:
                th["keywords"] = r["keywords"]
        parts_path = OUT / "participants.json"
        parts = jsonio.read_json(parts_path) if parts_path.is_file() else {}
        places, _ = taglib.load_places()
        vocab = [name for name, _ in taglib.vocabulary(threads, parts, places)]
        changes = screen_fill(reports, answers, kinds, vocab)
    else:
        changes = screen(reports, answers, args.tag, kinds)
    if not changes:
        print("\n바뀔 것이 없습니다.")
        return 0

    spread = collections.Counter(v["kind"] for v in changes.values())
    print("\n보고서 %d편이 %s." % (len(changes), "갈래를 받습니다" if fill else "갈립니다"))
    for name in kinds:
        print("  %-14s %d편" % (name, spread.get(name, 0)))
    left = len(ids) - len(changes)
    if left:
        print("  %-14s %d편 (%s)" % ("(못 가름)", left,
                                     "갈래 없이 그대로" if fill
                                     else "'%s' 그대로" % args.tag))
    swapped = {t: v["dropped"] for t, v in changes.items() if v.get("dropped")}
    if swapped:
        print("  태그가 꽉 차서 한 자리를 바꾼 편 %d개: %s" % (
            len(swapped), ", ".join("%s(%s)" % kv for kv in sorted(swapped.items()))))

    proposal_path.parent.mkdir(parents=True, exist_ok=True)
    proposal_path.write_text(
        json.dumps({"made": datetime.now().isoformat(timespec="seconds"),
                    "tag": args.tag, "fill_category": fill, "model": args.model,
                    "kinds": list(kinds), "answers": answers, "changes": changes},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\n제안 → %s" % shown(proposal_path))
    print("md 는 아직 한 글자도 안 바꿨습니다. 적용:")
    print('  python -m scripts.split_tag --tag "%s"%s --apply'
          % (args.tag, (" --fill-category %s" % fill) if fill else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
