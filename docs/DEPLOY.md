# 배포 안내 (P1 — 회원 전용 아카이브)

Firebase 프로젝트: `katok-crawling-project`

## 구조 한눈에

```
[공개] Hosting     hosting/  — 앱 껍데기 61KB. 대화 데이터·이미지 없음(공개돼도 안전)
[인증] Auth        Google 로그인
[보호] Firestore   대화 전문 — members/ 명부에 있는 사람만 읽기
[보호] Storage     이미지 64장 — 멤버만 인증 요청으로 열람
```

핵심: **대화 데이터가 정적 파일로 배포되지 않는다.** 로그인하고 명부에 있는 사람에게만
Firestore에서 전송된다. `getDownloadURL`(공개 URL)을 쓰지 않고 ID 토큰을 붙인 요청으로
이미지를 받아오므로 규칙 검사를 받는다.

---

## 처음 1회 준비

### 1. Firebase 콘솔에서 확인
- **Authentication → Sign-in method → Google 사용 설정**
- **Firestore Database 만들기** (위치: `asia-northeast3` 서울 권장, 프로덕션 모드)
- **Storage 시작하기** ✅ (이미 완료)
- 권장: Blaze 요금제 — P2의 Cloud Functions에 필요. P1만이면 무료(Spark)로도 동작

### 2. 서비스 계정 키
콘솔 → 프로젝트 설정 → 서비스 계정 → **새 비공개 키 생성** →
프로젝트 루트에 `serviceAccountKey.json`으로 저장.
(`.gitignore`에 있어 커밋되지 않음. 절대 공유하지 말 것)

### 3. Storage CORS 설정 (1회, 필수)
```bash
node scripts/setup_storage_cors.js
```
Firebase Storage 는 오류 응답에는 CORS 헤더를 붙이지만 **객체 다운로드(200)에는
버킷 CORS 설정이 없으면 붙이지 않는다.** 이 설정 없이는 브라우저가 성공 응답을
차단해 이미지가 뜨지 않는다(`Failed to fetch`). 확인은 `--show`.

접근 권한과는 무관하다 — CORS 는 "어느 웹페이지가 응답을 읽을 수 있는가"만 정하고,
누가 읽을 수 있는지는 `storage.rules` 가 결정한다. 커스텀 도메인을 붙이면
`scripts/setup_storage_cors.js` 의 `ORIGINS` 에 추가하고 다시 실행한다.

### 4. 도구 설치
```bash
npm install
npm install -g firebase-tools
firebase login
```

### 5. 멤버 명부 작성
`config/members.json`에 열람을 허용할 사람을 넣는다. **여기 없는 사람은 로그인해도 못 본다.**
```json
{ "members": [
  { "email": "you@sasw.or.kr", "name": "이름", "nickname": "김종원", "role": "admin" },
  { "email": "member@example.org", "name": "멤버", "nickname": "한도윤", "role": "user" }
]}
```
- `role: admin` — 원본 메시지 열람, (P2) 관리자 페이지 권한
- `nickname` — 카톡 대화방 표시명. 발행할 때 `output/participants.json` 과 대조해
  오타·미기입을 경고한다. 첫 관리자만 손으로 넣고, 나머지는 아래 승인 절차가 채운다.
- 이 파일은 개인정보이므로 `.gitignore` 처리됨

---

## 배포 (매번 이 순서)

```bash
python -m scripts.build_firestore_payload
```
→ `firestore-payload/` 생성 + 멤버 목록이 박힌 `storage.rules` 생성.
   제외 리포트(`firestore-payload/exclusion-report.json`)로 무엇이 빠졌는지 확인.

```bash
node scripts/upload_firestore.js --dry-run
```
→ 쓰기 계획만 확인 (실제 쓰기 없음).

```bash
node scripts/upload_firestore.js
```
→ Firestore 적재 + Storage 이미지 업로드.

```bash
python -m scripts.build_hosting
firebase deploy
```
→ 규칙·Hosting 배포. 끝나면 `https://katok-crawling-project.web.app` 접속.

### 부분 배포
```bash
firebase deploy --only hosting     # 프런트만
firebase deploy --only firestore   # Firestore 규칙만
firebase deploy --only storage     # Storage 규칙만 (멤버 변경 시 필수)
```

---

## 열람 신청 · 승인

명부에 없는 사람이 로그인하면 **신청 화면**이 뜬다. 대화방 표시 이름을 적으면
`claims/{이메일}` 문서 한 장이 생기고, 관리자가 승인할 때까지 "승인 대기 중"이 보인다.

> 참여자 36명 명단을 화면에 뿌리지 않는 이유: 구글 계정만 있으면 누구나 로그인은
> 되므로, 목록을 보여주면 실명·소속이 그대로 노출된다. 그래서 본인이 직접 적게 하고
> 대조는 관리자가 로컬에서 한다. 규칙상 신청서는 **본인과 관리자만** 볼 수 있다.

