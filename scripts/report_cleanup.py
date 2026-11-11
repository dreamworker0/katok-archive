# -*- coding: utf-8 -*-
"""삭제·제외된 글이 든 주제의 보고서를 보류하고, 남은 글로 다시 쓴다. (2026-11-11)

왜 필요한가
    여럿이 나눈 대화에서 한 사람이 자기 글을 지워 달라고 하면, 그 글은 원장에서
    발행으로 가는 길에 빠진다(build_firestore_payload.effective_exclusions). 그런데
    주제 보고서(output/reports/{id}.md)와 AI 검증 주석은 **그 글이 있을 때** 쓴
    것이라, 인용·요약·이름이 그대로 남는다. 주제 자체는 다른 사람 글이 남아 있어
    살아남으므로 보고서도 같이 나간다 — 외부 평가(agy, 2026-11-11)가 짚었다.

사용자 결정(2026-11-11): **보류 + 다시 쓰기**
    1. 보류 — 발행본을 만들 때, 지금의 제외를 반영해 다시 쓴 적이 없는 주제는
       보고서·AI 주석을 '다시 정리하는 중' 안내로 바꿔 발행한다(withheld_ids).
    2. 다시 쓰기 — 밤 갱신이 남은 글만으로 보고서를 다시 쓴다(main). 다 쓰면
       '이 제외까지 반영했다' 고 적어 두고(output/reports-cleaned.json), 옛 AI 주석은
       백업으로 옮겨 run_daily 가 같은 밤에 새로 쓰게 한다.
    다시 쓴 뒤 제외가 또 늘면(다른 글 삭제) 반영한 목록과 달라져 다시 보류된다.

비용
    보고서 한 편 약 $0.05~0.4. 하룻밤 상한(DEFAULT_LIMIT)을 두고, 남은 것은 다음 밤에.
    같은 주제가 연달아 실패하면(MAX_TRIES) 더 부르지 않고 보류한 채 사람에게 알린다.

사용
    python -m scripts.report_cleanup            # 다시 쓴다(밤 갱신이 부른다)
    python -m scripts.report_cleanup --list     # 보류 중인 주제만 보여 준다(AI 안 부름)
"""
from __future__ import annotations

import argparse
import shutil
from datetime import date
from pathlib import Path

from scripts import jsonio

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
STATE = OUTPUT / "reports-cleaned.json"
DEFAULT_LIMIT = 5
MAX_TRIES = 3

# 보류하는 동안 화면에 나갈 말. 보고서 자리와 AI 주석 자리에 함께 쓴다.
WITHHELD_REPORT = ("이 주제는 멤버의 삭제 요청을 반영해 보고서를 다시 정리하는 중이에요. "
                   "다음 갱신 때 남은 대화로 다시 써서 올립니다.")


def pending_exclusions(topics: dict, kept_ids: set[str]) -> dict[str, list[str]]:
    """일부 글만 빠진 주제 → 빠진 글 ID 목록. 통째로 빠진 주제는 발행되지 않으므로 뺀다."""
    out: dict[str, list[str]] = {}
    for t in topics.get("threads", []):
        ids = list(t.get("message_ids") or [])
        gone = sorted(m for m in ids if m not in kept_ids)
        if gone and len(gone) < len(ids):
            out[t["id"]] = gone
    return out


def load_state() -> dict:
    if not STATE.exists():
        return {"cleaned": {}, "tries": {}}
    try:
        data = jsonio.read_json(STATE)
    except (OSError, ValueError):
        return {"cleaned": {}, "tries": {}}
    data.setdefault("cleaned", {})
    data.setdefault("tries", {})
    return data


def withheld_ids(pending: dict[str, list[str]], state: dict | None = None) -> set[str]:
    """보류할 주제 — 지금의 제외 목록을 반영해 다시 쓴 적이 없는 것."""
    cleaned = (state or load_state()).get("cleaned", {})
    return {tid for tid, gone in pending.items() if cleaned.get(tid) != gone}


def withhold(threads: list[dict], ids: set[str]) -> int:
    """발행본 스레드에서 보고서·AI 주석을 안내 문구로 바꾼다. 바꾼 수를 돌려준다."""
    n = 0
    for t in threads:
        if t.get("id") not in ids:
            continue
        t["report"] = WITHHELD_REPORT
        for k in ("ai_report", "ai_checked", "ai_models"):
            t.pop(k, None)
        t["report_withheld"] = True
        n += 1
    return n


