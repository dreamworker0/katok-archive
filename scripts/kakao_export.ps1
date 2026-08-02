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

방 창이 없으면 직접 연다 (2026-07-29 추가)
  2026-07-28 밤 갱신이 통째로 빠졌다. 방 창이 없어서 첫 줄에서 중단했다.
  방 창은 사람이 닫지 않아도 사라진다(실측) — '열어두면 된다' 는 전제로는
  매일 자동 실행이 성립하지 않으므로 없으면 열고 진행한다. Open-RoomWindow 참고.
    · 트레이 아이콘을 클릭하지 않는다 (숨겨진 메인 창에 ShowWindow)
    · 키를 보내지 않는다 (Enter 는 동작하지 않고, 타이핑은 메시지 전송 위험)
    · 목록은 '채팅' 탭의 것인지 이름으로 확인한다 (친구 목록과 클래스가 같다)
    · 클릭할 행은 OCR 로 읽어 고르고, 열린 창의 제목으로 최종 확인
  실패하면 예전과 똑같이 화면을 남기고 중단한다.

사용
  powershell -File scripts\kakao_export.ps1              # 내보내기 실행
  powershell -File scripts\kakao_export.ps1 -Discover    # 창 확인·방 열기까지만 (Ctrl+S 안 보냄)
  powershell -File scripts\kakao_export.ps1 -NoAutoOpen  # 방 창이 없으면 그냥 중단 (예전 동작)
#>
param(
    [switch]$Discover,
    [string]$Room = '바이브코딩,업무자동화 화상회의모임',
    [string]$LogDir = 'logs',
    [string]$InboxDir = 'inbox',
    # 방 창이 없을 때 채팅 목록을 몇 화면까지 훑을지. 방은 최근 대화 순으로
    # 자리가 바뀌므로 맨 위에 있다고 가정하지 않는다.
    [int]$MaxScrollPages = 5,
    # 방 창이 없어도 직접 열지 않고 중단한다(예전 동작).
    [switch]$NoAutoOpen
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, System.Windows.Forms, System.Drawing

if (-not ('Win32' -as [type])) {
    Add-Type -TypeDefinition @"
using System;using System.Text;using System.Runtime.InteropServices;
public class Win32 {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h,int c);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h,uint m,IntPtr w,IntPtr l);
  [DllImport("user32.dll")] static extern void mouse_event(uint f,uint x,uint y,uint d,int e);
  public static void MouseClick(){ mouse_event(0x0002,0,0,0,0); mouse_event(0x0004,0,0,0,0); }

  // 채팅 목록에서 방을 여는 동작. 카톡 목록은 더블클릭으로 방 창을 띄운다(실측).
  public static void MouseDoubleClick(){
    mouse_event(0x0002,0,0,0,0); mouse_event(0x0004,0,0,0,0);
    System.Threading.Thread.Sleep(80);
    mouse_event(0x0002,0,0,0,0); mouse_event(0x0004,0,0,0,0);
  }
  // 채팅 목록 스크롤.
  //
  // 실제 휠 입력(mouse_event)은 이 컨트롤에서 완전히 무시된다(실측 2026-07-29:
  // 커서를 목록 위에 올리고 15번 굴려도 화면이 한 픽셀도 바뀌지 않았다).
  // WM_VSCROLL·PageDown·End 도 듣지 않는다. WM_MOUSEWHEEL 을 컨트롤 핸들로
  // 직접 보내는 것만 동작한다.
  //
  // 이 방식은 더 안전하기도 하다 — 커서를 어디에도 올리지 않으므로 스크롤이
  // 다른 창에 닿을 수 없다. lParam 은 WM_MOUSEWHEEL 규약상 화면 좌표다.
  public static void ScrollList(IntPtr list, int notches, bool down, int screenX, int screenY){
    IntPtr wp = (IntPtr)((down ? -120 : 120) << 16);
    IntPtr lp = (IntPtr)((screenY << 16) | (screenX & 0xFFFF));
    for (int i = 0; i < notches; i++) {
      PostMessage(list, 0x020A, wp, lp);      // WM_MOUSEWHEEL
      System.Threading.Thread.Sleep(80);
    }
  }

  [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc p,IntPtr l);
  [DllImport("user32.dll")] public static extern int GetClassName(IntPtr h,StringBuilder s,int m);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h,StringBuilder s,int m);
  public delegate bool EnumProc(IntPtr h,IntPtr l);

  // 카카오톡의 '메인 창'(채팅 목록) 핸들.
  //
  // 트레이로 내려간 상태에서도 이 창은 최상위 창으로 살아 있고 숨겨져 있을 뿐이다(실측).
  // 트레이 아이콘 클릭이 하는 일이 바로 이 창의 ShowWindow 이므로, 핸들로 직접 부르면
  // 알림 영역 좌표·아이콘 순서·숨김 영역에 전혀 의존하지 않는다.
  public static IntPtr KakaoMain(){
    IntPtr found = IntPtr.Zero;
    EnumWindows(delegate(IntPtr h, IntPtr l){
      uint pid; GetWindowThreadProcessId(h, out pid);
      try { if (System.Diagnostics.Process.GetProcessById((int)pid).ProcessName != "KakaoTalk") return true; }
      catch { return true; }
      var c = new StringBuilder(256); GetClassName(h, c, 256);
      var t = new StringBuilder(512); GetWindowText(h, t, 512);
      if (c.ToString() == "EVA_Window_Dblclk" && t.ToString() == "카카오톡") { found = h; return false; }
      return true;
    }, IntPtr.Zero);
    return found;
  }
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

