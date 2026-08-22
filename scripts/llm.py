# -*- coding: utf-8 -*-
"""`claude -p` 호출과 응답 읽기 — 파이프라인 공용.

왜 따로 뽑았는가
    `call_claude` 와 `parse_reply` 는 `classify_unsorted.py`(1,204줄) 안에 있었고,
    **일곱 모듈이 거기서 import 했다** — adopt_orphans · assign_secondary ·
    audit_thread_fit · retag_reports · retire_tag · split_tag. 태그 하나를 나누는
    스크립트가 분류기 전체를 끌고 들어왔고, 분류기를 고칠 때마다 관계없는 모듈이
    함께 흔들렸다.

    `jsonio.py` 를 뽑을 때와 똑같은 상황이다. 그 모듈 docstring 에 적어 둔 문장이
    여기에도 그대로 들어맞는다 — "실제로는 공용이었고, 그래서 한쪽을 고칠 때마다
    관계없는 모듈이 함께 딸려 흔들렸다".

    예전 이름으로 부르는 곳이 많고 검사도 그 이름을 쓰므로,
    `classify_unsorted` 에는 이름만 남긴다.

이 파이프라인에서 LLM 을 쓰는 규칙
    **실패는 예외가 아니라 예상된 결과다.** 그래서 이 모듈의 함수는 던지지 않고
    `None` 을 돌려준다. LLM 장애가 그날 타임라인·통계·삭제 요청 반영을 통째로
    날려서는 안 된다 — 부르는 쪽은 `None` 을 받으면 그 일만 건너뛰고 나아간다.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

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


def call_claude(prompt: str, model: str, timeout: int = TIMEOUT_SEC,
                what: str = "분류") -> str | None:
    """claude -p 를 호출해 결과 문자열을 돌려준다. 실패하면 None.

    `what` 은 실패 로그에 쓸 일 이름이다. 이 함수를 분류 말고도 여섯 곳에서 쓴다
    (`assign_secondary`·`audit_thread_fit`·`retag_reports`·`split_tag`·
    `retire_tag`·`adopt_orphans`) — 무엇이 실패했는지 로그가 틀리게 말하면
    로그를 읽는 사람이 엉뚱한 데를 본다.

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
        print(f"claude CLI 를 찾을 수 없습니다 — {what}를 건너뜁니다.")
        return None
    except subprocess.TimeoutExpired:
        print(f"{what}가 {timeout}초를 넘겨 포기합니다 — 건너뜁니다.")
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
