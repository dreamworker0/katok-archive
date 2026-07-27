# -*- coding: utf-8 -*-
"""미분류 스레드를 주제별로 분류한다 (LLM 판단).

왜 이 파일만 LLM 을 쓰는가
    파싱·증분 병합·발행은 코드가 더 정확하고 싸고 안정적이라 LLM 을 쓰지 않는다.
    그런데 "이 대화가 어느 주제인가"는 코드가 답할 수 없다. 그래서 파이프라인의
    이 한 칸만 판단을 맡기고, 나머지는 전부 결정론적으로 남긴다.

    원래 이 작업은 사람이 주 1회 하는 일이었다. 자동으로 돌리기로 정한 뒤에도
    "LLM 장애가 파이프라인을 멈추지 않는다"는 성질은 지켜야 한다 — 그래서 이
    스크립트는 **실패해도 종료 코드 0** 이다. 실패하면 미분류 스레드가 그대로
    남을 뿐이고, 타임라인·통계·갤러리는 예정대로 발행된다.

비용을 어떻게 억제하는가
    · 미분류 스레드가 없으면 **호출 자체를 하지 않는다** (조용한 날 = 0원)
    · 하루 최대 1회, 그날 새 메시지만 보낸다 (전체 1,500건을 보내지 않는다)
    · `claude -p` 는 OAuth 로그인 계정의 요금제를 쓴다 — 종량 API 키가 아니다

무엇을 고치고 무엇을 안 고치는가
    고침   topics.json  미분류 스레드를 실제 카테고리·제목·요지로 교체
           knowledge.json  새로 등장한 사람·앱·도구 노드와 엣지 (덧붙이기만)
    안 고침 topic-digests.json  카테고리별 요지 산문. 그건 아카이브 전체를 요약한
           글이라, 새 글 2건 때문에 12편을 매일 다시 쓰면 품질이 흔들리고 비용도
           훨씬 크다. 그건 사람이 필요할 때 갱신한다.

지켜야 하는 불변식
    **모든 메시지는 정확히 하나의 스레드에 속한다.** LLM 이 메시지를 빠뜨리거나
    없는 ID 를 만들어내면 아카이브가 조용히 깨진다. 그래서 적용 전에 집합이
    정확히 일치하는지 확인하고, 어긋나면 아무것도 적용하지 않는다.

사용
    python -m scripts.classify_unsorted
    python -m scripts.classify_unsorted --dry-run    # 호출은 하고 파일은 안 씀
    python -m scripts.classify_unsorted --model sonnet   # 더 싸게
    python -m scripts.classify_unsorted --no-graph   # 관계 그래프는 건드리지 않음
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
TOPICS = OUT / "topics.json"
MESSAGES = OUT / "messages.jsonl"
KNOWLEDGE = OUT / "knowledge.json"

UNSORTED_RE = re.compile(r"^t-unsorted-\d{4}-\d{2}-\d{2}$")

# 한 번에 분류할 메시지 상한. 오래 방치해 미분류가 잔뜩 쌓였을 때 프롬프트가
# 폭발하지 않게 막는다. 넘치면 오래된 것부터 이만큼만 하고, 나머지는 다음 실행이
# 이어서 한다 — 한 번에 다 못 해도 매일 줄어든다.
MAX_MESSAGES_PER_RUN = 120

# LLM 이 오래 물고 있으면 갱신 전체가 늦어진다. 넘기면 포기하고 미분류로 남긴다.
TIMEOUT_SEC = 300

# 기본 모델 — 오늘의 실제 2건으로 네 모델을 견줘 정했다(2026-07-27).
#
#   fable   $0.59  '우리말 윤문 도구 비용 해결 공유'      노드+1 엣지+1
#   opus    $0.28  '우리말 윤문 도구 토큰 비용 해결'      노드+1 엣지+2
#   sonnet  $0.23  '윤문 도구 비용 문제 해결 공유'        노드+1 엣지+2
#   haiku   $0.066 '윤문 도구 Claude API 마이그레이션'     그래프 없음
#
# 넷 다 카테고리는 projects 로 같게 봤다. haiku 는 뜻을 뒤집었다 — 실제로는 API 에서
# 요금제로 옮겨온 이야기인데 'API 마이그레이션'이라 적었고 그래프도 못 뽑았다.
# opus 의 제목이 맥락('토큰 비용')을 가장 정확히 잡았고, fable 의 절반 값이다.
#
# 판단이 틀리면 아카이브의 주제 구조가 조용히 어긋나고, 그건 사람이 나중에 찾아
# 고쳐야 하는 종류의 손해다. 하루 1회뿐인 호출이라 그쪽에 값을 쓰는 편이 맞다.
# (비용은 API 환산 추정치다. claude -p 는 OAuth 계정의 요금제 사용량을 쓴다.)
DEFAULT_MODEL = "opus"

# 사람이 읽는 로그는 한국어로, 판단에 쓰는 신호는 ASCII 표식으로 준다.
# run_daily.ps1 이 콘솔 코드페이지 때문에 한국어를 못 읽는 경우가 있어서다
# (scripts/run_daily.ps1 의 인코딩 주석을 함께 볼 것).
def emit(marker: str, value) -> None:
    print(f"{marker}={value}")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def read_messages(ids: set[str]) -> list[dict]:
    """필요한 메시지만 골라 읽는다. 전체를 메모리에 들이지 않는다."""
    found = []
    with MESSAGES.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            m = json.loads(line)
            if m.get("id") in ids:
                found.append(m)
    found.sort(key=lambda m: (m.get("timestamp") or "", m.get("id") or ""))
    return found


def build_prompt(msgs: list[dict], categories: list[dict],
                 examples: list[dict], known_nodes: list[dict]) -> str:
    cat_lines = "\n".join(
        f"  {c['id']}: {c['label']}" for c in categories
    )
    # 이미 있는 앱·도구를 알려준다. 안 알려주면 같은 것을 다른 id 로 또 만든다 —
    # 실측 2026-07-27: 'app:urimal'(우리말 윤문)이 있는데 'app:우리말'을 새로 만들었다.
    known_lines = "\n".join(
        f"  {n['id']} = {n['label']}" for n in known_nodes
    ) or "  (없음)"
    ex_lines = "\n".join(
        f"  [{t['category']}] {t['title']} — {t.get('summary', '')}"
        for t in examples
    )
    msg_lines = []
    for m in msgs:
        urls = m.get("urls") or []
        extra = (" | 링크: " + ", ".join(urls)) if urls else ""
        text = (m.get("text") or "").replace("\n", " ⏎ ")
        msg_lines.append(
            f"  {m['id']} | {m.get('date')} {m.get('time')} | "
            f"{m.get('nickname')} | {text}{extra}"
        )
    msgs_block = "\n".join(msg_lines)

    return f"""당신은 카카오톡 대화 아카이브의 주제 분류를 맡았습니다.

