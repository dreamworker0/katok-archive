"""전체 보고서의 링크·미디어 문맥 자리표를 안전하게 검사한다.

원문 메시지 텍스트는 출력하지 않는다. 보고서 ID와 메시지 ID, 집계만 보여
주므로 운영 로그에 대화 내용이 새지 않는다.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import re


LINK_ANCHOR = re.compile(r"^!\[\[link:([A-Za-z0-9_-]+)\]\]\s*$", re.M)
MEDIA_ANCHOR = re.compile(r"^!\[\[([A-Za-z0-9_-]+)\]\]\s*$", re.M)


def audit_context(
    threads: list[dict],
    media: list[dict],
    expected_media_ids: set[str] | None = None,
) -> dict:
    expected_media_ids = expected_media_ids or set()
    media_by_thread: dict[str, list[dict]] = {}
    for item in media:
        media_by_thread.setdefault(item.get("thread_id") or "", []).append(item)

    result = {
        "reports": 0,
        "links_inline": 0,
        "links_fallback": 0,
        "media_inline": 0,
        "media_fallback": 0,
        "pending_anchors": [],
        "invalid_anchors": [],
        "duplicate_anchors": [],
        "t162_youtube_inline": False,
    }

    for thread in threads:
        report = thread.get("report") or ""
        if not report:
            continue
        result["reports"] += 1
        tid = thread.get("id") or ""

        link_ids = LINK_ANCHOR.findall(report)
        media_ids = MEDIA_ANCHOR.findall(report)
        link_counts = Counter(link_ids)
        media_counts = Counter(media_ids)
        link_anchor_set = set(link_ids)
        media_anchor_set = set(media_ids)

        for mid, count in sorted(link_counts.items()):
            if count > 1:
                result["duplicate_anchors"].append(f"{tid}:link:{mid}")
        for mid, count in sorted(media_counts.items()):
            if count > 1:
                result["duplicate_anchors"].append(f"{tid}:media:{mid}")

        links = thread.get("links") or []
        valid_link_ids = {str(link.get("id") or "") for link in links}
        for mid in sorted(link_anchor_set - valid_link_ids):
            result["invalid_anchors"].append(f"{tid}:link:{mid}")
        for link in links:
            if link.get("id") in link_anchor_set:
                result["links_inline"] += 1
                if (
                    tid == "t-162"
                    and link.get("id") == "msg-001480"
                    and "youtu.be/HDfr8PvfoOw" in (link.get("url") or "")
                ):
                    result["t162_youtube_inline"] = True
            else:
                result["links_fallback"] += 1

        thread_media = media_by_thread.get(tid, [])
        valid_media_ids = {str(item.get("id") or "") for item in thread_media}
        for mid in sorted(media_anchor_set - valid_media_ids):
            if mid in expected_media_ids:
                result["pending_anchors"].append(f"{tid}:{mid}")
            else:
                result["invalid_anchors"].append(f"{tid}:{mid}")
        for item in thread_media:
            if item.get("id") in media_anchor_set:
                result["media_inline"] += 1
            else:
                result["media_fallback"] += 1

    return result


def audit_exit_code(result: dict) -> int:
    return 1 if result["invalid_anchors"] or result["duplicate_anchors"] else 0


def _load_archive() -> tuple[list[dict], list[dict], set[str]]:
    from scripts import build_site

    root = Path(__file__).resolve().parent.parent
    output = root / "output"
    messages = build_site._read_jsonl(output / "messages.jsonl")
    images = build_site._read_jsonl(output / "images.jsonl")
    participants = build_site._read_json(output / "participants.json")
    topics = build_site._read_json(output / "topics.json")
    knowledge = build_site._read_json(output / "knowledge.json")
    digests = build_site._read_json(output / "topic-digests.json")
    files_path = output / "files.jsonl"
    files = build_site._read_jsonl(files_path) if files_path.exists() else []

    data = build_site.build_data(
        messages, images, participants, topics, knowledge, digests, files
    )
    threads = build_site.enrich_threads(data["threads"], data["messages"])
    media = build_site.build_media(data["messages"])
    expected_media_ids = {
        message["id"]
        for message in data["messages"]
        if (
            message.get("kind") in {"image", "file"}
            or message.get("file")
            or message.get("is_file_share")
        )
    }
    return threads, media, expected_media_ids


def main() -> int:
    threads, media, expected_media_ids = _load_archive()
    result = audit_context(threads, media, expected_media_ids)
    print(f"보고서 {result['reports']}개")
    print(
        "링크 문맥 %d개 · 하단 유지 %d개"
        % (result["links_inline"], result["links_fallback"])
    )
    print(
        "사진·첨부 문맥 %d개 · 하단 유지 %d개"
        % (result["media_inline"], result["media_fallback"])
    )
    print(
        "유효하지 않은 자리표 %d개 · 중복 자리표 %d개"
        % (len(result["invalid_anchors"]), len(result["duplicate_anchors"]))
    )
    print("아직 수집되지 않은 사진 자리표 %d개" % len(result["pending_anchors"]))
    print(
        "t-162 msg-001480 YouTube 문맥 연결: %s"
        % ("확인" if result["t162_youtube_inline"] else "미확인")
    )
    for issue in result["invalid_anchors"]:
        print("INVALID", issue)
    for issue in result["duplicate_anchors"]:
        print("DUPLICATE", issue)
    return audit_exit_code(result)


if __name__ == "__main__":
    raise SystemExit(main())
