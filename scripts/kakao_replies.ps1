<#
방 창을 거슬러 올라가며 찍어서 **답장 관계**를 건져 온다.

왜 필요한가
  대화 내보내기(txt)는 답장 구조를 통째로 버린다. '누구에게 답장' 머리글도,
  인용문도 없이 본문만 남는다(실측 2026-09-22: 9/21 김철수의 '와~ 이거 스포
  쪼끔만 해주셔도 되나요?!!' 는 txt 에서 앞뒤와 아무 연결이 없어 혼자 떨어진
  스레드가 됐다. 실제로는 사흘 전 홍길동의 △△ 개편 글에 단 답장이었다).

  그런데 **화면에는 남아 있다.** 답장 말풍선은 이렇게 그려진다(실측 2026-09-22):

      김철수                          <- 보낸 사람
      +------------------------+
      | 홍길동에게 답장           |  검정 굵게 - 부모의 보낸이
      | ○○부에서 △△ 개편을 ... |  회색 - 인용된 원문
      | ---------------------- |  연회색 구분선
      | 와~ 이거 스포 쪼끔만 ...   |  검정 - 실제 본문
      +------------------------+

  그래서 내보내기로 못 받는 것을 화면에서 받아 온다. audit_thread_fit.py 가
  내용으로 **추론**하던 것을 여기서는 **사실**로 확정한다.

무엇을 남기고 무엇을 버리나 - OCR 글자는 저장하지 않는다
  OCR 은 부정확하다(실측: '일치시키는' -> '일지시기는', '스포' -> '人포').
  그 글자를 아카이브에 넣으면 본문이 오염된다. 그래서 OCR 로 읽은 글은 **이미
  아카이브에 있는 원문과 맞춰보는 열쇠로만** 쓰고, 남기는 것은 메시지 ID 한 쌍
  (child -> parent)뿐이다. 맞출 원문이 없으면 그 건은 버린다.

설계 - 창을 다루는 일과 그림을 읽는 일을 나눈다
  kakao_drawer.ps1 과 같은 구조다. 여기서는 PrintWindow 로 찍고 OCR 만 해서
  프레임별 JSON 을 떨구고, scripts/reply_bubbles.py 가 색으로 인용문과 본문을
  가르고 아카이브와 맞춘다.

실측으로 확정된 것 (2026-09-22)
  · 방 창 '바이브코딩,...' 아래 가장 큰 EVA_VH_ListControl_Dblclk 가 메시지 목록
  · PrintWindow(PW_RENDERFULLCONTENT) 는 가려진 채로 찍힌다 -> 밤에 돌아도
    사람 화면을 가로채지 않는다. 포커스를 뺏지 않는다
  · 휠 한 노치 = **90px** (프레임 상관관계로 실측, 잔차 67 대 기준선 4945)
  · 목록 패널 높이 653px -> 3노치(270px)씩 올리면 383px 이 겹친다
  · 말풍선은 한 프레임보다 클 수 있다. 그래서 프레임을 **이어 붙여** 본다 -
    겹침으로 실제 이동량을 다시 재므로 카톡이 지연 로딩으로 튀어도 따라간다

안전
  · 이 스크립트가 방 창에 보내는 것은 **WM_MOUSEWHEEL 뿐이다.** 클릭도, 키도,
    커서 이동도 없다. 커서를 올리지 않으므로 스크롤이 다른 창에 닿을 수 없다
  · ☰ 메뉴 근처에 가지 않는다 (나가기·대화삭제가 거기 있다)
  · 방 창이 없으면 열지 않고 물러난다 - run_daily.ps1 이 앞서 kakao_export.ps1
    을 돌리고 그쪽이 방 창을 열어 두므로 보통은 이미 있다

사용
  powershell -File scripts\kakao_replies.ps1                  # 최근 이틀치
  powershell -File scripts\kakao_replies.ps1 -Days 7
  powershell -File scripts\kakao_replies.ps1 -KeepShots       # 프레임 PNG 남기기
