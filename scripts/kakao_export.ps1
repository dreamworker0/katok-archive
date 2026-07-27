<#
카카오톡 '대화 내보내기'를 자동 실행한다.

설계 — 메뉴를 클릭하지 않고 단축키(Ctrl+S)를 쓴다
  실측으로 확인한 사실:
    · 카톡 UI 는 접근성 API 에 아무것도 노출하지 않는다(Button·MenuItem 0개)
    · 메뉴에서 '대화 내용' 아래 약 50px 에 '채팅방 나가기' 가 있고,
      하위 메뉴에는 '대화 내용 모두 삭제' 가 있다
    · 창은 실행 중에도 이동·리사이즈된다(960x1020 -> 570x960)
    · 그리고 '대화 내보내기' 에는 단축키 **Ctrl+S** 가 있다

  그래서 좌표 클릭을 전부 버리고 Ctrl+S 한 번만 보낸다. 위험한 메뉴 항목을
  아예 지나가지 않으므로 오클릭으로 방을 나가거나 대화를 삭제할 경로가 없다.

  남은 안전장치
    1) 창 제목이 정확히 일치하는지 확인
    2) 그 창이 실제로 최상단인지 확인 (다른 앱에 Ctrl+S 를 보내지 않도록)
    3) 저장 대화상자(표준 #32770)가 떴는지 확인 — 안 뜨면 아무 것도 하지 않고 중단
    4) 저장 대화상자는 접근성 API 로 다룬다(좌표 클릭 없음)
    5) 파일이 실제로 생기고 크기가 안정될 때까지 확인

사용
  powershell -File scripts\kakao_export.ps1            # 내보내기 실행
  powershell -File scripts\kakao_export.ps1 -Discover  # 창·단축키 확인만 (전송 안 함)
#>
param(
    [switch]$Discover,
    [string]$Room = '바이브코딩,업무자동화 화상회의모임',
    [string]$LogDir = 'logs',
    [string]$InboxDir = 'inbox'
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, System.Windows.Forms, System.Drawing

if (-not ('Win32' -as [type])) {
    Add-Type -TypeDefinition @"
using System;using System.Runtime.InteropServices;
public class Win32 {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h,int c);
  [DllImport("user32.dll")] static extern void mouse_event(uint f,uint x,uint y,uint d,int e);
  public static void MouseClick(){ mouse_event(0x0002,0,0,0,0); mouse_event(0x0004,0,0,0,0); }
  [DllImport("user32.dll")] static extern void keybd_event(byte k,byte s,uint f,IntPtr e);
  // Windows 는 포그라운드가 아닌 프로세스의 SetForegroundWindow 를 거부한다.
  // Alt 를 한 번 눌러주면 포그라운드 전환이 허용되는 것이 표준 우회법이다.
  public static void NudgeAlt(){ keybd_event(0x12,0,0,IntPtr.Zero); keybd_event(0x12,0,2,IntPtr.Zero); }
  [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
  [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, IntPtr pid);
  [DllImport("user32.dll")] static extern bool AttachThreadInput(uint from, uint to, bool attach);
  [DllImport("kernel32.dll")] static extern uint GetCurrentThreadId();

  // Windows 는 포그라운드가 아닌 프로세스의 SetForegroundWindow 를 거부한다.
  // 대상 창의 입력 스레드에 우리 스레드를 붙이면(AttachThreadInput) 허용된다.
  // Ctrl+S 를 실제 키 이벤트로 보낸다.
  // SendKeys 는 Alt 선행 입력 뒤에 삼켜지는 경우가 있었다(실측).
  public static void CtrlS(){
    keybd_event(0x11,0,0,IntPtr.Zero);        // Ctrl down
    System.Threading.Thread.Sleep(60);
    keybd_event(0x53,0,0,IntPtr.Zero);        // S down
    System.Threading.Thread.Sleep(60);
    keybd_event(0x53,0,2,IntPtr.Zero);        // S up
    System.Threading.Thread.Sleep(40);
    keybd_event(0x11,0,2,IntPtr.Zero);        // Ctrl up
  }
  [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X; public int Y; }
  [DllImport("user32.dll")] static extern IntPtr WindowFromPoint(POINT p);
  [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);

  // 그 화면 좌표에 실제로 '보이는' 창의 소유 프로세스. 창이 없으면 0.
  //
  // 포그라운드와 다른 개념이다. '항상 위' 창은 포그라운드가 아니어도 남의 창 위에
  // 그려지므로, 좌표를 클릭하면 그쪽이 맞는다.
  public static uint PidAt(int x, int y){
    POINT p; p.X = x; p.Y = y;
    IntPtr h = WindowFromPoint(p);
    if (h == IntPtr.Zero) return 0;
    uint pid = 0; GetWindowThreadProcessId(h, out pid); return pid;
  }
  public static bool ForceForeground(IntPtr h){
    uint target = GetWindowThreadProcessId(h, IntPtr.Zero);
    uint me = GetCurrentThreadId();
    bool attached = (target != me) && AttachThreadInput(me, target, true);
    try {
      ShowWindow(h, 9);
      BringWindowToTop(h);
      NudgeAlt();
      SetForegroundWindow(h);
    } finally {
      if (attached) AttachThreadInput(me, target, false);
    }
    return GetForegroundWindow() == h;
  }
}
"@
}
if (-not ('U32' -as [type])) {
    Add-Type -TypeDefinition @"
using System;using System.Runtime.InteropServices;
public class U32 {
  [DllImport("user32.dll")] public static extern int SendMessage(IntPtr h,uint m,IntPtr w,IntPtr l);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h,uint m,IntPtr w,IntPtr l);
  [DllImport("user32.dll")] public static extern bool IsWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetWindow(IntPtr h,uint c);
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc p, IntPtr l);

  // 특정 창이 '소유한' 팝업 목록. 카톡의 내보내기 알림이 여기에 해당한다.
  public static System.Collections.Generic.List<IntPtr> OwnedPopups(IntPtr owner){
    var list = new System.Collections.Generic.List<IntPtr>();
    EnumWindows(delegate(IntPtr h, IntPtr l){
      if (h != owner && GetWindow(h, 4) == owner) list.Add(h);   // 4 = GW_OWNER
      return true;
    }, IntPtr.Zero);
    return list;
  }
}
"@
}

