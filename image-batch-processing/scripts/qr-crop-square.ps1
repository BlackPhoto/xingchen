# qr-crop-square.ps1 — 批量把含二维码的图片裁成正方形（仅保留二维码）
# 用法: powershell -ExecutionPolicy Bypass -File qr-crop-square.ps1 -Dir <目录> [-Filter "*二维码*"] [-Threshold 0.4] [-Margin 0.05] [-WhatIf]
# 依赖: .NET System.Drawing（Windows 内置，无需安装任何库）
# 原理: 二维码黑白点阵密集，行/列灰度方差显著高于纯色背景与平滑渐变区；
#       取方差超阈值的行列区间得包围盒，扩正方形加边距后按原格式保存。
param(
    [Parameter(Mandatory=$true)][string]$Dir,
    [string]$Filter = "*二维码*",
    [double]$Threshold = 0.4,      # 方差阈值（相对最大方差的比例）
    [double]$Margin   = 0.05,     # 裁切边距（相对边长的比例）
    [switch]$WhatIf
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

function Get-QrBoundingBox {
    param([System.Drawing.Bitmap]$bmp, [double]$Threshold)
    $w = $bmp.Width; $h = $bmp.Height
    $gray = New-Object 'double[]'($w * $h)
    for ($y = 0; $y -lt $h; $y++) {
        for ($x = 0; $x -lt $w; $x++) {
            $c = $bmp.GetPixel($x, $y)
            $gray[$y * $w + $x] = ($c.R * 299 + $c.G * 587 + $c.B * 114) / 1000.0
        }
    }
    function Var([double[]]$a) {
        if ($a.Count -eq 0) { return 0.0 }
        $m = ($a | Measure-Object -Average).Average
        $s = 0.0; foreach ($v in $a) { $s += ($v - $m) * ($v - $m) }
        return $s / $a.Count
    }
    $rowVar = New-Object 'double[]'($h)
    for ($y = 0; $y -lt $h; $y++) {
        $row = New-Object 'double[]'($w)
        [Array]::Copy($gray, $y * $w, $row, 0, $w)
        $rowVar[$y] = Var $row
    }
    $colVar = New-Object 'double[]'($w)
    for ($x = 0; $x -lt $w; $x++) {
        $col = New-Object 'double[]'($h)
        for ($y = 0; $y -lt $h; $y++) { $col[$y] = $gray[$y * $w + $x] }
        $colVar[$x] = Var $col
    }
    $maxRow = ($rowVar | Measure-Object -Maximum).Maximum
    $maxCol = ($colVar | Measure-Object -Maximum).Maximum
    if ($maxRow -le 0 -or $maxCol -le 0) { return $null }
    $rowCut = $maxRow * $Threshold; $colCut = $maxCol * $Threshold
    $rows = 0..($h-1) | Where-Object { $rowVar[$_] -ge $rowCut }
    $cols = 0..($w-1) | Where-Object { $colVar[$_] -ge $colCut }
    if (-not $rows -or -not $cols) { return $null }
    $y0 = ($rows | Measure-Object -Minimum).Minimum; $y1 = ($rows | Measure-Object -Maximum).Maximum
    $x0 = ($cols | Measure-Object -Minimum).Minimum; $x1 = ($cols | Measure-Object -Maximum).Maximum
    return @{ X0=$x0; Y0=$y0; X1=$x1; Y1=$y1 }
}

$files = Get-ChildItem $Dir -File | Where-Object { $_.Name -like $Filter -and $_.Extension -match '^\.(jpg|jpeg|png|bmp)$' }
Write-Output "待处理: $($files.Count) 个文件"

$ok = 0; $skip = 0; $fail = 0; $failed = @()
foreach ($f in $files) {
    try {
        $img = [System.Drawing.Image]::FromFile($f.FullName)
        $w = $img.Width; $h = $img.Height
        if ($w -eq $h) { $img.Dispose(); $skip++; continue }   # 已是正方形

        # 缩到最长边 300px 做方差分析
        $scale = [Math]::Max(1.0, [Math]::Max($w, $h) / 300.0)
        $sw = [int][Math]::Round($w / $scale); $sh = [int][Math]::Round($h / $scale)
        $small = New-Object System.Drawing.Bitmap($sw, $sh)
        $g = [System.Drawing.Graphics]::FromImage($small)
        $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::Bilinear
        $g.DrawImage($img, 0, 0, $sw, $sh); $g.Dispose()

        $box = Get-QrBoundingBox -bmp $small -Threshold $Threshold
        $small.Dispose()
        if (-not $box) { $img.Dispose(); $fail++; $failed += $f.Name; continue }

        # 映射回原图坐标
        $x0 = [int][Math]::Floor($box.X0 * $scale); $y0 = [int][Math]::Floor($box.Y0 * $scale)
        $x1 = [int][Math]::Ceiling(($box.X1 + 1) * $scale); $y1 = [int][Math]::Ceiling(($box.Y1 + 1) * $scale)
        $bw = $x1 - $x0; $bh = $y1 - $y0
        $side = [Math]::Max($bw, $bh)
        $m = [int][Math]::Round($side * $Margin)
        $side += 2 * $m
        # 居中扩正方形并夹在图内
        $cx = [int](($x0 + $x1) / 2); $cy = [int](($y0 + $y1) / 2)
        $sx = [Math]::Max(0, [Math]::Min($w - $side, $cx - [int]($side / 2)))
        $sy = [Math]::Max(0, [Math]::Min($h - $side, $cy - [int]($side / 2)))
        if ($side -gt $w -or $side -gt $h) { $side = [Math]::Min($w, $h); $sx = [int](($w - $side)/2); $sy = [int](($h - $side)/2) }

        $fmt = $img.RawFormat
        $crop = New-Object System.Drawing.Bitmap($side, $side)
        $g2 = [System.Drawing.Graphics]::FromImage($crop)
        $g2.DrawImage($img,
            (New-Object System.Drawing.Rectangle(0, 0, $side, $side)),
            (New-Object System.Drawing.Rectangle($sx, $sy, $side, $side)),
            [System.Drawing.GraphicsUnit]::Pixel)
        $g2.Dispose()
        $img.Dispose()

        if ($WhatIf) { Write-Output "[WhatIf] $($f.Name): ${w}x${h} -> ${side}x${side} @($sx,$sy)"; $crop.Dispose(); $ok++; continue }
        $tmp = Join-Path $f.DirectoryName ($f.BaseName + "_crop_tmp" + $f.Extension)
        $crop.Save($tmp, $fmt)
        $crop.Dispose()
        Move-Item -Path $tmp -Destination $f.FullName -Force   # Dispose 后才能覆盖
        $ok++
    } catch {
        $fail++; $failed += "$($f.Name): $($_.Exception.Message)"
    }
}

Write-Output "完成: 成功 $ok, 跳过(已正方形) $skip, 失败 $fail"
if ($failed.Count -gt 0) {
    Write-Output "失败清单（需人工确认，勿静默跳过）:"
    $failed | ForEach-Object { Write-Output "  $_" }
}
