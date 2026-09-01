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

# AI 보고서(사람 보고서와 짝을 이루는 기계의 말)는 따로 둔다. 같은 폴더에 섞으면
# 밤 자동 갱신이 사람 보고서로 알고 덮어쓴다 — 두 글은 쓰는 주체도 규칙도 다르다.
AI_REPORTS_DIR = Path(__file__).resolve().parent.parent / "output" / "ai-reports"

# 인용 한 줄의 상한. 넘기면 요약이 아니라 원문 발행이다.
MAX_VERBATIM_CHARS = 40

# 구조를 요구하는 기준. 이 두 숫자가 규칙 글과 검사에 함께 쓰인다 — 프롬프트가
# 요구하는 것과 검사가 보는 것이 어긋나면 규칙이 아니라 취향이 된다.
QUOTE_REQUIRED_FROM = 6     # 대화 6건 이상이면 인용이 하나는 있어야 한다
SECTION_REQUIRED_FROM = 10  # 대화 10건 이상이면 절을 나눈다

# 건수만 보면 새는 구멍이 있다. 대화 5건인데 한 문단 450자로 쓴 보고서가 두 기준을
# 모두 비껄러 나갔다(2026-07-28 지적). 짧은 대화라도 길게 쓰면 구조가 필요하다.
QUOTE_REQUIRED_CHARS = 250    # 본문 250자 넘으면 인용이 하나는 있어야 한다
SECTION_REQUIRED_CHARS = 400  # 본문 400자 넘으면 절·목록·표 중 하나는 있어야 한다

# 보고서 본문 규칙 — **원본은 여기 하나다.**
#
# 예전에는 규칙이 두 곳에 따로 있었다. 밤 자동 갱신이 쓰는 분류 프롬프트에는
# "링크나 사진 자리표를 넣지 마세요, 자료는 화면 아래에 따로 붙습니다" 뿐이었고,
# 인용·절 나눔 규칙은 보고서 전용 프롬프트에만 있었다. 그래서 자동 갱신이 만든
# 보고서는 한 덩어리 산문이고 사진·링크가 전부 글 끝에 모였다(2026-07-27 실측).
# 규칙을 한 군데 두고 두 프롬프트가 같은 것을 읽게 한다.
REPORT_RULES = f"""- 사실만 씁니다. 대화에 없는 내용을 채우지 마세요.
- **읽는 사람이 구조를 눈으로 볼 수 있게** 씁니다. 한 덩어리 산문은 안 됩니다.

### 인용 — 자료가 본문 사이로 들어오는 통로다
- 결정적인 **짧은 말**을 인용(`>`)으로 옮기세요. 한 편에 1~3개. 말투·이모티콘까지
  그대로. **대화 {QUOTE_REQUIRED_FROM}건 이상이거나 본문이 {QUOTE_REQUIRED_CHARS}자를
  넘으면** 인용이 하나는 있어야 합니다.
- **한 인용은 {MAX_VERBATIM_CHARS}자를 넘기지 마세요.** 긴 글은 인용하지 말고
  요약하세요. 이 아카이브는 요약을 발행하고 원문은 발행하지 않습니다. 긴 글을
  통째로 옮기면 그건 원문 발행이고, 검사에서 걸려 보고서가 버려집니다.
- 긴 글에서 꼭 살리고 싶은 표현이 있으면 그 **한 구절만** 따오세요.

### 절 — 흐름이 눈에 보이게 나눈다
- **대화 {SECTION_REQUIRED_FROM}건 이상이거나 본문이 {SECTION_REQUIRED_CHARS}자를
  넘으면** `## 짧은 제목` 으로 절을 나누거나 `-` 목록으로 갈라 쓰세요. 한 문단이
  400자를 넘으면 읽는 사람이 눈으로 짚을 곳이 없습니다.
  문제 제기 → 시도 → 막힌 곳 → 해결 같은 흐름이면 그대로 절이 됩니다.
- 짚을 것이 여럿이면 `-` 목록으로, 견주는 것이면 표로 쓰세요.
- 정말 중요한 한두 곳만 `**굵게**`. 남용하면 아무것도 강조되지 않습니다.

### 사진·첨부·링크는 **본문 사이에** 놓으세요
- 그 자료를 이야기하는 문단 **바로 뒤에** 자리표를 한 줄로 적습니다.
  · 사진·첨부 → `![[msg-000123]]`
  · 링크      → `![[link:msg-000123]]`
- **위 대화 목록에 있는 message id 만** 씁니다. 없는 id 를 지어내면 검사에서
  버려집니다(내용이 아니라 자리만 가리키는 것이라 틀릴 여지가 없습니다).
- 자리표를 안 놓은 자료는 글 끝에 모입니다. 그러면 '글 따로 자료 따로'가 되어
  읽기 불편합니다 — 사진이 왜 거기 있는지 본문이 말해 주어야 합니다.
- 같은 자리에 여러 장이 오갔으면 자리표를 여러 줄로 잇대어 적습니다."""



