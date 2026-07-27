<#
일일 갱신 전체 실행 — 내보내기부터 Firestore 발행까지 한 번에.

단계
  1. (선택) 카카오톡에서 대화 내보내기        kakao_export.ps1
  2. 멤버 명부 거울 갱신                       sync_members.js
  3. 멤버 요청(수집 동의·삭제) 내려받기        sync_member_requests.js
  4. inbox/*.txt 를 증분 반영                  ingest_incremental.py
  5. 발행본 재생성                             build_firestore_payload.py
  6. Firestore·Storage 적재                    upload_firestore.js
  7. 테스트로 정합성 확인                      unittest

설계
  - 각 단계는 실패하면 즉시 중단한다. 반쪽 상태로 발행하지 않는다.
  - 5~6단계는 새 메시지가 있거나 멤버 요청이 바뀌었을 때만 돈다.
    조용한 날에 들어온 삭제 요청이 묻히면 안 되므로 요청 변경도 발행 사유다.
  - 멤버 요청을 증분 반영보다 먼저 받는다. '수집 거부'는 수집 단계에서 걸러야 해서
    순서가 뒤바뀌면 거부 의사를 낸 그날 글이 한 번 수집되고 만다.
  - 모든 출력은 logs\daily-YYYYMMDD.log 에 남긴다.

사용
  powershell -File scripts\run_daily.ps1 -SkipExport   # 내보내기는 수동, 나머지 자동
  powershell -File scripts\run_daily.ps1               # 내보내기까지 자동
  powershell -File scripts\run_daily.ps1 -DryRun       # 확인만
#>
param(
    [switch]$SkipExport,   # 카톡 조작 없이 inbox 의 txt 만 처리
    [switch]$DryRun,       # 변경·발행 없이 확인만
    [string]$LogDir = 'logs'
)

$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))

# 자식 프로세스 출력 인코딩을 UTF-8 로 맞춘다.
#
# Node 는 언제나 UTF-8 로 쓴다. 그런데 콘솔 코드페이지가 cp949(한국어 윈도 기본)면
# PowerShell 이 그 바이트를 cp949 로 읽어 '멤버' 가 '硫ㅻ쾭' 처럼 깨진다. 로그를
# 못 읽는 것도 문제지만, 진짜 문제는 아래에서 출력을 -match 로 읽는다는 점이다.
# 깨진 글자는 절대 매칭되지 않으므로 '요청 변경: 있음' 을 놓치고, 조용한 날에
# 들어온 삭제 요청이 발행되지 않은 채 묻힌다.
#
# 그래서 두 겹으로 막는다: (1) 인코딩을 맞춰 애초에 안 깨지게 하고,
# (2) 판단에 쓰는 신호는 ASCII 표식(REQUESTS_CHANGED / NEW_MESSAGES)으로 받는다.
# 작업 스케줄러처럼 콘솔이 없는 환경에서는 (1)이 실패할 수 있어 (2)가 필요하다.
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
# 파이썬도 같은 인코딩으로 내보내게 한다. PYTHONUTF8 과 달리 open() 기본값은
# 건드리지 않아, 파일을 읽고 쓰는 기존 동작이 그대로 유지된다.
$env:PYTHONIOENCODING = 'utf-8'

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Force $LogDir | Out-Null }
$log = Join-Path $LogDir ("daily-{0}.log" -f (Get-Date -Format 'yyyyMMdd'))

function Say { param([string]$m, [string]$lvl = 'INFO')
    $line = "[{0}] {1} {2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $lvl, $m
    Write-Host $line
    Add-Content -Path $log -Value $line -Encoding utf8
}

# 한 번에 하나만 돈다 — 겹쳐 돌면 발행이 반쪽 상태로 섞인다.
#
# 실행 경로가 둘이 됐다: 매일 23:40 작업 스케줄러, 그리고 관리 탭의 '지금 갱신'
# (refresh_watcher.js 가 이 스크립트를 부른다). 스케줄러의 IgnoreNew 는 자기
# 작업만 막으므로, 23:40 직전에 버튼을 누르면 두 개가 동시에 발행에 들어간다.
#
# PID 파일이 아니라 파일 핸들을 잡는다. 프로세스가 죽으면 OS 가 핸들을 닫아
# 잠금이 저절로 풀린다 — 강제 종료된 실행이 남긴 찌꺼기 때문에 다음 갱신이
# 영영 막히는 일이 없다.
$lockPath = Join-Path $LogDir 'run_daily.lock'
try {
    $lock = [System.IO.File]::Open($lockPath, 'OpenOrCreate', 'Write', 'None')
} catch {
    Say "다른 갱신이 이미 실행 중입니다 — 중단합니다." 'WARN'
    # 75 는 '실패'가 아니라 '겹쳐서 안 함'이라는 뜻이다. 부르는 쪽이 구분해야
    # 화면에 엉뚱한 실패로 뜨지 않는다.
    exit 75
}

function Invoke-Step {
    param([string]$name, [scriptblock]$body)
    Say "--- $name ---"
    $out = & $body 2>&1
    $code = $LASTEXITCODE
    foreach ($l in $out) { Say "    $l" }
    if ($null -ne $code -and $code -ne 0) {
        Say "$name 실패 (exit $code) — 중단합니다." 'ERROR'
        exit $code
    }
    , $out
}

Say "===== 일일 갱신 시작 (SkipExport=$SkipExport DryRun=$DryRun) ====="

# 1) 내보내기
if (-not $SkipExport) {
    Invoke-Step '카카오톡 대화 내보내기' {
        powershell -ExecutionPolicy Bypass -File scripts\kakao_export.ps1
    } | Out-Null
} else {
    Say "내보내기 건너뜀 — inbox\ 의 기존 txt 를 사용합니다."
}

# 2) 멤버 명부 거울 갱신 — 관리 탭에서 승인한 사람이 로컬에도 반영되어야
#    닉네임 대조와 이메일→표시명 매핑이 맞는다
Invoke-Step '멤버 명부 동기화' { node scripts\sync_members.js } | Out-Null

# 3) 멤버 요청 내려받기 — 수집 거부를 증분 반영보다 먼저 알아야 한다
$syncArgs = @('scripts\sync_member_requests.js')
if ($DryRun) { $syncArgs += '--dry-run' }
$syncOut = Invoke-Step '멤버 요청 동기화' { node @syncArgs }

# 표식이 아예 없으면 '변경 없음' 으로 넘기지 않는다. 그렇게 하면 요청이 조용히
# 묻히고, 묻힌 사실조차 남지 않는다. 모를 때는 발행하는 쪽으로 기운다 — 불필요한
# 발행은 손해가 없지만, 삭제 요청을 못 지키는 건 되돌릴 수 없다.
$requestsChanged = $null
foreach ($l in $syncOut) {
    if ($l -match 'REQUESTS_CHANGED=([01])') { $requestsChanged = ($Matches[1] -eq '1') }
}
if ($null -eq $requestsChanged) {
    Say "멤버 요청 변경 여부를 읽지 못했습니다 (REQUESTS_CHANGED 표식 없음)." 'WARN'
    Say "    요청을 놓치지 않으려고 변경된 것으로 보고 발행합니다." 'WARN'
    $requestsChanged = $true
}

# 4) 증분 반영
$ingestArgs = @('-m', 'scripts.ingest_incremental')
if ($DryRun) { $ingestArgs += '--dry-run' }
$ingestOut = Invoke-Step '증분 반영' { python @ingestArgs }

# 새 메시지 수. 여기도 ASCII 표식으로 받는다 — 못 읽으면 새 글이 있어도 발행을
# 건너뛰고, 그날 대화가 아카이브에 들어오지 않는다.
$added = $null
foreach ($l in $ingestOut) {
    if ($l -match 'NEW_MESSAGES=(\d+)') { $added = [int]$Matches[1] }
}
if ($null -eq $added) {
    Say "새 메시지 수를 읽지 못했습니다 (NEW_MESSAGES 표식 없음)." 'WARN'
    Say "    새 글을 놓치지 않으려고 발행을 진행합니다." 'WARN'
    $added = 0
    $requestsChanged = $true
}
Say "새 메시지: $added 건 / 멤버 요청 변경: $requestsChanged"

if ($DryRun) { Say "===== DryRun 종료 (발행하지 않음) ====="; exit 0 }

if ($added -eq 0 -and -not $requestsChanged) {
    Say "새 메시지도 멤버 요청 변경도 없어 발행을 건너뜁니다."
    Say "===== 일일 갱신 종료 ====="
    exit 0
}
if ($added -eq 0) {
    Say "새 메시지는 없지만 멤버 요청이 바뀌어 발행합니다."
}

# 5) 발행본 재생성
Invoke-Step '발행본 생성' { python -m scripts.build_firestore_payload } | Out-Null

# 6) Firestore·Storage 적재
Invoke-Step 'Firestore 적재' { node scripts\upload_firestore.js } | Out-Null

# 7) 정합성 확인 — 파이썬(발행본 무결성) + 노드(증분 적재 규칙)
Invoke-Step '테스트' { python -m unittest discover -s tests } | Out-Null
Invoke-Step '테스트(적재)' { npm test --silent } | Out-Null

Say "===== 일일 갱신 완료: 새 메시지 $added 건 발행 ====="
if ($added -gt 0) {
    Say "주제 분류가 필요한 '미분류' 스레드가 생겼습니다 — 확인해 정리하세요."
}

# $lock 을 명시적으로 닫지 않는다. 위쪽 exit 경로가 여럿이라 한 군데서 닫아도
# 새지 않게 만들 수 없고, 프로세스가 끝나면 OS 가 어차피 닫는다. 이 스크립트는
# 항상 `powershell -File` 로 자기 프로세스에서 돈다.
exit 0
