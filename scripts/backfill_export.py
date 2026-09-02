# -*- coding: utf-8 -*-
"""옛날 대화가 담긴 내보내기 폴더를 아카이브에 합친다.

증분 수집(`ingest_incremental`)과 무엇이 다른가
    증분은 "마지막 메시지 뒤"만 본다. 그래서 아카이브가 시작되기 **전**의 대화가
    담긴 백업은 통째로 무시된다. 이 스크립트는 그 앞구간을 받기 위한 것이다.
    일상 경로가 아니라, 옛 백업이 나올 때만 도는 보조 경로다.

두 출처 중 어느 쪽이 정본인가 — 구간마다 다르다
    실측(2026-07-27, 2025-08~2026-07 모바일 백업 2,585건)으로 확인한 사실:

      · 모바일 내보내기는 본문을 **정확히 500자에서 자른다**. 기존 아카이브(PC
        내보내기)는 2,000자가 넘는 글도 온전하다. 그래서 겹치는 구간에서 긴 글은
        기존이 정본이다. 이걸 모르고 합치면 잘린 중복이 16건 생긴다.
      · 반대로 모바일에는 `<사진 읽지 않음>` 이 141건 있다. 그 기기가 사진을 받지
        못해 파일이 영영 없다는 뜻이다. 같은 자리에 기존은 실제 파일을 갖고 있다.
      · 대신 모바일만 가진 것도 있다 — 사진의 실제 파일 이름(해시.png)이 본문에
        박혀 있어, 메시지와 폴더 안 파일을 이어줄 수 있다.

    그래서 규칙은 이렇다.

      아카이브 시작 이전   백업이 유일한 출처다. 전부 받는다.
      겹치는 구간         기존이 정본이다. 기존에 없는 **글**만 받고,
                          '읽지 않음' 은 버리고, 파일 이름은 기존 사진에 이어붙인다.

같은 파일을 두 번 넣어도 안전한가
    그렇다. 판정이 (시각·이름·본문) 기준이라 두 번째 실행은 전부 '이미 있음' 이
    된다. 사진 파일도 내용 sha256 으로 걸러 같은 바이트를 두 번 복사하지 않는다.

사진 파일의 키가 두 개라는 점
    파일 이름 006bd1….png 는 **내용 해시가 아니다** — 실측 76개 전부 불일치했다.
    카톡 나름의 식별자라 메시지와 파일을 잇는 '참조 키' 로만 쓴다. 중복 판정은
    반드시 내용 sha256 으로 한다. 둘을 섞으면 55개 중복을 놓친다.

사용
    python -m scripts.backfill_export --dir assets/KakaoTalk_Chats_... --dry-run
    python -m scripts.backfill_export --dir assets/KakaoTalk_Chats_...
"""
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts import build_site, collection_policy
from scripts.kakao_parser import URL_RE, parse_chat

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
IMAGE_DIR = ROOT / "assets" / "images"
STATE_PATH = OUTPUT / "backfill-state.json"

# 모바일 내보내기가 본문을 자르는 길이. 이 길이에 딱 맞는 글은 잘렸다고 의심한다.
TRUNCATE_LEN = 500
UNSORTED_CATEGORY = "chat"
# classify_unsorted 는 t-unsorted-YYYY-MM-DD 형태만 미분류로 인식한다. 그래서
# 월 단위로 묶되 이름은 그 달 1일로 맞춘다 — 스레드 수를 11개로 줄이면서
# 기존 분류 경로를 그대로 쓸 수 있다.
UNSORTED_ID = "t-unsorted-%s-01"

WS_RE = re.compile(r"\s+")
# 내보내기 판마다 사진·이모티콘 표시를 본문 앞에 붙여 준다. 실측 2026-07-27:
#   PC        "출석이랑 물품 수령 등을 …"
#   점 구분   "이모티콘 출석이랑 물품 수령 등을 …"
# 같은 글인데 접두어 때문에 새 글로 잡혀 중복이 된다.
PREFIX_RE = re.compile(r"^(?:이모티콘|사진|동영상)\s+")


