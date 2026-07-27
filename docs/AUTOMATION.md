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
| `scripts/refresh_watcher.js` | 관리 탭의 '지금 갱신' 을 받아 위를 실행 (상주) |

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
6. 중단 시 화면을 `logs/abort-*.png` 로 남긴다

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

## 작업 스케줄러 등록 (완료)

작업 이름 **`카톡아카이브-일일갱신`** 으로 등록되어 있다 (2026-07-25 등록).

| 항목 | 값 | 이유 |
|---|---|---|
| 시각 | **매일 23:40** | 그날 대화가 끝난 뒤이고 날짜가 넘어가지 않는다 |
| 실행 | `powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden -File scripts\run_daily.ps1` | 콘솔 창이 카톡의 최상단을 빼앗지 않게 숨긴다 |
| 로그온 유형 | **Interactive (로그온한 경우에만)** | UI 자동화라 대화형 세션이 반드시 필요하다 |
| 권한 | Limited (관리자 아님) | 카톡과 같은 권한이어야 메시지를 보낼 수 있다 |
| 놓친 실행 | `-StartWhenAvailable` | PC 가 꺼져 있었으면 켠 뒤에 한 번 만회한다 |
| 동시 실행 | `IgnoreNew` | 겹쳐 돌아 발행이 꼬이지 않게 |
| 시간 제한 | 1시간 | 멈춘 실행을 방치하지 않는다 |

확인·해제:
```powershell
Get-ScheduledTaskInfo -TaskName '카톡아카이브-일일갱신'
```
```powershell
Unregister-ScheduledTask -TaskName '카톡아카이브-일일갱신' -Confirm:$false
```

### 왜 "로그온한 경우에만"인가 (선택 불가)
"사용자가 로그온했는지 여부에 관계없이 실행"을 고르면 작업이 **세션 0**(비대화형)
에서 돌아 데스크톱이 없다. Ctrl+S 를 받을 창도, 최상단이라는 개념도 없으므로
**항상 실패**한다. 화면이 잠겨 있을 때도 마찬가지로 최상단 확보에 실패해
안전장치가 중단시킨다 — 데이터는 안전하지만 그날 갱신은 없다.

> 새벽 시간대(예: 04:00)는 두 가지로 불리하다. ①그 시각엔 화면이 잠겨 있을
> 확률이 높다. ②이미 날짜가 넘어가서, 내보내기가 카톡에 로드된 범위만 주는 특성상
> 전날 대화를 놓칠 수 있다(실측: 16:20 내보내기 = 0.2 KB, 그날 것만).

## 관리 탭의 '지금 갱신' 버튼

23:40 을 기다리지 않고 관리자가 웹에서 갱신을 시작할 수 있다.

```
[관리 탭 '지금 갱신']
   → requestRefresh (관리자만)  → settings/refresh 문서에 요청을 적는다
[이 PC 의 refresh_watcher.js]   ← onSnapshot 으로 즉시 받는다
   → run_daily.ps1 실행         → 상태를 running / done / failed 로 되쓴다
[관리 탭]                        ← 상태를 실시간으로 표시 (진행 중엔 버튼 잠금)
```

### 왜 버튼이 직접 실행하지 않는가

갱신의 본체는 **카톡 창에 Ctrl+S 를 보내고 로컬 `output/` 을 고치는 일**이다.
클라우드에는 카톡도 `output/` 도 없다. 그래서 Function 은 요청만 적고, 실제 실행은
이 PC 에 상주하는 감시 스크립트가 맡는다. 버튼은 "갱신한다"가 아니라
**"갱신하라고 남긴다"** 에 가깝다 — 화면도 그렇게 보여준다.

폴링이 아니라 리스너를 쓴다. 30초 폴링이면 아무 일 없는 날에도 하루 2,880 읽기가
나가고 버튼 반응도 최대 30초 늦다. `onSnapshot` 은 바뀔 때만 들고 즉시 반응한다.

### 상태

| 상태 | 뜻 |
|---|---|
| `queued` | 요청을 적었다. PC 가 받으면 시작한다 |
| `running` | 실행 중. 버튼이 잠긴다 |
| `done` | 끝났다. 새 메시지 건수를 함께 보여준다 |
| `failed` | 멈춘 단계와 사유를 보여준다 |
| `skipped` | 이미 다른 갱신이 돌고 있어 건너뜀 |
| `expired` | 6시간 넘게 묵은 요청이라 실행하지 않음 |