# AI 보고서 규칙 — 사람 보고서 옆에 붙는 기계의 검증 주석(output/ai-reports/)이
# 지키는 것. **원본은 여기 하나다.**
#
# 통과 기준이 '두 모델의 합의' 였던 판을 버리고 '원 출처 확인' 으로 바꾼 이유가
# 있다. 2026-08-27 첫 일곱 편을 만들면서 두 번 사고가 났다.
#
#   1. 두 모델이 Hosting 무료 전송량을 "Blaze 는 월 10GB" 로 **사이좋게 동의**했다.
#      공식 요금 페이지를 열어 보니 두 요금제 모두 하루 360MB 였다. 합의가 오류를
#      막은 것이 아니라 **통과시켰다.**
#   2. 한 모델이 '한국디지털사회복지학회' 가 실재한다고 옳게 답했는데, 다른 쪽
#      검색(미국 기준)이 못 찾자 몰아붙였고 **맞는 답이 철회됐다.** 그 잘못된
#      철회가 '합의' 로 기록됐다. 홈페이지를 직접 열고서야 바로잡혔다.
#
# 둘 다 같은 것을 말한다 — 모델이 몇이든 **동의는 근거가 아니다.** 같은 오해를
# 나눠 갖거나 한쪽이 다른 쪽에 끌려간다. 근거는 원 출처 하나뿐이다.
AI_REPORT_RULES = """- **원 출처를 연 것만 단정합니다.** 두 모델이 합의했다는 사실은 근거가 아닙니다.
  합의는 '무엇을 확인할지' 를 고르는 단계일 뿐이고, 보고서에 단정으로 싣는 것은
  공식 문서·기관 홈페이지·저장소 파일을 **실제로 열어 본 것**에 한합니다.
- **확인하지 못한 것은 따로 모아 적습니다.** 마지막에 `## 확인하지 못한 것` 절을
  두고, 확인 못 한 이유까지 한 줄로 적으세요. 빈칸을 그럴듯한 말로 채우지 마세요.
- **근거 링크를 답니다.** 마지막에 `## 근거` 절을 두고 연 주소를 `[이름](주소)` 로
  적으세요. **직접 연 것과 검색 결과로만 안 것을 갈라 적습니다** — 읽는 사람이
  어디까지 믿을지 스스로 정할 수 있어야 합니다. 링크 없이 "공식 문서에 따르면"
  이라고만 쓰면 그 말을 확인할 길이 없어 규칙이 없는 것과 같습니다.
- **검색에 없다는 것은 없다는 뜻이 아닙니다.** 도구의 언어·지역 한계를 먼저
  의심하세요. 한국 학회·기관·제도는 영어권 검색에 잘 잡히지 않습니다.
- **한쪽 모델을 몰아붙여 얻은 동의는 버립니다.** 답이 바뀌면 그 자체가 신호가
  아니라 잡음입니다. 바뀐 답이 아니라 원 출처를 보세요.
- **틀렸던 자리는 지우지 말고 남깁니다.** 무엇을 어떻게 잘못 짚었는지가 다음에
  읽는 사람에게 가장 쓸모 있습니다.
- **검증할 것이 없는 대화에는 쓰지 않습니다.** 인사·가입·안부처럼 대조할 사실이
  없으면 아예 만들지 마세요. "검증할 것이 없습니다" 만 반복하는 칸이 되면, 정작
  정정이 실린 편까지 그냥 넘기게 됩니다.
- **개인의 경력·신원은 캐지 않습니다.** 기관·제도·제품처럼 공개된 것만 확인하고,
  사람에 대한 서술은 본인과 소개한 이의 말로 둡니다."""