#>
param(
    [string]$Room = '바이브코딩,업무자동화 화상회의모임',
    # 며칠치 스크롤백을 훑을지. 날짜 구분선을 읽어서 판단한다.
    [int]$Days = 2,
    # 한 번에 몇 노치씩 거슬러 올라갈지. 3 = 270px (패널 653px 중 383px 겹침).
    [int]$Step = 3,
    # 폭주 방지. 60프레임 = 약 16,000px 의 스크롤백.
    [int]$MaxFrames = 60,
    # OCR 배율. 1 로 읽으면 굵은 머리글을 놓친다(실측) - 2 아래로 내리지 말 것.
    [int]$OcrScale = 2,
    [string]$LogDir = 'logs',
    [string]$WorkDir,
    [switch]$KeepShots
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

Add-Type -Name Dpi -Namespace W32 -MemberDefinition '[DllImport("user32.dll")] public static extern bool SetProcessDPIAware();'
[void][W32.Dpi]::SetProcessDPIAware()
Add-Type -AssemblyName System.Drawing

Add-Type -ReferencedAssemblies System.Drawing -TypeDefinition @"
using System;using System.Drawing;using System.Runtime.InteropServices;using System.Text;
public class RP {
  public delegate bool EnumProc(IntPtr h, IntPtr p);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
  [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr p, EnumProc cb, IntPtr x);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool IsWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint f);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr wp, IntPtr lp);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
  public const uint WM_MOUSEWHEEL = 0x020A;

  public static IntPtr ByTitle(string want) {
    IntPtr hit = IntPtr.Zero;
    EnumWindows((h,p) => {
      if (!IsWindowVisible(h)) return true;
      var sb = new StringBuilder(512); GetWindowText(h, sb, 512);
      if (sb.ToString() == want) { hit = h; return false; }
      return true;
    }, IntPtr.Zero);
    return hit;
  }
  // 방 창 아래에서 가장 큰 EVA_VH_ListControl_Dblclk = 메시지 목록.
  // 크기로 고르는 이유: 같은 클래스의 숨은 작은 컨트롤(검색 목록 등)이 섞여 있다.
  public static IntPtr ListPane(IntPtr room, out RECT rect) {
    IntPtr best = IntPtr.Zero; int bestArea = 0; RECT br = new RECT();
    EnumChildWindows(room, (h,p) => {
      var c = new StringBuilder(256); GetClassName(h, c, 256);
      if (c.ToString() != "EVA_VH_ListControl_Dblclk") return true;
      RECT r; GetWindowRect(h, out r);
      int a = (r.Right-r.Left) * (r.Bottom-r.Top);
      if (a > bestArea) { bestArea = a; best = h; br = r; }
      return true;
    }, IntPtr.Zero);
    rect = br; return best;
  }
  // 커서를 옮기지 않는다. lParam 은 WM_MOUSEWHEEL 규약상 화면 좌표이고,
  // 메시지를 컨트롤 핸들로 직접 보내므로 커서가 어디에 있든 상관없다.
  public static void Wheel(IntPtr pane, RECT r, int notches, bool down) {
    int cx = (r.Left + r.Right) / 2, cy = (r.Top + r.Bottom) / 2;
    IntPtr wp = (IntPtr)((down ? -120 : 120) << 16);
    IntPtr lp = (IntPtr)((cy << 16) | (cx & 0xFFFF));
    for (int i = 0; i < notches; i++) {
      PostMessage(pane, WM_MOUSEWHEEL, wp, lp);
      System.Threading.Thread.Sleep(90);
    }
  }
  public static Bitmap Shoot(IntPtr h) {
    RECT r; GetWindowRect(h, out r);
    int w = r.Right-r.Left, ht = r.Bottom-r.Top;
    if (w <= 0 || ht <= 0) return null;
    var bmp = new Bitmap(w, ht);
    using (var g = Graphics.FromImage(bmp)) {
      IntPtr dc = g.GetHdc(); bool ok = PrintWindow(h, dc, 0x2); g.ReleaseHdc(dc);
      if (!ok) { bmp.Dispose(); return null; }
    }
    return bmp;
  }
}
"@

