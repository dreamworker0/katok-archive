# -*- coding: utf-8 -*-
"""사람별 관심 주제. '이 사람은 무엇에 관심이 있나'를 대화에서 뽑는다.

두 가지를 낸다.

  관심 분야  — 그 사람이 참여한 주제의 분류 분포를 **방 평균과 비교**한다.
              방 전체가 프로젝트 이야기를 많이 하므로, 그냥 많은 순으로 세면
              모두의 1위가 '프로젝트'가 되어 아무 말도 못 한다.
  관심 화제  — 태그를 TF-IDF 로 고른다. '안티그래비티'는 22개 주제에 붙어 있어
              누구에게나 나오므로 그 사람의 특징이 아니다. 여러 사람이 쓴 태그의
              값을 깎고, 그 사람에게 몰린 태그를 올린다.

**숨기기**: 이 화면은 사람을 평가하는 것처럼 읽힐 수 있다. 그래서 본인이 원하면
빠질 수 있어야 하고, 그 판정은 화면이 아니라 **여기 발행 단계**에서 해야 한다 —
화면에서만 감추면 데이터는 그대로 내려가 누구나 볼 수 있다.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict

# 참여 주제가 이보다 적은 사람은 내지 않는다. 두세 마디로 관심사를 말할 수 없다.
MIN_THREADS = 3
MAX_TOPICS = 6
MAX_FIELDS = 3


def _lift_fields(rows: list[dict], room_count: Counter, room_total: int,
                 bucket_of, label_of, level: str,
                 skip: set[str] | None = None) -> list[dict]:
    """참여 분포를 방 평균과 견줘 '유난히 많이 이야기한 칸'만 남긴다.

    `bucket_of` 가 칸을 정한다 — 분류 그대로일 수도 있고 상위 묶음일 수도 있다.
    두 층이 같은 계산을 봐야 하므로 함수 하나만 둔다.

    None 을 돌려주는 칸(묶음 없는 분류)은 분모에서도 빠진다. 개인과 방이 같은
    잣대로 세어야 비율을 견줄 수 있다.

    `skip` 은 **결과에서만** 뺀다. 분모는 그대로 두므로 다른 칸의 lift 가 흔들리지
    않는다 — 잡담을 안 내는 것이 남의 관심 분야를 바꿀 이유는 없다.
    """
    mine: Counter[str] = Counter()
    for r in rows:
        b = bucket_of(r["category"])
        if b:
            mine[b] += 1
    mine_total = sum(mine.values()) or 1

    out = []
    for key, n in mine.items():
        if n < 2 or key in (skip or set()):
            continue
        base = room_count.get(key, 0) / (room_total or 1)
        if not base:
            continue
        lift = (n / mine_total) / base
        if lift < 1.2:
            continue
        out.append({"category": key, "label": label_of(key), "count": n,
                    "lift": round(lift, 2), "level": level})
    out.sort(key=lambda f: (-f["lift"], -f["count"]))
    return out


def build_interests(threads: list[dict], categories: list[dict],
                    hidden: set[str] | None = None,
                    person_tags: set[str] | None = None,
                    group_of=None, group_label=None,
                    skip_categories: set[str] | None = None) -> dict:
    """{"people": [...], "hidden_count": n} 를 돌려준다.

    `person_tags` 로 준 사람 이름 태그는 관심 화제에서 뺀다 — 자기 이름이
    '내 관심사'로 올라오면(실측: 김종원·오세라) 화면이 우스워진다.

    `group_of`·`group_label` 을 주면 분류 12개로 아무것도 안 나온 사람에게
    **상위 묶음**으로 한 번 더 계산한다. 분류가 평평해서 주제 3~5개짜리 참여자는
    12분면에서 표본이 너무 얇다 — 실측 2026-08-14 에 32명 중 5명이 관심 분야가
    0개였다. 'AI 코딩 도구' 1건 + 'AI 모델' 1건은 분류로는 각각 1건이라 묻히지만
    묶으면 'AI 도구·모델' 2건이 된다.

    묶음은 **채우는 것이 아니라 대신하는 것**이다. 둘을 섞으면 '프로젝트·결과물'
    옆에 '만들기·기술' 이 나란히 서서 같은 말을 두 번 한다.

    `skip_categories` 에 적은 분류는 관심 분야로 내지 않는다 — 실측 2026-08-14 에
    세 사람이 '일상·잡담' 을 관심 분야로 달고 있었다. 자세한 이유는
    `ontology.PROVISIONAL_CATEGORIES` 설명 참고.
    """
    hidden = {h.strip() for h in (hidden or set()) if h and h.strip()}
    person_tags = person_tags or set()
    label_of = {c["id"]: c["label"] for c in categories}

    threads_of: dict[str, list[dict]] = defaultdict(list)
    for t in threads:
        for nick in t.get("participants") or []:
            threads_of[nick].append(t)

    room_cat = Counter()
    for t in threads:
        room_cat[t["category"]] += 1
    room_total = sum(room_cat.values()) or 1

    # 묶음 쪽 잣대. 묶음 없는 분류(chat)는 여기서 빠지므로 분모도 그만큼 작다.
    room_group: Counter[str] = Counter()
    if group_of:
        for t in threads:
            g = group_of(t["category"])
            if g:
                room_group[g] += 1
    group_total = sum(room_group.values()) or 1

    # 방 전체에서 그 태그가 붙은 주제의 비율. 개인 비율과 견줄 잣대다.
    room_tag: Counter[str] = Counter()
    for t in threads:
        for tag in t.get("tags") or []:
            room_tag[tag] += 1
    n_threads = len(threads) or 1

    people = []
    for nick, rows in sorted(threads_of.items(), key=lambda kv: -len(kv[1])):
        if nick in hidden or len(rows) < MIN_THREADS:
            continue

        fields = _lift_fields(rows, room_cat, room_total, lambda c: c,
                              lambda c: label_of.get(c, c), "category",
                              skip_categories)
        # 분류로 아무것도 안 나온 사람만 묶음으로 한 번 더 본다.
        if not fields and group_of:
            fields = _lift_fields(rows, room_group, group_total, group_of,
                                  group_label or (lambda g: g), "group")

        tf = Counter(tg for r in rows for tg in (r.get("tags") or [])
                     if tg not in person_tags)
        scored = []
        for tag, n in tf.items():
            # 그 사람의 주제 중 이 태그가 붙은 비율 ÷ 방 전체의 같은 비율.
            #
            # 처음에는 '몇 명이 쓴 태그인가'(TF-IDF)로 깎았는데, 발언이 많은
            # 사람은 방의 유행어(안티그래비티·바이브코딩)를 워낙 많이 건드려서
            # 그게 그대로 개인 특징으로 올라왔다 — 여섯 사람의 관심 화제가 거의
            # 같아졌다. 비율로 견주면 '방보다 유난히 많이 이야기한 것'만 남는다.
            lift = (n / len(rows)) / (room_tag[tag] / n_threads)
            scored.append((lift * math.log(1 + n), lift, n, tag))
        # 근거가 두 주제 이상인 것이 먼저다. 없으면 한 번뿐인 것으로 대신한다 —
        # 그 사람만 쓴 말이면 한 번이라도 관심사를 꽤 잘 가리킨다.
        strong = [s for s in scored if s[2] >= 2 and s[1] >= 1.3]
        pool = strong or [s for s in scored if s[1] >= 1.5]
        pool.sort(key=lambda s: (-s[0], -s[2], s[3]))
        topics = [{"tag": t, "count": n} for _, _, n, t in pool[:MAX_TOPICS]]

        if not topics and not fields:
            continue
        people.append({
            "nickname": nick,
            "thread_count": len(rows),
            "fields": fields[:MAX_FIELDS],
            "topics": topics,
        })

    return {
        "people": people,
        "hidden_count": sum(1 for n in threads_of if n in hidden),
        "min_threads": MIN_THREADS,
    }
