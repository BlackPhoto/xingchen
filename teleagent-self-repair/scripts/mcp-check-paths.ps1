#requires -version 5.1
# ============================================================
# MCP 路径校验脚本 (Windows PowerShell 5.1+)
# ============================================================
# 功能：备份配置 → 解析 MCP 条目 → 校验路径 → 推测正确路径 → 输出诊断结果
# 用法：.\mcp-check-paths.ps1
# 输出：结构化诊断信息，供 Agent 展示给用户确认
# ============================================================

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# --- 定位当前账号配置目录（环境变量优先 → TELL owner标记 → 探测兜底）---
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
$configDir = Get-AccountConfigDir
$jsoncFile = Join-Path $configDir "TeleAgent.jsonc"

# 配置文件不在标准路径时，搜索目录下疑似配置文件
if (-not (Test-Path $jsoncFile)) {
    if (Test-Path $configDir) {
        foreach ($ext in @("*.jsonc", "*.json", "*.jsonc.bak")) {
            $found = Get-ChildItem -Path $configDir -Filter $ext -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($found) { $jsoncFile = $found.FullName; break }
        }
    }
}

if (-not (Test-Path $jsoncFile)) {
    Write-Output "[错误] 配置文件不存在: $jsoncFile"
    exit 1
}

# --- Step 1: 备份 ---
Copy-Item $jsoncFile "$jsoncFile.bak" -Force
Write-Output "[信息] 已备份: $jsoncFile -> $jsoncFile.bak"

# --- Step 2: 读取并解析 JSONC ---
$content = Get-Content $jsoncFile -Raw

