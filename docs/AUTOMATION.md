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

반면 **'대화 내보내기'는 카톡이 대화를 txt 파일로 만들어 준다.** 화면에 보이는 것을
긁는 게 아니라 클라이언트가 가진 대화를 그대로 써주므로 데이터가 온전하다.
매일 돌리면 그날 분량만 나와 파일이 작고 처리도 빠르다. 그래서 자동화는
"내보내기를 실행하는 것"까지만 하고, 나머지는 결정론적 코드가 처리한다.

### LLM 은 파이프라인에 넣지 않는다
파싱·증분 병합·발행은 코드가 더 정확하고 싸고 안정적이다. 매일 돌려도 비용이 없고,
LLM 장애가 파이프라인을 멈추지 않는다. LLM 이 필요한 곳은 주제 분류와 요지 산문뿐이며,
새 메시지는 일단 **'미분류' 스레드**에 들어가 나중에 정리한다.

---

## 구성

| 파일 | 역할 |
|---|---|
| `scripts/kakao_export.ps1` | 카톡에 Ctrl+S 를 보내 대화 내보내기 → inbox 로 |
| `scripts/kakao_ocr.ps1` | 화면 글자를 좌표와 함께 읽기(진단용) |
| `scripts/ingest_incremental.py` | txt → 새 메시지만 추출해 아카이브 갱신 |
| `scripts/run_daily.ps1` | 위 단계를 순서대로 실행 |

## 메뉴를 클릭하지 않는다 — Ctrl+S 를 쓴다

카톡 메뉴에는 위험한 항목이 붙어 있다. `대화 내용` 바로 아래 약 50px 에
`채팅방 나가기` 가 있고, 그 하위 메뉴에는 `대화 내용 모두 삭제` 가 있다.
게다가 창은 실행 중에도 이동·리사이즈된다(실측: 960×1020 → 570×960).

다행히 **`대화 내보내기` 에는 단축키 `Ctrl+S`** 가 있다. 그래서 메뉴를 아예
지나가지 않는다 — 오클릭으로 방을 나가거나 대화를 삭제할 경로 자체가 없다.

### 실제로 동작시키기까지 필요했던 것들 (모두 실측)

| 문제 | 원인 | 해결 |
|---|---|---|
| 창을 앞으로 못 올림 | 카톡 **내보내기 알림 팝업**이 포커스를 붙잡고 있었다. 이 팝업은 방 창이 소유한 WS_POPUP 이고 접근성 API 에 전혀 노출되지 않으며 화면에 잔상만 남는다 | 실행 전·후로 **방 창이 소유한 팝업만** WM_CLOSE (다른 앱·메인 창은 건드리지 않음) |
| `SetForegroundWindow` 거부 | 호출 프로세스가 포그라운드가 아니면 윈도우가 거부 | `AttachThreadInput` + Alt 선행 입력 + 재시도 |
| Ctrl+S 무반응 | 창을 앞으로 올려도 **내부 포커스**가 없으면 단축키가 안 먹는다 | 메시지 입력칸을 한 번 클릭(커서만 놓음, Enter 는 절대 안 보냄) |
| 저장 대화상자 못 찾음 | 데스크톱 직접 자식이 아니라 **하위(Descendants)** 에 있다 | `Descendants` + class `#32770` + 카톡 PID |
| 파일명 칸·버튼 못 찾음 | 컨트롤이 `Edit`/`Button` 타입이 아니라 **`Pane`** 으로 노출된다 | win32 클래스+AutomationId 로 찾기 (`Edit`/`1001`, `Button`/`1`) |
| 파일명 읽기 실패 | 비어 있을 때 UIA `Name` 이 라벨('파일 이름:')을 돌려준다. `WM_SETTEXT` 도 안 먹는다 | 파일명을 아예 다루지 않고, **저장 후 새로 생긴 txt** 를 찾아 옮긴다 |

### 남은 안전장치
1. 창 제목이 정확히 일치하는지
2. 그 창이 실제로 최상단인지 (다른 앱에 Ctrl+S 가 가지 않도록)
3. 저장 대화상자가 떴는지 — 안 뜨면 아무것도 하지 않고 중단
4. 저장 대화상자는 접근성 API·Win32 메시지로 다룬다 (좌표 클릭 없음)
5. 파일이 실제로 생기고 크기가 안정될 때까지 확인
6. 중단 시 화면을 `logsbort-*.png` 로 남긴다

> **Esc 를 보내지 않는다.** 카톡에서 Esc 는 대화방 창을 닫아버려, 다음 실행에서
> 창을 못 찾게 된다.

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

### 매일 (반자동)
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

### 내보내기 단계만 확인 (Ctrl+S 를 보내지 않음)
```powershell
powershell -File scripts\kakao_export.ps1 -Discover
```
창을 찾고 포커스까지만 확보한 뒤 종료한다.

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

- **실사용 검증 완료** (2026-07-25): 팝업 정리 → 포커스 → Ctrl+S → 저장 →
  inbox 이동 → 알림 정리까지 전 구간 성공.
- 카톡 UI 가 바뀌면 입력칸 클릭 위치나 대화상자 구조가 달라질 수 있다.
  그때는 안전장치가 중단시키고 화면을 남기므로 데이터가 망가지지는 않는다.
- 매일 내보내면 그날 대화만 담긴 작은 파일이 나온다(정상). 전체 히스토리가
  필요하면 카톡에서 위로 스크롤해 불러온 뒤 내보내야 한다.
- 사진 파일은 자동 수집되지 않는다(내보내기 txt 에 포함되지 않음).
  현재 147건이 `pending` 상태이며 화면에는 플레이스홀더로 표시된다.
