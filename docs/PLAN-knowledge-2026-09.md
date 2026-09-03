# 계획서 — 주제별 지식 구조 최적화 (2026-09-04)

- 상태: **계획. 아래 "오퍼스에게 줄 프롬프트" 절을 그대로 새 세션에 붙여 실행한다.**
- 근거: 2026-09-04 저장소 실측(아래 0장), [PLAN-v3.md](PLAN-v3.md) 5장(온톨로지 v2), [REPORT-RULES.md](REPORT-RULES.md)
- 이 문서에는 방 사람의 실명을 적지 않는다. 주제는 id(`t-xxx`)로만 가리킨다. 저장소는 공개다.

---

## 0. 실측 — 지금 어디에 서 있나

| 층 | 지금 | 비고 |
|---|---|---|
| 원장 | 메시지 3,146 · 주제 405 · 보고서 405 · AI 주석 274 | 2025-08-20 ~ 2026-09-03 |
| 주 분류 | 12개, 평평함. projects 106 · ai-tools 50 · events 40 · ai-models 32 · infra 30 · news-articles 27 · welfare-practice 27 · members 26 · community 21 · governance 19 · chat 15 · hwp 12 | '한 주제 = 한 분류' 가 통계·증분 적재의 전제 |
| 상위 묶음 | 4개(`ontology.CATEGORY_GROUPS`) — **관심 분야 계산에만** 쓰이고 화면 내비게이션에는 없음 | |
| 보조 분류 | 173 / 405 (43%) — 매일 밤 새 주제만 자동 | 정상 |
| 요지 산문 | 12편, **마지막 갱신 2026-07-28** (그때 주제 346). 그 뒤 59개(+17%), 가장 활발한 8월(68개)이 통째로 빠져 있음 | `docs/AUTOMATION.md` 가 "사람이 한다" 로 남겨 둔 자리. **첫 화면**이다 |
| 요지 구조 | 분류마다 headline + overview 한 문단(~500자) + keywords. projects 는 한 문단이 106개 주제를 덮는다 | 절(section) 없음, 정리 시점(as_of) 없음 |
| 갈래 태그 | `config/tag_broader.json` 에 '앱 제작' 7갈래(업무 앱·당사자 지원 앱·실천 도구·문서 처리 도구·커뮤니티 웹·게임 제작·개발 보조 도구)가 이미 있음. projects 106개 중 **65개만** 갈래 태그가 있고 41개는 없음 | 태그 화면에서만 살고 요지 화면과 이어지지 않음 |
| 형식 분류 | news-articles 27 · chat 15. 표본을 읽으면 절반 이상이 실제 주제(모델 장애·클라우드 리전·AI 리터러시 논문·보안 사고)를 가진 대화다 | 2026-08-21 에 태그 '링크 공유'를 거둔 것과 같은 병 — **행위·형식이 주제 자리를 차지** |
| 태그 | 1,481개 · 347종 · 1회짜리 186종(54%) · 어휘 167종 · 어휘 밖 205개(14%) · 고립 35 | 2026-08-21 대수술 뒤 안정. 잔여만 남음 |
| 관계망 | 245노드 · 560엣지 · **근거(evidence) 0** · 차수 1 노드 70 | PLAN-v3 P3(근거·엔티티×패턴) 미착수 |

## 1. 진단 — 무엇이 병목인가 (우선순위 순)

1. **첫 화면이 5주 전에 멈춰 있다.** 요지 산문은 사람이 쓰는 글로 남겨 두었고, 그 결과 8월 대화가 첫 화면에 없다. 분류·태그·보조 분류·AI 주석은 전부 밤마다 자동인데 요지만 예외다. 구조 문제라기보다 **갱신 체계가 없는 것**이 문제다.
2. **projects 가 한 덩어리다.** 106개 주제를 한 문단·한 목록으로 보인다. 태그 쪽에는 이미 7갈래가 있으니 새 분류를 만들 일이 아니라 **있는 갈래를 요지 화면과 산문에 잇는 일**이다. 다만 41개가 갈래 태그가 없어 먼저 채워야 한다.
3. **형식 분류가 주제를 감춘다.** '뉴스·자료 공유'에 들어간 AI 리터러시 논문은 '복지 실천' 요지에서 찾을 수 없다. 옮기면 그 분류의 요지가 정확해진다.
4. **12분류 평평한 내비게이션.** 상위 묶음 4개가 이미 코드에 있는데 화면이 안 쓴다. 작은 일이다.
5. 태그 잔여(고립 35)·관계망 근거는 이번 범위에서 **뒤로** 미룬다(아래 2장).