Set-Location (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
. (Join-Path $PSScriptRoot 'kakao_ocr.ps1')

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$script:LogPath = Join-Path $LogDir ("kakao-replies-{0}.log" -f (Get-Date -Format 'yyyyMMdd'))
function Write-Log { param([string]$m, [string]$level = 'INFO')
    $line = "[{0}] {1} {2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $level, $m
    Write-Host $line
    try { Add-Content -Path $script:LogPath -Value $line -Encoding utf8 } catch {}
}

function Get-PaneHash { param([IntPtr]$Win, $Box)
    <# 패널을 성기게 훑은 합. 스크롤이 더 움직이는지만 보면 되므로 이걸로 충분하다. #>
    $bmp = [RP]::Shoot($Win)
    if ($null -eq $bmp) { return -1 }
    try {
        $sum = 0
        for ($y = $Box.y; $y -lt ($Box.y + $Box.h); $y += 7) {
            for ($x = $Box.x; $x -lt ($Box.x + $Box.w); $x += 7) {
                if ($x -lt $bmp.Width -and $y -lt $bmp.Height) {
                    $c = $bmp.GetPixel($x, $y)
                    $sum += ($c.R + $c.G + $c.B)
                }
            }
        }
        return $sum
    } finally { $bmp.Dispose() }
}

function Reset-ToBottom { param([IntPtr]$Win, [IntPtr]$Pane, $Rect, $Box, [int]$MaxRounds = 40)
    <# 고정 노치 수로 내리면 안 된다 - 실측 2026-09-22: 40노치(3600px)로는 바닥에
       닿지 못해 9/21~9/22 가 통째로 캡처에서 빠졌고, 그날 답장을 하나도 못 건졌다.
       화면이 더 안 바뀔 때까지 내린다. #>
    $prev = -2
    for ($r = 1; $r -le $MaxRounds; $r++) {
        [RP]::Wheel($Pane, $Rect, 10, $true)
        Start-Sleep -Milliseconds 250
        $h = Get-PaneHash $Win $Box
        if ($h -eq $prev) { return $r }
        $prev = $h
    }
    return $MaxRounds
}

function New-Scaled { param([string]$Path, [int]$Scale)
    <# 프레임을 확대한 임시 PNG 를 만들어 경로를 돌려준다. #>
    if ($Scale -eq 1) { return $Path }
    $src = [System.Drawing.Image]::FromFile($Path)
    try {
        $big = New-Object System.Drawing.Bitmap ($src.Width * $Scale), ($src.Height * $Scale)
        $g = [System.Drawing.Graphics]::FromImage($big)
        $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $g.DrawImage($src, 0, 0, ($src.Width * $Scale), ($src.Height * $Scale))
        $g.Dispose()
    } finally { $src.Dispose() }
    $out = [System.IO.Path]::ChangeExtension($Path, ".x$Scale.png")
    $big.Save($out, [System.Drawing.Imaging.ImageFormat]::Png)
    $big.Dispose()
    $out
}

function Write-Utf8NoBom { param([string]$Path, [string]$Text)
    # PS 5.1 의 Set-Content -Encoding utf8 은 BOM 을 붙인다. 파이썬 쪽 공용 리더
    # (scripts/jsonio.read_json)는 BOM 없는 UTF-8 을 읽으므로 여기서 맞춰 쓴다.
    [System.IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding($false)))
}

if (-not $WorkDir) {
    $WorkDir = Join-Path ([System.IO.Path]::GetTempPath()) ("kakao-replies-" + [guid]::NewGuid().ToString('N'))
}
New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null

Write-Log "답장 수집 시작 - 방 '$Room', $Days 일치, 작업폴더 $WorkDir"

$hRoom = [RP]::ByTitle($Room)
if ($hRoom -eq [IntPtr]::Zero) {
    # 열지 않는다. run_daily.ps1 이 앞서 kakao_export.ps1 을 돌려 방 창을 열어 둔다.
    Write-Log "방 창이 없습니다 - 답장 수집을 건너뜁니다 (kakao_export.ps1 이 먼저 돌아야 합니다)" 'WARN'
    exit 2
}
$paneRect = New-Object RP+RECT
$pane = [RP]::ListPane($hRoom, [ref]$paneRect)
if ($pane -eq [IntPtr]::Zero) { Write-Log "메시지 목록 패널을 찾지 못했습니다" 'ERROR'; exit 1 }

$winRect = New-Object RP+RECT
[void][RP]::GetWindowRect($hRoom, [ref]$winRect)
# 패널을 창 기준 좌표로. reply_bubbles.py 가 이 사각형 안만 본다.
$paneBox = @{
    x = $paneRect.Left - $winRect.Left
    y = $paneRect.Top  - $winRect.Top
    w = $paneRect.Right - $paneRect.Left
    h = $paneRect.Bottom - $paneRect.Top
}
Write-Log ("목록 패널: 창 기준 {0},{1} {2}x{3}" -f $paneBox.x, $paneBox.y, $paneBox.w, $paneBox.h)

# 맨 아래로 - 시작 위치를 사람이 어디에 두었든 같은 곳에서 출발한다.
Write-Log "맨 아래로 내립니다"
$rounds = Reset-ToBottom $hRoom $pane $paneRect $paneBox
Write-Log ("  {0}번 만에 바닥" -f $rounds)

