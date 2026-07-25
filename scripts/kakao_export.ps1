<#
카카오톡 '대화 내용 저장'을 자동 실행한다.

설계 원칙 — 추정 좌표로는 절대 클릭하지 않는다
  카카오톡 UI 는 접근성 API 에 아무것도 노출하지 않아(Button·MenuItem 0개)
  좌표 클릭이 불가피하다. 그런데 메뉴에서 '대화 내용' 바로 아래 약 50px 에
  '채팅방 나가기' 가 있어, 좌표가 조금만 밀려도 40명 방을 나가버린다.
  게다가 창은 실행 중에도 이동·리사이즈된다(실측: 960x1020 -> 570x960).

  그래서 모든 클릭은 다음을 통과해야만 실행한다.
    1) 창 제목이 정확히 일치하는지
    2) 창을 최상단으로 올렸는지 (다른 창 위로 클릭 방지)
    3) 클릭 지점의 글자를 OCR 로 읽어 기대한 항목인지
    4) 금지 단어('나가', '삭제', '신고')가 포함되면 즉시 중단
  하나라도 실패하면 클릭하지 않고 Esc 로 원상복구한다.

사용
  powershell -File scripts\kakao_export.ps1 -Discover   # 클릭 없이 메뉴만 관찰
  powershell -File scripts\kakao_export.ps1             # 실제 내보내기
#>
param(
    [switch]$Discover,                       # 관찰 전용: 메뉴를 열어 OCR 결과만 출력
    [string]$Room = '바이브코딩,업무자동화 화상회의모임',
    [string]$LogDir = 'logs',
    [string]$InboxDir = 'inbox'              # 내보낸 txt 를 받을 폴더
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $here 'kakao_ocr.ps1')

Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
if (-not ('Win32' -as [type])) {
    Add-Type -TypeDefinition @"
using System;using System.Runtime.InteropServices;
public class Win32 {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h,int c);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint x,uint y,uint d,int e);
  [DllImport("user32.dll")] public static extern short GetAsyncKeyState(int k);
}
"@
}

# 클릭을 절대 허용하지 않는 단어 — OCR 결과에 하나라도 있으면 중단
$FORBIDDEN = @('나가', '나기', '삭제', '신고', '차단', '초대')

function Write-Log { param([string]$m, [string]$level = 'INFO')
    $line = "[{0}] {1} {2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $level, $m
    Write-Host $line
    if ($script:LogFile) { Add-Content -Path $script:LogFile -Value $line -Encoding utf8 }
}

function Stop-Safely { param([string]$why)
    Write-Log "중단: $why" 'ABORT'
    try { [System.Windows.Forms.SendKeys]::SendWait('{ESC}') } catch {}
    exit 1
}

function Get-RoomWindow {
    $root = [System.Windows.Automation.AutomationElement]::RootElement
    $cond = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::NameProperty, $Room)
    $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $cond)
}

function Set-RoomForeground {
    param($win)
    $h = [IntPtr]$win.Current.NativeWindowHandle
    [void][Win32]::ShowWindow($h, 9)          # SW_RESTORE
    [void][Win32]::SetForegroundWindow($h)
    Start-Sleep -Milliseconds 500
    if ([Win32]::GetForegroundWindow() -ne $h) {
        Stop-Safely "창을 최상단으로 올리지 못했습니다(다른 창 위로 클릭할 위험)."
    }
}