function Restore-KakaoMainWindow {
    <#
      트레이로 내려간 카카오톡 메인 창을 되살려 최상단으로 올린다.

      트레이 아이콘을 클릭하지 않는다. 알림 영역은 이 일에서 가장 깨지기 쉬운
      부분이다 — 아이콘이 숨김 영역(오버플로)으로 들어가면 좌표가 사라지고,
      다른 앱이 아이콘을 넣고 빼면 자리가 밀리고, 화면 배율에 따라 어긋난다.
      메인 창은 트레이 상태에서도 최상위 창으로 살아 있고 '숨겨져' 있을 뿐이므로
      (실측 2026-07-29) 핸들로 ShowWindow 를 부르면 같은 결과를 좌표 없이 얻는다.
    #>
    $mh = [Win32]::KakaoMain()
    if ($mh -eq [IntPtr]::Zero) { return [IntPtr]::Zero }
    if (-not [Win32]::IsWindowVisible($mh)) {
        Write-Log "  메인 창이 트레이에 숨어 있습니다 — ShowWindow 로 되살립니다"
        [void][Win32]::ShowWindow($mh, 5)          # SW_SHOW
        Start-Sleep -Milliseconds 900
    }
    for ($i = 1; $i -le 5; $i++) {
        if ([Win32]::ForceForeground($mh)) { return $mh }
        Start-Sleep -Milliseconds 400
        if ([Win32]::GetForegroundWindow() -eq $mh) { return $mh }
    }
    Write-Log "  메인 창을 최상단으로 올리지 못했습니다" 'WARN'
    [IntPtr]::Zero
}

function Get-RowMatchScore {
    <#
      OCR 로 읽은 목록 한 줄이 방 이름의 앞부분인지 0~1 로 점수를 낸다.

      정확 일치를 쓸 수 없다. 목록의 방 이름은 폭에 맞춰 잘리고(...), OCR 은
      글자를 틀린다 — 실측에서 '바이브코딩' 을 '바이브코팅' 으로 읽었다.
      그래서 기호·공백을 뗀 뒤 글자 단위 일치율로 판정하고, 최종 확인은
      '열린 창의 제목이 방 이름과 정확히 같은지' 로 한다. 근사 판정이 틀리면
      엉뚱한 창이 열리지만 제목 검사에서 걸러지므로 Ctrl+S 까지 가지 않는다.
    #>
    param([string]$Text, [string]$Target)
    $a = ($Text -replace '[^\p{L}\p{N}]', '')
    $b = ($Target -replace '[^\p{L}\p{N}]', '')
    if ($a.Length -lt 6 -or $b.Length -eq 0) { return 0.0 }
    if ($a.Length -gt $b.Length) { $a = $a.Substring(0, $b.Length) }
    $same = 0
    for ($i = 0; $i -lt $a.Length; $i++) { if ($a[$i] -eq $b[$i]) { $same++ } }
    [double]$same / $a.Length
}

