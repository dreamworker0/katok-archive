# -*- coding: utf-8 -*-
"""한 대화인데 갈린 주제들을 하나로 합친다 — audit_same_day 의 제안을 반영한다.

남기는 번호
  묶음에서 **가장 먼저 시작한 주제**의 번호를 남긴다. 사라진 번호는
  output/retired-thread-ids.json 에 적고, 새 주제 번호(classify_unsorted.next_thread_id)
  가 그 번호를 다시 쓰지 않게 한다 — 다시 쓰면 예전에 건넨 주제 주소가 엉뚱한
  주제를 가리킨다.

함께 고치는 것
  topics.json            메시지를 모으고, 제목·요지를 묶음 제안의 것으로
  secondary_categories   보조 분류를 합집합으로(주 분류는 빼고)
  knowledge.json         그래프 근거(evidence)의 사라진 번호를 남는 번호로
  ai-reports-skipped     묶음에 든 번호를 지운다 — 합친 내용으로 다시 판단한다
  reports·ai-reports     사라진 주제의 .md 는 지우지 않고 백업으로 옮긴다

건너뛰는 것
  관리자가 발행에서 뺀 주제(member_requests.hidden_threads)가 든 묶음 — 합치면
  빼 둔 것이 되살아나거나 멀쩡한 대화까지 빠진다. 목록으로만 알린다.

반영한 뒤 다시 써야 할 보고서가 output/merge-applied.json 에 남고, 그 명령을 출력한다.

    python -m scripts.merge_threads                         # 보여주기만 (high)
    python -m scripts.merge_threads --confidence medium     # medium 까지 보여주기
    python -m scripts.merge_threads --apply                 # 반영
    python -m scripts.merge_threads --groups t-1+t-2 --apply   # 손으로 지정
"""
from __future__ import annotations

import argparse
import shutil
from datetime import date
from pathlib import Path

from scripts import member_requests
from scripts.jsonio import read_json, read_jsonl, write_json

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
TOPICS = OUTPUT / "topics.json"
MESSAGES = OUTPUT / "messages.jsonl"
PROPOSAL = OUTPUT / "same-day-merge.json"
SECONDARY = OUTPUT / "secondary_categories.json"
KNOWLEDGE = OUTPUT / "knowledge.json"
AI_SKIPS = OUTPUT / "ai-reports-skipped.json"
REPORTS = OUTPUT / "reports"
AI_REPORTS = OUTPUT / "ai-reports"
RETIRED = OUTPUT / "retired-thread-ids.json"
APPLIED = OUTPUT / "merge-applied.json"


def load_retired() -> list[str]:
    return list(read_json(RETIRED)) if RETIRED.exists() else []


def proposed_groups(want_medium: bool, only: str | None = None) -> list[dict]:
    if not PROPOSAL.exists():
        return []
    # 사람이 읽고 뺀 묶음은 confidence 를 'rejected' 로 바꿔 둔다 — 지우지 않는 것은
    # 감사를 다시 돌려도 같은 제안이 되살아날 때 왜 뺐는지 남기려는 것이다.
    take = {only} if only else ({"high", "medium"} if want_medium else {"high"})
    out = []
    for gs in (read_json(PROPOSAL).get("days") or {}).values():
        for g in gs:
            if g["confidence"] in take:
                out.append(g)
    return out


def combine(groups: list[dict]) -> list[dict]:
    """여러 날에 걸친 주제는 날마다 다른 묶음에 들 수 있다. 겹치는 묶음을 잇는다."""
    out: list[dict] = []
    for g in groups:
        ids = set(g["threads"])
        hit = [o for o in out if o["ids"] & ids]
        merged = {"ids": set(ids), "parts": [g]}
        for o in hit:
            merged["ids"] |= o["ids"]
            merged["parts"] = o["parts"] + merged["parts"]
            out.remove(o)
        out.append(merged)
    return out


