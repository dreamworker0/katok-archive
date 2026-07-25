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

### 3. 도구 설치
```bash
npm install
npm install -g firebase-tools
firebase login
```

### 4. 멤버 명부 작성
`config/members.json`에 열람을 허용할 사람을 넣는다. **여기 없는 사람은 로그인해도 못 본다.**
```json
{ "members": [
  { "email": "you@sasw.or.kr", "name": "이름", "role": "admin" },
  { "email": "member@example.org", "name": "멤버", "role": "user" }
]}
```
- `role: admin` — 원본 메시지 열람, (P2) 관리자 페이지 권한
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

## 자주 하는 작업

**멤버 추가/제거**
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

**특정 인물·키워드 제외**
`output/exclusions.json` 작성 (`output/exclusions.example.json` 참고) 후 재발행.
제외된 메시지는 발행본에 **애초에 들어가지 않으므로** 멤버도 devtools로 볼 수 없다.
```json
{ "exclude_people": ["홍길동"], "exclude_keywords": ["[제외]"], "exclude_message_ids": [] }
```

**로컬 미리보기** (로그인 없이, 배포와 무관)
```bash
python scripts/build_site.py     # site/index.html 을 브라우저로 열기
```

---

## 검증 체크리스트

배포 후 직접 확인:
1. 로그인 전 `https://katok-crawling-project.web.app` — 로그인 화면만 보이고 대화가 없다
2. 브라우저 devtools → Network → 배포된 JS에 대화 문자열이 없다
3. 명부에 **없는** 계정으로 로그인 → "접근 권한이 없습니다"
4. 명부에 **있는** 계정으로 로그인 → 5개 뷰 정상, 이미지 표시
5. 로그아웃 후 이미지 URL 직접 접근 → 403

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

## 남은 것 (다음 단계)

- **P2** 관리자 페이지 + Cloud Functions (멤버·제외를 UI로, Custom Claims)
- **P3** 온톨로지 v2 (엔티티×패턴·근거)
- **P5** 자동 수집 (Codex Computer Use)
- ⚠️ **멤버 동의 정리 후 실제 공개** — 7/23 대화방 찬반 투표·개인정보 동의 참조