```bash
node scripts/approve_claims.js
```
신청 목록을 `output/participants.json` 과 대조해 보여준다.
`○` 는 명단에 있는 이름, `×` 는 없는 이름(비슷한 후보를 함께 제시).

```bash
node scripts/approve_claims.js --approve someone@gmail.com
```
`config/members.json` 추가 → 페이로드 재생성 → Firestore 적재 → `firebase deploy --only storage`
까지 한 번에 하고 신청서를 지운다. 신청자는 새로고침하면 들어온다.

| 옵션 | 쓰임 |
|---|---|
| `--nickname "홍길동"` | 적어낸 이름이 틀렸을 때 바로잡아 승인 |
| `--role admin` | 관리자로 승인 |
| `--reject a@x.com` | 신청 삭제 |
| `--dry-run` | 파일·발행 없이 결과만 확인 |
| `--no-publish` | `members.json` 만 고치고 발행은 직접 |

**중요:** 승인은 Firestore 쓰기만으로 끝나지 않는다. `storage.rules` 에 멤버 이메일이
하드코딩돼 있어 재배포하지 않으면 **대화는 열리는데 이미지만 403** 이 된다.
위 명령은 그 재배포까지 포함한다.

신청 기능 자체는 Firestore 규칙에 의존하므로, 규칙을 먼저 배포해야 동작한다:
```bash
firebase deploy --only firestore
```

---

## 자주 하는 작업

**멤버 추가/제거** (손으로 할 때 — 보통은 위의 `approve_claims.js` 를 쓴다)
```bash
# config/members.json 수정 후
python -m scripts.build_firestore_payload
node scripts/upload_firestore.js --skip-images
firebase deploy --only storage      # ← Storage 규칙에 목록이 박혀 있어 반드시 필요
```
> Storage 규칙은 Firestore를 읽을 수 없어 P1에서는 목록을 규칙에 넣는다.
> P2에서 Custom Claims로 바꾸면 이 재배포가 없어진다.

**대화 갱신 후 재발행**
```bash
python -m scripts.build_firestore_payload
node scripts/upload_firestore.js
```

**특정 인물·키워드 제외 (발행 단계)**
`output/exclusions.json` 작성 (`output/exclusions.example.json` 참고) 후 재발행.
제외된 메시지는 발행본에 **애초에 들어가지 않으므로** 멤버도 devtools로 볼 수 없다.
```json
{ "exclude_people": ["홍길동"], "exclude_keywords": ["[제외]"], "exclude_message_ids": [] }
```

---

## 제외의 두 층

되돌릴 수 있느냐가 다르다. 헷갈리면 사고가 난다.

| | 수집 거부 | 발행 제외 |
|---|---|---|
| 설정 | `config/collection-policy.json` | `output/exclusions.json` |
| 적용 시점 | 증분 수집 (`ingest_incremental`) | 발행 (`build_firestore_payload`) |
| 원본(`messages.jsonl`) | **안 들어감** | 남음 |
| 관리자 열람 | 불가 — 존재 자체가 없음 | 가능 (`messagesSource`) |
| 되돌리기 | **불가** — 그 기간은 영영 빔 | 가능 — 설정만 되돌리면 다시 보임 |

### 글 쓸 때 `[제외]` — 가장 손이 덜 가는 방법

카톡에 글을 쓰면서 본문에 `[제외]` 를 넣으면 **그 메시지는 수집되지 않는다.**
설정 파일이 없어도 기본으로 동작하며, 전각 대괄호 `［제외］` 도 함께 받는다.

```
[홍길동] [오전 9:02] 이건 남기지 말아주세요 [제외]     → 수집 안 됨
[김철수] [오전 9:04] 그건 제외하고 봅시다              → 수집됨 (대괄호 없음)
```

수집 거부 건수는 실행 로그에 건수만 남는다. **본문은 로그에도 남기지 않는다** —
수집하지 않기로 한 글이 로그로 새면 설정의 의미가 없다.

알아둘 한계:
- **사진에는 본문이 없어** 키워드를 붙일 수 없다. 사진은 사람 단위 설정으로 다룬다.
- **소급 적용되지 않는다.** 이미 보낸 글을 내리려면 위의 '발행 제외'를 쓴다.
- 키워드가 대화방에 그대로 보인다. 명시적이라는 게 장점이자 단점이다.

사람 단위로 아예 수집하지 않으려면 `config/collection-policy.json` 을 만든다
(`config/collection-policy.example.json` 참고):
```json
{ "keywords": ["[제외]", "［제외］"], "opt_out_people": ["홍길동"] }
```
> 과거에 이미 수집된 글은 그대로 남는다. 그것까지 내리려면 `exclusions.json` 의
> `exclude_people` 에도 넣어야 한다.

### 멤버가 직접 정하는 경우

멤버는 웹에서 수집 동의를 3단계로 고르고 자기 글 삭제를 요청할 수 있다.
요청은 Firestore 에 쌓이고 **매일 23:40 자동화가 파이프라인을 다시 돌리며 반영한다.**

