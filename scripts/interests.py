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


def build_interests(threads: list[dict], categories: list[dict],
                    hidden: set[str] | None = None,
                    person_tags: set[str] | None = None) -> dict:
    """{"people": [...], "hidden_count": n} 를 돌려준다.

    `person_tags` 로 준 사람 이름 태그는 관심 화제에서 뺀다 — 자기 이름이
    '내 관심사'로 올라오면(실측: 김종원·오세라) 화면이 우스워진다.
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

        mine_cat = Counter(r["category"] for r in rows)
        mine_total = sum(mine_cat.values()) or 1
        fields = []
        for cid, n in mine_cat.items():
            if n < 2:
                continue
            lift = (n / mine_total) / (room_cat[cid] / room_total)
            if lift < 1.2:
                continue
            fields.append({"category": cid, "label": label_of.get(cid, cid),
                           "count": n, "lift": round(lift, 2)})
        fields.sort(key=lambda f: (-f["lift"], -f["count"]))

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
