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

다만 '어디쯤에서 오간 사진인가'는 보고서만 아는 정보라, 자리만 가리킬 수
있게 했다. 본문에 한 줄로

    ![[msg-000123]]

이라 적어 두면 화면이 그 message id 의 사진·첨부를 그 자리에 끼운다.
내용을 옮겨 적는 것이 아니라 자리만 가리키므로 어긋날 여지가 없고,
자리표가 없는 사진은 예전처럼 보고서 끝에 모인다.

원본은 이 md 파일이다. 다만 대화 데이터를 저장소에서 뺀 뒤로 원본이 로컬
디스크 한 곳에만 남았다. 발행하면 본문이 threads/all 문서에 통째로 실리므로
Firestore 가 결과적으로 원격 사본이 된다 — 디스크를 잃으면

    node scripts/restore_reports.js

로 md 를 되살린다(마지막 발행 판까지. 고친 이력은 남지 않는다).
"""

from __future__ import annotations

from difflib import SequenceMatcher
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
_URL = re.compile(r"https?://\S+", re.I)
_ANY_ANCHOR = re.compile(r"^!\[\[(?:link:)?([A-Za-z0-9_-]+)\]\]\s*$", re.M)
_MEDIA_ANCHOR = re.compile(r"^!\[\[([A-Za-z0-9_-]+)\]\]\s*$", re.M)
_LINK_ANCHOR = re.compile(r"^!\[\[link:([A-Za-z0-9_-]+)\]\]\s*$", re.M)
_CONTEXT_MIN_CHARS = 18
_CONTEXT_MATCH = 0.72
_CONTEXT_AMBIGUITY = 0.04


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


def _context_text(value: str) -> str:
    """링크·마크다운·문장부호를 뺀 문맥 비교 문자열."""
    value = _URL.sub(" ", value or "")
    value = re.sub(r"^#{1,6}\s+|^>\s?|^\s*[-*]\s+", " ", value, flags=re.M)
    return re.sub(r"[^0-9a-z가-힣]+", "", value.lower())


def _context_blocks(report: str) -> list[dict]:
    """보고서의 사람이 읽는 블록과 원본 줄 위치를 돌려준다."""
    lines = report.replace("\r\n", "\n").split("\n")
    blocks = []
    start = None
    for i in range(len(lines) + 1):
        line = lines[i] if i < len(lines) else ""
        if line.strip():
            if start is None:
                start = i
            continue
        if start is None:
            continue
        raw = "\n".join(lines[start:i])
        stripped = raw.strip()
        if (
            not _ANY_ANCHOR.fullmatch(stripped)
            and not re.fullmatch(r"#{1,6}\s+.*", stripped)
        ):
            normalized = _context_text(raw)
            if normalized:
                blocks.append({
                    "start": start,
                    "end": i - 1,
                    "text": normalized,
                })
        start = None
    return blocks


def _context_score(source: str, block: str) -> float:
    if min(len(source), len(block)) < _CONTEXT_MIN_CHARS:
        return 0.0
    if source in block or block in source:
        return 0.99
    return SequenceMatcher(None, source, block, autojunk=False).ratio()


def _best_context_block(text: str, blocks: list[dict]) -> tuple[int, float] | None:
    source = _context_text(text)
    if len(source) < _CONTEXT_MIN_CHARS:
        return None
    ranked = sorted(
        (
            (_context_score(source, block["text"]), block["end"])
            for block in blocks
        ),
        reverse=True,
    )
    if not ranked or ranked[0][0] < _CONTEXT_MATCH:
        return None
    if (
        len(ranked) > 1
        and ranked[1][0] >= _CONTEXT_MATCH
        and ranked[0][0] - ranked[1][0] <= _CONTEXT_AMBIGUITY
    ):
        return None
    return ranked[0][1], ranked[0][0]


def _is_media_message(message: dict) -> bool:
    return bool(
        message.get("images")
        or message.get("file")
        or message.get("is_file_share")
        or message.get("kind") in {"image", "file"}
    )


def _insert_context_markers(report: str, markers: dict[int, list[str]]) -> str:
    if not markers:
        return report
    lines = report.replace("\r\n", "\n").split("\n")
    for end, values in sorted(markers.items(), reverse=True):
        pos = end + 1
        if pos < len(lines) and not lines[pos].strip():
            pos += 1
            payload = values + [""]
        elif pos == len(lines):
            payload = [""] + values
        else:
            payload = [""] + values + [""]
        lines[pos:pos] = payload
    return "\n".join(lines)


def place_context_anchors(report: str, messages: list[dict]) -> str:
    """확실한 링크·미디어만 관련 보고서 블록 뒤에 자리표로 붙인다.

    결과에는 메시지 본문이 들어가지 않는다. 화면이 이미 발행하는 링크·미디어
    목록에서 같은 message id 를 찾아 자리표를 채우므로 개인정보 발행 범위도
    넓어지지 않는다.
    """
    if not report or not messages:
        return report
    blocks = _context_blocks(report)
    if not blocks:
        return report

    manual_media = set(_MEDIA_ANCHOR.findall(report))
    manual_links = set(_LINK_ANCHOR.findall(report))
    markers: dict[int, list[str]] = {}

    for message in messages:
        mid = str(message.get("id") or "")
        if not mid or not message.get("urls") or mid in manual_links:
            continue
        match = _best_context_block(message.get("text") or "", blocks)
        if match:
            markers.setdefault(match[0], []).append(f"![[link:{mid}]]")

    for index, message in enumerate(messages):
        mid = str(message.get("id") or "")
        if not mid or mid in manual_media or not _is_media_message(message):
            continue

        candidates = []
        own = _best_context_block(message.get("text") or "", blocks)
        if own:
            candidates.append((own[1], own[0], 0))

        for distance in (1, 2):
            for neighbor_index in (index - distance, index + distance):
                if neighbor_index < 0 or neighbor_index >= len(messages):
                    continue
                neighbor = messages[neighbor_index]
                if neighbor.get("nickname") != message.get("nickname"):
                    continue
                match = _best_context_block(neighbor.get("text") or "", blocks)
                if match:
                    candidates.append((match[1] - (distance * 0.01), match[0], distance))

        candidates.sort(reverse=True)
        if not candidates or candidates[0][0] < _CONTEXT_MATCH:
            continue
        if (
            len(candidates) > 1
            and candidates[0][0] - candidates[1][0] <= _CONTEXT_AMBIGUITY
        ):
            continue
        markers.setdefault(candidates[0][1], []).append(f"![[{mid}]]")

    return _insert_context_markers(report, markers)


def min_body_for(message_count: int) -> int:
    for upper, need in MIN_BODY_BY_COUNT:
        if message_count <= upper:
            return need
    return MIN_BODY_BY_COUNT[-1][1]


def body_length(report: str) -> int:
    """본문 글자 수. 마크다운 기호는 빼고 실제 내용만 센다."""
    t = re.sub(r"^!\[\[[^\]]+\]\]\s*$", "", report, flags=re.M)  # 사진 자리표는 내용이 아니다
    t = re.sub(r"^#{1,6}\s*", "", t, flags=re.M)
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
