# -*- coding: utf-8 -*-
"""답장 말풍선 캡처를 읽어 **부모 메시지 ID** 를 확정한다.

왜 이 파일이 있나
  카톡 txt 내보내기는 답장 구조를 통째로 버린다(kakao_replies.ps1 머리말 참고).
  그래서 몇 시간·며칠 전 글에 단 답장이 분류에서 바로 앞 화제에 흡수된다.
  audit_thread_fit.py 는 그것을 **내용으로 추론**했다. 여기서는 화면에 실제로
  그려진 '○○에게 답장' 머리글과 인용문을 읽어 **사실로 확정**한다.

어떻게 가르나 - 평균이 아니라 '가장 어두운 화소' 를 본다
  답장 말풍선 안에서 인용문과 본문은 **글자 색만** 다르다. 자리로는 못 가른다.
  실측 2026-09-22, 받은 말풍선(흰 바탕) 한 줄씩 가장 어두운 화소:

      '홍길동에게 답장'  -> 0            (순검정, 굵게)
      인용된 원문        -> 118,118,118  (평평한 회색, 0 이 한 번도 안 나옴)
      구분선            -> 230          (한 줄)
      본문              -> 0

  세 값이 멀찍이 떨어져 있어서 문턱을 지어낼 필요가 없다. 회색 118 은 R=G=B 라
  파란 링크(0,0,238 계열)와도 갈린다.

OCR 글자는 저장하지 않는다
  OCR 은 부정확하다(실측: '일치시키는' -> '일지시기는', '에게' -> '에계').
  읽은 글은 **이미 아카이브에 있는 원문과 맞춰보는 열쇠로만** 쓰고, 남기는 것은
  메시지 ID 한 쌍뿐이다. 맞출 원문이 없거나 어느 것인지 헷갈리면 버린다 -
  틀린 연결을 남기느니 없는 편이 낫다.

프레임을 잇지 않고, 말풍선 단위로 합친다
  처음에는 프레임을 세로로 이어 붙였다. 겹침으로 이동량을 재면 3노치가 263~270px
  로 들쭉날쭉한데(실측), 그 오차가 쌓여 같은 줄이 프레임마다 다른 자리에 놓였다.
  그래서 인용문 덩어리가 쪼개지고 본문이 빈 채로 잡혔다.

  그래서 **프레임마다 따로 읽고, 찾은 말풍선을 합친다.** 3노치(270px)씩 올리므로
  패널 653px 중 383px 이 겹치고, 그보다 낮은 말풍선은 어느 한 프레임에는 통째로
  들어온다. 같은 말풍선이 여러 프레임에 걸리면 **가장 많이 읽힌 판**만 남긴다.

덮어쓰지 않는다
  output/replies.jsonl 은 **합친다.** audit-thread-fit.json 이 --days 로 돌릴
  때마다 통째로 덮여 그 전 결과가 날아갔던 것과 같은 함정이다. 같은 child 가
  다시 잡히면 점수가 높은 쪽만 남긴다.

사용
  python -m scripts.reply_bubbles --frames <작업폴더>\\frames.json
  python -m scripts.reply_bubbles --frames ... --report   # 쓰지 않고 보여주기만
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

from PIL import Image

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.jsonio import read_json, read_jsonl

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
MESSAGES = OUTPUT / "messages.jsonl"
RESULT = OUTPUT / "replies.jsonl"

# --- 실측 상수 (2026-09-22, 받은 말풍선 / 밝은 테마) ---------------------------
# 인용문 회색. 정확히 118 이지만 안티에일리어싱을 감안해 폭을 준다.
QUOTE_MIN, QUOTE_MAX = 96, 150
# 본문·머리글의 검정.
INK_MAX = 60
# 말풍선 바탕(흰색)으로 볼 밝기의 아래끝. 노란 '내가 보낸' 말풍선을 걸러낸다.
BUBBLE_BG_MIN = 244
# 같은 말풍선으로 볼 줄 사이 간격과 왼쪽 여백 오차.
LINE_GAP_MAX = 42
LEFT_TOL = 10
# 머리글과 인용문 첫 줄 사이 간격.
HEADER_GAP_MAX = 48

# --- 맞추기 문턱 ---------------------------------------------------------------
# OCR 오류를 견디되 엉뚱한 연결은 막는 선.
CHILD_MIN = 0.72
PARENT_MIN = 0.62
# 1등과 2등이 이만큼은 벌어져야 한다. 안 벌어지면 '헷갈린다' 로 보고 버린다.
MARGIN_MIN = 0.06
# 닉네임은 짧아 OCR 오류가 치명적이다. 느슨하게 보되 후보를 좁히는 데만 쓴다.
NICK_MIN = 0.55
# 같은 말풍선으로 볼 닮음. 프레임을 건너뛰며 중복을 합칠 때 쓴다.
SAME_BUBBLE_MIN = 0.70
# 같은 말풍선이 걸쳐 있을 수 있는 프레임 거리. 3노치씩 올리므로 넉넉히 셋.
SAME_BUBBLE_FRAMES = 3
# 인용문 사이에 끼어도 넘어가 줄 '읽을 수 없는 줄' 수.
QUOTE_RUN_SKIP = 2
# 잘린 본문을 원문 앞부분과 견주는 방식으로 맞출 때 요구하는 최소 길이.
# 짧은 글에 이 방식을 쓰면 '감사합니다' 류가 아무 데나 붙는다.
PREFIX_MIN_LEN = 10

# '○○에게 답장'. OCR 이 '에계'·'답잠' 으로 읽는 일이 잦아(실측: 머리글 9개 중
# 5개가 '에계') 느슨하게 본다.
HEADER_RE = re.compile(r"^(?P<who>.{1,24}?)\s*에\s*[게계]\s*답\s*[장잠쟁]\s*$")

_KEEP = re.compile(r"[가-힣0-9a-zA-Z]+")


def norm(text: str) -> str:
    """맞춰보기 전용 정규화. 공백·문장부호·이모지를 버리고 글자만 남긴다.

    OCR 은 문장부호와 이모지에서 특히 많이 틀린다. 그것 때문에 맞는 짝을 놓치지
    않도록 아예 뺀다.
    """
    return "".join(_KEEP.findall(text or ""))


def ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


# ---------------------------------------------------------------- 그림 읽기

def _flatten(node) -> list[dict]:
    """중첩된 배열을 풀어 줄 객체만 남긴다.

    PowerShell 쪽 모양이 한결같지 않다: Get-OcrLines 는 `, $lines` 로 돌려주므로
    배열이 한 겹 더 감싸여 내려오고, 줄이 하나면 배열이 벗겨져 객체로 내려온다.
    실측 2026-09-22: 이 처리를 안 했을 때 789줄이 통째로 버려져 '답장 0개' 가
    나왔다 - 그래서 main() 에서 '한 줄도 못 읽음' 을 따로 막는다.
    """
    if node is None:
        return []
    if isinstance(node, dict):
        return [node]
    out: list[dict] = []
    for item in node:
        out.extend(_flatten(item))
    return out


def classify(img: Image.Image, line: dict) -> str:
    """글자 상자 안의 가장 어두운 화소로 줄의 종류를 가른다.

    'quote'     인용된 원문(회색 118)
    'ink'       머리글·본문(검정)
    'other'     링크·이모지·그 밖 - 답장 판정에 쓰지 않는다
    'nonwhite'  흰 말풍선이 아님(내가 보낸 노란 말풍선 등)
    """
    left = max(0, line["left"] - 2)
    top = max(0, line["top"] - 2)
    right = min(img.width, line["right"] + 2)
    bottom = min(img.height, line["bottom"] + 2)
    if right <= left or bottom <= top:
        return "other"
    crop = img.crop((left, top, right, bottom)).convert("RGB")
    px = crop.load()
    w, h = crop.size

    darkest, dark_rgb, brightest = 255, (255, 255, 255), 0
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            v = (r + g + b) // 3
            if v < darkest:
                darkest, dark_rgb = v, (r, g, b)
            if v > brightest:
                brightest = v

    # 말풍선 바탕이 흰색인지. 글자 사이 여백이 가장 밝은 화소다.
    if brightest < BUBBLE_BG_MIN:
        return "nonwhite"
    if darkest <= INK_MAX:
        return "ink"
    if QUOTE_MIN <= darkest <= QUOTE_MAX:
        r, g, b = dark_rgb
        # 회색은 R=G=B 다. 파란 링크·색 글자를 여기서 떨어뜨린다.
        if max(r, g, b) - min(r, g, b) <= 12:
            return "quote"
    return "other"


def load_frames(manifest_path: Path) -> list[dict]:
    manifest = read_json(manifest_path)
    pane = manifest["pane"]
    frames = []
    for jf in manifest["frames"]:
        data = read_json(jf)
        img = Image.open(data["image"])
        img.load()
        kept = []
        for ln in _flatten(data.get("lines")):
            if not all(k in ln for k in ("left", "right", "top", "bottom")):
                continue
            # 패널 밖(머리·입력칸)은 보지 않는다.
            if ln["top"] < pane["y"] or ln["bottom"] > pane["y"] + pane["h"]:
                continue
            ln = dict(ln)
            ln["kind"] = classify(img, ln)
            kept.append(ln)
        img.close()
        kept.sort(key=lambda l: (l["top"], l["left"]))
        frames.append({"index": data["index"], "image": data["image"],
                       "pane": pane, "lines": kept})
    frames.sort(key=lambda f: f["index"])
    return frames


# ------------------------------------------------------------ 말풍선 조립

def find_bubbles(frame: dict) -> list[dict]:
    """한 프레임 안에서 인용문(회색) 덩어리를 찾고, 그 위의 머리글과 아래의
    본문을 모은다."""
    lines = frame["lines"]
    pane = frame["pane"]
    bubbles = []
    i = 0
    while i < len(lines):
        if lines[i]["kind"] != "quote":
            i += 1
            continue
        # 인용문 덩어리. 중간에 이모지·깨진 줄('口 | 으')이 한둘 끼어도 끊지
        # 않는다 - 실측 2026-09-22: 그것 때문에 한 말풍선의 인용문이 세 조각으로
        # 나뉘어 본문이 빈 채로 잡혔다.
        run = [lines[i]]
        j = i + 1
        skipped = 0
        while j < len(lines):
            nx, last = lines[j], run[-1]
            if (abs(nx["left"] - last["left"]) > LEFT_TOL
                    or nx["top"] - last["bottom"] > LINE_GAP_MAX):
                break
            if nx["kind"] == "quote":
                run.append(nx)
                skipped = 0
                j += 1
            elif nx["kind"] == "other" and skipped < QUOTE_RUN_SKIP:
                skipped += 1
                j += 1
            else:
                break
        # 건너뛴 줄이 끝에 매달려 있으면 되돌린다.
        j -= skipped

        # 머리글: 인용문 바로 위의 검정 줄이 '○○에게 답장' 이어야 한다.
        who = None
        for k in range(i - 1, -1, -1):
            cand = lines[k]
            if run[0]["top"] - cand["bottom"] > HEADER_GAP_MAX:
                break
            if cand["kind"] != "ink":
                continue
            m = HEADER_RE.match((cand["text"] or "").strip())
            if m:
                who = m.group("who").strip()
            break

        if who is None:
            i = j
            continue

        # 본문: 인용문 아래의 검정 줄들. 같은 왼쪽 여백으로 이어지는 데까지.
        body = []
        last_bottom = run[-1]["bottom"]
        for k in range(j, len(lines)):
            nx = lines[k]
            if nx["top"] - last_bottom > LINE_GAP_MAX + 20:
                break
            if nx["kind"] != "ink":
                continue
            if abs(nx["left"] - run[0]["left"]) > LEFT_TOL:
                break
            body.append(nx)
            last_bottom = nx["bottom"]

        bubbles.append({
            "parent_nickname_ocr": who,
            "quote_ocr": " ".join(l["text"] for l in run),
            "body_ocr": " ".join(l["text"] for l in body),
            "frame": frame["index"],
            # 프레임 아래끝에 닿았으면 본문이 잘렸을 수 있다 - 합칠 때 참고.
            "clipped": (pane["y"] + pane["h"]) - last_bottom < 30,
        })
        i = j
    return bubbles


def _overlaps(a: str, b: str) -> bool:
    """짧은 쪽이 긴 쪽 어딘가에 거의 그대로 들어 있는가."""
    if not a or not b:
        return False
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) < 6:
        return ratio(a, b) >= SAME_BUBBLE_MIN
    m = difflib.SequenceMatcher(None, short, long).find_longest_match(0, len(short), 0, len(long))
    return m.size >= len(short) * SAME_BUBBLE_MIN


def merge_bubbles(bubbles: list[dict]) -> list[dict]:
    """여러 프레임에 걸쳐 잡힌 같은 말풍선을 하나로 줄인다.

    같다고 보는 조건: 가까운 프레임이고, 인용문이나 본문 가운데 하나가 확실히
    겹친다. 남기는 것은 **가장 많이 읽힌 판** - 프레임 가장자리에서 잘린 판은
    글이 짧아 자연히 진다.
    """
    kept: list[dict] = []
    for b in sorted(bubbles, key=lambda x: x["frame"]):
        bq, bb = norm(b["quote_ocr"]), norm(b["body_ocr"])
        hit = None
        for prev in kept:
            if abs(prev["frame"] - b["frame"]) > SAME_BUBBLE_FRAMES:
                continue
            # 보낸이 이름으로는 거르지 않는다 - 짧아서 OCR 이 크게 틀린다
            # (실측 2026-09-22: 같은 '이영희에게 답장' 이 '길돔에게', '47\ 2홀동에게'
            # 로 읽혔다). 이름을 조건에 넣으면 같은 말풍선이 안 합쳐져 잘린 판이
            # 따로 남는다. 인용문·본문이 겹치는지만 본다.
            pq, pb = norm(prev["quote_ocr"]), norm(prev["body_ocr"])
            if _overlaps(pq, bq) or (pb and bb and _overlaps(pb, bb)):
                hit = prev
                break
            # 본문이 통째로 비어 있으면 프레임 가장자리에서 잘린 조각이다.
            # 같은 사람에게 단 답장이 이웃 프레임에 또 있을 일은 사실상 없으므로,
            # 인용문이 안 겹쳐도(잘려서 다른 데가 읽혔을 뿐이다) 같은 것으로 본다.
            if (not pb or not bb) and ratio(norm(prev["parent_nickname_ocr"]),
                                            norm(b["parent_nickname_ocr"])) >= SAME_BUBBLE_MIN:
                hit = prev
                break
        if hit is None:
            kept.append(b)
            continue
        if len(bq) + len(bb) > len(norm(hit["quote_ocr"])) + len(norm(hit["body_ocr"])):
            kept[kept.index(hit)] = b
    return kept


# ---------------------------------------------------------------- 맞추기

def best_match(target: str, candidates: list[tuple[str, dict]]) -> tuple[dict | None, float, float]:
    """(가장 닮은 것, 점수, 2등과의 차). 후보가 하나면 차는 1.0 으로 본다."""
    scored = sorted(((ratio(target, key), i, msg) for i, (key, msg) in enumerate(candidates)),
                    key=lambda t: t[0], reverse=True)
    if not scored:
        return None, 0.0, 0.0
    top_score, _, top_msg = scored[0]
    margin = top_score - scored[1][0] if len(scored) > 1 else 1.0
    return top_msg, top_score, margin


def frag_score(fragment: str, full: str) -> float:
    """읽어 낸 조각이 이 원문에서 나온 것인가.

    인용문도 본문도 **원문의 연속된 한 조각**이다 - 말풍선 폭에서 잘리거나,
    프레임 가장자리에서 잘리거나, 인용문 중간부터 읽히기도 한다(실측 2026-09-22:
    목록이 딸린 글의 첫 줄이 빠지고 가운데부터 읽혔다).

    그래서 세 가지로 재고 가장 높은 값을 쓴다:
      · 통째로 견주기        - 잘리지 않았을 때
      · 원문 앞부분과 견주기  - 뒤가 잘렸을 때
      · 가장 긴 공통 덩어리   - 앞이 잘렸거나 가운데만 읽혔을 때
    마지막 것은 조각이 짧으면 아무 데나 걸리므로 길이를 요구한다.
    """
    if not fragment or not full:
        return 0.0
    best = ratio(fragment, full)
    best = max(best, ratio(fragment, full[:len(fragment)]))
    if len(fragment) >= PREFIX_MIN_LEN:
        m = difflib.SequenceMatcher(None, fragment, full).find_longest_match(
            0, len(fragment), 0, len(full))
        best = max(best, m.size / len(fragment))
    return best


def best_frag(fragment: str, candidates: list[tuple[str, dict]]) -> tuple[dict | None, float, float]:
    """frag_score 로 고른다. best_match 와 같은 모양으로 돌려준다."""
    scored = sorted(((frag_score(fragment, key), i, msg)
                     for i, (key, msg) in enumerate(candidates)),
                    key=lambda t: t[0], reverse=True)
    if not scored:
        return None, 0.0, 0.0
    top_score, _, top_msg = scored[0]
    margin = top_score - scored[1][0] if len(scored) > 1 else 1.0
    return top_msg, top_score, margin


def resolve(bubbles: list[dict], messages: list[dict]) -> tuple[list[dict], list[dict]]:
    by_nick: dict[str, list[dict]] = {}
    for m in messages:
        by_nick.setdefault(m["nickname"], []).append(m)
    nick_keys = [(norm(n), {"nickname": n}) for n in by_nick]
    body_keys = [(norm(m["text"]), m) for m in messages if norm(m["text"])]

    found, dropped = [], []
    for b in bubbles:
        body_n, quote_n = norm(b["body_ocr"]), norm(b["quote_ocr"])
        label = f"'{b['parent_nickname_ocr']}에게 답장' (프레임 {b['frame']})"
        if len(body_n) < 4 or len(quote_n) < 4:
            dropped.append({**b, "why": f"{label}: 읽은 글이 너무 짧아 맞출 수 없음"})
            continue

        child, cscore, cmargin = best_frag(body_n, body_keys)
        if child is None or cscore < CHILD_MIN or cmargin < MARGIN_MIN:
            dropped.append({**b, "why": f"{label}: 답장 본문을 특정 못함 "
                                        f"(점수 {cscore:.2f}, 차 {cmargin:.2f})"})
            continue

        # 부모의 보낸이. OCR 닉네임을 실제 참여자 이름에 맞춘다.
        # 이름은 짧아 크게 깨지는 일이 있다(실측: '이영희' -> '47\ 7入래').
        # 그때는 이름으로 좁히기를 포기하고 **인용문만으로** 전체에서 찾는다 -
        # 인용문은 길어서 그것만으로도 충분히 갈린다. 버리는 것보다 낫다.
        nick, nscore, _ = best_match(norm(b["parent_nickname_ocr"]), nick_keys)
        if nick is not None and nscore >= NICK_MIN:
            parent_nick = nick["nickname"]
            pool_src = by_nick[parent_nick]
            scope = parent_nick
        else:
            pool_src = messages
            scope = "이름 못 읽음 - 전체에서"

        pool = []
        for m in pool_src:
            if m["timestamp"] >= child["timestamp"]:
                continue
            key = norm(m["text"])
            if key:
                pool.append((key, m))
        parent, pscore, pmargin = best_frag(quote_n, pool)
        if parent is None or pscore < PARENT_MIN or pmargin < MARGIN_MIN:
            dropped.append({**b, "why": f"{label}: 부모를 특정 못함 "
                                        f"({scope}, 점수 {pscore:.2f}, 차 {pmargin:.2f})"})
            continue

        found.append({
            "child": child["id"],
            "child_nickname": child["nickname"],
            "child_date": child["date"],
            "parent": parent["id"],
            "parent_nickname": parent["nickname"],
            "parent_date": parent["date"],
            "body_score": round(cscore, 3),
            "quote_score": round(pscore, 3),
        })
    return found, dropped


def merge_into(path: Path, rows: list[dict]) -> tuple[int, int]:
    """기존 결과와 **합친다.** 같은 child 는 점수 합이 높은 쪽만 남긴다."""
    existing: dict[str, dict] = {}
    if path.exists():
        for r in read_jsonl(path):
            existing[r["child"]] = r
    added = changed = 0
    for r in rows:
        old = existing.get(r["child"])
        if old is None:
            existing[r["child"]] = r
            added += 1
        elif (r["body_score"] + r["quote_score"]) > (old["body_score"] + old["quote_score"]):
            existing[r["child"]] = r
            if old["parent"] != r["parent"]:
                changed += 1
    out = sorted(existing.values(), key=lambda r: r["child"])
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out),
                    encoding="utf-8")
    return added, changed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--frames", required=True, help="kakao_replies.ps1 이 만든 frames.json")
    ap.add_argument("--report", action="store_true", help="쓰지 않고 찾은 것만 보여준다")
    args = ap.parse_args()

    frames = load_frames(Path(args.frames))
    if not frames:
        print("프레임이 없습니다", file=sys.stderr)
        return 1
    total_lines = sum(len(f["lines"]) for f in frames)
    print(f"프레임 {len(frames)}장, 읽은 줄 {total_lines}개")
    if total_lines == 0:
        # 조용히 '0개' 로 끝내지 않는다 - 실측 2026-09-22: 줄 모양이 바뀌어 전부
        # 버려졌는데 '답장 없음' 처럼 보였다.
        print("OCR 줄을 하나도 못 읽었습니다 - 프레임 JSON 모양을 확인하세요", file=sys.stderr)
        return 1

    raw = []
    for fr in frames:
        raw.extend(find_bubbles(fr))
    bubbles = merge_bubbles(raw)
    print(f"답장 말풍선 {len(bubbles)}개 (겹쳐 잡힌 것 {len(raw)}개를 합침)")

    found, dropped = resolve(bubbles, read_jsonl(MESSAGES))
    for r in found:
        print(f"  {r['child']} ({r['child_nickname']}, {r['child_date']})"
              f"  ->  {r['parent']} ({r['parent_nickname']}, {r['parent_date']})"
              f"   본문 {r['body_score']:.2f} / 인용 {r['quote_score']:.2f}")
    for d in dropped:
        print(f"  [버림] {d['why']}")

    if args.report:
        print("(--report: 쓰지 않았습니다)")
        return 0

    added, changed = merge_into(RESULT, found)
    print(f"{RESULT.name}: 새로 {added}건, 부모가 바뀐 것 {changed}건 (전체는 합쳐서 보관)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