# 태그(keywords) 규칙 — 본문 규칙과 같은 이유로 **원본은 여기 하나다.**
#
# 예전에는 두 프롬프트가 각자 한 줄씩 적어 두었고("keywords 는 2~6개. 찾을 때 쓸
# 말"), 둘 다 '무슨 말을 쓸지'는 말하지 않았다. 그 결과가 태그 1,224종 중 1,090종이
# 한 번만 쓰인 상태다 — 보고서마다 태그를 새로 지어낸 것이다.
#
# 사후 봉합(표기 통일·넓은 태그 승격)으로는 1회짜리의 약 10%만 구제된다는 것을
# 실측했다(2026-07-29). 나머지는 애초에 다른 말로 지어졌기 때문에 기계가 합칠 근거가
# 없다. 그래서 만들 때 고르게 한다.
TAG_COUNT_MIN = 2
TAG_COUNT_MAX = 6
NEW_TAGS_ALLOWED = 1     # 목록에 없는 말은 한 편에 이만큼만


def tag_debt_line(kinds: int | None = None, once: int | None = None) -> str:
    """'왜 목록에서 고르라 하는가' 를 한 줄로. 숫자는 **재서** 넣는다.

    예전에는 이 문장에 '1,224종 중 1,090종' 이 박혀 있었다. 그 사이 표기 통일과
    승격으로 1,091종 중 947종이 되었는데(실측 2026-08-21) 프롬프트는 옛 숫자를
    계속 말하고 있었다. 규칙 글에 든 숫자가 틀리면 규칙이 근거를 잃는다 —
    그래서 부르는 쪽이 재서 넘기고, 못 재면 숫자 없이 말한다.
    """
    if kinds and once:
        return (f"지금 태그 {kinds:,}종 중 {once:,}종이 딱 한 번만 쓰였고, "
                "그 대부분이 보고서마다 새로 지어낸 말입니다.")
    return ("같은 것을 다른 말로 부르면 태그가 흩어지고, 한 번만 쓰인 태그는 태그 "
            "목록에 나오지도 않습니다.")


