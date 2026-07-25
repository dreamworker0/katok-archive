# OCR 유틸 — 화면 영역의 글자를 좌표와 함께 읽는다.
#
# 왜 필요한가
#   카카오톡 UI 는 접근성 API 에 아무것도 노출하지 않는다(Button·MenuItem 0개).
#   그래서 좌표 클릭이 불가피한데, 메뉴에서 '대화 내용' 바로 아래 약 51px 지점에
#   '채팅방 나가기' 가 있다. 추정 좌표로 클릭하면 40명 방을 나가버릴 수 있다.
#   따라서 "클릭할 지점의 글자를 OCR 로 먼저 읽어 기대한 텍스트인지 확인"하고,
#   기대와 다르면 클릭하지 않고 중단한다.
#
# 사용: . scripts\kakao_ocr.ps1  (점 소싱)

Add-Type -AssemblyName System.Drawing, System.Windows.Forms, System.Runtime.WindowsRuntime

# WinRT IAsyncOperation<T> 을 동기로 기다리는 표준 패턴
$script:AsTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() |
    Where-Object {
        $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    })[0]

function Wait-WinRt {
    param($Operation, [Type]$ResultType)
    $asTask = $script:AsTaskGeneric.MakeGenericMethod($ResultType)
    $task = $asTask.Invoke($null, @($Operation))
    [void]$task.Wait(-1)
    $task.Result
}

function Save-ScreenRegion {
    <# 화면 영역을 확대해 PNG 로 저장하고 경로를 반환 #>
    param([int]$X, [int]$Y, [int]$Width, [int]$Height, [int]$Scale = 2, [string]$Path)
    if (-not $Path) { $Path = [System.IO.Path]::Combine($env:TEMP, "ocr-$([guid]::NewGuid().ToString('N')).png") }
    $src = New-Object System.Drawing.Bitmap $Width, $Height
    $g = [System.Drawing.Graphics]::FromImage($src)
    $g.CopyFromScreen($X, $Y, 0, 0, (New-Object System.Drawing.Size $Width, $Height))
    $g.Dispose()
    if ($Scale -ne 1) {
        $big = New-Object System.Drawing.Bitmap ($Width * $Scale), ($Height * $Scale)
        $g2 = [System.Drawing.Graphics]::FromImage($big)
        $g2.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $g2.DrawImage($src, 0, 0, ($Width * $Scale), ($Height * $Scale))
        $g2.Dispose()
        $big.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
        $big.Dispose()
    } else {
        $src.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
    }
    $src.Dispose()
    $Path
}

function Get-OcrLines {
    <#
      이미지 파일을 OCR 해서 줄 목록을 반환한다.
      반환: @{ text; x; y }  — x,y 는 화면 절대좌표(원점·배율 보정 후) 중심
    #>
    param([string]$Path, [int]$OriginX = 0, [int]$OriginY = 0, [int]$Scale = 2)

    $null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
    $null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime]
    $null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]

    $file = Wait-WinRt ([Windows.Storage.StorageFile]::GetFileFromPathAsync($Path)) ([Windows.Storage.StorageFile])
    $stream = Wait-WinRt ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Wait-WinRt ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Wait-WinRt ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])

    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
    if ($null -eq $engine) { throw "OCR 엔진 생성 실패" }
    $result = Wait-WinRt ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])

    $lines = @()
    foreach ($line in $result.Lines) {
        # 줄의 중심 = 단어 경계들의 합집합
        $minX = [double]::MaxValue; $maxX = 0.0
        $minY = [double]::MaxValue; $maxY = 0.0
        foreach ($w in $line.Words) {
            $r = $w.BoundingRect
            if ($r.X -lt $minX) { $minX = $r.X }
            if (($r.X + $r.Width) -gt $maxX) { $maxX = $r.X + $r.Width }
            if ($r.Y -lt $minY) { $minY = $r.Y }
            if (($r.Y + $r.Height) -gt $maxY) { $maxY = $r.Y + $r.Height }
        }
        if ($line.Words.Count -eq 0) { continue }
        $lines += [pscustomobject]@{
            text = $line.Text
            x    = [int]($OriginX + (($minX + $maxX) / 2) / $Scale)
            y    = [int]($OriginY + (($minY + $maxY) / 2) / $Scale)
            left = [int]($OriginX + $minX / $Scale)
        }
    }
    , $lines
}

function Get-ScreenOcr {
    <# 화면 영역을 바로 OCR (캡처 + 인식) #>
    param([int]$X, [int]$Y, [int]$Width, [int]$Height, [int]$Scale = 2)
    $p = Save-ScreenRegion -X $X -Y $Y -Width $Width -Height $Height -Scale $Scale
    try { Get-OcrLines -Path $p -OriginX $X -OriginY $Y -Scale $Scale }
    finally { Remove-Item $p -Force -ErrorAction SilentlyContinue }
}
