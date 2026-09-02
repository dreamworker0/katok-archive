# -*- coding: utf-8 -*-
"""주제가 아닌 태그를 거둔다 — 떼고, 얇아지는 편만 새 태그를 고른다.

왜 이 파일이 있나
    태그 목록에서 큰 것을 훑다가 '링크 공유' 58편을 만났다. 가를까 하다 재보니
    가를 것이 아니었다 — 주제가 아니라 **행위**이고, 게다가 어긋나 있었다
    (실측 2026-08-21).

        본문에 링크 자료가 있는 편          163
        '링크 공유' 태그가 붙은 편            58   ← 122편이 빠졌다
        태그는 붙었는데 본문에 링크가 없는 편    17

    링크가 있다는 사실은 화면이 이미 자료로 안다. 태그가 할 일은 '무엇을
    이야기했나' 다. 이런 태그를 갈래로 가르면 어긋난 태그가 넷으로 늘어난다.

    같은 성질의 태그가 더 있다 — '사진 공유' 21 · '유튜브 영상' 15 · '영상 공유' 13 ·
    '페이스북 공유' 6. 그래서 태그 이름을 받는다.

거두면 얇아지는 편이 있다
    태그를 떼기만 하면 남는 것이 하나뿐인 편이 생긴다(링크 공유의 경우 58편 중 8편).
    태그 하나짜리 주제는 규칙(`TAG_COUNT_MIN`)에 안 맞고, 입구도 하나뿐이다.
    그 편들만 골라 어휘에서 새 태그를 고르게 한다 — 나머지는 호출 없이 떼기만 한다.

    기준은 **keywords 개수**다. '목록에 보이는 태그(2회 이상 쓰인 것) 개수' 로 하면
    더 촘촘할 것 같지만 그러지 않는다. 실측 2026-08-21: 링크 공유를 거두니 목록에
    보이는 태그가 둘에서 하나로 줄어든 편이 5개 더 나왔는데(t-113·t-129·t-178·
    t-224·t-180), 넷은 본문이 한두 줄이었다('마이크로소프트 Stride를 공유하며 PC에서만
    된다고 알렸다'). 그런 편에 태그를 더 요구하면 없는 내용을 지어내게 된다.
    입구가 하나 남는 것은 그 대화가 실제로 한 줄이라는 뜻이고, 그 하나는 진짜 주제다.

거두기 전에 막는 것
    거둘 태그가 `config/tag_broader.json` 에 부모나 자식으로 적혀 있으면 멈춘다.
      · 부모라면  keywords 에서 떼도 승격이 다시 붙여 화면에서 사라지지 않는다
      · 자식이라면 그 편이 부모에게 닿는 길을 잃는다
    둘 다 '거뒀다고 생각했는데 아닌' 상태다. 표에서 먼저 지우게 한다.

무엇을 고치고 무엇을 안 고치는가
    고침    output/reports/*.md 의 `keywords:` 줄
    안 고침 본문·제목·요지, 그 밖의 모든 것

사용
    python -m scripts.retire_tag --tag "링크 공유"           # 제안만 만든다
    python -m scripts.retire_tag --tag "링크 공유" --apply   # 제안을 적용한다
    python -m scripts.retire_tag --tag "링크 공유" --stats   # 몇 편인지만 센다
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
from scripts.retag_reports import (
    freeze_vocabulary,
    load_state,
    sanitize,
)
from scripts.tag_surgery import apply_keyword_changes, backup_dir, shown
from scripts.topic_reports import TAG_COUNT_MIN, load_reports, tag_rules

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
BROADER = ROOT / "config" / "tag_broader.json"

BATCH = 20
TIMEOUT_SEC = 300


def guard_broader(tag: str, path: Path | None = None) -> None:
    """거둘 태그가 승격 표에 얽혀 있으면 멈춘다."""
    raw = json.loads((path or BROADER).read_text(encoding="utf-8"))
    broader = raw.get("broader") or {}
    key = taglib.fold(tag)
    if any(taglib.fold(p) == key for p in broader):
        raise SystemExit(
            "'%s' 는 승격 표의 **부모** 입니다. keywords 에서 떼도 승격이 다시 붙여\n"
            "화면에서는 사라지지 않습니다. 먼저 %s 에서 그 항목을 지우세요."
            % (tag, shown(path or BROADER))
        )
    parents = [p for p, kids in broader.items()
               if any(taglib.fold(k) == key for k in kids)]
    if parents:
        raise SystemExit(
            "'%s' 는 %s 의 **자식** 입니다. 거두면 그 편들이 부모에게 닿는 길을\n"
            "잃습니다. 먼저 %s 에서 그 항목을 지우세요."
            % (tag, "·".join(parents), shown(path or BROADER))
        )
    if any(taglib.fold(s) == key for s in (raw.get("short_parents") or [])):
        raise SystemExit(
            "'%s' 는 short_parents 에 있습니다 — 기계가 부모로 씁니다.\n"
            "먼저 %s 에서 그 항목을 지우세요." % (tag, shown(path or BROADER))
        )


def targets(reports: dict[str, dict], tag: str) -> list[str]:
    key = taglib.fold(tag)
    return sorted(t for t, r in reports.items()
                  if any(taglib.fold(k) == key for k in r["keywords"]))


def overlap_parents(reports: dict[str, dict], tag: str, min_count: int = 2
                    ) -> list[tuple[str, int]]:
    """글자가 겹쳐 이 태그를 받아 주던 넓은 태그들. (태그, 지금 편수)

    표(`guard_broader`)만 보면 놓치는 길이 있다. 승격은 표 말고 **글자 겹침**으로도
    붙는다 — '유튜브 영상' 은 '유튜브' 를 품고 있으니 '유튜브' 의 자식이다. 그래서
    거두면 그쪽 입구도 함께 줄어든다.

    실측 2026-08-21: '유튜브 영상' 15편을 거두면 '유튜브' 가 19 → 6 으로 주저앉고,
    '페이스북 공유' 6편을 거두면 '페이스북' 이 10 → 4, 그 부모 '협업 도구' 가
    25 → 19 가 된다. 표에는 아무 흔적이 없어 검사기가 통과시킨다.

    막지는 않는다 — 거두는 것이 옳을 때도 있다. 다만 얼마를 잃는지 보고 결정해야
    하고, 잃는 것이 크면 거두는 대신 **표기 통일**(config/tag_aliases.json)로
    넓은 쪽에 합치는 편이 낫다. 그러면 보고서를 안 고치고도 행위 표현만 사라진다.
    """
    key = taglib.fold(tag)
    counts: collections.Counter[str] = collections.Counter()
    for rep in reports.values():
        for k in rep["keywords"]:
            counts[k] += 1
    out = []
    for other, n in counts.items():
        okey = taglib.fold(other)
        if okey != key and okey in key and n >= min_count:
            out.append((other, n))
    out.sort(key=lambda r: -r[1])
    return out


def without(keywords: list[str], tag: str) -> list[str]:
    key = taglib.fold(tag)
    return [k for k in keywords if taglib.fold(k) != key]


def build_prompt(items: list[dict], tag: str, vocab: list[str], need: int) -> str:
    """얇아진 편에 붙일 태그를 어휘에서 고르게 한다."""
    blocks = []
    for it in items:
        blocks.append(
            "[%s]\n제목: %s\n요지: %s\n남은 태그: %s\n본문:\n%s"
            % (it["id"], it["title"], it["summary"],
               ", ".join(it["left"]) or "(없음)", it["report"])
        )
    ids = ", ".join(it["id"] for it in items)

    return f"""'{tag}' 태그를 거두는 중입니다. 그 말은 '무엇을 이야기했나' 가 아니라
