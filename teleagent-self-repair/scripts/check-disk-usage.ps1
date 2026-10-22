#requires -version 5.1
# ============================================================
# TeleAgent 磁盘空间检测脚本 (Windows PowerShell 5.1+)
# ============================================================
# 功能：扫描磁盘空间 → 检测各目录体积 → 三级分类 → 输出 JSON
# 用法：.\check-disk-usage.ps1
# 输出：JSON 格式评估结果，供 Agent 解析判断
# ============================================================

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# 环境变量兜底（极端情况下可能缺失）
if (-not $env:USERPROFILE) { $env:USERPROFILE = $env:HOME }
if (-not $env:LOCALAPPDATA) { $env:LOCALAPPDATA = Join-Path $env:USERPROFILE "AppData\Local" }
if (-not $env:APPDATA) { $env:APPDATA = Join-Path $env:USERPROFILE "AppData\Roaming" }
if (-not $env:windir) { $env:windir = "C:\Windows" }
if (-not $env:SystemDrive) { $env:SystemDrive = "C:" }
if (-not $env:ProgramData) { $env:ProgramData = "C:\ProgramData" }

# ============================================================
# 工具函数
# ============================================================

function Get-DirSizeMB {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return 0.0 }
    try {
        $size = (Get-ChildItem -Path $Path -Recurse -File -ErrorAction SilentlyContinue |
            Measure-Object -Property Length -Sum -ErrorAction SilentlyContinue).Sum
        if ($null -eq $size) { return 0.0 }
        return [Math]::Round($size / 1MB, 1)
    } catch {
        return 0.0
    }
}

function Test-IsLocked {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return $false }
    try {
        $files = Get-ChildItem -Path $Path -File -ErrorAction SilentlyContinue | Select-Object -First 3
        foreach ($f in $files) {
            $fs = [System.IO.File]::Open($f.FullName, 'Open', 'Read', 'None')
            $fs.Close()
        }
        return $false
    } catch {
        return $true
    }
}