$frames = @()
$script:lastHash = -1
$script:stuck = 0
for ($i = 1; $i -le $MaxFrames; $i++) {
    if (-not [RP]::IsWindow($hRoom)) { Write-Log "방 창이 사라졌습니다 - 여기까지만" 'WARN'; break }
    $bmp = [RP]::Shoot($hRoom)
    if ($null -eq $bmp) { Write-Log "PrintWindow 실패 (프레임 $i)" 'WARN'; break }
    $png = Join-Path $WorkDir ("frame-{0:d3}.png" -f $i)
    $bmp.Save($png, [System.Drawing.Imaging.ImageFormat]::Png)
    $bmp.Dispose()

    # **2배로 키워 읽는다.** 실측 2026-09-22: 원본 크기로 읽으면 답장 머리글
    # ('홍길동에게 답장')을 통째로 놓치고 본문도 '스포'를 '人포'로 읽는다.
    # 2배에서는 머리글이 잡히고 본문도 정확해졌다. 좌표는 Get-OcrLines 가
    # -Scale 로 나눠 돌려주므로 창 기준 그대로다.
    $scaled = New-Scaled $png $OcrScale
    $lines = @(Get-OcrLines -Path $scaled -Scale $OcrScale)
    # 확대본은 바로 버린다. 수백 프레임을 돌리면 원본보다 큰 것이 그만큼 쌓인다.
    if ($scaled -ne $png) { Remove-Item $scaled -Force -ErrorAction SilentlyContinue }
    $json = Join-Path $WorkDir ("frame-{0:d3}.json" -f $i)
    Write-Utf8NoBom $json (@{ image = $png; index = $i; pane = $paneBox; lines = $lines } |
        ConvertTo-Json -Depth 5 -Compress)
    $frames += $json

    # 날짜 구분선을 읽어 얼마나 거슬러 왔는지 본다. OCR 이 '㈜ 2026년 9월 21일 ...'
    # 처럼 앞에 쓰레기를 붙이므로 숫자만 뽑되, **요일까지 붙은 줄만** 구분선으로 본다.
    # 실측 2026-09-22: 요일을 안 따졌더니 '하나 궁금한건 수집 기간이 2026년 02월'
    # 이라는 **메시지 본문**을 구분선으로 읽고 거기서 수집을 멈췄다. 사람이 대화에
    # 날짜를 적기만 해도 그날치 수집이 잘리는 셈이다.
    # -match 와 $Matches 를 쓰지 않는다 - 왼편이 문자열이 아니면 $Matches 가 비어 있고(실측),
    # 그 때 조용히 터진다. [regex]::Match 는 입력을 문자열로 받아 그럴 여지가 없다.
    $oldest = $null
    foreach ($l in $lines) {
        $m = [regex]::Match([string]$l.text,
            '(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일\s*[월화수목금토일]\s*요일\s*$')
        if ($m.Success) {
            $d = Get-Date -Year ([int]$m.Groups[1].Value) -Month ([int]$m.Groups[2].Value) -Day ([int]$m.Groups[3].Value)
            if ($null -eq $oldest -or $d -lt $oldest) { $oldest = $d }
        }
    }
    if ($oldest -and $oldest -lt (Get-Date).Date.AddDays(-$Days)) {
        Write-Log ("프레임 {0}: {1:yyyy-MM-dd} 까지 올라왔습니다 - 충분합니다" -f $i, $oldest)
        break
    }

    [RP]::Wheel($pane, $paneRect, $Step, $false)
    Start-Sleep -Milliseconds 350

    # 스크롤백 꼭대기에 닿으면 화면이 더 안 바뀐다. 그대로 두면 MaxFrames 까지
    # 같은 그림을 찍으며 헛돈다 - 길게 돌릴 때는 그게 십수 분이다.
    $h = Get-PaneHash $hRoom $paneBox
    if ($h -eq $script:lastHash) {
        $script:stuck++
        if ($script:stuck -ge 3) {
            Write-Log ("프레임 {0}: 더 올라갈 데가 없습니다 - 스크롤백 꼭대기입니다" -f $i)
            break
        }
    } else {
        $script:stuck = 0
        $script:lastHash = $h
    }
}
Write-Log ("프레임 {0}장 확보" -f $frames.Count)

# 사람이 보던 자리로 되돌린다 - 방 창은 맨 아래가 자연스러운 자리다.
# 여기서도 고정 노치 수를 쓰지 않는다. 덜 내려가면 다음 실행이 바닥에서
# 출발하지 못한다.
[void](Reset-ToBottom $hRoom $pane $paneRect $paneBox)

$manifest = Join-Path $WorkDir 'frames.json'
Write-Utf8NoBom $manifest (@{ room = $Room; frames = $frames; pane = $paneBox } |
    ConvertTo-Json -Depth 5)

Write-Log "그림 읽기로 넘깁니다 - scripts/reply_bubbles.py"
& python -m scripts.reply_bubbles --frames $manifest
$code = $LASTEXITCODE
if ($code -ne 0) { Write-Log "reply_bubbles.py 실패 (exit $code)" 'ERROR' }

if (-not $KeepShots -and $code -eq 0) {
    Remove-Item -Recurse -Force $WorkDir -ErrorAction SilentlyContinue
} else {
    Write-Log "프레임을 남겼습니다: $WorkDir"
}
exit $code