## 2. 범위

**한다**
- 요지 산문 자동 갱신 체계(규칙 원본 한 곳 + 스크립트 + 밤 단계 + 정리 시점 표기) 및 12편 전면 재작성
- projects 갈래 채우기(41개) → 요지 화면의 소속 주제를 갈래로 묶어 보이기 → 요지 산문의 절도 갈래로
- news-articles·chat 감사(제안 → 사람 검토 → 적용). 분류 id 는 없애지 않는다
- 요지 화면 내비게이션을 상위 묶음으로
- 문서 갱신(AUTOMATION·REPORT-RULES·README)

**안 한다 (이유)**
- 분류 체계 재설계(12개를 갈아엎기) — 통계 합계·증분 적재·digests 문서 키가 전부 분류 id 위에 서 있다. 얻는 것보다 깨지는 것이 많다
- 관계망 근거(evidence)·엔티티×패턴 — PLAN-v3 P3 그대로 별도 계획. 엣지 473개 중 33%만 원문 근거가 있어 한 번에 될 일이 아니다
- 보고서 본문 재작성 — 방장 결정(기존 보고서는 손대지 않는다). 태그 줄만 예외
- 분류 id 삭제(news-articles 가 작아져도) — 이번엔 남은 개수만 보고

## 3. 단계와 검수 기준

| 단계 | 일 | LLM | 끝난 기준 | 멈춤 |
|---|---|---|---|---|
| 0 | 실측·기준선 보고 | 없음 | 위 0장의 숫자를 다시 재어 보고 | — |
| 1 | 형식 분류 감사 제안서 | opus 1~2회 (~$1) | `output/recat-proposal-YYYYMMDD.{json,md}` — 옮길 주제·목적지·한 줄 이유 | **멈춤 ①** 사람이 제안서 검토 |
| 1′ | 승인된 것만 적용 | 없음 | topics.json 분류 이동 + 옛 분류를 보조 분류로 + 백업 | — |
| 2 | projects 갈래 채우기 | opus 1~2회 (~$1) | 갈래 없는 주제 41 → 5 이하. 백업 | — |
| 3 | 요지 산문 체계 + 12편 재작성 | **fable 권장** 12회 (~$8~12) | 12편 모두 `as_of` = 오늘, 큰 분류는 절 있음, 이어지지 않는 요지 태그 0 | — |
| 4 | 화면(묶음 nav·갈래 목록·절·정리 시점) | 없음 | 8화면 × 데스크톱/모바일 확인, 숫자 합 일치 | — |
| 5 | 태그 잔여(선택) | opus 1회 | 고립 35 제안서만 | — |
| 6 | 발행본 → 테스트 → 보고 | 없음 | 858+ 검사·node 검사·ruff 통과, 크기 경고 0 | **멈춤 ②** 적재·배포 승인 |
| 6′ | 적재 + 호스팅 배포 | 없음 | Firestore 요청 수·캐시 지문 확인 | — |

---

## 4. 오퍼스에게 줄 프롬프트

> 아래 가로줄 사이를 그대로 붙인다. 모델은 Opus. 3단계의 요지 산문 생성은 스크립트 안에서 `claude -p --model fable` 로 부르게 되어 있다 — 그 12회만 상위 모델을 쓴다.

---

당신은 `D:\apps\카톡데이터크롤링` 저장소에서 **주제별 지식 구조 최적화** 작업을 맡았다. 계획서는 `docs/PLAN-knowledge-2026-09.md` 다 — 먼저 통째로 읽고, 0~3장의 진단과 범위를 전제로 4장(이 프롬프트)을 수행한다. 계획서의 범위를 넘는 일이 필요해지면 **먼저 알리고 되돌릴 대안을 함께 제시**한 뒤에 한다(이유 · 안 하면 무엇이 깨지나 · 대안, 셋을 묶어서).

### 이 저장소에서 지키는 것 (예외 없음)

