"""주제별 대화 보고서 — 마크다운 원본을 읽어 발행본에 얹는다.

원문을 발행하지 않기로 한 이상 요약이 원문을 대신해야 한다. 그런데 한 줄
요약으로는 내용을 알 수 없었고, 서술형으로 늘린 뒤에도 문제가 남았다 —
대화 2건짜리와 47건짜리의 분량이 거의 같았다. 방장이 짚었다:
"분량에 비례로 정리해야 할 것 같다. 요약이라는 느낌보다는 대화 보고서."
그리고 "그냥 md 파일로 관리할까?"

마크다운을 원본으로 삼은 이유:
  - 소제목·목록·표·인용이 공짜다. 보고서 꼴을 짜는 데 JSON 블록보다 낫다.
  - 내려받기가 변환 없이 그대로다. 화면에 보이는 것이 곧 파일이다.
  - 이 앱이 없어져도 내용이 남는다. 아카이브의 값은 앱이 아니라 글에 있다.
  - git diff 가 읽힌다. 보고서를 고친 이력이 그대로 남는다.

topics.json 을 직접 고치지 않고 별도 파일로 두는 이유:
  - 증분 수집(ingest_incremental)이 topics.json 에 미분류 스레드를 계속 덧붙인다.
    같은 파일을 양쪽에서 만지면 손으로 쓴 보고서가 덮여 날아간다.
  - 보고서는 사람이 원문을 읽고 쓴 것이라 재생성이 비싸다.

형식(output/reports/{스레드ID}.md):

    ---
    title: rhwp 마켓플레이스 도전과 오피스 구독 부담
    summary: 드라이브에서 hwp 를 바로 열려는 시도와 테크숩 가격 인상
    keywords: rhwp, 마켓플레이스, 테크숩, 한컴오피스
    ---

    ## 무슨 일이 있었나

    김종원이 **rhwp 엔진** 기반 설치형 프로그램을 ...

    ## 핵심 정리

    - 모바일 hwp 편집은 익스텐션 대신 한컴독스 앱으로
    - 공개 저장소에 API 키 노출 → 환경변수 분리 후 재공개

사진·첨부는 여기에 적지 않는다. media 발행본에 thread_id 가 있어 화면이
알아서 붙인다 — 사람이 두 군데를 맞춰 적으면 반드시 어긋난다.
"""

from __future__ import annotations

import re
from pathlib import Path

REPORTS_DIR = Path(__file__).resolve().parent.parent / "output" / "reports"

# 대화 건수별 본문 최소 분량. 47건짜리와 2건짜리가 같은 분량이면 보고서가
# 아니다. 넘치는 것은 막지 않는다 — 할 말이 많은 주제도 있다.
MIN_BODY_BY_COUNT = (
    (3, 60),       # ~3건    한두 문장이면 충분하다
    (8, 200),      # 4~8건   문단 하나 + 짧은 목록
    (15, 380),     # 9~15건  절을 나눈다
    (25, 650),     # 16~25건 여러 절 + 표
    (10**9, 900),  # 26건~   본격적인 보고서
)

_FM = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z", re.S)


def parse_report(text: str, where: str = "") -> dict:
    """프론트매터 + 본문으로 가른다.

    pyyaml 을 쓰지 않는다. 필요한 건 문자열 세 개뿐인데 의존성을 늘릴 이유가
    없고, 값에 콜론이 흔해서(제목에 URL·시각) 일반 YAML 파서가 오히려 걸린다.
    그래서 첫 콜론에서만 자른다.
    """
    m = _FM.match(text)
    if not m:
        raise ValueError("%s: --- 로 감싼 프론트매터가 없습니다" % where)
    head, body = m.group(1), m.group(2)

    meta: dict[str, str] = {}
    for line in head.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise ValueError("%s: 프론트매터 '%s' 에 콜론이 없습니다" % (where, line))
        k, v = line.split(":", 1)
        meta[k.strip()] = v.strip()

    if not meta.get("title"):
        raise ValueError("%s: title 이 없습니다" % where)
    if not meta.get("summary"):
        raise ValueError("%s: summary 가 없습니다" % where)

    kw = [x.strip() for x in (meta.get("keywords") or "").split(",")]
    return {
        "title": meta["title"],
        "summary": meta["summary"],
        "keywords": [x for x in kw if x],
        "report": body.strip(),
    }


def load_reports(path: Path | None = None) -> dict[str, dict]:
    """output/reports/*.md 를 전부 읽는다. 폴더가 없으면 빈 dict."""
    d = path or REPORTS_DIR
    if not d.exists():
        return {}
    out: dict[str, dict] = {}
    for p in sorted(d.glob("*.md")):
        out[p.stem] = parse_report(p.read_text(encoding="utf-8"), p.name)
    return out


def min_body_for(message_count: int) -> int:
    for upper, need in MIN_BODY_BY_COUNT:
        if message_count <= upper:
            return need
    return MIN_BODY_BY_COUNT[-1][1]


def body_length(report: str) -> int:
    """본문 글자 수. 마크다운 기호는 빼고 실제 내용만 센다."""
    t = re.sub(r"^#{1,6}\s*", "", report, flags=re.M)
    t = re.sub(r"^[-*]\s+", "", t, flags=re.M)
    t = re.sub(r"^>\s*", "", t, flags=re.M)
    t = re.sub(r"[*=`|]", "", t)
    return len(re.sub(r"\s+", "", t))


def apply_reports(threads: list[dict], reports: dict[str, dict]) -> int:
    """스레드 목록에 보고서를 얹는다. 얹은 개수를 돌려준다.

    threads 를 제자리에서 고친다. 보고서만 있고 스레드에는 없는 ID 는 조용히
    무시한다 — 주제가 합쳐지거나 사라져도 파이프라인이 멈추면 안 된다.
    """
    applied = 0
    for t in threads:
        r = reports.get(t["id"])
        if not r:
            continue
        t["title"] = r["title"]
        t["summary"] = r["summary"]
        if r["keywords"]:
            t["keywords"] = list(r["keywords"])
        if r["report"]:
            t["report"] = r["report"]
        applied += 1
    return applied


def thin_reports(
    threads: list[dict], raw_chars: dict[str, int] | None = None
) -> list[tuple[str, int, int, int]]:
    """대화량에 비해 본문이 얇은 주제. (id, 대화수, 본문길이, 기준)

    건수만 보면 안 된다. "환영합니다"가 여섯 번 오간 주제에 200자를 요구하면
    없는 내용을 지어내게 된다. 그래서 원문 글자 수의 절반을 넘겨 요구하지
    않는다 — 요약은 원문보다 짧아야 하고, 짧은 대화의 보고서는 짧아야 한다.
    """
    raw_chars = raw_chars or {}
    out = []
    for t in threads:
        if not t.get("report"):
            continue
        n = t.get("count") or 0
        need = min_body_for(n)
        raw = raw_chars.get(t["id"])
        if raw is not None:
            need = min(need, int(raw * 0.5))
        got = body_length(t["report"])
        if got < need:
            out.append((t["id"], n, got, need))
    return out
