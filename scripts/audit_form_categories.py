# -*- coding: utf-8 -*-
"""형식 분류 감사 — '뉴스·자료 공유'·'일상·잡담'에 숨은 **주제**를 제 분류로 옮긴다.

왜 이 파일이 있나
    분류 열두 개 가운데 둘은 '무엇을 이야기했나' 가 아니라 '어떤 꼴로 오갔나' 를
    가리킨다. `news-articles`(뉴스·자료 공유)는 링크를 붙였다는 행위이고,
    `chat`(일상·잡담)은 아직 자리가 안 정해졌다는 뜻이다
    (`ontology.PROVISIONAL_CATEGORIES`). 그런데 그 안을 읽으면 모델 장애·클라우드
    리전·AI 리터러시 논문·보안 사고처럼 **다른 분류의 정의에 그대로 드는 대화**가
    섞여 있다.

    그러면 두 손해가 겹친다. 그 대화를 찾는 사람은 제 분류에서 못 찾고, 그 분류의
    요지 산문은 있어야 할 이야기를 빼고 쓰인다. 링크를 공유했다는 사실은 화면이
    이미 '공유 링크' 로 안다 — 분류가 할 일은 그것이 아니다.

    2026-08-21 에 태그 '링크 공유'·'사진 공유'·'영상 공유' 를 거둔 것과 같은
    판단이다. 행위·형식이 주제의 자리를 차지하면 그 자리만큼 주제를 잃는다.

무엇을 고치고 무엇을 안 고치는가
    고침    output/topics.json                그 주제의 `category` 하나
            output/secondary_categories.json  옛 분류를 보조 분류로 덧붙인다
    안 고침 보고서 본문·제목·요지·태그, `knowledge.json`, 분류 id 자체

    보고서를 손대지 않는 이유는 이 저장소의 규칙이다(방장 결정). 분류 id 도 지우지
    않는다 — `news-articles` 가 작아져도 digests 문서 열쇠·통계 색·Firestore 문서가
    그 id 위에 서 있고, 거두는 일은 그것들을 함께 옮기는 별도의 일이다.

    `knowledge.json` 을 건드리지 않아도 되는 것은 `build_site.weigh_knowledge` 가
    `topic:<분류>` 노드의 무게를 발행 때마다 원문에서 다시 세기 때문이다.

두 단계 — 제안 → 사람 검토 → 적용
    옮기는 판단은 되돌리기가 번거롭다(주 분류가 통계 합계의 전제다). 그래서 먼저
    제안서만 쓰고, 사람이 표를 읽고 승인한 것만 `--apply --only` 로 적용한다.
    제안 파일에는 모델 답 원본(`replies`)도 남긴다 — 걸러내는 규칙을 고칠 때
    다시 묻지 않게(`retag_reports` 와 같은 방식).

사용
    python -m scripts.audit_form_categories                  # 제안만 만든다
    python -m scripts.audit_form_categories --dry-run        # 프롬프트만 보고 만다
    python -m scripts.audit_form_categories --apply          # 제안 전부 적용
    python -m scripts.audit_form_categories --apply --only t-015,t-042
"""
from __future__ import annotations

import argparse
import collections
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

from scripts import jsonio
from scripts.assign_secondary import MAX_PER_THREAD
from scripts.llm import DEFAULT_MODEL, TIMEOUT_SEC, call_claude, parse_reply
from scripts.tag_surgery import backup_dir, shown
from scripts.topic_reports import load_reports

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
TOPICS = OUT / "topics.json"
MESSAGES = OUT / "messages.jsonl"
SECONDARY = OUT / "secondary_categories.json"

# 감사 대상. '형식·행위' 를 가리키는 분류들이다. 목적지로는 쓰지 않는다.
FORM_CATEGORIES = ("news-articles", "chat")

# 한 번에 물어볼 주제 수. 42개 × 보고서 = 10KB 라 한 번에도 들어가지만, 판정마다
# 열두 분류의 정의를 다시 읽게 해서 뒤로 갈수록 뭉개지는 것을 막는다.
BATCH = 25


def proposal_paths(day: str) -> tuple[Path, Path]:
    return (OUT / ("recat-proposal-%s.json" % day),
            OUT / ("recat-proposal-%s.md" % day))


def targets(threads: list[dict], categories: tuple[str, ...] = FORM_CATEGORIES
            ) -> list[str]:
    """감사할 주제 id. 원장 순서(= 시간순)로 돌려준다."""
    wanted = set(categories)
    return [t["id"] for t in threads if t.get("category") in wanted]


