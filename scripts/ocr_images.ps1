# 보관된 사진의 글자를 전부 읽어 output/image_ocr.json 에 쌓는다.
#
# 왜 PowerShell 인가
#   Windows 내장 OCR(Windows.Media.Ocr)은 무료·오프라인이고 한국어를 읽는다.
#   `scripts/kakao_ocr.ps1` 이 이미 이 엔진을 감싸 두었다 — 원래는 '채팅방 나가기'
#   오클릭을 막기 위해 화면 글자를 확인하는 용도였는데, 파일에도 그대로 쓸 수 있다.
#   파이썬에서 사진 한 장마다 PowerShell 을 새로 띄우면 프로세스 시작 비용이
#   OCR 자체보다 크므로, 한 번 띄워 전부 읽고 JSON 으로 넘긴다.
#
# 읽은 글자를 개인정보로 판정하는 일은 `scripts/scan_image_pii.py` 가 한다.
#
# 사용:  powershell -File scripts\ocr_images.ps1 [-Force]
#   -Force 없이 돌리면 이미 읽은 사진은 건너뛴다(매일 갱신용).

param([switch]$Force)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "kakao_ocr.ps1")

function Save-Json {
    <# BOM 없는 UTF-8 로 쓴다.
       `Out-File -Encoding utf8` 은 Windows PowerShell 5.1 에서 BOM 을 붙이는데,
       파이썬 `json.load` 는 BOM 을 만나면 그대로 예외를 던진다(실측). 이 파일을
       읽는 쪽이 `scripts/scan_image_pii.py` 이므로 여기서 맞춰 준다. #>
    param($Object, [string]$Path)
    $json = $Object | ConvertTo-Json -Depth 4 -Compress
    # 옆에 다 쓴 뒤 바꿔 끼운다(2026-11-11 외부 평가 지적). 바로 덮어쓰다 끊기면 파일이
    # 깨지고, 다음 밤 이 스크립트가 읽다 죽어 '사진 개인정보 검사' 단계(치명)가 그날
    # 발행 전체를 멈췄다.
    $tmp = "$Path.tmp"
    [System.IO.File]::WriteAllText($tmp, $json, [System.Text.UTF8Encoding]::new($false))
    # 셋째 인자(백업 경로)에 $null 을 그냥 넘기면 PowerShell 이 "" 로 바꿔 넘겨
    # "The path is not of a legal form." 으로 죽는다(2026-11-11 밤 갱신이 여기서 멈춤).
    # [NullString]::Value 라야 .NET 에 진짜 null 이 간다.
    if (Test-Path $Path) { [System.IO.File]::Replace($tmp, $Path, [NullString]::Value) }
    else { [System.IO.File]::Move($tmp, $Path) }
}

$outPath = Join-Path $root "output\image_ocr.json"
$done = @{}
if ((Test-Path $outPath) -and -not $Force) {
    try {
        $prev = Get-Content $outPath -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($p in $prev.PSObject.Properties) { $done[$p.Name] = $p.Value }
        "이미 읽은 사진 $($done.Count)장은 건너뜁니다 (-Force 로 다시 읽기)"
    } catch {
        # 깨진 결과 파일 때문에 발행이 멈추면 안 된다 — 옆으로 치우고 처음부터 읽는다.
        # 오래 걸릴 뿐(사진 수백 장) 틀린 판정을 내지는 않는다.
        $broken = "$outPath.broken-$(Get-Date -Format yyyyMMddHHmmss)"
        Move-Item -LiteralPath $outPath -Destination $broken -Force
        Write-Warning "OCR 결과 파일을 읽지 못해 $broken 로 옮기고 처음부터 읽습니다: $($_.Exception.Message)"
        $done = @{}
    }
}

# OCR 엔진이 받는 최대 변 길이. Windows.Media.Ocr 은 넘으면 예외를 던진다.
$maxDim = 4000
$sliceHeight = 3000     # 잘라 넣을 때 한 조각의 높이
$sliceOverlap = 120     # 자른 자리에 걸친 글자 줄을 잃지 않게 겹치는 폭

function Read-Upscaled {
    <# 작은 사진을 두 배로 키운 PNG 를 임시로 만들어 OCR 하고 글자 줄만 돌려준다. #>
    param([string]$Path, [int]$Width, [int]$Height)
    $src = [System.Drawing.Image]::FromFile($Path)
    $tmp = [System.IO.Path]::Combine($env:TEMP, "ocrup-$([guid]::NewGuid().ToString('N')).png")
    try {
        $bmp = New-Object System.Drawing.Bitmap ($Width * 2), ($Height * 2)
        $g = [System.Drawing.Graphics]::FromImage($bmp)
        $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $g.DrawImage($src, 0, 0, $Width * 2, $Height * 2)
        $g.Dispose()
        $bmp.Save($tmp, [System.Drawing.Imaging.ImageFormat]::Png)
        $bmp.Dispose()
        # 줄을 하나씩 흘려보낸다 — 부르는 쪽이 @( ) 로 받는다. 배열로 한 겹 싸서
        # 돌려주면 @( ) 안에서 '배열 하나짜리 배열' 이 되어 글자가 System.Object[] 로 남는다.
        Get-OcrLines -Path $tmp -Scale 2 | ForEach-Object { $_.text }
    } finally {
        $src.Dispose()
        Remove-Item $tmp -Force -ErrorAction SilentlyContinue
    }
}