function Test-IsAdmin {
    $id = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object System.Security.Principal.WindowsPrincipal($id)
    return $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Test-ProcessRunning {
    param([string[]]$ProcessNames)
    foreach ($name in $ProcessNames) {
        $p = Get-Process -Name $name -ErrorAction SilentlyContinue
        if ($p) { return $true }
    }
    return $false
}

# ============================================================
# 磁盘信息
# ============================================================

$diskInfo = @()
$drives = Get-PSDrive -PSProvider FileSystem -ErrorAction SilentlyContinue
foreach ($d in $drives) {
    if ($null -ne $d.Used -and $null -ne $d.Free) {
        $totalGB = [Math]::Round(($d.Used + $d.Free) / 1GB, 1)
        $freeGB = [Math]::Round($d.Free / 1GB, 1)
        $usagePercent = if ($totalGB -gt 0) { [Math]::Round($d.Used / ($d.Used + $d.Free) * 100, 1) } else { 0 }
        $diskInfo += @{
            drive = "$($d.Name):"
            free_gb = $freeGB
            total_gb = $totalGB
            usage_percent = $usagePercent
        }
    }
}

# ============================================================
# 进程状态
# ============================================================

$runningProcesses = @{
    teleagent = Test-ProcessRunning -ProcessNames @("TeleAgent", "teleagent", "TeleClaw", "teleclaw")
    chrome = Test-ProcessRunning -ProcessNames @("chrome")
    edge = Test-ProcessRunning -ProcessNames @("msedge")
    firefox = Test-ProcessRunning -ProcessNames @("firefox")
    docker = Test-ProcessRunning -ProcessNames @("Docker Desktop", "com.docker.backend", "com.docker.service", "dockerd")
}

$hasAdmin = Test-IsAdmin

# ============================================================
# 定位 TeleAgent 数据目录
# ============================================================

$teleagentDataDir = $null
if ($env:TELEAGENT_DATA_DIR -and (Test-Path $env:TELEAGENT_DATA_DIR)) {
    $teleagentDataDir = $env:TELEAGENT_DATA_DIR
} else {
    # 兜底：读 owner 标记拼 users\<owner>\
    $ownerFile = Join-Path (Join-Path $env:USERPROFILE ".local\share\TeleAgent") "current-owner.json"
    if (Test-Path $ownerFile) {
        try {
            $owner = (Get-Content $ownerFile -Raw | ConvertFrom-Json).ownerDir
            if ($owner) {
                $d = Join-Path (Join-Path (Join-Path $env:USERPROFILE ".local\share\TeleAgent") "users") $owner
                if (Test-Path $d) { $teleagentDataDir = $d }
            }
        } catch {}
    }
    # 再兜底：探测活跃子目录
    if (-not $teleagentDataDir) {
        $usersRoot = Join-Path (Join-Path $env:USERPROFILE ".local\share\TeleAgent") "users"
        if (Test-Path $usersRoot) {
            $latest = Get-ChildItem $usersRoot -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1
            if ($latest) { $teleagentDataDir = $latest.FullName }
        }
    }
    # 最后回退根目录（旧版）
    if (-not $teleagentDataDir -and $env:USERPROFILE) {
        $stdPath = Join-Path $env:USERPROFILE ".local\share\TeleAgent"
        if (Test-Path $stdPath) { $teleagentDataDir = $stdPath }
    }
}

# --- 定位当前账号配置目录（环境变量优先 → owner标记 → 探测兜底）---
function Get-AccountConfigDir {
    if ($env:TELEAGENT_CONFIG_DIR -and (Test-Path $env:TELEAGENT_CONFIG_DIR)) {
        return $env:TELEAGENT_CONFIG_DIR
    }
    $ownerFile = Join-Path (Join-Path $env:USERPROFILE ".local\share\TeleAgent") "current-owner.json"
    if (Test-Path $ownerFile) {
        try {
            $owner = (Get-Content $ownerFile -Raw | ConvertFrom-Json).ownerDir
            if ($owner) {
                $cfg = Join-Path (Join-Path (Join-Path $env:USERPROFILE ".config\TeleAgent") "users") $owner
                if (Test-Path $cfg) { return $cfg }
            }
        } catch {}
    }
    $usersRoot = Join-Path (Join-Path $env:USERPROFILE ".config\TeleAgent") "users"
    if (Test-Path $usersRoot) {
        $latest = Get-ChildItem $usersRoot -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($latest) { return $latest.FullName }
    }
    return Join-Path $env:USERPROFILE ".config\TeleAgent"
}

$teleagentLocalDir = $null
if ($env:LOCALAPPDATA) {
    $laPath = Join-Path $env:LOCALAPPDATA "TeleAgent"
    if (Test-Path $laPath) { $teleagentLocalDir = $laPath }
}

# ============================================================
# 收集扫描项
# ============================================================

$safeToClean = @()
$cautionClean = @()
$lockedItems = @()

# --- 系统临时文件 ---
$tempPath = $env:TEMP
if (-not $tempPath) { $tempPath = Join-Path $env:LOCALAPPDATA "Temp" }
if (Test-Path $tempPath) {
    $sz = Get-DirSizeMB -Path $tempPath
    $locked = Test-IsLocked -Path $tempPath
    $item = @{
        name = "系统临时文件"
        path = $tempPath
        size_mb = $sz
        exists = $true
        is_locked = $locked
        needs_admin = $false
        note = if ($locked) { "部分文件被占用，需关闭程序后清理" } else { "可直接清理" }
    }
    $safeToClean += $item
    if ($locked) {
        $lockedItems += @{ name = $item.name; path = $item.path; size_mb = $sz; blocking_process = "unknown" }
    }
}

# --- 回收站（遍历所有盘符） ---
foreach ($d in $drives) {
    $recyclePath = "$($d.Name):\`$Recycle.Bin"
    if (Test-Path $recyclePath) {
        $sz = Get-DirSizeMB -Path $recyclePath
        $safeToClean += @{
            name = "回收站($($d.Name):)"
            path = $recyclePath
            size_mb = $sz
            exists = $true
            is_locked = $false
            needs_admin = $false
            note = "可直接清理"
        }
    }
}

# --- Windows 更新缓存 ---
$wuPath = Join-Path $env:windir "SoftwareDistribution\Download"
if (Test-Path $wuPath) {
    $sz = Get-DirSizeMB -Path $wuPath
    $safeToClean += @{
        name = "Windows更新缓存"
        path = $wuPath
        size_mb = $sz
        exists = $true
        is_locked = $false
        needs_admin = $true
        note = "可直接清理（建议以管理员身份运行）"
    }
}

# --- Windows.old ---
$oldPath = Join-Path $env:SystemDrive "Windows.old"
if (Test-Path $oldPath) {
    $sz = Get-DirSizeMB -Path $oldPath
    $creationTime = (Get-Item $oldPath -ErrorAction SilentlyContinue).CreationTime
    $daysOld = if ($creationTime) { [Math]::Floor((Get-Date - $creationTime).TotalDays) } else { 999 }
    $note = if ($daysOld -le 10) { "升级 ${daysOld} 天，删除后无法回退旧系统" } else { "可直接清理（已超过10天回退期限）" }
    $safeToClean += @{
        name = "Windows.old"
        path = $oldPath
        size_mb = $sz
        exists = $true
        is_locked = $false
        needs_admin = $true
        note = $note
    }
}

# --- Windows 错误报告 ---
$werPath = Join-Path $env:ProgramData "Microsoft\Windows\WER"
if (Test-Path $werPath) {
    $sz = Get-DirSizeMB -Path $werPath
    $safeToClean += @{
        name = "Windows错误报告"
        path = $werPath
        size_mb = $sz
        exists = $true
        is_locked = $false
        needs_admin = $false
        note = "可直接清理"
    }
}

# --- 缩略图缓存 ---
$thumbBase = Join-Path $env:LOCALAPPDATA "Microsoft\Windows\Explorer"
if (Test-Path $thumbBase) {
    $thumbFiles = Get-ChildItem -Path $thumbBase -Filter "thumbcache_*.db" -File -ErrorAction SilentlyContinue
    $thumbSize = 0.0
    if ($thumbFiles) {
        $thumbSize = [Math]::Round(($thumbFiles | Measure-Object -Property Length -Sum).Sum / 1MB, 1)
    }
    if ($thumbSize -gt 0) {
        $safeToClean += @{
            name = "缩略图缓存"
            path = $thumbBase
            size_mb = $thumbSize
            exists = $true
            is_locked = $false
            needs_admin = $false
            note = "可直接清理，删除后自动重建"
        }
    }
}

# --- 浏览器缓存 ---
$browserConfigs = @(
    @{ name = "Chrome缓存"; process = "chrome"; isRunning = $runningProcesses.chrome;
       paths = @("$env:LOCALAPPDATA\Google\Chrome\User Data\Default\Cache",
                 "$env:LOCALAPPDATA\Google\Chrome\User Data\*\Cache") }
    @{ name = "Edge缓存"; process = "msedge"; isRunning = $runningProcesses.edge;
       paths = @("$env:LOCALAPPDATA\Microsoft\Edge\User Data\Default\Cache",
                 "$env:LOCALAPPDATA\Microsoft\Edge\User Data\*\Cache") }
    @{ name = "Firefox缓存"; process = "firefox"; isRunning = $runningProcesses.firefox;
       paths = @("$env:LOCALAPPDATA\Mozilla\Firefox\Profiles\*\cache2") }
)

foreach ($bc in $browserConfigs) {
    $foundPaths = @()
    $seenPaths = @{}
    foreach ($p in $bc.paths) {
        $resolved = Get-Item -Path $p -ErrorAction SilentlyContinue
        if ($resolved) {
            $resolved | ForEach-Object {
                if (-not $seenPaths.ContainsKey($_.FullName.ToLower())) {
                    $seenPaths[$_.FullName.ToLower()] = $true
                    $foundPaths += $_.FullName
                }
            }
        }
    }
    if ($foundPaths.Count -gt 0) {
        $totalSz = 0.0
        foreach ($fp in $foundPaths) { $totalSz += Get-DirSizeMB -Path $fp }
        $totalSz = [Math]::Round($totalSz, 1)
        $isLocked = $bc.isRunning
        $item = @{
            name = $bc.name
            path = ($foundPaths -join "; ")
            size_mb = $totalSz
            exists = $true
            is_locked = $isLocked
            needs_admin = $false
            note = if ($isLocked) { "需关闭 $($bc.process) 后清理" } else { "可直接清理" }
        }
        $safeToClean += $item
        if ($isLocked) {
            $lockedItems += @{ name = $bc.name; path = ($foundPaths -join "; "); size_mb = $totalSz; blocking_process = $bc.process }
        }
    }
}

# --- npm 缓存 ---
$npmPaths = @()
if ($env:APPDATA) { $npmPaths += Join-Path $env:APPDATA "npm-cache" }
if ($env:LOCALAPPDATA) { $npmPaths += Join-Path $env:LOCALAPPDATA "npm-cache" }
$npmSize = 0.0
$npmFound = $false
$npmExistingPaths = @()
foreach ($p in $npmPaths) {
    if (Test-Path $p) {
        $npmSize += Get-DirSizeMB -Path $p
        $npmFound = $true
        $npmExistingPaths += $p
    }
}
if ($npmFound) {
    $safeToClean += @{
        name = "npm缓存"
        path = ($npmExistingPaths -join "; ")
        size_mb = [Math]::Round($npmSize, 1)
        exists = $true
        is_locked = $false
        needs_admin = $false
        note = "可直接清理，下次安装时重新下载"
    }
}

# --- pip 缓存 ---
$pipPath = Join-Path $env:LOCALAPPDATA "pip\Cache"
if (Test-Path $pipPath) {
    $sz = Get-DirSizeMB -Path $pipPath
    $safeToClean += @{
        name = "pip缓存"
        path = $pipPath
        size_mb = $sz
        exists = $true
        is_locked = $false
        needs_admin = $false
        note = "可直接清理，下次安装时重新下载"
    }
}

# --- Docker 未使用资源 ---
if ($runningProcesses.docker) {
    try {
        $dockerDf = docker system df --format "{{.Type}}|{{.Size}}|{{.Reclaimable}}" 2>$null
        if ($dockerDf) {
            $dockerReclaimable = 0.0
            foreach ($line in $dockerDf) {
                $parts = $line -split '\|'
                if ($parts.Count -ge 3 -and $parts[2] -match '([\d.]+)\s*([A-Za-z]+)') {
                    $val = [double]$Matches[1]
                    $unit = $Matches[2].ToUpper()
                    $mb = switch ($unit) {
                        "GB" { $val * 1024 }
                        "MB" { $val }
                        "KB" { $val / 1024 }
                        "B" { $val / (1024 * 1024) }
                        default { 0 }
                    }
                    $dockerReclaimable += $mb
                }
            }
            if ($dockerReclaimable -gt 0) {
                $safeToClean += @{
                    name = "Docker未使用资源"
                    path = "docker system prune"
                    size_mb = [Math]::Round($dockerReclaimable, 1)
                    exists = $true
                    is_locked = $false
                    needs_admin = $false
                    note = "可通过 docker system prune 清理未使用的镜像/容器/卷"
                }
            }
        }
    } catch {}
}

# --- TeleAgent 缓存目录候选位置 ---
# TeleAgent 缓存可能在 %LOCALAPPDATA%\TeleAgent 或 数据目录下
$taCacheSearchDirs = @()
if ($teleagentLocalDir) { $taCacheSearchDirs += $teleagentLocalDir }
if ($teleagentDataDir) { $taCacheSearchDirs += $teleagentDataDir }

# 去重
$taCacheSearchDirs = $taCacheSearchDirs | Sort-Object -Unique

foreach ($taDir in $taCacheSearchDirs) {
    # --- TeleAgent Cache ---
    $cachePath = Join-Path $taDir "Cache"
    if (Test-Path $cachePath) {
        $sz = Get-DirSizeMB -Path $cachePath
        $isLocked = $runningProcesses.teleagent
        $item = @{
            name = "TeleAgent缓存"
            path = $cachePath
            size_mb = $sz
            exists = $true
            is_locked = $isLocked
            needs_admin = $false
            note = if ($isLocked) { "需关闭TeleAgent后清理" } else { "可直接清理，重启后自动重建" }
        }
        $safeToClean += $item
        if ($isLocked) {
            $lockedItems += @{ name = $item.name; path = $cachePath; size_mb = $sz; blocking_process = "teleagent" }
        }
    }

    # --- TeleAgent GPUCache ---
    $gpuPath = Join-Path $taDir "GPUCache"
    if (Test-Path $gpuPath) {
        $sz = Get-DirSizeMB -Path $gpuPath
        $isLocked = $runningProcesses.teleagent
        $item = @{
            name = "TeleAgent GPUCache"
            path = $gpuPath
            size_mb = $sz
            exists = $true
            is_locked = $isLocked
            needs_admin = $false
            note = if ($isLocked) { "需关闭TeleAgent后清理" } else { "可直接清理，重启后自动重建" }
        }
        $safeToClean += $item
        if ($isLocked) {
            $lockedItems += @{ name = $item.name; path = $gpuPath; size_mb = $sz; blocking_process = "teleagent" }
        }
    }

    # --- TeleAgent Code Cache ---
    $codeCachePath = Join-Path $taDir "Code Cache"
    if (Test-Path $codeCachePath) {
        $sz = Get-DirSizeMB -Path $codeCachePath
        $isLocked = $runningProcesses.teleagent
        $item = @{
            name = "TeleAgent Code Cache"
            path = $codeCachePath
            size_mb = $sz
            exists = $true
            is_locked = $isLocked
            needs_admin = $false
            note = if ($isLocked) { "需关闭TeleAgent后清理" } else { "可直接清理，重启后自动重建" }
        }
        $safeToClean += $item
        if ($isLocked) {
            $lockedItems += @{ name = $item.name; path = $codeCachePath; size_mb = $sz; blocking_process = "teleagent" }
        }
    }

    # --- TeleAgent Crashpad ---
    $crashPath = Join-Path $taDir "Crashpad\reports"
    if (Test-Path $crashPath) {
        $sz = Get-DirSizeMB -Path $crashPath
        $safeToClean += @{
            name = "TeleAgent Crashpad报告"
            path = $crashPath
            size_mb = $sz
            exists = $true
            is_locked = $false
            needs_admin = $false
            note = "可直接清理"
        }
    }
}

# --- TeleAgent 旧版本残留 ---
# 在 %LOCALAPPDATA% 和 数据目录的父目录中搜索 TeleAgent* 目录
$taSearchBases = @()
if ($teleagentLocalDir) { $taSearchBases += (Split-Path $teleagentLocalDir -Parent) }
if ($teleagentDataDir) { $taSearchBases += (Split-Path $teleagentDataDir -Parent) }
$taSearchBases = $taSearchBases | Sort-Object -Unique

$taCurrentDirs = @()
if ($teleagentLocalDir) { $taCurrentDirs += $teleagentLocalDir.ToLower() }
if ($teleagentDataDir) { $taCurrentDirs += $teleagentDataDir.ToLower() }

foreach ($base in $taSearchBases) {
    $taDirs = Get-ChildItem -Path $base -Directory -Filter "TeleAgent*" -ErrorAction SilentlyContinue
    foreach ($d in $taDirs) {
        if ($d.FullName.ToLower() -notin $taCurrentDirs) {
            $sz = Get-DirSizeMB -Path $d.FullName
            if ($sz -gt 1) {
                $safeToClean += @{
                    name = "TeleAgent旧版本残留($($d.Name))"
                    path = $d.FullName
                    size_mb = $sz
                    exists = $true
                    is_locked = $false
                    needs_admin = $false
                    note = "可直接清理，当前版本不再使用"
                }
            }
        }
    }
}

# --- 谨慎清理项 ---

# 系统日志 (Windows 事件日志不直接清理，跳过; 改为检查日志目录)
# TeleAgent 日志（同时检查 %LOCALAPPDATA%\TeleAgent\logs 旧版 和 数据目录\log 单数账号日志）
$taLogDirs = @()
if ($teleagentLocalDir) {
    $taLogCandidate = Join-Path $teleagentLocalDir "logs"
    if (Test-Path $taLogCandidate) { $taLogDirs += $taLogCandidate }
}
if ($teleagentDataDir) {
    $taLogCandidate = Join-Path $teleagentDataDir "log"
    if (Test-Path $taLogCandidate) { $taLogDirs += $taLogCandidate }
}
# 去重
$taLogDirs = $taLogDirs | Sort-Object -Unique
foreach ($taLogDir in $taLogDirs) {
    $sz = Get-DirSizeMB -Path $taLogDir
    if ($sz -gt 0) {
        $cautionClean += @{
            name = "TeleAgent日志"
            path = $taLogDir
            size_mb = $sz
            note = "建议保留最近7天，清理更旧的"
        }
    }
}

# 下载目录大文件
$downloadPath = $null
if ($env:USERPROFILE) {
    $dlCandidate = Join-Path $env:USERPROFILE "Downloads"
    if (Test-Path $dlCandidate) { $downloadPath = $dlCandidate }
}
if ($downloadPath) {
    $largeFiles = Get-ChildItem -Path $downloadPath -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Length -gt 100MB }
    if ($largeFiles) {
        $largeSize = [Math]::Round(($largeFiles | Measure-Object -Property Length -Sum).Sum / 1MB, 1)
        $cautionClean += @{
            name = "下载目录大文件(>100MB)"
            path = $downloadPath
            size_mb = $largeSize
            note = "需您确认哪些可删，共 $($largeFiles.Count) 个文件"
        }
    }
}