def norm_text(value: str | None) -> str:
    """공백 차이를 지운 비교용 본문.

    같은 글인데 PC 는 줄바꿈 하나, 모바일은 둘로 내보내는 경우가 있다. 그대로
    비교하면 같은 글이 새 글로 잡힌다.
    """
    return WS_RE.sub(" ", value or "").strip()


def content_key(value: str | None) -> str:
    """중복 판정용 열쇠. 공백과 판별 접두어를 지운 본문."""
    return WS_RE.sub(" ", PREFIX_RE.sub("", norm_text(value))).strip()


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ───────────────────────── 병합 판정 ─────────────────────────


@dataclass
class MergePlan:
    """무엇을 받고 무엇을 왜 버리는지. 적용 전에 사람이 읽어볼 수 있어야 한다."""
    old: list = field(default_factory=list)        # 아카이브 시작 이전 — 전부 받음
    overlap: list = field(default_factory=list)    # 겹치는 구간에서 건진 글
    media_links: list = field(default_factory=list)  # (기존 image_id, 파일명) 이어붙이기
    repairs: list = field(default_factory=list)    # (기존 id, 온전한 본문) 잘림 복구
    skipped: Counter = field(default_factory=Counter)

    @property
    def accepted(self) -> list:
        return sorted(self.old + self.overlap, key=lambda m: m.timestamp)


def _is_truncated_copy(candidate: str, existing_texts: list[str]) -> bool:
    """백업 쪽 글이 기존 긴 글의 앞부분만 잘라온 것인가.

    모바일 내보내기가 500자에서 자르기 때문에, 기존에 더 긴 원문이 있으면 그건
    새 글이 아니라 같은 글의 조각이다. 길이 조건을 함께 보는 이유는 짧은 글이
    우연히 다른 글의 앞부분과 겹치는 오판을 막기 위해서다.
    """
    if len(candidate) < TRUNCATE_LEN:
        return False
    head = norm_text(candidate)
    return any(norm_text(text).startswith(head) for text in existing_texts)


