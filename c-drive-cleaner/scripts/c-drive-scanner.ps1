# C Drive Safe Scanner - Scan and Report Only
$ErrorActionPreference = "SilentlyContinue"
$results = @()

function Get-FolderSizeInfo {
    param([string]$Path, [string]$Label, [string]$Category, [bool]$SafeToDelete = $true)
    if (-not (Test-Path $Path)) { return $null }
    try {
        $files = Get-ChildItem -Path $Path -Recurse -File -Force -ErrorAction SilentlyContinue
        $fileCount = ($files | Measure-Object).Count
        $sizeBytes = 0
        foreach ($f in $files) { $sizeBytes += $f.Length }
        $sizeMB = [math]::Round($sizeBytes / 1MB, 2)
        $obj = New-Object PSObject -Property @{
            Label = $Label; Path = $Path; Category = $Category
            FileCount = $fileCount; SizeBytes = $sizeBytes; SizeMB = $sizeMB; SafeToDelete = $SafeToDelete
        }
        return $obj
    } catch { return $null }
}

# 1-13: Scan items
$r = Get-FolderSizeInfo "C:\Windows\Temp" "Windows Temp" "System Temp"; if ($r) { $results += $r }
$userTemp = [System.IO.Path]::GetTempPath().TrimEnd('\')
$r = Get-FolderSizeInfo $userTemp "User Temp" "User Temp"; if ($r) { $results += $r }
$rbPath = 'C:\$Recycle.Bin'
if (Test-Path $rbPath) { $r = Get-FolderSizeInfo $rbPath "Recycle Bin" "Recycle Bin"; if ($r) { $results += $r } }
$r = Get-FolderSizeInfo "C:\Windows\SoftwareDistribution\Download" "Windows Update Cache" "Update Cache"; if ($r) { $results += $r }
$r = Get-FolderSizeInfo "C:\Windows\Prefetch" "Prefetch Data" "System Cache" $false; if ($r) { $results += $r }

$thumbPath = "$env:LOCALAPPDATA\Microsoft\Windows\Explorer"
if (Test-Path $thumbPath) {
    $thumbFiles = Get-ChildItem $thumbPath -Filter "thumbcache_*.db" -Force -ErrorAction SilentlyContinue
    if ($thumbFiles) {
        $tSize = 0; foreach ($tf in $thumbFiles) { $tSize += $tf.Length }
        $results += New-Object PSObject -Property @{
            Label="Thumbnail Cache"; Path="$thumbPath\thumbcache_*.db"; Category="System Cache"
            FileCount=$thumbFiles.Count; SizeBytes=$tSize; SizeMB=[math]::Round($tSize/1MB,2); SafeToDelete=$true
        }
    }
}

$r = Get-FolderSizeInfo "$env:LOCALAPPDATA\Microsoft\Edge\User Data\Default\Cache" "Edge Browser Cache" "Browser Cache"; if ($r) { $results += $r }
$r = Get-FolderSizeInfo "$env:LOCALAPPDATA\Google\Chrome\User Data\Default\Cache" "Chrome Browser Cache" "Browser Cache"; if ($r) { $results += $r }
$r = Get-FolderSizeInfo "C:\Windows\Logs" "Windows Logs" "Log Files"; if ($r) { $results += $r }
$r = Get-FolderSizeInfo "C:\Windows\SoftwareDistribution\DataStore" "Update DataStore" "Update Cache"; if ($r) { $results += $r }

$dlPath = "$env:USERPROFILE\Downloads"
if (Test-Path $dlPath) {
    $bigFiles = Get-ChildItem $dlPath -Recurse -File -Force -ErrorAction SilentlyContinue | Where-Object { $_.Length -gt 100MB } | Sort-Object Length -Descending | Select-Object -First 10
    if ($bigFiles) {
        $bTotal = 0; foreach ($bf in $bigFiles) { $bTotal += $bf.Length }
        $results += New-Object PSObject -Property @{
            Label="Large Files in Downloads (>100MB)"; Path=$dlPath; Category="Large File Alert"
            FileCount=$bigFiles.Count; SizeBytes=$bTotal; SizeMB=[math]::Round($bTotal/1MB,2); SafeToDelete=$false
        }
    }
}

$r = Get-FolderSizeInfo "$env:LOCALAPPDATA\CrashDumps" "Crash Dumps" "Dump Files"; if ($r) { $results += $r }
$r = Get-FolderSizeInfo "C:\ProgramData\Microsoft\Windows\WER" "Windows Error Reports" "Error Reports"; if ($r) { $results += $r }

# ============ Output Report ============
Write-Output ""
Write-Output "=============================================="
Write-Output "       C Drive Junk File Scan Report"
Write-Output "       Scan Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Output "=============================================="
Write-Output ""

$cDrive = Get-WmiObject Win32_LogicalDisk -Filter "DeviceID='C:'"
$freeGB = [math]::Round($cDrive.FreeSpace / 1GB, 2)
$totalGB = [math]::Round($cDrive.Size / 1GB, 2)
$usedGB = [math]::Round(($cDrive.Size - $cDrive.FreeSpace) / 1GB, 2)
$usedPct = [math]::Round(($cDrive.Size - $cDrive.FreeSpace) / $cDrive.Size * 100, 1)

Write-Output "--- C Drive Space Overview ---"
Write-Output "  Total:  $totalGB GB"
Write-Output "  Used:   $usedGB GB ($usedPct%)"
Write-Output "  Free:   $freeGB GB"
Write-Output ""

if ($results.Count -eq 0) {
    Write-Output "No cleanable files found."
} else {
    $safeItems = @($results | Where-Object { $_.SafeToDelete -and $_.SizeMB -gt 0 })
    $unsafeItems = @($results | Where-Object { -not $_.SafeToDelete -and $_.SizeMB -gt 0 })

    $totalMB = 0; foreach ($si in $safeItems) { $totalMB += $si.SizeMB }
    $totalMB = [math]::Round($totalMB, 2)

    Write-Output "--- Safe to Clean ---"
    $fmt = "{0,-40} {1,12} {2,8} {3,-18}"
    Write-Output ($fmt -f "Item", "Size(MB)", "Files", "Category")
    Write-Output ("-" * 80)
    foreach ($item in ($safeItems | Sort-Object SizeBytes -Descending)) {
        Write-Output ($fmt -f $item.Label, $item.SizeMB, $item.FileCount, $item.Category)
    }
    Write-Output ("-" * 80)
    Write-Output ($fmt -f "TOTAL RELEASABLE", "$totalMB MB", "", "")

    if ($unsafeItems.Count -gt 0) {
        Write-Output ""
        Write-Output "--- Caution Items (reference only, NOT auto-deleted) ---"
        Write-Output ($fmt -f "Item", "Size(MB)", "Files", "Category")
        Write-Output ("-" * 80)
        foreach ($item in ($unsafeItems | Sort-Object SizeBytes -Descending)) {
            Write-Output ($fmt -f $item.Label, $item.SizeMB, $item.FileCount, $item.Category)
        }
    }
}

Write-Output ""
Write-Output "=============================================="
Write-Output "  Note: SCAN ONLY - No files have been deleted"
Write-Output "=============================================="

Write-Output ""
Write-Output "---JSON_DATA_START---"
$jsonOut = $results | Where-Object { $_.SizeMB -gt 0 } | Select-Object Label, Path, Category, FileCount, SizeMB, SafeToDelete | ConvertTo-Json -Compress
Write-Output $jsonOut
Write-Output "---JSON_DATA_END---"