# --- 不可清理项 (仅统计体积，不提供路径供清理) ---
$notCleanable = @()

if ($teleagentDataDir) {
    # 统计数据库文件体积
    $dbPaths = @(
        (Join-Path $teleagentDataDir "scheduler\scheduler.db"),
        (Join-Path $teleagentDataDir "im-service\im-service.db")
    )
    $dbSize = 0.0
    $dbFound = @()
    foreach ($db in $dbPaths) {
        if (Test-Path $db) {
            $dbSize += [Math]::Round((Get-Item $db).Length / 1MB, 1)
            $dbFound += $db
        }
    }
    # 统计配置文件（当前账号配置根，兼容旧版根目录与数据目录）
    $accountConfigDir = Get-AccountConfigDir
    $configPaths = @()
    if ($accountConfigDir) { $configPaths += (Join-Path $accountConfigDir "TeleAgent.jsonc") }
    # 兼容旧版本：根目录和数据目录下可能存在配置文件
    $configPaths += (Join-Path $env:USERPROFILE ".config\TeleAgent\TeleAgent.jsonc")
    $configPaths += (Join-Path $teleagentDataDir "TeleAgent.jsonc")
    # 去重
    $configPaths = @($configPaths | Sort-Object -Unique)
    $cfgFound = @()
    foreach ($cfg in $configPaths) {
        if (Test-Path $cfg) { $cfgFound += $cfg }
    }
    if ($dbFound.Count -gt 0 -or $cfgFound.Count -gt 0) {
        $allPaths = $dbFound + $cfgFound
        $notCleanable += @{
            name = "TeleAgent数据库与配置"
            paths = $allPaths
            size_mb = $dbSize
            note = "核心数据，不可删除"
        }
    }

    # memory 目录
    $memPath = Join-Path $teleagentDataDir "memory"
    if (Test-Path $memPath) {
        $memSz = Get-DirSizeMB -Path $memPath
        $notCleanable += @{
            name = "TeleAgent记忆目录"
            paths = @($memPath)
            size_mb = $memSz
            note = "长期记忆数据，不可删除"
        }
    }
}