def tag_rules(vocabulary: list[str] | None = None, kinds: int | None = None,
              once: int | None = None) -> str:
    """keywords 규칙. 이미 쓰이는 태그 목록을 함께 보여준다.

    목록이 비면(새 아카이브·첫 실행) 고르라는 말을 하지 않는다 — 없는 목록에서
    고르라고 하면 지시가 거짓이 되고, 모델은 그 문장을 무시하는 대신 헤맨다.

    새 말을 아주 막지는 않는다. 이 방은 매주 처음 나오는 도구·앱을 이야기하므로
    새 이름을 못 붙이면 태그가 뭉개진다. 다만 한 편에 하나로 묶어 두면, 진짜 새것일
    때만 쓰게 된다.

    `kinds`·`once` 는 지금의 태그 빚이다. 넘기면 규칙 글이 그 숫자로 말한다
    (`tag_debt_line`).
    """
    head = (f"- keywords 는 {TAG_COUNT_MIN}~{TAG_COUNT_MAX}개. 나중에 이 대화를 찾을 때 "
            "쓸 말(도구 이름, 개념, 결과물)입니다.\n"
            "- 카테고리 이름을 그대로 넣지 마세요.\n"
            "- 사람 이름·기관 이름·지명은 태그로 쓰지 마세요 — 누가·어디는 참여자 화면과\n"
            "  본문이 말합니다. 태그는 '무엇을 이야기했나' 의 자리입니다.")
    if not vocabulary:
        return head
    words = " · ".join(vocabulary)
    return (f"""- keywords 는 {TAG_COUNT_MIN}~{TAG_COUNT_MAX}개. **아래 '이미 쓰이는 태그' 에서 먼저 고르세요.**
  같은 이야기가 매번 다른 말로 붙으면 태그로 찾을 수 없습니다 —
  {tag_debt_line(kinds, once)}
- 목록에 없는 말은 **한 편에 {NEW_TAGS_ALLOWED}개까지만** 새로 만드세요. 이 대화에만 있는
  고유한 것(처음 나온 도구·앱 이름 같은 것)일 때만입니다. 목록의 말로 충분하면
  새로 만들지 마세요.
- 카테고리 이름을 그대로 넣지 마세요.
- 사람 이름, 그리고 특정 기관·지역 이름(○○복지관·○○구)은 **새로 만들지** 마세요 —
  누가·어디는 참여자 화면과 본문이 말합니다. 태그는 '무엇을 이야기했나' 의 자리입니다.
  위 목록에 이미 있는 말은 그대로 골라도 됩니다.

### 이미 쓰이는 태그 (많이 쓰인 순)
{words}""")


# 자리표를 받을 수 있는 메시지 종류. 동영상이 빠져 있던 동안, 본문이 짚어 둔
# 동영상 자리표는 `sanitize_anchors` 가 '이 대화에 없는 자료' 로 보아 지웠고
# `_is_media_message` 는 대신 놓아 주지도 않았다 — 화면에는 "이 주제에서 함께
# 공유된 자료" 라는 제목만 남고 아래가 비었다(2026-08-31 t-426 실측).
# 한 곳에 적는다. 두 곳에 적으면 갈라지고, 갈라진 것이 이 고장이었다.
MEDIA_KINDS = frozenset({"image", "video", "file"})


def sanitize_anchors(body: str, messages: list[dict]) -> tuple[str, list[str]]:
    """본문의 자리표를 검증한다. (고친 본문, 버린 자리표 목록)

    본문이 자료의 자리를 짚는 것은 좋은 일이지만(안 짚으면 자료가 전부 글 끝으로
    밀린다), 없는 message id 를 가리키면 화면이 빈 자리를 그린다. 그래서 이 대화에
    실제로 있는 자료만 남기고 나머지 줄은 지운다 — 보고서를 통째로 버리지 않는다.
    자리표는 내용이 아니라 자리만 가리키므로 틀린 줄만 지우면 손해가 없다.
    """
    if not body:
        return body, []
    media_ok, link_ok = set(), set()
    for m in messages or []:
        mid = str(m.get("id") or "")
        if not mid:
            continue
        if (m.get("kind") in MEDIA_KINDS or m.get("images") or m.get("videos")
                or m.get("file") or m.get("is_file_share")):
            media_ok.add(mid)
        if m.get("urls"):
            link_ok.add(mid)

    dropped: list[str] = []
    seen: set[str] = set()
    out_lines = []
    for line in body.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        hit = _ANY_ANCHOR.match(stripped)
        if not hit and "![[" in stripped:
            # 문장 속에 섞어 쓴 자리표는 화면이 못 읽는다(한 줄로 있어야 한다).
            dropped.append(stripped[:40])
            continue
        if hit:
            is_link = stripped.startswith("![[link:")
            mid = hit.group(1)
            ok = mid in (link_ok if is_link else media_ok)
            if not ok or stripped in seen:
                dropped.append(stripped)
                continue
            seen.add(stripped)
        out_lines.append(line)
    return "\n".join(out_lines), dropped


