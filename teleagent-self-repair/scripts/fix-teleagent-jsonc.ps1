#requires -version 5.1
# ============================================================
# TeleAgent.jsonc 配置文件修复脚本 (Windows PowerShell 5.1+)
# ============================================================
# 功能：格式修复（渐进式）→ 字段修复 → 验证 → 回滚兜底
# 用法：.\fix-teleagent-jsonc.ps1
# 前置：需先运行 check-teleagent-jsonc.ps1 创建备份
# ============================================================

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

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
    Write-Output "[错误] 配置文件不存在: $configDir"
    exit 1
}

# --- 验证备份存在 ---
if (-not (Test-Path "$jsoncFile.bak")) {
    Write-Output "[信息] 未找到备份文件，先创建备份"
    Copy-Item $jsoncFile "$jsoncFile.bak" -Force
}

Write-Output "[信息] 配置文件: $jsoncFile"
Write-Output "[信息] 备份文件: $jsoncFile.bak"

# --- 辅助函数：剥离 JSONC 注释（位置保持）---
function Strip-JsoncPreservePosition {
    param([string]$Text)

    $result = $Text.ToCharArray()
    $i = 0
    $inStr = $false
    $esc = $false

    while ($i -lt $Text.Length) {
        $c = $Text[$i]

        if ($inStr) {
            if ($esc) { $esc = $false }
            elseif ($c -eq '\') { $esc = $true }
            elseif ($c -eq '"') { $inStr = $false }
            $i++
        }
        elseif ($c -eq '"') {
            $inStr = $true
            $i++
        }
        elseif ($c -eq '/' -and ($i + 1) -lt $Text.Length) {
            $nxt = $Text[$i + 1]
            if ($nxt -eq '/') {
                while ($i -lt $Text.Length -and $Text[$i] -ne "`n") {
                    $result[$i] = ' '
                    $i++
                }
            }
            elseif ($nxt -eq '*') {
                $result[$i] = ' '
                $result[$i + 1] = ' '
                $i += 2
                while ($i -lt $Text.Length) {
                    if ($Text[$i] -eq '*' -and ($i + 1) -lt $Text.Length -and $Text[$i + 1] -eq '/') {
                        $result[$i] = ' '
                        $result[$i + 1] = ' '
                        $i += 2
                        break
                    }
                    if ($Text[$i] -ne "`n") { $result[$i] = ' ' }
                    $i++
                }
            }
            else { $i++ }
        }
        else { $i++ }
    }

    return -join $result
}

# --- 辅助函数：验证 JSON 可解析 ---
function Test-JsonParse {
    param([string]$Text)

    $stripped = Strip-JsoncPreservePosition $Text
    try {
        $null = $stripped | ConvertFrom-Json -ErrorAction Stop
        return $true
    }
    catch {
        return $false
    }
}

# --- 读取内容 ---
$bytes = [System.IO.File]::ReadAllBytes($jsoncFile)
$content = [System.IO.File]::ReadAllText($jsoncFile, [System.Text.Encoding]::UTF8)
$fixesApplied = @()

# ========== 格式修复 ==========

# --- 修复 1: 移除 UTF-8 BOM ---
if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
    $newBytes = New-Object byte[] ($bytes.Length - 3)
    [Array]::Copy($bytes, 3, $newBytes, 0, $bytes.Length - 3)
    [System.IO.File]::WriteAllBytes($jsoncFile, $newBytes)
    $content = [System.Text.Encoding]::UTF8.GetString($newBytes)
    $bytes = $newBytes
    $fixesApplied += "移除 UTF-8 BOM"
    Write-Output "[修复][格式] 移除 UTF-8 BOM"
}

# --- 修复 2: 清除控制字符 ---
$controlRegex = '[\x00-\x08\x0B\x0C\x0E-\x1F]'
$controlMatches = [regex]::Matches($content, $controlRegex)
if ($controlMatches.Count -gt 0) {
    $content = [regex]::Replace($content, $controlRegex, '')
    [System.IO.File]::WriteAllText($jsoncFile, $content, [System.Text.Encoding]::UTF8)
    $fixesApplied += "清除 $($controlMatches.Count) 个控制字符"
    Write-Output "[修复][格式] 清除 $($controlMatches.Count) 个控制字符"
}

# --- 修复 3: 替换全角符号（字符串外）---
$fullwidthMap = @{
    [char]0xFF0C = ','; [char]0xFF1A = ':'; [char]0x201C = '"'; [char]0x201D = '"'
    [char]0xFF08 = '('; [char]0xFF09 = ')'; [char]0xFF3B = '['; [char]0xFF3D = ']'
    [char]0xFF5B = '{'; [char]0xFF5D = '}'; [char]0xFF1B = ';'
}