function Get-ChatRoomList {
    <#
      메인 창에서 '채팅 목록' 컨트롤을 돌려준다. 보이지 않으면 $null.

      클래스 이름으로만 고르면 안 된다 — 친구 목록도, 검색 결과 목록도 같은
      EVA_VH_ListControl_Dblclk 다(실측 2026-08-03). 2026-08-02 밤 갱신은
      카톡이 '친구' 탭에 떠 있어서 친구 목록을 채팅 목록으로 잡았고, 사람 이름을
      다섯 화면 훑다가 '최고 일치율 7%' 로 중단했다 — 그날 대화가 통째로 빠졌다.

      그래서 컨트롤 이름으로 고른다. 이름은 'ChatRoomListCtrl_0x000302ea' 처럼
      주소가 붙어 실행마다 달라지므로 앞부분만 본다. 접근성 API 는 보이는 것만
      노출하므로(실측), 이 이름이 없다는 것은 곧 '채팅 탭이 떠 있지 않다' 는 뜻이다.
    #>
    param($Main)
    $all = $Main.FindAll([System.Windows.Automation.TreeScope]::Descendants,
        [System.Windows.Automation.Condition]::TrueCondition)
    for ($i = 0; $i -lt $all.Count; $i++) {
        $e = $all.Item($i)
        if ($e.Current.ClassName -eq 'EVA_VH_ListControl_Dblclk' -and
            $e.Current.Name -like 'ChatRoomListCtrl*' -and -not $e.Current.IsOffscreen) { return $e }
    }
    $null
}

