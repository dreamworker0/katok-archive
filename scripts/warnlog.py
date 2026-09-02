# -*- coding: utf-8 -*-
"""매일 같은 경고를 '어제와 달라진 것' 으로 바꾼다.

왜 필요한가
    발행본을 만들 때마다 같은 문장이 찍혔다 — "원문에 한 번도 안 나오는 노드 12개",
    "부모도 없고 한 번만 쓰인 태그 33개", "이름으로 주제를 못 찾는 노드 5개". 39일치
    일일 로그를 훑으면 이 줄들은 거의 한 글자도 안 바뀌었다. 그러면 사람은 그 줄을
    읽지 않게 되고, 어느 날 '12개' 가 '27개' 가 되어도 지나간다(실측: 2026-09-01
    로그가 정확히 그랬다 — 같은 밤 안에서도 12 와 27 이 섞여 있었는데 아무도 몰랐다).

    경고가 신호이려면 **달라진 것**을 말해야 한다. 그래서 지난 실행이 본 목록을
    output/warnings-seen.json 에 두고, 이번 목록과 견줘 새로 생긴 것과 사라진 것만
    적는다. 같으면 한 줄 — "33개 — 지난번과 같음".

쓰는 법
    note("orphan_tags", [태그 이름들], "[태그] 부모도 없고 한 번만 쓰인 태그",
         advice="검색 말고는 입구가 없습니다. config/tag_broader.json 에 넣을지 보세요")
    ...
    save()          # 발행 진입점(main)에서만. 검사가 build_data 를 불러도 상태는 안 바뀐다

    항목은 문자열이어야 한다(주제 id, 태그 이름, 노드 id). 견주는 단위가 그것이라서다.
    상태 파일이 없으면(첫 실행, 새 clone) 예전처럼 전부 적는다.

save() 를 main 에서만 부르는 이유
    tests/ 가 build_data 를 실제 데이터로 몇 번씩 부른다. 그때마다 상태가 갱신되면
    그날 밤 발행은 "같음" 만 보게 된다 — 검사가 경고를 먼저 보고 지워 버린 꼴이다.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "output" / "warnings-seen.json"

# 이번 실행이 본 목록. save() 가 이것을 상태 파일에 합친다.
_seen: dict[str, list[str]] = {}
_prev_cache: dict | None = None


def _prev() -> dict:
    global _prev_cache
    if _prev_cache is None:
        try:
            data = json.loads(STATE.read_text(encoding="utf-8"))
            _prev_cache = data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            _prev_cache = {}
    return _prev_cache


def reset() -> None:
    """검사가 상태 파일을 바꿔 가며 부를 때 쓴다."""
    global _prev_cache
    _prev_cache = None
    _seen.clear()


def note(key: str, items, headline: str, advice: str = "", sample: int = 8) -> str | None:
    """경고 한 줄을 만들어 찍고 돌려준다. 항목이 없고 지난번에도 없었으면 조용하다."""
    cur = list(dict.fromkeys(str(x) for x in items))
    _seen[key] = cur
    prev = _prev().get(key)
    prev = list(prev) if isinstance(prev, list) else None

    if not cur:
        if prev:
            line = "%s 0개 — 지난번 %d개가 다 사라졌습니다" % (headline, len(prev))
            print(line)
            return line
        return None

    tail = (" — " + advice) if advice else ""
    if prev is None:
        line = "%s %d개%s (앞 %d개: %s)" % (
            headline, len(cur), tail, min(sample, len(cur)), ", ".join(cur[:sample]))
    else:
        ps, cs = set(prev), set(cur)
        new = [x for x in cur if x not in ps]
        gone = [x for x in prev if x not in cs]
        if not new and not gone:
            line = "%s %d개 — 지난번과 같음" % (headline, len(cur))
        else:
            parts = ["%s %d개 (새로 %d · 사라짐 %d)%s" % (headline, len(cur), len(new), len(gone), tail)]
            if new:
                parts.append("새로: " + ", ".join(new[:sample]))
            if gone:
                parts.append("사라짐: " + ", ".join(gone[:sample]))
            line = " ".join(parts)
    print(line)
    return line


def save() -> None:
    """이번 실행이 본 목록을 상태에 합쳐 쓴다. 이번에 안 본 열쇠는 그대로 둔다."""
    state = dict(_prev())
    state.update(_seen)
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as e:
        # 상태를 못 써도 발행은 계속한다. 다음 실행이 전부 다시 적을 뿐이다.
        print("[경고 상태] 쓰지 못했습니다(%s) — 다음 실행이 전부 다시 적습니다." % e)
