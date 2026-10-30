# -*- coding: utf-8 -*-
"""'AI에게 물어보기' 답을 **지금 기준으로** 다시 확인한다 — 멤버가 누르는 단추 하나.

밤 갱신의 AI 검증 주석(scripts/ai_reports.py)과 같은 세 걸음이다.
    1. 찾는다 — claude 웹 검색(서버 쪽 도구 하나만)이 근거 주소를 댄다. 안 되면 agy(검색
       도구 하나만 가진 Gemini 에이전트)가 대신 찾는다. 밤과 순서가 반대인 까닭은
       DEFAULT_ENGINE 머리말 — 사람이 기다리는 단추라 빠른 쪽이 먼저다.
    2. 연다   — **이 PC 가 그 주소를 실제로 열어 본다**(ai_reports.open_url — 내부망
       주소는 열지 않는다). 열린 것만 단정의 근거가 된다.
    3. 쓴다   — claude 가 열린 것과 안 열린 것을 갈라 받아 '확인됨 / 달라짐 / 확인 못함'
       으로 정리한다.

두 AI 를 토론시키지 않는다. 동의는 근거가 아니다 — 8월에 두 모델이 나란히 틀린 것이
'합의' 로 통과됐고, 몰아붙이자 맞는 답이 철회됐다(ai_reports.py 머리말). 두 모델을
쓰는 값은 보는 자료가 달라서다.

밤 검증과 다른 점
    - 대상이 주제 보고서가 아니라 **멤버가 받은 답**이다. 답은 발행본으로만 쓴 글이라
      바깥으로 나가는 것은 밤 검증과 같은 범위다(발행된 글).
    - 사람이 기다린다. 죽은 주소 되짚기(recover_links)는 하지 않는다 — 한 번에 1분이
      더 든다. 하나도 못 열었을 때만 다른 엔진으로 한 번 더 찾는다.
    - claude 는 llm.call_claude 가 아니라 여기서 더 좁게 띄운다. 멤버가 누르는 단추라
      ask_worker 와 같은 격리(공용 설정·CLAUDE.md 를 안 읽고 빈 임시 폴더에서, 토큰류
      환경 변수 없이)를 쓴다.

주고받기 (scripts/ask_worker.js 가 부른다)
    stdin  JSON {question, answer, today, engine?}
    stdout JSON {ok, body, sources:[{n,url}], opened, total, engine, skipped, error}
    stderr '@@stage search' · '@@stage open 3/5' · '@@stage write' — 화면의 진행 표시.
           그 밖의 줄은 로그다.

    python -m scripts.verify_answer --question "…" --answer-file a.txt   # 손으로 시험
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

from scripts import ai_reports as AR

WRITE_MODEL = "sonnet"
# 먼저 찾는 쪽. 2026-10-30 두 답×다섯 설정 실측 — claude 웹 검색 45~57초(검색 28~43초),
# 출처 4/6·2/2 열림 / agy(아르곤 high) 93~117초(검색 77~100초), 2/4·2/3 열림. 사람이
# 기다리는 단추라 claude 를 앞에 둔다. 검색 한 번에 claude 요금제 환산 $0.09~0.16 이
# 더 들고(agy 는 구글 요금제), 안 되면 agy 가 대신 찾는다. 밤 검증은 그대로 agy 가 먼저다.
DEFAULT_ENGINE = "claude"
SEARCH_TIMEOUT_SEC = 240        # 사람이 기다린다 — 밤(420초)보다 짧게
WRITE_TIMEOUT_SEC = 150
MAX_CLAIMS = 5
MAX_LINKS = 6
_SECRET_ENV = re.compile(r"TOKEN|KEY|SECRET|PASSWORD|CREDENTIAL|KATOK_SA", re.I)


def stage(name: str) -> None:
    """화면의 진행 표시. ask_worker 가 이 줄만 골라 Firestore 에 옮긴다."""
    print("@@stage " + name, file=sys.stderr, flush=True)


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def child_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not _SECRET_ENV.search(k)}
    env.update({"ENABLE_CLAUDEAI_MCP_SERVERS": "false", "DISABLE_AUTOUPDATER": "1",
                "FORCE_COLOR": "0"})
    return env


def call_claude(prompt: str, model: str, timeout: int, tools: str = "") -> str | None:
    """claude -p 를 좁게 띄운다(webapp-claude-isolation 표준). 실패하면 None.

    tools 는 비우거나 서버 쪽 도구 하나("WebSearch")만 — 이 PC 의 파일에 닿지 않는다."""
    cmd = ["claude", "-p", "--output-format", "json", "--model", model,
           "--tools", tools, "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
           "--setting-sources", "", "--disable-slash-commands", "--no-session-persistence"]
    if tools:
        cmd += ["--allowedTools", tools]
    try:
        with tempfile.TemporaryDirectory(prefix="katok-verify-",
                                         ignore_cleanup_errors=True) as work:
            r = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=timeout,
                               cwd=work, env=child_env())
    except (FileNotFoundError, OSError) as e:
        log("claude 를 부르지 못했습니다: %s" % e)
        return None
    except subprocess.TimeoutExpired:
        log("claude 가 %d초를 넘겼습니다." % timeout)
        return None
    if r.returncode != 0:
        log("claude 실패 (exit %d): %s" % (r.returncode, (r.stderr or "")[:200]))
        return None
    try:
        env = json.loads(r.stdout)
    except json.JSONDecodeError:
        log("claude 응답을 읽지 못했습니다.")
        return None
    if env.get("is_error"):
        log("claude 오류 응답: %s" % str(env.get("result"))[:200])
        return None
    if env.get("total_cost_usd") is not None:
        log("환산 $%.4f (%s)" % (env["total_cost_usd"], model))
    return env.get("result")


def build_search_prompt(question: str, answer: str, today: str) -> str:
    return (
        "search_web 도구만 사용하라. read_url_content 와 run_command 는 쓰지 마라.\n"
        "학습된 기억으로 단정하지 말고 검색 결과에 근거하라.\n\n"
        "오늘은 %s 이다. 아래는 사회복지 실무자들의 단톡방 아카이브에서, 멤버의 질문에\n"
        "AI 가 예전 대화를 읽고 쓴 답이다. 대화는 몇 달 전 것일 수 있고 한 사람의 말일\n"
        "수 있다. 이 답 속 **사실 주장** 가운데 지금 기준으로 바뀌었거나 틀렸을 수 있는\n"
        "것(요금·한도·버전·무료 행사·제품 기능·정책·법령)을 최대 %d개 골라 **최신 정보로**\n"
        "검증하라.\n\n"
        "--- 질문: %s\n--- 답:\n%s\n---\n\n"
        "**주장마다 근거 URL 을 함께 적어라.** 주소 없는 주장은 쓰지 마라.\n"
        "- 그 내용이 실제로 실려 있는 페이지의 주소를 적어라. 검색 중계·리다이렉트 주소,\n"
        "  홈페이지 대문(경로 없는 주소)은 안 된다.\n"
        "- 못 찾으면 그 주장은 \"확인 불가\" 라고 적어라. 지어내지 마라.\n"
        "개인의 경력·신원은 캐지 마라 — 기관·제도·제품처럼 공개된 것만.\n"
        "검증할 공개 사실이 거의 없으면(개인 경험담뿐이면) 첫 줄에 정확히 `검증대상없음`\n"
        "이라고만 적어라. 서론 없이 주장 번호대로."
        % (today, MAX_CLAIMS, question.strip(), answer.strip())
    )


_LOGIN_HOSTS = ("accounts.google.com", "login.microsoftonline.com", "nid.naver.com",
                "accounts.kakao.com", "www.facebook.com/login")
_LOGIN_PATH = re.compile(r"/(signin|sign-in|login|log-in|auth)(/|\?|$)", re.I)


def is_login(url: str) -> bool:
    """끝 주소가 로그인 화면인가. 열리긴 해도 내용은 못 본 것이다 — 실측 2026-10-30:
    초대 페이지가 accounts.google.com 로그인으로 넘어갔는데 출처 번호를 달고 나왔다."""
    u = str(url or "").lower()
    host = re.sub(r"^https?://", "", u).split("/")[0]
    return any(host == h or u.split("://", 1)[-1].startswith(h) for h in _LOGIN_HOSTS) \
        or bool(_LOGIN_PATH.search(u.split("://", 1)[-1][len(host):]))


def link_lines(links: list[dict]) -> tuple[list[str], list[dict]]:
    """열린 주소에 번호를 매겨 준다. 그 번호가 화면의 '출처 n' 이다.
    대문이나 로그인 화면만 열린 것은 번호를 주지 않는다 — 내용의 근거가 못 된다."""
    for l in links:
        if l["ok"] and is_login(l.get("final") or l["url"]):
            l["ok"], l["note"] = False, "로그인 화면으로 넘어가 내용을 못 봄"
    opened = [l for l in links if l["ok"] and not l.get("root")]
    roots = [l for l in links if l["ok"] and l.get("root")]
    failed = [l for l in links if not l["ok"] and not l.get("blocked")]
    blocked = [l for l in links if l.get("blocked")]
    sources = [{"n": i + 1, "url": l.get("final") or l["url"]} for i, l in enumerate(opened)]
    lines = ["열린 주소(근거로 써도 되는 것, 번호가 출처 번호다):"]
    lines += ["  [%d] %s" % (s["n"], s["url"]) for s in sources] or ["  없음"]
    if roots:
        lines.append("대문만 열린 주소(기관이 있다는 것까지만 — 구체적 주장의 근거로 못 쓴다):")
        lines += ["  - %s" % (l.get("final") or l["url"]) for l in roots]
    if failed:
        lines.append("열리지 않은 주소(근거로 쓸 수 없다):")
        lines += ["  - %s (%s)" % (l["url"], l["note"] or l["status"]) for l in failed]
    if blocked:
        # 왜 막았는지(풀린 IP)는 바깥 모델에 알리지 않는다 — ai_reports 와 같다.
        lines.append("열지 않기로 한 주소(근거로 쓸 수 없다):")
        lines += ["  - %s" % l["url"] for l in blocked]
    return lines, sources


def build_write_prompt(question: str, answer: str, today: str, findings: str,
                       lines: list[str]) -> str:
    return (
        "너는 단톡방 아카이브의 AI 답을 **지금 기준으로** 확인한 결과를 멤버에게 짧게\n"
        "알려 준다. 오늘은 %s 이다.\n\n"
        "== 멤버의 질문 ==\n%s\n\n== AI 가 예전 대화로 쓴 답 ==\n%s\n\n"
        "== 다른 모델이 웹에서 찾아 온 것 ==\n%s\n\n"
        "== 우리가 실제로 열어 본 주소 ==\n%s\n\n"
        "== 쓰는 법 ==\n"
        "- **열린 주소로 뒷받침되는 것만 단정하라.** 찾아 온 내용이라도 주소가 열리지\n"
        "  않았으면 '확인 못함' 으로 내려라. 다른 모델이 그렇게 말했다는 것은 근거가 아니다.\n"
        "- 너 자신이 따로 아는 지식으로 단정하지 마라.\n"
        "- 첫 줄: 머리말 없이 한 문장으로 전체 결과(예: '대부분 그대로지만 무료 행사 둘은\n"
        "  끝났어요.').\n"
        "- 그다음 아래 머리말 중 **해당하는 것만** 혼자 한 줄로 쓰고, 그 아래 '- ' 목록으로:\n"
        "  **✅ 확인됨** / **⚠️ 달라짐** / **❓ 확인 못함**\n"
        "- 항목마다 '답의 어느 말이 → 지금은 어떤지' 를 1~2문장, 존댓말로. 근거는 문장 끝에\n"
        "  '(출처 1)' 처럼 위 열린 주소의 번호로만 단다. **주소를 글에 쓰지 마라.**\n"
        "- 질문에 답하는 데 중요한 주장만, 모두 합쳐 %d개까지.\n"
        "- 법·의료·금전처럼 믿고 행동할 내용이면 끝에 '일반 정보이며 전문가 자문이 아니에요'\n"
        "  한 줄.\n"
        "- 확인할 공개 사실이 없으면 **오직** `검증대상없음` 한 줄만 답하라.\n"
        "마크다운은 위의 굵은 머리말과 '- ' 목록만 쓴다. 표·제목(#)·링크는 쓰지 마라."
        % (today, question.strip(), answer.strip(), (findings or "").strip(),
           "\n".join(lines), MAX_CLAIMS)
    )


def clean(body: str) -> str:
    """글 속 주소·자리표를 지운다. 링크는 화면이 sources 로만 단다."""
    body = AR.clean_body(body or "")
    body = AR._URL_RE.sub("", body)
    body = re.sub(r"!\[\[[^\]]*\]\]", "", body)
    return re.sub(r"\n{3,}", "\n\n", body).strip()


def cited_numbers(body: str) -> set[int]:
    """글에서 단 출처 번호. '(출처 2, 3)'·'(출처 1·2)' 처럼 묶어 적기도 한다 —
    처음엔 첫 번호만 잡아 출처 3 의 링크가 빠졌다(실측 2026-10-30)."""
    out: set[int] = set()
    for grp in re.findall(r"출처\s*((?:\d+\s*(?:,|·|및|와|과)?\s*)+)", body or ""):
        out.update(int(n) for n in re.findall(r"\d+", grp))
    return out


def search_with(name: str, prompt: str, used: list[str]) -> str | None:
    """한 엔진으로 찾는다. name 은 'claude' 나 'agy'."""
    if name == "agy":
        out = AR.call_agy(prompt, SEARCH_TIMEOUT_SEC)
        if out is not None:
            used.append(AR.SEARCH_MODEL)
        return out
    out = call_claude(prompt, "sonnet", SEARCH_TIMEOUT_SEC, tools="WebSearch")
    if out is not None:
        used.append("claude-sonnet")
    return out


def other(name: str) -> str:
    return "agy" if name == "claude" else "claude"


def search(prompt: str, engine: str, used: list[str]) -> str | None:
    """먼저 engine 으로, 안 되면 다른 쪽으로 찾는다."""
    out = search_with(engine, prompt, used)
    if out is None:
        log("%s 검색이 안 돼 %s 로 찾습니다." % (engine, other(engine)))
        out = search_with(other(engine), prompt, used)
    return out


def open_all(urls: list[str]) -> list[dict]:
    stage("open 0/%d" % len(urls))
    with ThreadPoolExecutor(max_workers=6) as ex:
        links = list(ex.map(AR.open_url, urls))
    stage("open %d/%d" % (sum(1 for l in links if l["ok"]), len(urls)))
    return links


def run(question: str, answer: str, today: str, engine: str = DEFAULT_ENGINE) -> dict:
    t0 = time.time()
    used: list[str] = []
    stage("search")
    findings = search(build_search_prompt(question, answer, today), engine, used)
    if findings is None:
        return {"ok": False, "error": "출처를 찾지 못했어요."}
    if AR.is_skip(findings):
        return {"ok": True, "skipped": True, "body": "", "sources": [], "opened": 0,
                "total": 0, "engine": " + ".join(used), "sec": round(time.time() - t0)}

    links = open_all(AR.extract_urls(findings, MAX_LINKS))
    tried = {"agy" if u == AR.SEARCH_MODEL else "claude" for u in used}
    if not any(l["ok"] and not l.get("root") for l in links) and len(tried) < 2:
        # 하나도 못 열었으면 다른 엔진으로 한 번만 더 찾는다. 같은 쪽을 되풀이하면
        # 같은 죽은 주소를 또 댄다(ai_reports.recover_links 머리말).
        nxt = other(next(iter(tried))) if tried else other(engine)
        log("열린 주소가 없어 %s 로 한 번 더 찾습니다." % nxt)
        stage("search")
        again = search_with(nxt, build_search_prompt(question, answer, today), used)
        if again and not AR.is_skip(again):
            findings = findings + "\n\n" + again
            seen = {l["url"] for l in links}
            links += open_all([u for u in AR.extract_urls(again, MAX_LINKS) if u not in seen])

    lines, sources = link_lines(links)
    stage("write")
    body = call_claude(build_write_prompt(question, answer, today, findings, lines),
                       WRITE_MODEL, WRITE_TIMEOUT_SEC)
    if body is None:
        return {"ok": False, "error": "확인 결과를 쓰지 못했어요."}
    body = clean(body)
    skipped = AR.is_skip(body)
    # 글에서 실제로 단 번호의 출처만 남긴다 — 안 쓴 주소까지 늘어놓으면 근거처럼 보인다.
    cited = cited_numbers(body)
    return {"ok": True, "skipped": skipped, "body": "" if skipped else body,
            "sources": [s for s in sources if s["n"] in cited],
            "opened": len(sources), "total": len(links), "engine": " + ".join(used),
            "sec": round(time.time() - t0)}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--question")
    p.add_argument("--answer-file")
    p.add_argument("--engine", choices=["agy", "claude"], default=None)
    a = p.parse_args()
    if a.question:
        with open(a.answer_file, encoding="utf-8") as f:
            req = {"question": a.question, "answer": f.read()}
    else:
        req = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    today = req.get("today") or time.strftime("%Y-%m-%d")
    engine = a.engine or req.get("engine") or DEFAULT_ENGINE
    try:
        out = run(str(req.get("question", "")), str(req.get("answer", "")), today, engine)
    except Exception as e:                      # 실패는 결과다 — 던지지 않는다
        out = {"ok": False, "error": "확인하다 멈췄어요.", "detail": type(e).__name__}
    sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False).encode("utf-8"))


if __name__ == "__main__":
    main()
