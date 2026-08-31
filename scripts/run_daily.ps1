<#
일일 갱신 전체 실행 — 내보내기부터 Firestore 발행까지 한 번에.

단계
  1. (선택) 카카오톡에서 대화 내보내기        kakao_export.ps1
  2. 멤버 명부 거울 갱신                       sync_members.js
  3. 멤버 요청(수집 동의·삭제) 내려받기        sync_member_requests.js
  4. inbox/*.txt 를 증분 반영                  ingest_incremental.py
  5. 주제 분류 (LLM, 비치명적)                 classify_unsorted.py
  5c. 발행본이 로컬보다 뒤처졌나 확인           publish_state.py
  6. 갤러리용 작은 사진 생성                   build_thumbnails.py
  6b. 사진 속 개인정보 검사                     ocr_images.ps1 + scan_image_pii.py
  7. 발행본 재생성                             build_firestore_payload.py
  8. 테스트로 정합성 확인 (적재 전에)          unittest
  9. Firestore·Storage 적재                    upload_firestore.js
 10. 결과를 화면에 남기기                      report_run.js
 11. 작업 폴더 마름질(로그·스크린샷)          prune_workspace.py

설계
  - 각 단계는 실패하면 즉시 중단한다. 반쪽 상태로 발행하지 않는다.
    **단, 5단계(주제 분류)는 예외다** — 실패하면 미분류 스레드가 남을 뿐이므로
    삼키고 나아간다. LLM 장애가 그날 타임라인·통계·삭제 요청 반영을 통째로
    날려서는 안 된다. 이것이 파이프라인에서 유일하게 LLM 을 쓰는 칸이다.
  - 6~8단계는 발행 사유가 있을 때만 돈다. 사유는 넷이다 — 새 메시지, 멤버 요청
    변경, 주제 분류 변경, 그리고 **발행본이 로컬보다 뒤처짐**. 조용한 날에 들어온
    삭제 요청이 묻히면 안 되므로 요청 변경도 사유이고, 정리해 놓고 안 올리면 화면이
    거짓말을 하므로 분류도 사유다. 넷째는 지난 실행이 남긴 빚을 본다 — 앞의 셋은
    모두 '이번 실행에서 새로 생긴 것' 만 보므로, 원장에는 반영하고 적재 전에 죽은
    날의 글은 다시 갱신해도 영영 올라가지 않았다(실측 2026-07-30, 34건).
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

    # 로그를 못 써도 갱신은 계속한다. $ErrorActionPreference = 'Stop' 이라
    # Add-Content 실패는 여기서 갱신을 죽인다 — 로그를 tail -f 로 열어두거나
    # 백신이 잡고 있으면 그렇게 된다(실측 2026-07-27, kakao_export.ps1 에서).
    # 진단을 남기려는 코드가 그날 갱신을 없애서는 안 된다.
    for ($i = 0; $i -lt 3; $i++) {
        try { Add-Content -Path $log -Value $line -Encoding utf8; return }
        catch { Start-Sleep -Milliseconds 150 }
    }
    if (-not $script:LogWriteWarned) {
        $script:LogWriteWarned = $true
        Write-Host "  (로그 파일이 잠겨 있어 화면에만 남깁니다)"
    }
}

# 갱신 결과를 화면에도 남긴다 (settings/lastRun).
#
# 로그만으로는 부족했다. '지금 갱신' 버튼 경로는 refresh_watcher.js 가 상태를 써서
# 관리 탭이 실시간으로 보여주는데, 매일 23:40 스케줄러는 아무것도 쓰지 않았다.
# 그래서 야간 갱신이 며칠 내리 실패해도 화면은 조용하고, 사람이 logs\daily-*.log 를
# 열어 보기 전까지 아무도 모른다.
#
# **실패해도 갱신 결과를 바꾸지 않는다.** 종료 코드를 보지 않고, stderr 를 오류로
# 승격시키지 않는다 — 알림을 남기려는 코드가 그날 갱신을 죽여서는 안 된다.
# -DryRun 에서는 쓰지 않는다. 확인만 하는 실행이 화면의 '마지막 갱신' 을 덮으면
# 그것이 곧 거짓말이 된다.
function Report-Run {
    param([string]$status, [string]$step, [int]$code = 0, [string]$why, [int]$added = -1)
    if ($DryRun) { return }
    $a = @('scripts\report_run.js', '--status', $status, '--exit', "$code")
    if ($step)      { $a += @('--step', $step) }
    if ($why)       { $a += @('--why', $why) }
    if ($added -ge 0) { $a += @('--added', "$added") }
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { $out = & node @a 2>&1 } catch { $out = "기록 실패: $_" }
    finally { $ErrorActionPreference = $prevEap }
    foreach ($l in $out) { Say "    $l" }
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

    # 네이티브 명령의 stderr 를 오류로 승격시키지 않는다.
    #
    # PowerShell 5.1 에서 `& $body 2>&1` 은 네이티브 exe 가 stderr 에 쓴 줄마다
    # NativeCommandError 레코드를 만든다. $ErrorActionPreference = 'Stop' 이면 그것이
    # 종료 오류가 되어, 명령이 0 으로 성공했어도 스크립트가 그 자리에서 죽는다.
    #
    # `python -m unittest` 는 진행 표시(......)와 'OK' 를 모두 stderr 로 쓴다. 실측
    # 2026-07-27: 237개 테스트가 전부 통과했는데 갱신이 '테스트' 단계에서 죽었고,
    # 로그에는 단계 제목만 남아 원인이 보이지 않았다. 이 단계는 그날까지 무인
    # 실행에서 한 번도 돌지 않았다 — 앞선 이틀은 새 메시지가 0건이라 발행 전에
    # 종료됐다. 그래서 잠재 버그로 남아 있었다.
    #
    # 성패는 stderr 가 아니라 종료 코드로 판단한다 (바로 아래에서 그렇게 한다).
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { $out = & $body 2>&1 } finally { $ErrorActionPreference = $prevEap }
    $code = $LASTEXITCODE
    foreach ($l in $out) { Say "    $l" }
    if ($null -ne $code -and $code -ne 0) {
        Say "$name 실패 (exit $code) — 중단합니다." 'ERROR'
        # 어느 단계에서 멈췄는지까지 남긴다. 로그를 열지 않고도 관리 탭에서 보인다.
        Report-Run -status 'failed' -step $name -code $code
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

# 4b) 서랍에서 첨부 원본 받기 — 증분 반영 **뒤**, 작은 사진·개인정보 검사 **앞**
#
#     내보내기 txt 에는 첨부가 들어 있지 않다(파일은 이름 한 줄, 사진은 흔적만).
#     원본은 '채팅방 서랍' 에서 따로 받아야 하는데, **파일은 공유일 + 14일이면
#     만료된다** — 유효기간 날짜에 도달하면 이미 못 받으므로 실질 13일이다.
#     실측 2026-08-20: 아카이브에 없던 파일 45개 중 서랍에 남은 것은 7개뿐이고
#     그중 4개는 그날 만료였다. 38개는 영구 소실이었다. 그래서 매일 돌아야 한다.
#
#     여기 두는 이유는 순서 때문이다. 사진이 들어와야 '작은 사진 생성'과 '사진
#     개인정보 검사'가 그것들을 훑고, 그 판정이 발행본에 반영된다. 뒤에 두면 그날
#     받은 사진이 검사도 축소판도 없이 다음 날까지 밀린다.
#
#     **실패해도 갱신을 멈추지 않는다.** Invoke-Step 을 쓰지 않는 이유다. 첨부는
#     더해지는 것이고, 서랍 창이 닫혀 있으면 그날은 못 받을 뿐이다. 그것 때문에
#     그날 대화·주제·통계 발행이 통째로 날아가면 손해가 훨씬 크다. 13일 여유가
#     있으니 다음 날 다시 받으면 된다. 대신 로그에 또렷이 남긴다.
#     자세한 진행은 logs\kakao-drawer-<날짜>.log 에 따로 쌓인다.
$prevEap = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try {
    Say '서랍 첨부 수집'
    $drawerOut = & powershell -ExecutionPolicy Bypass -File scripts\kakao_drawer.ps1 2>&1
    $drawerExit = $LASTEXITCODE
    foreach ($l in $drawerOut) {
        if ($l -match '탭 ──|화면: 카드|개 선택|받은 파일 \d+개 →|WARN|ABORT') { Say "    $l" }
    }
    # 첨부를 못 받은 날은 **화면에도** 남긴다.
    #
    # 실측 2026-08-22~25: 서랍 창이 닫혀 있어 나흘 내리 한 개도 못 받았는데,
    # 경고가 logs\kakao-drawer-*.log 에만 있어서 아무도 몰랐다. 파일은 공유일 +
    # 14일에 만료되므로, 모르고 지나간 날이 쌓이면 그대로 영구 소실이다.
    # 발행은 멀쩡히 됐으니 status 는 'ok' 로 두되, 사유 줄에 얹어 관리 탭에서
    # 보이게 한다 — 조용한 실패가 이 일의 진짜 위험이다.
    if ($drawerExit -eq 2) {
        Say '    서랍 창이 없고 열지도 못했습니다 — 카카오톡이 트레이에 있거나 잠겨 있는지 보세요.' 'WARN'
        $script:drawerWarn = '서랍 첨부 못 받음(창 없음)'
    }
    elseif ($drawerExit -ne 0) {
        Say "    서랍 수집 실패 (exit $drawerExit) — 갱신은 계속합니다." 'WARN'
        $script:drawerWarn = "서랍 첨부 못 받음(exit $drawerExit)"
    }
    else {
        foreach ($l in (& python -m scripts.collect_drawer 2>&1)) { Say "    $l" }
        foreach ($l in (& python -m scripts.build_file_manifest 2>&1)) {
            if ($l -match '연결 \(|짝을 못 찾은|같은 이름의') { Say "    $l" }
        }
    }
}
finally { $ErrorActionPreference = $prevEap }

# 5) 주제 분류 (LLM) — 실패해도 갱신을 멈추지 않는다
#
#    파이프라인에서 유일하게 LLM 을 쓰는 칸이다. "이 대화가 어느 주제인가"는 코드가
#    답할 수 없어서 맡긴다. 원래 사람이 주 1회 하던 일을 자동으로 돌리기로 했다.
#
#    Invoke-Step 을 쓰지 않는다 — 그것은 실패하면 갱신을 중단시킨다. 분류는 있으면
#    좋은 것이고, 없으면 미분류 스레드가 남을 뿐이다. LLM 장애 때문에 그날 타임라인·
#    통계·삭제 요청 반영이 통째로 날아가서는 안 된다. 그래서 실패를 삼키고 나아간다.
#
#    분류가 발행보다 **앞**에 있어야 한다. 뒤에 두면 분류 결과를 올리려고 발행을
#    한 번 더 해야 한다.
#
#    그리고 '발행할지' 판단보다도 앞이어야 한다. 새 메시지가 없는 날에도 지난 실패나
#    한 번에 처리하는 상한(MAX_MESSAGES_PER_RUN) 때문에 미분류가 남아 있을 수 있다.
#    발행 여부로 먼저 걸러내면 그 잔여분을 영영 치우지 못한다 — 새 글이 있는 날에만
#    정리되는 셈이 되고, 실패가 한 번 나면 그대로 굳는다.
#
#    비용: 미분류가 없으면 스크립트가 호출 자체를 하지 않는다(조용한 날 0원).
Say "--- 주제 분류 (LLM) ---"
# Invoke-Step 과 같은 이유로 stderr 를 오류로 승격시키지 않는다 — 파이썬이 stderr 에
# 한 줄이라도 쓰면 'Stop' 정책이 여기서 갱신을 죽인다.
$prevEap = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try { $classifyOut = & { python -m scripts.classify_unsorted } 2>&1 }
finally { $ErrorActionPreference = $prevEap }
$classifyCode = $LASTEXITCODE
foreach ($l in $classifyOut) { Say "    $l" }

# 분류가 실제로 무언가 바꿨으면 그것도 발행 사유다. 안 그러면 새 메시지가 없는 날에
# 미분류를 정리해 놓고도 발행을 건너뛰어, 화면은 그대로 '미분류'로 남는다.
$classified = 0
if ($null -ne $classifyCode -and $classifyCode -ne 0) {
    Say "주제 분류가 실패했습니다 (exit $classifyCode) — 미분류로 남기고 계속합니다." 'WARN'
} else {
    $marker = $null
    foreach ($l in $classifyOut) {
        if ($l -match 'CLASSIFIED=(\d+)') { $marker = [int]$Matches[1] }
    }
    if ($null -eq $marker) {
        # 표식을 못 읽으면 바뀌었을 수도 있다고 본다 — 발행하는 쪽으로 기운다.
        # 불필요한 발행은 손해가 없지만, 정리해 놓고 안 올리면 화면이 거짓말을 한다.
        Say "분류 결과 표식(CLASSIFIED)을 읽지 못했습니다 — 발행하는 쪽으로 진행합니다." 'WARN'
        $classified = 1
    } else {
        $classified = $marker
        if ($classified -gt 0) {
            Say "주제 분류: 메시지 $classified 건을 정리했습니다."
        }
    }
}

# 5b-2) AI 검증 주석 (agy 검색 + 주소 열기 + LLM 작성)
#
#     사람 보고서 옆에 붙는 기계의 주석이다. 사람 보고서가 쓰인 **뒤**에 돌아야
#     한다 — 그 글을 재료로 삼는다.
#
#     Invoke-Step 을 쓰지 않는다. 이것이 실패해도 갱신은 굴러가야 한다. 곁딸린
#     글 하나 때문에 그날 타임라인·통계가 통째로 날아가서는 안 된다.
#
#     하룻밤에 몇 편만 쓴다(기본 5편, 편당 약 $0.3~0.5). 한 번에 많이 쓰면
#     잘못된 틀이 여러 편에 한꺼번에 박히고, 사람이 눈으로 보고 고칠 여지가
#     사라진다. 남은 것은 다음 밤에 이어서 쓴다.
Say "--- AI 검증 주석 (LLM) ---"
$prevEap = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try { $aiOut = & { python -m scripts.ai_reports } 2>&1 }
finally { $ErrorActionPreference = $prevEap }
$aiCode = $LASTEXITCODE
foreach ($l in $aiOut) { Say "    $l" }
if ($null -ne $aiCode -and $aiCode -ne 0) {
    Say "AI 검증 주석이 실패했습니다 (exit $aiCode) — 없이 계속합니다." 'WARN'
}

# 5c) 네 번째 발행 사유 — 발행본이 로컬보다 뒤처졌나(지난 실행이 남긴 빚)
#
#     앞의 사유 셋은 모두 '이번 실행에서 새로 생긴 것' 을 본다. 그래서 지난 실행이
#     원장에는 반영하고 적재 전에 죽은 경우를 아무도 보지 않았다. 실측 2026-07-30:
#     23:40 갱신이 새 글 34건을 원장에 넣고 테스트 단계에서 멈췄고, 다음 날 '지금
#     갱신' 을 눌러도 증분이 0건이라 "마쳤습니다" 만 뜨고 타임라인은 그대로였다.
#     버튼을 몇 번 눌러도 같다 — 사람이 손으로 발행할 때까지 영영 안 올라간다.
#
#     Invoke-Step 을 쓰지 않는다. 이 확인이 실패해도 갱신은 굴러가야 한다.
#     못 읽었으면 발행하는 쪽으로 기운다 — 적재는 달라진 문서만 쓰므로(해시 비교)
#     헛발행은 거의 무료지만, 올릴 것을 안 올리면 화면이 거짓말을 한다.
$prevEap = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try { $staleOut = & { python -m scripts.publish_state } 2>&1 }
finally { $ErrorActionPreference = $prevEap }
$staleCode = $LASTEXITCODE
foreach ($l in $staleOut) { Say "    $l" }
$stale = $null
if ($null -eq $staleCode -or $staleCode -eq 0) {
    foreach ($l in $staleOut) {
        if ($l -match 'PUBLISH_STALE=([01])') { $stale = ($Matches[1] -eq '1') }
    }
}
if ($null -eq $stale) {
    Say "발행본이 최신인지 확인하지 못했습니다 — 발행하는 쪽으로 진행합니다." 'WARN'
    $stale = $true
}

# 발행할지 판단 — 분류 뒤에 둔다(위 주석 참고)
if ($added -eq 0 -and -not $requestsChanged -and $classified -eq 0 -and -not $stale) {
    Say "새 메시지도 멤버 요청 변경도 분류 변경도 없고 발행본도 최신이라 발행을 건너뜁니다."
    # 건너뛴 것은 실패가 아니다. 그래도 남긴다 — 이 기록이 없으면 화면은 '실패'와
    # '조용한 날'을 구분하지 못하고, 둘 다 '소식 없음'으로 보인다.
    Report-Run -status 'skipped' -why '발행 사유 없음' -added 0
    Say "===== 일일 갱신 종료 ====="
    exit 0
}
if ($added -eq 0) {
    if (-not $requestsChanged -and $classified -eq 0) {
        Say "새 메시지는 없지만 발행본이 로컬보다 뒤처져 있어 발행합니다."
    } else {
        Say "새 메시지는 없지만 멤버 요청 변경 또는 주제 분류가 있어 발행합니다."
    }
}

# 5b) 보조 분류 — 새로 생긴 주제만 판정한다(이미 물어본 주제는 다시 묻지 않는다).
#
#     실패해도 갱신을 멈추지 않는다. 보조 분류는 '여기서도 볼 만한 주제'라는
#     곁길일 뿐이고, 없으면 그 곁길만 안 생긴다. 다음 날 실행이 이어서 한다.
$prevEap = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try { $secOut = & { python -m scripts.assign_secondary } 2>&1 }
finally { $ErrorActionPreference = $prevEap }
$secCode = $LASTEXITCODE
foreach ($l in $secOut) { Say "    $l" }
if ($null -ne $secCode -and $secCode -ne 0) {
    Say "보조 분류가 실패했습니다 (exit $secCode) — 곁길 없이 계속합니다." 'WARN'
}

# 6) 갤러리용 작은 사진 — 발행본을 만들기 전에 있어야 한다
#
#    없으면 화면이 원본을 그대로 내려받는다. 22MB 사진을 200px 칸에 넣으려고 22MB 를
#    받는 셈이다(실측 2026-07-27: 사진 312장이 462MB, 작은 사진으로는 5MB).
#    이미 있는 것은 건너뛰므로 새로 들어온 사진만 만든다 — 조용한 날은 거의 0초다.
Invoke-Step '작은 사진 생성' { python -m scripts.build_thumbnails } | Out-Null

# 6b) 사진 속 개인정보 검사 — 발행본을 만들기 **전**이어야 한다
#
#     판정 결과(output/image_pii.json)를 build_firestore_payload 가 읽어 업로드
#     목록에서 뺀다. 뒤에 두면 그날 사진이 검사 없이 올라간다.
#
#     이미 읽은 사진은 건너뛰므로 새로 들어온 것만 OCR 한다(조용한 날 거의 0초).
#
#     실패하면 **멈춘다**. 분류·보조분류와 다르게 삼키지 않는다 — 그 둘은 없으면
#     곁길이 안 생길 뿐이지만, 이 검사가 빠진 채 발행하면 검사받지 않은 새 사진이
#     그대로 올라간다. 되돌릴 수 없는 쪽이므로 발행을 하루 미루는 편이 맞다.
Invoke-Step '사진 개인정보 검사' {
    powershell -ExecutionPolicy Bypass -File scripts\ocr_images.ps1
    if ($LASTEXITCODE -eq 0) { python -m scripts.scan_image_pii }
} | Out-Null

# 7) 발행본 재생성
Invoke-Step '발행본 생성' { python -m scripts.build_firestore_payload } | Out-Null

# 8) 정합성 확인 — 파이썬(발행본 무결성) + 노드(증분 적재 규칙)
#
#    **적재보다 먼저** 돈다. 예전에는 적재 뒤였는데, 그러면 검사가 잘못된 발행을
#    막지 못한다 — 이미 올라간 뒤에 "틀렸다"고 말하는 셈이다(2026-07-27 사람 노드
#    누락이 정확히 그 꼴이었다). Invoke-Step 이므로 실패하면 여기서 멈추고, 그날의
#    발행은 건너뛴다. 원본은 그대로 남으므로 고친 뒤 다시 돌리면 된다.
Invoke-Step '테스트' { python -m unittest discover -s tests } | Out-Null
Invoke-Step '테스트(적재)' { npm test --silent } | Out-Null

#    인용이 실제 발언인지 원문과 대조한다. 원문을 발행하지 않는 아카이브에서 보고서는
#    유일한 기록이고, 인용은 '이 사람이 이렇게 말했다'는 가장 강한 주장이다. 지어낸
#    인용은 사람의 말을 왜곡해 남기므로 가장 되돌리기 어렵다.
#    **갱신을 멈추지는 않는다** — 판정에 애매한 구석이 있어(같은 사람의 연속 발언을
#    이어붙인 인용 등) 여기서 멈추면 정상인 날에도 발행이 막힌다. 로그로 알린다.
$prevEap = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try { $quoteOut = & { python -m scripts.audit_quotes } 2>&1 }
finally { $ErrorActionPreference = $prevEap }
foreach ($l in $quoteOut) {
    if ($l -match '못 찾은 인용|자 초과') { Say "    [인용 검사] $l" 'WARN' }
}

# 9) Firestore·Storage 적재
Invoke-Step 'Firestore 적재' { node scripts\upload_firestore.js } | Out-Null

# 무엇 때문에 발행했는지 남긴다. '새 메시지 0 건 발행' 만 적히면 로그를 보는 사람이
# 헛돌았다고 읽는다 — 뒤처진 발행본을 따라잡은 날이 실제로 그 꼴이다.
$why = @()
if ($added -gt 0) { $why += "새 메시지 $added 건" }
if ($requestsChanged) { $why += "멤버 요청 변경" }
if ($classified -gt 0) { $why += "분류 $classified 건" }
if ($stale) { $why += "뒤처진 발행본 따라잡기" }
# 발행 사유는 아니지만 같은 줄에 얹는다 — 여기가 사람이 실제로 보는 유일한 자리다.
if ($script:drawerWarn) { $why += "⚠ $($script:drawerWarn)" }
Say ("===== 일일 갱신 완료: {0} 발행 =====" -f ($why -join ', '))
Report-Run -status 'ok' -why ($why -join ', ') -added $added

# 11) 작업 폴더 마름질 — 적재가 끝난 뒤에 한다
#
#     `abort-*.png` 가 급한 이유는 용량이 아니다. 자동화가 멈출 때 무슨 화면이었는지
#     남기려고 찍은 것인데 그 화면이 카톡 대화창이다 — 대화 내용이 담긴 이미지가
#     평문으로 무기한 남았다(실측 2026-08-22: 14장, 가장 오래된 것이 넉 주째).
#     발행본에서는 사진 속 개인정보까지 OCR 로 걸러내면서 진단 스크린샷은 그대로
#     둔 셈이었다.
#
#     적재 **뒤**에 두는 이유: 마름질이 잘못돼도 그날 발행은 이미 끝나 있어야 한다.
#     앞에 두면 지우는 코드의 실수가 발행을 막는다.
#
#     자산 중복(766MB)은 여기서 건드리지 않는다. 해시를 다 계산해 1분 가까이 걸리고,
#     무엇보다 그 폴더들에 아카이브에 없는 사진·동영상이 섞여 있었다. 사람이 보고
#     판단할 일이라 손으로만 돌린다: python -m scripts.prune_workspace --assets
#
#     실패해도 갱신을 멈추지 않는다 — 마름질은 없으면 쌓일 뿐이다.
$prevEap = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try {
    $pruneArgs = @('-m', 'scripts.prune_workspace')
    if (-not $DryRun) { $pruneArgs += '--apply' }
    foreach ($l in (& python @pruneArgs 2>&1)) {
        if ($l -match '지움|합계|마름질할 것이 없습니다') { Say "    $l" }
    }
}
finally { $ErrorActionPreference = $prevEap }
# 미분류가 남았는지는 세어 보고 말한다.
#
# 예전에는 '새 메시지가 있으면' 무조건 이 줄을 찍었다. 사람이 주 1회 재분류하던
# 시절의 문구다. 5단계(주제 분류)가 파이프라인에 들어온 뒤로는 대부분의 날에 사실이
# 아니다 — 실측 2026-08-04: 새 글 23건이 그 자리에서 네 주제로 분류됐는데도
# '미분류가 생겼습니다' 가 찍혔다. 없는 일을 매일 찾게 만드는 줄은 진짜 경고까지
# 같이 흘려보게 한다.
#
# 적재가 끝난 뒤에 보므로 발행 판단에는 영향이 없다. 이 확인이 실패해도 갱신은
# 이미 끝났으니 경고만 남긴다.
$prevEap = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try { $unsortedOut = & { python -m scripts.count_unsorted } 2>&1 }
finally { $ErrorActionPreference = $prevEap }
$unsorted = $null
foreach ($l in $unsortedOut) {
    if ($l -match 'UNSORTED=(\d+)') { $unsorted = [int]$Matches[1] }
}
if ($null -eq $unsorted) {
    Say "미분류 스레드 수를 세지 못했습니다 (UNSORTED 표식 없음)." 'WARN'
} else {
    # 0개인 날에도 표식은 흘려보낸다.
    #
    # 이 줄을 읽는 쪽이 하나 더 있다 — '지금 갱신' 버튼의 감시 스크립트다. 화면에
    # "미분류가 몇 개 남았다"를 말하려면 '0' 과 '못 읽었다' 를 구분할 수 있어야
    # 하는데, 표식을 남을 때만 찍으면 그 둘이 똑같이 보인다. 사람이 읽을 목록은
    # 여전히 남아 있을 때만 찍는다 — 없는 날 매일 찍히면 진짜 경고가 묻힌다.
    Say "    UNSORTED=$unsorted"
    if ($unsorted -gt 0) {
        foreach ($l in $unsortedOut) { if ($l -notmatch 'UNSORTED=') { Say "    $l" } }
        Say "주제 분류가 필요한 '미분류' 스레드 $unsorted 개가 남아 있습니다 — 확인해 정리하세요."
    }
}

# $lock 을 명시적으로 닫지 않는다. 위쪽 exit 경로가 여럿이라 한 군데서 닫아도
# 새지 않게 만들 수 없고, 프로세스가 끝나면 OS 가 어차피 닫는다. 이 스크립트는
# 항상 `powershell -File` 로 자기 프로세스에서 돈다.
exit 0