def plan(topics: dict, groups: list[dict]) -> tuple[list[dict], list[dict]]:
    by_id = {t["id"]: t for t in topics["threads"]}
    hidden = set(member_requests.load_hidden_threads())
    todo, skipped = [], []
    for c in combine(groups):
        ids = sorted((i for i in c["ids"] if i in by_id),
                     key=lambda i: by_id[i]["message_ids"][0])
        if len(ids) < 2:
            # 하나만 남았으면 이미 합친 묶음이다(밤마다 같은 제안 파일을 다시 읽는다).
            # 둘 다 없을 때만 알린다 — 그건 다른 일로 주제가 사라진 것이다.
            if not ids:
                skipped.append({"ids": sorted(c["ids"]), "why": "지금은 없는 주제"})
            continue
        if hidden & set(ids):
            skipped.append({"ids": ids, "why": "발행에서 뺀 주제가 들어 있음: "
                            + ", ".join(sorted(hidden & set(ids)))})
            continue
        # 제목·요지는 가장 큰 제안의 것 — 여러 제안이 이어졌으면 가장 넓게 본 것이다.
        best = max(c["parts"], key=lambda g: len(g["threads"]))
        biggest = max(ids, key=lambda i: (len(by_id[i]["message_ids"]), -ids.index(i)))
        todo.append({"keep": ids[0], "drop": ids[1:], "ids": ids,
                     "category": by_id[biggest]["category"],
                     "title": best.get("title") or by_id[ids[0]]["title"],
                     "summary": best.get("summary") or by_id[ids[0]].get("summary", ""),
                     "reasons": [g.get("reason", "") for g in c["parts"]],
                     "confidence": min((g["confidence"] for g in c["parts"]),
                                       key=lambda x: x != "medium")})
    return todo, skipped


def apply(topics: dict, todo: list[dict]) -> None:
    by_id = {t["id"]: t for t in topics["threads"]}
    gone = set()
    for g in todo:
        keep = by_id[g["keep"]]
        mids = sorted({m for i in g["ids"] for m in by_id[i]["message_ids"]})
        kws: list[str] = []
        for i in g["ids"]:
            kws += [k for k in by_id[i].get("keywords") or [] if k not in kws]
        origin = next((by_id[i]["reply_origin"] for i in g["ids"]
                       if by_id[i].get("reply_origin")
                       and by_id[i]["reply_origin"].get("parent") not in mids), None)
        keep.update(message_ids=mids, start_msg=mids[0], end_msg=mids[-1],
                    title=g["title"], summary=g["summary"], keywords=kws,
                    category=g["category"])
        if origin:
            keep["reply_origin"] = origin
        else:
            keep.pop("reply_origin", None)
        gone.update(g["drop"])
    topics["threads"] = [t for t in topics["threads"] if t["id"] not in gone]