# ============================================================
# 汇总
# ============================================================

$safeTotal = 0.0
foreach ($s in $safeToClean) { $safeTotal += $s.size_mb }
$cautionTotal = 0.0
foreach ($c in $cautionClean) { $cautionTotal += $c.size_mb }

# 清理建议
$cleanupSuggestion = "no_need"
if ($safeTotal -ge 100) {
    $cleanupSuggestion = "safe_only"
}
if ($safeTotal -ge 100 -and $cautionTotal -ge 100) {
    $cleanupSuggestion = "all"
}

# summary
$summaryParts = @()
if ($safeTotal -ge 100) {
    $summaryParts += "可安全清理约 $([Math]::Round($safeTotal / 1024, 1)) GB"
} else {
    $summaryParts += "可安全清理空间有限（$([Math]::Round($safeTotal, 1)) MB）"
}
if ($lockedItems.Count -gt 0) {
    $lockedTotal = 0.0
    foreach ($l in $lockedItems) { $lockedTotal += $l.size_mb }
    $summaryParts += "$($lockedItems.Count) 项被占用（约 $([Math]::Round($lockedTotal, 1)) MB）需关闭程序后清理"
}

$result = @{
    disk_info = $diskInfo
    running_processes = $runningProcesses
    has_admin = $hasAdmin
    categories = @{
        safe_to_clean = $safeToClean
        caution_clean = $cautionClean
        not_cleanable = $notCleanable
    }
    safe_cleanable_total_mb = [Math]::Round($safeTotal, 1)
    caution_cleanable_total_mb = [Math]::Round($cautionTotal, 1)
    locked_items_need_script = $lockedItems
    cleanup_suggestion = $cleanupSuggestion
    summary = ($summaryParts -join "；")
}

$result | ConvertTo-Json -Depth 6
