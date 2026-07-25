"""'미분류' 스레드가 얼마나 쌓였는지 센다 — 주 1회 재분류 시점 판단용.

일일 자동 갱신은 새 메시지를 t-unsorted-YYYY-MM-DD 스레드(카테고리 chat)에
넣기만 한다. 실제 주제 배정은 LLM 판단이 필요해 사람이 요청해야 하므로,
얼마나 밀렸는지 한눈에 보여준다.

사용: python -m scripts.count_unsorted
"""
from __future__ import annotations

import json
from pathlib import Path

TOPICS = Path(__file__).resolve().parent.parent / "output" / "topics.json"
PREFIX = "t-unsorted-"


def collect(topics: dict) -> list[dict]:
    """미분류 스레드만 날짜 순으로 추린다."""
    threads = [t for t in topics.get("threads", []) if t.get("id", "").startswith(PREFIX)]
    return sorted(threads, key=lambda t: t["id"])


def main() -> int:
    if not TOPICS.exists():
        print("topics.json 이 없습니다: %s" % TOPICS)
        return 1

    topics = json.loads(TOPICS.read_text(encoding="utf-8"))
    unsorted_threads = collect(topics)

    if not unsorted_threads:
        print("미분류 스레드 없음 - 정리할 것이 없습니다.")
        return 0

    total = sum(len(t.get("message_ids", [])) for t in unsorted_threads)
    print("미분류 %d개 스레드, 메시지 %d건" % (len(unsorted_threads), total))
    for t in unsorted_threads:
        print("  %-24s %4d건  %s" % (t["id"], len(t.get("message_ids", [])), t.get("title", "")))
    print()
    print("정리 절차: docs/AUTOMATION.md '갱신 후 할 일 - 주 1회 재분류'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
