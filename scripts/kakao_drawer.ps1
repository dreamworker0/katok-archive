<#
카톡 '채팅방 서랍' 에서 첨부 원본을 내려받는다.

왜 필요한가
  대화 내보내기(txt)에는 첨부가 들어 있지 않다 — 파일은 이름 한 줄, 사진은 흔적만
  남는다. 원본은 서랍에서 따로 받아야 한다. 그런데 **파일은 공유일 + 14일이면
  만료된다**(유효기간 날짜에 도달하면 이미 못 받는다 = 실질 13일). 실측 2026-08-20:
  아카이브에 없던 파일 45개 중 서랍에 남아 있던 것은 7개뿐이고 4개는 그날 만료였다.
  38개는 영구 소실이었다. 그래서 이 일은 **매일** 돌아야 한다.

설계 — 창을 다루는 일과 그림을 읽는 일을 나눈다
  서랍의 항목은 접근성 API 에 하나도 없다(격자 패널과 스크롤바만 보인다). 좌표를
  눌러야 하는데, 월 구분 머리글이 행을 밀어서 좌표를 고정값으로 적어 둘 수 없다.
  그래서 여기서 PrintWindow 로 찍고, scripts/drawer_grid.py 가 카드 사각형을 찾고,
  다시 여기서 그 좌표를 누른다.

실측으로 확정된 것 (2026-08-20)
  · 서랍은 방 창과 **별개의 최상위 창** — 방 창 ☰(= 나가기·대화삭제가 있는 메뉴)를
    건드릴 필요가 없다
  · PrintWindow(PW_RENDERFULLCONTENT) 는 **가려진 채로** 찍힌다 → 밤에 돌아도
    사람 화면을 가로채지 않는다
  · 배율 150% — SetProcessDPIAware() 없으면 좌표가 1.5배 어긋난다
  · 창 최소 높이 1106 > 화면 1080 → 하단 선택 바가 작업표시줄에 가린다.
    y=-110 에 두면 바가 화면 안으로 들어온다
  · 카드 **본문** 클릭 = 단일 선택(교체), 좌상단 **동그라미** 클릭 = 추가
  · 선택 바가 뜨면 격자 패널이 86px 줄어든다(780→694). **맨 위로 올려둔 상태**에서
    선택을 시작하면 스크롤 위치가 그대로라 카드 좌표가 안 밀린다
  · 저장은 대화상자 없이 '내 문서\카카오톡 받은 파일' 로 떨어지고, 끝나면 제목 없는
    '저장 결과' 팝업이 뜬다 → WM_CLOSE 로 닫는다
  · 하단 바에 **삭제 버튼은 없다** (오조작으로 지울 경로가 없다)
  · Ctrl+A·Shift+↓ 는 듣지 않는다 — 이 컨트롤에 키보드 모델이 없다

서랍 창이 없으면 직접 연다 (2026-08-25 추가)
  '열어 두면 된다' 는 전제로는 매일 자동 실행이 성립하지 않는다. 실측: 8/22~8/25
  나흘 연속으로 창이 없어 첨부를 한 개도 못 받았고, 경고가 로그에만 남아 아무도
  몰랐다. kakao_export.ps1 이 방 창에 대해 같은 결론에 이른 것과 같은 이유다.

  **Ctrl+J 로 연다 — 메뉴를 지나가지 않는다.**
  서랍으로 가는 유일한 앱 내 경로는 방 창 ☰ 메뉴다. 방 창 머리에도(돋보기·통화·
  화상통화·☰), 발치에도(+·이모티콘·파일·전송) 서랍 단추는 없고, 메인 창
  '⋯ 더보기' 에도 없다(실측). 그런데 그 ☰ 메뉴에는 '채팅방 나가기' 가 같이 있다
  (실측 2026-08-25: 서랍 y=277, 나가기 y=544 — 267px 떨어져 있지만, 카톡이 항목
  하나만 끼워 넣어도 좌표가 밀린다). 46명짜리 방을 잘못 나가면 되돌릴 수 없다.

  그 메뉴를 열어 읽어 보니 하위 메뉴 '채팅방 서랍 > 파일' 에 **Ctrl+J** 가 붙어
  있었다. 그래서 메뉴를 아예 열지 않는다. kakao_export.ps1 이 '대화 내보내기' 를
  Ctrl+S 로 처리하는 것과 같은 설계다 — 위험 항목 근처에 가지 않는 것이 요점이다.

  Esc 를 쓰지 않는다. 카카오톡에서 Esc 는 '취소' 가 아니라 '창 닫기' 이고, 메뉴가
  닫힌 뒤의 Esc 는 방 창을 닫는다(실측 2026-08-25: 그렇게 방 창을 날렸다).

