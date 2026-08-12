# -*- coding: utf-8 -*-
"""사진 개인정보 판정을 사람이 한 번에 훑어볼 검토표를 만든다.

## 왜 필요한가

OCR 판정은 `hide`(감춤)까지만 정한다. 실제로 감추는 것은
`config/image_pii_allow.json` 의 `apply` 가 켜져야 일어나고, 그것을 켜는 판단은
사람 몫이다 — 켜면 `upload_firestore.js` 의 `pruneOrphans` 가 Storage 에서 원본과
썸네일을 **실제로 지운다.** 되돌릴 수 없으므로 눈으로 보고 정해야 한다.

그런데 판정 결과(`output/image_pii.json`)만으로는 볼 수가 없다. 경로와 가린 값이
적혀 있을 뿐이라, 그 사진이 기관 안내문인지 누군가의 명함인지 알 수 없다. 실제로
2026-07-30 에 18장을 확인하기로 하고 13일을 보류했다 — 훑을 도구가 없어서다.

## 무엇을 내놓는가

`output/image-pii-review.html` 한 장. 판단이 필요한 사진만 큼직하게 늘어놓고,
찍힌 값(가린 형태)·올린 사람·날짜·어느 대화였는지를 함께 보여준다. 다 보고 나면
'그대로 발행할 것' 으로 고른 경로 목록을 복사해 `image_pii_allow.json` 의 `paths`
에 붙일 수 있다.

## 왜 파일 하나에 담는가

사진을 data URI 로 박아 넣는다. 그래서 서버 없이 두 번 눌러 열 수 있고, 검토가
끝나면 파일 하나만 지우면 된다 — 개인정보가 찍힌 사진을 여기저기 복사해 두지
않는다. 이 파일은 `output/` 에 쓴다(커밋 대상이 아니다).

**원본 값은 이 파일에 쓰지 않는다.** 판정 결과에는 애초에 가린 형태만 남아 있고
(`pii.find` 가 그렇게 만든다), 판단에 필요한 원본은 사진 안에 있다. 검토표가
연락처 목록이 되어서는 안 된다.

사용
    python -m scripts.build_image_pii_review
    python -m scripts.build_image_pii_review --all   # 이미 판단한 것까지 전부
"""
from __future__ import annotations

import argparse
import base64
import html
import io
import json
from pathlib import Path

from scripts import jsonio, scan_image_pii

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
OUT_HTML = OUTPUT / "image-pii-review.html"

# 사진에 찍힌 이메일·전화를 읽어야 판단이 되므로 썸네일로는 부족하다. 그렇다고
# 원본(수 MB)을 박으면 파일이 수십 MB 가 된다. 실측: 1100px 이면 화면 캡처의
# 본문 글자가 읽힌다.
MAX_WIDTH = 1100
JPEG_QUALITY = 82

# 판단이 필요한 판정만 낸다. `ok` 는 볼 것이 없고, `allowed` 는 사람이 이미
# 발행하기로 정한 것이다 — 한 번 판단한 것을 또 묻지 않는다(`place_candidates`
# 와 같은 방식).
NEEDS_DECISION = ("hide", "review")