def dates_of(threads: list[dict], messages: list[dict]) -> dict[str, str]:
    """주제 id → 첫 메시지 날짜. 날짜를 못 찾은 주제는 표에 없다."""
    when = {m["id"]: m.get("date") or "" for m in messages}
    out: dict[str, str] = {}
    for t in threads:
        days = sorted(d for d in (when.get(mid) for mid in t.get("message_ids") or [])
                      if d)
        if days:
            out[t["id"]] = days[0]
    return out


def build_prompt(items: list[dict], categories: list[dict]) -> str:
    """무엇을 실을지가 이 함수의 판단이다.

    보고서 본문까지 싣고 **원문 메시지는 싣지 않는다.** 발행 단위는 보고서이고,
    보고서로 판단이 안 서는 주제는 옮기지 않는 것이 맞다. 원문을 실으면 프롬프트가
    커지는 것보다 나쁜 일이 생긴다 — 형식만 보고 옮기게 된다(링크가 여럿이면
    뉴스, 인사말이 있으면 잡담).
    """
    cat_lines = "\n".join("  %-16s %s" % (c["id"], c["label"]) for c in categories)
    form_lines = " · ".join("%s(%s)" % (c["id"], c["label"]) for c in categories
                            if c["id"] in FORM_CATEGORIES)

    blocks = []
    for it in items:
        blocks.append(
            "### %s  [지금: %s]  %s  대화 %d건\n제목: %s\n요지: %s\n태그: %s\n"
            "보조 분류: %s\n보고서:\n%s"
            % (it["id"], it["category"], it.get("date") or "날짜 모름", it["count"],
               it["title"], it["summary"],
               ", ".join(it["keywords"]) or "(없음)",
               ", ".join(it["also"]) or "(없음)",
               it["report"] or "(보고서 없음)")
        )
    body = "\n\n".join(blocks)
    ids = ", ".join(it["id"] for it in items)
    form_names = " · ".join(FORM_CATEGORIES)

    return f"""사회복지 종사자들의 AI 활용 카카오톡 아카이브다. 주제마다 분류가 하나씩
붙어 있는데, 열두 분류 가운데 둘은 '무엇을 이야기했나' 가 아니라 **'어떤 꼴로
오갔나'** 를 가리킨다 — {form_lines}.

그 두 곳에 든 주제 {len(items)}개를 다시 본다. 그 안에 **실제 주제가 있는 것**은
그 주제의 분류로 옮기고, 정말로 형식이 본체인 것은 그대로 둔다. 링크를 붙였다는
사실은 화면이 '공유 링크' 로 이미 안다 — 분류가 할 일은 무엇을 이야기했나다.

### 분류 열두 개
{cat_lines}

### 옮기는 기준 — 하나라도 어긋나면 그대로 둔다
- 보고서가 **다른 분류의 정의에 분명히 드는 주제 하나**를 다룰 때만 옮긴다.
- 뉴스·자료를 **여러 건 늘어놓은 것**은 그대로 둔다. 묶는 주제가 없다.
- **인사·안부·잡담이 본체**인 것은 그대로 둔다. 곁가지로 다른 이야기가 스쳐도
  옮기지 않는다.
- **두 분류에 반씩 걸친 것**은 그대로 둔다. 그건 보조 분류가 할 일이고, 주 분류를
  옮기면 오히려 잃는다.
- 목적지는 위 열두 id 중 하나다. **{form_names} 로는 옮기지 않는다.**
- 확신이 없으면 두는 편이 낫다. 두는 것은 나중에 다시 볼 수 있지만, 잘못 옮긴 것은
  그 분류의 요지 산문까지 틀리게 만든다.

### 주제
{body}

### 답
JSON 만. 설명·코드펜스 없이. {len(items)}개 전부({ids})가 `moves` 나 `kept` 어느
한쪽에 있어야 한다. `reason` 은 한 줄로, 원문을 인용하지 말고.

{{"moves":[{{"id":"t-015","to":"ai-models","reason":"모델 장애 대응을 처음부터 끝까지 다룬다"}}],
 "kept":[{{"id":"t-042","reason":"링크 넉 건을 늘어놓은 것이라 묶는 주제가 없다"}}]}}"""