감시는 5분마다 `watcherSeenAt` 을 쓴다. 화면은 12분까지 살아 있는 것으로 보고,
그보다 오래 조용하면 **"PC 가 응답하지 않습니다"** 를 띄운다. 이게 없으면 눌러도
아무 일이 없는데 이유를 알 수 없다.

### 겹쳐 돌지 않는 이유

실행 경로가 둘이 됐다 — 23:40 스케줄러와 버튼. 스케줄러의 `IgnoreNew` 는 자기
작업만 막으므로 23:40 직전에 버튼을 누르면 둘이 동시에 발행에 들어갈 수 있다.

그래서 `run_daily.ps1` 이 **`logs\run_daily.lock` 파일 핸들을 배타적으로 잡는다.**
PID 파일이 아니라 핸들인 이유: 프로세스가 강제 종료돼도 OS 가 핸들을 닫아 잠금이
저절로 풀린다 — 찌꺼기 때문에 다음 갱신이 영영 막히는 일이 없다. 잠겨 있으면
**exit 75**(실패가 아니라 '겹쳐서 안 함')로 끝나고 화면에는 `skipped` 로 뜬다.

### 멈춘 상태 해제

PC 가 꺼지거나 감시가 죽으면 문서가 `queued`·`running` 으로 남는다. 오래되면
(대기 30분 / 실행 90분) 화면에 **'멈춘 상태 해제하고 다시 요청'** 버튼이 나오고,
`requestRefresh({force:true})` 로 밀어낸다. 실제로 돌고 있었다면 위의 파일 잠금이
막으므로 강제 해제로 겹쳐 돌 일은 없다.

### 감시 스크립트 등록

```powershell
node scripts\refresh_watcher.js --dry-run   # 무엇을 할지만 출력
node scripts\refresh_watcher.js --once      # 대기 중인 요청 하나만 처리하고 끝
npm run watch:refresh                       # 상주
```

작업 이름 **`카톡아카이브-갱신감시`** 로 등록되어 있다 (2026-07-27 등록).
23:40 작업과 같은 이유로 **대화형 세션**이 필요하다 — 결국 카톡 창을 조작하기 때문이다.

| 항목 | 값 | 이유 |
|---|---|---|
| 트리거 | 로그온 시 | 상주 프로세스라 세션이 열릴 때 한 번 뜨면 된다 |
| 실행 | `C:\Program Files\nodejs\node.exe scripts\refresh_watcher.js` | **절대 경로.** 작업 스케줄러가 PATH 를 못 잡는 경우가 있다 |
| 시간 제한 | **없음 (`PT0S`)** | 상주인데 기본 3일 제한에 걸려 조용히 죽으면 그날부터 버튼이 먹지 않는다 |
| 다시 시작 | 5분 간격 3회 | 리스너가 끊겨 스스로 종료했을 때 다시 띄운다 |
| 동시 실행 | `IgnoreNew` | 두 감시가 같은 요청을 잡아 카톡을 동시에 조작하지 않게 |
| 권한 | Limited (관리자 아님) | 카톡과 같은 권한이어야 한다 |

### 등록은 `schtasks /xml` 로 한다 — `Register-ScheduledTask` 는 안 된다

`Register-ScheduledTask` 는 권한 상승 없이 부르면 **Access denied
(HRESULT 0x80070005)** 로 실패한다(실측). `schtasks.exe /create /xml` 은 같은
사용자·같은 설정으로 그냥 된다. 등록에 쓴 XML 은
[`docs/assets/watcher-task.xml`](assets/watcher-task.xml) 에 있다.

XML 안의 `__USER__` 를 등록하는 사람으로 바꿔 넣는다. 저장소에 계정명·호스트명을
박아두지 않으려고 자리표로 뒀다 — 이 저장소는 개인정보를 담지 않는다.

```powershell
$tmp = Join-Path $env:TEMP 'watcher-task.xml'
$xml = [System.IO.File]::ReadAllText('docs\assets\watcher-task.xml', [System.Text.Encoding]::Unicode).Replace('__USER__', "$env:USERDOMAIN\$env:USERNAME")
[System.IO.File]::WriteAllText($tmp, $xml, [System.Text.Encoding]::Unicode)
schtasks /create /tn '카톡아카이브-갱신감시' /xml $tmp /f
```