function Write-Log { param([string]$m, [string]$level = 'INFO')
    $line = "[{0}] {1} {2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $level, $m
    Write-Host $line
    if (-not $script:LogFile) { return }

    # 로그를 못 써도 실행은 계속한다.
    #
    # $ErrorActionPreference = 'Stop' 이라 Add-Content 실패는 스크립트를 그 자리에서
    # 죽인다. 실측(2026-07-27): 진행 상황을 보려고 로그를 `tail -f` 로 열어둔 것만으로
    # 내보내기가 첫 줄에서 죽었다 — 그 잠금이 Add-Content 를 막았다. 백신·백업·
    # 편집기도 같은 일을 한다.
    #
    # 진단을 남기려고 둔 코드가 실행을 멈추는 것은 앞뒤가 맞지 않는다. 짧게 몇 번
    # 다시 시도하고, 그래도 안 되면 화면에만 남기고 나아간다. 로그가 없는 것은
    # 불편한 일이지만, 그날 갱신이 없는 것은 되돌릴 수 없는 손해다.
    for ($i = 0; $i -lt 3; $i++) {
        try {
            Add-Content -Path $script:LogFile -Value $line -Encoding utf8
            return
        } catch {
            Start-Sleep -Milliseconds 150
        }
    }
    if (-not $script:LogWriteWarned) {
        $script:LogWriteWarned = $true
        Write-Host "  (로그 파일이 잠겨 있어 화면에만 남깁니다 — 다른 프로그램이 열고 있는지 보세요)"
    }
}

function Save-Screenshot { param([string]$tag)
    try {
        $vs = [System.Windows.Forms.SystemInformation]::VirtualScreen
        $bmp = New-Object System.Drawing.Bitmap $vs.Width, $vs.Height
        $g = [System.Drawing.Graphics]::FromImage($bmp)
        $g.CopyFromScreen($vs.X, $vs.Y, 0, 0, (New-Object System.Drawing.Size $vs.Width, $vs.Height))
        $g.Dispose()
        $p = Join-Path $script:LogDirResolved ("{0}-{1}.png" -f $tag, (Get-Date -Format 'yyyyMMdd-HHmmss'))
        $bmp.Save($p, [System.Drawing.Imaging.ImageFormat]::Png); $bmp.Dispose()
        Write-Log "화면 저장: $p"
    } catch { Write-Log "화면 저장 실패: $($_.Exception.Message)" 'WARN' }
}