def ask(items_by_id: dict[str, dict], ids: list[str], categories: list[dict],
        model: str, batch_size: int, timeout: int) -> list[dict]:
    """배치로 나눠 물어 **다듬지 않은 답**을 모은다. 실패한 배치는 건너뛴다."""
    replies: list[dict] = []
    total = (len(ids) + batch_size - 1) // batch_size
    for n in range(total):
        chunk = ids[n * batch_size:(n + 1) * batch_size]
        items = [items_by_id[t] for t in chunk]
        print("배치 %d/%d — %d개 (%s ~ %s)"
              % (n + 1, total, len(chunk), chunk[0], chunk[-1]))
        reply = parse_reply(
            call_claude(build_prompt(items, categories), model, timeout,
                        "형식 분류 감사") or "")
        if not reply:
            print("  답을 받지 못해 이 배치는 건너뜁니다 — 다음 실행이 다시 봅니다.")
            continue
        replies.append(reply)
    return replies


def screen(replies: list[dict], asked: list[str], main_of: dict[str, str],
           valid_cats: set[str]) -> tuple[list[dict], list[dict]]:
    """답을 규칙에 걸러 (옮길 것, 두는 것) 으로 만든다. 호출하지 않는다.

    여기서 너그러우면 지어낸 분류 id 가 원장에 들어간다. `topics.json` 의 category
    가 `categories` 목록 밖이면 발행이 그 주제를 어느 카드에도 담지 못하고, 통계
    합계가 조용히 어긋난다 — 그래서 목록에 없는 목적지는 버린다.
    """
    ask_set = set(asked)
    moves: dict[str, dict] = {}
    kept: dict[str, dict] = {}

    for reply in replies:
        for row in reply.get("moves") or []:
            if not isinstance(row, dict):
                continue
            tid, to = row.get("id"), row.get("to")
            if tid not in ask_set or tid in moves:
                continue
            if to not in valid_cats:
                print("  %s: 목록에 없는 분류 '%s' — 버립니다" % (tid, to))
                continue
            if to in FORM_CATEGORIES:
                print("  %s: 형식 분류 '%s' 로는 옮기지 않습니다 — 버립니다" % (tid, to))
                continue
            if to == main_of.get(tid):
                continue      # 지금과 같은 곳. 옮길 것이 없다
            moves[tid] = {"id": tid, "from": main_of[tid], "to": to,
                          "reason": str(row.get("reason") or "").strip()}
        for row in reply.get("kept") or []:
            if not isinstance(row, dict):
                continue
            tid = row.get("id")
            if tid in ask_set and tid not in kept:
                kept[tid] = {"id": tid, "reason": str(row.get("reason") or "").strip()}

    # 어느 쪽에도 없는 것은 '두는 것' 으로 본다. 답이 빠진 것과 두라는 답을
    # 가르지 않는다 — 어느 쪽이든 결과가 같고(안 옮긴다), 표에는 그대로 적힌다.
    for tid in asked:
        if tid not in moves and tid not in kept:
            kept[tid] = {"id": tid, "reason": "(답이 없어 그대로 둡니다)"}
    for tid in moves:
        kept.pop(tid, None)

    return ([moves[t] for t in asked if t in moves],
            [kept[t] for t in asked if t in kept])


def render_markdown(moves: list[dict], kept: list[dict], titles: dict[str, str],
                    labels: dict[str, str], day: str, model: str) -> str:
    """사람이 읽을 제안서. 실명이 들어갈 자리가 없다 — 제목·분류·이유뿐이다."""
    def rows(items: list[dict], with_dest: bool) -> str:
        out = []
        for it in items:
            title = (titles.get(it["id"]) or "").replace("|", "／")
            reason = (it.get("reason") or "").replace("|", "／").replace("\n", " ")
            if with_dest:
                out.append("| %s | %s | %s → %s | %s |"
                           % (it["id"], title,
                              labels.get(it["from"], it["from"]),
                              labels.get(it["to"], it["to"]), reason))
            else:
                out.append("| %s | %s | %s |" % (it["id"], title, reason))
        return "\n".join(out) or ("| — | (없음) | — | — |" if with_dest
                                  else "| — | (없음) | — |")

    spread = collections.Counter(m["to"] for m in moves)
    spread_lines = "\n".join(
        "- %s ← %d개" % (labels.get(c, c), n)
        for c, n in spread.most_common()) or "- (옮길 것이 없습니다)"
    scope = " · ".join(labels.get(c, c) for c in FORM_CATEGORIES)

    return f"""# 형식 분류 감사 제안서 — {day}

- 대상: {scope} 에 든 주제 {len(moves) + len(kept)}개
- 모델: {model}
- **아직 한 글자도 안 바꿨습니다.** 적용은 아래 명령입니다.

## 옮길 것 {len(moves)}개

| id | 지금 제목 | from → to | 이유 |
|---|---|---|---|
{rows(moves, True)}

{spread_lines}

## 그대로 둘 것 {len(kept)}개

| id | 지금 제목 | 이유 |
|---|---|---|
{rows(kept, False)}

## 적용

```
python -m scripts.audit_form_categories --apply
python -m scripts.audit_form_categories --apply --only t-015,t-042
```
"""


