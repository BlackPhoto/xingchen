#requires -version 5.1
# ============================================================
# TeleAgent 正在运行的软件与显存占用检测脚本 (Windows PowerShell 5.1+)
# ============================================================
# 功能：枚举进程 → 统计内存/CPU → 检测 GPU 显存 → 输出 JSON
# 用法：.\check-running-software.ps1
# 输出：JSON 格式检测结果，供 Agent 解析展示
# ============================================================

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# 环境变量兜底
if (-not $env:USERPROFILE) { $env:USERPROFILE = $env:HOME }
if (-not $env:LOCALAPPDATA) { $env:LOCALAPPDATA = Join-Path $env:USERPROFILE "AppData\Local" }

# ============================================================
# 配置：排除的系统核心进程
# ============================================================

$ExcludedProcesses = @(
    'System', 'Registry', 'smss', 'csrss', 'wininit', 'winlogon',
    'services', 'lsass', 'svchost', 'dwm', 'conhost',
    'RuntimeBroker', 'SearchIndexer', 'sihost', 'taskhostw',
    'fontdrvhost', 'ctfmon', 'dllhost', 'WerFault', 'WUDFHost',
    'spoolsv', 'audiodg', 'WmiPrvSE', 'vds', 'TrustedInstaller',
    'MsMpEng', 'MpCmdRun', 'NisSrv', 'SecurityHealthService',
    'SearchApp', 'ShellExperienceHost', 'StartMenuExperienceHost',
    'SettingSyncHost', 'BackgroundTaskHost', 'WinStore.App',
    'ApplicationFrameHost', 'LogonUI', 'LockApp', 'SecureSystem',
    'SystemSettings', 'GameBar', 'GameBarFT', 'TextInputHost',
    'VideoUI', 'Microsoft.VisualBasic'
)

# ============================================================
# 工具函数
# ============================================================