아래 메시지들을 읽고, 내용이 이어지는 것끼리 묶어 **스레드**로 나누고 각 스레드에
카테고리·제목·요지를 붙이세요.

## 카테고리 (이 id 중에서만 고릅니다)
{cat_lines}

## 기존 스레드 예시 (제목·요지의 톤을 맞추세요)
{ex_lines}

## 분류할 메시지
{msgs_block}

## 규칙
- 모든 메시지가 **정확히 하나의** 스레드에 들어가야 합니다. 빠뜨리거나 중복시키지
  마세요. 목록에 없는 메시지 ID 를 만들지 마세요.
- 내용이 이어지면 한 스레드로 묶고, 무관하면 나눕니다. 한 스레드가 될 수도 있고
  여러 개가 될 수도 있습니다.
- category 는 위 id 중 하나여야 합니다. 애매하면 'chat' 을 쓰되, 실제로 도구·모델·
  프로젝트·정책 이야기라면 그에 맞는 카테고리를 고르세요.
- title 은 30자 이내의 명사구. summary 는 한 문장(80자 이내), 사람 이름을 주어로.

## 이미 등록된 앱·도구 (새로 만들지 말고 이 id 를 그대로 쓰세요)
{known_lines}

## graph 규칙
- 이 대화에서 **새로 등장한** 앱·도구만 nodes 에 넣습니다. 위 목록에 있으면 절대
  새로 만들지 말고, edges 에서 그 id 를 그대로 참조하세요.
