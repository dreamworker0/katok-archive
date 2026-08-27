# -*- coding: utf-8 -*-
"""AI 검증 주석(output/ai-reports/*.md)을 무인으로 쓴다.

무엇을 자동화하고 무엇을 자동화하지 않는가
    이 글의 규칙은 하나다 — **원 출처를 연 것만 단정한다**
    (`topic_reports.AI_REPORT_RULES`). 사람이 손으로 쓸 때 그 '연다'는 브라우저로
    페이지를 여는 일이었다. 여기서는 **파이썬이 실제로 그 주소를 연다.** 열리면
    단정해도 좋은 것, 안 열리면 '확인하지 못한 것' 이다. 규칙을 문장으로만 적어
    두고 모델의 선의에 맡기지 않는다는 뜻이다.

    이 구분이 왜 중요한지는 2026-08-27 에 두 번 확인했다. 두 모델이 파이어베이스
    전송량을 "Blaze 는 월 10GB" 로 **사이좋게 동의**했고 그것은 틀렸다. 그리고 한
    모델이 학회의 실재를 옳게 답했는데 몰아붙이자 **맞는 답을 철회**했고 그 오답이
    '합의' 로 기록됐다. 동의는 근거가 아니다. 열어 본 것만 근거다.

세 걸음
    1. **agy 가 찾는다** — `search_web` 이 헤드리스에서 승인 없이 돌고, 한국어
       자료(학회·정부 지침·인증 제도·국내 요금제)를 영어권 검색보다 잘 찾는다.
       이 방의 이야기가 대부분 그것이라 이쪽을 쓴다.
    2. **파이썬이 연다** — agy 가 댄 주소를 하나씩 열어 본다. 이 걸음이 이
       모듈의 존재 이유다. 여기서 열린 것만 3번에서 단정으로 쓸 수 있다.
    3. **claude 가 쓴다** — 사람 보고서·agy 결과·열림 여부표를 받아 규칙대로
       글을 만든다. 열리지 않은 주소에 기댄 문장은 '확인하지 못한 것' 으로
       내려보내라고 시킨다.

    두 모델을 쓰는 값은 판단이 하나 더 늘어서가 아니라 **보는 자료가 다르기**
    때문이다. 한쪽만으로는 이 두 걸음이 한 모델의 자기 검토가 된다.

실패는 예상된 결과다
    `llm.py` 와 같은 방침이다. 이 모듈의 함수는 던지지 않는다. agy 가 죽어도,
    주소가 안 열려도, claude 가 실패해도 그 한 편을 건너뛰고 다음으로 간다.
    검증 주석 하나 때문에 그날 갱신 전체가 멈춰서는 안 된다.

건너뛴 것을 기억한다
    인사·가입·안부처럼 대조할 사실이 없는 대화에는 쓰지 않는다. 다만 그냥 넘기면
    **매일 밤 같은 대화를 다시 물어본다.** 그래서 건너뛴 판단을 대장
    (`output/ai-reports-skipped.json`)에 적어 둔다.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from scripts import llm
from scripts.topic_reports import AI_REPORT_RULES, AI_REPORTS_DIR, load_reports

ROOT = Path(__file__).resolve().parent.parent

# 건너뛴 판단 대장. 없으면 처음부터 다시 묻는다(그래도 동작은 한다).
SKIP_LEDGER = ROOT / "output" / "ai-reports-skipped.json"

# agy 는 검색을 여러 번 돌기도 해서 claude 보다 오래 걸린다.
AGY_TIMEOUT_SEC = 420
AGY_MODEL = "gemini-3.7-flash-high"

# 주소 하나를 열어 보는 데 쓸 시간. 야간 갱신을 붙들지 않도록 짧게 둔다.
FETCH_TIMEOUT_SEC = 20

# 한 편에서 열어 볼 주소의 상한. agy 가 스무 개를 대는 날도 있는데, 그것을 다
# 열면 한 편에 몇 분이 든다.
MAX_LINKS_PER_REPORT = 8

# 하룻밤에 쓸 편수 기본값. 하나에 agy 1회 + 주소 몇 개 + claude 1회가 든다.
# 크게 잡으면 갱신이 늦어지고, 무엇보다 **한 번에 많이 쓰면 잘못된 틀이 여러
# 편에 한꺼번에 박힌다** — 사람이 눈으로 보고 고칠 여지를 남긴다.
DEFAULT_LIMIT = 5

# 봇 차단이 흔하다. 브라우저 UA 로 열지 않으면 살아 있는 페이지가 400 을 낸다
# (실측: kci.go.kr 은 curl 기본 UA 에 400, 브라우저 UA 에 200).
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

_URL_RE = re.compile(r"https?://[^\s<>\"'\])}]+")

# 이 갈래는 대체로 대조할 사실이 없다. 다만 **이것만으로 거르지는 않는다** —
# 실측(2026-08-27)에 '가입 안내' 가 community 에, '공감 소감' 이 welfare-practice
# 에 들어 있었다. 갈래는 힌트일 뿐이고 판단은 글을 읽고 한다.
THIN_CATEGORIES = ("members", "chat")


def load_skips() -> dict:
    """건너뛴 판단 대장. 깨져 있으면 빈 것으로 본다(다시 물으면 그만이다)."""
    try:
        return json.loads(SKIP_LEDGER.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_skips(skips: dict) -> None:
    SKIP_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    SKIP_LEDGER.write_text(
        json.dumps(skips, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8")


def pick_targets(threads: list[dict], limit: int,
                 ids: list[str] | None = None) -> list[dict]:
    """아직 검증 주석이 없는 주제를 고른다.

    이미 쓴 것은 건드리지 않는다. 다시 쓰고 싶으면 파일을 지우고 부르면 된다 —
    덮어쓰기를 기본으로 두면 사람이 손본 글이 밤새 조용히 사라진다.
    """
    if ids:
        want = set(ids)
        return [t for t in threads if t["id"] in want]

    skips = load_skips()
    out = []
    for t in sorted(threads, key=lambda x: x["id"], reverse=True):
        if (AI_REPORTS_DIR / ("%s.md" % t["id"])).exists():
            continue
        if t["id"] in skips:
            continue
        out.append(t)
        if len(out) >= limit:
            break
    return out


def call_agy(prompt: str, timeout: int = AGY_TIMEOUT_SEC) -> str | None:
    """agy -p 를 부른다. 실패하면 None.

    `search_web` 만 쓰게 한다. `read_url_content` 와 `run_command` 는 헤드리스에서
    승인을 받을 수 없어 어차피 막히고(실측), 무엇보다 **주소를 여는 일은 우리가
    한다.** 모델이 열었다고 말하는 것과 우리가 연 것은 다른 일이다.
    """
    cmd = ["agy", "--model", AGY_MODEL, "-p", prompt]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, cwd=str(ROOT))
    except FileNotFoundError:
        print("agy CLI 를 찾을 수 없습니다 — 검증을 건너뜁니다.")
        return None
    except subprocess.TimeoutExpired:
        print("agy 가 %d초를 넘겨 포기합니다." % timeout)
        return None
    if r.returncode != 0:
        print("agy 실패 (exit %d): %s" % (r.returncode, (r.stderr or "")[:300]))
        return None
    out = (r.stdout or "").strip()
    if not out:
        print("agy 가 빈 답을 돌려주었습니다.")
        return None
    # 도구 권한이 막히면 오류 문구를 stdout 으로 낸다 — 성공으로 세면 안 된다.
    if "no output produced" in out or "auto-denied" in out:
        print("agy 도구 권한이 막혔습니다: %s" % out[:200])
        return None
    return out


def extract_urls(text: str, limit: int = MAX_LINKS_PER_REPORT) -> list[str]:
    """답에서 주소를 뽑는다. 순서를 지키고 중복은 지운다."""
    seen, out = set(), []
    for m in _URL_RE.finditer(text or ""):
        u = m.group(0).rstrip(".,;:)")
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
        if len(out) >= limit:
            break
    return out


def open_url(url: str, timeout: int = FETCH_TIMEOUT_SEC) -> dict:
    """주소를 실제로 열어 본다. **이 함수가 이 모듈의 요점이다.**

    돌려주는 것: {url, final, ok, status, note}

    **`final` 이 리다이렉트를 따라간 끝 주소다.** 이것이 없으면 안 된다 —
    agy 의 검색 근거는 `vertexaisearch.../grounding-api-redirect/...` 형태의
    경유 주소로 돌아온다. 그대로 근거에 적으면 읽는 사람은 그 링크가 어디로
    가는지 알 수 없고, 그런 주소는 오래 살지도 않는다. 근거 링크를 다는 뜻이
    사라진다(실측 2026-08-27: 첫 자동 생성본의 근거 여덟 줄이 전부 그 경유
    주소였고, 보고서 스스로 "최종 도착지를 적지 못했다"고 적었다).
    본문을 읽어 주장까지 대조하지는 않는다 — 그것까지 기계에 맡기면 '읽었다고
    말하는 것' 이 또 하나 늘 뿐이다. 여기서 정하는 것은 **그 주소가 실재하고
    열리는가** 하나이고, 그것만으로도 지어낸 주소는 걸러진다(실측 2026-08-27:
    한 모델이 학회지 이름과 함께 그럴듯한 주소를 만들어 냈다).
    """
    # 한글 도메인·한글 경로는 그대로 보내면 latin-1 로 못 실어 예외가 난다.
    # 이 방 자료에 국가법령정보센터(법령/저작권법) 같은 주소가 실제로 나온다.
    try:
        sp = urllib.parse.urlsplit(url)
        host = sp.hostname.encode("idna").decode("ascii") if sp.hostname else ""
        if sp.port:
            host += ":%d" % sp.port
        url = urllib.parse.urlunsplit((
            sp.scheme, host,
            urllib.parse.quote(sp.path, safe="/%:@!$&'()*+,;=~"),
            urllib.parse.quote(sp.query, safe="/?=&%:@!$'()*+,;~"),
            "",
        ))
    except Exception:
        pass          # 못 바꾸면 원래 주소로 시도한다 — 그쪽이 맞는 날도 있다

    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            code = getattr(r, "status", 200)
            r.read(2048)          # 연결이 실제로 열리는지까지 본다
            return {"url": url, "final": r.geturl() or url,
                    "ok": 200 <= code < 400, "status": code, "note": ""}
    except urllib.error.HTTPError as e:
        return {"url": url, "final": url, "ok": False, "status": e.code,
                "note": "HTTP %d" % e.code}
    except Exception as e:                       # 인증서·DNS·타임아웃 전부
        return {"url": url, "final": url, "ok": False, "status": 0,
                "note": type(e).__name__ + ": " + str(e)[:120]}


def build_search_prompt(thread: dict, report: str) -> str:
    """agy 에게 줄 말. **발행된 보고서 본문만 준다.**

    미발행 대화 원문을 외부 서비스로 내보내지 않는다. 이 방침은 2026-08-27 에
    사람이 정한 것이고, 자동화한다고 느슨해질 이유가 없다.
    """
    return (
        "search_web 도구만 사용하라. read_url_content 와 run_command 는 쓰지 마라.\n"
        "학습된 기억으로 단정하지 말고 검색 결과에 근거하라.\n\n"
        "아래는 이미 공개된 대화 요약 보고서다. 여기 적힌 **사실 주장**을 검증하라.\n\n"
        "--- 제목: %s\n%s\n---\n\n"
        "답할 것:\n"
        "1. 본문에 사실 오류가 있는가? 있으면 무엇이 어떻게 틀렸는지.\n"
        "2. 읽는 사람이 놓치기 쉬운 배경·맥락 중 **검증 가능한 일반 사실**만.\n"
        "3. 검증할 사실 주장이 거의 없는 대화(인사·가입·안부·소감)라면 "
        "억지로 채우지 말고 첫 줄에 정확히 `검증대상없음` 이라고만 적어라.\n\n"
        "**주장마다 근거 URL 을 함께 적어라.** 주소 없는 주장은 쓰지 마라.\n"
        "개인의 경력·신원은 캐지 마라 — 기관·제도·제품처럼 공개된 것만.\n"
        "확인 못 한 것은 \"확인 불가\"라고 분명히 적어라. 지어내지 마라.\n"
        "서론 인사말 없이 항목 번호대로."
        % (thread.get("title", ""), report.strip())
    )


def build_compose_prompt(thread: dict, report: str, findings: str,
                         links: list[dict]) -> str:
    """claude 에게 줄 말. 열린 주소와 안 열린 주소를 **갈라서** 준다."""
    opened = [l for l in links if l["ok"]]
    failed = [l for l in links if not l["ok"]]
    lines = []
    if opened:
        lines.append("열린 주소(단정의 근거로 써도 되는 것):")
        # 끝 주소를 준다 — 경유 주소를 근거에 적으면 어디로 가는지 알 수 없다.
        lines += ["  - %s" % (l.get("final") or l["url"]) for l in opened]
    else:
        lines.append("열린 주소: 없음")
    if failed:
        lines.append("열리지 않은 주소(근거로 쓸 수 없다):")
        lines += ["  - %s  (%s)" % (l["url"], l["note"] or l["status"])
                  for l in failed]

    return (
        "너는 아카이브의 'AI 검증 주석'을 쓴다. 사람이 쓴 대화 요약 보고서 옆에\n"
        "붙는 짧은 글이고, 사람 보고서를 다시 쓰는 것이 아니다.\n\n"
        "== 지켜야 할 규칙 ==\n%s\n\n"
        "== 사람이 쓴 보고서 (제목: %s) ==\n%s\n\n"
        "== 다른 모델이 검색해 온 것 ==\n%s\n\n"
        "== 우리가 실제로 열어 본 주소 ==\n%s\n\n"
        "== 쓰는 법 ==\n"
        "- **열린 주소로 뒷받침되는 것만 단정하라.** 검색해 온 내용이라도 그\n"
        "  주소가 열리지 않았으면 단정하지 말고 '확인하지 못한 것' 으로 내려라.\n"
        "- 다른 모델이 그렇게 말했다는 것은 근거가 아니다. 동의는 근거가 아니다.\n"
        "- `## 짧은 제목` 으로 절을 나눠라. 마지막 두 절은 반드시\n"
        "  `## 확인하지 못한 것` 과 `## 근거` 다.\n"
        "- `## 근거` 에는 **위 '열린 주소' 에 적힌 주소를 글자 그대로** 옮겨\n"
        "  `[이름](주소)` 로 적어라. 검색 결과에서 본 다른 주소로 바꾸지 마라.\n"
        "  열리지 않은\n"
        "  것은 '확인하지 못한 것' 쪽에 왜 못 열었는지와 함께 적어라.\n"
        "- 사람 보고서에 이미 있는 말을 되풀이하지 마라. 보태는 것만 써라.\n"
        "- 법·의료·금전처럼 사람이 믿고 행동할 내용이면 첫머리에 이것이 일반\n"
        "  정보이지 전문가의 자문이 아님을 한 줄로 밝혀라.\n"
        "- 검증할 것이 없어 쓸 말이 없으면 **오직** `검증대상없음` 한 줄만 답하라.\n\n"
        "프론트매터·머리말·맺음말 없이 **본문 마크다운만** 답하라."
        % (AI_REPORT_RULES, thread.get("title", ""), report.strip(),
           (findings or "").strip(), "\n".join(lines))
    )


def write_report(tid: str, body: str, models: str, checked: str,
                 method: str) -> Path:
    """프론트매터를 붙여 파일로 남긴다."""
    AI_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    p = AI_REPORTS_DIR / ("%s.md" % tid)
    p.write_text(
        "---\nchecked: %s\nmodels: %s\nmethod: %s\n---\n\n%s\n"
        % (checked, models, method, body.strip()),
        encoding="utf-8")
    return p


def clean_body(raw: str) -> str:
    """모델이 붙인 프론트매터·코드펜스를 떼어 낸다.

    시키지 않아도 `---` 를 붙여 오는 날이 있다. 그대로 쓰면 프론트매터가 두 겹이
    되어 파서가 본문을 통째로 오해한다.
    """
    body = (raw or "").strip()
    if body.startswith("```"):
        body = re.sub(r"^```[a-zA-Z]*\n", "", body)
        body = re.sub(r"\n```$", "", body).strip()
    if body.startswith("---"):
        m = re.match(r"^---\n.*?\n---\n(.*)$", body, re.S)
        if m:
            body = m.group(1).strip()
    return body


def is_skip(text: str) -> bool:
    """'쓸 것이 없다' 는 답인지.

    **첫 줄이 그 말 하나일 때만** 건너뛴다. 본문 어딘가에 그 낱말이 들어 있는지를
    보면(처음에 그렇게 짰다) 「검증대상없음 이라고 답하지 않은 이유」 같은 문장을
    쓴 멀쩡한 보고서가 통째로 버려진다.
    """
    lines = [l.strip() for l in (text or "").strip().splitlines() if l.strip()]
    if not lines:
        return False
    first = lines[0].strip("`*#_ -").strip()
    return first == "검증대상없음"


def run_one(thread: dict, report: str, today: str, model: str,
            dry_run: bool = False) -> str:
    """한 편을 쓴다. 결과를 한 낱말로 돌려준다 — written/skipped/failed."""
    tid = thread["id"]
    hint = " (갈래상 얇을 수 있음)" if thread.get("category") in THIN_CATEGORIES else ""
    print("  %s %s%s" % (tid, thread.get("title", ""), hint))

    findings = call_agy(build_search_prompt(thread, report))
    if findings is None:
        return "failed"
    if is_skip(findings):
        print("    검증할 것이 없다고 판단 — 건너뜁니다.")
        return "skipped"

    urls = extract_urls(findings)
    links = [open_url(u) for u in urls]
    ok = sum(1 for l in links if l["ok"])
    print("    주소 %d개 중 %d개 열림" % (len(links), ok))

    body = llm.call_claude(
        build_compose_prompt(thread, report, findings, links),
        model=model, what="AI 보고서 작성")
    if body is None:
        return "failed"
    body = clean_body(body)
    if is_skip(body) or len(body) < 80:
        print("    쓸 말이 없다고 판단 — 건너뜁니다.")
        return "skipped"

    if dry_run:
        print("    --dry-run: 쓰지 않습니다 (%d자)" % len(body))
        return "written"

    method = "agy 검색 + 근거 주소 %d/%d 열림 확인" % (ok, len(links))
    p = write_report(tid, body, "claude-%s, %s" % (model, AGY_MODEL),
                     today, method)
    print("    %s (%d자)" % (p.name, len(body)))
    return "written"


def main() -> None:
    ap = argparse.ArgumentParser(description="AI 검증 주석을 쓴다")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                    help="한 번에 쓸 편수 (기본 %d)" % DEFAULT_LIMIT)
    ap.add_argument("--ids", default="",
                    help="주제 ID 를 쉼표로 (이미 있는 것도 다시 쓴다)")
    ap.add_argument("--model", default=llm.DEFAULT_MODEL, help="글을 쓸 모델")
    ap.add_argument("--dry-run", action="store_true", help="부르되 쓰지 않는다")
    ap.add_argument("--today", default="", help="checked 에 적을 날짜 (YYYY-MM-DD)")
    args = ap.parse_args()

    if args.today:
        today = args.today
    else:
        from datetime import date
        today = date.today().isoformat()

    topics_path = ROOT / "output" / "topics.json"
    try:
        threads = json.loads(topics_path.read_text(encoding="utf-8"))["threads"]
    except Exception as e:
        print("주제 목록을 읽지 못했습니다(%s) — AI 보고서를 건너뜁니다." % e)
        return

    reports = load_reports()
    ids = [x.strip() for x in args.ids.split(",") if x.strip()]
    targets = pick_targets(threads, args.limit, ids or None)
    if not targets:
        print("[AI보고서] 새로 쓸 주제가 없습니다.")
        return

    print("[AI보고서] %d편을 씁니다." % len(targets))
    skips = load_skips()
    counts = {"written": 0, "skipped": 0, "failed": 0}
    for t in targets:
        r = reports.get(t["id"])
        body = (r or {}).get("report") or ""
        if not body.strip():
            print("  %s 사람 보고서가 없어 건너뜁니다." % t["id"])
            counts["failed"] += 1
            continue
        try:
            res = run_one(t, body, today, args.model, args.dry_run)
        except Exception as e:      # 한 편의 사고가 갱신을 멈추지 않는다
            print("  %s 쓰다 실패: %s" % (t["id"], e))
            res = "failed"
        counts[res] += 1
        if res == "skipped" and not args.dry_run:
            skips[t["id"]] = {"why": "검증할 사실 없음", "when": today}

    if not args.dry_run:
        save_skips(skips)
    print("[AI보고서] 쓴 것 %d · 건너뛴 것 %d · 실패 %d"
          % (counts["written"], counts["skipped"], counts["failed"]))


if __name__ == "__main__":
    main()