def structure_gaps(threads: list[dict]) -> list[tuple[str, int, str]]:
    """규칙을 어긴 보고서. (스레드 id, 대화 건수, 무엇이 없나)

    분량(thin_reports)과 따로 본다 — 길게만 쓴 한 덩어리 산문이 정확히 이 검사에
    걸리는 것이고, 그것이 읽기 불편하다고 지적된 꼴이다.
    """
    gaps = []
    for t in threads:
        body = t.get("report") or ""
        if not body:
            continue
        count = t.get("count") or len(t.get("message_ids") or [])
        # 자리표·소제목을 뺀 실제 글 길이로 본다.
        length = content_chars(re.sub(r"^!\[\[.*?\]\]\s*$", "", body, flags=re.M))
        missing = []
        if ((count >= QUOTE_REQUIRED_FROM or length >= QUOTE_REQUIRED_CHARS)
                and not re.search(r"^>", body, re.M)):
            missing.append("인용")
        # 절 대신 목록·표로 갈라 썼으면 그것도 구조다.
        if ((count >= SECTION_REQUIRED_FROM or length >= SECTION_REQUIRED_CHARS)
                and not re.search(r"^(##\s|[-*]\s|\|)", body, re.M)):
            missing.append("절 나눔")
        # 자료가 있는데 자리표가 하나도 없으면 사진·링크가 전부 글 끝으로 밀린다.
        if t.get("asset_count") and not _ANY_ANCHOR.search(body):
            missing.append("자료 자리")
        if missing:
            gaps.append((t["id"], count, "·".join(missing)))
    gaps.sort(key=lambda g: -g[1])
    return gaps


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


def load_ai_reports(path: Path | None = None) -> dict[str, dict]:
    """output/ai-reports/*.md 를 읽는다. 폴더가 없으면 빈 dict.

    **모든 주제에 있어야 하는 글이 아니다.** 인사·가입·안부처럼 검증할 사실이
    없는 대화에는 쓰지 않는다. 억지로 채우면 "검증할 것이 없습니다"만 반복하는
    칸이 되어, 정작 정정이 실린 편까지 그냥 넘기게 만든다.

    parse_report 를 쓰지 않는다. 그쪽은 title·summary 를 반드시 요구하는데,
    AI 보고서는 제목을 따로 갖지 않는다 — 사람 보고서에 딸린 주석이라 제목은
    그쪽 것을 쓴다. 여기서 필요한 것은 본문과 '언제 무엇으로 검증했나' 뿐이다.
    """
    d = path or AI_REPORTS_DIR
    if not d.exists():
        return {}
    out: dict[str, dict] = {}
    for p in sorted(d.glob("*.md")):
        text = p.read_text(encoding="utf-8")
        m = _FM.match(text)
        meta, body = {}, text
        if m:
            body = m.group(2)
            for line in m.group(1).splitlines():
                line = line.strip()
                if not line or line.startswith("#") or ":" not in line:
                    continue
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        body = body.strip()
        if not body:
            continue
        out[p.stem] = {
            "report": body,
            "checked": meta.get("checked", ""),
            "models": meta.get("models", ""),
            "method": meta.get("method", ""),
        }
    return out


def apply_ai_reports(threads: list[dict], reports: dict[str, dict]) -> int:
    """스레드에 AI 보고서를 얹는다. 얹은 개수를 돌려준다.

    사람 보고서와 달리 title·summary·keywords 는 건드리지 않는다. 화면에 보이는
    제목은 사람이 쓴 것 하나뿐이어야 한다.
    """
    applied = 0
    for t in threads:
        r = reports.get(t["id"])
        if not r:
            continue
        t["ai_report"] = r["report"]
        t["ai_checked"] = r["checked"]
        t["ai_models"] = r["models"]
        applied += 1
    return applied


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
        or message.get("videos")
        or message.get("file")
        or message.get("is_file_share")
        or message.get("kind") in MEDIA_KINDS
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

    markers = _place_leftovers_in_short_reports(report, messages, markers)
    return _insert_context_markers(report, markers)


