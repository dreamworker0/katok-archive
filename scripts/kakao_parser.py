"""카카오톡 '대화 내보내기' txt 를 메시지 목록으로 바꾼다.

내보내기 형식이 두 가지다
    PC      --------------- 2026년 3월 8일 일요일 ---------------
            [김종원] [오전 9:48] 본문
    모바일  2025년 8월 20일 오후 4:34, 김종원 : 본문

    둘은 날짜를 두는 자리가 다르다. PC 는 날짜 구분줄을 한 번 찍고 그 아래
    메시지에 시각만 붙이는데, 모바일은 줄마다 날짜와 시각을 다 붙인다. 그래서
    줄을 읽는 방법만 갈라 두고, 메시지를 만드는 뒷단은 같이 쓴다.

    형식은 첫 메시지 줄을 보고 자동으로 고른다 — 파일 이름은 믿을 게 못 된다.

사진을 가리키는 말도 형식마다 다르다
    사진 / 사진 3장        둘 다.        파일은 따로 모아야 한다
    <사진 읽지 않음>       모바일만.     그 기기가 사진을 안 받아서 파일이 영영 없다
    006bd1….png            모바일만.     내보내기 폴더 안 실제 파일을 가리킨다

    셋을 모두 kind="image" 로 두되 media_status 로 구분한다. 특히 '읽지 않음' 은
    수집 대기(pending)로 두면 안 된다 — 채워질 일이 없는데 대기 목록만 더럽힌다.
    그래서 lost 로 표시해 "여기 사진이 있었다"는 사실만 남긴다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re


KST = timezone(timedelta(hours=9))

# ── PC 형식 ──
DATE_RE = re.compile(r"^-+ (\d{4})년 (\d{1,2})월 (\d{1,2})일 .+ -+$")
MESSAGE_RE = re.compile(r"^\[(.+)\] \[(오전|오후) (\d{1,2}):(\d{2})\] ?(.*)$")

# ── 모바일 형식 ──
# 날짜만 있는 줄은 구분자다. 메시지 줄과 앞부분이 같아서 먼저 걸러야 한다.
M_STAMP = r"(\d{4})년 (\d{1,2})월 (\d{1,2})일 (오전|오후) (\d{1,2}):(\d{2})"
M_DATE_ONLY_RE = re.compile(r"^%s$" % M_STAMP)
M_MESSAGE_RE = re.compile(r"^%s, (.+?) : (.*)$" % M_STAMP)
M_SYSTEM_RE = re.compile(r"^%s, .+님(?:이|을) .+했습니다\.$" % M_STAMP)

# ── 점 구분 형식 (안드로이드 판) ──
#   2025. 8. 20. 16:34, 김종원 : 본문
# 오전/오후 없이 24시간제이고, 요일 줄이 따로 하루를 연다. 시스템 알림은 시각
# 뒤가 쉼표가 아니라 콜론이다 — 그 차이가 유일한 구분점이라 순서를 지켜야 한다.
D_STAMP = r"(\d{4})\. (\d{1,2})\. (\d{1,2})\. (\d{1,2}):(\d{2})"
D_DAY_RE = re.compile(r"^\d{4}년 \d{1,2}월 \d{1,2}일 .+요일$")
D_MESSAGE_RE = re.compile(r"^%s, (.+?) : (.*)$" % D_STAMP)
D_SYSTEM_RE = re.compile(r"^%s: .+님(?:이|을) .+했습니다\.$" % D_STAMP)

URL_RE = re.compile(r"https?://[^\s\)\]<>]+")
PHOTO_RE = re.compile(r"^사진(?: (\d+)장)?$")
# 카톡이 내보내기 폴더에 쓰는 이름. 내용 해시가 아니라 카톡 나름의 식별자다.
MEDIA_REF_RE = re.compile(r"^([0-9a-f]{64})\.(png|jpg|jpeg|gif|webp|mp4|mov)$", re.I)
LOST_PHOTO_RE = re.compile(r"^<사진 읽지 않음>$")
LOST_VIDEO_RE = re.compile(r"^<동영상 읽지 않음>$")
VIDEO_EXT = {"mp4", "mov"}
SYSTEM_RE = re.compile(
    r"^(?:"
    r".+님이 .+님(?:, .+님)*을 초대했습니다\."
    r"|메시지가 삭제되었습니다\."
    r")$"
)


@dataclass(frozen=True)
class Message:
    id: str
    timestamp: str
    date: str
    time: str
    nickname: str
    text: str
    urls: list[str]
    kind: str
    image_id: str | None
    image_count: int | None
    source_line: int
    # 아래 둘은 모바일 내보내기에서만 채워진다. PC 내보내기에는 그런 정보가 없다.
    media_refs: tuple[str, ...] = ()
    media_status: str | None = None   # None | "lost"


@dataclass(frozen=True)
class ParseResult:
    messages: list[Message]
    excluded: dict[str, int]
    warnings: list[dict[str, object]]


def _to_24_hour(period: str, hour: int) -> int:
    if period == "오전":
        return 0 if hour == 12 else hour
    return 12 if hour == 12 else hour + 12


def _classify(body: str) -> tuple[str, int | None, tuple[str, ...], str | None]:
    """본문을 보고 (kind, 사진 수, 파일 참조, media_status) 를 정한다.

    한 메시지에 사진이 여러 장이면 줄마다 하나씩 온다. 그래서 줄 단위로 세되,
    사진 줄과 글 줄이 섞이면 글로 본다 — 사진 설명을 붙인 경우를 잃지 않는다.
    """
    photo_match = PHOTO_RE.fullmatch(body)
    if photo_match:
        return "image", int(photo_match.group(1) or 1), (), None

    lines = [ln for ln in body.split("\n") if ln.strip()]
    if lines and all(LOST_PHOTO_RE.fullmatch(ln) for ln in lines):
        return "image", len(lines), (), "lost"

    refs = [MEDIA_REF_RE.fullmatch(ln) for ln in lines]
    if lines and all(refs):
        names = tuple(m.group(0) for m in refs if m)
        if all((m.group(2).lower() in VIDEO_EXT) for m in refs if m):
            return "video", None, names, None
        return "image", len(names), names, "referenced"

    if body.startswith("파일:"):
        return "file", None, (), None
    return "text", None, (), None


def _build(raw_messages: list[dict], excluded: dict, warnings: list) -> ParseResult:
    """줄 읽기가 끝난 뒤 공통으로 도는 부분 — 두 형식이 여기서 다시 만난다."""
    messages: list[Message] = []
    for raw in raw_messages:
        raw_lines = raw["lines"]
        if not isinstance(raw_lines, list):
            raise TypeError("Message lines must be a list")
        body = "\n".join(str(item) for item in raw_lines).rstrip()

        if body == "동영상" or LOST_VIDEO_RE.fullmatch(body):
            excluded["video"] += 1
            continue
        if body == "이모티콘":
            excluded["emoticon"] += 1
            continue

        kind, image_count, media_refs, media_status = _classify(body)
        if kind == "video":
            excluded["video"] += 1
            continue

        raw_date_parts = raw["date_parts"]
        if not isinstance(raw_date_parts, tuple):
            raise TypeError("Message date must be a tuple")
        year, month, day = raw_date_parts
        hour = _to_24_hour(str(raw["period"]), int(raw["hour"]))
        dt = datetime(year, month, day, hour, int(raw["minute"]), tzinfo=KST)
        number = len(messages) + 1
        messages.append(
            Message(
                id=f"msg-{number:06d}",
                timestamp=dt.isoformat(timespec="minutes"),
                date=dt.date().isoformat(),
                time=dt.strftime("%H:%M"),
                nickname=str(raw["nickname"]),
                text=body,
                urls=URL_RE.findall(body),
                kind=kind,
                image_id=(f"img-{number:06d}" if kind == "image" else None),
                image_count=image_count,
                source_line=int(raw["source_line"]),
                media_refs=media_refs,
                media_status=media_status,
            )
        )

    return ParseResult(messages=messages, excluded=excluded, warnings=warnings)


def _detect_format(lines: list[str]) -> str:
    """앞쪽 몇 줄만 보고 형식을 가린다. 파일 이름은 믿을 게 못 된다.

    먼저 나오는 표식이 이긴다 — 셋 다 날짜로 시작하는 줄을 쓰지만 모양이 겹치지
    않는다. 아무것도 못 찾으면 PC 로 둔다. 기존 동작을 그대로 두는 쪽이 안전하다.
    """
    for line in lines[:200]:
        if DATE_RE.match(line):
            return "pc"
        if D_MESSAGE_RE.match(line) or D_SYSTEM_RE.match(line):
            return "dotted"
        if M_MESSAGE_RE.match(line) or M_DATE_ONLY_RE.match(line):
            return "mobile"
    return "pc"


def _parse_pc(lines: list[str]) -> ParseResult:
    current_date: tuple[int, int, int] | None = None
    raw_messages: list[dict] = []
    excluded = {"video": 0, "emoticon": 0, "system": 0}
    warnings: list[dict[str, object]] = []
    active: dict | None = None

    def flush() -> None:
        nonlocal active
        if active is not None:
            raw_messages.append(active)
            active = None

    for line_number, line in enumerate(lines, start=1):
        date_match = DATE_RE.match(line)
        if date_match:
            flush()
            current_date = tuple(map(int, date_match.groups()))
            continue

        if SYSTEM_RE.match(line):
            flush()
            excluded["system"] += 1
            continue

        message_match = MESSAGE_RE.match(line)
        if message_match:
            flush()
            nickname, period, hour_text, minute_text, body = message_match.groups()
            if current_date is None:
                warnings.append(
                    {"line": line_number, "reason": "message_before_date", "text": line}
                )
                continue
            active = {
                "nickname": nickname,
                "period": period,
                "hour": int(hour_text),
                "minute": int(minute_text),
                "lines": [body],
                "source_line": line_number,
                "date_parts": current_date,
            }
            continue

        if active is not None:
            active["lines"].append(line)
        elif current_date is not None and line.strip():
            excluded["system"] += 1

    flush()
    return _build(raw_messages, excluded, warnings)


def _parse_mobile(lines: list[str]) -> ParseResult:
    raw_messages: list[dict] = []
    excluded = {"video": 0, "emoticon": 0, "system": 0}
    warnings: list[dict[str, object]] = []
    active: dict | None = None

    def flush() -> None:
        nonlocal active
        if active is not None:
            raw_messages.append(active)
            active = None

    for line_number, line in enumerate(lines, start=1):
        # 날짜 구분줄과 시스템 알림은 앞부분이 메시지 줄과 같다. 순서가 중요하다.
        if M_DATE_ONLY_RE.match(line):
            flush()
            continue
        if M_SYSTEM_RE.match(line):
            flush()
            excluded["system"] += 1
            continue

        message_match = M_MESSAGE_RE.match(line)
        if message_match:
            flush()
            year, month, day, period, hour_text, minute_text, nickname, body = (
                message_match.groups()
            )
            active = {
                "nickname": nickname,
                "period": period,
                "hour": int(hour_text),
                "minute": int(minute_text),
                "lines": [body],
                "source_line": line_number,
                "date_parts": (int(year), int(month), int(day)),
            }
            continue

        # '메시지가 삭제되었습니다.' 는 다음 줄에 홀로 온다. 앞 메시지 본문에
        # 붙이면 그 메시지가 원문과 달라져 증분 비교에서 매번 새 글로 잡힌다.
        if SYSTEM_RE.match(line):
            flush()
            excluded["system"] += 1
            continue

        if active is not None:
            active["lines"].append(line)

    flush()
    return _build(raw_messages, excluded, warnings)


def _parse_dotted(lines: list[str]) -> ParseResult:
    raw_messages: list[dict] = []
    excluded = {"video": 0, "emoticon": 0, "system": 0}
    warnings: list[dict[str, object]] = []
    active: dict | None = None

    def flush() -> None:
        nonlocal active
        if active is not None:
            raw_messages.append(active)
            active = None

    for line_number, line in enumerate(lines, start=1):
        # 시스템 알림이 메시지 줄과 앞부분이 같다(시각 뒤 콜론 vs 쉼표). 먼저 본다.
        if D_DAY_RE.match(line) or D_SYSTEM_RE.match(line):
            flush()
            if not D_DAY_RE.match(line):
                excluded["system"] += 1
            continue

        message_match = D_MESSAGE_RE.match(line)
        if message_match:
            flush()
            year, month, day, hour, minute, nickname, body = message_match.groups()
            active = {
                "nickname": nickname,
                # 이 형식은 24시간제라 오전/오후가 없다. _build 가 쓰는 모양에
                # 맞추려고 '오전' 으로 두고 시각을 그대로 넘긴다 — _to_24_hour 는
                # 오전 12 만 0 으로 바꾸므로 0~23 이 그대로 보존된다.
                "period": "오전" if int(hour) < 12 else "오후",
                "hour": int(hour) if int(hour) <= 12 else int(hour) - 12,
                "minute": int(minute),
                "lines": [body],
                "source_line": line_number,
                "date_parts": (int(year), int(month), int(day)),
            }
            continue

        # '메시지가 삭제되었습니다.' 는 다음 줄에 홀로 온다. 앞 메시지에 붙이면
        # 그 메시지가 원문과 달라져 증분 비교에서 매번 새 글로 잡힌다.
        if SYSTEM_RE.match(line):
            flush()
            excluded["system"] += 1
            continue

        if active is not None:
            active["lines"].append(line)

    flush()
    return _build(raw_messages, excluded, warnings)


def parse_chat(text: str) -> ParseResult:
    lines = text.lstrip("﻿").splitlines()
    kind = _detect_format(lines)
    if kind == "dotted":
        return _parse_dotted(lines)
    if kind == "mobile":
        return _parse_mobile(lines)
    return _parse_pc(lines)