- 사람(person) 노드는 만들지 마세요. 참여자는 다른 곳에서 자동으로 관리됩니다.
  기존 사람을 edge 에서 "person:닉네임" 으로 참조하는 것은 됩니다.
- 새 node 는 이렇게 씁니다 (네 필드 모두 필수):
  · id       "app:영문-소문자-하이픈" 또는 "tool:영문-소문자-하이픈" (한글·공백 금지)
  · type     app | tool
  · category 위 카테고리 id 중 하나
  · label    화면에 보일 이름 (한글 가능)
- edge.type 은 made | uses | belongs | interested 중 하나.
  source/target 은 "person:닉네임", "app:...", "tool:...", "topic:카테고리id".
- 확실하지 않으면 빈 배열로 두세요. 틀린 노드보다 없는 편이 낫습니다.

## 출력
JSON 만 출력하세요. 산문·설명·코드펜스 없이 이 형태 그대로:

{{"threads":[{{"category":"ai-tools","title":"제목","summary":"요지 한 문장","message_ids":["msg-001510"]}}],"graph":{{"nodes":[{{"id":"tool:claude-p","type":"tool","category":"ai-tools","label":"Claude -p"}}],"edges":[{{"source":"person:김종원","target":"tool:claude-p","type":"uses"}}]}}}}
"""


def call_claude(prompt: str, model: str) -> str | None:
    """claude -p 를 호출해 결과 문자열을 돌려준다. 실패하면 None.

    도구·MCP 를 끊는다 — 이 일은 파일을 읽거나 명령을 돌릴 필요가 없고, 도구
    스키마가 프롬프트에 붙으면 그만큼 토큰이 더 든다.

    프롬프트는 **stdin** 으로 넘긴다. 인자로 주면 두 가지가 걸린다: `--disallowed-tools`
    가 가변인자(`<tools...>`)라 뒤따르는 프롬프트까지 삼켜버리고(실측), 메시지가
    쌓인 날에는 명령줄 길이 제한에 닿는다.
    """
    cmd = [
        "claude", "-p",
        "--output-format", "json",
        "--model", model,
        "--strict-mcp-config",
        "--mcp-config", '{"mcpServers":{}}',
        "--disallowed-tools", "Bash,Read,Write,Edit,Glob,Grep,WebFetch,WebSearch",
    ]
    try:
        r = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
            timeout=TIMEOUT_SEC, cwd=str(ROOT),
        )
    except FileNotFoundError:
        print("claude CLI 를 찾을 수 없습니다 — 분류를 건너뜁니다.")
        return None
    except subprocess.TimeoutExpired:
        print(f"분류가 {TIMEOUT_SEC}초를 넘겨 포기합니다 — 미분류로 남깁니다.")
        return None

    if r.returncode != 0:
        print(f"claude -p 실패 (exit {r.returncode}): {(r.stderr or '')[:300]}")
        return None
    try:
        env = json.loads(r.stdout)
    except json.JSONDecodeError:
        print(f"claude -p 응답을 읽지 못했습니다: {r.stdout[:200]}")
        return None
    if env.get("is_error"):
        print(f"claude -p 오류 응답: {str(env.get('result'))[:300]}")
        return None

    cost = env.get("total_cost_usd")
    if cost is not None:
        # 요금제 사용량이지 청구액이 아니다. 추세를 보려고 남긴다.
        print(f"환산 비용(참고): ${cost:.4f}")
    return env.get("result")


def parse_reply(raw: str) -> dict | None:
    """모델이 코드펜스나 잡담을 붙였을 때도 JSON 만 꺼낸다."""
    if not raw:
        return None
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    else:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            text = text[start:end + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        print(f"JSON 파싱 실패: {e}")
        return None
    return data if isinstance(data, dict) else None


def validate(data: dict, expected_ids: set[str],
             valid_categories: set[str]) -> list[dict] | None:
    """불변식을 지키는지 확인한다. 하나라도 어긋나면 None (= 아무것도 적용 안 함).

    여기서 너그러우면 아카이브가 조용히 깨진다 — 메시지가 사라지거나, 없는 ID 를
    가리키는 스레드가 생기거나, 한 메시지가 두 스레드에 들어간다. 그중 어느 것도
    화면에서는 바로 눈에 띄지 않는다.
    """
    threads = data.get("threads")
    if not isinstance(threads, list) or not threads:
        print("threads 가 비었거나 목록이 아닙니다.")
        return None

    seen: set[str] = set()
    clean = []
    for i, t in enumerate(threads):
        if not isinstance(t, dict):
            print(f"threads[{i}] 가 객체가 아닙니다.")
            return None
        cat = str(t.get("category") or "").strip()
        if cat not in valid_categories:
            print(f"threads[{i}] 카테고리가 목록에 없습니다: {cat!r}")
            return None
        ids = t.get("message_ids")
        if not isinstance(ids, list) or not ids:
            print(f"threads[{i}] message_ids 가 비었습니다.")
            return None
        for mid in ids:
            if mid not in expected_ids:
                print(f"threads[{i}] 에 모르는 메시지 ID: {mid!r}")
                return None
            if mid in seen:
                print(f"메시지가 두 스레드에 들어갔습니다: {mid}")
                return None
            seen.add(mid)
        title = str(t.get("title") or "").strip()
        summary = str(t.get("summary") or "").strip()
        if not title:
            print(f"threads[{i}] 제목이 없습니다.")
            return None
        clean.append({
            "category": cat,
            "title": title[:60],
            "summary": summary[:200],
            "message_ids": list(ids),
        })

    missing = expected_ids - seen
    if missing:
        print(f"분류에서 빠진 메시지 {len(missing)}건: {sorted(missing)[:5]}")
        return None
    return clean


NEW_NODE_ID_RE = re.compile(r"^(app|tool):[a-z0-9][a-z0-9-]{1,39}$")


def norm_label(s: str) -> str:
    return re.sub(r"[\s\-_]+", "", str(s or "")).lower()


def merge_graph(knowledge: dict, graph: dict,
                valid_categories: set[str]) -> tuple[int, int]:
    """새 노드·엣지를 덧붙인다. 기존 것은 건드리지 않는다.

    지우지 않는 이유: 관계 그래프는 아카이브 전체에서 누적된 것이고, 그날 대화만
    본 판단으로 옛 노드를 지우면 과거가 사라진다. 덧붙이기만 하면 틀려도 손해가
    작고 사람이 나중에 정리할 수 있다.

    프롬프트로 부탁한 것을 여기서 다시 막는다. 실측 2026-07-27 에 두 가지가 났다:
      · category 없는 노드를 만들어 발행본 생성이 KeyError 로 깨졌다
        (build_site.build_digests 가 app 노드의 n["category"] 를 요구한다)
      · 'app:urimal'(우리말 윤문)이 있는데 'app:우리말'을 새로 만들었다
    프롬프트는 부탁이고 검증은 보장이다. 스키마가 안 맞으면 그 노드만 버린다.
    """
    if not isinstance(graph, dict):
        return 0, 0
    valid_edge_types = {t["id"] if isinstance(t, dict) else t
                        for t in knowledge.get("edge_types", [])}

    nodes = knowledge.setdefault("nodes", [])
    have_nodes = {n["id"] for n in nodes}
    have_labels = {(n.get("type"), norm_label(n.get("label"))) for n in nodes}
    added_n = 0
    for n in (graph.get("nodes") or []):
        if not isinstance(n, dict):
            continue
        nid = str(n.get("id") or "").strip()
        ntype = str(n.get("type") or "").strip()
        label = str(n.get("label") or "").strip()
        cat = str(n.get("category") or "").strip()

        # person 은 만들지 않는다 — 참여자는 결정론적 파이프라인이 관리한다.
        # topic 은 카테고리에 묶인 고정 노드다.
        if ntype not in ("app", "tool"):
            continue
        if not NEW_NODE_ID_RE.match(nid):
            print(f"  건너뜀(노드 id 형식): {nid!r}")
            continue
        if nid in have_nodes:
            continue
        if cat not in valid_categories:
            print(f"  건너뜀(노드 카테고리): {nid} -> {cat!r}")
            continue
        if not label:
            continue
        if (ntype, norm_label(label)) in have_labels:
            print(f"  건너뜀(이미 있는 이름): {nid} = {label}")
            continue

        nodes.append({
            "id": nid, "type": ntype, "category": cat,
            "label": label[:60], "value": 1,
            # query 는 화면이 이 노드와 관련된 스레드를 찾는 데 쓴다.
            # 없으면 라벨로 찾게 둔다.
            "query": str(n.get("query") or label)[:60],
        })
        have_nodes.add(nid)
        have_labels.add((ntype, norm_label(label)))
        added_n += 1

    have_edges = {(e.get("source"), e.get("target"), e.get("type"))
                  for e in knowledge.get("edges", [])}
    added_e = 0
    for e in (graph.get("edges") or []):
        if not isinstance(e, dict):
            continue
        src, dst = str(e.get("source") or ""), str(e.get("target") or "")
        etype = str(e.get("type") or "")
        if etype not in valid_edge_types:
            continue
        # 양쪽 끝이 실제로 있는 노드여야 한다. 없는 노드를 가리키는 엣지는
        # 화면에서 그려지지 않거나 그리다 깨진다.
        if src not in have_nodes or dst not in have_nodes:
            continue
        if (src, dst, etype) in have_edges:
            continue
        knowledge.setdefault("edges", []).append(
            {"source": src, "target": dst, "type": etype, "weight": 1}
        )
        have_edges.add((src, dst, etype))
        added_e += 1

    return added_n, added_e


def next_thread_id(threads: list[dict]) -> int:
    """t-001 형식의 다음 번호. 미분류 스레드는 이 형식이 아니라 섞이지 않는다."""
    top = 0
    for t in threads:
        m = re.match(r"^t-(\d+)$", str(t.get("id") or ""))
        if m:
            top = max(top, int(m.group(1)))
    return top + 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="호출은 하되 파일은 쓰지 않는다")
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    help=f"claude -p 에 넘길 모델 (기본: {DEFAULT_MODEL})")
    ap.add_argument("--no-graph", action="store_true",
                    help="관계 그래프는 건드리지 않는다")
    args = ap.parse_args()

    topics = load_json(TOPICS)
    threads = topics.get("threads", [])
    unsorted = [t for t in threads if UNSORTED_RE.match(str(t.get("id") or ""))]

    if not unsorted:
        # 여기서 끝내는 것이 비용 억제의 핵심이다. 조용한 날은 호출이 없다.
        print("미분류 스레드가 없습니다 — 분류할 것이 없습니다.")
        emit("CLASSIFIED", 0)
        return 0

    target_ids: list[str] = []
    for t in sorted(unsorted, key=lambda x: str(x.get("id"))):
        for mid in t.get("message_ids", []):
            if mid not in target_ids:
                target_ids.append(mid)

    capped = len(target_ids) > MAX_MESSAGES_PER_RUN
    if capped:
        print(f"미분류 {len(target_ids)}건 — 이번 실행은 오래된 "
              f"{MAX_MESSAGES_PER_RUN}건만 하고 나머지는 다음 실행이 이어서 합니다.")
        target_ids = target_ids[:MAX_MESSAGES_PER_RUN]

    msgs = read_messages(set(target_ids))
    if len(msgs) != len(target_ids):
        print(f"메시지를 다 찾지 못했습니다 ({len(msgs)}/{len(target_ids)}) — "
              "분류를 건너뜁니다.")
        emit("CLASSIFIED", 0)
        return 0

    categories = topics.get("categories", [])
    valid_categories = {c["id"] for c in categories}
    # 톤을 맞출 표본. 너무 많이 보내면 프롬프트만 커진다.
    examples = [t for t in threads
                if not UNSORTED_RE.match(str(t.get("id") or ""))][:12]

    print(f"미분류 {len(msgs)}건을 분류합니다 (모델: {args.model})")
    known_nodes = [n for n in (load_json(KNOWLEDGE).get("nodes", [])
                              if KNOWLEDGE.exists() else [])
                   if n.get("type") in ("app", "tool")]
    prompt = build_prompt(msgs, categories, examples, known_nodes)
    raw = call_claude(prompt, args.model)
    data = parse_reply(raw) if raw else None
    if data is None:
        print("분류 결과를 받지 못했습니다 — 미분류로 남깁니다(갱신은 계속됩니다).")
        emit("CLASSIFIED", 0)
        return 0

    handled = {m["id"] for m in msgs}
    clean = validate(data, handled, valid_categories)
    if clean is None:
        print("분류 결과가 규칙을 어겨 아무것도 적용하지 않습니다"
              "(갱신은 계속됩니다).")
        emit("CLASSIFIED", 0)
        return 0

    # ── 적용 ──
    # 처리한 메시지만 미분류 스레드에서 빼고, 남은 것이 있으면 스레드를 남긴다
    # (상한에 걸려 일부만 처리한 경우). 그래야 남은 메시지가 어느 스레드에도
    # 속하지 않는 상태가 생기지 않는다.
    rebuilt: list[dict] = []
    for t in threads:
        if not UNSORTED_RE.match(str(t.get("id") or "")):
            rebuilt.append(t)
            continue
        left = [mid for mid in t.get("message_ids", []) if mid not in handled]
        if left:
            t = dict(t)
            t["message_ids"] = left
            t["start_msg"], t["end_msg"] = left[0], left[-1]
            rebuilt.append(t)

    nid = next_thread_id(threads)
    for c in clean:
        ids = c["message_ids"]
        rebuilt.append({
            "id": f"t-{nid:03d}",
            "category": c["category"],
            "title": c["title"],
            "summary": c["summary"],
            "start_msg": ids[0],
            "end_msg": ids[-1],
            "message_ids": ids,
        })
        nid += 1

    topics["threads"] = rebuilt

    added_n = added_e = 0
    knowledge = None
    if not args.no_graph and KNOWLEDGE.exists():
        knowledge = load_json(KNOWLEDGE)
        added_n, added_e = merge_graph(knowledge, data.get("graph") or {},
                                       valid_categories)

    for c in clean:
        print(f"  [{c['category']}] {c['title']} ({len(c['message_ids'])}건)")
    if added_n or added_e:
        print(f"  관계 그래프: 노드 +{added_n}, 엣지 +{added_e}")

    if args.dry_run:
        print("--dry-run: 파일을 쓰지 않았습니다.")
        emit("CLASSIFIED", 0)
        return 0

    save_json(TOPICS, topics)
    if knowledge is not None and (added_n or added_e):
        save_json(KNOWLEDGE, knowledge)

    print(f"분류 완료: 스레드 {len(clean)}개, 메시지 {len(handled)}건")
    emit("CLASSIFIED", len(handled))
    return 0


if __name__ == "__main__":
    sys.exit(main())