안전 원칙
  · 누르기 직전에 그 픽셀의 창이 '채팅방 서랍' 소속인지 확인하고, 아니면 중단한다
    (실측: 확인을 안 넣었을 때 커서가 Chrome 과 작업표시줄 위에 있었다)
  · 방 창에 보내는 것은 **입력칸 클릭 한 번과 Ctrl+J** 뿐이다. 그 둘도 방 창이
    최상단인지, 누를 자리가 정말 카톡인지 확인한 뒤에만 보낸다 — 덮은 창이
    편집기라면 단축키가 남의 파일에 간다(kakao_export.ps1 실측)
  · ☰ 메뉴는 열지 않는다
  · 방 창까지 없으면 그때는 물러난다 (run_daily.ps1 은 이 스크립트 앞에
    kakao_export.ps1 을 돌리고, 그쪽이 방 창을 열어 두므로 보통은 이미 있다)

사용
  powershell -File scripts\kakao_drawer.ps1 -Discover     # 판독만, 고르기·저장 없음
  powershell -File scripts\kakao_drawer.ps1 -NoAutoOpen   # 서랍이 없으면 그냥 중단 (예전 동작)
  powershell -File scripts\kakao_drawer.ps1               # 실제 저장
#>
param(
    [switch]$Discover,
    [string]$DrawerTitle = '채팅방 서랍',
    # 서랍이 닫혀 있을 때 Ctrl+J 를 보낼 방. kakao_export.ps1 의 기본값과 같다.
    [string]$Room = '바이브코딩,업무자동화 화상회의모임',
    [string]$LogDir = 'logs',
    [string]$ShotDir = 'logs\drawer',
    [string]$SaveDir = "$env:USERPROFILE\Documents\카카오톡 받은 파일",
    # 한 탭에서 훑을 화면 수. 사진 28장이 3~4화면이라 넉넉히 둔다.
    [int]$MaxScreens = 10,
    # 서랍 창이 없어도 직접 열지 않고 중단한다(예전 동작).
    [switch]$NoAutoOpen
)

$ErrorActionPreference = 'Stop'
Add-Type -Name Dpi -Namespace W32 -MemberDefinition '[DllImport("user32.dll")] public static extern bool SetProcessDPIAware();'
[void][W32.Dpi]::SetProcessDPIAware()
Add-Type -AssemblyName System.Drawing

