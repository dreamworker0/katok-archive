# -*- coding: utf-8 -*-
"""유산 태그 재부여 — 공통 어휘가 없던 때 쓰인 보고서의 **태그만** 다시 고른다.

왜 이 파일이 있나
    태그 규칙(`topic_reports.tag_rules`)이 '이미 쓰이는 태그에서 먼저 고르라' 고
    말하기 시작한 것은 2026-08-04 부터다. 그 앞의 보고서 328편은 목록을 못 본 채
    각자 태그를 지어냈다. 실측 2026-08-21:

        2026-08     태그 169개 중 어휘 밖 23개  (14%)
        그 이전      태그 1,555개 중 967개      (45~78%)

    결과가 태그 1,091종 중 947종이 딱 한 번만 쓰인 상태다. 한 번만 쓰인 태그는
    태그 목록에 나오지도 않는다(`build_tag_index` 의 `min_count`) — 그 주제로 가는
    입구가 검색밖에 없다는 뜻이다.

    사후 봉합(표기 통일·넓은 태그 승격)으로는 1회짜리의 약 10%만 구제된다는 것을
    이미 실측했다(2026-07-29). 나머지는 애초에 **다른 말로** 지어졌으니 기계가
    합칠 근거가 없다. 그래서 어휘를 보여주고 다시 고르게 한다.

무엇을 고치고 무엇을 안 고치는가
    고침    output/reports/*.md 의 `keywords:` **한 줄**
    안 고침 본문·제목·요지, topics.json, 그 밖의 모든 것

    본문을 손대지 않는 것은 결정이다. 사람이 원문을 읽고 쓴 글이고, 방장이 기존
    보고서는 손대지 않기로 정했다. 태그는 사정이 다르다 — 글이 아니라 **색인**이고,
    색인은 나중에 다시 매길 수 있다.

    그래서 파일을 다시 렌더하지 않는다(`render_report` 를 쓰지 않는다). 프론트매터의
    keywords 줄만 제자리에서 바꾼다. 줄바꿈(이 폴더는 CRLF 다)도 그대로 둔다 —
    다시 렌더하면 git diff 가 371편 전체로 번져 무엇을 고쳤는지 안 보인다.

두 단계로 나눈 이유
    1단계(기본)   LLM 을 불러 제안을 `output/retag-proposal.json` 에 적고, 바뀌는
                  폭을 숫자로 보여준다. md 는 한 글자도 안 건드린다.
    2단계(--apply) 그 제안 파일을 읽어 적용한다. 호출은 하지 않는다.

    한 번의 호출로 300편을 갈아치우는 일이라, 무엇이 바뀌는지 보고 나서 적용해야
    한다. 나눠 두면 되돌릴 판단도 공짜다 — 제안 파일이 곧 검토 자료다.

    제안에는 **모델의 답 원본**(`replies`)도 담는다. 걸러내는 규칙(`sanitize`)을
    고칠 때마다 300편을 다시 물으면 25분과 요금제 사용량이 드는데, 답이 남아 있으면
    `--resanitize` 로 공짜로 다시 건다. 실제로 규칙을 한 번 고쳐야 했다 —
    '그 편에 없던 말' 을 다 버렸더니, 다른 편의 1회짜리 태그를 이 편으로 넓히려는
    제안까지 버려졌다(그게 이 작업이 하려던 일이다).

어휘를 얼려 쓰는 이유
    태그를 바꾸면 태그 횟수가 바뀌고, 그러면 `tags.vocabulary()` 가 내놓는 목록도
    바뀐다. 배치마다 다시 계산하면 앞 배치와 뒤 배치가 다른 목록에서 고르게 되어
    결과를 재현할 수 없다. 그래서 시작할 때 한 번 재서 제안 파일에 함께 적는다.

사용
    python -m scripts.retag_reports                  # 제안만 만든다 (300편)
    python -m scripts.retag_reports --limit 20       # 먼저 20편으로 재본다
    python -m scripts.retag_reports --apply          # 제안을 적용한다
    python -m scripts.retag_reports --stats          # 지금 상태만 센다 (호출 없음)
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
from scripts.topic_reports import (
    REPORTS_DIR,
    TAG_COUNT_MAX,
    TAG_COUNT_MIN,
    load_reports,
    tag_rules,
)
from scripts.tag_surgery import (
    apply_keyword_changes,
    backup_dir,
    replace_keywords_line,
    shown,
)

# `shown` 과 `replace_keywords_line` 은 scripts/tag_surgery.py 로 옮겼다. 네
# 스크립트가 함께 쓰는 것이라 한 곳에 두는 편이 맞다. 예전 이름으로 부르는 곳이
# 셋이고 검사도 그 이름을 쓰므로 여기 남긴다 (`jsonio`·`llm` 때와 같은 방식).
__all_reexported__ = ("shown", "replace_keywords_line")

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
TOPICS = OUT / "topics.json"
MESSAGES = OUT / "messages.jsonl"
PARTICIPANTS = OUT / "participants.json"
PROPOSAL = OUT / "retag-proposal.json"

# 태그 규칙이 어휘 목록을 보여주기 시작한 달. 이 달부터의 보고서는 이미 목록에서
# 골랐으므로 대상이 아니다 — 다시 고르게 하면 그 편의 정당한 '새 태그 1개'
# (`NEW_TAGS_ALLOWED`) 를 없앨 수도 있다.
VOCAB_SINCE = "2026-08"

# 한 번의 호출에 넣을 보고서 수. 본문이 평균 420자라 20편이면 프롬프트가 1만자
# 안쪽이다. 어휘 목록(약 1,600자)은 배치마다 다시 실리므로 너무 작게 쪼개면
# 목록만 300번 보내게 된다.
BATCH = 20

# 배치 하나에 주는 시간. 20편이면 답이 짧다(JSON 한 덩어리).
TIMEOUT_SEC = 300


# ---------------------------------------------------------------- 읽기·재기

def load_state() -> dict:
    reports = load_reports()
    topics = json.loads(TOPICS.read_text(encoding="utf-8"))
    threads = topics["threads"]
    participants = json.loads(PARTICIPANTS.read_text(encoding="utf-8"))
    places, _ = taglib.load_places()

    # build_site 가 하는 것과 같게 보고서의 태그를 스레드에 얹는다. 어휘는 이
    # 상태에서 재야 화면에 보이는 것과 같은 목록이 나온다.
    for th in threads:
        r = reports.get(th["id"])
        if r:
            th["keywords"] = r["keywords"]

    return {
        "reports": reports,
        "threads": threads,
        "by_id": {th["id"]: th for th in threads},
        "participants": participants,
        "places": places,
        "categories": {c.get("label", "") for c in topics.get("categories") or []},
    }


def message_dates() -> dict[str, str]:
    out: dict[str, str] = {}
    with MESSAGES.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            m = json.loads(line)
            out[m["id"]] = str(m.get("date") or m.get("ts") or "")[:10]
    return out


def thread_month(thread: dict, dates: dict[str, str]) -> str:
    """그 대화가 오간 달. 태그 규칙이 언제부터 있었는지와 견주는 데 쓴다."""
    days = [dates.get(i, "") for i in (thread.get("message_ids") or [])]
    days = [d for d in days if d]
    return min(days)[:7] if days else ""


def freeze_vocabulary(state: dict) -> list[str]:
    rows = taglib.vocabulary(state["threads"], state["participants"], state["places"])
    return [name for name, _ in rows]


def select_targets(state: dict, vocab: list[str], dates: dict[str, str],
                   since: str = VOCAB_SINCE) -> list[str]:
    """다시 고를 보고서. 어휘가 없던 달의 것 중 **어휘 밖 태그를 가진** 것만.

    태그가 이미 전부 어휘 안에 있으면 다시 물어 얻을 것이 없다(실측: 328편 중
    28편이 그렇다). 호출을 아끼는 것보다, 잘 붙은 것을 흔들지 않는 것이 요점이다.
    """
    keys = {taglib.fold(v) for v in vocab}
    out = []
    for tid, rep in state["reports"].items():
        th = state["by_id"].get(tid)
        if not th:
            continue
        if thread_month(th, dates) >= since:
            continue
        if any(taglib.fold(k) not in keys for k in rep["keywords"]):
            out.append(tid)
    return sorted(out)


# ---------------------------------------------------------------- 프롬프트

def build_prompt(items: list[dict], vocab: list[str], kinds: int = 0,
                 once: int = 0) -> str:
    """보고서 여러 편의 태그를 한 번에 다시 고르게 한다.

    지금 붙어 있는 태그를 함께 보여준다. 감추면 '이 대화에만 있는 고유한 이름'
    (처음 나온 도구·앱·결과물)을 모델이 본문에서 다시 찾아내야 하고, 그러면 이미
    말뭉치에 있는 표기 대신 새 말을 지어낼 여지가 생긴다. 지금 태그를 보여주고
    '그중 하나는 남겨도 된다' 고 하면, 새 말이 아니라 **있는 말**이 남는다.
    """
    blocks = []
    for it in items:
        blocks.append(
            "[%s]\n제목: %s\n요지: %s\n지금 태그: %s\n본문:\n%s"
            % (it["id"], it["title"], it["summary"],
               ", ".join(it["keywords"]) or "(없음)", it["report"])
        )
    body = "\n\n".join(blocks)
    ids = ", ".join(it["id"] for it in items)

    return f"""아래 보고서 {len(items)}편의 keywords(태그)를 **다시 고르는** 일입니다.