`WriteAllText` 로 **UTF-16** 으로 쓰는 것이 중요하다 — `schtasks` 가 요구한다.
`Set-Content` 기본 인코딩으로 쓰면 읽지 못한다. 확인·해제·즉시 시작:

```powershell
Get-ScheduledTaskInfo -TaskName '카톡아카이브-갱신감시'
```
```powershell
Start-ScheduledTask -TaskName '카톡아카이브-갱신감시'
```
```powershell
Unregister-ScheduledTask -TaskName '카톡아카이브-갱신감시' -Confirm:$false
```

> `LastTaskResult` 가 **267009**(0x41301)면 실패가 아니라 **'지금 실행 중'** 이다.
> 상주 작업이라 정상 상태가 그것이다.

로그는 `logs\refresh-YYYYMMDD.log` 에 남는다. 감시가 살아 있는지는 관리 탭이
`watcherSeenAt` 으로 보여주므로, 죽으면 화면에서 먼저 눈에 띈다.

### 무인 실행 전제
- 카카오톡이 실행 중이고 해당 방 창이 열려 있어야 한다
- 화면이 잠겨 있지 않아야 한다 (절전은 `-StartWhenAvailable` 이 만회)
- `serviceAccountKey.json` 이 있어야 Firestore 적재가 로그인 없이 된다
- 실패는 `logs\daily-*.log` 와 `logs\abort-*.png` 에 남는다 — 주기적으로 볼 것

## 로그

- `logs\daily-YYYYMMDD.log` — 전체 실행
- `logs\kakao-export-YYYYMMDD.log` — 내보내기 단계(OCR 결과 포함)

## 무엇이 자동으로 갱신되고, 무엇이 안 되는가

자동 실행은 **절반만** 갱신한다. `ingest_incremental.py` 가 실제로 쓰는 파일이
경계선이다.

### 자동 (결정론적 코드 — 매일 밤 반영)

| 쓰는 파일 | 사이트에서 보이는 것 |
|---|---|
| `output/messages.jsonl` | **타임라인** — 새 대화가 그대로 붙는다 |
| `output/participants.json` | **참여자·통계** — 인원·메시지 수 재계산 |
| `output/images.jsonl` | **갤러리** — 새 사진이 `pending` 플레이스홀더로 |
| `output/topics.json` | 스레드 소속 — 단 `t-unsorted-YYYY-MM-DD` (카테고리 `chat`) 로만 |

### 자동 아님 (LLM 판단·큐레이션 산출물)

| 건드리지 않는 파일 | 결과 |
|---|---|
| `output/topics.json` 의 실제 카테고리 배정 | 새 메시지는 **'미분류'** 에 머문다 |
| `output/knowledge.json` | **관계 그래프**에 새 사람·앱·도구 노드가 안 생긴다 |
| `output/topic-digests.json` | **요지 산문**이 어제 상태로 남는다 |
| 사진 파일 자체 | 내보내기 txt 에 없다 → `pending` 유지 |

즉 매일 아침 상태는 **"타임라인·통계는 최신, 주제별 지식 뷰는 마지막 정리 시점"** 이다.

## 발행은 바뀐 것만 올린다

예전에는 새 글이 3건인 날에도 **전부** 다시 올렸다 — Firestore 쓰기 1,526건(그중
1,509건이 원문), 구문서 확인용 읽기 약 1,530건, 사진 64장 41MB 재업로드.
지금은 문서마다 해시를 대장(`output/upload-state.json`)에 적어 두고 달라진 것만 쓴다.

| 상황 | 쓰기 | 읽기 | Storage |
|---|---|---|---|
| 새 글 없음(발행 자체를 건너뜀) | 0 | 0 | — |
| 새 글 1건 | **2** (meta + 그 글) · threads 묶음이 바뀌면 +1 | 0 | 새 사진만 |
| 주제 재분류·요지 갱신 | 바뀐 묶음·요지만 | 0 | 새 사진만 |
| 주 1회 또는 `--full` | 전량 1,526 | 전량 | 크기 다른 것만 |

측정(2026-07-26): 전량 4.2초 → 변경 없는 날 3.6초, 쓰기 1,526건 → **1건**.

대장이 원격과 어긋나면 '안 쓰고 넘어가는' 사고가 난다. 그래서 —

- 대장이 없거나 깨졌거나 프로젝트가 다르면 **자동으로 전량 모드**
- **7일마다 한 번은 전량**으로 맞춘다 (`FULL_EVERY_DAYS`)
- 대장은 적재가 끝까지 성공한 뒤에만 쓴다. 중간에 실패하면 옛 대장이 남아
  다음 실행이 **더 많이** 쓴다 — 덜 쓰는 쪽이 아니라 더 쓰는 쪽으로 틀린다