Add-Type -ReferencedAssemblies System.Drawing -TypeDefinition @"
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Runtime.InteropServices;
using System.Text;
public class DW {
    public delegate bool EnumProc(IntPtr h, IntPtr p);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr p, EnumProc cb, IntPtr x);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern bool IsWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern int GetDlgCtrlID(IntPtr h);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool MoveWindow(IntPtr h, int x, int y, int w, int ht, bool rp);
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint f);
    [DllImport("user32.dll")] public static extern IntPtr WindowFromPoint(POINT p);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern bool GetCursorPos(out POINT p);
    [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, IntPtr e);
    [DllImport("user32.dll")] public static extern IntPtr GetAncestor(IntPtr h, uint f);
    [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr h, uint m, IntPtr wp, IntPtr lp);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr wp, IntPtr lp);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
    [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool attach);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
    [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte sc, uint f, IntPtr e);

    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X, Y; }
    public const uint GA_ROOT = 2, LEFTDOWN = 0x0002, LEFTUP = 0x0004;
    public const uint WM_MOUSEWHEEL = 0x020A, WM_CLOSE = 0x0010;

    public static IntPtr ByTitle(string want) {
        IntPtr hit = IntPtr.Zero;
        EnumWindows((h, p) => {
            if (!IsWindowVisible(h)) return true;
            var sb = new StringBuilder(512); GetWindowText(h, sb, 512);
            if (sb.ToString() == want) { hit = h; return false; }
            return true;
        }, IntPtr.Zero);
        return hit;
    }
    // 서랍이 최소화·숨김이면 ByTitle 이 못 찾는다(보이는 창만 훑는다). 그럴 때를
    // 위해 보이지 않는 창도 한 번 더 훑는다 — 되살릴 수 있으면 되살린다.
    public static IntPtr ByTitleAny(string want) {
        IntPtr hit = IntPtr.Zero;
        EnumWindows((h, p) => {
            var sb = new StringBuilder(512); GetWindowText(h, sb, 512);
            if (sb.ToString() == want) { hit = h; return false; }
            return true;
        }, IntPtr.Zero);
        return hit;
    }
    public static List<IntPtr> Children(IntPtr p) {
        var all = new List<IntPtr>();
        EnumChildWindows(p, (h, x) => { all.Add(h); return true; }, IntPtr.Zero);
        return all;
    }
    // 카카오톡이 띄운 제목 없는 작은 창들 — '저장 결과' 팝업이 여기 걸린다.
    public static List<IntPtr> NamelessPopups(uint pid, int maxW) {
        var all = new List<IntPtr>();
        EnumWindows((h, p) => {
            if (!IsWindowVisible(h)) return true;
            uint owner; GetWindowThreadProcessId(h, out owner);
            if (owner != pid) return true;
            var sb = new StringBuilder(64); GetWindowText(h, sb, 64);
            if (sb.Length != 0) return true;
            RECT r; GetWindowRect(h, out r);
            int w = r.Right - r.Left;
            if (w > 0 && w <= maxW) all.Add(h);
            return true;
        }, IntPtr.Zero);
        return all;
    }
    public static string Describe(IntPtr h) {
        if (h == IntPtr.Zero) return "창 없음";
        var cn = new StringBuilder(256); GetClassName(h, cn, 256);
        var root = GetAncestor(h, GA_ROOT);
        var tt = new StringBuilder(512); GetWindowText(root, tt, 512);
        return string.Format("0x{0:X} class='{1}' ctrlId={2} 최상위='{3}'",
            (long)h, cn.ToString(), GetDlgCtrlID(h), tt.ToString());
    }
    static void NudgeAlt() {
        keybd_event(0x12, 0, 0, IntPtr.Zero);
        System.Threading.Thread.Sleep(30);
        keybd_event(0x12, 0, 2, IntPtr.Zero);
    }
    // Ctrl+J — '채팅방 서랍 > 파일' 단축키. 메뉴를 지나가지 않는 유일한 길이다.
    // SendKeys 를 쓰지 않는 이유는 kakao_export.ps1 의 Ctrl+S 와 같다(Alt 선행
    // 입력 뒤에 삼켜지는 경우가 있었다) — 실제 키 이벤트로 보낸다.
    public static void SendCtrlJ() {
        keybd_event(0x11, 0, 0, IntPtr.Zero);   // Ctrl down
        System.Threading.Thread.Sleep(40);
        keybd_event(0x4A, 0, 0, IntPtr.Zero);   // J down
        System.Threading.Thread.Sleep(40);
        keybd_event(0x4A, 0, 2, IntPtr.Zero);   // J up
        System.Threading.Thread.Sleep(40);
        keybd_event(0x11, 0, 2, IntPtr.Zero);   // Ctrl up
    }
    // 그 화면 좌표를 실제로 차지한 창의 프로세스. 0 이면 창이 없다.
    public static uint PidAt(int x, int y) {
        var p = new POINT(); p.X = x; p.Y = y;
        IntPtr h = WindowFromPoint(p);
        if (h == IntPtr.Zero) return 0;
        uint pid; GetWindowThreadProcessId(h, out pid); return pid;
    }
    public static bool ForceForeground(IntPtr h) {
        uint pid; uint target = GetWindowThreadProcessId(h, out pid);
        uint me = GetCurrentThreadId();
        bool attached = (target != me) && AttachThreadInput(me, target, true);
        try {
            ShowWindow(h, 9);
            BringWindowToTop(h);
            NudgeAlt();
            SetForegroundWindow(h);
        } finally { if (attached) AttachThreadInput(me, target, false); }
        return GetForegroundWindow() == h;
    }
    public static Bitmap Shoot(IntPtr h) {
        RECT r; GetWindowRect(h, out r);
        int w = r.Right - r.Left, ht = r.Bottom - r.Top;
        if (w <= 0 || ht <= 0) return null;
        var bmp = new Bitmap(w, ht);
        using (var g = Graphics.FromImage(bmp)) {
            IntPtr dc = g.GetHdc();
            bool ok = PrintWindow(h, dc, 0x2);
            g.ReleaseHdc(dc);
            if (!ok) { bmp.Dispose(); return null; }
        }
        return bmp;
    }
}
"@

