from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re


KST = timezone(timedelta(hours=9))
DATE_RE = re.compile(r"^-+ (\d{4})년 (\d{1,2})월 (\d{1,2})일 .+ -+$")
MESSAGE_RE = re.compile(r"^\[(.+)\] \[(오전|오후) (\d{1,2}):(\d{2})\] ?(.*)$")
URL_RE = re.compile(r"https?://[^\s\)\]<>]+")
PHOTO_RE = re.compile(r"^사진(?: (\d+)장)?$")
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


@dataclass(frozen=True)
class ParseResult:
    messages: list[Message]
    excluded: dict[str, int]
    warnings: list[dict[str, object]]


def _to_24_hour(period: str, hour: int) -> int:
    if period == "오전":
        return 0 if hour == 12 else hour
    return 12 if hour == 12 else hour + 12


def _kind_for(text: str) -> str:
    if PHOTO_RE.fullmatch(text):
        return "image"
    if text.startswith("파일:"):
        return "file"
    return "text"


def parse_chat(text: str) -> ParseResult:
    lines = text.lstrip("\ufeff").splitlines()
    current_date: tuple[int, int, int] | None = None
    raw_messages: list[dict[str, object]] = []
    excluded = {"video": 0, "emoticon": 0, "system": 0}
    warnings: list[dict[str, object]] = []
    active: dict[str, object] | None = None

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
                    {
                        "line": line_number,
                        "reason": "message_before_date",
                        "text": line,
                    }
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
            message_lines = active["lines"]
            if isinstance(message_lines, list):
                message_lines.append(line)
        elif current_date is not None and line.strip():
            excluded["system"] += 1

    flush()

    messages: list[Message] = []
    for raw in raw_messages:
        raw_lines = raw["lines"]
        if not isinstance(raw_lines, list):
            raise TypeError("Message lines must be a list")
        body = "\n".join(str(item) for item in raw_lines).rstrip()
        if body == "동영상":
            excluded["video"] += 1
            continue
        if body == "이모티콘":
            excluded["emoticon"] += 1
            continue

        kind = _kind_for(body)
        if kind == "image":
            photo_match = PHOTO_RE.fullmatch(body)
            if photo_match is None:
                raise ValueError(f"Invalid photo message: {body}")
            expected_image_count = int(photo_match.group(1) or 1)
        else:
            expected_image_count = None

        raw_date_parts = raw["date_parts"]
        if not isinstance(raw_date_parts, tuple):
            raise TypeError("Message date must be a tuple")
        year, month, day = raw_date_parts
        period = str(raw["period"])
        hour = _to_24_hour(period, int(raw["hour"]))
        minute = int(raw["minute"])
        dt = datetime(year, month, day, hour, minute, tzinfo=KST)
        message_number = len(messages) + 1
        messages.append(
            Message(
                id=f"msg-{message_number:06d}",
                timestamp=dt.isoformat(timespec="minutes"),
                date=dt.date().isoformat(),
                time=dt.strftime("%H:%M"),
                nickname=str(raw["nickname"]),
                text=body,
                urls=URL_RE.findall(body),
                kind=kind,
                image_id=(
                    f"img-{message_number:06d}"
                    if kind == "image"
                    else None
                ),
                image_count=expected_image_count,
                source_line=int(raw["source_line"]),
            )
        )

    return ParseResult(messages=messages, excluded=excluded, warnings=warnings)
