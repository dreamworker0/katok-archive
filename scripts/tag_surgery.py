# -*- coding: utf-8 -*-
"""보고서의 태그를 고치는 네 스크립트가 함께 쓰는 골격.

무엇이 중복이었나
    `retag_reports`(태그 다시 고르기) · `split_tag`(한 태그를 갈래로 쪼개기) ·
    `retire_tag`(태그 거두기) · `adopt_orphans`(부모 없는 태그에 입구 주기) 넷은
    합쳐 1,246줄인데 같은 골격을 되풀이했다:

        대상 고르기 → 프롬프트 → LLM → 걸러내기 → 백업하고 적용

    특히 `apply_proposal` 은 26줄짜리 함수인데 `split_tag` 와 `retire_tag` 것을
    diff 하면 **코드 한 줄과 docstring 만 달랐다** — 백업 폴더 이름뿐이었다.

        < backup = OUT / ("backup-split-%s" % day)
        > backup = OUT / ("backup-retire-%s" % day)

    되풀이된 코드가 나쁜 이유는 줄 수가 아니다. 이 함수는 **원본 md 를 덮어쓰는**
    자리라, 백업을 빼먹거나 CRLF 를 망가뜨리는 실수가 되돌리기 어렵다. 그런
    코드가 네 벌 있으면 한 벌만 고치고 세 벌을 놓친다.

여기 있는 것과 없는 것
    있음   백업 폴더 만들기, keywords 줄 바꿔 쓰기, 로그용 경로 표기
    없음   무엇을 물을지, 무엇을 걸러낼지. 그건 네 스크립트가 서로 다르고,
           다른 것을 억지로 합치면 분기만 늘어난다.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from scripts.topic_reports import REPORTS_DIR

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"


def shown(path: Path) -> str:
    """로그에 적을 경로. 저장소 밖(또는 상대 경로로 받은 것)이면 있는 그대로 적는다."""
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def backup_dir(kind: str, day: str) -> Path:
    """`output/backup-<kind>-<날짜>/` 를 만들어 돌려준다.

    날짜를 이름에 넣는 이유: 같은 수술을 며칠에 걸쳐 나눠 하는 일이 잦고, 그때
    어제 백업을 덮으면 되돌릴 지점이 하루치 사라진다. 같은 날 두 번 돌리면
    덮어쓰는데, 그건 의도한 것이다 — 한 번의 수술을 되돌리는 데 필요한 것은
    '그 수술 직전' 상태 하나뿐이다.
    """
    d = OUT / ("backup-%s-%s" % (kind, day))
    d.mkdir(parents=True, exist_ok=True)
    return d


_FRONT = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.S)
_KW_LINE = re.compile(r"(?m)^keywords[ \t]*:[^\r\n]*")


def replace_keywords_line(text: str, tags: list[str]) -> str:
    """프론트매터의 keywords 줄만 바꾼다. 본문·줄바꿈은 한 글자도 안 건드린다.

    다시 렌더하지 않는 이유가 이 함수의 존재 이유다 — 이 폴더는 CRLF 이고,
    `render_report` 로 다시 쓰면 371편의 줄바꿈이 전부 바뀌어 git diff 에서
    무엇을 고쳤는지 보이지 않는다. 그래서 `$` 대신 `[^\r\n]*` 로 끊는다 —
    `$` 는 CRLF 의 `\r` 까지 먹어 그 줄만 LF 로 바뀐다.
    """
    m = _FRONT.match(text)
    if not m:
        raise ValueError("--- 로 감싼 프론트매터가 없습니다")
    head_start, head_end = m.start(1), m.end(1)
    head = text[head_start:head_end]
    line = "keywords: " + ", ".join(tags)
    new_head, n = _KW_LINE.subn(lambda _m: line, head, count=1)
    if n != 1:
        raise ValueError("프론트매터에 keywords 줄이 없습니다")
    return text[:head_start] + new_head + text[head_end:]


def save_before(backup: Path, changes: dict) -> None:
    """바꾸기 전 태그를 한 파일에 모아 둔다.

    md 사본만으로도 되돌릴 수 있지만, "무엇이 어떻게 바뀌었나"를 훑어보려면
    태그만 모인 파일이 훨씬 빠르다. 371편의 md 를 열어 볼 일이 아니다.
    """
    (backup / "keywords-before.json").write_text(
        json.dumps({t: v["before"] for t, v in changes.items()},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def apply_keyword_changes(changes: dict, backup: Path) -> tuple[int, list[str]]:
    """제안대로 각 보고서의 keywords 줄을 바꾼다.

    돌려주는 것은 (바꾼 편 수, 못 바꾼 이유 목록). **실패를 던지지 않는다** —
    한 편의 프론트매터가 깨져 있다고 나머지 예순 편을 못 고치면, 사람이 그
    한 편을 찾아 고칠 때까지 수술 전체가 멈춘다. 대신 이유를 모아 돌려주고
    부르는 쪽이 로그에 남긴다.

    바꾸기 전 원본은 반드시 백업 폴더로 먼저 복사한다. 순서가 뒤바뀌면
    (쓰고 나서 복사하면) 백업이 '바꾼 뒤' 가 되어 되돌릴 수 없다.
    """
    save_before(backup, changes)

    done, failed = 0, []
    for tid, change in sorted(changes.items()):
        path = REPORTS_DIR / ("%s.md" % tid)
        if not path.is_file():
            failed.append("%s: 파일이 없습니다" % tid)
            continue
        # newline="" 로 읽고 쓴다 — 이 폴더는 CRLF 이고, 파이썬 기본값으로
        # 오가면 줄바꿈이 전부 바뀌어 git diff 가 쓸모없어진다.
        text = path.read_text(encoding="utf-8", newline="")
        try:
            new_text = replace_keywords_line(text, change["after"])
        except ValueError as e:
            failed.append("%s: %s" % (tid, e))
            continue
        if new_text != text:
            shutil.copy2(path, backup / path.name)
            path.write_text(new_text, encoding="utf-8", newline="")
            done += 1
    return done, failed