1. **원장과 보고서 본문은 고치지 않는다.** `output/messages.jsonl`, `output/reports/*.md` 의 본문·제목·요지는 손대지 않는다. 보고서에서 고칠 수 있는 것은 `keywords:` **한 줄**뿐이고, 그때도 `scripts/tag_surgery.py` 의 골격(백업 → `replace_keywords_line` 제자리 치환)을 쓴다. 이 폴더는 CRLF 다. 파일을 다시 렌더하면 diff 가 405편으로 번진다.
2. **규칙 원본은 한 곳.** 보고서 규칙이 `scripts/topic_reports.REPORT_RULES` 하나인 것과 같은 이유로, 요지 산문 규칙도 `topic_reports.DIGEST_RULES` 하나에 두고 프롬프트와 검사가 그것을 읽는다. 문서(`docs/REPORT-RULES.md`)에는 규칙 문장을 옮겨 적지 말고 코드를 가리킨다. 규칙 글에 숫자가 들어가면 그 숫자는 상수에서 f-string 으로 받는다 — 글과 검사가 다른 숫자를 보면 규칙이 취향이 된다.
3. **두 단계: 제안 → 적용.** 원장(`topics.json`·`secondary_categories.json`)이나 보고서 태그 줄을 바꾸는 일은 먼저 `output/*-proposal-YYYYMMDD.json`(+ 사람이 읽을 `.md`)을 쓰고, `--apply` 가 그 파일을 읽어 적용한다. 적용 직전에 `output/backup-<일이름>-YYYYMMDD/` 에 원본을 복사한다. 제안 파일에는 모델 답 원본도 남긴다(`retag_reports` 의 `replies` 처럼) — 걸러내는 규칙을 고칠 때 다시 묻지 않게.
4. **실명 금지.** 저장소는 공개다. `scripts/`·`tests/`·`docs/`·`config/` 에 커밋되는 파일에는 방 사람의 이름·닉네임을 쓰지 않는다. 검사 자료가 필요하면 가짜 이름을 만든다. 제안서·백업은 `output/` 아래(전부 gitignore)에만 둔다. 커밋 전에 `git diff --cached` 를 훑어 이름이 없는지 본다.
5. **LLM 은 실패해도 된다.** `scripts/llm.call_claude` 는 실패하면 `None` 을 돌려준다. 새 단계도 같은 규칙 — 밤 갱신에서 요지 갱신이 실패하면 그 일만 건너뛰고 나아가야 한다. `run_daily.ps1` 에서 `Invoke-Step`(실패 시 중단)이 아니라 분류(`classify_unsorted`)와 같은 꼴로 붙인다.
6. **화면을 바꾸면 8화면 × 양쪽 폭.** summary·timeline·graph·gallery·files·stats·mine·admin 을 데스크톱과 모바일(760px 경계) 양쪽에서 본다. 바꾼 화면만 보고 "된다" 고 하지 않는다. 스크립트 목록이 여섯 곳(index.html 둘·sw.js·build_hosting·build_site·test_ui_contract)에서 함께 움직이니 새 js 파일을 만들면 전부 고친다(가능하면 새 파일을 만들지 말고 `web/summary.js` 안에서 끝낸다). 로컬 미리보기(`python -m scripts.serve_hosting`)는 `/summary` 같은 경로 주소가 404 라 **루트로 들어가 탭을 누른다**.
7. **발행 순서는 발행본 → 테스트 → 적재.** `python -m scripts.build_firestore_payload` → `python -m unittest discover -s tests` + `npm test` + `ruff check .` → (승인 뒤) `node scripts/upload_firestore.js` → 화면이 바뀌었으면 `python -m scripts.build_hosting && ./node_modules/.bin/firebase deploy --only hosting --project katok-crawling-project` (`firebase` 는 PATH 에 없고 `node_modules/.bin` 에 있다. 한 번 배포하면 두 사이트가 함께 바뀐다). 요지 문서는 `meta.content_hash` 에 들어가므로 적재하면 화면 캐시가 스스로 갈아탄다 — 캐시 코드를 건드릴 일은 없다.
8. **콘솔은 cp949 다.** 파이썬 한 줄 스크립트를 돌릴 때 `$env:PYTHONIOENCODING='utf-8'`(PowerShell) 을 먼저 둔다. 안 그러면 한글 라벨이 깨지고 `—` 에서 예외가 난다.
9. **커밋은 단계마다.** 메시지는 이 저장소의 꼴을 따른다 — `type(scope): 무엇을 했다 — 왜/실측`. 한국어. 마지막 줄 `Co-Authored-By: Claude Opus <noreply@anthropic.com>`. 스크립트·검사·문서를 한 커밋에 묶는다. `output/` 은 커밋되지 않는다(전부 gitignore) — 데이터 변화는 커밋이 아니라 **적재**로 나간다.
10. 단계를 시작할 때 "지금 N단계, 하는 일은 ○○" 한 줄, 끝날 때 숫자로 된 결과 한 줄. 끝에 전체 표(전/후)를 낸다.