def plan_merge(parsed_messages, existing: list[dict]) -> MergePlan:
    """파싱 결과와 기존 아카이브를 견줘 받을 것을 고른다."""
    plan = MergePlan()
    if not existing:
        plan.old = list(parsed_messages)
        return plan

    archive_start = existing[0]["timestamp"]
    exact = {(e["timestamp"], e["nickname"], content_key(e["text"])) for e in existing}
    # 표시명을 뺀 열쇠도 만든다. 카톡에서 이름을 바꾸면 같은 글이 다른 사람 것으로
    # 보인다 — 실측 2026-07-27: '다온종합사회복지관' 이 '임태오' 으로 바뀌어 그
    # 사람 글 전부가 새 글로 잡혔다. 그냥 넣으면 중복에 유령 참여자까지 생긴다.
    same_text = {(e["timestamp"], content_key(e["text"])) for e in existing}
    by_slot: dict[tuple[str, str], list[dict]] = defaultdict(list)
    existing_by_time: dict[str, list[dict]] = defaultdict(list)
    for e in existing:
        by_slot[(e["timestamp"], e["nickname"])].append(e)
        existing_by_time[e["timestamp"]].append(e)

    for msg in parsed_messages:
        slot = (msg.timestamp, msg.nickname)
        key = content_key(msg.text)

        # 잘림 복구가 가장 먼저다. 이 판정은 구간과 무관하다 — 어느 출처든 '기존이
        # 새 것의 앞부분이고 더 짧다' 면 기존이 잘린 것이다. 방향이 스스로 지켜지므로
        # 잘린 출처(모바일 500자)가 온전한 본문을 덮어쓰는 일은 생기지 않는다.
        truncated = _find_truncated(msg, by_slot.get(slot, []))
        if truncated:
            plan.repairs.append((truncated["id"], msg.text))
            plan.skipped["잘림복구"] += 1
            continue

        if msg.timestamp < archive_start:
            plan.old.append(msg)
            continue

        # ── 여기부터는 겹치는 구간. 기존이 정본이다. ──
        if msg.media_status == "lost":
            # 기존은 같은 자리에 실제 사진을 갖고 있다. 받으면 오히려 나빠진다.
            plan.skipped["겹침_읽지않음"] += 1
            continue

        if msg.media_status == "referenced":
            targets = [e for e in by_slot.get(slot, []) if e.get("image_id")]
            if targets:
                # 기존 사진 메시지에 붙일 파일 이름이다. 새 메시지가 아니다.
                for ref in msg.media_refs:
                    plan.media_links.append((targets[0]["image_id"], ref))
                plan.skipped["겹침_파일연결"] += 1
                continue
            # 붙일 자리가 없다 = 아카이브가 아직 못 본 사진이다. 버리면 파일을
            # 손에 쥐고도 잃는다 — 나중에 증분 수집이 같은 사진을 '수집 대기'로
            # 넣어도 그때는 파일과 이어줄 단서가 없다.
            plan.overlap.append(msg)
            continue

        if msg.kind in ("image", "video"):
            # 같은 자리에 미디어 메시지가 **실제로 있을 때만** 건너뛴다. 예전에는
            # 무조건 건너뛰었는데, 그건 '겹치는 구간이면 아카이브에 그 사진이 있다'는
            # 가정이었다. 동영상에는 그 가정이 성립하지 않는다 — 2026-07-27 전까지
            # 아예 수집하지 않았으므로 자리가 없다. 무조건 건너뛰면 정책을 바꿔도
            # 옛 동영상이 영영 들어오지 못한다.
            # 이름은 보지 않는다. 사진·동영상에는 견줄 본문이 없어서 표시명이
            # 바뀌면 같은 사진이 남의 것으로 보인다 — 실측 2026-07-27: '임태오' 으로
            # 들어온 사진이 아카이브에는 '다온종합사회복지관' 으로 있었고, 이름으로
            # 찾으니 자리가 없다고 판단해 중복 사진과 유령 참여자를 만들었다.
            same_minute = any(
                e.get("image_id") and e.get("kind") == msg.kind
                for e in existing_by_time.get(msg.timestamp, []))
            if same_minute:
                plan.skipped["겹침_사진"] += 1
                continue
            plan.overlap.append(msg)
            continue

        if (msg.timestamp, msg.nickname, key) in exact:
            plan.skipped["이미_보관"] += 1
            continue

        if (msg.timestamp, key) in same_text:
            plan.skipped["이름만_다름"] += 1
            continue

        if _is_truncated_copy(msg.text, [e["text"] for e in by_slot.get(slot, [])]):
            plan.skipped["잘린_중복"] += 1
            continue

        plan.overlap.append(msg)

    return plan


def _find_truncated(msg, candidates: list[dict]) -> dict | None:
    """이 메시지의 온전한 본문으로 고쳐야 할 기존 레코드. 없으면 None.

    조건을 좁게 잡는다 — 기존이 40자 이상이고, 새 것이 더 길고, 새 것의 앞부분이
    기존과 같아야 한다. 짧은 글끼리 우연히 앞부분이 겹쳐 엉뚱한 글을 덮어쓰는 일을
    막기 위해서다.
    """
    if msg.kind != "text":
        return None
    incoming = norm_text(msg.text)
    for e in candidates:
        if e.get("kind") != "text":
            continue
        current = norm_text(e.get("text"))
        if len(current) < 40 or len(current) >= len(incoming):
            continue
        if incoming.startswith(current[:60]):
            return e
    return None


# ───────────────────────── 레코드 만들기 ─────────────────────────


def to_record(msg, number: int) -> dict:
    """messages.jsonl 레코드. 스키마는 기존과 똑같이 둔다.

    '읽지 않음' 같은 사진의 사연은 images.jsonl 이 들고 있다. 정본 파일의 모양을
    바꾸면 파생 파일과 웹까지 전부 흔들리므로, 여기서는 늘리지 않는다.
    """
    return {
        "id": "msg-%06d" % number,
        "timestamp": msg.timestamp,
        "date": msg.date,
        "time": msg.time,
        "nickname": msg.nickname,
        # '읽지 않음' 은 본문이 아니라 상태다. 화면에 그 말이 그대로 나오면
        # 대화 내용처럼 읽힌다 — 사진/동영상 자리표로 바꿔 둔다.
        "text": ("동영상" if msg.kind == "video" else "사진")
                if msg.media_status else msg.text,
        "urls": list(msg.urls),
        "kind": msg.kind,
        "image_id": ("img-%06d" % number) if msg.kind in ("image", "video") else None,
        "image_count": msg.image_count if msg.kind in ("image", "video") else None,
        "source_line": msg.source_line,
        "is_file_share": msg.kind == "file",
    }