function Stop-Safely { param([string]$why)
    Write-Log "중단: $why" 'ABORT'
    Save-Screenshot -tag 'abort'
    # Esc 를 보내지 않는다 — 카카오톡에서 Esc 는 대화방 창을 닫아버린다.
    # 매일 자동 실행하려면 방 창이 열린 채로 남아 있어야 한다.
    exit 1
}

function Get-RoomWindow {
    $root = [System.Windows.Automation.AutomationElement]::RootElement
    $cond = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::NameProperty, $Room)
    $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $cond)
}

function Find-ByClassAndId {
    <# 하위 트리에서 (win32 클래스, AutomationId) 로 컨트롤을 찾는다. #>
    param($parent, [string]$Class, [string]$Id)
    $a = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ClassNameProperty, $Class)
    $b = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::AutomationIdProperty, $Id)
    $parent.FindFirst([System.Windows.Automation.TreeScope]::Descendants,
        (New-Object System.Windows.Automation.AndCondition($a, $b)))
}

function Wait-SaveDialog {
    <#
      '다른 이름으로 저장' 대화상자를 찾는다.

      실측으로 확인한 구조 (Windows 10 / 카카오톡):
        · 대화상자는 데스크톱의 직접 자식이 아니라 **하위(Descendants)** 에 있다
          -> Children 으로 찾으면 못 찾는다
        · 클래스는 '#32770', 소유 프로세스는 카카오톡
        · 내부 컨트롤이 Edit/Button 타입이 아니라 **Pane** 으로 노출된다
          -> ControlType 으로 찾으면 파일목록 컬럼만 잡힌다.
             win32 클래스 + AutomationId 로 찾아야 한다:
               파일 이름 칸 = class 'Edit',   id '1001'
               저장 버튼    = class 'Button', id '1'
    #>
    param([int]$TimeoutSec = 20, [int]$OwnerPid)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    $root = [System.Windows.Automation.AutomationElement]::RootElement
    $cond = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ClassNameProperty, '#32770')
    while ((Get-Date) -lt $deadline) {
        $dlgs = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond)
        for ($i = 0; $i -lt $dlgs.Count; $i++) {
            $d = $dlgs.Item($i)
            if ($d.Current.ProcessId -ne $OwnerPid) { continue }   # 카톡 소유만
            $edit = Find-ByClassAndId $d 'Edit' '1001'
            $btn = Find-ByClassAndId $d 'Button' '1'
            if ($edit -and $btn) {
                Write-Log "저장 대화상자 발견: '$($d.Current.Name)' (기본 파일명='$($edit.Current.Name)')"
                return @{ dialog = $d; edit = $edit; button = $btn }
            }
        }
        Start-Sleep -Milliseconds 400
    }
    $null
}

