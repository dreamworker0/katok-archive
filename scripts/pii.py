# -*- coding: utf-8 -*-
"""개인정보(전화·이메일·주민번호·카드)를 찾아 발행 단계에서만 가린다.

왜 발행 단계인가
  원장(`output/messages.jsonl`)과 보고서 원본(`output/reports/*.md`)은 고치지
  않는다. 태그 통일(`scripts/tags.py`)과 같은 철학이다 — 원본은 사실의 기록이고,
  무엇을 감출지는 발행 정책이므로 정책이 바뀌면 다시 발행하면 된다. 원본을 고치면
  되돌릴 수 없고, "원래 뭐였는지" 를 확인할 방법도 사라진다.

왜 정규식만으로는 안 되는가 (2026-07-30 실측)
  메시지 2,648건에 소박한 정규식을 돌리니 25건이 걸렸는데 진짜 개인정보는 4건,
  오탐이 21건이었다. 오탐의 정체:

    - **URL 안의 숫자** — 뉴스 기사 ID(`v.daum.net/v/20260203000002`), 페이스북
      포스트 ID, 교보문고 상품코드(`S000219133433`). 지역번호 패턴에 그대로 걸린다.
    - **예시 번호** — `010-1234-5678`, `02-1234-5678`. 슬랙이 전화번호를 링크로
      만들어 주지 않는다는 그 테스트 대화다. 개인정보가 아니다.

  그래서 이 모듈은 세 겹으로 걸러낸다.
    1. URL·코드 구간을 먼저 지운 자리에서 찾는다 (오탐 대부분이 여기서 사라진다)
    2. 예시 번호 사전에 있는 것은 넘긴다
    3. 하이픈 없는 맨 숫자열은 **근접 키워드**('연락처'·'전화'·'번호' 등)가 있을
       때만 개인정보로 본다 — 지역번호 모양 숫자는 세상에 너무 많다

등급
  certain  가릴 것. 발행본에 남아 있으면 테스트가 배포를 막는다.
  likely   경고만. 사람이 보고 `config/pii_allow.json` 이나 예외에 넣는다.

기관 대표번호·업무용 이메일처럼 감추면 오히려 불편한 것은 `config/pii_allow.json`
에 적어 둔다. 전화는 숫자만 비교하므로 표기가 달라도 걸러진다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from scripts import jsonio

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"

# ────────────────────────── 검사에서 뺄 구간 ──────────────────────────

# URL 은 통째로 지운다. 기사 ID·상품코드가 전화번호 모양이라 오탐의 최대 원인이다.
_URL = re.compile(r"(?:https?://|www\.)[^\s<>()\[\]\"']+", re.I)
# 코드 블록. 설정값·해시가 주민번호 모양일 수 있다.
#
# **인라인 코드(`…`)는 빼지 않는다.** 처음엔 빼도록 만들었는데, 그러면 보고서에
# 실제로 새고 있던 이메일 하나를 놓쳤다 — t-346 에 "`nobody9f3a@hanmail.net` 을
# 들었다" 처럼 백틱으로 감싸여 있었다. 보고서 규칙이 인용한 값을 백틱으로 두라고
# 하므로, 인라인 코드는 개인정보가 가장 잘 숨는 자리다.
_FENCE = re.compile(r"```.*?```", re.S)
# 이미지·링크의 주소 부분만 (표시 문자열은 검사한다 — 거기 이름이 들어간다)
_MD_TARGET = re.compile(r"\]\(([^)\s]+)")

_BLANK = "\x00"


def _mask_out_spans(text: str) -> str:
    """검사 대상에서 뺄 구간을 같은 길이의 \\x00 으로 덮는다.

    지우지 않고 덮는 이유는 위치(offset)를 보존해야 원문에 그대로 돌려 쓸 수
    있기 때문이다. 길이가 달라지면 찾은 자리와 바꿀 자리가 어긋난다.
    """
    out = list(text)

    def blank(start: int, end: int) -> None:
        for i in range(start, end):
            out[i] = _BLANK

    for pat in (_FENCE, _URL):
        for m in pat.finditer(text):
            blank(m.start(), m.end())
    for m in _MD_TARGET.finditer(text):
        blank(m.start(1), m.end(1))
    return "".join(out)


# ────────────────────────── 패턴 ──────────────────────────

# 마지막 마디(TLD)는 알파벳만 받는다. OCR 로 읽은 화면에는 `UbUntU@.24.@4.10`
# 처럼 이메일 모양의 쓰레기가 흔한데, 숫자 TLD 를 허용하면 그것이 다 걸린다.
_P_EMAIL = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,24}\b"
)

# 전화·카드의 구분자에서 **줄바꿈을 뺀다.**
#
# `\s` 로 두었더니 표를 OCR 한 글자에서 사고가 났다. 식권 가격이 세로로
# "5000 / 5000 / 5000 / 5000" 늘어선 화면이 줄바꿈으로 이어져 카드번호
# 5000-0000-0000-5000 으로 읽혔다(실측 2026-07-30, img-002213-03). 전화번호도
# 같은 함정에 걸린다 — 세로로 늘어선 숫자 넷은 전화번호가 아니다.
_SEP = r"[-.  ]"

# 주민등록번호·외국인등록번호. 뒷자리 첫 숫자는 1~8 만 쓴다.
_P_RRN = re.compile(
    r"(?<!\d)(\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01]))" + _SEP +
    r"?([1-8]\d{6})(?!\d)")
# 카드번호. 구분자가 있는 것만 — 16자리 맨 숫자열은 주문번호가 훨씬 많다.
_P_CARD = re.compile(r"(?<!\d)\d{4}" + _SEP + r"\d{4}" + _SEP + r"\d{4}" +
                     _SEP + r"\d{4}(?!\d)")
# 휴대전화. 구분자가 있는 것.
_P_MOBILE = re.compile(r"(?<!\d)(01[016789])" + _SEP + r"(\d{3,4})" + _SEP +
                       r"(\d{4})(?!\d)")
# 휴대전화. 맨 숫자열 — 근접 키워드가 있을 때만 본다.
_P_MOBILE_BARE = re.compile(r"(?<!\d)(01[016789])(\d{3,4})(\d{4})(?!\d)")
# 지역번호 전화. 오탐이 많아 구분자가 있어도 근접 키워드를 요구한다.
_P_LOCAL = re.compile(
    r"(?<!\d)(0(?:2|3[1-3]|4[1-4]|5[1-5]|6[1-4]|70))" + _SEP + r"?(\d{3,4})" +
    _SEP + r"?(\d{4})(?!\d)"
)

# 서식 안내용 가짜 주소. 사람 것이 아니므로 가리면 오히려 화면이 이상해진다.
# (실측: 권한 요청 서식의 `name@example.com` 이 사진 한 장을 통째로 감췄다)
_PLACEHOLDER_DOMAINS = ("example.com", "example.org", "example.net",
                        "example.co.kr", "test.com", "domain.com",
                        "email.com", "yourcompany.com", "gmail.co")

# 근접 키워드 — 앞뒤 20자 안에 있으면 "사람의 연락처" 로 본다.
_NEAR = re.compile(
    r"연락처|연락|전화|번호|폰|핸드폰|휴대폰|모바일|문의|통화|콜|call|tel|phone", re.I
)
_NEAR_WINDOW = 20

# 예시·더미 번호. 숫자만 남긴 값으로 비교한다.
_DUMMY_TAILS = ("12345678", "00000000", "11111111", "12341234", "98765432", "00001111")
_DUMMY_FULL = {"024998721"}   # 슬랙 전화번호 테스트 대화에 나온 예시 (2026-07-30)


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def _is_dummy_phone(raw: str) -> bool:
    d = _digits(raw)
    if d in _DUMMY_FULL:
        return True
    if any(d.endswith(t) for t in _DUMMY_TAILS):
        return True
    # 같은 숫자 반복(0000-0000)이나 연속 증가(1234-5678)로 끝나는 것
    return len(set(d)) <= 2


# ────────────────────────── 허용 목록 ──────────────────────────

def load_allow(path: Path | None = None) -> dict[str, set[str]]:
    """`config/pii_allow.json` — 감추지 않을 값.

    기관 대표번호처럼 방에서 공개적으로 공유된 연락처가 여기 들어간다.
    형식: {"phones": ["02-000-0000"], "emails": ["a@b.or.kr"], "note": "..."}
    """
    p = path or (CONFIG / "pii_allow.json")
    if not p.exists():
        return {"phones": set(), "emails": set()}
    raw = jsonio.read_json(p)
    return {
        "phones": {_digits(x) for x in (raw.get("phones") or []) if _digits(x)},
        "emails": {str(x).strip().lower() for x in (raw.get("emails") or []) if x},
    }


# ────────────────────────── 탐지 ──────────────────────────

@dataclass(frozen=True)
class Hit:
    start: int
    end: int
    kind: str      # email | rrn | card | mobile | local
    grade: str     # certain | likely
    value: str
    masked: str


def _mask_email(v: str) -> str:
    local, _, domain = v.partition("@")
    return "%s****@%s" % (local[:1], domain)


def _mask_phone(v: str) -> str:
    """앞머리와 끝 네 자리만 남긴다 — 같은 사람인지 알아볼 수는 있게."""
    sep = "-" if re.search(r"[-.\s]", v) else ""
    d = _digits(v)
    head_len = 3 if d.startswith("01") else (2 if d.startswith("02") else 3)
    return sep.join([d[:head_len], "*" * (len(d) - head_len - 4), d[-4:]]) if sep \
        else d[:head_len] + "*" * (len(d) - head_len - 4) + d[-4:]


def find(text: str, allow: dict[str, set[str]] | None = None) -> list[Hit]:
    """개인정보로 보이는 자리를 찾는다. 위치는 원본 `text` 기준이다."""
    if not text:
        return []
    allow = allow if allow is not None else load_allow()
    hay = _mask_out_spans(text)
    hits: list[Hit] = []

    def near(start: int, end: int) -> bool:
        window = hay[max(0, start - _NEAR_WINDOW):end + _NEAR_WINDOW]
        return bool(_NEAR.search(window))

    def add(m: re.Match, kind: str, grade: str, masked: str) -> None:
        hits.append(Hit(m.start(), m.end(), kind, grade, m.group(0), masked))

    for m in _P_EMAIL.finditer(hay):
        v = m.group(0).lower()
        if v in allow["emails"] or v.endswith(_PLACEHOLDER_DOMAINS):
            continue
        add(m, "email", "certain", _mask_email(m.group(0)))

    for m in _P_RRN.finditer(hay):
        add(m, "rrn", "certain", "%s-*******" % m.group(1))

    for m in _P_CARD.finditer(hay):
        d = _digits(m.group(0))
        add(m, "card", "certain", "%s-****-****-%s" % (d[:4], d[-4:]))

    taken: list[tuple[int, int]] = [(h.start, h.end) for h in hits]

    def overlaps(m: re.Match) -> bool:
        return any(m.start() < e and s < m.end() for s, e in taken)

    for pat, kind in ((_P_MOBILE, "mobile"), (_P_MOBILE_BARE, "mobile"),
                      (_P_LOCAL, "local")):
        for m in pat.finditer(hay):
            if overlaps(m) or _digits(m.group(0)) in allow["phones"]:
                continue
            if _is_dummy_phone(m.group(0)):
                continue
            # 구분자 있는 휴대전화만 그 자체로 확실하다고 본다. 맨 숫자열과
            # 지역번호는 근접 키워드가 있을 때만 — 없으면 경고로 남긴다.
            certain = (pat is _P_MOBILE) or near(m.start(), m.end())
            add(m, kind, "certain" if certain else "likely", _mask_phone(m.group(0)))
            taken.append((m.start(), m.end()))

    return sorted(hits, key=lambda h: h.start)


def mask(text: str, allow: dict[str, set[str]] | None = None) -> tuple[str, list[Hit]]:
    """certain 등급만 가린 문자열과, 찾은 것 전부를 돌려준다."""
    hits = find(text, allow)
    out = text
    for h in reversed([h for h in hits if h.grade == "certain"]):
        out = out[:h.start] + h.masked + out[h.end:]
    return out, hits


def mask_tree(obj, allow: dict[str, set[str]] | None = None) -> tuple[object, list[Hit]]:
    """JSON 구조를 훑어 모든 문자열을 가린다.

    발행본은 스레드 요약·보고서·요지가 겹겹이 중첩된 구조라, 어느 필드에 원문
    인용이 들어갈지 미리 정해 두면 언젠가 새 필드가 그 사이로 빠져나간다.
    전부 훑는 편이 안전하다 — 값이 짧은 문자열(id·날짜)에서는 아무것도 안 걸린다.
    """
    allow = allow if allow is not None else load_allow()
    found: list[Hit] = []

    def walk(o):
        if isinstance(o, str):
            new, hits = mask(o, allow)
            found.extend(hits)
            return new
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        if isinstance(o, list):
            return [walk(v) for v in o]
        return o

    return walk(obj), found


def summarize(hits: list[Hit]) -> str:
    """발행 로그에 한 줄로 남길 요약."""
    from collections import Counter
    c = Counter("%s:%s" % (h.kind, h.grade) for h in hits)
    return ", ".join("%s %d건" % (k, n) for k, n in sorted(c.items()))
