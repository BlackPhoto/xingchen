#requires -version 5.1
# ============================================================
# TeleAgent 日志异常检测脚本 (Windows PowerShell 5.1+)
# ============================================================
# 功能：定位日志 → 读取末尾 → 扫描异常关键词 → 提取上下文 → 输出 JSON
# 用法：.\check-log-anomalies.ps1
# 输出：JSON 格式诊断结果，供 Agent 解析判断
# ============================================================

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# --- 配置 ---
$TailLines = 2000   # 读取日志末尾行数上限

# 异常关键词列表（不区分大小写匹配）
$AnomalyPatterns = @(
    "fatal",
    "crash",
    "panic",
    "FATAL ERROR",
    "uncaughtException",
    "Segmentation fault",
    "SIGSEGV",
    "SIGABRT",
    "abort",
    "EBUSY",
    "EPERM",
    "EADDRINUSE",
    "OOM",
    "out of memory",
    "heap out of memory",
    "Allocation failed",
    "MARK_BIT",
    "process killed",
    "EBUSY resource busy"
)

# 启动成功标记（从日志末尾向前搜索最近的标记）
$StartSuccessMarkers = @(
    "app ready",
    "Server started",
    "listening on",
    "ready in",
    "started successfully"
)

# 启动尝试标记
$StartAttemptMarkers = @(
    "starting",
    "launching",
    "booting",
    "initializing"
)

# 退出标记
$ExitMarkers = @(
    "exiting",
    "shutting down",
    "process exit",
    "fatal error"
)

# --- 定位日志文件 ---
function Find-LogFile {
    $candidates = @()

    # 优先级1：TeleAgent 注入的日志环境变量（精确指向当前账号 log 目录）
    if ($env:SUPER_AGENT_LOG_DIR) {
        $candidates += $env:SUPER_AGENT_LOG_DIR
    }

    # 优先级2：当前账号数据目录下的 log\（单数）
    $accountData = $null
    if ($env:TELEAGENT_DATA_DIR -and (Test-Path $env:TELEAGENT_DATA_DIR)) {
        $accountData = $env:TELEAGENT_DATA_DIR
    } else {
        $ownerFile = Join-Path (Join-Path $env:USERPROFILE ".local\share\TeleAgent") "current-owner.json"
        if (Test-Path $ownerFile) {
            try {
                $owner = (Get-Content $ownerFile -Raw | ConvertFrom-Json).ownerDir
                if ($owner) {
                    $d = Join-Path (Join-Path (Join-Path $env:USERPROFILE ".local\share\TeleAgent") "users") $owner
                    if (Test-Path $d) { $accountData = $d }
                }
            } catch {}
        }
    }
    if ($accountData) {
        $candidates += Join-Path $accountData "log"
        $candidates += $accountData
    }

    # 兜底候选路径（旧版，兼容）
    if ($env:LOCALAPPDATA) {
        $candidates += Join-Path $env:LOCALAPPDATA "TeleAgent"
    }
    if ($env:USERPROFILE) {
        $candidates += Join-Path $env:USERPROFILE ".local\share\TeleAgent"
    }
    if ($env:APPDATA) {
        $candidates += Join-Path $env:APPDATA "TeleAgent"
    }

    foreach ($dir in $candidates) {
        if (Test-Path $dir) {
            # 优先在根目录找 .log 文件
            $logFiles = Get-ChildItem -Path $dir -Filter "*.log" -File -ErrorAction SilentlyContinue |
                Sort-Object LastWriteTime -Descending |
                Select-Object -First 1
            if ($logFiles) {
                return $logFiles.FullName
            }

            # 检查 runtime 子目录
            $runtimeDir = Join-Path $dir "runtime"
            if (Test-Path $runtimeDir) {
                $runtimeLogs = Get-ChildItem -Path $runtimeDir -Filter "*.log" -File -ErrorAction SilentlyContinue |
                    Sort-Object LastWriteTime -Descending |
                    Select-Object -First 1
                if ($runtimeLogs) {
                    return $runtimeLogs.FullName
                }
            }

            # 递归搜索一层（兼容 logs/ 子目录）
            $subLogs = Get-ChildItem -Path $dir -Recurse -Depth 1 -Filter "*.log" -File -ErrorAction SilentlyContinue |
                Sort-Object LastWriteTime -Descending |
                Select-Object -First 1
            if ($subLogs) {
                return $subLogs.FullName
            }
        }
    }

    return $null
}

# --- 提取异常上下文 ---
function Get-AnomalyContext {
    param(
        [string[]]$Lines,
        [int]$MatchIndex,
        [int]$ContextRadius = 3
    )

    $start = [Math]::Max(0, $MatchIndex - $ContextRadius)
    $end = [Math]::Min($Lines.Length - 1, $MatchIndex + $ContextRadius)

    $contextLines = @()
    for ($i = $start; $i -le $end; $i++) {
        $contextLines += "[$($i + 1)] $($Lines[$i])"
    }
    return ($contextLines -join "`n")
}

# --- 从日志行提取时间戳 ---
function Get-TimestampFromLine {
    param([string]$Line)

    # 匹配 ISO 8601 时间戳: 2026-08-01T10:23:45.123Z
    if ($Line -match '(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[\.\d]*Z?)') {
        return $Matches[1]
    }
    # 匹配常见日志时间戳: [2026-08-01 10:23:45.123] 或 2026-08-01 10:23:45
    if ($Line -match '(\d{4}-\d{2}-\d{2}[\s T]\d{2}:\d{2}:\d{2}(?:\.\d+)?)') {
        return $Matches[1]
    }
    return ""
}