- 콘솔에서 문서를 직접 고쳤다면 `npm run upload:full` 로 맞춘다

검증: `tests/upload_state.test.js` 10개 (`npm test`) — 대장 없음·깨짐·딴 프로젝트,
변경분만 쓰기, 빠진 문서 삭제, 중간 실패 후 재실행, 원격 구문서 정리.

## 데이터는 저장소에 없다 — 그래서 보고서 복구 수단을 둔다

저장소는 코드만 백업한다(2026-07-26 결정). `output/`·`assets/images/`·
`KakaoTalk_*.txt` 는 `.gitignore` 로 빠져 있고 이력에도 없다. 실명 대화와 사진은
36명의 개인정보이고, 협업자를 한 명 초대하면 그 사람에게 방 전체가 열리기 때문이다.

그래서 손으로 쓴 보고서(`output/reports/*.md`)의 원본이 로컬 디스크 한 곳에만
남는다. 발행하면 본문이 `threads/all` 문서에 통째로 실리므로 Firestore 가 사실상
원격 사본이다. 디스크를 잃으면 되살린다.

```bash
node scripts/restore_reports.js --dry-run   # 무엇이 없고 무엇이 다른지
node scripts/restore_reports.js             # 없는 것만 만든다
node scripts/restore_reports.js --force     # 다른 것까지 발행본으로 덮는다
```

확인(2026-07-26): 발행본 164개를 임시 폴더에 풀어 로컬 원본과 견주니 **전부
바이트 단위로 동일**했고, 복구본을 `topic_reports.parse_report` 로 다시 읽어
164개 모두 정상 파싱됐다(사진 자리표 포함).

한계 — Firestore 에는 **마지막으로 발행한 판**만 있다. 고친 이력은 남지 않으므로
발행 전에 날린 편집은 되살릴 수 없다.

## 갱신 후 할 일 — 주 1회 재분류

'미분류' 스레드가 쌓이면 주제별 지식 뷰가 뒤처진다. **주 1회** 정리한다
(LLM 판단이 필요하므로 Claude 에게 요청 — 재분류·요지 산문은 Fable 권장).

1. `output/topics.json` 에서 `t-unsorted-YYYY-MM-DD` 스레드 확인
2. 적절한 카테고리의 스레드로 옮기거나 새 스레드로 분리
3. 새로 등장한 사람·앱·도구를 `output/knowledge.json` 에 노드·엣지로 추가
4. 필요하면 `output/topic-digests.json` 의 요지 산문 갱신
5. 테스트: `python -m unittest discover -s tests` (참조 무결성·커버리지 검증)
6. 재발행: `python -m scripts.build_firestore_payload && node scripts/upload_firestore.js`

미분류가 얼마나 쌓였는지 세기:
```bash
python -m scripts.count_unsorted
```

## 남은 한계

- **실사용 검증 완료** (2026-07-25): 팝업 정리 → 포커스 → Ctrl+S → 저장 →
  inbox 이동 → 알림 정리까지 전 구간 성공.
- 카톡 UI 가 바뀌면 입력칸 클릭 위치나 대화상자 구조가 달라질 수 있다.
  그때는 안전장치가 중단시키고 화면을 남기므로 데이터가 망가지지는 않는다.
- 매일 내보내면 그날 대화만 담긴 작은 파일이 나온다(정상). 전체 히스토리가
  필요하면 카톡에서 위로 스크롤해 불러온 뒤 내보내야 한다.
- 사진 파일은 자동 수집되지 않는다(내보내기 txt 에 포함되지 않음).
  현재 147건이 `pending` 상태이며 화면에는 플레이스홀더로 표시된다.
# 보고서 문맥 연결 감사

링크·사진·첨부가 보고서의 관련 문단에 연결됐는지, 잘못되거나 중복된
자리표가 없는지 전체 보고서를 검사한다. 원문 메시지 내용은 출력하지 않는다.

```powershell
python -m scripts.audit_report_context
```

`유효하지 않은 자리표`와 `중복 자리표`가 모두 0이면 종료 코드 0이다.
문맥이 불분명해 `하단 유지`로 집계된 자료는 오류가 아니며 자동으로 잘못된
문단에 붙이지 않았다는 뜻이다.
