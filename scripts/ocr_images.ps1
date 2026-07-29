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
    [System.IO.File]::WriteAllText($Path, $json, [System.Text.UTF8Encoding]::new($false))
}

$outPath = Join-Path $root "output\image_ocr.json"
$done = @{}
if ((Test-Path $outPath) -and -not $Force) {
    $prev = Get-Content $outPath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($p in $prev.PSObject.Properties) { $done[$p.Name] = $p.Value }
    "이미 읽은 사진 $($done.Count)장은 건너뜁니다 (-Force 로 다시 읽기)"
}

# OCR 엔진이 받는 최대 변 길이. Windows.Media.Ocr 은 넘으면 예외를 던진다.
$maxDim = 4000
$sliceHeight = 3000     # 잘라 넣을 때 한 조각의 높이
$sliceOverlap = 120     # 자른 자리에 걸친 글자 줄을 잃지 않게 겹치는 폭

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
    if ($done.ContainsKey($key)) { continue }

    try {
        # 작은 사진은 확대해야 글자가 읽힌다. 큰 화면 캡처는 원본 배율로 충분하고
        # 2배로 키우면 시간만 두 배가 된다.
        $img = [System.Drawing.Image]::FromFile($f.FullName)
        $w = $img.Width; $h = $img.Height
        $img.Dispose()
        $scale = if ($w -lt 1000) { 2 } else { 1 }

        if ($h -le $sliceHeight -and $w -le $maxDim) {
            $lines = @(Get-OcrLines -Path $f.FullName -Scale $scale | ForEach-Object { $_.text })
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
