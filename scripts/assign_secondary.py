# -*- coding: utf-8 -*-
"""주제마다 '보조 분류'를 붙인다 — 한 주제를 여러 분류에서 찾을 수 있게.

분류는 사실이 아니라 **찾는 길**이다. '차량운행일지 슬랙 연동'은 프로젝트이면서
AI 도구 이야기이고, '가온 교수 대시보드'는 프로젝트이면서 복지 실천 이야기다.
길이 하나뿐이면 다른 길로 들어온 사람은 못 찾는다.

그래서 주 분류(topics.json 의 category)는 **그대로 하나로 둔다** — 통계·요지의
메시지 수 합계, 파이어스토어 증분 동기화가 모두 '한 주제 = 한 분류'를 전제로
서 있고, 복제해 넣으면 숫자가 이중으로 세어진다. 대신 보조 분류를 따로 적어
두고, 화면에서 "여기서도 볼 만한 주제"로 함께 보여 준다.

결과는 `output/secondary_categories.json` 에 쌓인다(주제 id → 분류 id 목록).
이미 판정한 주제는 다시 묻지 않으므로, 매일 새로 생긴 주제만 비용이 든다.

    python -m scripts.assign_secondary            # 새로 생긴 주제만
    python -m scripts.assign_secondary --all      # 전부 다시 판정
    python -m scripts.assign_secondary --dry-run  # 호출 없이 대상만 보기
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scripts.llm import DEFAULT_MODEL, call_claude
from scripts.topic_reports import load_reports

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
TOPICS = OUT / "topics.json"
SECONDARY = OUT / "secondary_categories.json"

# 한 번에 물어볼 주제 수. 너무 크면 판단이 뭉개지고, 너무 작으면 호출이 늘어난다.
BATCH = 40

# 보조 분류 상한. 셋 넘게 걸리는 주제는 사실 아무 데도 안 걸리는 주제다.
MAX_PER_THREAD = 2


def build_prompt(rows: list[dict], categories: list[dict],
                 encourage: bool = False) -> str:
    """`encourage` 는 '다시 묻기' 용이다.

    첫 판정에서 '대부분은 0개가 맞다'고 못박았더니 314개 중 112개만 보조 분류를
    받았고, 대화 10건 넘는 주제 62개가 빈 채였다 — 그중에는 API 키 노출 사고(보안)나
    앱스스크립트 팀 시스템(도구)처럼 두 분야를 실제로 걸친 것이 섞여 있었다.
    다시 물을 때는 그 못박음을 뺀다. 기준 자체는 그대로다 — '상당히 다뤘는가'.
    """
    stance = ("- 보조 분류는 0개~%d개. 이 방의 대화는 두 분야를 실제로 걸치는 일이\n"
              "  잦다. 걸쳤으면 달고, 아니면 달지 마세요." % MAX_PER_THREAD
              if encourage else
              "- 보조 분류는 0개~%d개. **대부분은 0개가 맞다.** 억지로 채우지 말 것."
              % MAX_PER_THREAD)
    return _prompt_body(rows, categories, stance)


def _prompt_body(rows: list[dict], categories: list[dict], stance: str) -> str:
    cat_lines = "\n".join(f"  {c['id']}: {c['label']}" for c in categories)
    items = []
    for r in rows:
        tags = ", ".join(r.get("tags") or []) or "(없음)"
        items.append(
            f"- {r['id']} [주 분류: {r['category']}]\n"
            f"  제목: {r['title']}\n"
            f"  요지: {r['summary']}\n"
            f"  태그: {tags}"
        )
    return f"""사회복지 종사자들의 AI 활용 카카오톡 아카이브다. 주제마다 분류가 하나씩
붙어 있는데, 한 길로만 찾게 되어 아쉬운 주제가 있다. 각 주제에 **보조 분류**를
달아 다른 분류에서도 찾을 수 있게 하려 한다.

분류 목록:
{cat_lines}

규칙:
{stance}
- 주 분류는 절대 다시 적지 말 것.
- 그 분류를 찾는 사람이 이 주제를 보고 "찾던 게 이거다" 할 때만 달 것.
  주제가 그 분류의 내용을 실제로 **상당히** 담고 있어야 한다. 스쳐 지나가는
  언급은 이유가 안 된다.