def image_entry(rec: dict, msg, note: str) -> dict:
    """사진·동영상 메시지 하나에 대응하는 images.jsonl 항목(파일은 아직 안 붙임)."""
    lost = msg.media_status == "lost"
    return {
        "image_id": rec["image_id"],
        # 사진과 동영상이 같은 대장을 쓰므로 무엇인지 적어 둔다. 이게 없으면
        # 동영상 경로가 사진 목록에 섞여 화면이 <img> 로 그리려다 깨진다.
        "media_kind": "video" if rec["kind"] == "video" else "image",
        "message_id": rec["id"],
        "timestamp": rec["timestamp"],
        "nickname": rec["nickname"],
        "image_sequence": 1,
        "expected_asset_count": rec.get("image_count") or 1,
        # 'lost' 는 수집 대기와 구분한다. 채워질 수 없는 것을 대기로 두면
        # 수집 목록이 영원히 줄지 않아 남은 일이 얼마인지 알 수 없게 된다.
        "status": "lost" if lost else "pending",
        "local_path": None,
        "original_filename": None,
        "extension": None,
        "byte_size": None,
        "sha256": None,
        "collected_at": None,
        "note": note,
        "assets": [],
        "media_refs": list(msg.media_refs),
    }


# ───────────────────────── 사진 파일 붙이기 ─────────────────────────


def build_sha_index(images: list[dict]) -> dict[str, str]:
    """이미 갖고 있는 내용 sha256 → 저장 경로."""
    index: dict[str, str] = {}
    for row in images:
        for asset in row.get("assets") or []:
            if asset.get("sha256") and asset.get("local_path"):
                index.setdefault(asset["sha256"], asset["local_path"])
        if row.get("sha256") and row.get("local_path"):
            index.setdefault(row["sha256"], row["local_path"])
    return index


def attach_files(images: list[dict], source_dir: Path, dry_run: bool) -> Counter:
    """media_refs 로 지목된 파일을 실제로 붙인다.

    같은 바이트를 이미 갖고 있으면 복사하지 않고 그 경로를 가리킨다. 백업을 여러
    번 받다 보면 같은 사진이 계속 나오는데, 그때마다 복사하면 저장소만 커진다.
    """
    stats = Counter()
    sha_index = build_sha_index(images)
    now = datetime.now(KST).isoformat(timespec="seconds")

    for row in images:
        refs = row.get("media_refs") or []
        if not refs or row.get("assets"):
            continue

        assets = []
        seen_here: set[str] = set()
        for seq, ref in enumerate(refs, start=1):
            src = source_dir / ref
            if not src.is_file():
                stats["파일없음"] += 1
                continue

            digest = sha256_of(src)
            # 한 메시지 안에서 같은 사진이 두 번 붙는 일이 있다 — '사진 2장' 인데
            # 내보내기가 같은 파일을 두 개 준 경우다(실측 img-001900). 그대로 두면
            # 갤러리에 같은 썸네일이 두 번 나오고 장수도 부풀려진다.
            if digest in seen_here:
                stats["같은_사진_중복"] += 1
                continue
            seen_here.add(digest)
            suffix = src.suffix.lower()
            known = sha_index.get(digest)
            if known:
                rel = known
                stats["중복_재사용"] += 1
            else:
                month = row["timestamp"][:7]
                # 동영상은 폴더를 갈라 둔다. assets/images 는 '사진 하나당 파일
                # 하나' 라는 성질을 지켜야 하고(테스트가 그것을 센다), Storage
                # 규칙도 경로로 나누면 무엇이 무엇인지 규칙만 봐도 안다.
                root = ("assets/videos" if row.get("media_kind") == "video"
                        else "assets/images")
                rel = "%s/%s/%s-%02d%s" % (root, month, row["image_id"], seq, suffix)
                if not dry_run:
                    dest = ROOT / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)
                sha_index[digest] = rel
                stats["새_파일"] += 1

            assets.append({
                "asset_id": "%s-%02d" % (row["image_id"], seq),
                "local_path": rel,
                # 카톡 폴더 안 이름. 내용 해시가 아니라 참조 키다.
                "original_filename": ref,
                "extension": suffix,
                "byte_size": src.stat().st_size,
                "sha256": digest,
                "collected_at": now,
            })

        if assets:
            first = assets[0]
            row.update({
                "status": "downloaded" if len(assets) >= (row.get("expected_asset_count") or 1)
                          else "partial",
                "local_path": first["local_path"],
                "original_filename": first["original_filename"],
                "extension": first["extension"],
                "byte_size": first["byte_size"],
                "sha256": first["sha256"],
                "collected_at": now,
                "assets": assets,
            })
    return stats