# --- 判断最近一次启动是否成功 ---
function Get-LastStartStatus {
    param([string[]]$Lines)

    # 从末尾向前搜索，找到最近的启动尝试标记
    $lastAttemptIndex = -1
    for ($i = $Lines.Length - 1; $i -ge 0; $i--) {
        $lower = $Lines[$i].ToLower()
        foreach ($marker in $StartAttemptMarkers) {
            if ($lower -like "*$marker*") {
                $lastAttemptIndex = $i
                break
            }
        }
        if ($lastAttemptIndex -ge 0) { break }
    }

    if ($lastAttemptIndex -lt 0) {
        return "unknown"
    }

    # 从启动尝试位置向后搜索，看是否出现成功标记
    for ($i = $lastAttemptIndex; $i -lt $Lines.Length; $i++) {
        $lower = $Lines[$i].ToLower()
        foreach ($marker in $StartSuccessMarkers) {
            if ($lower -like "*$marker*") {
                return "success"
            }
        }
    }

    # 从启动尝试位置向后搜索，看是否出现退出标记
    for ($i = $lastAttemptIndex; $i -lt $Lines.Length; $i++) {
        $lower = $Lines[$i].ToLower()
        foreach ($marker in $ExitMarkers) {
            if ($lower -like "*$marker*") {
                return "failed"
            }
        }
    }

    # 仅有宽泛启动词（initializing/launching 等）而无成功/退出标记：
    # 日志窗口可能正常停在运行中、或该词来自正文（如 “initializing db”）而非真实进程启动，
    # 不确证为启动失败，返回 unknown，避免误报。真正的启动失败通常伴随 fatal/crash，由 anomalies 统计兜底。
    return "unknown"
}

# --- 主流程 ---

$logFile = Find-LogFile

if (-not $logFile) {
    $result = @{
        status = "no_log"
        log_file = ""
        last_start_status = "unknown"
        anomalies = @()
        summary = "找不到 TeleAgent 日志文件，请检查 TeleAgent 是否曾正常安装"
    }
    $result | ConvertTo-Json -Depth 5
    exit 0
}

# 读取日志末尾（指定 UTF-8 编码，避免中文/emoji 乱码）
# 使用 -Tail 参数仅读取末尾指定行数，避免大日志文件内存溢出
$lines = Get-Content -Path $logFile -Encoding UTF8 -Tail $TailLines -ErrorAction SilentlyContinue
if (-not $lines -or $lines.Count -eq 0) {
    $result = @{
        status = "empty_log"
        log_file = $logFile
        last_start_status = "unknown"
        anomalies = @()
        summary = "日志文件为空，无法诊断"
    }
    $result | ConvertTo-Json -Depth 5
    exit 0
}

# 由于使用 -Tail 读取，$lines 即为末尾内容
$totalLines = $lines.Count

# 判断最近一次启动状态
$lastStart = Get-LastStartStatus -Lines $lines

# 扫描异常关键词
$anomalies = @()
for ($i = 0; $i -lt $lines.Length; $i++) {
    $lineLower = $lines[$i].ToLower()
    foreach ($pattern in $AnomalyPatterns) {
        $patternLower = $pattern.ToLower()
        if ($lineLower -like "*$patternLower*") {
            # 避免重复添加同一行
            $alreadyAdded = $false
            foreach ($a in $anomalies) {
                if ($a.line_number -eq ($i + 1) -and ($totalLines - $lines.Length + $i + 1) -eq $a.absolute_line) {
                    $alreadyAdded = $true
                    break
                }
            }
            if (-not $alreadyAdded) {
                $ts = Get-TimestampFromLine -Line $lines[$i]
                $context = Get-AnomalyContext -Lines $lines -MatchIndex $i
                $anomalies += @{
                    type = $pattern
                    timestamp = $ts
                    message = $lines[$i].Trim()
                    context = $context
                    line_number = $i + 1
                    absolute_line = $totalLines - $lines.Length + $i + 1
                }
            }
            break  # 同一行只匹配一个关键词
        }
    }
}

# 生成 summary
if ($anomalies.Count -eq 0 -and $lastStart -eq "success") {
    $status = "normal"
    $summary = "未检测到异常，最近一次启动成功"
} elseif ($anomalies.Count -eq 0 -and $lastStart -eq "failed") {
    $status = "anomaly_found"
    $summary = "最近一次启动失败（日志中有启动尝试但未出现成功标记）"
} elseif ($anomalies.Count -eq 0 -and $lastStart -eq "unknown") {
    $status = "normal"
    $summary = "未检测到异常"
} else {
    $status = "anomaly_found"
    # 用最近一条异常的 message 作为 summary
    $lastAnomaly = $anomalies[$anomalies.Count - 1]
    if ($lastStart -eq "failed") {
        $summary = "最近一次启动失败，异常原因：$($lastAnomaly.message)"
    } else {
        $summary = "检测到异常：$($lastAnomaly.message)"
    }
}

$result = @{
    status = $status
    log_file = $logFile
    last_start_status = $lastStart
    anomalies = $anomalies
    summary = $summary
}

$result | ConvertTo-Json -Depth 5