function Invoke-SaveDialog {
    <#
      기본 파일명·기본 폴더로 저장한 뒤, 새로 생긴 파일을 inbox 로 옮긴다.

      파일명을 읽거나 쓰지 않는다:
        · 파일명 칸의 UIA Name 은 비어 있을 때 라벨('파일 이름:')을 돌려준다(실측)
        · Vista 스타일 대화상자의 자동완성 Edit 에는 WM_SETTEXT 가 먹지 않는다(실측)
      그래서 저장 전 폴더 상태를 기록해 두고, 저장 후 **새로 생긴 txt** 를 찾는다.
      카톡이 붙이는 기본 이름(KakaoTalk_날짜_시각_group.txt)이 그대로 쓰이므로
      파일명 충돌도 사실상 없다.
    #>
    param($found, [string]$Directory)

    $docs = [Environment]::GetFolderPath('MyDocuments')
    $before = @{}
    Get-ChildItem $docs -Filter *.txt -ErrorAction SilentlyContinue |
        ForEach-Object { $before[$_.Name] = $true }
    Write-Log "저장 전 문서 폴더 txt: $($before.Count)개"

    $bh = [IntPtr]$found.button.Current.NativeWindowHandle
    Write-Log "저장 버튼 클릭 (BM_CLICK)"
    [void][U32]::SendMessage($bh, 0x00F5, [IntPtr]::Zero, [IntPtr]::Zero)

    # 새로 생긴 파일을 찾고, 크기가 안정될 때까지 기다린다
    $deadline = (Get-Date).AddSeconds(120)
    $newFile = $null
    while ((Get-Date) -lt $deadline) {
        $cand = Get-ChildItem $docs -Filter *.txt -ErrorAction SilentlyContinue |
            Where-Object { -not $before.ContainsKey($_.Name) } |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($cand) {
            $a = $cand.Length
            Start-Sleep -Milliseconds 900
            $cand.Refresh()
            if ($cand.Length -eq $a) { $newFile = $cand; break }
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $newFile) { Stop-Safely "저장된 파일을 찾지 못했습니다(문서 폴더에 새 txt 없음)." }
    Write-Log "저장 확인: $($newFile.Name) ($([Math]::Round($newFile.Length/1KB,1)) KB)"

    $dest = Join-Path $Directory $newFile.Name
    if (Test-Path $dest) {
        $dest = Join-Path $Directory ("{0}-{1}.txt" -f
            [IO.Path]::GetFileNameWithoutExtension($newFile.Name), (Get-Date -Format 'HHmmss'))
    }
    Move-Item -LiteralPath $newFile.FullName -Destination $dest -Force
    Write-Log "inbox 로 이동: $dest"
    $dest
}

function Close-OwnedPopups {
    <#
      방 창이 소유한 팝업을 닫는다.

      카톡의 '대화 내보내기 / 완료되었습니다' 알림은 방 창이 소유한 WS_POPUP 이고,
      접근성 API 에 전혀 노출되지 않으며(자식 컨트롤 0개) 화면에도 잔상만 남는
      경우가 있다. 그런데 이 팝업이 살아 있으면 방 창이 포커스를 받지 못해
      다음 실행에서 Ctrl+S 가 동작하지 않는다(실측: 성공/실패가 번갈아 발생).

      소유자가 방 창인 팝업만 WM_CLOSE 로 닫으므로, 카톡 메인 창이나 다른 앱은
      건드리지 않는다.
    #>
    param([IntPtr]$RoomHandle, [string]$When)
    $popups = [U32]::OwnedPopups($RoomHandle)
    if ($popups.Count -eq 0) { return 0 }
    Write-Log "$When 방 창 소유 팝업 $($popups.Count)개 발견 - 닫습니다"
    $closed = 0
    foreach ($ph in $popups) {
        [void][U32]::PostMessage($ph, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero)   # WM_CLOSE
        $closed++
    }
    Start-Sleep -Milliseconds 1200
    $left = [U32]::OwnedPopups($RoomHandle)
    Write-Log ("  닫음 {0}개, 남은 팝업 {1}개" -f $closed, $left.Count)
    $closed
}

# ───────────────────────── 실행 ─────────────────────────
Set-Location (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Force $LogDir | Out-Null }
if (-not (Test-Path $InboxDir)) { New-Item -ItemType Directory -Force $InboxDir | Out-Null }
$script:LogDirResolved = (Resolve-Path $LogDir).Path
$script:LogFile = Join-Path $script:LogDirResolved ("kakao-export-{0}.log" -f (Get-Date -Format 'yyyyMMdd'))

Write-Log "=== 대화 내보내기 시작 (Discover=$Discover) ==="

# 1) 방 창 확인
$win = Get-RoomWindow
if ($null -eq $win) { Stop-Safely "'$Room' 창을 찾을 수 없습니다. 카카오톡에서 해당 방을 열어두세요." }
$h = [IntPtr]$win.Current.NativeWindowHandle
$r = $win.Current.BoundingRectangle
Write-Log "창 확인: '$($win.Current.Name)' (x=$([int]$r.X) y=$([int]$r.Y) w=$([int]$r.Width) h=$([int]$r.Height))"

# 2) 잔여 팝업 정리 — 남아 있으면 방 창이 포커스를 받지 못한다
[void](Close-OwnedPopups -RoomHandle $h -When '시작 시')

# 3) 최상단 확보 — 다른 앱에 Ctrl+S 를 보내면 안 된다.
#    SetForegroundWindow 는 호출자가 포그라운드가 아니면 윈도우가 거부하므로(실측)
#    Alt 를 눌러 전환을 허용시키고 여러 번 시도한다.
$ok = $false
for ($try = 1; $try -le 5; $try++) {
    if ([Win32]::ForceForeground($h)) { $ok = $true; break }
    Start-Sleep -Milliseconds 400
    if ([Win32]::GetForegroundWindow() -eq $h) { $ok = $true; break }
    Write-Log "최상단 전환 재시도 $try/5" 'WARN'
}
if (-not $ok) {
    Stop-Safely "방 창을 최상단으로 올리지 못했습니다. 다른 앱에 단축키가 갈 위험이 있어 중단합니다."
}
$kakaoPid = $win.Current.ProcessId
Write-Log "최상단 확보 확인 (카톡 PID=$kakaoPid)"

if ($Discover) {
    Write-Log "관찰 모드 — Ctrl+S 를 보내지 않고 종료합니다."
    exit 0
}

# 3) Ctrl+S — '대화 내보내기' 단축키. 메뉴를 지나가지 않으므로 위험 항목에 닿지 않는다.
# 창을 앞으로 올리는 것만으로는 Ctrl+S 가 먹지 않았다(실측).
# 창 내부 포커스가 필요하므로 메시지 입력칸을 한 번 클릭한다.
# 입력칸 클릭은 커서만 놓는 동작이라 안전하다 — Enter 는 절대 보내지 않는다.
$ix = [int]($r.X + 60)
$iy = [int]($r.Y + $r.Height - 145)

# 좌표를 그냥 클릭하지 않는다 — 그 자리에 다른 창이 덮여 있을 수 있다.
#
# '최상단 확보'를 통과했는데도 실패한 적이 있다(실측 2026-07-27). 작업 관리자의
# '항상 위' 옵션이 켜져 있으면 카톡이 포그라운드여도 그 위에 그려진다. 그 상태로
# 좌표를 클릭하면 포커스가 작업 관리자로 넘어가고 Ctrl+S 도 거기로 간다 —
# 로그에는 "최상단 확보 확인" 다음에 "저장 대화상자가 뜨지 않았습니다" 만 남아
# 원인이 안 보였다.
#
# 그리고 이건 실패로 끝나는 것보다 나쁠 수 있다. 덮은 창이 편집기라면 Ctrl+S 가
# 남의 파일을 저장한다. 이 스크립트의 원칙은 '엉뚱한 창에 키를 보내지 않는다' 이므로,
# 포그라운드만 보지 말고 클릭할 자리가 실제로 카톡인지 확인한다.
$pidAt = [Win32]::PidAt($ix, $iy)
if ($pidAt -ne $kakaoPid) {
    $who = '알 수 없음'
    if ($pidAt -ne 0) {
        try { $who = (Get-Process -Id $pidAt -ErrorAction Stop).ProcessName } catch {}
    }
    Stop-Safely ("입력칸 자리($ix, $iy)가 다른 창에 덮여 있습니다 — '$who'(PID $pidAt). " +
        "'항상 위'로 떠 있는 창(작업 관리자 등)을 닫고 다시 시도하세요.")
}

Write-Log "메시지 입력칸 클릭으로 내부 포커스 확보 ($ix, $iy) — 그 자리 창 확인됨(카톡)"
[System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point($ix, $iy)
Start-Sleep -Milliseconds 250
[Win32]::MouseClick()
Start-Sleep -Milliseconds 500

Write-Log "Ctrl+S 전송 (대화 내보내기 단축키)"
[Win32]::CtrlS()

# 4) 저장 대화상자 대기 — 안 뜨면 아무 것도 하지 않고 중단
$dlg = Wait-SaveDialog -TimeoutSec 20 -OwnerPid $kakaoPid
if ($null -eq $dlg) {
    Stop-Safely ("저장 대화상자가 뜨지 않았습니다(단축키가 동작하지 않았을 수 있음). " +
        "클릭 직후에 다른 창이 앞으로 나왔거나, 시스템이 몹시 느려 20초 안에 " +
        "대화상자가 못 떴을 수 있습니다 — 남긴 화면을 확인하세요.")
}

$savePath = Invoke-SaveDialog -found $dlg -Directory (Resolve-Path $InboxDir).Path

# 완료 알림 닫기 — 남겨두면 다음 실행에서 포커스를 막는다
[void](Close-OwnedPopups -RoomHandle $h -When '저장 후')

$kb = [Math]::Round((Get-Item $savePath).Length / 1KB, 1)
$lines = (Get-Content -LiteralPath $savePath -Encoding utf8 | Measure-Object -Line).Lines
Write-Log "내보내기 완료: $savePath ($kb KB, $lines 줄)"
Write-Log "다음: python -m scripts.ingest_incremental"
Write-Log "=== 정상 종료 ==="
exit 0