# 시각을 이름으로 쓰는 판. 20251001_090514_1.png = 2025-10-01 09:05:14 의 첫 장.
TIME_NAME_RE = re.compile(
    r"^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})(?:_(\d+))?\.(\w+)$")
IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "webp"}
VIDEO_EXT = {"mp4", "mov"}
# 사진과 동영상은 같은 미디어 대장을 쓰므로 함께 맞춘다. 대신 자리를 섞으면 안 된다 —
# 사진 메시지에 동영상이 붙으면 갤러리가 그림으로 읽으려 해 깨진다.
MEDIA_EXT = IMAGE_EXT | VIDEO_EXT


def link_by_timestamp(images: list[dict], source_dir: Path) -> Counter:
    """파일 이름의 시각으로 사진 메시지를 찾아 이어 준다.

    앞선 판(해시 이름)은 본문에 파일 이름이 적혀 있어 그대로 이었지만, 이 판은
    본문이 그냥 '사진' 이다. 대신 파일 이름이 초 단위 시각이라 메시지의 분과 맞출
    수 있다. 한 분에 여러 장이면 파일 이름의 순번 순서대로 채운다.

    이미 파일을 가진 항목은 건드리지 않는다 — 먼저 들어온 것이 정본이다.
    """
    stats = Counter()
    # 사진과 동영상을 갈라서 맞춘다. 한 통에 섞으면 사진 메시지에 mp4 가 붙어
    # 화면이 그림으로 읽으려다 깨진다 — 자리 수만 맞으면 조용히 잘못 붙는다.
    by_minute: dict[tuple[str, str], list[tuple[int, str]]] = defaultdict(list)
    for path in sorted(source_dir.iterdir()):
        match = TIME_NAME_RE.match(path.name)
        if not match or match.group(8).lower() not in MEDIA_EXT:
            continue
        year, month, day, hour, minute, _sec, seq, ext = match.groups()
        stamp = "%s-%s-%sT%s:%s+09:00" % (year, month, day, hour, minute)
        lane = "video" if ext.lower() in VIDEO_EXT else "image"
        by_minute[(stamp, lane)].append((int(seq or 0), path.name))

    for rows in by_minute.values():
        rows.sort()

    # 같은 분의 미디어 메시지를 순서대로 놓고 파일을 차례로 붙인다
    waiting: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in images:
        if row.get("assets") or row.get("media_refs"):
            continue
        waiting[(row["timestamp"], row.get("media_kind") or "image")].append(row)

    for stamp, files in by_minute.items():
        targets = waiting.get(stamp) or []
        if not targets:
            stats["대응_메시지_없음"] += len(files)
            continue
        names = [name for _seq, name in files]
        for index, row in enumerate(targets):
            want = row.get("expected_asset_count") or 1
            take, names = names[:want], names[want:]
            if not take:
                break
            row["media_refs"] = take
            # '유실' 로 적어 둔 것이 실제로 나타났다. 상태를 되돌린다.
            if row.get("status") == "lost":
                row["status"] = "pending"
                row["note"] = "옛 백업(시각 이름)에서 원본을 찾음"
            stats["연결"] += len(take)
        if names:
            stats["남은_파일"] += len(names)
    return stats


