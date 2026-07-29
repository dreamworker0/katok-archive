# -*- coding: utf-8 -*-
"""OCR 로 읽은 사진 글자에서 개인정보를 찾아 '감출 사진' 목록을 만든다.

흐름
  scripts/ocr_images.ps1  사진 → output/image_ocr.json   (글자 읽기, Windows 내장 OCR)
  이 스크립트             글자 → output/image_pii.json   (판정)
  build_firestore_payload 판정 → 업로드 목록에서 제외

왜 '화면에서 감추기' 가 아니라 '올리지 않기' 인가
  관심 주제 빠지기를 만들 때 배운 것이다 — 화면에서만 감추면 개발자도구로 읽힌다.
  사진은 더 심하다. Storage 주소를 한 번 알면 화면을 거치지 않고 바로 받을 수 있다.
  그래서 감출 사진은 **업로드 목록에서 뺀다**.

판정 결과 파일에는 찾은 값을 **가린 형태로만** 적는다. 원래 값을 적으면 이 파일이
곧 개인정보 목록이 되고, 그게 저장소에 커밋된다.

사람이 되돌리는 길: `config/image_pii_allow.json` 의 `paths` 에 경로를 적으면
개인정보로 판정됐어도 그대로 발행한다(기관 안내문·포스터처럼 공개된 연락처).

사용:  python -m scripts.scan_image_pii [--verbose]
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from scripts import jsonio, pii

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
CONFIG = ROOT / "config"

OCR_PATH = OUTPUT / "image_ocr.json"
VERDICT_PATH = OUTPUT / "image_pii.json"
ALLOW_PATH = CONFIG / "image_pii_allow.json"


def load_allow_paths(path: Path | None = None) -> set[str]:
    p = path or ALLOW_PATH
    if not p.exists():
        return set()
    raw = jsonio.read_json(p)
    return {str(x).replace("\\", "/") for x in (raw.get("paths") or [])}


def hiding_enabled(path: Path | None = None) -> bool:
    """판정 결과를 실제로 발행에서 뺄지.

    `false` 로 두면 검사는 매일 돌지만 사진은 그대로 발행된다. 판정을 먼저 쌓아
    두고 사람이 감출 목록을 확인한 뒤에 켜기 위한 스위치다 — 파일을 어딘가로
    치워 두는 것보다 낫다. 치워 두면 왜 안 도는지 아무 데도 적혀 있지 않다.

    기본값은 켬이다. 설정 파일이 없는 상태가 '안전한 쪽' 이어야 한다.
    """
    p = path or ALLOW_PATH
    if not p.exists():
        return True
    return bool(jsonio.read_json(p).get("apply", True))


def judge(ocr: dict[str, list[str] | None],
          allow_paths: set[str] | None = None) -> dict:
    """사진별 판정. 반환은 그대로 output/image_pii.json 이 된다."""
    allow_paths = allow_paths if allow_paths is not None else load_allow_paths()
    allow = pii.load_allow()

    images: dict[str, dict] = {}
    for path, lines in sorted(ocr.items()):
        key = path.replace("\\", "/")
        if lines is None:
            # OCR 이 실패한 사진. '글자가 없다'와 갈라 둔다 — 확인하지 못한 것을
            # 통과시키면 검사를 돌린 보람이 없고, 통째로 감추면 읽기 실패 한 번에
            # 사진이 사라진다. 사람이 볼 수 있게 표시만 남기고 발행은 한다.
            images[key] = {"verdict": "unread", "kinds": [], "found": [], "lines": 0}
            continue

        # 줄 목록에 null 이 섞여 온다 — 글자가 없는 조각을 OCR 하면 PowerShell 쪽
        # ForEach-Object 가 빈 값을 하나 흘린다. 문자열만 남긴다.
        text = "\n".join(str(x) for x in lines if isinstance(x, str))
        hits = pii.find(text, allow)
        certain = [h for h in hits if h.grade == "certain"]
        likely = [h for h in hits if h.grade == "likely"]

        if certain and key not in allow_paths:
            verdict = "hide"
        elif certain:
            verdict = "allowed"      # 개인정보가 있지만 사람이 발행하기로 한 것
        elif likely:
            verdict = "review"       # 가릴 정도는 아니지만 사람이 한 번 볼 것
        else:
            verdict = "ok"

        images[key] = {
            "verdict": verdict,
            "kinds": sorted({h.kind for h in hits}),
            # 원래 값은 절대 적지 않는다 — 이 파일이 개인정보 목록이 되어 버린다
            "found": [{"kind": h.kind, "grade": h.grade, "masked": h.masked}
                      for h in hits],
            "lines": len(lines),
        }
    return {"version": 1, "images": images}


def hidden_paths(verdicts: dict | None = None) -> set[str]:
    """발행에서 뺄 사진 경로. 판정 파일이 없으면 빈 집합 — 검사 없이도 발행된다."""
    if verdicts is None:
        if not VERDICT_PATH.exists() or not hiding_enabled():
            return set()
        verdicts = jsonio.read_json(VERDICT_PATH)
    return {
        p for p, v in (verdicts.get("images") or {}).items()
        if v.get("verdict") == "hide"
    }


def main() -> None:
    if not OCR_PATH.exists():
        print("output/image_ocr.json 이 없습니다. 먼저 "
              "`powershell -File scripts\\ocr_images.ps1` 를 돌리세요.")
        return

    ocr = jsonio.read_json(OCR_PATH)
    result = judge(ocr)
    VERDICT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    counts = Counter(v["verdict"] for v in result["images"].values())
    total = len(result["images"])
    print("사진 %d장 판정 — 감춤 %d / 확인필요 %d / 통과 %d / 사람허용 %d / 읽기실패 %d"
          % (total, counts["hide"], counts["review"], counts["ok"],
             counts["allowed"], counts["unread"]))

    kinds = Counter(f["kind"] for v in result["images"].values()
                    for f in v["found"] if f["grade"] == "certain")
    if kinds:
        print("  걸린 종류: %s"
              % ", ".join("%s %d건" % kv for kv in kinds.most_common()))

    if counts["hide"] and not hiding_enabled():
        print("  [보류] config/image_pii_allow.json 의 apply 가 false 라 "
              "감추지 않고 그대로 발행합니다. 켜려면 true 로 바꾸세요.")

    if "--verbose" in sys.argv:
        for p, v in result["images"].items():
            if v["verdict"] in ("hide", "review"):
                print("  [%s] %s — %s" % (
                    v["verdict"], p,
                    ", ".join("%s %s" % (f["kind"], f["masked"]) for f in v["found"])))

    print("→ output/image_pii.json")


if __name__ == "__main__":
    main()