function Split-TallImage {
    <# 긴 이미지를 조각으로 잘라 각각 OCR 하고 줄 목록을 합친다. #>
    param([string]$Path, [int]$Width, [int]$Height)
    $out = @()
    $src = [System.Drawing.Image]::FromFile($Path)
    try {
        # 폭이 한도를 넘으면 폭만 줄인다(가로로 긴 표는 드물다)
        $ratio = if ($Width -gt $maxDim) { $maxDim / $Width } else { 1.0 }
        $y = 0
        while ($y -lt $Height) {
            $sliceH = [Math]::Min($sliceHeight, $Height - $y)
            $tw = [int]($Width * $ratio); $th = [int]($sliceH * $ratio)
            if ($tw -lt 1 -or $th -lt 1) { break }
            $bmp = New-Object System.Drawing.Bitmap $tw, $th
            $g = [System.Drawing.Graphics]::FromImage($bmp)
            $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
            $g.DrawImage($src,
                (New-Object System.Drawing.Rectangle 0, 0, $tw, $th),
                (New-Object System.Drawing.Rectangle 0, $y, $Width, $sliceH),
                [System.Drawing.GraphicsUnit]::Pixel)
            $g.Dispose()
            $tmp = [System.IO.Path]::Combine($env:TEMP, "ocrslice-$([guid]::NewGuid().ToString('N')).png")
            $bmp.Save($tmp, [System.Drawing.Imaging.ImageFormat]::Png)
            $bmp.Dispose()
            try {
                $out += @(Get-OcrLines -Path $tmp -Scale 1 | ForEach-Object { $_.text })
            } finally {
                Remove-Item $tmp -Force -ErrorAction SilentlyContinue
            }
            if ($sliceH -lt $sliceHeight) { break }
            $y += ($sliceHeight - $sliceOverlap)
        }
    } finally {
        $src.Dispose()
    }
    , $out
}

$files = Get-ChildItem (Join-Path $root "assets\images") -Recurse -File |
    Where-Object { $_.Extension -match '^\.(jpg|jpeg|png|gif|bmp|webp)$' }
"사진 $($files.Count)장"

$i = 0
$read = 0
foreach ($f in $files) {
    $i++
    # 키는 저장소 기준 상대경로 — 발행 목록(images.json)과 같은 표기여야 맞춰볼 수 있다
    $key = $f.FullName.Substring($root.Length + 1).Replace('\', '/')
    # 읽은 사진만 건너뛴다. 못 읽은 것(null)은 다음 밤에 다시 해 본다(2026-11-11 외부
    # 평가 지적) — 한 번 실패를 영구 '확인 못 함' 으로 굳히면, 판정 쪽이 그 사진을 공개
    # 쪽으로 넘기는 동안 다시 볼 기회가 없었다. 계속 실패하면 null 로 남을 뿐이다.
    if ($done.ContainsKey($key) -and $null -ne $done[$key]) { continue }

    try {
        # 크기를 잰다. GDI+(System.Drawing)는 .webp 를 못 연다 — 그때는 크기를 모른 채
        # WinRT 디코더(OCR 이 쓰는 것)에 원본을 바로 넘긴다. 예전에는 여기서 예외가 나
        # 그 사진이 '확인 못 함' 으로 공개됐다(2026-11-11 외부 평가 지적).
        $w = 0; $h = 0
        try {
            $img = [System.Drawing.Image]::FromFile($f.FullName)
            $w = $img.Width; $h = $img.Height
            $img.Dispose()
        } catch { $w = 0 }

        if ($w -eq 0) {
            $lines = @(Get-OcrLines -Path $f.FullName -Scale 1 | ForEach-Object { $_.text })
        } elseif ($w -lt 1000 -and $h * 2 -le $sliceHeight) {
            # 작은 사진은 **실제로** 두 배로 키워서 읽는다. Get-OcrLines 의 -Scale 은 돌려줄
            # 좌표만 나누는 값이라, 예전처럼 -Scale 2 만 넘기면 확대 없이 그대로 읽었다
            # (2026-11-11 외부 평가 지적 — 작은 캡처 속 전화번호를 놓칠 수 있었다).
            $lines = @(Read-Upscaled -Path $f.FullName -Width $w -Height $h)
        } elseif ($h -le $sliceHeight -and $w -le $maxDim) {
            $lines = @(Get-OcrLines -Path $f.FullName -Scale 1 | ForEach-Object { $_.text })
        } else {
            # 긴 화면 캡처는 OCR 엔진의 최대 크기를 넘는다(실측: 카톡 대화 통짜
            # 캡처 한 장이 "Image dimensions are too large" 로 실패했다).
            #
            # 줄여서 넣지 않고 **잘라서** 넣는다. 긴 캡처를 한도에 맞게 줄이면
            # 글자가 뭉개져 읽으나 마나가 된다. 자른 자리에 걸친 줄을 잃지 않도록
            # 조금 겹쳐 자른다.
            $lines = @()
            $lines += Split-TallImage -Path $f.FullName -Width $w -Height $h
        }
        $done[$key] = $lines
        $read++
    } catch {
        # 읽지 못한 사진은 빈 목록이 아니라 null 로 남긴다 — 빈 목록은 "글자가
        # 없다"는 뜻이고, null 은 "확인하지 못했다"는 뜻이다. 판정 쪽에서 갈라 쓴다.
        $done[$key] = $null
        Write-Warning "$key : $($_.Exception.Message)"
    }

    if ($i % 50 -eq 0) {
        "  $i / $($files.Count) ..."
        Save-Json $done $outPath
    }
}

Save-Json $done $outPath
"완료: 새로 읽은 사진 $($read)장 / 누적 $($done.Count)장 → output/image_ocr.json"