$chars = $content.ToCharArray()
$fullwidthCount = 0
$inStr = $false
$esc = $false

for ($i = 0; $i -lt $chars.Length; $i++) {
    $c = $chars[$i]

    if ($inStr) {
        if ($esc) { $esc = $false }
        elseif ($c -eq '\') { $esc = $true }
        elseif ($c -eq '"') { $inStr = $false }
        continue
    }

    if ($c -eq '"') { $inStr = $true; continue }

    if ($fullwidthMap.ContainsKey($c)) {
        $chars[$i] = $fullwidthMap[$c]
        $fullwidthCount++
    }
}

if ($fullwidthCount -gt 0) {
    $content = -join $chars
    [System.IO.File]::WriteAllText($jsoncFile, $content, [System.Text.Encoding]::UTF8)
    $fixesApplied += "替换 $fullwidthCount 处全角符号"
    Write-Output "[修复][格式] 替换 $fullwidthCount 处全角符号"
}

# --- 尝试解析 → 成功则跳到字段修复 ---
$formatFixed = $false
if (Test-JsonParse $content) {
    $formatFixed = $true
    Write-Output "[通过][格式] 修复后 JSON 格式校验通过"
}

if (-not $formatFixed) {
    # --- 修复 4: 移除尾逗号（字符串外，保留原始注释）---
    $sb = New-Object System.Text.StringBuilder
    $inStr = $false; $esc = $false; $trailingCount = 0; $i = 0

    while ($i -lt $content.Length) {
        $c = $content[$i]

        if ($inStr) {
            [void]$sb.Append($c)
            if ($esc) { $esc = $false }
            elseif ($c -eq '\') { $esc = $true }
            elseif ($c -eq '"') { $inStr = $false }
            $i++; continue
        }

        if ($c -eq '"') { $inStr = $true; [void]$sb.Append($c); $i++; continue }

        if ($c -eq ',') {
            $j = $i + 1
            while ($j -lt $content.Length) {
                if ([char]::IsWhiteSpace($content[$j])) { $j++ }
                elseif ($content[$j] -eq '/' -and ($j + 1) -lt $content.Length -and $content[$j + 1] -eq '/') {
                    while ($j -lt $content.Length -and $content[$j] -ne "`n") { $j++ }
                }
                elseif ($content[$j] -eq '/' -and ($j + 1) -lt $content.Length -and $content[$j + 1] -eq '*') {
                    $j += 2
                    while ($j -lt $content.Length) {
                        if ($content[$j] -eq '*' -and ($j + 1) -lt $content.Length -and $content[$j + 1] -eq '/') { $j += 2; break }
                        $j++
                    }
                }
                else { break }
            }
            if ($j -lt $content.Length -and ($content[$j] -eq '}' -or $content[$j] -eq ']')) {
                $trailingCount++; $i++; continue
            }
            [void]$sb.Append($c); $i++; continue
        }

        [void]$sb.Append($c); $i++
    }

    if ($trailingCount -gt 0) {
        $content = $sb.ToString()
        [System.IO.File]::WriteAllText($jsoncFile, $content, [System.Text.Encoding]::UTF8)
        $fixesApplied += "移除 $trailingCount 处尾逗号"
        Write-Output "[修复][格式] 移除 $trailingCount 处尾逗号"
    }

    if (Test-JsonParse $content) {
        $formatFixed = $true
        Write-Output "[通过][格式] 修复后 JSON 格式校验通过"
    }
}

if (-not $formatFixed) {
    # --- 修复 5: 修复连续逗号（字符串外，注释感知）---
    $sb = New-Object System.Text.StringBuilder
    $inStr = $false; $esc = $false; $prevComma = $false; $doubleCount = 0; $i = 0

    while ($i -lt $content.Length) {
        $c = $content[$i]

        if ($inStr) {
            [void]$sb.Append($c)
            if ($esc) { $esc = $false }
            elseif ($c -eq '\') { $esc = $true }
            elseif ($c -eq '"') { $inStr = $false }
            $prevComma = $false; $i++; continue
        }

        if ($c -eq '"') { $inStr = $true; $prevComma = $false; [void]$sb.Append($c); $i++; continue }

        if ($c -eq '/' -and ($i + 1) -lt $content.Length -and $content[$i + 1] -eq '/') {
            while ($i -lt $content.Length -and $content[$i] -ne "`n") { [void]$sb.Append($content[$i]); $i++ }
            $prevComma = $false; continue
        }

        if ($c -eq '/' -and ($i + 1) -lt $content.Length -and $content[$i + 1] -eq '*') {
            [void]$sb.Append($content[$i]); [void]$sb.Append($content[$i + 1]); $i += 2
            while ($i -lt $content.Length) {
                if ($content[$i] -eq '*' -and ($i + 1) -lt $content.Length -and $content[$i + 1] -eq '/') {
                    [void]$sb.Append($content[$i]); [void]$sb.Append($content[$i + 1]); $i += 2; break
                }
                [void]$sb.Append($content[$i]); $i++
            }
            $prevComma = $false; continue
        }

        if ($c -eq ',') {
            if ($prevComma) { $doubleCount++; $i++; continue }
            $prevComma = $true
        }
        elseif (-not [char]::IsWhiteSpace($c)) { $prevComma = $false }

        [void]$sb.Append($c); $i++
    }

    if ($doubleCount -gt 0) {
        $content = $sb.ToString()
        [System.IO.File]::WriteAllText($jsoncFile, $content, [System.Text.Encoding]::UTF8)
        $fixesApplied += "修复 $doubleCount 处连续逗号"
        Write-Output "[修复][格式] 修复 $doubleCount 处连续逗号"
    }

    if (Test-JsonParse $content) {
        $formatFixed = $true
        Write-Output "[通过][格式] 修复后 JSON 格式校验通过"
    }
}

if (-not $formatFixed) {
    # --- 修复 6: 补全缺少闭合的括号 ---
    $stack = @()
    $inStr = $false; $esc = $false
    $stripped = Strip-JsoncPreservePosition $content

    for ($i = 0; $i -lt $stripped.Length; $i++) {
        $c = $stripped[$i]

        if ($inStr) {
            if ($esc) { $esc = $false }
            elseif ($c -eq '\') { $esc = $true }
            elseif ($c -eq '"') { $inStr = $false }
        }
        else {
            if ($c -eq '"') { $inStr = $true }
            elseif ($c -eq '{' -or $c -eq '[') { $stack += $c }
            elseif ($c -eq '}' -or $c -eq ']') {
                if ($stack.Count -gt 0) {
                    $top = $stack[$stack.Count - 1]
                    $expected = if ($c -eq '}') { '{' } else { '[' }
                    if ($top -eq $expected) {
                        if ($stack.Count -le 1) { $stack = @() } else { $stack = $stack[0..($stack.Count - 2)] }
                    }
                }
            }
        }
    }

    if ($stack.Count -gt 0) {
        $closers = ""
        for ($si = $stack.Count - 1; $si -ge 0; $si--) {
            if ($stack[$si] -eq '{') { $closers += '}' }
            elseif ($stack[$si] -eq '[') { $closers += ']' }
        }
        $content = $content.TrimEnd() + "`n" + $closers + "`n"
        [System.IO.File]::WriteAllText($jsoncFile, $content, [System.Text.Encoding]::UTF8)
        $fixesApplied += "补全 $($stack.Count) 个闭合括号"
        Write-Output "[修复][格式] 补全 $($stack.Count) 个闭合括号: $closers"
    }

    if (Test-JsonParse $content) {
        $formatFixed = $true
        Write-Output "[通过][格式] 修复后 JSON 格式校验通过"
    }
}

if (-not $formatFixed) {
    # --- 修复 7: 修复未闭合的多行注释 ---
    $inStr = $false; $esc = $false; $inBlock = $false; $blockStartIdx = -1
    $chars = $content.ToCharArray()

    for ($i = 0; $i -lt $chars.Length; $i++) {
        $c = $chars[$i]

        if ($inStr) {
            if ($esc) { $esc = $false }
            elseif ($c -eq '\') { $esc = $true }
            elseif ($c -eq '"') { $inStr = $false }
        }
        elseif ($inBlock) {
            if ($c -eq '*' -and ($i + 1) -lt $chars.Length -and $chars[$i + 1] -eq '/') {
                $inBlock = $false; $i++
            }
        }
        else {
            if ($c -eq '"') { $inStr = $true }
            elseif ($c -eq '/' -and ($i + 1) -lt $chars.Length) {
                if ($chars[$i + 1] -eq '*') { $inBlock = $true; $blockStartIdx = $i; $i++ }
                elseif ($chars[$i + 1] -eq '/') { while ($i -lt $chars.Length -and $chars[$i] -ne "`n") { $i++ } }
            }
        }
    }

    if ($inBlock -and $blockStartIdx -ge 0) {
        $content = $content.TrimEnd() + "`n*/`n"
        [System.IO.File]::WriteAllText($jsoncFile, $content, [System.Text.Encoding]::UTF8)
        $fixesApplied += "修复未闭合注释"
        Write-Output "[修复][格式] 修复未闭合注释: 在末尾追加 */"
    }

    if (Test-JsonParse $content) {
        $formatFixed = $true
        Write-Output "[通过][格式] 修复后 JSON 格式校验通过"
    }
}

# --- 格式修复全部用尽仍失败 → 回滚 ---
if (-not $formatFixed) {
    Write-Output "[失败][格式] 自动修复后仍无法通过 JSON 格式校验"
    Copy-Item "$jsoncFile.bak" $jsoncFile -Force
    Write-Output "[回滚] 已恢复备份文件: $jsoncFile.bak"
    Write-Output "[建议] 请手动编辑配置文件修复格式错误"
    exit 1
}

# ========== 字段修复 ==========

# 剥离注释并解析 JSON（注释会丢失，文件转为标准 JSON）
$stripped = Strip-JsoncPreservePosition $content
$data = $stripped | ConvertFrom-Json
$fieldFixed = $false

# --- 字段修复 1: 移除/重命名非法字段 mcpServers ---
if ($data.PSObject.Properties.Name -contains 'mcpServers') {
    if ($data.PSObject.Properties.Name -notcontains 'mcp') {
        # mcp 不存在：将 mcpServers 重命名为 mcp
        $data | Add-Member -NotePropertyName 'mcp' -NotePropertyValue $data.mcpServers -Force
        $data.PSObject.Properties.Remove('mcpServers')
        $fixesApplied += "重命名非法字段 mcpServers -> mcp"
        Write-Output "[修复][字段] 重命名非法字段 mcpServers -> mcp"
    } else {
        # mcp 已存在：删除 mcpServers
        $data.PSObject.Properties.Remove('mcpServers')
        $fixesApplied += "删除非法字段 mcpServers（mcp 已存在）"
        Write-Output "[修复][字段] 删除非法字段 mcpServers（mcp 已存在，请确认 MCP 配置）"
    }
    $fieldFixed = $true
}

# --- 字段修复 2: 修正 MCP 字段值类型 ---
if ($data.mcp -and $data.mcp -is [PSCustomObject]) {
    foreach ($name in @($data.mcp.PSObject.Properties.Name)) {
        $entry = $data.mcp.$name
        if ($entry -isnot [PSCustomObject]) { continue }
        $props = $entry.PSObject.Properties.Name

        # type 大小写修正
        if ($props -contains 'type') {
            $lowerType = "$($entry.type)".ToLower()
            if ($entry.type -cne $lowerType -and $lowerType -in @('local', 'remote')) {
                $oldVal = $entry.type
                $entry.type = $lowerType
                $fieldFixed = $true
                $fixesApplied += "mcp.$name.type 大小写修正: $oldVal -> $lowerType"
                Write-Output "[修复][字段] mcp.$name.type 大小写修正: $oldVal -> $lowerType"
            }
        }

        # enabled 字符串 → 布尔值
        if ($props -contains 'enabled') {
            if ($entry.enabled -is [string]) {
                $oldVal = $entry.enabled
                $lowerEnabled = $entry.enabled.ToLower()
                if ($lowerEnabled -in @('true', 'yes', '1', 'enabled')) {
                    $entry.enabled = $true
                } elseif ($lowerEnabled -in @('false', 'no', '0', 'disabled', '')) {
                    $entry.enabled = $false
                } else {
                    $entry.enabled = $true
                }
                $fieldFixed = $true
                $fixesApplied += "mcp.$name.enabled 类型修正: `"$oldVal`" -> $($entry.enabled)"
                Write-Output "[修复][字段] mcp.$name.enabled 类型修正: `"$oldVal`" -> $($entry.enabled)"
            }
        }

        # timeout 字符串/浮点 → 正整数
        if ($props -contains 'timeout') {
            $val = $entry.timeout
            if ($val -is [string]) {
                $oldVal = $val
                $parsedVal = 0
                if ([int]::TryParse($val, [ref]$parsedVal)) {
                    $entry.timeout = $parsedVal
                } else {
                    $entry.timeout = 30000
                }
                $fieldFixed = $true
                $fixesApplied += "mcp.$name.timeout 类型修正: `"$oldVal`" -> $($entry.timeout)"
                Write-Output "[修复][字段] mcp.$name.timeout 类型修正: `"$oldVal`" -> $($entry.timeout)"
            } elseif ($val -is [bool]) {
                $entry.timeout = 30000
                $fieldFixed = $true
                $fixesApplied += "mcp.$name.timeout 类型修正: $val -> 30000"
                Write-Output "[修复][字段] mcp.$name.timeout 类型修正: $val -> 30000"
            } elseif ($val -is [double] -or $val -is [decimal]) {
                $entry.timeout = [int]$val
                $fieldFixed = $true
                $fixesApplied += "mcp.$name.timeout 类型修正: $val -> $($entry.timeout)"
                Write-Output "[修复][字段] mcp.$name.timeout 类型修正: $val -> $($entry.timeout)"
            } elseif ($val -lt 1) {
                $entry.timeout = 30000
                $fieldFixed = $true
                $fixesApplied += "mcp.$name.timeout 值修正: $val -> 30000"
                Write-Output "[修复][字段] mcp.$name.timeout 值修正: $val -> 30000"
            }
        }

        # command 字符串 → 数组
        if ($props -contains 'command') {
            if ($entry.command -isnot [System.Array]) {
                $oldVal = $entry.command
                $entry.command = @("$oldVal")
                $fieldFixed = $true
                $fixesApplied += "mcp.$name.command 类型修正: 字符串 -> 数组"
                Write-Output "[修复][字段] mcp.$name.command 类型修正: $oldVal -> 数组"
            }
        }

        # environment 非对象 → 删除（无法安全转换）
        if ($props -contains 'environment') {
            if ($entry.environment -isnot [System.Management.Automation.PSCustomObject]) {
                $entry.PSObject.Properties.Remove('environment')
                $fieldFixed = $true
                $fixesApplied += "mcp.$name.environment 类型错误，已删除（无法安全转换）"
                Write-Output "[修复][字段] mcp.$name.environment 类型错误，已删除（无法安全转换）"
            }
        }
    }
}

# --- 字段修复 3: 修正 permission.skill 值 ---
if ($data.permission -and $data.permission.skill -and $data.permission.skill -is [PSCustomObject]) {
    foreach ($skillId in @($data.permission.skill.PSObject.Properties.Name)) {
        $val = $data.permission.skill.$skillId
        if ($val -notin @('allow', 'deny')) {
            $oldVal = $val
            $lowerVal = "$val".ToLower()
            if ($val -is [bool]) {
                $data.permission.skill.$skillId = if ($val) { 'allow' } else { 'deny' }
            } elseif ($lowerVal -in @('true', 'yes', 'enabled', '1')) {
                $data.permission.skill.$skillId = 'allow'
            } elseif ($lowerVal -in @('false', 'no', 'disabled', '0')) {
                $data.permission.skill.$skillId = 'deny'
            } else {
                $data.permission.skill.$skillId = 'allow'
            }
            $fieldFixed = $true
            $fixesApplied += "permission.skill.$skillId 值修正: $oldVal -> $($data.permission.skill.$skillId)"
            Write-Output "[修复][字段] permission.skill.$skillId 值修正: $oldVal -> $($data.permission.skill.$skillId)"
        }
    }
}

# --- 序列化回写 ---
if ($fieldFixed) {
    $jsonOutput = $data | ConvertTo-Json -Depth 10
    [System.IO.File]::WriteAllText($jsoncFile, $jsonOutput, [System.Text.Encoding]::UTF8)
    Write-Output "[信息][字段] 字段修复完成，文件已转为标准 JSON（注释丢失）"
}

# --- 最终验证 ---
if (Test-JsonParse ([System.IO.File]::ReadAllText($jsoncFile, [System.Text.Encoding]::UTF8))) {
    Write-Output ""
    Write-Output "========== 修复汇总 =========="
    if ($fixesApplied.Count -gt 0) {
        Write-Output "[完成] 已应用修复: $($fixesApplied -join ', ')"
    } else {
        Write-Output "[完成] 无需修复，配置文件已通过所有检查"
    }
    exit 0
} else {
    Write-Output "[失败] 修复后仍无法通过 JSON 格式校验"
    Copy-Item "$jsoncFile.bak" $jsoncFile -Force
    Write-Output "[回滚] 已恢复备份文件: $jsoncFile.bak"
    Write-Output "[建议] 请手动编辑配置文件修复问题"
    exit 1
}
