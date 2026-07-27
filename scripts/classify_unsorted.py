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
    고침   topics.json      미분류 스레드를 실제 카테고리·제목·요지·태그로 교체
           output/reports/  주제 보고서 md — 태그와 본문 산문이 여기서 나온다
           knowledge.json   새로 등장한 앱·도구 노드와 엣지 (덧붙이기만)
    안 고침 topic-digests.json  카테고리별 요지 산문. 그건 아카이브 전체를 요약한
           글이라, 새 글 2건 때문에 12편을 매일 다시 쓰면 품질이 흔들리고 비용도
           훨씬 크다. 그건 사람이 필요할 때 갱신한다.

보고서를 빼먹으면 안 되는 이유
    보고서 md 가 화면의 실제 내용 단위다 — apply_reports() 가 제목·요지·**태그**·
    본문을 여기서 읽어 스레드에 얹는다. 보고서가 없으면 그 주제는 제목과 요지만
    있고 태그도 본문도 없다. 실측 2026-07-27: 자동 분류 첫날 스레드만 만들고
    보고서를 빼먹어 새 주제 두 개가 그 상태로 남았다.

    그리고 한 번 빠지면 스스로 낫지 않는다 — 분류가 끝나 미분류가 아니므로 다음
    실행이 다시 볼 일이 없다. 그래서 매 실행이 '보고서 없는 주제'도 함께 본다.

지켜야 하는 불변식
    **모든 메시지는 정확히 하나의 스레드에 속한다.** LLM 이 메시지를 빠뜨리거나
    없는 ID 를 만들어내면 아카이브가 조용히 깨진다. 그래서 적용 전에 집합이
    정확히 일치하는지 확인하고, 어긋나면 아무것도 적용하지 않는다.

사용
    python -m scripts.classify_unsorted
    python -m scripts.classify_unsorted --dry-run    # 호출은 하고 파일은 안 씀
    python -m scripts.classify_unsorted --model sonnet   # 더 싸게
    python -m scripts.classify_unsorted --no-graph   # 관계 그래프는 건드리지 않음

    옛 백업을 합친 뒤처럼 미분류가 수백 건 밀려 있을 때만:
    python -m scripts.classify_unsorted --max 25 --timeout 900
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from scripts.topic_reports import (
    REPORTS_DIR,
    content_chars,
    load_reports,
    parse_report,
    thin_reports,
)

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
- keywords 는 2~6개. 이 대화를 나중에 찾을 때 쓸 말(도구 이름, 개념, 결과물).
  카테고리 이름을 그대로 넣지 마세요.
- report 는 이 대화를 읽은 사람이 다시 읽지 않아도 되게 쓰는 **본문 산문**입니다.
  · 사실만 씁니다. 대화에 없는 내용을 채우지 마세요.
  · 원문보다 짧아야 합니다. 짧은 대화면 두세 문장으로 충분합니다.
  · 링크나 사진 자리표(![[...]])를 넣지 마세요. 자료는 화면 아래에 따로 붙습니다.
  · 굵게(**...**)는 정말 중요한 한두 곳에만.

## 이미 등록된 앱·도구 (새로 만들지 말고 이 id 를 그대로 쓰세요)
{known_lines}

## graph 규칙
- 이 대화에서 **새로 등장한** 앱·도구만 nodes 에 넣습니다. 위 목록에 있으면 절대
  새로 만들지 말고, edges 에서 그 id 를 그대로 참조하세요.
- 사람(person) 노드는 만들지 마세요. 참여자는 다른 곳에서 자동으로 관리됩니다.
  기존 사람을 edge 에서 "person:닉네임" 으로 참조하는 것은 됩니다.