### 0단계 — 실측 (호출 없음)

계획서 0장의 숫자를 지금 시점으로 다시 잰다: 메시지·주제·보고서·AI 주석 수, 분류 분포, 요지 산문 파일의 mtime 과 정리 시점 이후 늘어난 주제 수(분류별), projects 중 갈래 태그가 있는 주제 수(`config/tag_broader.json` 의 '앱 제작' 자식들을 `tags.fold` 로 맞춘다. 자식의 자식까지), 태그 수치(`python -m scripts.retag_reports --stats`, `python -m scripts.adopt_orphans --stats`), 보조 분류 수. 계획서와 크게 다르면(주제 ±10 이상, 갈래 없는 projects ±10 이상) 이유를 적고 계속한다. 이 숫자가 마지막 보고의 '전' 열이다.

### 1단계 — 형식 분류 감사 (제안서까지, 그리고 멈춤 ①)

**목적**: `news-articles`(뉴스·자료 공유)·`chat`(일상·잡담)에 든 주제 가운데 **실제 주제가 있는 것**을 그 주제의 분류로 옮긴다. 근거는 2026-08-21 에 태그 '링크 공유'를 거둔 판단과 같다 — 링크를 공유했다는 사실은 화면이 자료로 이미 안다. 분류가 할 일은 '무엇을 이야기했나' 다.

**새 스크립트** `scripts/audit_form_categories.py` (docstring 은 이 저장소의 다른 스크립트처럼 '왜 이 파일이 있나 / 무엇을 고치고 무엇을 안 고치나 / 사용' 세 절로):
- 대상: `category in {"news-articles", "chat"}` 인 주제 전부(지금 42개). 각 주제의 제목·요지·보고서 본문(`topic_reports.load_reports`)·태그·보조 분류를 프롬프트에 싣는다. 원문 메시지는 싣지 않는다 — 보고서가 발행 단위고, 보고서로 판단이 안 서면 옮기지 않는다.
- 판정 규칙(프롬프트에 그대로): 옮기는 것은 **보고서가 다른 분류의 정의에 분명히 드는 주제 하나를 다룰 때만**. 뉴스를 여러 건 늘어놓은 것, 인사·안부·잡담이 본체인 것, 두 분류에 반씩 걸친 것은 **그대로 둔다**. 목적지는 12개 id 중 하나이고 `news-articles`·`chat` 으로는 옮기지 않는다. 한 줄 이유를 쓰게 한다. `chat` 은 `ontology.PROVISIONAL_CATEGORIES` 에 있는 '아직 정해지지 않은 자리' 이므로 기준을 같게 두되, 진짜 잡담은 남는 것이 맞다.
- 제안 파일 `output/recat-proposal-YYYYMMDD.json`: `{ "asked": [...ids], "moves": [{"id","from","to","reason"}], "kept": [{"id","reason"}], "replies": [...] }`. 사람이 읽을 `output/recat-proposal-YYYYMMDD.md` 도 함께 — 표 한 장(id · 지금 제목 · from → to · 이유), 옮기는 것과 두는 것을 나눠서.
- `--apply`: 제안 파일을 읽어 `output/topics.json` 의 category 를 바꾼다. 옛 분류는 `output/secondary_categories.json` 에 **보조 분류로 덧붙인다**(이미 목적지가 보조에 있으면 그 항목은 지운다 — 주 분류와 보조가 같으면 안 된다. `assign_secondary.MAX_PER_THREAD`=2 를 넘으면 덧붙이지 않고 로그만). 적용 전 `output/backup-recat-YYYYMMDD/` 에 두 파일을 복사한다. `--only t-xxx,t-yyy` 로 일부만 적용할 수 있게 한다(사람이 몇 개를 기각할 것이다). `knowledge.json` 은 건드리지 않는다 — `topic:<분류>` 노드 값은 `build_site.weigh_knowledge` 가 발행 때 다시 센다.
- 검사 `tests/test_audit_form_categories.py`: 가짜 주제 4~5개로 (a) 제안에 없는 id 는 안 움직인다 (b) 목적지가 12개 밖이면 거부 (c) 옛 분류가 보조로 붙고 중복은 지워진다 (d) 두 번 적용해도 같다 (e) 백업 폴더가 생긴다. 이름은 전부 가짜.
- `output/` 의 `secondary_categories.json` 은 `asked` 목록으로 재판정을 막는다 — 옮긴 주제는 `asked` 에 이미 있으니 밤 5b 단계가 다시 묻지 않는다. 확인만 한다.