def _thumb_data_uri(path: Path) -> str | None:
    """사진을 읽을 만한 크기로 줄여 data URI 로. 못 읽으면 None."""
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            if im.width > MAX_WIDTH:
                h = round(im.height * MAX_WIDTH / im.width)
                im = im.resize((MAX_WIDTH, h), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    except OSError:
        return None
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _context() -> tuple[dict, dict]:
    """사진 경로 → 올린 사람·날짜, 그리고 메시지 → 주제 제목.

    '누가 언제 올렸나' 와 '무슨 이야기였나' 가 있어야 기관 안내문인지 개인 연락처인지
    가려진다. 관리자가 보는 화면이므로 표시명을 가리지 않는다 — 발행본과 달리
    관리자 원장은 오탐을 되돌릴 근거라서 가리지 않는 것과 같은 판단이다.
    """
    by_asset: dict[str, dict] = {}
    path = OUTPUT / "images.jsonl"
    rows = jsonio.read_jsonl(path) if path.exists() else []
    for r in rows:
        # `assets` 는 딕셔너리 목록이고 경로는 그 안의 `local_path` 다. 행 자체의
        # `local_path` 는 첫 장만 가리키므로(한 메시지에 사진 여러 장) 쓰면 안 된다.
        for asset in r.get("assets") or []:
            key = str((asset or {}).get("local_path") or "").replace("\\", "/")
            if not key:
                continue
            by_asset[key] = {"nickname": r.get("nickname") or "",
                             "timestamp": (r.get("timestamp") or "")[:16],
                             "message_id": r.get("message_id") or ""}

    title_of: dict[str, str] = {}
    topics = jsonio.read_json(OUTPUT / "topics.json") if (OUTPUT / "topics.json").exists() else {}
    for t in topics.get("threads") or []:
        for mid in t.get("message_ids") or []:
            title_of[mid] = t.get("title") or t.get("id") or ""
    return by_asset, title_of


def rows_to_review(verdicts: dict, allow: set[str],
                   include_all: bool = False) -> list[tuple[str, dict]]:
    """검토표에 낼 (경로, 판정) 목록. 판정이 나쁜 것부터."""
    images = (verdicts or {}).get("images") or {}
    out = []
    for key, v in images.items():
        verdict = v.get("verdict")
        if include_all:
            if verdict == "ok":
                continue
        elif verdict not in NEEDS_DECISION or key in allow:
            continue
        out.append((key, v))
    order = {"hide": 0, "review": 1, "allowed": 2, "unread": 3}
    out.sort(key=lambda kv: (order.get(kv[1].get("verdict"), 9), kv[0]))
    return out


def render(rows: list[tuple[str, dict]], by_asset: dict, title_of: dict,
           apply_on: bool) -> str:
    esc = html.escape
    cards = []
    for key, v in rows:
        meta = by_asset.get(key) or {}
        found = v.get("found") or []
        # 가린 형태만 보여준다. 원본은 사진 안에 있고, 이 표가 연락처 목록이
        # 되어서는 안 된다.
        hits = "".join(
            '<li><b>%s</b> <span class="grade %s">%s</span> %s</li>'
            % (esc(f.get("kind") or ""), esc(f.get("grade") or ""),
               esc(f.get("grade") or ""), esc(f.get("masked") or ""))
            for f in found)
        uri = _thumb_data_uri(ROOT / key)
        img = ('<img src="%s" alt="">' % uri) if uri else \
            '<div class="missing">사진 파일을 읽지 못했습니다</div>'
        cards.append("""
<section class="card" data-path="{path}">
  <header>
    <label><input type="checkbox" class="keep"> 그대로 발행 (오탐)</label>
    <span class="verdict {verdict}">{verdict}</span>
    <code>{path}</code>
  </header>
  <div class="body">
    <div class="shot">{img}</div>
    <aside>
      <ul class="hits">{hits}</ul>
      <dl>
        <dt>올린 사람</dt><dd>{nick}</dd>
        <dt>때</dt><dd>{when}</dd>
        <dt>주제</dt><dd>{title}</dd>
        <dt>OCR 줄 수</dt><dd>{lines}</dd>
      </dl>
    </aside>
  </div>
</section>""".format(
            path=esc(key), verdict=esc(v.get("verdict") or ""), img=img, hits=hits,
            nick=esc(meta.get("nickname") or "(모름)"),
            when=esc(meta.get("timestamp") or "(모름)"),
            title=esc(title_of.get(meta.get("message_id") or "") or "(모름)"),
            lines=esc(str(v.get("lines") or 0))))

    state = ("<b>지금 감추고 있습니다</b> (apply=true)" if apply_on else
             "<b>지금은 그대로 발행되고 있습니다</b> (apply=false) — "
             "아래 사진들이 멤버에게 보입니다")

    return """<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>사진 개인정보 검토 — 카톡 아카이브</title>
<style>
  :root {{ color-scheme: light dark;
    --bg:#fbf6ee; --ink:#2b2520; --soft:#6b5f54; --faint:#99887a;
    --line:#e3d9cc; --card:#fff; --warn:#b23b2e; }}
  @media (prefers-color-scheme: dark) {{ :root {{
    --bg:#241f1b; --ink:#efe6dc; --soft:#c3b5a7; --faint:#9f9081;
    --line:#3c342d; --card:#2e2823; --warn:#e8836f; }} }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; padding:24px; background:var(--bg); color:var(--ink);
    font:15px/1.6 -apple-system,"Segoe UI","Malgun Gothic",sans-serif; }}
  h1 {{ font-size:20px; margin:0 0 4px; }}
  .lede {{ color:var(--soft); max-width:70ch; margin:0 0 8px; }}
  .state {{ color:var(--warn); margin:0 0 20px; }}
  .card {{ background:var(--card); border:1px solid var(--line);
    border-radius:10px; margin:0 0 18px; overflow:hidden; }}
  .card.kept {{ opacity:.55; }}
  header {{ display:flex; gap:12px; align-items:center; flex-wrap:wrap;
    padding:10px 14px; border-bottom:1px solid var(--line); }}
  header code {{ color:var(--faint); font-size:12px; }}
  label {{ cursor:pointer; user-select:none; }}
  .verdict {{ font-size:11px; padding:2px 8px; border-radius:99px;
    border:1px solid var(--line); color:var(--soft); }}
  .verdict.hide {{ color:var(--warn); border-color:var(--warn); }}
  .body {{ display:flex; gap:16px; padding:14px; flex-wrap:wrap; }}
  .shot {{ flex:1 1 460px; min-width:0; }}
  .shot img {{ width:100%; height:auto; border:1px solid var(--line);
    border-radius:6px; display:block; }}
  .missing {{ color:var(--faint); padding:20px; border:1px dashed var(--line); }}
  aside {{ flex:0 1 300px; }}
  ul.hits {{ margin:0 0 12px; padding-left:18px; }}
  .grade {{ font-size:10px; padding:1px 6px; border-radius:99px;
    border:1px solid var(--line); color:var(--soft); }}
  dl {{ display:grid; grid-template-columns:auto 1fr; gap:2px 10px; margin:0;
    font-size:13px; }}
  dt {{ color:var(--faint); }}
  dd {{ margin:0; }}
  .foot {{ position:sticky; bottom:0; background:var(--bg);
    border-top:1px solid var(--line); padding:14px 0; margin-top:8px; }}
  button {{ font:inherit; padding:8px 14px; border-radius:8px;
    border:1px solid var(--line); background:var(--card); color:var(--ink);
    cursor:pointer; }}
  textarea {{ width:100%; height:130px; margin-top:10px; font:12px/1.5
    ui-monospace,Consolas,monospace; background:var(--card); color:var(--ink);
    border:1px solid var(--line); border-radius:8px; padding:10px; }}
</style></head><body>
<h1>사진 개인정보 검토 — 판단이 필요한 {n}장</h1>
<p class="lede">OCR 이 연락처를 찾은 사진입니다. 기관 안내문·포스터처럼 <b>공개된
연락처</b>면 '그대로 발행' 을 체크하세요. 개인 연락처면 그냥 두면 감춰집니다.
찍힌 값은 가린 형태로만 적었습니다 — 판단은 사진을 보고 하세요.</p>
<p class="state">{state}</p>
{cards}
<div class="foot">
  <button id="copy">그대로 발행할 경로 복사</button>
  <span id="msg" style="color:var(--soft)"></span>
  <textarea id="out" readonly placeholder="체크한 것이 여기에 JSON 으로 나옵니다."></textarea>
  <p class="lede" style="margin-top:10px">복사한 목록을
  <code>config/image_pii_allow.json</code> 의 <code>paths</code> 에 넣고,
  <code>apply</code> 를 <code>true</code> 로 바꾼 뒤
  <code>node scripts/upload_firestore.js</code> 를 돌리면 나머지가 감춰집니다.
  <b>그때 Storage 원본도 지워집니다 — 되돌릴 수 없습니다.</b></p>
</div>
<script>
  document.querySelectorAll(".keep").forEach(function (c) {{
    c.addEventListener("change", function () {{
      c.closest(".card").classList.toggle("kept", c.checked);
    }});
  }});
  document.getElementById("copy").onclick = function () {{
    var keep = [];
    document.querySelectorAll(".card").forEach(function (card) {{
      if (card.querySelector(".keep").checked) keep.push(card.dataset.path);
    }});
    var text = JSON.stringify(keep, null, 2);
    document.getElementById("out").value = text;
    /* 먼저 '아래 칸에 있다' 고 적어 둔다. 클립보드는 비동기이고 권한에 따라
       조용히 실패하는데, 그때 아무 말이 없으면 눌렸는지 알 수 없다. */
    var msg = document.getElementById("msg");
    msg.textContent = keep.length + "개 — 아래 칸에서 복사하세요.";
    if (navigator.clipboard) {{
      navigator.clipboard.writeText(text).then(function () {{
        msg.textContent = keep.length + "개 경로를 클립보드에 복사했습니다.";
      }}, function () {{}});
    }}
  }};
</script>
</body></html>""".format(n=len(rows), state=state, cards="".join(cards))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true",
                    help="이미 판단한 것(allowed)까지 전부 낸다")
    args = ap.parse_args()

    verdicts = jsonio.read_json(OUTPUT / "image_pii.json")
    if not verdicts:
        print("output/image_pii.json 이 없습니다 — 먼저 "
              "`powershell -File scripts/ocr_images.ps1` 와 "
              "`python -m scripts.scan_image_pii` 를 돌리세요.")
        return

    allow = scan_image_pii.load_allow_paths()
    rows = rows_to_review(verdicts, allow, args.all)
    if not rows:
        print("판단이 필요한 사진이 없습니다.")
        return

    by_asset, title_of = _context()
    OUT_HTML.write_text(
        render(rows, by_asset, title_of, scan_image_pii.hiding_enabled()),
        encoding="utf-8")
    size = OUT_HTML.stat().st_size / 1024
    print("검토표 생성: %s (%d장, %.0f KB)" % (OUT_HTML, len(rows), size))
    print("  두 번 눌러 브라우저로 열면 됩니다. 커밋 대상이 아닙니다(output/).")


if __name__ == "__main__":
    main()