# 이보다 문단이 많은 보고서에는 기계로 자리를 정하지 않는다. 문단이 여럿이면
# '어느 문단 뒤인가'가 판단이고, 틀린 자리에 사진이 놓이면 글이 거짓말을 한다.
_SHORT_REPORT_BLOCKS = 2


def _place_leftovers_in_short_reports(report: str, messages: list[dict],
                                      markers: dict[int, list[str]]) -> dict[int, list[str]]:
    """문단이 하나뿐인 보고서라면 남은 자료를 그 문단 뒤에 놓는다.

    인용을 기준으로 붙이는 방식은 인용이 짧으면(18자 미만) 건너뛴다. 그래서 두 건
    대화의 한 문단짜리 보고서에서 링크 하나가 글과 떨어져 아래 상자로 밀렸다 —
    "링크가 글과 함께 있어야 하는 것 아닌가" 라는 지적이 정확히 이 경우다.

    문단이 하나면 '그 뒤'가 유일한 답이라 판단할 것이 없다. 그래서 여기서만
    기계로 놓는다(실측 2026-07-28: 하단에만 남은 109개 중 48개가 이 경우).
    """
    if not report:
        return markers
    placed = {v.strip("![]").removeprefix("link:")
              for values in markers.values() for v in values}
    manual = set(_ANY_ANCHOR.findall(report))

    lines = report.replace("\r\n", "\n").split("\n")
    # 자리표를 놓을 수 있는 곳 = 소제목이 아닌 글 덩어리의 마지막 줄
    ends, run = [], None
    for i, line in enumerate(lines):
        if line.strip() and not line.lstrip().startswith("#"):
            run = i
        elif run is not None:
            ends.append(run)
            run = None
    if run is not None:
        ends.append(run)
    if not ends or len(ends) > _SHORT_REPORT_BLOCKS:
        return markers

    target = ends[-1]
    for message in messages:
        mid = str(message.get("id") or "")
        if not mid or mid in placed or mid in manual:
            continue
        if _is_media_message(message):
            markers.setdefault(target, []).append(f"![[{mid}]]")
        elif message.get("urls"):
            markers.setdefault(target, []).append(f"![[link:{mid}]]")
    return markers


def min_body_for(message_count: int) -> int:
    for upper, need in MIN_BODY_BY_COUNT:
        if message_count <= upper:
            return need
    return MIN_BODY_BY_COUNT[-1][1]


def content_chars(text: str | None) -> int:
    """요약할 수 있는 글자 수. 링크와 사진·동영상 자리표는 빼고 센다.

    왜 빼는가: 이 값이 '보고서가 얇은가'의 기준이 된다. 그런데 링크는 아무리 길어도
    요약할 내용이 아니고(구글 앱스 스크립트 배포 URL 하나가 100자를 넘는다),
    '사진'은 본문이 아예 없다는 표시다. 그것까지 세면 요약할 것이 없는 주제에
    분량을 요구하게 되고, 그건 없는 내용을 지어내라는 말이 된다.

    실측 2026-07-27: t-214 는 3건 108자로 잡혔는데 실제 내용은 "이 강의 녹화해놨어요.
    시간되실 때 보세요." 한 줄이고, 나머지는 URL 63자와 '사진' 2자였다.
    """
    value = _URL.sub(" ", text or "")
    value = re.sub(r"^(?:사진(?: \d+장)?|동영상|이모티콘)$", " ", value.strip(), flags=re.M)
    return len(re.sub(r"\s+", "", value))


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