function Invoke-ClickAt {
    param([int]$X, [int]$Y, [string]$label)
    Write-Log "클릭: $label ($X, $Y)"
    [System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point($X, $Y)
    Start-Sleep -Milliseconds 200
    [Win32]::mouse_event(0x0002, 0, 0, 0, 0)   # LEFTDOWN
    [Win32]::mouse_event(0x0004, 0, 0, 0, 0)   # LEFTUP
}

function Assert-DarkPixels {
    <# 지정 지점이 아이콘(어두운 픽셀)처럼 보이는지 확인 — 빈 배경 클릭 방지 #>
    param([int]$X, [int]$Y, [int]$Min = 25, [int]$Max = 220)
    $bmp = New-Object System.Drawing.Bitmap 26, 20
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen(($X - 13), ($Y - 10), 0, 0, (New-Object System.Drawing.Size 26, 20))
    $dark = 0
    for ($i = 0; $i -lt 26; $i++) { for ($j = 0; $j -lt 20; $j++) {
        $c = $bmp.GetPixel($i, $j); if ((($c.R + $c.G + $c.B) / 3) -lt 150) { $dark++ } } }
    $g.Dispose(); $bmp.Dispose()
    Write-Log "픽셀 검증: 어두운 픽셀 $dark/520"
    if ($dark -lt $Min -or $dark -gt $Max) {
        Stop-Safely "지정 지점이 예상 아이콘과 다릅니다(어두운 픽셀 $dark). 레이아웃이 바뀐 듯합니다."
    }
}

function Find-MenuLine {
    <#
      OCR 결과에서 원하는 항목을 찾는다.
      - 필수 단어를 모두 포함해야 한다
      - 금지 단어가 있으면 그 줄은 후보에서 제외
      - 후보가 정확히 1개가 아니면 중단(모호하면 클릭하지 않는다)
    #>
    param($lines, [string[]]$Must, [string]$what)
    $cands = @()
    foreach ($l in $lines) {
        $t = $l.text
        $bad = $false
        foreach ($f in $FORBIDDEN) { if ($t -like "*$f*") { $bad = $true } }
        if ($bad) { continue }
        $ok = $true
        foreach ($m in $Must) { if ($t -notlike "*$m*") { $ok = $false } }
        if ($ok) { $cands += $l }
    }
    if ($cands.Count -eq 0) { Stop-Safely "'$what' 항목을 화면에서 찾지 못했습니다." }
    if ($cands.Count -gt 1) {
        Write-Log ("후보 여러 개: " + (($cands | ForEach-Object { "'$($_.text)'@y=$($_.y)" }) -join ', ')) 'WARN'
        Stop-Safely "'$what' 후보가 $($cands.Count)개로 모호합니다."
    }
    Write-Log "확인: '$what' -> '$($cands[0].text)' at ($($cands[0].x), $($cands[0].y))"
    $cands[0]
}

function Wait-SaveDialog {
    <#
      표준 저장 대화상자를 기다린다. 커스텀 UI 와 달리 이건 접근성 API 로
      안전하게 다룰 수 있어(Edit·Button 노출) 좌표 클릭이 필요 없다.
    #>
    param([int]$TimeoutSec = 20)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    $root = [System.Windows.Automation.AutomationElement]::RootElement
    while ((Get-Date) -lt $deadline) {
        $cond = New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
            [System.Windows.Automation.ControlType]::Window)
        $wins = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $cond)
        for ($i = 0; $i -lt $wins.Count; $i++) {
            $w = $wins.Item($i)
            $cls = $w.Current.ClassName
            $nm = $w.Current.Name
            # 윈도우 공용 파일 대화상자: #32770 (Dialog)
            if ($cls -eq '#32770') {
                Write-Log "저장 대화상자 발견: '$nm' (class=$cls)"
                return $w
            }
        }
        Start-Sleep -Milliseconds 400
    }
    $null
}

function Save-Dialog-To {
    <# 저장 대화상자의 파일명 칸에 전체 경로를 넣고 저장한다. #>
    param($dlg, [string]$Directory)

    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $file = Join-Path $Directory "KakaoTalkExport-$stamp.txt"

    # 파일 이름 입력 칸(Edit) 찾기
    $econd = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::Edit)
    $edit = $dlg.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $econd)
    if ($null -eq $edit) { Stop-Safely "저장 대화상자에서 파일명 입력 칸을 찾지 못했습니다." }

    $vp = $edit.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
    $vp.SetValue($file)
    Write-Log "파일명 설정: $file"
    Start-Sleep -Milliseconds 300

    # 저장 버튼 찾기 (이름이 '저장' 또는 'Save')
    $bcond = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::Button)
    $btns = $dlg.FindAll([System.Windows.Automation.TreeScope]::Descendants, $bcond)
    $saveBtn = $null
    for ($i = 0; $i -lt $btns.Count; $i++) {
        $n = $btns.Item($i).Current.Name
        if ($n -like '*저장*' -or $n -like '*Save*') { $saveBtn = $btns.Item($i); break }
    }
    if ($null -eq $saveBtn) { Stop-Safely "저장 대화상자에서 저장 버튼을 찾지 못했습니다." }

    Write-Log "저장 버튼 클릭: '$($saveBtn.Current.Name)'"
    $ip = $saveBtn.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
    $ip.Invoke()
    $file
}

# ───────────────────────── 실행 ─────────────────────────
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Force $LogDir | Out-Null }
if (-not (Test-Path $InboxDir)) { New-Item -ItemType Directory -Force $InboxDir | Out-Null }
$script:LogFile = Join-Path $LogDir ("kakao-export-{0}.log" -f (Get-Date -Format 'yyyyMMdd'))

Write-Log "=== 카카오톡 대화 내보내기 시작 (Discover=$Discover) ==="

$win = Get-RoomWindow
if ($null -eq $win) { Stop-Safely "'$Room' 창을 찾을 수 없습니다. 카카오톡에서 해당 방을 열어두세요." }
Set-RoomForeground $win