본문·제목·요지는 고치지 않습니다. 태그만 다시 고릅니다.

왜 다시 고르나: 이 보고서들은 공통 태그 목록이 없던 때 쓰여서, 편마다 태그를 새로
지어냈습니다. 한 번만 쓰인 태그는 태그 목록에 나오지 않습니다 — 같은 이야기를 태그로
모을 수가 없습니다.

{tag_rules(vocab, kinds, once)}

### 지금 붙어 있는 태그를 어떻게 다룰까
- 목록의 말로 말할 수 있는 것은 **목록에서 고르세요.** 지금 태그가 '제미나이 3 프로
  성능' 인데 목록에 '제미나이' 가 있으면 목록의 말을 고릅니다.
- 지금 태그 중 **이 대화에만 있는 고유한 이름** 하나는 그대로 남겨도 됩니다
  (그 대화에서 처음 나온 도구·앱·결과물 이름 같은 것). 새 말을 **지어내지는**
  마세요 — 지금 붙어 있는 말 중에서 남기는 것입니다.
- 본문을 읽고 판단하세요. 이 대화가 무엇에 관한 것인지가 기준입니다.
- **목록의 말이라도, 이 대화가 실제로 그것을 다룬 것이 아니면 넣지 마세요.** 스쳐
  지나간 말은 태그가 아닙니다. 넓은 말을 아무 데나 붙이면 그 태그를 눌러도 관계없는
  주제가 쏟아져 태그가 쓸모없어집니다 — 태그를 줄이려고 부정확해지면 안 됩니다.