function Get-SystemMemory {
    try {
        $os = Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue
        if ($os) {
            $totalGB = [Math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
            $freeGB = [Math]::Round($os.FreePhysicalMemory / 1MB, 1)
            $usedGB = [Math]::Round(($os.TotalVisibleMemorySize - $os.FreePhysicalMemory) / 1MB, 1)
            $usagePercent = if ($os.TotalVisibleMemorySize -gt 0) {
                [Math]::Round(($os.TotalVisibleMemorySize - $os.FreePhysicalMemory) / $os.TotalVisibleMemorySize * 100, 1)
            } else { 0 }
            return @{
                total_gb     = $totalGB
                available_gb = $freeGB
                used_gb      = $usedGB
                usage_percent = $usagePercent
            }
        }
    } catch {}

    # 兜底：用 WMI
    try {
        $cs = Get-CimInstance Win32_ComputerSystem -ErrorAction SilentlyContinue
        $os = Get-CimInstance Win32_OperatingSystem -ErrorAction SilentlyContinue
        if ($cs -and $os) {
            $totalGB = [Math]::Round($cs.TotalPhysicalMemory / 1GB, 1)
            $freeGB = [Math]::Round($os.FreePhysicalMemory / 1KB / 1024, 1)
            $usedGB = [Math]::Round($totalGB - $freeGB, 1)
            $usagePercent = if ($totalGB -gt 0) { [Math]::Round(($totalGB - $freeGB) / $totalGB * 100, 1) } else { 0 }
            return @{
                total_gb      = $totalGB
                available_gb  = $freeGB
                used_gb       = $usedGB
                usage_percent = $usagePercent
            }
        }
    } catch {}

    return @{
        total_gb      = 0
        available_gb  = 0
        used_gb       = 0
        usage_percent = 0
    }
}

# ============================================================
# 枚举正在运行的软件
# ============================================================

$runningSoftware = @()
$allProcesses = @()

try {
    $allProcesses = Get-Process -ErrorAction SilentlyContinue
} catch {
    $allProcesses = @()
}

# 筛选：有窗口标题或有可执行路径，且不在排除列表中
$filteredProcesses = $allProcesses | Where-Object {
    $_.ProcessName -and
    $_.ProcessName -notin $ExcludedProcesses -and
    ($_.MainWindowTitle -ne "" -or $_.Path)
}

# 按进程名分组
$grouped = $filteredProcesses | Group-Object ProcessName

foreach ($group in $grouped) {
    $procName = $group.Name
    $instances = $group.Group

    # 取主进程（优先选有窗口标题的）
    $mainProc = $instances | Where-Object { $_.MainWindowTitle -ne "" } | Select-Object -First 1
    if (-not $mainProc) {
        $mainProc = $instances | Select-Object -First 1
    }

    # 内存合计
    $memBytes = ($instances | Measure-Object WorkingSet64 -Sum -ErrorAction SilentlyContinue).Sum
    if ($null -eq $memBytes) { $memBytes = 0 }
    $memMB = [Math]::Round($memBytes / 1MB, 1)

    # CPU 估算（PowerShell 5.1 中 CPU 属性为累计 CPU 时间秒数）
    $cpuPercent = $null
    try {
        $totalCpu = ($instances | Measure-Object CPU -Sum -ErrorAction SilentlyContinue).Sum
        if ($null -ne $totalCpu -and $totalCpu -gt 0) {
            # 近似值：用累计 CPU 时间 / 进程运行时间，取百分比
            # 这里直接输出累计 CPU 秒数作为参考值
            $cpuPercent = [Math]::Round($totalCpu, 1)
        }
    } catch {}

    $entry = @{
        name           = $procName
        pid            = $mainProc.Id
        instance_count = $instances.Count
        memory_mb      = $memMB
        cpu_seconds    = $cpuPercent
        path           = if ($mainProc.Path) { $mainProc.Path } else { "" }
    }

    $runningSoftware += $entry
}

# 按内存占用从高到低排序
$runningSoftware = $runningSoftware | Sort-Object { [double]$_.memory_mb } -Descending

# 合计内存
$totalMemoryMB = 0.0
foreach ($s in $runningSoftware) { $totalMemoryMB += $s.memory_mb }
$totalMemoryMB = [Math]::Round($totalMemoryMB, 1)

# ============================================================
# GPU 显存检测
# ============================================================

$gpuInfo = @()
$gpuProcesses = @()
$gpuNotes = @()

# --- NVIDIA (nvidia-smi) ---
$nvidiaSmi = $null
try {
    $nvidiaSmi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
} catch {}

if ($nvidiaSmi) {
    try {
        # GPU 设备信息
        $gpuQuery = & nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader,nounits 2>$null
        if ($gpuQuery) {
            foreach ($line in $gpuQuery) {
                $parts = $line -split ','
                if ($parts.Count -ge 3) {
                    $gpuName = $parts[0].Trim()
                    $usedMB = [Math]::Round([double]$parts[1].Trim(), 1)
                    $totalMB = [Math]::Round([double]$parts[2].Trim(), 1)
                    $usagePct = if ($totalMB -gt 0) { [Math]::Round($usedMB / $totalMB * 100, 1) } else { 0 }
                    $gpuInfo += @{
                        name          = $gpuName
                        vendor        = "nvidia"
                        used_mb       = $usedMB
                        total_mb      = $totalMB
                        usage_percent = $usagePct
                    }
                }
            }
        }

        # GPU 逐进程显存
        $procQuery = & nvidia-smi --query-compute-apps=pid,name,used_memory --format=csv,noheader,nounits 2>$null
        if ($procQuery) {
            foreach ($line in $procQuery) {
                $parts = $line -split ','
                if ($parts.Count -ge 3) {
                    $procPid = $parts[0].Trim()
                    $procName = $parts[1].Trim()
                    $gpuMem = [Math]::Round([double]$parts[2].Trim(), 1)
                    $gpuProcesses += @{
                        name          = $procName
                        pid           = [int]$procPid
                        gpu_memory_mb = $gpuMem
                    }
                }
            }
        }
    } catch {
        $gpuNotes += "nvidia-smi 执行失败：$($_.Exception.Message)"
    }
} else {
    # nvidia-smi 不可用，尝试检测 AMD / Intel
    $hasNvidia = $false
    try {
        $nvidiaGpu = Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like "*NVIDIA*" }
        if ($nvidiaGpu) {
            $hasNvidia = $true
            # 同时获取 AdapterRAM 作为总显存参考
            $nvidiaTotalMB = 0
            if ($nvidiaGpu.AdapterRAM -and $nvidiaGpu.AdapterRAM -gt 0) {
                $nvidiaTotalMB = [Math]::Round($nvidiaGpu.AdapterRAM / 1MB, 0)
            }
            $gpuInfo += @{
                name          = "$($nvidiaGpu.Name)"
                vendor        = "nvidia"
                used_mb       = 0
                total_mb      = $nvidiaTotalMB
                usage_percent = 0
            }
            $gpuNotes += "检测到 NVIDIA GPU（$($nvidiaGpu.Name)），但 nvidia-smi 不可用，请确认 NVIDIA 驱动已正确安装"
        }
    } catch {}

    if (-not $hasNvidia) {
        # 检查 AMD / Intel
        try {
            $gpus = Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue
            if ($gpus) {
                foreach ($g in $gpus) {
                    $gpuName = $g.Name
                    if ($gpuName -like "*AMD*" -or $gpuName -like "*Radeon*" -or $gpuName -like "*ATI*") {
                        $gpuInfo += @{
                            name          = $gpuName
                            vendor        = "amd"
                            used_mb       = 0
                            total_mb      = 0
                            usage_percent = 0
                        }
                        $gpuNotes += "AMD GPU（$gpuName）暂不支持逐进程显存查询（Windows 平台无标准 CLI 工具）"
                    } elseif ($gpuName -like "*Intel*") {
                        $gpuInfo += @{
                            name          = $gpuName
                            vendor        = "intel"
                            used_mb       = 0
                            total_mb      = 0
                            usage_percent = 0
                        }
                        $gpuNotes += "Intel 集显（$gpuName）暂不支持逐进程显存查询"
                    }
                }
            }
        } catch {}
    }
}

