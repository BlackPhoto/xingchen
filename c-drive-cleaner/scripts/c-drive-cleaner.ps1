# C Drive Safe Cleaner - Delete confirmed items only
# This script deletes safe-to-clean items after user confirmation

$ErrorActionPreference = "SilentlyContinue"
$deletedMB = 0

function Clean-Folder {
    param([string]$Path, [string]$Label)
    if (-not (Test-Path $Path)) { 
        Write-Output "  SKIP: $Label - Path not found"
        return 0 
    }
    try {
        $beforeSize = 0
        $files = Get-ChildItem -Path $Path -Recurse -File -Force -ErrorAction SilentlyContinue
        foreach ($f in $files) { $beforeSize += $f.Length }
        
        Get-ChildItem -Path $Path -Recurse -Force -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        
        $afterSize = 0
        $files2 = Get-ChildItem -Path $Path -Recurse -File -Force -ErrorAction SilentlyContinue
        foreach ($f in $files2) { $afterSize += $f.Length }
        
        $cleaned = [math]::Round(($beforeSize - $afterSize) / 1MB, 2)
        Write-Output "  DONE: $Label - Freed $cleaned MB"
        return $cleaned
    } catch {
        Write-Output "  FAIL: $Label - Error during cleanup"
        return 0
    }
}

function Clean-Files {
    param([string]$Path, [string]$Filter, [string]$Label)
    if (-not (Test-Path $Path)) { 
        Write-Output "  SKIP: $Label - Path not found"
        return 0 
    }
    try {
        $files = Get-ChildItem -Path $Path -Filter $Filter -Force -ErrorAction SilentlyContinue
        $beforeSize = 0; foreach ($f in $files) { $beforeSize += $f.Length }
        
        $files | Remove-Item -Force -ErrorAction SilentlyContinue
        
        $cleaned = [math]::Round($beforeSize / 1MB, 2)
        Write-Output "  DONE: $Label - Freed $cleaned MB"
        return $cleaned
    } catch {
        Write-Output "  FAIL: $Label - Error during cleanup"
        return 0
    }
}

Write-Output ""
Write-Output "=============================================="
Write-Output "       C Drive Cleanup - Starting"
Write-Output "       Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Output "=============================================="
Write-Output ""

# 1. Windows Temp
$deletedMB += Clean-Folder "C:\Windows\Temp" "Windows Temp"

# 2. User Temp
$userTemp = [System.IO.Path]::GetTempPath().TrimEnd('\')
$deletedMB += Clean-Folder $userTemp "User Temp"

# 3. Recycle Bin
Write-Output "  Cleaning Recycle Bin..."
try {
    $shell = New-Object -ComObject Shell.Application
    $rb = $shell.NameSpace(0x0A)
    $rbItems = $rb.Items()
    $rbCount = $rbItems.Count
    # Use Clear-RecycleBin for cleaner approach
    Clear-RecycleBin -DriveLetter C -Force -ErrorAction SilentlyContinue
    Write-Output "  DONE: Recycle Bin - Cleared $rbCount items"
} catch {
    Write-Output "  FAIL: Recycle Bin - Error"
}

# 4. Windows Update Cache
$deletedMB += Clean-Folder "C:\Windows\SoftwareDistribution\Download" "Windows Update Cache"

# 5. Thumbnail Cache
$thumbPath = "$env:LOCALAPPDATA\Microsoft\Windows\Explorer"
$deletedMB += Clean-Files $thumbPath "thumbcache_*.db" "Thumbnail Cache"

# 6. Edge Cache
$deletedMB += Clean-Folder "$env:LOCALAPPDATA\Microsoft\Edge\User Data\Default\Cache" "Edge Browser Cache"

# 7. Chrome Cache
$deletedMB += Clean-Folder "$env:LOCALAPPDATA\Google\Chrome\User Data\Default\Cache" "Chrome Browser Cache"

# 8. Windows Logs
$deletedMB += Clean-Folder "C:\Windows\Logs" "Windows Logs"

# 9. Update DataStore
$deletedMB += Clean-Folder "C:\Windows\SoftwareDistribution\DataStore" "Update DataStore"

# 10. Crash Dumps
$deletedMB += Clean-Folder "$env:LOCALAPPDATA\CrashDumps" "Crash Dumps"

# 11. Windows Error Reports
$deletedMB += Clean-Folder "C:\ProgramData\Microsoft\Windows\WER" "Windows Error Reports"

# Final report
$deletedMB = [math]::Round($deletedMB, 2)
Write-Output ""
Write-Output "=============================================="
Write-Output "       Cleanup Complete!"
Write-Output "       Total Freed: $deletedMB MB"
Write-Output "       Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Output "=============================================="
Write-Output ""

# Show new C drive space
$cDrive = Get-WmiObject Win32_LogicalDisk -Filter "DeviceID='C:'"
$freeGB = [math]::Round($cDrive.FreeSpace / 1GB, 2)
Write-Output "  C Drive Free Space Now: $freeGB GB"
Write-Output ""