- 지금 태그가 이 대화를 **정확히** 말하고 있으면 그대로 두세요. 억지로 바꿀 필요는
  없습니다.

--- 보고서 ---
{body}
--- 끝 ---

답은 JSON 만. 다른 말은 붙이지 마세요. 열쇠는 보고서 id, 값은 태그 목록입니다.
{len(items)}편 전부({ids})에 답해야 합니다.

{{"t-012": ["태그1", "태그2", "태그3"]}}"""


# ---------------------------------------------------------------- 검사

def sanitize(proposed: list, current: list[str], vocab_keys: set[str],
             people: set[str], places: set[str], categories: set[str],
             corpus_keys: set[str] | None = None
             ) -> tuple[list[str], list[str]]:
    """제안 태그를 받아들일 꼴로 다듬는다. (태그, 버린 이유 목록)

    버릴 것은 태그 하나 단위로 버리고 그 편을 통째로 되돌리지 않는다 — 태그 다섯
    중 하나가 어긋난 것을 이유로 나머지 넷을 버리면, 고치려던 문제가 그대로 남는다.
    다만 다듬은 뒤 `TAG_COUNT_MIN` 개 미만이면 부르는 쪽이 그 편을 손대지 않는다.

    `corpus_keys` 는 **말뭉치 어디에든 이미 있는** 태그다. 어휘 밖의 말을 '그 편에
    이미 붙어 있던 것' 으로만 좁혀서 받았더니, 다른 편에 있는 말을 이 편으로
    넓히려는 제안까지 '지어낸 말' 로 버렸다 — 실측 2026-08-21: 그렇게 버린 13개 중
    8개가 말뭉치에 한 번씩 있는 말이었다('MCP'·'백업'·'계정 연결'…).

    그런데 1회짜리 태그가 두 번째 편을 얻는 것이 바로 이 작업이 하려는 일이다.
    두 번 쓰이면 다음부터 추천 어휘에 오르고 태그 목록에도 나온다. 그래서 말뭉치에
    있는 말은 받고, 아주 새로 지어낸 말만 버린다.
    """
    notes: list[str] = []
    current_keys = {taglib.fold(c) for c in current}
    known_keys = current_keys | (corpus_keys or set())
    cat_keys = {taglib.fold(c) for c in categories if c}
    # 이름·카테고리는 fold 로 견준다 — 'AI 스튜디오' 를 'AI스튜디오' 로 적어 오면
    # 글자 그대로 견주는 검사는 그냥 지나친다.
    people_keys = {taglib.fold(p) for p in people}

    out: list[str] = []
    seen: set[str] = set()
    fresh = 0
    for raw in proposed if isinstance(proposed, list) else []:
        tag = re.sub(r"\s+", " ", str(raw or "")).strip()
        if not tag:
            continue
        key = taglib.fold(tag)
        if key in seen:
            continue
        if key in people_keys:
            notes.append("사람 이름 '%s' 버림" % tag)
            continue
        if key in places:
            notes.append("지명·기관 '%s' 버림" % tag)
            continue
        if key in cat_keys:
            notes.append("카테고리 이름 '%s' 버림" % tag)
            continue
        if key not in vocab_keys:
            # 어휘 밖은 '말뭉치에 이미 있는 말' 일 때만, 그것도 한 개까지만 남긴다.
            # 아주 새로 지어낸 말을 받아 주면 갚으려던 빚을 다시 지는 셈이다.
            if key not in known_keys:
                notes.append("지어낸 새 태그 '%s' 버림" % tag)
                continue
            if fresh >= 1:
                notes.append("고유 태그가 둘 이상 — '%s' 버림" % tag)
                continue
            fresh += 1
        seen.add(key)
        out.append(tag)
        if len(out) >= TAG_COUNT_MAX:
            break
    return out, notes


def canonical_name(tag: str, tag_map: dict[str, str]) -> str:
    """말뭉치가 이미 쓰는 표기로 맞춘다. 'AI Studio' 를 새로 세우지 않는다."""
    return tag_map.get(tag) or tag


# ---------------------------------------------------------------- 쓰기


# ---------------------------------------------------------------- 통계

def tag_stats(keywords_by_id: dict[str, list[str]], vocab_keys: set[str]) -> dict:
    """태그 상태를 센다. 어휘는 얼린 것을 쓴다 — 전후를 견주려면 자가 같아야 한다."""
    raw = [k for ks in keywords_by_id.values() for k in ks]
    tag_map = taglib.build_tag_map(raw)
    counts: collections.Counter[str] = collections.Counter()
    for ks in keywords_by_id.values():
        for name in taglib.canonical_tags(ks, tag_map):
            counts[name] += 1
    outside = sum(1 for k in raw if taglib.fold(k) not in vocab_keys)
    return {
        "reports": len(keywords_by_id),
        "tags": len(raw),
        "kinds": len(counts),
        "once": sum(1 for n in counts.values() if n == 1),
        "outside": outside,
    }


def print_delta(before: dict, after: dict) -> None:
    def pct(d):
        return round(100 * d["outside"] / d["tags"]) if d["tags"] else 0

    print("                 지금      다시 고른 뒤")
    print("  태그 수      %6d %12d" % (before["tags"], after["tags"]))
    print("  태그 종류    %6d %12d" % (before["kinds"], after["kinds"]))
    print("  1회짜리      %6d %12d" % (before["once"], after["once"]))
    print("  어휘 밖    %4d(%2d%%) %8d(%2d%%)"
          % (before["outside"], pct(before), after["outside"], pct(after)))


# ---------------------------------------------------------------- 제안 만들기

def ask(state: dict, targets: list[str], vocab: list[str], model: str,
        batch_size: int, timeout: int, debt: tuple[int, int] = (0, 0)
        ) -> dict[str, list]:
    """배치로 나눠 물어보고 **다듬지 않은 답**을 모은다. {보고서 id: [태그…]}

    답을 그대로 돌려주는 이유: 규칙(`sanitize`)을 고칠 때마다 300편을 다시 물으면
    한 번에 25분과 요금제 사용량이 든다. 답을 제안 파일에 남겨 두면 규칙만 고쳐
    `--resanitize` 로 공짜로 다시 걸 수 있다. 실제로 규칙을 한 번 고쳐야 했다.

    배치가 실패하면 그 배치만 건너뛴다 — 14배치가 성공했는데 1배치 때문에 전부
    버릴 이유가 없다. 건너뛴 보고서는 어휘 밖 태그를 그대로 지니므로 다음 실행이
    다시 대상으로 잡는다.
    """
    out: dict[str, list] = {}
    total = (len(targets) + batch_size - 1) // batch_size
    for n in range(total):
        chunk = targets[n * batch_size:(n + 1) * batch_size]
        items = [dict(state["reports"][t], id=t) for t in chunk]
        print("배치 %d/%d — %d편 (%s ~ %s)"
              % (n + 1, total, len(chunk), chunk[0], chunk[-1]))
        prompt = build_prompt(items, vocab, debt[0], debt[1])
        reply = parse_reply(call_claude(prompt, model, timeout, "태그 재부여") or "")
        if not reply:
            print("  답을 받지 못해 이 배치는 건너뜁니다 — 다음 실행이 다시 봅니다.")
            continue
        missing = [t for t in chunk if t not in reply]
        if missing:
            print("  답이 빠진 보고서 %d편: %s" % (len(missing), ", ".join(missing[:5])))
        for tid in chunk:
            if tid in reply and isinstance(reply[tid], list):
                out[tid] = reply[tid]
    return out


def screen(state: dict, replies: dict[str, list], vocab: list[str]) -> dict[str, dict]:
    """모은 답에 규칙을 걸어 제안으로 만든다. 호출하지 않는다."""
    vocab_keys = {taglib.fold(v) for v in vocab}
    people = taglib.person_names(state["participants"])
    places = state["places"]
    categories = state["categories"]

    # 표기는 말뭉치가 이미 쓰는 것으로 맞춘다(어휘 목록이 그 표기로 되어 있으니
    # 대개 그대로지만, 모델이 'AI studio' 라 적어 오는 경우가 있다).
    all_raw = [k for r in state["reports"].values() for k in r["keywords"]]
    tag_map = taglib.build_tag_map(all_raw + vocab)
    corpus_keys = {taglib.fold(k) for k in all_raw}

    out: dict[str, dict] = {}
    for tid in sorted(replies):
        rep = state["reports"].get(tid)
        if not rep:
            print("  %s: 보고서가 없습니다 — 건너뜁니다" % tid)
            continue
        current = rep["keywords"]
        picked = [canonical_name(t, tag_map) for t in (replies[tid] or [])]
        tags, notes = sanitize(picked, current, vocab_keys, people, places,
                               categories, corpus_keys)
        if len(tags) < TAG_COUNT_MIN:
            print("  %s: 남은 태그가 %d개뿐 — 손대지 않습니다" % (tid, len(tags)))
            continue
        if [taglib.fold(t) for t in tags] == [taglib.fold(t) for t in current]:
            continue
        out[tid] = {"before": current, "after": tags, "notes": notes}
        for note in notes:
            print("  %s: %s" % (tid, note))
    return out


# ---------------------------------------------------------------- 적용

def apply_proposal(proposal: dict, day: str) -> tuple[int, list[str], Path]:
    """제안대로 keywords 줄을 바꾼다. 바꾸기 전 md 와 태그는 백업 폴더에 남긴다.

    어휘 목록도 함께 남기는 것은 이 스크립트뿐이다. 여기서 LLM 이 고른 태그는
    '그때 보여준 목록' 안에서 고른 것이라, 목록이 없으면 나중에 판단을 되짚을 수
    없다 — 어휘는 발행본이 바뀔 때마다 달라진다.
    """
    backup = backup_dir("retag", day)
    (backup / "vocabulary.json").write_text(
        json.dumps(proposal.get("vocabulary") or [], ensure_ascii=False, indent=2)
        + "\n", encoding="utf-8")
    done, failed = apply_keyword_changes(proposal["changes"], backup)
    return done, failed, backup


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description="유산 보고서의 태그만 다시 고른다")
    ap.add_argument("--apply", action="store_true",
                    help="제안 파일을 읽어 md 의 keywords 줄을 바꾼다 (호출 없음)")
    ap.add_argument("--stats", action="store_true", help="지금 상태만 센다 (호출 없음)")
    ap.add_argument("--resanitize", action="store_true",
                    help="제안에 담긴 답 원본에 규칙을 다시 걸어 제안을 새로 쓴다 (호출 없음)")
    ap.add_argument("--limit", type=int, default=0, help="앞에서 이만큼만 (0=전부)")
    ap.add_argument("--batch", type=int, default=BATCH, help="한 번에 보낼 보고서 수")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--timeout", type=int, default=TIMEOUT_SEC)
    ap.add_argument("--since", default=VOCAB_SINCE,
                    help="이 달부터의 보고서는 대상이 아니다 (기본 %s)" % VOCAB_SINCE)
    ap.add_argument("--proposal", type=Path, default=PROPOSAL)
    args = ap.parse_args()

    if args.apply:
        if not args.proposal.is_file():
            print("제안 파일이 없습니다: %s" % args.proposal)
            print("먼저 python -m scripts.retag_reports 를 돌리세요.")
            return 1
        proposal = json.loads(args.proposal.read_text(encoding="utf-8"))
        if not (proposal.get("changes") or {}):
            print("제안에 바꿀 것이 없습니다.")
            return 0
        day = datetime.now().strftime("%Y%m%d")
        done, failed, backup = apply_proposal(proposal, day)
        print("보고서 %d편의 keywords 줄을 바꿨습니다." % done)
        for f in failed:
            print("  못 바꿈 — %s" % f)
        print("\n백업: %s/ (바꾸기 전 md 와 태그)" % shown(backup))
        print("다음: python -m scripts.build_site  → 테스트 → 발행")
        return 0

    state = load_state()
    now = {t: r["keywords"] for t, r in state["reports"].items()}
    old = (json.loads(args.proposal.read_text(encoding="utf-8"))
           if args.resanitize and args.proposal.is_file() else None)
    if args.resanitize and not (old or {}).get("replies"):
        print("다시 걸 답이 없습니다: %s" % shown(args.proposal))
        print("답 원본을 담은 제안이 있어야 합니다 — 먼저 그냥 한 번 돌리세요.")
        return 1

    # 다시 걸 때는 **그때 쓴 어휘**를 써야 한다. 지금 재면 목록이 달라져, 모델이
    # 보지도 않은 목록으로 그 답을 심판하게 된다.
    vocab = old["vocabulary"] if args.resanitize else freeze_vocabulary(state)
    vocab_keys = {taglib.fold(v) for v in vocab}
    before = tag_stats(now, vocab_keys)
    dates = message_dates()
    targets = select_targets(state, vocab, dates, args.since)

    print("보고서 %d편 · 어휘 %d종 · %s 이전에서 다시 고를 것 %d편"
          % (len(state["reports"]), len(vocab), args.since, len(targets)))
    if args.stats:
        print("  태그 %d개 / %d종 / 1회짜리 %d종 / 어휘 밖 %d개(%d%%)"
              % (before["tags"], before["kinds"], before["once"], before["outside"],
                 round(100 * before["outside"] / before["tags"])))
        return 0

    if args.resanitize:
        replies = old["replies"]
        print("  답 %d편을 규칙에 다시 겁니다 (호출 없음)." % len(replies))
    else:
        if args.limit:
            targets = targets[:args.limit]
            print("  --limit %d — 앞에서 %d편만 봅니다." % (args.limit, len(targets)))
        if not targets:
            print("다시 고를 것이 없습니다.")
            return 0
        replies = ask(state, targets, vocab, args.model, args.batch, args.timeout,
                      (before["kinds"], before["once"]))
        if not replies:
            print("\n답을 하나도 받지 못했습니다.")
            return 1

    changes = screen(state, replies, vocab)
    if not changes:
        print("\n바뀔 것이 없습니다.")
        return 0

    after = dict(now)
    after.update({t: v["after"] for t, v in changes.items()})
    print("\n보고서 %d편이 바뀝니다.\n" % len(changes))
    print_delta(before, tag_stats(after, vocab_keys))

    args.proposal.parent.mkdir(parents=True, exist_ok=True)
    args.proposal.write_text(
        json.dumps({"made": datetime.now().isoformat(timespec="seconds"),
                    "model": (old or {}).get("model") if args.resanitize else args.model,
                    "since": args.since, "vocabulary": vocab,
                    "replies": replies, "changes": changes},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\n제안 → %s" % shown(args.proposal))
    print("md 는 아직 한 글자도 안 바꿨습니다. 적용:")
    print("  python -m scripts.retag_reports --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