Set-Location (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
$script:LogPath = $null
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
New-Item -ItemType Directory -Force -Path $ShotDir | Out-Null
$script:LogPath = Join-Path $LogDir ("kakao-drawer-{0}.log" -f (Get-Date -Format 'yyyyMMdd'))

function Write-Log { param([string]$m, [string]$level = 'INFO')
    $line = "[{0}] {1} {2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $level, $m
    Write-Host $line
    try { Add-Content -Path $script:LogPath -Value $line -Encoding utf8 } catch {}
}

# ───────── 작업용 창 자리 ─────────
# y=-110 이면 하단 선택 바(창 기준 y≈1060)가 화면 950 에 와서 작업표시줄을 피한다.
$WORK = @{ X = 0; Y = -110; W = 1900; H = 1106 }
# 창 기준 좌표(실측) — 화면 좌표는 여기에 창 원점을 더한다.
$TAB_Y      = 293
$TAB_X      = @{ '사진/동영상' = 480; '파일' = 584 }
$SAVE_BTN   = @{ X = 1842; Y = 1060 }
# 선택 해제(⊗)의 **중심**이다. 처음에는 (401,1068) 로 적었는데 그 점은 동그라미
# 왼쪽 바로 밖이었다(실측 2026-08-21: 원이 x 403~424, y 1051~1072). 그래서 해제가
# 조용히 안 먹었고, 화면을 넘길 때마다 앞 화면의 선택이 그대로 남아 같은 것을 다시
# 저장했다 — 결과는 같았지만(중복은 걸러진다) 헛일이었다. 가장자리를 스치지 않게
# 중심을 적는다.
$CLEAR_BTN  = @{ X = 413;  Y = 1061 }

function Open-DrawerWindow {
    <#
      서랍 창이 없을 때 방 창에서 Ctrl+J 로 연다. 실패하면 [IntPtr]::Zero.

      왜 메뉴를 안 쓰는지, 왜 Ctrl+J 인지는 파일 머리의 '서랍 창이 없으면 직접 연다'
      를 보라. 요점은 '채팅방 나가기' 가 있는 메뉴를 아예 열지 않는다는 것이다.

      방 창은 전제다. run_daily.ps1 은 이 스크립트 앞에 kakao_export.ps1 을 돌리고,
      그쪽이 방 창이 없으면 목록에서 열어 두므로 보통은 이미 있다. 여기서 방 목록까지
      뒤지지 않는 것은 그 일이 이미 한 곳에 있기 때문이다 — 두 벌로 두면 갈라진다.
    #>
    Write-Log "서랍 창이 없습니다 — 방 창에서 Ctrl+J 로 엽니다"

    $room = [DW]::ByTitle($Room)
    if ($room -eq [IntPtr]::Zero) {
        Write-Log "  방 창 '$Room' 이 없습니다 — 열 방법이 없어 물러납니다" 'WARN'
        return [IntPtr]::Zero
    }
    $kpid = 0
    [void][DW]::GetWindowThreadProcessId($room, [ref]$kpid)

    # 최상단 확보 — 다른 앱에 Ctrl+J 를 보내면 안 된다.
    $front = $false
    for ($try = 1; $try -le 5; $try++) {
        if ([DW]::ForceForeground($room)) { $front = $true; break }
        Start-Sleep -Milliseconds 400
        if ([DW]::GetForegroundWindow() -eq $room) { $front = $true; break }
        Write-Log "  최상단 전환 재시도 $try/5" 'WARN'
    }
    if (-not $front) {
        Write-Log ("  방 창을 최상단으로 올리지 못했습니다 — 앞에 있는 창: {0}. " +
            "다른 앱에 단축키가 갈 위험이 있어 보내지 않습니다" -f `
            [DW]::Describe([DW]::GetForegroundWindow())) 'WARN'
        return [IntPtr]::Zero
    }

    # 창 내부 포커스가 있어야 단축키가 먹는다(실측 — 최상단만으로는 안 된다).
    # 메시지 입력칸을 한 번 누른다. 커서만 놓는 동작이라 안전하다 — Enter 도,
    # 글자도 보내지 않는다. 자리는 kakao_export.ps1 이 Ctrl+S 에 쓰는 것과 같다.
    $r = New-Object DW+RECT; [void][DW]::GetWindowRect($room, [ref]$r)
    $ix = $r.Left + 60
    $iy = $r.Bottom - 145

    # 최상단인데도 '항상 위' 창이 그 위에 그려질 수 있다(kakao_export.ps1 실측:
    # 작업 관리자). 그 상태로 누르면 포커스가 그리로 넘어가고 Ctrl+J 도 따라간다.
    $pidAt = [DW]::PidAt($ix, $iy)
    if ($pidAt -ne $kpid) {
        $who = '알 수 없음'
        if ($pidAt -ne 0) { try { $who = (Get-Process -Id $pidAt -ErrorAction Stop).ProcessName } catch {} }
        Write-Log ("  입력칸 자리($ix,$iy)가 다른 창에 덮여 있습니다 — '$who'(PID $pidAt). " +
            "누르지 않습니다") 'WARN'
        return [IntPtr]::Zero
    }

    Write-Log "  입력칸 클릭 ($ix,$iy) — 그 자리 카톡 확인됨"
    $saved = New-Object DW+POINT; [void][DW]::GetCursorPos([ref]$saved)
    [void][DW]::SetCursorPos($ix, $iy)
    Start-Sleep -Milliseconds 220
    [DW]::mouse_event([DW]::LEFTDOWN, 0, 0, 0, [IntPtr]::Zero)
    Start-Sleep -Milliseconds 60
    [DW]::mouse_event([DW]::LEFTUP, 0, 0, 0, [IntPtr]::Zero)
    Start-Sleep -Milliseconds 400
    [void][DW]::SetCursorPos($saved.X, $saved.Y)

    Write-Log "  Ctrl+J 전송 ('채팅방 서랍 > 파일' 단축키)"
    [DW]::SendCtrlJ()

    # 제목이 정확히 맞는 창이 떴는지로만 성공을 판정한다.
    $deadline = (Get-Date).AddSeconds(12)
    while ((Get-Date) -lt $deadline) {
        $opened = [DW]::ByTitle($DrawerTitle)
        if ($opened -ne [IntPtr]::Zero) {
            Write-Log ("  서랍 창 열림 확인 0x{0:X}" -f [int64]$opened)
            Start-Sleep -Milliseconds 800   # 격자가 그려질 틈
            return $opened
        }
        Start-Sleep -Milliseconds 500
    }
    Write-Log "  Ctrl+J 를 보냈지만 서랍 창이 뜨지 않았습니다" 'WARN'
    return [IntPtr]::Zero
}

$drawer = [DW]::ByTitle($DrawerTitle)
if ($drawer -eq [IntPtr]::Zero) {
    $hidden = [DW]::ByTitleAny($DrawerTitle)
    if ($hidden -ne [IntPtr]::Zero) {
        Write-Log "서랍 창이 숨어 있습니다 — 되살립니다"
        [void][DW]::ShowWindow($hidden, 9)
        Start-Sleep -Milliseconds 900
        $drawer = [DW]::ByTitle($DrawerTitle)
    }
}
if ($drawer -eq [IntPtr]::Zero -and -not $NoAutoOpen) {
    $drawer = Open-DrawerWindow
}
if ($drawer -eq [IntPtr]::Zero) {
    Write-Log "'$DrawerTitle' 창이 없고 열지도 못했습니다 — 첨부 수집을 건너뜁니다." 'WARN'
    Write-Log "  카카오톡에서 서랍을 한 번 열어 두면 다음 실행은 그것을 씁니다." 'WARN'
    Write-Log "  방 창 ☰ 메뉴는 건드리지 않습니다('채팅방 나가기'·'대화 내용 모두 삭제'가 있는 메뉴입니다)." 'WARN'
    exit 2
}

$pidOut = 0
[void][DW]::GetWindowThreadProcessId($drawer, [ref]$pidOut)
$origin = New-Object DW+RECT; [void][DW]::GetWindowRect($drawer, [ref]$origin)
Write-Log ("서랍 창 확인 0x{0:X} pid={1} ({2},{3} {4}x{5})" -f `
    [int64]$drawer, $pidOut, $origin.Left, $origin.Top, `
    ($origin.Right - $origin.Left), ($origin.Bottom - $origin.Top))

function Restore-Window {
    [void][DW]::MoveWindow($drawer, $origin.Left, $origin.Top,
        ($origin.Right - $origin.Left), ($origin.Bottom - $origin.Top), $true)
    Write-Log ("창을 원래 자리로 되돌렸습니다 ({0},{1} {2}x{3})" -f `
        $origin.Left, $origin.Top, ($origin.Right - $origin.Left), ($origin.Bottom - $origin.Top))
}

function Assert-Front {
    if ([DW]::GetForegroundWindow() -eq $drawer) { return $true }
    for ($i = 0; $i -lt 6; $i++) {
        if ([DW]::ForceForeground($drawer)) { return $true }
        Start-Sleep -Milliseconds 350
        if ([DW]::GetForegroundWindow() -eq $drawer) { return $true }
    }
    Write-Log ("최상단 확보 실패 — 앞에 있는 창: {0}" -f [DW]::Describe([DW]::GetForegroundWindow())) 'WARN'
    return $false
}

# 창 원점을 한 번만 읽어 담아 둔다.
#
# 처음에는 좌표가 필요할 때마다 GetWindowRect 를 부르는 helper 를 썼는데, 그 함수가
# 어떤 호출 경로에서 RECT 하나가 아니라 배열을 돌려줘 '$r.Left + $wx' 가 터졌다.
# 창 자리는 이 스크립트가 정해 놓고 실행 중에 바꾸지 않으므로, 원점을 한 번 재서
# 담아 두는 편이 짧고 확실하다.
$script:WinX = 0
$script:WinY = 0

function Set-Origin {
    $r = New-Object DW+RECT
    [void][DW]::GetWindowRect($drawer, [ref]$r)
    $script:WinX = [int]$r.Left
    $script:WinY = [int]$r.Top
}

function Invoke-Click { param([int]$wx, [int]$wy, [string]$what, [switch]$Always)
    # 판독 모드는 '고르기·저장'만 막는다. 탭 전환처럼 아무것도 바꾸지 않는 조작은
    # 막으면 조사가 무의미해진다 — 지금 열려 있는 탭만 두 번 훑게 된다(실측).
    if ($Discover -and -not $Always) { Write-Log "  (판독 모드 — '$what' 누르지 않음)"; return $false }
    if (-not (Assert-Front)) { return $false }
    $sx = $script:WinX + $wx
    $sy = $script:WinY + $wy
    $saved = New-Object DW+POINT; [void][DW]::GetCursorPos([ref]$saved)
    [void][DW]::SetCursorPos($sx, $sy)
    Start-Sleep -Milliseconds 220
    $pt = New-Object DW+POINT; $pt.X = $sx; $pt.Y = $sy
    $at = [DW]::WindowFromPoint($pt)
    if ($at -eq [IntPtr]::Zero -or [DW]::GetAncestor($at, [DW]::GA_ROOT) -ne $drawer) {
        Write-Log ("  '{0}' 자리({1},{2})가 서랍 소속이 아닙니다 — 누르지 않습니다: {3}" -f `
            $what, $sx, $sy, [DW]::Describe($at)) 'WARN'
        [void][DW]::SetCursorPos($saved.X, $saved.Y)
        return $false
    }
    [DW]::mouse_event([DW]::LEFTDOWN, 0, 0, 0, [IntPtr]::Zero)
    Start-Sleep -Milliseconds 60
    [DW]::mouse_event([DW]::LEFTUP, 0, 0, 0, [IntPtr]::Zero)
    Start-Sleep -Milliseconds 500
    [void][DW]::SetCursorPos($saved.X, $saved.Y)
    return $true
}

function Get-PaneRect {
    <# 지금 보이는 격자 패널을 찾는다. 탭마다 자식이 다르다(402=파일, 403=사진).
       돌려주는 값은 **창 기준** — 캡처의 (0,0) 이 창 좌상단이므로 그렇게 맞춘다. #>
    $best = $null
    foreach ($h in [DW]::Children($drawer)) {
        $id = [DW]::GetDlgCtrlID($h)
        if ($id -ne 402 -and $id -ne 403) { continue }
        if (-not [DW]::IsWindowVisible($h)) { continue }
        $r = New-Object DW+RECT; [void][DW]::GetWindowRect($h, [ref]$r)
        $area = ($r.Right - $r.Left) * ($r.Bottom - $r.Top)
        if ($null -eq $best -or $area -gt $best.Area) {
            $best = [pscustomobject]@{
                Handle = $h; CtrlId = $id; Area = $area
                X = $r.Left - $script:WinX; Y = $r.Top - $script:WinY
                W = ($r.Right - $r.Left); H = ($r.Bottom - $r.Top)
            }
        }
    }
    $best
}

function Save-Shot { param([string]$tag)
    $bmp = [DW]::Shoot($drawer)
    if ($null -eq $bmp) { Write-Log "  PrintWindow 실패" 'WARN'; return $null }
    $path = Join-Path $ShotDir ("{0}-{1}.png" -f (Get-Date -Format 'yyyyMMdd-HHmmss'), $tag)
    $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png); $bmp.Dispose()
    $path
}

function Read-Grid { param([string]$shot, $pane)
    $spec = "{0},{1},{2},{3}" -f $pane.X, $pane.Y, $pane.W, $pane.H
    $out = Join-Path $ShotDir 'grid.json'
    $env:PYTHONIOENCODING = 'utf-8'; $env:PYTHONUTF8 = '1'
    & python -m scripts.drawer_grid --image $shot --pane $spec --json $out 2>&1 | ForEach-Object {
        Write-Log ("  [격자] {0}" -f $_)
    }
    if (-not (Test-Path $out)) { return $null }
    Get-Content $out -Raw -Encoding utf8 | ConvertFrom-Json
}

function Invoke-Wheel { param($pane, [int]$notches, [switch]$Up)
    $delta = if ($Up) { 120 } else { -120 }
    $cx = $script:WinX + $pane.X + [int]($pane.W / 2)
    $cy = $script:WinY + $pane.Y + [int]($pane.H / 2)
    $lp = [IntPtr](($cy -shl 16) -bor ($cx -band 0xFFFF))
    for ($i = 1; $i -le $notches; $i++) {
        [void][DW]::SendMessage($pane.Handle, [DW]::WM_MOUSEWHEEL, [IntPtr]($delta -shl 16), $lp)
        Start-Sleep -Milliseconds 180
    }
}

function Close-ResultPopup {
    $popups = [DW]::NamelessPopups([uint32]$pidOut, 700)
    if ($popups.Count -eq 0) { return 0 }
    foreach ($h in $popups) {
        [void][DW]::PostMessage($h, [DW]::WM_CLOSE, [IntPtr]::Zero, [IntPtr]::Zero)
    }
    Start-Sleep -Milliseconds 900
    Write-Log ("  '저장 결과' 팝업 {0}개 닫음" -f $popups.Count)
    $popups.Count
}

function Count-Saved {
    if (-not (Test-Path $SaveDir)) { return 0 }
    (Get-ChildItem $SaveDir -File -ErrorAction SilentlyContinue).Count
}

# ───────────────────────── 실행 ─────────────────────────
Write-Log ("=== 서랍 첨부 수집 시작 (Discover={0}) ===" -f [bool]$Discover)
$before = Count-Saved
Write-Log ("받은 파일 폴더: {0} (지금 {1}개)" -f $SaveDir, $before)

if (-not (Assert-Front)) { Write-Log '최상단을 확보하지 못해 중단합니다' 'ABORT'; exit 3 }
[void][DW]::MoveWindow($drawer, $WORK.X, $WORK.Y, $WORK.W, $WORK.H, $true)
Start-Sleep -Milliseconds 800
Set-Origin
Write-Log ("작업 자리로 옮김 (원점 {0},{1})" -f $script:WinX, $script:WinY)

$totalClicked = 0
try {
    foreach ($tab in @('파일', '사진/동영상')) {
        # 한 탭이 넘어져도 다른 탭과 그날 갱신을 끌고 내려가지 않게 감싼다.
        #
        # 실측 2026-08-21: 저장 단계에서 한 번 예외가 나 탭 하나를 남긴 채 스크립트가
        # 끝났고, 곧바로 다시 돌리니 정상이었다. 재현되지 않는 일시적 실패다. 원인을
        # 못 짚은 채로는 막을 수 없지만, **번지지 않게** 할 수는 있다 — 첨부는 더해지는
        # 것이라 한 화면을 놓치는 것과 그날을 통째로 놓치는 것의 차이가 크다.
        try {
            Write-Log "── [$tab] 탭 ──"
            if (-not (Invoke-Click $TAB_X[$tab] $TAB_Y "$tab 탭" -Always)) {
                Write-Log "  탭을 누르지 못했습니다 — 건너뜁니다" 'WARN'
                continue
            }
            Start-Sleep -Milliseconds 700

            $pane = Get-PaneRect
            if ($null -eq $pane) { Write-Log '  격자 패널을 찾지 못했습니다' 'WARN'; continue }
            Write-Log ("  패널 ctrlId={0} (창기준 {1},{2} {3}x{4})" -f `
                $pane.CtrlId, $pane.X, $pane.Y, $pane.W, $pane.H)

            # 맨 위로 올린다. 위에서 시작하면 선택 바가 떠도 스크롤 위치가 안 바뀌므로
            # 카드 좌표가 밀리지 않는다(실측).
            Invoke-Wheel $pane 25 -Up

            $prevShot = $null
            for ($screen = 1; $screen -le $MaxScreens; $screen++) {
                $pane = Get-PaneRect
                $shot = Save-Shot ("{0}-{1}" -f ($tab -replace '/', ''), $screen)
                if ($null -eq $shot) { break }

                # 화면이 그대로면 더 내려갈 곳이 없다.
                if ($prevShot -and
                    (Get-FileHash $shot).Hash -eq (Get-FileHash $prevShot).Hash) {
                    Write-Log "  화면이 더 바뀌지 않습니다 — [$tab] 끝"
                    break
                }
                $prevShot = $shot

                $grid = Read-Grid $shot $pane
                if ($null -eq $grid -or $grid.cards.Count -eq 0) {
                    Write-Log "  누를 카드가 없습니다 — [$tab] 끝"
                    break
                }
                Write-Log ("  {0}화면: 카드 {1}개" -f $screen, $grid.cards.Count)

                if ($Discover) {
                    foreach ($c in $grid.cards) {
                        Write-Log ("    카드 ({0},{1} {2}x{3}) 동그라미 ({4},{5})" -f `
                            $c.x, $c.y, $c.w, $c.h, $c.circle[0], $c.circle[1])
                    }
                    Invoke-Wheel $pane 3
                    continue
                }

                # 첫 카드로 선택 모드에 들어간다 → 패널이 86px 줄어든다.
                # 맨 위에 있으므로 카드 좌표는 그대로다. 다시 재서 확인한다.
                $first = $grid.cards[0]
                [void](Invoke-Click $first.circle[0] $first.circle[1] '첫 카드')
                $pane2 = Get-PaneRect
                if ($pane2.H -ne $pane.H) {
                    Write-Log ("    선택 바가 떠서 패널이 {0}→{1} 로 줄었습니다 — 다시 잽니다" -f $pane.H, $pane2.H)
                    $shot2 = Save-Shot ("{0}-{1}-sel" -f ($tab -replace '/', ''), $screen)
                    $grid2 = Read-Grid $shot2 $pane2
                    if ($grid2 -and $grid2.cards.Count -gt 0) { $grid = $grid2 }
                }

                $clicked = 1
                foreach ($c in $grid.cards) {
                    # 첫 카드는 이미 선택돼 있다. 다시 누르면 해제된다.
                    if ($c.circle[0] -eq $first.circle[0] -and $c.circle[1] -eq $first.circle[1]) { continue }
                    if (Invoke-Click $c.circle[0] $c.circle[1] '카드') { $clicked++ }
                }
                Write-Log ("    {0}개 선택" -f $clicked)
                $totalClicked += $clicked

                [void](Invoke-Click $SAVE_BTN.X $SAVE_BTN.Y '저장')
                Start-Sleep -Seconds 3
                [void](Close-ResultPopup)
                [void](Invoke-Click $CLEAR_BTN.X $CLEAR_BTN.Y '선택 해제')

                $pane = Get-PaneRect
                Invoke-Wheel $pane 4
            }
        }
        catch {
            Write-Log ("  [$tab] 처리 중 오류: {0}" -f $_.Exception.Message) 'WARN'
            Write-Log '  이 탭은 여기서 접고 다음으로 갑니다 — 남은 선택은 풀어 둡니다.' 'WARN'
            # 선택이 남으면 다음 탭의 첫 클릭이 그것을 해제하는 데 쓰인다.
            try { [void](Invoke-Click $CLEAR_BTN.X $CLEAR_BTN.Y '선택 해제') } catch { }
            try { [void](Close-ResultPopup) } catch { }
        }
    }
}
finally {
    Restore-Window
}

$after = Count-Saved
Write-Log ("받은 파일 {0}개 → {1}개 (새로 {2}개)" -f $before, $after, ($after - $before))
Write-Log ("선택한 항목 누적 {0}개" -f $totalClicked)
Write-Log '다음: python -m scripts.collect_drawer'
Write-Log '=== 정상 종료 ==='
exit 0