**멈춤 ①**: 제안서(`.md`)의 표를 대화에 그대로 보이고 멈춘다. "적용" · "t-xxx 는 빼고 적용" · "전부 기각" 가운데 답을 받은 뒤 `--apply --only ...` 로 적용한다. 적용 결과(분류별 증감)를 한 줄로 적는다. 승인을 받기 전에는 2단계로 가지 않는다 — 요지 산문은 분류가 정해진 뒤에 써야 한다.

### 2단계 — projects 갈래 채우기

**목적**: projects 주제 가운데 갈래 태그('앱 제작' 의 자식: 업무 앱 · 당사자 지원 앱 · 실천 도구 · 문서 처리 도구 · 커뮤니티 웹 · 게임 제작 · 개발 보조 도구)가 하나도 없는 41개에 갈래 하나를 붙인다. 3단계의 절과 4단계의 목록이 이 갈래로 묶이므로 먼저 한다.

**방법**: `scripts/split_tag.py` 에 `--fill-category projects` 모드를 더한다(새 파일을 만들지 않는다 — 같은 `split_hints` 와 같은 프롬프트 골격을 쓰는 일이다). 대상은 '그 분류에 속하고 갈래 태그(자식의 자식까지 `tags.fold` 로 맞춤)가 없는 주제'. 갈래 설명은 `config/tag_broader.json` 의 `split_hints["앱 제작"]` 를 그대로 싣는다. 모델이 '어느 갈래도 아님' 을 고를 수 있게 하고, 그때는 붙이지 않는다 — 협업 경험담·구상만 있는 대화는 갈래가 없는 것이 맞다.
- 적용: 태그가 6개 미만이면 갈래를 **덧붙인다**. 6개면 어휘 밖(`tags.vocabulary()` 에 없는) 1회짜리 태그 하나를 갈래로 **바꾸고**, 그런 태그가 없으면 건너뛰고 로그. 백업 `output/backup-facet-YYYYMMDD/`.
- 이 일이 2026-08-21 의 `adopt_orphans` 사고(갈래를 붙였더니 초대·논문 대화가 '앱 제작' 으로 끌려온 것)를 되풀이하지 않는 이유는 대상이 **이미 projects 인 주제**라서다. docstring 에 그 판단을 적는다.
- 검사: `tests/test_split_tag.py` 에 fill 모드 3개 — 갈래 있는 주제는 대상이 아니다 / 6개일 때 어휘 밖 1회짜리만 바뀐다 / '아님' 은 건너뛴다.
- 끝난 기준: 갈래 없는 projects 주제 41 → **5 이하**. 그 이상 남으면 남은 id 와 모델의 이유를 보고서에 적는다(억지로 채우지 않는다).

### 3단계 — 요지 산문 자동 갱신 체계 + 12편 재작성

**목적**: 요지 산문을 사람 손에서 떼어 밤 갱신에 붙이되, 매일 12편을 다시 쓰지 않고 **낡은 분류만** 다시 쓴다. 규칙 원본은 한 곳, 정리 시점은 데이터에 남기고 화면에 보인다.

