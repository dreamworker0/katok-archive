<#
일일 갱신 전체 실행 — 내보내기부터 Firestore 발행까지 한 번에.

단계
  1. (선택) 카카오톡에서 대화 내보내기        kakao_export.ps1
  2. inbox/*.txt 를 증분 반영                  ingest_incremental.py
  3. 새 메시지가 있으면 발행본 재생성          build_firestore_payload.py
  4. Firestore·Storage 적재                    upload_firestore.js
  5. 테스트로 정합성 확인                      unittest

설계
  - 각 단계는 실패하면 즉시 중단한다. 반쪽 상태로 발행하지 않는다.
  - 새 메시지가 0건이면 3~4단계를 건너뛴다(무료 티어 쓰기 낭비 방지).
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

# 2) 증분 반영
$ingestArgs = @('-m', 'scripts.ingest_incremental')
if ($DryRun) { $ingestArgs += '--dry-run' }
$ingestOut = Invoke-Step '증분 반영' { python @ingestArgs }

# '신규 N건' 을 읽어 새 메시지 여부 판단
$added = 0
foreach ($l in $ingestOut) {
    if ($l -match '신규\s+(\d+)건\)') { $added = [int]$Matches[1] }
}
Say "새 메시지: $added 건"

if ($DryRun) { Say "===== DryRun 종료 (발행하지 않음) ====="; exit 0 }

if ($added -eq 0) {
    Say "새 메시지가 없어 발행을 건너뜁니다."
    Say "===== 일일 갱신 종료 ====="
    exit 0
}

# 3) 발행본 재생성
Invoke-Step '발행본 생성' { python -m scripts.build_firestore_payload } | Out-Null

# 4) Firestore·Storage 적재
Invoke-Step 'Firestore 적재' { node scripts\upload_firestore.js } | Out-Null

# 5) 정합성 확인
Invoke-Step '테스트' { python -m unittest discover -s tests } | Out-Null

Say "===== 일일 갱신 완료: 새 메시지 $added 건 발행 ====="
Say "주제 분류가 필요한 '미분류' 스레드가 생겼습니다 — 확인해 정리하세요."
exit 0