- chat(일상·잡담)은 보조로 달지 말 것 — 잡담을 찾아 들어오는 사람은 없다.

판정할 주제:
{chr(10).join(items)}

JSON 만 출력한다. 설명·코드블록 없이:
{{"assign":[{{"id":"t-002","also":["projects"]}}]}}
보조 분류가 없는 주제는 목록에서 빼면 된다."""


def parse_reply(text: str, valid_ids: set[str], cats: set[str],
                main_of: dict[str, str]) -> dict[str, list[str]]:
    """응답에서 판정을 꺼낸다. 규칙을 어긴 항목은 조용히 버린다."""
    s = text.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1].rsplit("```", 1)[0]
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end < 0:
        return {}
    try:
        data = json.loads(s[start:end + 1])
    except json.JSONDecodeError:
        return {}

    out: dict[str, list[str]] = {}
    for row in data.get("assign") or []:
        tid = row.get("id")
        if tid not in valid_ids:
            continue
        also = []
        for cid in row.get("also") or []:
            if cid in cats and cid != main_of.get(tid) and cid != "chat" and cid not in also:
                also.append(cid)
        if also:
            out[tid] = also[:MAX_PER_THREAD]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="이미 판정한 주제도 다시")
    ap.add_argument("--recheck-empty", type=int, metavar="N", default=0,
                    help="보조 분류가 없는 주제 중 대화 N건 이상인 것만 다시 판정")
    ap.add_argument("--dry-run", action="store_true", help="호출 없이 대상만 보기")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    args = ap.parse_args()

    topics = json.loads(TOPICS.read_text(encoding="utf-8"))
    threads = topics["threads"]
    categories = topics["categories"]
    cats = {c["id"] for c in categories}
    main_of = {t["id"]: t["category"] for t in threads}
    reports = load_reports()

    prev: dict[str, list[str]] = {}
    if SECONDARY.exists() and not args.all:
        prev = json.loads(SECONDARY.read_text(encoding="utf-8")).get("secondary") or {}
    # 이미 물어본 주제는 다시 묻지 않는다 — '보조 없음' 도 답이라 따로 적어 둔다.
    asked = set(json.loads(SECONDARY.read_text(encoding="utf-8")).get("asked") or []) \
        if (SECONDARY.exists() and not args.all) else set()

    rows = []
    for t in threads:
        if args.recheck_empty:
            # 보조 분류가 비어 있고 대화가 어느 정도 있는 것만 다시 묻는다
            if prev.get(t["id"]) or len(t.get("message_ids") or []) < args.recheck_empty:
                continue
        elif t["id"] in asked:
            continue
        r = reports.get(t["id"]) or {}
        rows.append({
            "id": t["id"],
            "category": t["category"],
            "title": r.get("title") or t["title"],
            "summary": r.get("summary") or t.get("summary", ""),
            "tags": r.get("keywords") or [],
        })

    print(f"판정할 주제 {len(rows)}개 (전체 {len(threads)}개, 이미 판정 {len(asked)}개)")
    if args.dry_run or not rows:
        return 0

    result = dict(prev)
    done = set(asked)
    for i in range(0, len(rows), BATCH):
        batch = rows[i:i + BATCH]
        print(f"  {i + 1}~{i + len(batch)} 판정 중…")
        reply = call_claude(
            build_prompt(batch, categories, encourage=bool(args.recheck_empty)),
            args.model)
        if reply is None:
            print("  실패 — 여기까지만 저장하고 멈춥니다(다음 실행이 이어서 합니다).")
            break
        got = parse_reply(reply, {b["id"] for b in batch}, cats, main_of)
        result.update(got)
        done.update(b["id"] for b in batch)
        print(f"    보조 분류 붙은 주제 {len(got)}개")

    # 사라진 주제(병합·삭제)는 정리한다.
    alive = set(main_of)
    result = {k: v for k, v in result.items() if k in alive}
    done &= alive

    SECONDARY.write_text(json.dumps({
        "secondary": dict(sorted(result.items())),
        "asked": sorted(done),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"저장: {SECONDARY.name} — 보조 분류 {len(result)}개 주제 / 판정 완료 {len(done)}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())