ASSETS_FILES = ROOT / "assets" / "files"
# 동영상은 이 아카이브가 수집하지 않는다 — 파서가 '동영상' 메시지를 제외하므로
# 붙일 자리가 아예 없다. 정책을 바꾸는 일이라 여기서 조용히 넣지 않는다.
SKIP_EXT = IMAGE_EXT | {"mp4", "mov"}


def link_attachments(files: list[dict], messages: list[dict],
                     source_dir: Path, dry_run: bool) -> Counter:
    """시각 이름 파일 중 첨부(pdf·html 등)를 '파일: 이름' 메시지에 붙인다.

    원본 파일명은 내보내기 폴더에 남지 않는다(이름이 시각으로 바뀐다). 그래서
    메시지 본문의 '파일: 원래이름' 을 파일명으로 쓴다 — 사람이 화면에서 보는
    이름이 그것이고, 목록도 그 이름으로 남아 있다.
    """
    stats = Counter()
    have_msg = {f["message_id"] for f in files}
    have_sha = {f.get("sha256") for f in files}
    waiting: dict[str, list[dict]] = defaultdict(list)
    for m in messages:
        if m.get("kind") == "file" and m["id"] not in have_msg:
            waiting[m["timestamp"]].append(m)

    for path in sorted(source_dir.iterdir()):
        match = TIME_NAME_RE.match(path.name)
        if not match or match.group(8).lower() in SKIP_EXT:
            continue
        year, month, day, hour, minute, _sec, _seq, ext = match.groups()
        stamp = "%s-%s-%sT%s:%s+09:00" % (year, month, day, hour, minute)
        targets = waiting.get(stamp) or []
        if not targets:
            stats["대응_메시지_없음"] += 1
            continue

        digest = sha256_of(path)
        if digest in have_sha:
            stats["이미_보유"] += 1
            continue

        msg = targets.pop(0)
        name = re.sub(r"^파일:\s*", "", (msg.get("text") or "")).strip() or path.name
        # 파일명에 경로 구분자가 섞이면 엉뚱한 곳에 쓴다. 이름만 남긴다.
        name = os.path.basename(name.replace("\\", "/")) or path.name
        rel = "assets/files/%s" % name
        if not dry_run:
            dest = ROOT / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
        files.append({
            "file_id": "file-%s" % msg["id"].split("-")[1],
            "message_id": msg["id"],
            "filename": name,
            "local_path": rel,
            "byte_size": path.stat().st_size,
            "sha256": digest,
            "content_type": mimetypes.guess_type(name)[0] or "application/octet-stream",
            "nickname": msg["nickname"],
            "date": msg["date"],
        })
        have_sha.add(digest)
        stats["연결"] += 1
    return stats


def apply_repairs(messages: list[dict], repairs: list[tuple[str, str]]) -> int:
    """잘린 본문을 온전한 것으로 고친다. 고친 건수를 돌려준다."""
    by_id = {m["id"]: m for m in messages}
    fixed = 0
    for mid, text in repairs:
        row = by_id.get(mid)
        if row is None or row.get("text") == text:
            continue
        row["text"] = text
        row["urls"] = URL_RE.findall(text)
        fixed += 1
    return fixed


def apply_media_links(images: list[dict], links: list[tuple[str, str]]) -> int:
    """겹치는 구간의 기존 사진 메시지에 파일 이름을 이어붙인다."""
    by_id = {row["image_id"]: row for row in images}
    linked = 0
    for image_id, ref in links:
        row = by_id.get(image_id)
        # 이미 파일을 갖고 있으면 건드리지 않는다 — 기존이 정본이다.
        if row is None or row.get("assets"):
            continue
        refs = row.setdefault("media_refs", [])
        if ref not in refs:
            refs.append(ref)
            linked += 1
    return linked


# ───────────────────────── 주제 배정 ─────────────────────────


