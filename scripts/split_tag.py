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

사용
    python -m scripts.split_tag --tag "앱 제작"            # 제안만 만든다
    python -m scripts.split_tag --tag "앱 제작" --apply    # 제안을 적용한다
    python -m scripts.split_tag --tag "앱 제작" --stats    # 몇 편인지만 센다
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from datetime import datetime
from pathlib import Path

from scripts import tags as taglib
from scripts.llm import DEFAULT_MODEL, call_claude, parse_reply
from scripts.tag_surgery import apply_keyword_changes, backup_dir, shown
from scripts.topic_reports import load_reports

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


def load_kinds(tag: str, path: Path | None = None) -> dict[str, str]:
    """`config/tag_broader.json` 에서 이 태그의 갈래와 설명을 읽는다.

    갈래는 `broader[tag]` 에 있어야 한다 — 거기 없으면 갈라내도 넓은 태그가 그것을
    되찾지 못해서, 갈라낸 편들이 넓은 입구에서 사라진다. 그건 가르는 것이 아니라
    잃는 것이다.
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
    return {c: str(hints.get(c, "")).strip() for c in children}


def targets(reports: dict[str, dict], tag: str) -> list[str]:
    """그 태그를 **직접** 지닌 보고서. 승격으로 얻은 것은 md 에 없으니 대상이 아니다."""
    key = taglib.fold(tag)
    return sorted(t for t, r in reports.items()
                  if any(taglib.fold(k) == key for k in r["keywords"]))


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


def ask(reports: dict[str, dict], ids: list[str], tag: str, kinds: dict[str, str],
        model: str, batch_size: int, timeout: int) -> dict[str, str]:
    """배치로 나눠 물어 **다듬지 않은 답**을 모은다. 실패한 배치는 건너뛴다."""
    out: dict[str, str] = {}
    total = (len(ids) + batch_size - 1) // batch_size
    for n in range(total):
        chunk = ids[n * batch_size:(n + 1) * batch_size]
        items = [dict(reports[t], id=t) for t in chunk]
        print("배치 %d/%d — %d편 (%s ~ %s)"
              % (n + 1, total, len(chunk), chunk[0], chunk[-1]))
        reply = parse_reply(
            call_claude(build_prompt(items, tag, kinds), model, timeout, "태그 가르기")
            or "")
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


def apply_proposal(proposal: dict, day: str) -> tuple[int, list[str], Path]:
    """제안대로 keywords 줄을 바꾼다. 바꾸기 전 md 와 태그는 백업 폴더에 남긴다."""
    backup = backup_dir("split", day)
    done, failed = apply_keyword_changes(proposal["changes"], backup)
    return done, failed, backup


def main() -> int:
    ap = argparse.ArgumentParser(description="너무 넓어진 태그를 갈래로 가른다")
    ap.add_argument("--tag", required=True, help="가를 넓은 태그")
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

    proposal_path = args.proposal or (
        OUT / ("split-proposal-%s.json" % args.tag.replace(" ", "_")))

    if args.apply:
        if not proposal_path.is_file():
            print("제안 파일이 없습니다: %s" % shown(proposal_path))
            return 1
        proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
        if not (proposal.get("changes") or {}):
            print("제안에 바꿀 것이 없습니다.")
            return 0
        done, failed, backup = apply_proposal(
            proposal, datetime.now().strftime("%Y%m%d"))
        print("보고서 %d편의 keywords 줄을 바꿨습니다." % done)
        for f in failed:
            print("  못 바꿈 — %s" % f)
        print("\n백업: %s/ (바꾸기 전 md 와 태그)" % shown(backup))
        print("다음: python -m scripts.build_site  → 테스트 → 발행")
        return 0

    reports = load_reports()
    kinds = load_kinds(args.tag)
    ids = targets(reports, args.tag)
    print("'%s' 를 직접 지닌 보고서 %d편 · 갈래 %d개" % (args.tag, len(ids), len(kinds)))
    for name, hint in kinds.items():
        print("  %-14s %s" % (name, hint))
    if args.stats:
        return 0
    if not ids:
        print("가를 것이 없습니다.")
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
        answers = ask(reports, ids, args.tag, kinds, args.model, args.batch,
                      args.timeout)
        if not answers:
            print("\n답을 하나도 받지 못했습니다.")
            return 1

    changes = screen(reports, answers, args.tag, kinds)
    if not changes:
        print("\n바뀔 것이 없습니다.")
        return 0

    spread = collections.Counter(v["kind"] for v in changes.values())
    print("\n보고서 %d편이 갈립니다." % len(changes))
    for name in kinds:
        print("  %-14s %d편" % (name, spread.get(name, 0)))
    left = len(ids) - len(changes)
    if left:
        print("  %-14s %d편 ('%s' 그대로)" % ("(못 가름)", left, args.tag))

    proposal_path.parent.mkdir(parents=True, exist_ok=True)
    proposal_path.write_text(
        json.dumps({"made": datetime.now().isoformat(timespec="seconds"),
                    "tag": args.tag, "model": args.model, "kinds": list(kinds),
                    "answers": answers, "changes": changes},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\n제안 → %s" % shown(proposal_path))
    print("md 는 아직 한 글자도 안 바꿨습니다. 적용:")
    print('  python -m scripts.split_tag --tag "%s" --apply' % args.tag)
    return 0


if __name__ == "__main__":
    sys.exit(main())