$r = $win.Current.BoundingRectangle
Write-Log "창 위치: x=$([int]$r.X) y=$([int]$r.Y) w=$([int]$r.Width) h=$([int]$r.Height)"

# 1) 햄버거 메뉴 — 창 우측 끝에서 31px, 상단에서 85px (상대 좌표라 창 이동에 안전)
$hx = [int]($r.X + $r.Width - 31)
$hy = [int]($r.Y + 85)
Assert-DarkPixels -X $hx -Y $hy
Invoke-ClickAt -X $hx -Y $hy -label '햄버거 메뉴'
Start-Sleep -Milliseconds 800

# 2) 메뉴 OCR — 메뉴는 햄버거 아래로 펼쳐진다
$mx = [int]($r.X + $r.Width - 380)
$my = $hy
$lines = Get-ScreenOcr -X $mx -Y $my -Width 380 -Height 520 -Scale 2
Write-Log "메뉴 OCR: $($lines.Count)줄"
foreach ($l in $lines) { Write-Log ("   y={0}  '{1}'" -f $l.y, $l.text) }

if ($Discover) {
    Write-Log "관찰 모드 — 클릭하지 않고 종료합니다."
    [System.Windows.Forms.SendKeys]::SendWait('{ESC}')
    exit 0
}

# 3) '대화 내용' 항목 클릭 (금지 단어 필터가 '채팅방 나가기'를 원천 배제)
$target = Find-MenuLine -lines $lines -Must @('대화', '내용') -what '대화 내용'
Invoke-ClickAt -X $target.x -Y $target.y -label "메뉴 항목 '$($target.text)'"
Start-Sleep -Milliseconds 900

# 4) 하위 메뉴에서 '대화 내보내기' 클릭
#    하위 메뉴는 클릭 지점 주변에 열리므로 넉넉한 범위를 OCR 한다.
$sx = [int]([Math]::Max(0, $target.x - 420))
$sy = [int]([Math]::Max(0, $target.y - 160))
$sub = Get-ScreenOcr -X $sx -Y $sy -Width 620 -Height 340 -Scale 2
Write-Log "하위 메뉴 OCR: $($sub.Count)줄"
foreach ($l in $sub) { Write-Log ("   y={0}  '{1}'" -f $l.y, $l.text) }

# '내보내기' 를 필수 단어로 삼는다. 금지 단어 필터가 여전히 위험 항목을 배제한다.
$exp = Find-MenuLine -lines $sub -Must @('내보내기') -what '대화 내보내기'
Invoke-ClickAt -X $exp.x -Y $exp.y -label "하위 항목 '$($exp.text)'"
Start-Sleep -Milliseconds 1200

# 5) 저장 대화상자 처리 — 표준 윈도우 대화상자이므로 접근성 API 로 안전하게 다룬다
$dlg = Wait-SaveDialog -TimeoutSec 20
if ($null -eq $dlg) {
    # 대화상자가 아니라 형식 선택 창일 수 있으니 화면을 기록해 둔다
    $now = Get-ScreenOcr -X 0 -Y 0 -Width ([int][System.Windows.Forms.SystemInformation]::VirtualScreen.Width) `
                         -Height ([int][System.Windows.Forms.SystemInformation]::VirtualScreen.Height) -Scale 1
    Write-Log "저장 대화상자를 찾지 못했습니다. 현재 화면:" 'WARN'
    foreach ($l in $now) { Write-Log ("   y={0}  '{1}'" -f $l.y, $l.text) }
    Stop-Safely "저장 대화상자를 찾지 못했습니다(형식 선택 단계가 있을 수 있음). 로그를 확인하세요."
}

$savePath = Save-Dialog-To -dlg $dlg -Directory (Resolve-Path $InboxDir).Path
Write-Log "저장 요청 경로: $savePath"

# 6) 파일이 실제로 생겼는지 확인
$deadline = (Get-Date).AddSeconds(60)
$saved = $null
while ((Get-Date) -lt $deadline) {
    if (Test-Path $savePath) {
        $len1 = (Get-Item $savePath).Length
        Start-Sleep -Milliseconds 800
        $len2 = (Get-Item $savePath).Length
        if ($len1 -eq $len2 -and $len2 -gt 0) { $saved = $savePath; break }
    }
    Start-Sleep -Milliseconds 500
}
if (-not $saved) { Stop-Safely "저장이 완료되지 않았습니다: $savePath" }

$size = (Get-Item $saved).Length
Write-Log "내보내기 완료: $saved ($([Math]::Round($size/1KB,1)) KB)"
Write-Log "=== 카카오톡 대화 내보내기 정상 종료 ==="
exit 0