# 如果没有检测到任何 GPU
if ($gpuInfo.Count -eq 0 -and $gpuNotes.Count -eq 0) {
    # 通过 WMI 再次尝试获取 GPU 信息
    try {
        $gpus = Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue
        if ($gpus) {
            foreach ($g in $gpus) {
                $gpuName = $g.Name
                $vendor = "unknown"
                if ($gpuName -like "*NVIDIA*") { $vendor = "nvidia" }
                elseif ($gpuName -like "*AMD*" -or $gpuName -like "*Radeon*") { $vendor = "amd" }
                elseif ($gpuName -like "*Intel*") { $vendor = "intel" }

                # 尝试从 AdapterRAM 获取总显存
                $totalMB = 0
                if ($g.AdapterRAM -and $g.AdapterRAM -gt 0) {
                    $totalMB = [Math]::Round($g.AdapterRAM / 1MB, 0)
                }

                $gpuInfo += @{
                    name          = $gpuName
                    vendor        = $vendor
                    used_mb       = 0
                    total_mb      = $totalMB
                    usage_percent = 0
                }
            }
        }
    } catch {}

    if ($gpuInfo.Count -eq 0) {
        $gpuNotes += "未检测到 GPU 设备"
    }
}

# ============================================================
# 系统内存信息
# ============================================================

$systemMemory = Get-SystemMemory

# ============================================================
# 输出 JSON
# ============================================================

$result = @{
    running_software  = $runningSoftware
    total_memory_mb   = $totalMemoryMB
    system_memory     = $systemMemory
    gpu               = $gpuInfo
    gpu_processes     = $gpuProcesses
    gpu_detection_notes = $gpuNotes
}

$result | ConvertTo-Json -Depth 5