- 새 node 는 이렇게 씁니다 (다섯 필드 모두 필수):
  · id       "app:영문-소문자-하이픈" 또는 "tool:영문-소문자-하이픈" (한글·공백 금지)
  · type     app | tool
  · category 위 카테고리 id 중 하나
  · label    화면에 보일 이름 (한글 가능)
  · query    **위 대화에 실제로 그대로 적혀 있는** 짧은 말. 화면이 이 말로 원문을
             훑어 노드 크기를 정하므로, 없는 말을 쓰면 그 노드는 가장 작게 나온다.
             · 대화에 "커서" 라고만 나오면 query 는 "커서" 다. "커서(Cursor)" 가 아니다.
             · '앱', '웹앱', '도구' 같은 꾸밈말은 붙이지 않는다.
             · '사진', '관리', '깃허브' 처럼 아무 데나 나오는 일반 낱말은 쓰지 않는다.
               그런 말밖에 없으면 label 을 그대로 쓴다 — 크기를 뻥튀기는 것보다 낫다.
- edge.type 은 made | uses | belongs | interested 중 하나.
  source/target 은 "person:닉네임", "app:...", "tool:...", "topic:카테고리id".
- 확실하지 않으면 빈 배열로 두세요. 틀린 노드보다 없는 편이 낫습니다.

## 출력
JSON 만 출력하세요. 산문·설명·코드펜스 없이 이 형태 그대로:

{{"threads":[{{"category":"ai-tools","title":"제목","summary":"요지 한 문장","keywords":["키워드1","키워드2"],"report":"본문 산문. 여러 문장이어도 됩니다.","message_ids":["msg-001510"]}}],"graph":{{"nodes":[{{"id":"tool:claude-p","type":"tool","category":"ai-tools","label":"Claude -p","query":"claude -p"}}],"edges":[{{"source":"person:김종원","target":"tool:claude-p","type":"uses"}}]}}}}
"""


def call_claude(prompt: str, model: str, timeout: int = TIMEOUT_SEC) -> str | None:
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
            timeout=timeout, cwd=str(ROOT),
        )
    except FileNotFoundError:
        print("claude CLI 를 찾을 수 없습니다 — 분류를 건너뜁니다.")
        return None
    except subprocess.TimeoutExpired:
        print(f"분류가 {timeout}초를 넘겨 포기합니다 — 미분류로 남깁니다.")
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
        # 키워드(=태그). 프론트매터에서 쉼표로 갈리므로 쉼표를 지운다.
        kws = []
        for k in (t.get("keywords") or []):
            k = str(k).replace(",", " ").strip()
            if k and k not in kws:
                kws.append(k[:30])

        clean.append({
            "category": cat,
            "title": title[:60],
            "summary": summary[:200],
            "keywords": kws[:6],
            "report": str(t.get("report") or "").strip(),
            "message_ids": list(ids),
        })

    missing = expected_ids - seen
    if missing:
        print(f"분류에서 빠진 메시지 {len(missing)}건: {sorted(missing)[:5]}")
        return None
    return clean


NEW_NODE_ID_RE = re.compile(r"^(app|tool):[a-z0-9][a-z0-9-]{1,39}$")


def render_report(title: str, summary: str, keywords: list[str],
                  body: str) -> str:
    """output/reports/*.md 형식으로 만든다.

    프론트매터는 `topic_reports.parse_report` 가 첫 콜론에서만 자르는 단순 형식이다
    (pyyaml 을 쓰지 않는 이유가 거기 적혀 있다). 값에 줄바꿈이 들어가면 그 파서가
    깨지므로 한 줄로 눕힌다.
    """
    def one_line(s: str) -> str:
        return re.sub(r"\s+", " ", str(s or "")).strip()

    head = [
        f"title: {one_line(title)}",
        f"summary: {one_line(summary)}",
    ]
    if keywords:
        head.append("keywords: " + ", ".join(one_line(k) for k in keywords))
    return "---\n" + "\n".join(head) + "\n---\n\n" + body.strip() + "\n"


def write_report(thread_id: str, thread: dict, raw_chars: int) -> str | None:
    """보고서 md 를 쓴다. 못 쓰면 이유를 돌려준다(None 이면 성공).

    보고서는 화면의 실제 내용 단위다 — 제목·요지·**키워드(태그)**·본문 산문이
    여기서 나오고, apply_reports() 가 그것을 스레드에 얹는다. 보고서가 없으면
    스레드는 제목과 요지만 있고 태그도 본문도 없다(실측 2026-07-27: 자동 분류가
    스레드만 만들고 보고서를 빼먹어 새 주제 두 개가 그런 상태였다).

    쓰기 전에 `parse_report` 로 되읽어 본다. 형식이 어긋난 md 를 남기면 다음
    실행의 `load_reports` 가 예외를 던져 파이프라인 전체가 멈춘다 — 보고서 하나
    때문에 갱신이 죽는 것은 이 설계에서 가장 피하고 싶은 일이다.
    """
    body = thread.get("report") or ""
    if not body:
        return "본문이 비었습니다"

    # 지어낸 내용이 섞였는지 본다. 다만 "원문보다 짧아야 한다"로 잡으면 안 된다 —
    # 실측 2026-07-27: 95자 메시지의 정상적인 보고서가 110자로 나와 걸렸다.
    # 짧고 압축된 말('Claude -p 로 구조를 바꿨다')을 읽을 수 있게 풀면 원문보다
    # 길어지는 게 당연하다. topic_reports 도 최소 분량만 정하고 상한은 두지 않는다.
    #
    # 그래서 '약간 김'이 아니라 '터무니없이 김'만 막는다. 두 문장짜리 대화에서
    # 원고지 몇 장이 나오면 그건 지어낸 것이다.
    limit = max(400, raw_chars * 2)
    if len(body) > limit:
        return f"본문이 원문에 비해 너무 깁니다 ({len(body)} > {limit})"

    # 자리표를 만들면 audit_report_context 가 '유효하지 않은 자리표'로 잡는다.
    # 링크·사진은 화면 아래에 따로 붙으므로 본문에 넣을 이유가 없다.
    if re.search(r"!\[\[|\]\]", body):
        return "본문에 자리표(![[...]])가 들어 있습니다"

    text = render_report(thread["title"], thread["summary"],
                         thread.get("keywords") or [], body)
    try:
        back = parse_report(text, thread_id + ".md")
    except ValueError as e:
        return f"되읽기 실패: {e}"
    if back["title"] != re.sub(r"\s+", " ", thread["title"]).strip():
        return "되읽은 제목이 다릅니다"

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / f"{thread_id}.md").write_text(text, encoding="utf-8")
    return None


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


def build_report_prompt(thread: dict, msgs: list[dict],
                        examples: list[dict], min_chars: int | None = None) -> str:
    """보고서만 새로 쓰는 프롬프트. 분류는 이미 끝난 스레드에 쓴다.

    min_chars 를 주면 '짧아도 된다' 대신 분량 목표를 말한다. 기본 지시는 짧게
    쓰라는 쪽이라(요약은 원문보다 짧아야 하므로 맞다), 그대로 다시 부르면 얇은
    보고서가 또 얇게 나온다 — 다시 쓰는 값을 못 얻는다.
    """
    ex = "\n".join(
        f"  [{t['category']}] {t['title']} — {t.get('summary', '')}"
        for t in examples[:6]
    )
    lines = []
    for m in msgs:
        urls = m.get("urls") or []
        extra = (" | 링크: " + ", ".join(urls)) if urls else ""
        text = (m.get("text") or "").replace("\n", " ⏎ ")
        lines.append(f"  {m.get('date')} {m.get('time')} | "
                     f"{m.get('nickname')} | {text}{extra}")
    if min_chars:
        # 분량을 말하되 '채워 넣어라'로 읽히지 않게 한다. 없는 내용을 지어내는 것보다
        # 얇은 채로 남는 편이 낫다 — 원문을 발행하지 않으니 거짓이 검증되지 않는다.
        length_rule = (
            f"  이 대화는 {len(msgs)}건입니다. 본문을 **{min_chars}자 이상**으로,\n"
            "  오간 내용을 빠짐없이 담아 쓰세요. 다만 대화에 없는 내용으로 분량을\n"
            "  채우지는 마세요 — 정말 쓸 것이 없으면 짧게 두는 편이 낫습니다."
        )
    else:
        length_rule = ("  원문보다 짧아야 하고, 짧은 대화면 두세 문장으로 충분합니다.")
    return f"""카카오톡 대화 아카이브의 주제 보고서를 씁니다.

이 주제는 이미 분류돼 있습니다. 제목·요지는 그대로 두고, **태그와 본문**만 씁니다.

## 이 주제
  제목: {thread.get('title')}
  요지: {thread.get('summary')}
  카테고리: {thread.get('category')}

## 톤을 맞출 예시
{ex}

## 대화
{chr(10).join(lines)}

## 규칙
- keywords 는 2~6개. 나중에 이 대화를 찾을 때 쓸 말(도구 이름, 개념, 결과물).
- report 는 본문 산문. 사실만 쓰고, 대화에 없는 내용을 채우지 마세요.
{length_rule}

### 인용을 반드시 쓰세요 — 두 가지 이유가 있습니다
- 결정적인 말은 **원문 그대로** 인용(`>`)으로 옮기세요. 한 편에 1~3개.
  줄여 쓰지 말고 그 사람이 쓴 문장을 그대로 씁니다. 조사·말투·이모티콘까지.
- 요약만 늘어놓은 글은 읽히지 않습니다. 실제 목소리가 한 번씩 들어와야 삽니다.
- 그리고 **사진과 링크가 이 인용을 기준으로 본문 사이에 끼워집니다.** 인용이
  없으면 자료가 전부 글 끝으로 밀려 글 따로 자료 따로가 됩니다.

### 대화가 여러 국면으로 흘렀으면 절로 나누세요
- `## 짧은 제목` 으로 나눕니다. 문제 제기 → 시도 → 막힌 곳 → 해결 같은 흐름이면
  그대로 절이 됩니다. 5건 이하의 짧은 대화는 나누지 않아도 됩니다.
- 정말 중요한 한두 곳만 `**굵게**`. 남용하면 아무것도 강조되지 않습니다.

### 자리표는 쓰지 마세요
  `![[...]]` 를 직접 넣지 마세요 — 사진·링크는 위 인용을 보고 자동으로 붙습니다.
  직접 쓰면 없는 자료를 가리켜 화면이 깨집니다.

## 출력
JSON 만, 코드펜스 없이:

{{"keywords":["키워드1","키워드2"],"report":"본문 산문."}}
"""


def fill_missing_reports(threads: list[dict], model: str,
                         examples: list[dict], dry_run: bool,
                         limit: int = 5, timeout: int = TIMEOUT_SEC) -> int:
    """보고서가 없는 스레드에 보고서를 써 넣는다. 쓴 편수를 돌려준다.

    왜 필요한가: 보고서 쓰기가 한 번 실패하면 그 주제는 태그도 본문도 없이 영구히
    남는다 — 분류는 이미 끝나 미분류가 아니므로 다음 실행이 다시 볼 일이 없다.
    실측 2026-07-27: 자동 분류 첫날 t-166·t-167 이 정확히 그 상태로 남았다.
    그래서 매 실행이 '보고서 없는 스레드'도 함께 본다. 스스로 메꾼다.

    한 번에 limit 편까지만 한다. 예전 주제 수십 개에 보고서가 없는 상태로 이 기능을
    켜면 하루에 다 쓰려다 프롬프트와 시간이 폭발한다 — 매일 조금씩 줄이는 편이 낫다.
    """
    have = set()
    if REPORTS_DIR.exists():
        have = {p.stem for p in REPORTS_DIR.glob("*.md")}
    missing = [t for t in threads
               if not UNSORTED_RE.match(str(t.get("id") or ""))
               and t["id"] not in have]
    if not missing:
        return 0

    print(f"보고서 없는 주제 {len(missing)}개 — 이번에 최대 {limit}개를 씁니다.")
    return _write_reports(missing[:limit], model, examples, dry_run, timeout)


def find_thin_reports(threads: list[dict]) -> list[tuple[dict, int]]:
    """대화량에 비해 본문이 얇은 주제를 고른다. [(스레드, 목표 분량)]

    '얇다'의 정의는 topic_reports.thin_reports 하나만 쓴다. 여기서 따로 세면
    화면 경고와 다시 쓰는 대상이 어긋나, 경고는 남았는데 손댈 방법이 없어진다.
    """
    reports = load_reports()
    counts = {t["id"]: len(t.get("message_ids") or []) for t in threads}
    raw_chars: dict[str, int] = {}
    wanted = {mid for t in threads for mid in (t.get("message_ids") or [])}
    lengths = {m["id"]: content_chars(m.get("text")) for m in read_messages(wanted)}
    for t in threads:
        raw_chars[t["id"]] = sum(lengths.get(m, 0) for m in (t.get("message_ids") or []))

    probe = [
        {"id": t["id"], "count": counts[t["id"]],
         "report": (reports.get(t["id"]) or {}).get("report") or ""}
        for t in threads
    ]
    by_id = {t["id"]: t for t in threads}
    out = []
    for tid, _count, _got, need in thin_reports(probe, raw_chars):
        out.append((by_id[tid], need))
    return out


def rewrite_thin_reports(threads: list[dict], model: str, examples: list[dict],
                         dry_run: bool, limit: int = 5,
                         timeout: int = TIMEOUT_SEC) -> int:
    """얇은 보고서를 분량 목표를 주고 다시 쓴다. 다시 쓴 편수를 돌려준다.

    보고서 없는 것을 메꾸는 일(fill_missing_reports)과 달리 이건 **매일 돌리지
    않는다**. 기준을 겨우 넘긴 보고서를 매일 다시 쓰면 같은 내용이 흔들리기만
    하고, 값은 계속 든다. 옛 백업을 한꺼번에 합친 뒤처럼 얇은 것이 무더기로
    생겼을 때 사람이 불러 쓴다.
    """
    thin = find_thin_reports(
        [t for t in threads if not UNSORTED_RE.match(str(t.get("id") or ""))])
    if not thin:
        print("얇은 보고서가 없습니다.")
        return 0

    print(f"얇은 보고서 {len(thin)}개 — 이번에 최대 {limit}개를 다시 씁니다.")
    return _write_reports([t for t, _ in thin[:limit]], model, examples,
                          dry_run, timeout,
                          min_by_id={t["id"]: need for t, need in thin[:limit]})


def _write_reports(targets: list[dict], model: str, examples: list[dict],
                   dry_run: bool, timeout: int,
                   min_by_id: dict[str, int] | None = None) -> int:
    """주제 목록에 보고서를 써 넣는다. 쓴 편수를 돌려준다.

    '없는 것 메꾸기'와 '얇은 것 다시 쓰기'가 이 루프를 같이 쓴다 — 대상을 고르는
    기준만 다르고, 쓰고 검사하고 태그를 얹는 절차는 똑같아야 한다.
    """
    wrote = 0
    for t in targets:
        msgs = read_messages(set(t.get("message_ids") or []))
        if not msgs:
            print(f"  건너뜀({t['id']}): 메시지를 찾지 못했습니다.")
            continue
        raw = sum(len(m.get("text") or "") for m in msgs)
        data = parse_reply(call_claude(
            build_report_prompt(t, msgs, examples,
                                (min_by_id or {}).get(t["id"])),
            model, timeout) or "")
        if not data:
            print(f"  건너뜀({t['id']}): 보고서 결과를 받지 못했습니다.")
            continue
        kws = []
        for k in (data.get("keywords") or []):
            k = str(k).replace(",", " ").strip()
            if k and k not in kws:
                kws.append(k[:30])
        payload = {
            "title": t.get("title") or "",
            "summary": t.get("summary") or "",
            "keywords": kws[:6],
            "report": str(data.get("report") or "").strip(),
        }
        if dry_run:
            print(f"  [dry-run] {t['id']} 본문 {len(payload['report'])}자 "
                  f"· 태그 {', '.join(payload['keywords'])}")
            continue
        why = write_report(t["id"], {**payload, "id": t["id"]}, raw)
        if why:
            print(f"  보고서 못 씀({t['id']}): {why}")
            continue
        # 스레드에도 태그를 얹어 둔다. 발행은 apply_reports 가 보고서에서 다시
        # 읽지만, topics.json 만 보는 도구들도 태그를 볼 수 있어야 한다.
        if payload["keywords"]:
            t["keywords"] = list(payload["keywords"])
        wrote += 1
        print(f"  {t['id']} 보고서 작성 · 태그: {', '.join(payload['keywords'])}")
    return wrote


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
    # 아래 두 값의 기본치는 '하루에 몇 건'을 전제로 잡혀 있다. 옛 백업을 합친 뒤처럼
    # 수백 건이 한꺼번에 밀려 있으면 한 번의 호출이 훨씬 무거워져 상한에 걸린다.
    # 매일 실행의 기본값은 건드리지 않고, 몰아서 할 때만 늘려 쓴다.
    ap.add_argument("--timeout", type=int, default=TIMEOUT_SEC,
                    help=f"claude -p 한 번의 제한 시간(초) (기본: {TIMEOUT_SEC})")
    ap.add_argument("--max", type=int, default=MAX_MESSAGES_PER_RUN, dest="max_messages",
                    help=f"한 번에 분류할 메시지 수 (기본: {MAX_MESSAGES_PER_RUN})")
    # 매일 실행에는 넣지 않는다 — 기준을 겨우 넘긴 보고서를 매일 다시 쓰면 내용이
    # 흔들리기만 하고 값은 계속 든다. 사람이 필요할 때 부르는 일이다.
    ap.add_argument("--rewrite-thin", type=int, metavar="N", default=0,
                    help="분류 대신, 대화량에 비해 얇은 보고서 N편을 다시 쓴다")
    ap.add_argument("--rewrite-ids", metavar="ID,ID", default="",
                    help="분류 대신, 지정한 주제의 보고서를 다시 쓴다 (t-216,t-182)")
    args = ap.parse_args()

    if args.rewrite_ids:
        topics = load_json(TOPICS)
        threads = topics.get("threads", [])
        want = [s.strip() for s in args.rewrite_ids.split(",") if s.strip()]
        by_id = {t["id"]: t for t in threads}
        missing = [i for i in want if i not in by_id]
        if missing:
            raise SystemExit("없는 주제: %s" % ", ".join(missing))
        examples = [t for t in threads
                    if not UNSORTED_RE.match(str(t.get("id") or ""))][:12]
        # 분량 목표는 '얇다' 판정과 같은 기준을 쓴다. 여기서 따로 정하면 다시 쓴
        # 보고서가 곧바로 얇다고 잡히는 일이 생긴다.
        need = dict((t["id"], n) for t, n in find_thin_reports([by_id[i] for i in want]))
        n = _write_reports([by_id[i] for i in want], args.model, examples,
                           args.dry_run, args.timeout, min_by_id=need)
        if n and not args.dry_run:
            save_json(TOPICS, topics)
        emit("REWRITTEN", n)
        return 0

    if args.rewrite_thin:
        topics = load_json(TOPICS)
        threads = topics.get("threads", [])
        examples = [t for t in threads
                    if not UNSORTED_RE.match(str(t.get("id") or ""))][:12]
        n = rewrite_thin_reports(threads, args.model, examples, args.dry_run,
                                 limit=args.rewrite_thin, timeout=args.timeout)
        if n and not args.dry_run:
            save_json(TOPICS, topics)
        emit("REWRITTEN", n)
        return 0

    topics = load_json(TOPICS)
    threads = topics.get("threads", [])
    unsorted = [t for t in threads if UNSORTED_RE.match(str(t.get("id") or ""))]

    categories = topics.get("categories", [])
    valid_categories = {c["id"] for c in categories}
    # 톤을 맞출 표본. 너무 많이 보내면 프롬프트만 커진다.
    examples = [t for t in threads
                if not UNSORTED_RE.match(str(t.get("id") or ""))][:12]

    if not unsorted:
        # 미분류가 없어도 '보고서 없는 주제'는 메꿔야 한다. 그것까지 없으면
        # 여기서 끝난다 — 조용한 날 LLM 호출 0회가 비용 억제의 핵심이다.
        print("미분류 스레드가 없습니다.")
        filled = fill_missing_reports(threads, args.model, examples,
                                      args.dry_run, timeout=args.timeout)
        if filled and not args.dry_run:
            save_json(TOPICS, topics)
        emit("CLASSIFIED", filled)
        return 0

    target_ids: list[str] = []
    for t in sorted(unsorted, key=lambda x: str(x.get("id"))):
        for mid in t.get("message_ids", []):
            if mid not in target_ids:
                target_ids.append(mid)

    capped = len(target_ids) > args.max_messages
    if capped:
        print(f"미분류 {len(target_ids)}건 — 이번 실행은 오래된 "
              f"{args.max_messages}건만 하고 나머지는 다음 실행이 이어서 합니다.")
        target_ids = target_ids[:args.max_messages]

    msgs = read_messages(set(target_ids))
    if len(msgs) != len(target_ids):
        print(f"메시지를 다 찾지 못했습니다 ({len(msgs)}/{len(target_ids)}) — "
              "분류를 건너뜁니다.")
        emit("CLASSIFIED", 0)
        return 0

    print(f"미분류 {len(msgs)}건을 분류합니다 (모델: {args.model})")
    known_nodes = [n for n in (load_json(KNOWLEDGE).get("nodes", [])
                              if KNOWLEDGE.exists() else [])
                   if n.get("type") in ("app", "tool")]
    prompt = build_prompt(msgs, categories, examples, known_nodes)
    raw = call_claude(prompt, args.model, args.timeout)
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

    # 원문 글자 수 — 보고서가 원문보다 길지 않은지 볼 때 쓴다
    raw_by_id = {m["id"]: len(m.get("text") or "") for m in msgs}

    nid = next_thread_id(threads)
    assigned = []
    for c in clean:
        ids = c["message_ids"]
        tid = f"t-{nid:03d}"
        thread = {
            "id": tid,
            "category": c["category"],
            "title": c["title"],
            "summary": c["summary"],
            "start_msg": ids[0],
            "end_msg": ids[-1],
            "message_ids": ids,
        }
        if c["keywords"]:
            thread["keywords"] = list(c["keywords"])
        rebuilt.append(thread)
        assigned.append((tid, c, sum(raw_by_id.get(i, 0) for i in ids)))
        nid += 1

    topics["threads"] = rebuilt

    added_n = added_e = 0
    knowledge = None
    if not args.no_graph and KNOWLEDGE.exists():
        knowledge = load_json(KNOWLEDGE)
        added_n, added_e = merge_graph(knowledge, data.get("graph") or {},
                                       valid_categories)

    for tid, c, raw in assigned:
        kw = (" · 태그: " + ", ".join(c["keywords"])) if c["keywords"] else ""
        print(f"  {tid} [{c['category']}] {c['title']} "
              f"({len(c['message_ids'])}건, 본문 {len(c['report'])}자){kw}")
    if added_n or added_e:
        print(f"  관계 그래프: 노드 +{added_n}, 엣지 +{added_e}")

    if args.dry_run:
        print("--dry-run: 파일을 쓰지 않았습니다.")
        emit("CLASSIFIED", 0)
        return 0

    save_json(TOPICS, topics)
    if knowledge is not None and (added_n or added_e):
        save_json(KNOWLEDGE, knowledge)

    # 보고서는 스레드를 저장한 뒤에 쓴다. 보고서만 있고 스레드가 없으면
    # apply_reports 가 조용히 무시해 무해하지만, 반대(스레드만 있고 보고서 없음)는
    # 화면에 태그도 본문도 없는 주제로 보인다 — 그쪽이 눈에 띄는 손해다.
    wrote = 0
    for tid, c, raw in assigned:
        why = write_report(tid, {**c, "id": tid}, raw)
        if why:
            print(f"  보고서 못 씀({tid}): {why} — 제목·요지만 남습니다.")
        else:
            wrote += 1

    print(f"분류 완료: 스레드 {len(clean)}개, 메시지 {len(handled)}건, "
          f"보고서 {wrote}편")

    # 이번에 못 쓴 보고서와 예전에 빠진 보고서를 함께 메꾼다.
    filled = fill_missing_reports(rebuilt, args.model, examples, False,
                                  timeout=args.timeout)
    if filled:
        save_json(TOPICS, topics)
        print(f"밀린 보고서 {filled}편을 채웠습니다.")

    emit("CLASSIFIED", len(handled))
    return 0


if __name__ == "__main__":
    sys.exit(main())