**규칙 원본** — `scripts/topic_reports.py` 에 추가:
```
DIGEST_SECTION_FROM = 20        # 소속 주제 20개 이상이면 절을 나눈다
DIGEST_STALE_THREADS = 5        # 정리 뒤 새 주제가 이만큼 쌓이면 낡은 것
DIGEST_STALE_DAYS = 30          # 또는 이만큼 지났고 새 주제가 하나라도 있으면
DIGEST_OVERVIEW_MAX = 600       # overview 글자 상한
DIGEST_KEYWORDS = (4, 8)
DIGEST_RULES = f"""..."""       # 아래 내용을 이 상수들로 f-string
```
규칙 문장에 들어갈 것: 사실만(주제 보고서에 없는 것을 채우지 않는다) · headline 은 40자 이내 한 줄 · overview 는 이 분류가 무엇을 이야기하는 방인지 처음 온 사람에게 하는 말로, 흐름(무엇이 반복 화두였고 무엇으로 이어졌나)을 담고 `DIGEST_OVERVIEW_MAX` 자 이내 · 소속 주제 `DIGEST_SECTION_FROM` 개 이상이면 `sections` 로 나누되 절 제목은 **주어진 갈래 이름을 그대로** 쓰고 갈래가 없는 분류는 시기·화두로 나눈다 · 한 절은 3~6문장 · keywords 는 **주어진 어휘에서만** `DIGEST_KEYWORDS` 개(어휘 밖은 검사에서 버린다) · 사람 이름은 주어로 써도 되나 평가하는 말은 쓰지 않는다 · 인용은 하지 않는다(요지는 보고서의 요약이고 보고서가 이미 원문의 요약이다).

**새 스크립트** `scripts/digest_prose.py`:
- `select_stale(categories, threads, prose, today)` → 다시 쓸 분류 목록. 기준은 위 두 상수. `as_of` 가 없는 분류는 낡은 것으로 본다(지금 12편 전부).
- `build_digest_prompt(cat, threads, reports, facets, vocabulary)` → 프롬프트. 싣는 것: 분류 라벨과 그 정의(12개 라벨 전체를 보여 이 분류의 자리를 알게), 소속 주제 전부의 `id · 날짜 · 제목 · 요지 · 태그 · 갈래`, 각 보고서 본문(있으면), 보조 분류로 걸린 곁 주제의 제목만(참고용, 본문에 쓰지 말라고 명시), 갈래 이름 목록(`ontology.CATEGORY_FACETS`, 아래 4단계), 어휘(`tags.vocabulary()` + `tag_broader` 부모들), 그리고 `DIGEST_RULES`. 원문 메시지는 싣지 않는다. projects 는 보고서 106편 ≈ 45KB 라 한 호출에 들어간다 — 들어가지 않는 분류가 생기면 보고서를 요지 한 줄로 대신하고 로그에 적는다.
- `validate(obj, vocabulary, thread_count)` → headline/overview 길이, sections 유무(기준 이상이면 필수), keywords 어휘 밖 제거, 빈 값 거부. 어긴 것은 그 분류만 버리고 옛 글을 남긴다(보고서 `[규칙 미달]` 로그와 같은 꼴).
- 출력 형식: `output/topic-digests.json` 의 `digests[cat]` 에 `headline · overview · sections: [{title, body}] · keywords · as_of: {date, thread_count, last_thread_id}`. 기존 키 이름은 그대로(화면·검사가 읽는다). `ensure_ascii=False, indent=2`. 바뀐 분류만 쓰고, 쓰기 전에 `output/backup-digests-YYYYMMDD/` 로 복사.
- CLI: `--all`(전부) · `--cat projects` · `--limit 3`(하룻밤 상한, 기본 3) · `--dry-run`(프롬프트만 만들고 부르지 않는다 — LLM 을 먼저 부르고 결과만 버리는 dry-run 은 이 저장소에서 결함으로 기록된 꼴이다) · `--model`(기본 `llm.DEFAULT_MODEL`).
- 발행 경고: `build_site.build_digests` 가 분류마다 `as_of` 와 지금 주제 수를 견줘 낡았으면 `[요지] <분류>: 정리 뒤 주제 +N (as_of 날짜)` 한 줄을 찍는다. `warnlog` 가 달라진 것만 남기므로 매일 같은 줄이 쌓이지 않는다. `as_of` 가 없으면 `[요지] <분류>: 정리 시점 없음`.
- 화면으로 내려보내는 것: `build_digests` 결과에 `sections` 와 `as_of` 를 실어 보낸다. `pii.mask_tree(data["digests"])` 가 트리 전체를 가리므로 따로 할 일은 없지만, `build_firestore_payload.plan_documents` 의 크기 경고(`digests/{분류}` 80%)를 실행 뒤 확인한다.
- `run_daily.ps1`: 5b(보조 분류) 뒤에 **5c '요지 산문 갱신'** — `python -m scripts.digest_prose`(기본 = 낡은 것만, `--limit 3`). 분류 단계와 같은 try/catch 꼴, 실패는 로그만. `publish_state.WATCHED` 에 `topic-digests.json` 은 이미 있다 — 확인만.
- 검사 `tests/test_digest_prose.py`: (a) 프롬프트에 `DIGEST_RULES` 가 그대로 들어 있다 (b) `select_stale` 두 기준 (c) `validate` 가 어휘 밖 keywords 를 버리고 절 없는 큰 분류를 거부한다 (d) `--dry-run` 이 `call_claude` 를 부르지 않는다 (mock) (e) 바뀐 분류만 쓰고 나머지 바이트는 같다. `tests/test_report_rules.py` 에 '규칙 숫자와 검사가 같은 상수를 본다' 한 개. `tests/test_build_site.py` 에 '발행 digests 마다 `as_of` 가 있다' 한 개 — 이 검사는 12편을 다시 쓴 뒤에 통과한다.
- 문서: `docs/REPORT-RULES.md` 에 '요지 산문 규칙' 절(규칙 문장은 옮기지 않고 상수와 스크립트를 가리킨다, 왜 낡은 것만 다시 쓰는지). `docs/AUTOMATION.md` 의 "요지 산문은 여전히 사람이 한다"(약 38행), '자동 아님' 표(약 516행), 손 절차(약 635행) 세 곳을 고친다. `README.md` 파이프라인 그림에 요지 갱신 한 줄.