def apply_proposal(proposal: dict, day: str, only: set[str] | None = None
                   ) -> tuple[list[dict], list[str], Path]:
    """제안대로 주 분류를 옮기고 옛 분류를 보조로 덧붙인다.

    돌려주는 것은 (옮긴 것, 건너뛴 이유들, 백업 폴더). 여러 번 돌려도 같다 —
    이미 목적지에 있는 주제는 건너뛴다.

    보조 분류를 덧붙이는 것은 잃지 않기 위해서다. '뉴스로 공유된 논문' 이라는
    사실은 그 자체로 찾는 길이었고, 주 분류를 옮기면 그 길이 끊긴다. 다만 주
    분류와 보조가 같으면 안 되므로(같은 것을 두 번 세는 꼴이다) 목적지가 이미
    보조에 있으면 그 항목을 지운다.
    """
    backup = backup_dir("recat", day)
    for p in (TOPICS, SECONDARY):
        if p.is_file():
            shutil.copy2(p, backup / p.name)

    topics = jsonio.read_json(TOPICS)
    by_id = {t["id"]: t for t in topics["threads"]}
    valid_cats = {c["id"] for c in topics["categories"]}
    sec_doc = jsonio.read_json(SECONDARY) if SECONDARY.is_file() else {}
    secondary = dict(sec_doc.get("secondary") or {})

    done: list[dict] = []
    skipped: list[str] = []
    for mv in proposal.get("moves") or []:
        tid, frm, to = mv.get("id"), mv.get("from"), mv.get("to")
        if only is not None and tid not in only:
            continue
        t = by_id.get(tid)
        if not t:
            skipped.append("%s: 원장에 없는 주제입니다" % tid)
            continue
        if to not in valid_cats or to in FORM_CATEGORIES:
            skipped.append("%s: 목적지 '%s' 를 쓸 수 없습니다" % (tid, to))
            continue
        if t["category"] == to:
            skipped.append("%s: 이미 %s 입니다 — 건너뜁니다" % (tid, to))
            continue
        if t["category"] != frm:
            # 제안을 만든 뒤 원장이 바뀌었다. 그때 판단이 지금 원장에 맞는지
            # 알 수 없으므로 손대지 않는다.
            skipped.append("%s: 지금 분류가 %s 라 제안(%s)과 다릅니다 — 건너뜁니다"
                           % (tid, t["category"], frm))
            continue

        t["category"] = to
        also = [c for c in (secondary.get(tid) or []) if c != to]
        if frm not in also:
            if len(also) < MAX_PER_THREAD:
                also.append(frm)
            else:
                skipped.append("%s: 보조 분류가 이미 %d개라 옛 분류 %s 를 못 붙였습니다"
                               % (tid, MAX_PER_THREAD, frm))
        if also:
            secondary[tid] = also
        else:
            secondary.pop(tid, None)
        done.append(dict(mv))

    jsonio.write_json(TOPICS, topics)
    sec_doc["secondary"] = dict(sorted(secondary.items()))
    jsonio.write_json(SECONDARY, sec_doc)
    return done, skipped, backup


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true",
                    help="제안 파일을 읽어 원장을 바꾼다 (호출 없음)")
    ap.add_argument("--only", help="쉼표로 나눈 주제 id — 이것만 적용한다")
    ap.add_argument("--dry-run", action="store_true",
                    help="프롬프트만 만들어 보고 만다 (호출 없음)")
    ap.add_argument("--stats", action="store_true", help="대상 수만 센다 (호출 없음)")
    ap.add_argument("--rescreen", action="store_true",
                    help="제안에 담긴 답에 규칙을 다시 걸어 제안을 새로 쓴다 (호출 없음)")
    ap.add_argument("--batch", type=int, default=BATCH)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--timeout", type=int, default=TIMEOUT_SEC)
    ap.add_argument("--day", default=datetime.now().strftime("%Y%m%d"),
                    help="제안 파일 이름의 날짜 (기본: 오늘)")
    args = ap.parse_args()

    json_path, md_path = proposal_paths(args.day)
    only = ({x.strip() for x in args.only.split(",") if x.strip()}
            if args.only else None)

    if args.apply:
        if not json_path.is_file():
            print("제안 파일이 없습니다: %s" % shown(json_path))
            return 1
        proposal = json.loads(json_path.read_text(encoding="utf-8"))
        if not (proposal.get("moves") or []):
            print("제안에 옮길 것이 없습니다.")
            return 0
        done, skipped, backup = apply_proposal(proposal, args.day, only)
        spread: collections.Counter = collections.Counter()
        for mv in done:
            spread[mv["from"]] -= 1
            spread[mv["to"]] += 1
        print("주제 %d개를 옮겼습니다." % len(done))
        for cid, n in sorted(spread.items(), key=lambda r: (-r[1], r[0])):
            print("  %-16s %+d" % (cid, n))
        for s in skipped:
            print("  건너뜀 — %s" % s)
        print("\n백업: %s/ (바꾸기 전 topics.json · secondary_categories.json)"
              % shown(backup))
        print("다음: python -m scripts.build_site  → 테스트 → 발행")
        return 0

    topics = jsonio.read_json(TOPICS)
    threads = topics["threads"]
    categories = topics["categories"]
    reports = load_reports()
    sec_doc = jsonio.read_json(SECONDARY) if SECONDARY.is_file() else {}
    secondary = sec_doc.get("secondary") or {}
    when = dates_of(threads, jsonio.read_jsonl(MESSAGES)) if MESSAGES.is_file() else {}

    ids = targets(threads)
    by_id = {t["id"]: t for t in threads}
    spread = collections.Counter(by_id[t]["category"] for t in ids)
    print("감사 대상 %d개 — %s"
          % (len(ids), " · ".join("%s %d" % (c, n) for c, n in spread.most_common())))
    if args.stats:
        return 0
    if not ids:
        print("대상이 없습니다.")
        return 0

    items_by_id = {}
    for tid in ids:
        t = by_id[tid]
        r = reports.get(tid) or {}
        items_by_id[tid] = {
            "id": tid,
            "category": t["category"],
            "date": when.get(tid, ""),
            "count": len(t.get("message_ids") or []),
            "title": r.get("title") or t.get("title") or "",
            "summary": r.get("summary") or t.get("summary") or "",
            "keywords": r.get("keywords") or t.get("keywords") or [],
            "also": secondary.get(tid) or [],
            "report": r.get("report") or "",
        }

    if args.dry_run:
        prompt = build_prompt([items_by_id[t] for t in ids[:args.batch]], categories)
        print("\n--- 프롬프트 (첫 배치, %d자) ---\n%s" % (len(prompt), prompt))
        print("\n--- 끝 --- 호출하지 않았습니다.")
        return 0

    if args.rescreen:
        if not json_path.is_file():
            print("다시 걸 답이 없습니다: %s" % shown(json_path))
            return 1
        replies = json.loads(json_path.read_text(encoding="utf-8")).get("replies") or []
        if not replies:
            print("다시 걸 답이 없습니다: %s" % shown(json_path))
            return 1
        print("  답 %d배치를 규칙에 다시 겁니다 (호출 없음)." % len(replies))
    else:
        replies = ask(items_by_id, ids, categories, args.model, args.batch,
                      args.timeout)
        if not replies:
            print("\n답을 하나도 받지 못했습니다.")
            return 1

    main_of = {t: by_id[t]["category"] for t in ids}
    valid_cats = {c["id"] for c in categories}
    moves, kept = screen(replies, ids, main_of, valid_cats)

    print("\n옮길 것 %d개 · 그대로 둘 것 %d개" % (len(moves), len(kept)))
    for cid, n in collections.Counter(m["to"] for m in moves).most_common():
        print("  %-16s ← %d개" % (cid, n))

    labels = {c["id"]: c["label"] for c in categories}
    titles = {t: items_by_id[t]["title"] for t in ids}
    OUT.mkdir(parents=True, exist_ok=True)
    jsonio.write_json(json_path, {
        "made": datetime.now().isoformat(timespec="seconds"),
        "model": args.model,
        "asked": ids,
        "moves": moves,
        "kept": kept,
        "replies": replies,
    })
    md_path.write_text(
        render_markdown(moves, kept, titles, labels, args.day, args.model),
        encoding="utf-8")
    print("\n제안 → %s" % shown(json_path))
    print("       %s (사람이 읽는 표)" % shown(md_path))
    print("원장은 아직 한 글자도 안 바꿨습니다. 적용:")
    print("  python -m scripts.audit_form_categories --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