def _current() -> tuple[dict, dict[str, list[str]], set[str]]:
    """(topics, 일부 빠진 주제, 남은 글 ID) — 발행과 같은 계산으로."""
    from scripts import build_firestore_payload as bp
    from scripts import build_site
    messages_raw = build_site._read_jsonl(OUTPUT / "messages.jsonl")
    topics = build_site._read_json(OUTPUT / "topics.json")
    exclusions = bp.effective_exclusions(messages_raw, topics)[0]
    kept, _ = bp.apply_exclusions(messages_raw, exclusions)
    kept_ids = {m["id"] for m in kept}
    return topics, pending_exclusions(topics, kept_ids), kept_ids


def _retire_ai_report(tid: str) -> bool:
    """옛 AI 주석을 백업으로 옮긴다 — 빠진 글을 근거로 썼을 수 있다."""
    from scripts.topic_reports import AI_REPORTS_DIR
    src = AI_REPORTS_DIR / ("%s.md" % tid)
    if not src.exists():
        return False
    bak = OUTPUT / ("backup-ai-cleanup-%s" % date.today().strftime("%Y%m%d"))
    bak.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(bak / src.name))
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="삭제가 든 주제 보고서를 남은 글로 다시 쓴다")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    ap.add_argument("--list", action="store_true", help="보류 중인 주제만 보여 준다")
    args = ap.parse_args()

    topics, pending, kept_ids = _current()
    state = load_state()
    todo = sorted(withheld_ids(pending, state))
    print("삭제·제외가 든 주제 %d개 중 다시 써야 할 것 %d개" % (len(pending), len(todo)))
    if args.list or not todo:
        for tid in todo:
            print("  %s (빠진 글 %d건)" % (tid, len(pending[tid])))
        print("REPORTS_WITHHELD=%d" % len(todo))
        print("CLEANED_IDS=")
        return 0

    from scripts import classify_unsorted as cu
    by_id = {t["id"]: t for t in topics["threads"]}
    examples = [t for t in topics["threads"]
                if not cu.UNSORTED_RE.match(str(t.get("id") or ""))][:12]
    done: list[str] = []
    gave_up: list[str] = []
    tried = 0
    for tid in todo:
        if state["tries"].get(tid, 0) >= MAX_TRIES:
            gave_up.append(tid)
            continue
        if tried >= args.limit:
            continue
        tried += 1
        # 남은 글만 넘긴다 — 빠진 글은 보고서를 다시 쓰는 AI 에게도 보내지 않는다.
        t = dict(by_id[tid])
        t["message_ids"] = [m for m in t.get("message_ids") or [] if m in kept_ids]
        try:
            n = cu._write_reports([t], cu.DEFAULT_MODEL, examples, False, cu.TIMEOUT_SEC)
        except Exception as e:          # 한 편의 사고가 갱신을 멈추지 않는다
            print("  %s 다시 쓰다 실패: %s" % (tid, e))
            n = 0
        if n:
            state["cleaned"][tid] = pending[tid]
            state["tries"].pop(tid, None)
            if _retire_ai_report(tid):
                print("  %s 옛 AI 주석은 백업으로 옮겼습니다 — 새로 씁니다" % tid)
            done.append(tid)
        else:
            state["tries"][tid] = state["tries"].get(tid, 0) + 1
    # 더는 일부 빠진 주제가 아니게 된 것(요청 철회 등)은 기록에서 뺀다
    for tid in list(state["cleaned"]):
        if tid not in pending:
            state["cleaned"].pop(tid)
    jsonio.write_json(STATE, state)

    left = [t for t in todo if t not in done]
    print("다시 쓴 보고서 %d편, 남은 보류 %d편" % (len(done), len(left)))
    if gave_up:
        print("  %d번 넘게 실패해 멈춘 것: %s — 손으로 보세요" % (MAX_TRIES, ", ".join(gave_up)))
    # run_daily.ps1 이 읽는 표식
    print("REPORTS_WITHHELD=%d" % len(left))
    print("CLEANED_IDS=%s" % ",".join(done))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
