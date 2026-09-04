# -*- coding: utf-8 -*-
"""JSON·JSONL 읽고 쓰기 — 파이프라인 공용.

`build_site._read_json` 을 여덟 모듈이 갖다 썼다. 밑줄로 시작하는 이름은 '이
모듈 안에서만 쓴다'는 뜻인데 실제로는 공용이었고, 그래서 build_site 를 고칠 때마다
관계없는 모듈이 함께 흔들렸다(발행·감사·백필·증분이 모두 딸려 있다).

여기로 모으고, build_site 에는 이름만 남긴다 — 예전 이름으로 부르는 곳이 많고
테스트도 그 이름을 쓴다.

인코딩을 한 곳에 고정하는 것도 이 모듈의 몫이다. 한글이 들어간 파일을 PS 5.1 의
기본 코드페이지로 읽으면 깨진다 — 늘 UTF-8 로 읽고, 쓸 때는 `ensure_ascii=False`.
"""
from __future__ import annotations

import json
from pathlib import Path


def read_json(path: str | Path):
    with Path(path).open(encoding="utf-8") as fh:
        return json.load(fh)


def read_jsonl(path: str | Path) -> list[dict]:
    rows = []
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _text(data, indent: int | None) -> str:
    """쓰는 모양은 한 곳에서만 만든다 — `write_json_if_changed` 가 이것과
    글자까지 같은지로 '안 바뀌었다' 를 판정하기 때문이다."""
    return json.dumps(data, ensure_ascii=False, indent=indent) + "\n"


def write_json(path: str | Path, data, indent: int | None = 2) -> None:
    """사람이 읽고 git diff 로 볼 파일이라 들여쓰기를 준다."""
    Path(path).write_text(_text(data, indent), encoding="utf-8")


def write_json_if_changed(path: str | Path, data, indent: int | None = 2) -> bool:
    """내용이 같으면 쓰지 않는다. 실제로 썼을 때만 True.

    파일 **시각**이 신호이기 때문이다. `publish_state` 는 원장 파일이 마지막
    적재보다 새로운지를 보고 '발행본이 뒤처졌다' 를 판정한다. 내용이 같은데 다시
    쓰면 아무 일도 없던 날에 발행이 한 번 돈다 — 실측 2026-09-05: 검사만 돌려도
    (test_firestore_payload 가 build_payload 를 부른다) knowledge.json 의 시각이
    움직여 PUBLISH_STALE=1 이 됐다.

    한 번 쓴 것과 글자까지 같아야 안 쓴다 — `write_json` 과 같은 모양으로 만들어
    견준다(들여쓰기 2, 끝에 줄바꿈 하나).
    """
    p = Path(path)
    text = _text(data, indent)
    if p.exists():
        try:
            if p.read_text(encoding="utf-8") == text:
                return False
        except (OSError, UnicodeDecodeError):
            pass          # 못 읽으면 쓴다 — 읽기 실패가 안 쓸 이유는 못 된다
    p.write_text(text, encoding="utf-8")
    return True


def write_jsonl(path: str | Path, rows: list[dict]) -> None:
    with Path(path).open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