# 去除 JSONC 注释（状态机 + $esc 标志位，正确处理字符串内的 // 和转义）
$sb = New-Object System.Text.StringBuilder
$inStr = $false; $esc = $false; $i = 0
while ($i -lt $content.Length) {
    $c = $content[$i]
    $nxt = if ($i + 1 -lt $content.Length) { $content[$i + 1] } else { '' }
    if ($inStr) {
        [void]$sb.Append($c)
        if ($esc) { $esc = $false }
        elseif ($c -eq '\') { $esc = $true }
        elseif ($c -eq '"') { $inStr = $false }
        $i++
    } else {
        if ($c -eq '/' -and $nxt -eq '/') {
            while ($i -lt $content.Length -and $content[$i] -ne "`n") { $i++ }
        } elseif ($c -eq '/' -and $nxt -eq '*') {
            $i += 2
            while ($i -lt $content.Length) {
                if ($content[$i] -eq '*' -and ($i + 1) -lt $content.Length -and $content[$i + 1] -eq '/') { $i += 2; break }
                $i++
            }
        } elseif ($c -eq '"') {
            $inStr = $true; [void]$sb.Append($c); $i++
        } else {
            [void]$sb.Append($c); $i++
        }
    }
}

try {
    $data = $sb.ToString() | ConvertFrom-Json
} catch {
    Write-Output "[错误] JSONC 解析失败: $($_.Exception.Message)"
    exit 1
}

# --- Step 3: 校验 MCP 路径 ---
$issues = @()

if (-not $data.mcp) {
    Write-Output "[通过] 配置中无 MCP 段，无需校验"
    exit 0
}

foreach ($name in $data.mcp.PSObject.Properties.Name) {
    $entry = $data.mcp.$name

    # --- 检查 command 数组中所有像路径的元素 ---
    if ($entry.command) {
        for ($j = 0; $j -lt $entry.command.Count; $j++) {
            $cmdPart = $entry.command[$j]
            # 路径特征判断：含反斜杠、盘符开头、以/开头、或以脚本扩展名结尾
            $looksLikePath = ($cmdPart -match '\\') -or
                             ($cmdPart -match '^[A-Za-z]:') -or
                             ($cmdPart -match '^/') -or
                             ($cmdPart -match '\.(js|py|ts|exe|cmd|sh)$')
            if ($looksLikePath) {
                $expanded = [System.Environment]::ExpandEnvironmentVariables($cmdPart)
                if (-not (Test-Path $expanded)) {
                    $issues += @{
                        Server   = $name
                        Field    = "command[$j]"
                        BadPath  = $cmdPart
                        Expanded = $expanded
                    }
                }
            }
        }
    }

    # --- 检查 environment.PATH 中的目录 ---
    if ($entry.environment -and $entry.environment.PATH) {
        $envParts = $entry.environment.PATH -split ';' | Where-Object { $_ -and $_ -notmatch '^\$\{' }
        foreach ($p in $envParts) {
            $expandedP = [System.Environment]::ExpandEnvironmentVariables($p)
            if (-not (Test-Path $expandedP -PathType Container)) {
                $issues += @{
                    Server   = $name
                    Field    = 'environment.PATH'
                    BadPath  = $p
                    Expanded = $expandedP
                }
            }
        }
    }
}

if ($issues.Count -eq 0) {
    Write-Output "[通过] 所有 MCP 路径校验通过，无路径错误"
    exit 0
}

# --- Step 4: 推测正确路径 ---
Write-Output "[发现 $($issues.Count) 个路径问题]"
Write-Output ""
# 定位当前账号数据目录（环境变量优先 → owner标记 → 探测兜底）
function Get-AccountDataDir {
    if ($env:TELEAGENT_DATA_DIR -and (Test-Path $env:TELEAGENT_DATA_DIR)) {
        return $env:TELEAGENT_DATA_DIR
    }
    $ownerFile = Join-Path (Join-Path $env:USERPROFILE ".local\share\TeleAgent") "current-owner.json"
    if (Test-Path $ownerFile) {
        try {
            $owner = (Get-Content $ownerFile -Raw | ConvertFrom-Json).ownerDir
            if ($owner) {
                $d = Join-Path (Join-Path (Join-Path $env:USERPROFILE ".local\share\TeleAgent") "users") $owner
                if (Test-Path $d) { return $d }
            }
        } catch {}
    }
    $usersRoot = Join-Path (Join-Path $env:USERPROFILE ".local\share\TeleAgent") "users"
    if (Test-Path $usersRoot) {
        $latest = Get-ChildItem $usersRoot -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($latest) { return $latest.FullName }
    }
    return Join-Path $env:USERPROFILE ".local\share\TeleAgent"
}
$userDataDir = Get-AccountDataDir

foreach ($iss in $issues) {
    $suggested = $null
    $badPath = $iss.BadPath

    # 场景1: 用户名目录拼错 → 替换为当前用户
    # 匹配任意盘符下的 Users\用户名\ 模式（如 C:\Users\某人\、D:\Users\test\）
    if ($badPath -match '[A-Za-z]:\\Users\\[^\\]+\\') {
        $candidate = $badPath -replace '[A-Za-z]:\\Users\\[^\\]+', $env:USERPROFILE
        if (Test-Path ([System.Environment]::ExpandEnvironmentVariables($candidate))) {
            $suggested = $candidate
        }
    }

    # 场景2: 运行时路径错误 → 在标准目录下搜索同名文件
    if (-not $suggested -and $badPath -match 'runtimes') {
        $filename = Split-Path $badPath -Leaf
        if ($filename -and (Test-Path "$userDataDir\runtimes" -PathType Container)) {
            $found = Get-ChildItem -Path "$userDataDir\runtimes" -Recurse -Filter $filename -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($found) { $suggested = $found.FullName }
        }
    }

    # 场景3: 斜杠方向错误（正斜杠写成了反斜杠，或反过来）→ 尝试替换
    if (-not $suggested -and $badPath -match '/') {
        $candidate = $badPath -replace '/', '\'
        $candidateExp = [System.Environment]::ExpandEnvironmentVariables($candidate)
        if (Test-Path $candidateExp) { $suggested = $candidate }
    }

    Write-Output "[问题] MCP '$($iss.Server)' | $($iss.Field)"
    Write-Output "  当前错误路径: $($iss.Expanded)"
    if ($suggested) {
        Write-Output "  建议修正路径: $suggested"
    } else {
        Write-Output "  建议修正路径: [无法自动推测，需手动确认]"
    }
    Write-Output ""
}