**12편 재작성**: 체계가 검사를 통과하면 `python -m scripts.digest_prose --all --model fable` 로 12편을 쓴다(이 호출만 상위 모델 — 아카이브 전체를 요약하는 산문이라 판단이 글의 질이 된다. 편당 약 $0.7~1, 합 $8~12 로 어림. 사용자가 비용을 이미 허용했다). 끝나면 `python -m scripts.build_site` 를 돌려 `[요지 태그] 어느 주제와도 이어지지 않아 화면에서 뺀` 경고가 **0** 인지, `[요지]` 낡음 경고가 0 인지 본다. 12편의 headline 과 절 제목만 대화에 보인다(overview 전체는 길다).

### 4단계 — 화면

**데이터 쪽** (`scripts/ontology.py`): `CATEGORY_FACETS = {"projects": "앱 제작"}` 를 `CATEGORY_GROUPS` 옆에 둔다(분류 → 갈래를 자식으로 가진 부모 태그). docstring 에 '왜 projects 만인가' 를 적는다 — ai-tools 는 갈래가 도구 이름 24개라 묶음이 아니라 목록이고, 다른 분류는 20개 미만이다. `build_site.build_digests` 가 분류마다 `facets: [{"label", "thread_ids"}]` 를 만든다: 소속 주제(`threads_by_cat`)를 갈래 자식(자식의 자식까지, `taglib.fold` 로) 으로 나눈다. 한 주제는 **딱 한 갈래** — 여럿에 걸리면 `split_hints` 순서에서 앞선 것. 어느 갈래도 아니면 마지막 '그 밖'. 검사(`tests/test_build_site.py`): 갈래 thread_ids 의 합 = 소속 주제 수, 겹침 0, '그 밖' 이 마지막.

**화면 쪽** (`web/summary.js` 만):
- 상단 `cat-nav`: 12개 평평한 줄 → `CATEGORY_GROUPS` 4묶음(만들기·기술 / AI 도구·모델 / 실천·제도 / 모임·나눔) 아래 분류, 묶음 없는 `chat` 은 끝에. 묶음 라벨은 발행 데이터에서 읽는다(`ontology.CATEGORY_GROUPS` 를 `build_data` 가 `groups` 로 내려보낸다. 화면에 하드코딩하지 않는다 — 온톨로지 원본이 한 곳인 이유와 같다).
- 카드 본문 `overview` 아래에 `sections` 를 `h3 + p` 로. 없으면 지금과 같다.
- `doc-meta` 에 정리 시점: "N개 메시지 · M개 주제 · 정리 2026-09-04". `as_of.thread_count` 보다 지금 주제가 많으면 "· 그 뒤 +k" 를 덧붙인다(낡음이 화면에서 보이면 사람이 안다).
- 소속 대화 주제 목록: `d.facets` 가 있으면 갈래별 소제목(`업무 앱 · 20`)으로 묶는다. 갈래마다 지금의 '10개 + 더보기' 규칙을 그대로 적용하지 말고, **갈래가 있으면 갈래 자체가 접힘 단위**다(모바일은 전부 접힘, 데스크톱은 열림. 지금 `.more-fold` 와 같은 요소를 쓴다). '그 밖' 이 마지막. 갈래가 없는 분류는 지금 그대로.
- 확인: `python -m scripts.build_site` → `python -m scripts.serve_hosting`(루트로 들어간다) → 8화면 × 데스크톱(≥1100px)/모바일(≤760px). 요지 화면에서 (1) 묶음 nav 에 12개 전부 (2) projects 갈래 합이 카드 우상단 주제 수와 같다 (3) 정리 시점이 오늘 (4) 절이 보인다. 다른 7화면은 깨진 것이 없는지만. `tests/test_ui_contract.py` 는 새 화면 id 를 만들지 않았으니 건드릴 것이 없어야 한다 — 실패하면 무엇을 요구하는지 읽고 맞춘다.

