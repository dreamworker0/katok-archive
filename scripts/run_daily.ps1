<#
일일 갱신 전체 실행 — 내보내기부터 Firestore 발행까지 한 번에.

단계
  1. (선택) 카카오톡에서 대화 내보내기        kakao_export.ps1
  2. 멤버 요청(수집 동의·삭제) 내려받기        sync_member_requests.js
  3. inbox/*.txt 를 증분 반영                  ingest_incremental.py
  4. 발행본 재생성                             build_firestore_payload.py
  5. Firestore·Storage 적재                    upload_firestore.js
  6. 테스트로 정합성 확인                      unittest

설계
  - 각 단계는 실패하면 즉시 중단한다. 반쪽 상태로 발행하지 않는다.
  - 4~5단계는 새 메시지가 있거나 멤버 요청이 바뀌었을 때만 돈다.
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

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Force $LogDir | Out-Null }
$log = Join-Path $LogDir ("daily-{0}.log" -f (Get-Date -Format 'yyyyMMdd'))

function Say { param([string]$m, [string]$lvl = 'INFO')
    $line = "[{0}] {1} {2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $lvl, $m
    Write-Host $line
    Add-Content -Path $log -Value $line -Encoding utf8
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

# 2) 멤버 요청 내려받기 — 수집 거부를 증분 반영보다 먼저 알아야 한다
$syncArgs = @('scripts\sync_member_requests.js')
if ($DryRun) { $syncArgs += '--dry-run' }
$syncOut = Invoke-Step '멤버 요청 동기화' { node @syncArgs }

$requestsChanged = $false
foreach ($l in $syncOut) {
    if ($l -match '요청 변경:\s*있음') { $requestsChanged = $true }
}

# 3) 증분 반영
$ingestArgs = @('-m', 'scripts.ingest_incremental')
if ($DryRun) { $ingestArgs += '--dry-run' }
$ingestOut = Invoke-Step '증분 반영' { python @ingestArgs }

# '신규 N건' 을 읽어 새 메시지 여부 판단.
# 닫는 괄호까지 묶으면 '(신규 2건, 수집 거부 1건)' 같은 줄을 놓친다.
$added = 0
foreach ($l in $ingestOut) {
    if ($l -match '신규\s+(\d+)건') { $added = [int]$Matches[1] }
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

# 4) 발행본 재생성
Invoke-Step '발행본 생성' { python -m scripts.build_firestore_payload } | Out-Null

# 5) Firestore·Storage 적재
Invoke-Step 'Firestore 적재' { node scripts\upload_firestore.js } | Out-Null

# 6) 정합성 확인
Invoke-Step '테스트' { python -m unittest discover -s tests } | Out-Null

Say "===== 일일 갱신 완료: 새 메시지 $added 건 발행 ====="
if ($added -gt 0) {
    Say "주제 분류가 필요한 '미분류' 스레드가 생겼습니다 — 확인해 정리하세요."
}
exit 0
