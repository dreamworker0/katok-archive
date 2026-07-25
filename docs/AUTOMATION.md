# 일일 갱신 자동화 (P5)

카카오톡 대화를 내보내 아카이브에 반영하고 Firestore 에 발행하기까지를 자동화한다.

## 한 줄 요약

```powershell
powershell -File scripts\run_daily.ps1 -SkipExport
```
`inbox\` 에 내보낸 txt 를 두고 위 명령을 실행하면 증분 반영 → 발행본 생성 →
Firestore 적재 → 테스트까지 자동으로 진행된다.

---

## 왜 이런 구조인가

### 대화를 화면에서 읽지 않는다
카카오톡 대화 목록은 `EVA_VH_ListControl` 커스텀 컨트롤이라 접근성 API 로 텍스트를
읽을 수 없다(실측: 창 하위에 Button·MenuItem **0개**). 가상 스크롤이라 화면 밖
메시지는 존재하지도 않고, 긴 메시지는 잘린다.

반면 **'대화 내보내기'는 카톡이 전체 대화를 txt 로 만들어 준다.** 스크롤이 필요 없고
데이터가 온전하다. 1,500건이든 10,000건이든 클릭 수는 같다. 그래서 자동화는
"내보내기 버튼을 누르는 것"까지만 하고, 나머지는 결정론적 코드가 처리한다.

### LLM 은 파이프라인에 넣지 않는다
파싱·증분 병합·발행은 코드가 더 정확하고 싸고 안정적이다. 매일 돌려도 비용이 없고,
LLM 장애가 파이프라인을 멈추지 않는다. LLM 이 필요한 곳은 주제 분류와 요지 산문뿐이며,
새 메시지는 일단 **'미분류' 스레드**에 들어가 나중에 정리한다.

---

## 구성

| 파일 | 역할 |
|---|---|
| `scripts/kakao_export.ps1` | 카톡 ≡ → 대화 내용 → 대화 내보내기 → 저장 |
| `scripts/kakao_ocr.ps1` | 화면 글자를 좌표와 함께 읽기(안전 검증용) |
| `scripts/ingest_incremental.py` | txt → 새 메시지만 추출해 아카이브 갱신 |
| `scripts/run_daily.ps1` | 위 단계를 순서대로 실행 |

## 안전장치 — 왜 필요한가

카톡 메뉴에서 **`대화 내용` 바로 아래 약 50px 에 `채팅방 나가기`** 가 있다.
좌표가 조금만 밀리면 40명 방을 나가버린다. 게다가 창은 실행 중에도 이동·리사이즈된다
(실측: 960×1020 → 570×960).

그래서 모든 클릭은 아래를 통과해야만 실행된다.

1. 창 제목이 정확히 일치하는지
2. 창을 최상단으로 올렸는지 (다른 창 위로 클릭 방지)
3. 클릭 지점이 아이콘처럼 보이는지 (어두운 픽셀 수 검사)
4. **클릭할 항목의 글자를 OCR 로 읽어 기대한 텍스트인지**
5. 금지 단어(`나가`·`삭제`·`신고`·`차단`·`초대`)가 있으면 즉시 중단
6. 후보가 2개 이상이면 모호하므로 중단

하나라도 실패하면 클릭하지 않고 Esc 로 원상복구한다.
Windows 10 내장 OCR(한국어)을 쓰므로 추가 설치가 필요 없다.

> 좌표는 창 기준 **상대 위치**로 계산한다(우측 끝에서 31px, 상단에서 85px).
> 창이 움직여도 따라간다.

## 증분 반영이 안전한 이유

카카오톡 내보내기는 **항상 전체 대화**를 준다. 매번 대부분이 겹친다.

- `(시각, 닉네임, 본문)` 조합으로 이미 보관된 것을 판별한다 —
  시각만으로 자르면 같은 분에 여러 건일 때 누락된다
- 처리한 txt 의 SHA-256 을 기록해 같은 파일을 두 번 넣어도 무해하다
- 새 사진은 `pending` 상태로 등록된다(파일 미수집 → 화면에 플레이스홀더)
- 새 메시지는 날짜별 '미분류' 스레드에 담겨 "모든 메시지가 정확히 하나의 스레드에
  속한다"는 불변식이 자동 실행에서도 유지된다

검증: `tests/test_ingest_incremental.py` 13개 — 동일 파일 재투입, 겹침+신규,
같은 분 여러 건, 파일 내 중복, 미분류 스레드 커버리지 등

---

## 사용법

### 매일 (반자동 — 권장)
1. 카톡에서 방 열기 → ≡ → **대화 내용** → **대화 내보내기** → `inbox\` 에 저장
2. ```powershell
   powershell -File scripts\run_daily.ps1 -SkipExport
   ```

### 매일 (전자동)
```powershell
powershell -File scripts\run_daily.ps1
```
카톡이 실행 중이고 해당 방 창이 열려 있어야 한다.

### 확인만
```powershell
powershell -File scripts\run_daily.ps1 -SkipExport -DryRun
python -m scripts.ingest_incremental --dry-run
```

### 내보내기 단계만 관찰 (클릭 없이 메뉴 OCR 결과만)
```powershell
powershell -File scripts\kakao_export.ps1 -Discover
```

## 작업 스케줄러 등록 (선택)

```powershell
$act = New-ScheduledTaskAction -Execute 'powershell.exe' `
  -Argument '-ExecutionPolicy Bypass -File "D:\apps\카톡데이터크롤링\scripts\run_daily.ps1"' `
  -WorkingDirectory 'D:\apps\카톡데이터크롤링'
$trg = New-ScheduledTaskTrigger -Daily -At 23:30
Register-ScheduledTask -TaskName '카톡아카이브-일일갱신' -Action $act -Trigger $trg
```

> ⚠️ 무인 실행 주의: 화면이 잠겨 있거나 카톡 창 상태가 다르면 안전장치가 작동해
> **중단**된다(클릭하지 않음). 실패는 `logs\` 에 남으니 주기적으로 확인할 것.
> 무인 자동화가 불안하면 `-SkipExport` 로 두고 내보내기만 손으로 하는 편이 안전하다.

## 로그

- `logs\daily-YYYYMMDD.log` — 전체 실행
- `logs\kakao-export-YYYYMMDD.log` — 내보내기 단계(OCR 결과 포함)

## 갱신 후 할 일

새 메시지는 **'미분류' 스레드**에 들어간다. 주제별 지식 뷰의 품질을 유지하려면
정리가 필요하다.

1. `output/topics.json` 에서 `t-unsorted-YYYY-MM-DD` 스레드 확인
2. 적절한 카테고리의 스레드로 옮기거나 새 스레드로 분리
3. 필요하면 `output/topic-digests.json` 의 요지 산문 갱신
4. 재발행: `python -m scripts.build_firestore_payload && node scripts/upload_firestore.js`

## 남은 한계

- 내보내기 자동화는 **실사용 테스트가 아직 안 됐다**(코드·문법 검증만 완료).
  처음에는 `-Discover` 로 확인한 뒤 쓰는 것을 권한다.
- 카톡 UI 가 바뀌면 좌표·OCR 문구가 달라질 수 있다. 그때는 안전장치가 중단시키므로
  데이터가 망가지지는 않는다.
- 사진 파일은 자동 수집되지 않는다(내보내기 txt 에 포함되지 않음).
  현재 147건이 `pending` 상태이며 화면에는 플레이스홀더로 표시된다.