| 설정 | 뜻 | 반영되는 곳 |
|---|---|---|
| `public` | 기본. 수집·발행 모두 한다 | — |
| `unpublished` | 수집은 하되 발행본에서 뺀다 | `exclude_people` |
| `none` | 수집 자체를 안 한다 | `collection-policy` 의 `opt_out_people` |

```bash
node scripts/sync_member_requests.js            # Firestore → output/member-requests.json
node scripts/sync_member_requests.js --dry-run  # 내려받을 내용만 확인
```

**소유권은 반영 직전에 다시 확인한다.** 보안 규칙은 "본인 문서에만 쓴다"까지만
보장하고, 그 문서 안에 남의 메시지 ID 를 적는 것은 막지 못한다(규칙에서 다른
문서를 조회할 수 없다). 그래서 `messages.jsonl` 과 대조해 본인 글이 아닌 ID 는
버리고 발행 로그에 남긴다.

```
[요청 거부] someone@gmail.com → msg-000417 (본인 메시지가 아님)
```

`nickname` 이 없는 멤버의 요청은 어느 메시지가 그 사람 것인지 알 수 없어
반영되지 않는다 — sync 단계에서 경고가 뜨므로 `members.json` 을 채운다.

> **반영 시점 주의:** 일일 자동화는 새 메시지가 0건이면 발행을 건너뛴다.
> 그대로 두면 조용한 날 들어온 삭제 요청이 묻히므로, **요청이 바뀐 것도 발행
> 사유**로 넣었다. 급하면 아래를 직접 돌려 즉시 반영한다.
> ```bash
> node scripts/sync_member_requests.js
> python -m scripts.build_firestore_payload
> node scripts/upload_firestore.js --skip-images
> ```

---

**로컬 미리보기** (로그인 없이, 배포와 무관)
```bash
python scripts/build_site.py     # site/index.html 을 브라우저로 열기
```

---

## 검증 체크리스트

배포 후 직접 확인:
1. 로그인 전 `https://katok-crawling-project.web.app` — 로그인 화면만 보이고 대화가 없다
2. 브라우저 devtools → Network → 배포된 JS에 대화 문자열이 없다
3. 명부에 **없는** 계정으로 로그인 → 열람 신청 화면 (참여자 명단이 보이지 않아야 한다)
4. 신청 후 새로고침 → "승인 대기 중"
5. `node scripts/approve_claims.js` 로 신청이 보이고, 명단 대조 표시가 맞다
6. 승인 후 신청자가 새로고침 → 5개 뷰 정상, **이미지까지** 표시
7. 로그아웃 후 이미지 URL 직접 접근 → 403

---

## 비용

P1 기준 무료 티어 내:
- **Firestore 읽기: 멤버 1명이 전체를 볼 때 33회**
  (meta 1 + 청크 16 + 스레드 1 + 요지 12 + 그래프 2 + 본인 멤버 문서 1)
  - 메시지를 문서당 1건씩 두면 1,509회 → 100건씩 묶어 16회
  - 스레드도 165개 문서 대신 1문서로 묶음(60KB) → 165회 절약
  - 무료 한도 일 5만 회 → 멤버 36명이 하루 40회 이상 열어도 여유
- 적재 쓰기: 1,542건(1회성). 무료 한도 일 2만 회
- Storage: 이미지 41MB, 지연 로딩(화면에 들어올 때만) — 무료 한도 일 1GB 전송
- Hosting: 61KB

## 문제 해결

**이미지가 안 보이고 콘솔에 `Failed to fetch`**
→ 버킷 CORS 설정 누락. `node scripts/setup_storage_cors.js` 실행.
   원인: 성공 응답(200)에 `Access-Control-Allow-Origin` 이 없어 브라우저가 차단.

**로그인 시 `auth/configuration-not-found`**
→ 콘솔에서 Authentication 을 활성화하고 Google 공급자를 켠다.

**"접근 권한이 없습니다"**
→ 로그인한 이메일이 `config/members.json` 에 없다. 추가 후 재발행·재배포.

**승인했는데 이미지만 안 보인다**
→ `storage.rules` 재배포 누락. `firebase deploy --only storage`.
   `approve_claims.js` 를 `--no-publish` 로 돌렸을 때 잘 생긴다.

**신청 화면에서 "신청을 보내지 못했습니다"**
→ `claims/` 규칙이 아직 배포되지 않았다. `firebase deploy --only firestore`.

**진단 도구** (브라우저 콘솔)
```javascript
ArchiveImages.diagnose()   // {mode, total, loaded, failed, waiting, lastError}
```

## 남은 것 (다음 단계)

- **P2** 관리자 페이지 + Cloud Functions (멤버·제외를 UI로, Custom Claims)
- **P3** 온톨로지 v2 (엔티티×패턴·근거)
- **P5** 자동 수집 (Codex Computer Use)
- ⚠️ **멤버 동의 정리 후 실제 공개** — 7/23 대화방 찬반 투표·개인정보 동의 참조