def fix_side_files(todo: list[dict], bak: Path) -> None:
    to_keep = {d: g["keep"] for g in todo for d in g["drop"]}

    if SECONDARY.exists():
        sec = read_json(SECONDARY)
        for key, val in sec.items():
            if isinstance(val, dict):
                for g in todo:
                    union = set()
                    for i in g["ids"]:
                        union |= set(val.pop(i, []))
                    union.discard(g["category"])
                    if union:
                        val[g["keep"]] = sorted(union)
            elif isinstance(val, list):
                sec[key] = [i for i in val if i not in to_keep]
        write_json(SECONDARY, sec)

    if KNOWLEDGE.exists():
        kn = read_json(KNOWLEDGE)
        for e in kn.get("edges", []):
            ev = e.get("evidence")
            if isinstance(ev, list):
                e["evidence"] = list(dict.fromkeys(to_keep.get(i, i) for i in ev))
        write_json(KNOWLEDGE, kn)

    if AI_SKIPS.exists():
        skips = read_json(AI_SKIPS)
        for g in todo:
            for i in g["ids"]:
                skips.pop(i, None)
        write_json(AI_SKIPS, skips)

    for d in to_keep:
        for folder in (REPORTS, AI_REPORTS):
            p = folder / f"{d}.md"
            if p.exists():
                dst = bak / folder.name
                dst.mkdir(exist_ok=True)
                shutil.move(str(p), str(dst / p.name))

    write_json(RETIRED, sorted(set(load_retired()) | set(to_keep)))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="실제로 고친다(기본은 보여주기만)")
    ap.add_argument("--confidence", choices=["high", "medium"], default="high")
    ap.add_argument("--groups", default="",
                    help="제안 대신 손으로: t-1+t-2,t-3+t-4 (제목·요지는 앞 주제의 것)")
    args = ap.parse_args()

    topics = read_json(TOPICS)
    if args.groups:
        groups = [{"threads": g.split("+"), "confidence": "high", "reason": "손으로 지정"}
                  for g in args.groups.split(",") if "+" in g]
    else:
        groups = proposed_groups(args.confidence == "medium")
    todo, skipped = plan(topics, groups)

    by_id = {t["id"]: t for t in topics["threads"]}
    msgs = {m["id"]: m for m in read_jsonl(MESSAGES)}
    print(f"합칠 묶음 {len(todo)}개 · 사라질 주제 {sum(len(g['drop']) for g in todo)}개")
    for g in todo:
        day = msgs.get(by_id[g["keep"]]["message_ids"][0], {}).get("date", "")
        print(f"\n  [{g['confidence']}] {day}  → {g['keep']} '{g['title']}'")
        for i in g["ids"]:
            print(f"      {i} ({len(by_id[i]['message_ids'])}건) {by_id[i]['title']}")
        for r in g["reasons"]:
            print(f"      · {r}")
    for s in skipped:
        print(f"\n  [건너뜀] {', '.join(s['ids'])}: {s['why']}")
    # 자동으로 합치지 않는 medium 가운데 아직 남은 것 — 사람이 읽고 정할 몫이다.
    # 실측 2026-10-03: medium 18개 중 4개는 통째로 합치면 안 되는 것이었다
    # (메시지 한두 건만 잘못 붙은 경우). 정했으면 그 묶음을 'rejected' 로 바꾸거나
    # --confidence medium --apply 로 합친다.
    if not args.groups and args.confidence == "high":
        pending, _ = plan(topics, proposed_groups(False, only="medium"))
        for g in pending:
            print(f"\n  [확인 필요·medium] {' + '.join(g['ids'])} → '{g['title']}'")
            for r in g["reasons"]:
                print(f"      · {r}")
        print(f"PENDING_MEDIUM={len(pending)}")

    if not args.apply:
        print("\n(--apply 를 주면 실제로 고칩니다. 지금은 아무것도 쓰지 않았습니다.)")
        return 0
    if not todo:
        print("MERGE_REWRITE=")
        return 0

    bak = OUTPUT / f"backup-merge-{date.today():%Y%m%d}"
    bak.mkdir(parents=True, exist_ok=True)
    for f in (TOPICS, SECONDARY, KNOWLEDGE, AI_SKIPS):
        if f.exists() and not (bak / f.name).exists():
            shutil.copy2(f, bak / f.name)
    for g in todo:                       # 남는 주제의 옛 보고서도 떠 둔다
        for folder in (REPORTS, AI_REPORTS):
            p = folder / f"{g['keep']}.md"
            if p.exists():
                (bak / folder.name).mkdir(exist_ok=True)
                if not (bak / folder.name / p.name).exists():
                    shutil.copy2(p, bak / folder.name / p.name)

    apply(topics, todo)
    write_json(TOPICS, topics)
    fix_side_files(todo, bak)

    rewrite = [g["keep"] for g in todo]
    write_json(APPLIED, {"groups": todo, "rewrite": rewrite, "backup": bak.name})
    print(f"\n고쳤습니다. 백업: {bak.name}/")
    print(f"  보고서 다시 쓰기 {len(rewrite)}편:")
    print(f"    python -m scripts.classify_unsorted --rewrite-ids {','.join(rewrite)}")
    print(f"    python -m scripts.ai_reports --ids {','.join(rewrite)}")
    print(f"MERGE_REWRITE={','.join(rewrite)}")     # run_daily.ps1 이 읽는 표식
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