function Select-ChatTab {
    <#
      '채팅' 탭을 눌러 채팅 목록을 띄운다. 성공하면 목록 컨트롤, 실패하면 $null.

      왼쪽 탭 띠는 접근성 API 에 버튼이 0개이고(실측), 아이콘이라 OCR 로 읽을
      글자도 없다. 그래서 자리를 추정해 누르되 **누를 때마다 채팅 목록이 떴는지
      확인**한다. 맞히면 멈추고 틀리면 다음 자리를 누른다.

      더듬어도 되는 이유: 탭 전환은 되돌릴 수 있고, 메시지가 나가거나 방을
      나가는 경로가 아니다. 대신 아래쪽 설정·알림 아이콘까지 내려가지 않도록
      뷰 위쪽 320px 까지만 훑고, 클릭 자리는 여느 클릭과 같이 '그 자리에 보이는
      창이 카톡인지' 를 먼저 묻는다.
    #>
    param($Main, [int]$KakaoPid)

    # 탭 띠의 폭 = 메인 창 왼쪽 끝 ~ 내용 뷰(채팅 목록·친구 목록…) 왼쪽 끝.
    # 배율·창 크기가 바뀌어도 이 두 좌표에서 매번 다시 잰다.
    $mr = $Main.Current.BoundingRectangle
    $contentX = $null; $contentTop = $null; $seen = @()
    $all = $Main.FindAll([System.Windows.Automation.TreeScope]::Descendants,
        [System.Windows.Automation.Condition]::TrueCondition)
    for ($i = 0; $i -lt $all.Count; $i++) {
        $e = $all.Item($i).Current
        if ($e.Name -notmatch 'View_0x' -or $e.Name -like 'OnlineMainView*' -or $e.IsOffscreen) { continue }
        $seen += ($e.Name -replace '_0x.*', '')
        if ($null -eq $contentX -or $e.BoundingRectangle.X -lt $contentX) {
            $contentX = $e.BoundingRectangle.X
            $contentTop = $e.BoundingRectangle.Y
        }
    }
    if ($seen.Count) { Write-Log ("  지금 보이는 뷰: {0}" -f ($seen -join ', ')) }
    if ($null -eq $contentX) { Write-Log "  탭 띠 위치를 잴 수 없습니다" 'WARN'; return $null }

    $barWidth = $contentX - $mr.X
    if ($barWidth -lt 30 -or $barWidth -gt 200) {
        Write-Log ("  탭 띠 폭이 예상 밖입니다 ({0}px) — 누르지 않습니다" -f [int]$barWidth) 'WARN'
        return $null
    }
    $tx = [int]($mr.X + $barWidth / 2)

    for ($dy = 20; $dy -le 320; $dy += 24) {
        $ty = [int]($contentTop + $dy)
        $pidAtTab = [Win32]::PidAt($tx, $ty)
        if ($pidAtTab -ne $KakaoPid) { continue }    # 남의 창이 덮은 자리는 누르지 않는다
        [System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point($tx, $ty)
        Start-Sleep -Milliseconds 120
        [Win32]::MouseClick()
        Start-Sleep -Milliseconds 350
        $list = Get-ChatRoomList $Main
        if ($null -ne $list) {
            Write-Log ("  '채팅' 탭으로 전환했습니다 ($tx, $ty)")
            return $list
        }
    }
    Write-Log "  탭 띠에서 '채팅' 을 찾지 못했습니다" 'WARN'
    $null
}

function Open-RoomWindow {
    <#
      방 창이 없을 때, 트레이 상태의 카톡에서 방 창을 열어 반환한다. 실패하면 $null.

      왜 필요한가
        방 창은 사람 손 없이도 사라진다(실측 2026-07-29: 관찰 중에 없어졌다).
        2026-07-28 밤 갱신은 이 때문에 통째로 빠졌다. '창을 열어두면 된다' 는
        전제는 유지될 수 없으므로, 없으면 직접 연다.

      키를 보내지 않는다
        Enter 로 목록의 선택 항목을 여는 것은 동작하지 않았다(실측).
        방 이름을 검색창에 타이핑하는 방법도 쓰지 않는다 — 포커스가 대화방
        입력칸에 있으면 그 글자가 방에 메시지로 전송된다. 되돌릴 수 없는 사고다.
        더블클릭만으로 되므로, 이 경로는 키보드 입력을 아예 쓰지 않는다.

      클릭할 자리는 OCR 로 먼저 읽는다
        채팅 목록은 EVA_VH_ListControl_Dblclk 한 덩어리로, 접근성 API 에 항목이
        0개다(실측). 몇 번째 행인지 알 수 없으므로 목록 영역을 OCR 해서 방 이름이
        보이는 줄의 y 좌표를 얻는다. 이 저장소가 메뉴를 다룰 때 쓰던 원칙과 같다.
    #>
    Write-Log "방 창 복구 시도 — 트레이 상태의 카카오톡에서 방을 엽니다"

    $mh = Restore-KakaoMainWindow
    if ($mh -eq [IntPtr]::Zero) {
        Write-Log "  카카오톡 메인 창을 찾지 못했습니다(카톡이 실행 중이 아닐 수 있음)" 'WARN'
        return $null
    }

    $root = [System.Windows.Automation.AutomationElement]::RootElement
    $main = $root.FindFirst([System.Windows.Automation.TreeScope]::Children,
        (New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::NameProperty, '카카오톡')))
    if ($null -eq $main) { Write-Log "  메인 창이 접근성 API 에 보이지 않습니다" 'WARN'; return $null }
    $kakaoPid = $main.Current.ProcessId

    # 채팅 목록 컨트롤 위치. 없으면 다른 탭이 떠 있는 것이므로 '채팅' 탭으로 돌린다.
    $list = Get-ChatRoomList $main
    if ($null -eq $list) {
        Write-Log "  채팅 목록이 보이지 않습니다 — 다른 탭이 떠 있는 것 같습니다"
        $list = Select-ChatTab -Main $main -KakaoPid $kakaoPid
    }
    if ($null -eq $list) {
        Write-Log "  채팅 목록을 찾지 못했습니다 — 잠금 화면이나 로그아웃 상태일 수 있습니다" 'WARN'
        return $null
    }
    $lr = $list.Current.BoundingRectangle
    $lh = [IntPtr]$list.Current.NativeWindowHandle
    $cx = [int]($lr.X + $lr.Width / 2)
    $mid = [int]($lr.Y + $lr.Height / 2)
    Write-Log ("  채팅 목록: x={0} y={1} w={2} h={3}" -f [int]$lr.X, [int]$lr.Y, [int]$lr.Width, [int]$lr.Height)

    # 목록을 맨 위로 되돌린다 — 스크롤은 컨트롤에 메시지를 보내는 것이라 안전하다
    [Win32]::ScrollList($lh, 25, $false, $cx, $mid)
    Start-Sleep -Milliseconds 600

    # 목록을 OCR 해서 방 이름 줄을 찾는다.
    #
    # 방이 목록 맨 위에 있다고 가정하지 않는다. 목록은 최근 대화 순이라 자리가 매일
    # 바뀌고, 한 화면에 안 보일 수도 있다. 그래서 위에서부터 한 화면씩 훑는다.
    # 스크롤은 휠이므로 훑는 동안 아무 것도 열리지 않는다.
    . (Join-Path $PSScriptRoot 'kakao_ocr.ps1')
    $best = $null; $bestScore = 0.0
    for ($page = 0; $page -lt $MaxScrollPages; $page++) {
        # 그려지기 전에 캡처하면 몇 줄만 읽힌다(실측: 20줄이 나올 자리에서 1줄).
        # 줄 수가 터무니없이 적으면 한 번 더 읽는다.
        $lines = Get-ScreenOcr -X ([int]$lr.X) -Y ([int]$lr.Y) -Width ([int]$lr.Width) -Height ([int]$lr.Height) -Scale 2
        if ($lines.Count -lt 5) {
            Start-Sleep -Milliseconds 800
            $lines = Get-ScreenOcr -X ([int]$lr.X) -Y ([int]$lr.Y) -Width ([int]$lr.Width) -Height ([int]$lr.Height) -Scale 2
        }
        $pageBest = $null; $pageScore = 0.0
        foreach ($l in $lines) {
            $s = Get-RowMatchScore -Text $l.text -Target $Room
            if ($s -gt $pageScore) { $pageScore = $s; $pageBest = $l }
        }
        Write-Log ("  목록 {0}쪽: {1}줄, 최고 일치율 {2:P0}" -f ($page + 1), $lines.Count, $pageScore)
        if ($pageScore -gt $bestScore) { $bestScore = $pageScore; $best = $pageBest }
        if ($bestScore -ge 0.8) { break }

        # 다음 화면으로. 더 스크롤할 것이 없으면 화면이 그대로이므로 그때 멈춘다.
        $sig = ($lines | ForEach-Object { $_.text }) -join '|'
        [Win32]::ScrollList($lh, 4, $true, $cx, $mid)
        Start-Sleep -Milliseconds 700
        $after = Get-ScreenOcr -X ([int]$lr.X) -Y ([int]$lr.Y) -Width ([int]$lr.Width) -Height ([int]$lr.Height) -Scale 2
        if ((($after | ForEach-Object { $_.text }) -join '|') -eq $sig) {
            Write-Log "  목록 끝 — 더 훑을 화면이 없습니다"
            break
        }
    }
    if ($null -eq $best -or $bestScore -lt 0.8) {
        Write-Log ("  목록에서 '{0}' 을 찾지 못했습니다 (최고 일치율 {1:P0}, {2}쪽까지 확인)" -f
            $Room, $bestScore, $MaxScrollPages) 'WARN'
        return $null
    }
    Write-Log ("  후보 줄: '{0}' (일치율 {1:P0}, y={2})" -f $best.text, $bestScore, $best.y)

    # 클릭할 자리가 실제로 카톡인지 확인 — '항상 위' 창이 덮고 있으면 클릭하지 않는다.
    # 변수 이름이 아래 Ctrl+S 쪽 가드($pidAt)와 겹치지 않게 둔다 — 안전장치 계약
    # 테스트가 '첫 번째 $pidAt 가드' 를 Ctrl+S 가드로 보고 검사한다.
    $cy = [int]$best.y
    $pidAtRow = [Win32]::PidAt($cx, $cy)
    if ($pidAtRow -ne $kakaoPid) {
        $who = '알 수 없음'
        if ($pidAtRow -ne 0) { try { $who = (Get-Process -Id $pidAtRow -ErrorAction Stop).ProcessName } catch {} }
        Write-Log ("  클릭 자리($cx, $cy)가 다른 창에 덮여 있습니다 — '$who'(PID $pidAtRow). " +
            "'항상 위'로 떠 있는 창(작업 관리자 등)일 수 있습니다. 클릭하지 않습니다") 'WARN'
        return $null
    }

    Write-Log "  더블클릭으로 방 열기 ($cx, $cy)"
    [System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point($cx, $cy)
    Start-Sleep -Milliseconds 250
    [Win32]::MouseDoubleClick()

    # 제목이 정확히 일치하는 창이 떴는지로만 성공을 판정한다
    $deadline = (Get-Date).AddSeconds(12)
    while ((Get-Date) -lt $deadline) {
        $w = Get-RoomWindow
        if ($null -ne $w) { Write-Log "  방 창 열림 확인: '$($w.Current.Name)'"; return $w }
        Start-Sleep -Milliseconds 500
    }

    # 실패 — 엉뚱한 방이 열렸다면 닫아서 원래 상태로 되돌린다
    Write-Log "  방 창이 열리지 않았습니다" 'WARN'
    $kids = $root.FindAll([System.Windows.Automation.TreeScope]::Children,
        [System.Windows.Automation.Condition]::TrueCondition)
    for ($i = 0; $i -lt $kids.Count; $i++) {
        $e = $kids.Item($i)
        if ($e.Current.ProcessId -eq $kakaoPid -and
            $e.Current.ClassName -eq 'EVA_Window_Dblclk' -and
            $e.Current.Name -and $e.Current.Name -ne '카카오톡' -and $e.Current.Name -ne $Room) {
            Write-Log "  잘못 열린 창을 닫습니다: '$($e.Current.Name)'"
            [void][Win32]::PostMessage([IntPtr]$e.Current.NativeWindowHandle, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero)
        }
    }
    $null
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

# 1) 방 창 확인 — 없으면 직접 연다
#
# 2026-07-28 밤 갱신이 통째로 빠진 원인이 이것이다. 방 창은 사람이 닫지 않아도
# 사라지므로(실측) '열어두면 된다' 는 전제로는 매일 자동 실행이 성립하지 않는다.
# 복구가 실패하면 예전과 똑같이 화면을 남기고 중단한다 — 나빠지는 경우는 없다.
$win = Get-RoomWindow
if ($null -eq $win) {
    if ($NoAutoOpen) {
        Stop-Safely "'$Room' 창을 찾을 수 없습니다(-NoAutoOpen). 카카오톡에서 해당 방을 열어두세요."
    }
    Write-Log "'$Room' 창이 없습니다 — 직접 열어 봅니다" 'WARN'
    try { $win = Open-RoomWindow } catch {
        Write-Log "  복구 중 오류: $($_.Exception.Message)" 'WARN'
        $win = $null
    }
}
if ($null -eq $win) {
    Stop-Safely "'$Room' 창을 찾을 수 없고, 카카오톡에서 직접 여는 것도 실패했습니다. 남긴 화면을 확인하세요."
}
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