'링크·사진을 나눴다' 는 **행위**여서, 자료가 있다는 사실은 화면이 이미 자료로 압니다.

아래 {len(items)}편은 그 태그를 떼면 남는 태그가 {need}개 미만이 됩니다. 그래서 이
대화가 **무엇에 관한 것인지** 말해 줄 태그를 채워야 합니다. 본문·제목·요지는 고치지
않습니다.

{tag_rules(vocab)}

### 이 일에서 지킬 것
- 남은 태그에 **더할 것만** 답하세요. 이미 붙어 있는 것을 다시 적지 마세요.
- '{tag}' 는 다시 쓰지 마세요. 같은 뜻의 다른 행위 말('자료 공유'·'기사 공유')도
  만들지 마세요 — 거두려는 것이 바로 그것입니다.
- 합쳐서 최소 {need}개가 되게 채우세요. 본문이 얇으면 하나만 채워도 됩니다.
- 본문에 없는 것을 짐작해 넣지 마세요.

--- 보고서 ---
{"\n\n".join(blocks)}
--- 끝 ---

답은 JSON 만. 열쇠는 보고서 id, 값은 **더할 태그** 목록입니다.
{len(items)}편 전부({ids})에 답해야 합니다.

{{"t-012": ["제미나이"]}}"""


def ask(items: list[dict], tag: str, vocab: list[str], model: str,
        batch_size: int, timeout: int, need: int) -> dict[str, list]:
    out: dict[str, list] = {}
    total = (len(items) + batch_size - 1) // batch_size
    for n in range(total):
        chunk = items[n * batch_size:(n + 1) * batch_size]
        print("배치 %d/%d — %d편" % (n + 1, total, len(chunk)))
        reply = parse_reply(
            call_claude(build_prompt(chunk, tag, vocab, need), model, timeout,
                        "태그 채우기") or "")
        if not reply:
            print("  답을 받지 못해 이 배치는 건너뜁니다.")
            continue
        for it in chunk:
            if it["id"] in reply and isinstance(reply[it["id"]], list):
                out[it["id"]] = reply[it["id"]]
    return out


def apply_proposal(proposal: dict, day: str) -> tuple[int, list[str], Path]:
    """제안대로 keywords 줄을 바꾼다. 바꾸기 전 md 와 태그는 백업 폴더에 남긴다."""
    backup = backup_dir("retire", day)
    done, failed = apply_keyword_changes(proposal["changes"], backup)
    return done, failed, backup


def main() -> int:
    ap = argparse.ArgumentParser(description="주제가 아닌 태그를 거둔다")
    ap.add_argument("--tag", required=True, help="거둘 태그")
    ap.add_argument("--apply", action="store_true", help="제안을 적용한다 (호출 없음)")
    ap.add_argument("--stats", action="store_true", help="몇 편인지만 센다 (호출 없음)")
    ap.add_argument("--min", type=int, default=TAG_COUNT_MIN, dest="need",
                    help="이 수 미만으로 남는 편은 새 태그를 고른다 (기본 %d)" % TAG_COUNT_MIN)
    ap.add_argument("--batch", type=int, default=BATCH)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--timeout", type=int, default=TIMEOUT_SEC)
    ap.add_argument("--proposal", type=Path, default=None)
    args = ap.parse_args()

    proposal_path = args.proposal or (
        OUT / ("retire-proposal-%s.json" % args.tag.replace(" ", "_")))

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

    guard_broader(args.tag)
    reports = load_reports()
    ids = targets(reports, args.tag)
    thin = [t for t in ids if len(without(reports[t]["keywords"], args.tag)) < args.need]
    print("'%s' 를 지닌 보고서 %d편 · 떼면 태그가 %d개 미만이 되는 편 %d개"
          % (args.tag, len(ids), args.need, len(thin)))
    feeds = overlap_parents(reports, args.tag)
    if feeds:
        print("\n  주의 — 글자가 겹쳐 이 태그를 받아 주던 넓은 태그가 있습니다."
              " 거두면 그쪽도 줄어듭니다:")
        for other, n in feeds:
            print("    %s (지금 %d편)" % (other, n))
        print("  잃는 것이 크면 거두는 대신 config/tag_aliases.json 으로 그쪽에"
              " 합치세요 — 보고서를 안 고치고도 행위 표현만 사라집니다.")
    if args.stats:
        return 0
    if not ids:
        print("거둘 것이 없습니다.")
        return 0

    changes: dict[str, dict] = {}
    for tid in ids:
        before = reports[tid]["keywords"]
        changes[tid] = {"before": before, "after": without(before, args.tag)}

    if thin:
        state = load_state()
        vocab = [v for v in freeze_vocabulary(state)
                 if taglib.fold(v) != taglib.fold(args.tag)]
        vocab_keys = {taglib.fold(v) for v in vocab}
        people = taglib.person_names(state["participants"])
        corpus_keys = {taglib.fold(k) for r in reports.values() for k in r["keywords"]}
        items = [dict(reports[t], id=t, left=changes[t]["after"]) for t in thin]
        added = ask(items, args.tag, vocab, args.model, args.batch, args.timeout,
                    args.need)
        for tid, extra in added.items():
            left = changes[tid]["after"]
            # 더할 태그도 같은 검사를 받는다 — 사람 이름·지명·지어낸 말을 막는다.
            picked, notes = sanitize(list(extra), left, vocab_keys, people,
                                     state["places"], state["categories"],
                                     corpus_keys)
            fresh = [p for p in picked
                     if taglib.fold(p) not in {taglib.fold(x) for x in left}
                     and taglib.fold(p) != taglib.fold(args.tag)]
            for note in notes:
                print("  %s: %s" % (tid, note))
            if not fresh:
                print("  %s: 채울 태그를 못 얻음 — 태그 %d개로 남습니다"
                      % (tid, len(left)))
                continue
            changes[tid]["after"] = left + fresh
            print("  %s: + %s" % (tid, ", ".join(fresh)))
        still = [t for t in thin if len(changes[t]["after"]) < args.need]
        if still:
            print("\n아직 %d개 미만인 편 %d개: %s" % (args.need, len(still), ", ".join(still)))

    print("\n보고서 %d편에서 '%s' 를 뗍니다." % (len(changes), args.tag))
    proposal_path.parent.mkdir(parents=True, exist_ok=True)
    proposal_path.write_text(
        json.dumps({"made": datetime.now().isoformat(timespec="seconds"),
                    "tag": args.tag, "model": args.model, "changes": changes},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("제안 → %s" % shown(proposal_path))
    print("md 는 아직 한 글자도 안 바꿨습니다. 적용:")
    print('  python -m scripts.retire_tag --tag "%s" --apply' % args.tag)
    return 0


if __name__ == "__main__":
    sys.exit(main())