def assign_monthly(topics: dict, records: list[dict]) -> int:
    """새 메시지를 달 단위 미분류 스레드에 넣는다.

    날짜 단위로 쪼개면 11개월치가 스레드 200개가 된다. 분류기는 어차피 미분류를
    한데 모아 처리하므로, 사람이 목록을 훑을 수 있는 크기인 달 단위로 둔다.
    """
    by_month: dict[str, list[str]] = defaultdict(list)
    for rec in records:
        by_month[rec["date"][:7]].append(rec["id"])

    existing = {t["id"]: t for t in topics["threads"]}
    for month, ids in sorted(by_month.items()):
        tid = UNSORTED_ID % month
        thread = existing.get(tid)
        if thread:
            thread["message_ids"].extend(ids)
            thread["end_msg"] = ids[-1]
            continue
        topics["threads"].append({
            "id": tid,
            "category": UNSORTED_CATEGORY,
            "title": "미분류 대화 (%s)" % month,
            "summary": "옛 백업에서 합쳐진 대화입니다. 주제 분류가 필요합니다.",
            "start_msg": ids[0],
            "end_msg": ids[-1],
            "message_ids": list(ids),
        })
    return len(by_month)


# ───────────────────────── 본 처리 ─────────────────────────


def find_export_txt(directory: Path) -> Path:
    candidates = sorted(directory.glob("*.txt"))
    if not candidates:
        raise SystemExit("폴더 안에 txt 가 없습니다: %s" % directory)
    if len(candidates) > 1:
        raise SystemExit("txt 가 여러 개입니다. --file 로 하나를 지정하세요: %s"
                         % ", ".join(p.name for p in candidates))
    return candidates[0]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def run(directory: Path, dry_run: bool) -> dict:
    txt_path = find_export_txt(directory)
    digest = sha256_of(txt_path)

    state = build_site._read_json(STATE_PATH) if STATE_PATH.exists() else {"processed": []}
    if digest in {e["sha256"] for e in state.get("processed", [])}:
        print("이미 합친 백업입니다: %s" % txt_path.name)
        return {"added": 0, "already": True}

    messages = build_site._read_jsonl(OUTPUT / "messages.jsonl")
    images = build_site._read_jsonl(OUTPUT / "images.jsonl")
    topics = build_site._read_json(OUTPUT / "topics.json")

    result = parse_chat(txt_path.read_text(encoding="utf-8", errors="replace"))
    print("%s: 파싱 %d건 (제외 %s)" % (txt_path.name, len(result.messages), result.excluded))

    plan = plan_merge(result.messages, messages)
    policy = collection_policy.load_policy()
    accepted, refused, _ = collection_policy.filter_messages(plan.accepted, policy)

    print("  아카이브 이전 %d건 / 겹치는 구간에서 건진 글 %d건"
          % (len(plan.old), len(plan.overlap)))
    print("  건너뜀: %s" % dict(plan.skipped))
    if refused:
        print("  수집 거부 %d건 %s" % (sum(refused.values()), refused))
    truncated = sum(1 for m in accepted if len(m.text) >= TRUNCATE_LEN)
    if truncated:
        print("  ⚠ 500자에서 잘린 채 들어오는 글 %d건 — 더 긴 원본이 없습니다" % truncated)

    if plan.repairs:
        by_id = {m["id"]: m for m in messages}
        gained = sum(len(t) - len(by_id[i]["text"]) for i, t in plan.repairs if i in by_id)
        print("  잘림 복구 %d건 — 되찾는 글자 %d자 (원본을 고쳐 씁니다)"
              % (len(plan.repairs), gained))
        for mid, text in sorted(plan.repairs, key=lambda p: -len(p[1]))[:5]:
            row = by_id.get(mid)
            if row:
                print("      %s %s %s  %d자 → %d자"
                      % (mid, row["timestamp"][:16], row["nickname"],
                         len(row["text"]), len(text)))

    if dry_run:
        print("\n--dry-run: 파일을 바꾸지 않았습니다.")
        return {"added": len(accepted), "plan": plan}

    # 마지막 줄이 아니라 **전체 최댓값**에서 다음 번호를 뽑는다. 이 파일은 시각 순으로
    # 정렬돼 있어서 마지막 줄이 가장 큰 번호가 아니다 — 옛 백업을 합치면 번호가 큰
    # 레코드가 중간으로 간다. 실측 2026-07-27: 마지막 줄을 믿어 msg-002596 을 다시
    # 발급해 같은 ID 를 가진 메시지가 두 개 생겼고, 주제 배정까지 어긋났다.
    # (ingest_incremental.next_message_number 도 같은 이유로 고쳤다.)
    start_no = max((int(m["id"].split("-")[1]) for m in messages), default=0) + 1
    new_records = []
    for offset, msg in enumerate(accepted):
        rec = to_record(msg, start_no + offset)
        new_records.append(rec)
        if rec["kind"] in ("image", "video"):
            note = ("내보내기 시점에 사진을 받지 못해 원본이 없습니다"
                    if msg.media_status == "lost" else "옛 백업에서 합쳐짐")
            images.append(image_entry(rec, msg, note))

    repaired = apply_repairs(messages, plan.repairs)
    files_path = OUTPUT / "files.jsonl"
    attachments = build_site._read_jsonl(files_path) if files_path.exists() else []
    link_attachments(attachments, messages, directory, dry_run=False)
    linked = apply_media_links(images, plan.media_links)
    # 본문에 파일 이름이 적힌 판을 먼저 붙이고, 남은 것을 시각으로 맞춘다.
    # 순서가 중요하다 — 이름이 적힌 쪽이 더 확실하므로 그것이 자리를 먼저 잡는다.
    time_stats = link_by_timestamp(images, directory)
    file_stats = attach_files(images, directory, dry_run=False)
    months = assign_monthly(topics, new_records)

    messages.extend(new_records)
    messages.sort(key=lambda m: (m["timestamp"], m["id"]))

    write_jsonl(OUTPUT / "messages.jsonl", messages)
    write_jsonl(OUTPUT / "images.jsonl", images)
    (OUTPUT / "participants.json").write_text(
        json.dumps(_participants(messages), ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUT / "topics.json").write_text(
        json.dumps(topics, ensure_ascii=False, indent=2), encoding="utf-8")

    state.setdefault("processed", []).append({
        "file": txt_path.name,
        "sha256": digest,
        "added": len(new_records),
        "repaired": repaired,
        "linked_files": linked,
        "merged_at": datetime.now(KST).isoformat(timespec="seconds"),
    })
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n합침: 메시지 +%d건, 잘림 복구 %d건, 미분류 스레드 %d개"
          % (len(new_records), repaired, months))
    print("  사진 연결: 이름 기준 %d건 · 시각 기준 %s" % (linked, dict(time_stats)))
    print("  파일 처리: %s" % dict(file_stats))
    return {"added": len(new_records), "plan": plan}


def _participants(messages: list[dict]) -> dict:
    rows: dict[str, dict] = {}
    for m in messages:
        row = rows.get(m["nickname"])
        if row is None:
            rows[m["nickname"]] = {"nickname": m["nickname"], "message_count": 1,
                                   "first_timestamp": m["timestamp"],
                                   "last_timestamp": m["timestamp"]}
        else:
            row["message_count"] += 1
            row["first_timestamp"] = min(row["first_timestamp"], m["timestamp"])
            row["last_timestamp"] = max(row["last_timestamp"], m["timestamp"])
    return {"participants": sorted(rows.values(),
                                   key=lambda r: r["message_count"], reverse=True)}


def main() -> int:
    ap = argparse.ArgumentParser(description="옛 내보내기 폴더를 아카이브에 합친다")
    ap.add_argument("--dir", required=True, help="KakaoTalk_Chats_... 폴더")
    ap.add_argument("--dry-run", action="store_true", help="바꾸지 않고 결과만 본다")
    args = ap.parse_args()

    directory = Path(args.dir)
    if not directory.is_absolute():
        directory = ROOT / directory
    if not directory.is_dir():
        raise SystemExit("폴더가 없습니다: %s" % directory)

    run(directory, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
