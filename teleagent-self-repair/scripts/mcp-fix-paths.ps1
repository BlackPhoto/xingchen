#requires -version 5.1
# ============================================================
# MCP 路径修复脚本 (Windows PowerShell 5.1+)
# ============================================================
# 功能：读取修复清单 JSON 文件 → 写入修正路径 → JSON 格式校验 → 失败回滚
# 用法：.\mcp-fix-paths.ps1 -FixesFile <修复清单JSON文件路径>
#
# 修复清单 JSON 格式：
# [
#   {
#     "server": "<MCP Server 名称>",
#     "field": "command[1]",
#     "old_bad": "<当前错误路径>",
#     "new_path": "<修正后的路径>"
#   }
# ]
# ============================================================

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

param(
    [Parameter(Mandatory=$true)]
    [string]$FixesFile
)

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

if (-not (Test-Path "$jsoncFile.bak")) {
    Write-Output "[警告] 未找到备份文件 (.bak)，请确认已运行 mcp-check-paths.ps1"
}

# --- 读取修复清单 ---
if (-not (Test-Path $FixesFile)) {
    Write-Output "[错误] 修复清单文件不存在: $FixesFile"
    exit 1
}

try {
    $fixes = Get-Content $FixesFile -Raw | ConvertFrom-Json
} catch {
    Write-Output "[错误] 修复清单 JSON 解析失败: $($_.Exception.Message)"
    exit 1
}

# --- 读取并解析 JSONC ---
$content = Get-Content $jsoncFile -Raw

# 去除 JSONC 注释（状态机 + $esc 标志位）
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

# --- 应用修复 ---
foreach ($fix in $fixes) {
    if (-not $data.mcp.($fix.server)) {
        Write-Output "[警告] MCP Server '$($fix.server)' 不存在，跳过"
        continue
    }

    $entry = $data.mcp.($fix.server)
    $field = $fix.field

    if ($field -match '^command\[') {
        # 提取索引: command[N]
        $index = [int]($field -replace 'command\[(\d+)\]', '$1')
        $oldValue = $entry.command[$index]
        $entry.command[$index] = $fix.new_path
        Write-Output "[修复] $($fix.server) | command[$index] | $oldValue -> $($fix.new_path)"
    }
    elseif ($field -eq 'environment.PATH') {
        # 按分隔符拆分后逐个匹配替换，避免误伤包含子串的其他路径
        $sep = if ($entry.environment.PATH -match ';') { ';' } else { ':' }
        $pathParts = $entry.environment.PATH -split $sep
        $replaced = $false
        for ($pi = 0; $pi -lt $pathParts.Count; $pi++) {
            if ($pathParts[$pi] -eq $fix.old_bad) {
                $pathParts[$pi] = $fix.new_path
                $replaced = $true
            }
        }
        if ($replaced) {
            $entry.environment.PATH = $pathParts -join $sep
        }
        Write-Output "[修复] $($fix.server) | environment.PATH | $($fix.old_bad) -> $($fix.new_path)"
    }
    else {
        Write-Output "[警告] 未知字段: $field，跳过"
    }
}

# --- 写入文件（注意：JSONC 注释会丢失，转为标准 JSON）---
$jsonOutput = $data | ConvertTo-Json -Depth 10
[System.IO.File]::WriteAllText($jsoncFile, $jsonOutput, [System.Text.Encoding]::UTF8)

# --- JSON 格式校验 ---
try {
    $null = Get-Content $jsoncFile -Raw | ConvertFrom-Json
    Write-Output "[通过] 修正后 JSON 格式校验通过"
} catch {
    Write-Output "[失败] 修正后 JSON 格式校验失败，正在回滚..."
    Copy-Item "$jsoncFile.bak" $jsoncFile -Force
    Write-Output "[回滚] 已恢复备份文件"
    exit 1
}