### 5단계 — 태그 잔여 (선택, 시간이 남으면)

`python -m scripts.adopt_orphans` 로 고립 35개의 부모 제안을 만들고 **제안서만** 보인다. 표에 적는 것은 사람 판단이라 적용하지 않는다(2026-08-21 에 여섯 개가 잘못 붙은 전례). `python -m scripts.retag_reports --stats` 숫자를 '후' 열에 넣는다.

### 6단계 — 발행본 · 테스트 · 보고 (멈춤 ②) · 적재 · 배포

1. `python -m scripts.build_firestore_payload` — `[주의]` 줄 전부 옮겨 적는다(크기·요지·태그).
2. `python -m unittest discover -s tests` (858개 + 새 검사), `npm test`, `ruff check .` — 셋 다 통과. 실패는 원인을 고친다. 검사가 나쁜 것이 아니라면 검사를 고치지 않는다.
3. 전/후 표를 낸다:

   | 항목 | 전(0단계) | 후 |
   |---|---|---|
   | 요지 12편 정리 시점 · as_of 없는 편 | | |
   | projects 갈래 없는 주제 | 41 | |
   | news-articles / chat 주제 수 | 27 / 15 | |
   | 옮긴 주제 수 (분류별 증감) | — | |
   | 요지 태그 중 이어지지 않아 뺀 것 | | 0 |
   | 태그 종 / 1회짜리 / 고립 | 347 / 186 / 35 | |
   | 검사 수 · 통과 | 858 | |
   | 커밋 | — | 해시 목록 |

   그리고 범위 밖으로 손댄 곳(있으면)과 되돌리는 법, 판단이 애매해 사람이 봐야 할 것(예: 갈래를 못 받은 projects 주제, 기각한 이동)을 적는다. **여기서 멈춘다.**
4. 승인이 오면: `node scripts/upload_firestore.js` → `python -m scripts.build_hosting && ./node_modules/.bin/firebase deploy --only hosting --project katok-crawling-project`. 적재 로그의 문서 수·`cacheHashWarning` 없음을 확인하고 끝낸다. 배포 뒤 사이트를 한 번 열어 요지 화면이 새 정리 시점을 보이는지 본다(캐시는 `content_hash` 가 바뀌어 스스로 갈아탄다).

### 비용·모델 안내 (사용자에게 말할 것)

- 1·2단계의 판정, 5단계 제안: 스크립트 기본 모델(opus), 합 $3 안팎.
- 3단계 12편: `--model fable`, $8~12 어림. 스크립트가 다 만들어진 뒤 이 한 번만.
- 밤 갱신에 붙인 요지 단계는 낡은 분류가 있을 때만 돌고 하룻밤 3편 상한이라 대개 $0, 많아야 $1~2.

---

## 5. 이 계획이 끝나면 남는 것 (다음 계획서 후보)

- 관계망 근거(evidence) — PLAN-v3 P3. 엣지에 `evidence: [message_ids]`, 노드에 `threads`. `build_digests.threads_matching` 이 이미 앱→주제를 잇고 있으니 그것을 발행 데이터가 아니라 원장에 남기는 것부터.
- `news-articles` 가 작아졌으면 분류 id 를 거둘지 결정(digests 문서 키·통계 색·Firestore 문서 삭제까지 함께).
- ai-tools 50개의 묶음 — 도구 이름이 아니라 '무엇을 하려 했나'(설치·요금·비교·워크플로) 축이 필요하다. 갈래 표가 먼저다.
