#requires -version 5.1
# ============================================================
# TeleAgent.jsonc 配置文件诊断脚本 (Windows PowerShell 5.1+)
# ============================================================
# 功能：备份 → 格式检查 → 字段检查 → 路径检查 → 输出诊断结果
# 用法：.\check-teleagent-jsonc.ps1
# 输出：结构化诊断信息，供 Agent 展示给用户确认
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

Write-Output "[信息] 配置文件: $jsoncFile"

# --- Step 1: 备份 ---
Copy-Item $jsoncFile "$jsoncFile.bak" -Force
Write-Output "[信息] 已备份: $jsoncFile -> $jsoncFile.bak"

# --- 辅助函数：剥离 JSONC 注释（位置保持）---
function Strip-JsoncPreservePosition {
    param([string]$Text)
    $result = $Text.ToCharArray()
    $i = 0; $inStr = $false; $esc = $false
    while ($i -lt $Text.Length) {
        $c = $Text[$i]
        if ($inStr) {
            if ($esc) { $esc = $false }
            elseif ($c -eq '\') { $esc = $true }
            elseif ($c -eq '"') { $inStr = $false }
            $i++
        }
        elseif ($c -eq '"') { $inStr = $true; $i++ }
        elseif ($c -eq '/' -and ($i + 1) -lt $Text.Length) {
            $nxt = $Text[$i + 1]
            if ($nxt -eq '/') {
                while ($i -lt $Text.Length -and $Text[$i] -ne "`n") { $result[$i] = ' '; $i++ }
            }
            elseif ($nxt -eq '*') {
                $result[$i] = ' '; $result[$i + 1] = ' '; $i += 2
                while ($i -lt $Text.Length) {
                    if ($Text[$i] -eq '*' -and ($i + 1) -lt $Text.Length -and $Text[$i + 1] -eq '/') {
                        $result[$i] = ' '; $result[$i + 1] = ' '; $i += 2; break
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

# ========== 格式检查 ==========

# --- Step 2: 检测 UTF-8 BOM ---
$bytes = [System.IO.File]::ReadAllBytes($jsoncFile)
$hasBOM = ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)
if ($hasBOM) { Write-Output "[问题][格式] UTF-8 BOM: 文件前3字节为 EF BB BF" }

# --- Step 3: 读取文本内容 ---
$content = [System.IO.File]::ReadAllText($jsoncFile, [System.Text.Encoding]::UTF8)
$lines = $content -split "`n"

# --- Step 4: 检测控制字符 ---
$controlCharFound = $false
for ($ln = 0; $ln -lt $lines.Length; $ln++) {
    for ($ci = 0; $ci -lt $lines[$ln].Length; $ci++) {
        $code = [int]$lines[$ln][$ci]
        if (($code -ge 0x00 -and $code -le 0x08) -or $code -eq 0x0B -or $code -eq 0x0C -or ($code -ge 0x0E -and $code -le 0x1F)) {
            if (-not $controlCharFound) { Write-Output "[问题][格式] 控制字符: 文件包含不可见控制字符"; $controlCharFound = $true }
            Write-Output ("  第 " + ($ln + 1) + " 行第 " + ($ci + 1) + " 列: 0x" + $code.ToString("X2"))
        }
    }
}

# --- Step 5: 检测全角符号 ---
$fullwidthMap = @{
    [char]0xFF0C = ','; [char]0xFF1A = ':'; [char]0x201C = '"'; [char]0x201D = '"'
    [char]0xFF08 = '('; [char]0xFF09 = ')'; [char]0xFF3B = '['; [char]0xFF3D = ']'
    [char]0xFF5B = '{'; [char]0xFF5D = '}'; [char]0xFF1B = ';'
}
$fullwidthFound = $false
for ($ln = 0; $ln -lt $lines.Length; $ln++) {
    for ($ci = 0; $ci -lt $lines[$ln].Length; $ci++) {
        $c = $lines[$ln][$ci]
        if ($fullwidthMap.ContainsKey($c)) {
            if (-not $fullwidthFound) { Write-Output "[问题][格式] 全角符号: 文件包含全角符号混入"; $fullwidthFound = $true }
            Write-Output ("  第 " + ($ln + 1) + " 行第 " + ($ci + 1) + " 列: $c -> " + $fullwidthMap[$c])
        }
    }
}

# --- Step 6: 剥离 JSONC 注释 ---
$stripped = Strip-JsoncPreservePosition $content

# --- Step 7: 检测尾逗号 ---
$trailingCommas = @()
$inStr = $false; $esc = $false; $lineNum = 1; $colNum = 1
for ($i = 0; $i -lt $stripped.Length; $i++) {
    $c = $stripped[$i]
    if ($inStr) {
        if ($esc) { $esc = $false } elseif ($c -eq '\') { $esc = $true } elseif ($c -eq '"') { $inStr = $false }
    } else {
        if ($c -eq '"') { $inStr = $true }
        elseif ($c -eq ',') {
            $j = $i + 1
            while ($j -lt $stripped.Length -and [char]::IsWhiteSpace($stripped[$j])) { $j++ }
            if ($j -lt $stripped.Length -and ($stripped[$j] -eq '}' -or $stripped[$j] -eq ']')) {
                $trailingCommas += @{ Line = $lineNum; Col = $colNum }
            }
        }
    }
    if ($c -eq "`n") { $lineNum++; $colNum = 1 } else { $colNum++ }
}
if ($trailingCommas.Count -gt 0) {
    Write-Output "[问题][格式] 尾逗号: 发现 $($trailingCommas.Count) 处"
    foreach ($tc in $trailingCommas) { Write-Output "  第 $($tc.Line) 行第 $($tc.Col) 列" }
}

# --- Step 8: 检测连续逗号 ---
$doubleCommas = @()
$inStr = $false; $esc = $false; $prevComma = $false; $prevCommaLine = 0; $prevCommaCol = 0; $lineNum = 1; $colNum = 1
for ($i = 0; $i -lt $stripped.Length; $i++) {
    $c = $stripped[$i]
    if ($inStr) {
        if ($esc) { $esc = $false } elseif ($c -eq '\') { $esc = $true } elseif ($c -eq '"') { $inStr = $false }
        $prevComma = $false
    } else {
        if ($c -eq '"') { $inStr = $true; $prevComma = $false }
        elseif ($c -eq ',') {
            if ($prevComma) { $doubleCommas += @{ Line = $prevCommaLine; Col = $prevCommaCol } }
            $prevComma = $true; $prevCommaLine = $lineNum; $prevCommaCol = $colNum
        }
        elseif (-not [char]::IsWhiteSpace($c)) { $prevComma = $false }
    }
    if ($c -eq "`n") { $lineNum++; $colNum = 1 } else { $colNum++ }
}
if ($doubleCommas.Count -gt 0) {
    Write-Output "[问题][格式] 连续逗号: 发现 $($doubleCommas.Count) 处"
    foreach ($dc in $doubleCommas) { Write-Output "  第 $($dc.Line) 行第 $($dc.Col) 列" }
}

# --- Step 9: 检测括号不匹配 ---
$bracketIssues = @()
$stack = @()
$inStr = $false; $esc = $false; $lineNum = 1; $colNum = 1
for ($i = 0; $i -lt $stripped.Length; $i++) {
    $c = $stripped[$i]
    if ($inStr) {
        if ($esc) { $esc = $false } elseif ($c -eq '\') { $esc = $true } elseif ($c -eq '"') { $inStr = $false }
    } else {
        if ($c -eq '"') { $inStr = $true }
        elseif ($c -eq '{' -or $c -eq '[') { $stack += @{ Char = $c; Line = $lineNum; Col = $colNum } }
        elseif ($c -eq '}' -or $c -eq ']') {
            if ($stack.Count -eq 0) {
                $bracketIssues += @{ Type = "多余闭合"; Char = $c; Line = $lineNum; Col = $colNum }
            } else {
                $top = $stack[$stack.Count - 1]
                $expected = if ($c -eq '}') { '{' } else { '[' }
                if ($top.Char -eq $expected) {
                    if ($stack.Count -le 1) { $stack = @() } else { $stack = $stack[0..($stack.Count - 2)] }
                } else {
                    $bracketIssues += @{ Type = "类型不匹配"; Char = $c; Line = $lineNum; Col = $colNum }
                }
            }
        }
    }
    if ($c -eq "`n") { $lineNum++; $colNum = 1 } else { $colNum++ }
}
foreach ($s in $stack) { $bracketIssues += @{ Type = "缺少闭合"; Char = (if ($s.Char -eq '{') { '}' } else { ']' }); Line = $s.Line; Col = $s.Col } }
if ($bracketIssues.Count -gt 0) {
    $missing = @($bracketIssues | Where-Object { $_.Type -eq "缺少闭合" }).Count
    $extra = @($bracketIssues | Where-Object { $_.Type -eq "多余闭合" }).Count
    $mismatch = @($bracketIssues | Where-Object { $_.Type -eq "类型不匹配" }).Count
    Write-Output "[问题][格式] 括号不匹配: 缺少闭合 $missing 处, 多余闭合 $extra 处, 类型不匹配 $mismatch 处"
    foreach ($bi in $bracketIssues) {
        if ($bi.Type -eq "缺少闭合") { Write-Output "  第 $($bi.Line) 行: 缺少闭合 $($bi.Char)" }
        elseif ($bi.Type -eq "多余闭合") { Write-Output "  第 $($bi.Line) 行第 $($bi.Col) 列: 多余闭合 $($bi.Char)" }
        else { Write-Output "  第 $($bi.Line) 行第 $($bi.Col) 列: 类型不匹配 $($bi.Char)" }
    }
}

# --- Step 10: 检测未闭合的多行注释 ---
$inStr = $false; $esc = $false; $inBlock = $false; $blockStartLine = 0; $lineNum = 1
for ($i = 0; $i -lt $content.Length; $i++) {
    $c = $content[$i]
    if ($c -eq "`n") { $lineNum++; continue }
    if ($inStr) {
        if ($esc) { $esc = $false } elseif ($c -eq '\') { $esc = $true } elseif ($c -eq '"') { $inStr = $false }
    }
    elseif ($inBlock) {
        if ($c -eq '*' -and ($i + 1) -lt $content.Length -and $content[$i + 1] -eq '/') { $inBlock = $false; $i++ }
    }
    else {
        if ($c -eq '"') { $inStr = $true }
        elseif ($c -eq '/' -and ($i + 1) -lt $content.Length) {
            if ($content[$i + 1] -eq '*') { $inBlock = $true; $blockStartLine = $lineNum; $i++ }
            elseif ($content[$i + 1] -eq '/') { while ($i -lt $content.Length -and $content[$i] -ne "`n") { $i++ } }
        }
    }
}
if ($inBlock) { Write-Output "[问题][格式] 未闭合注释: 第 $blockStartLine 行存在未闭合的 /* 注释" }

# --- Step 11: JSON 解析测试 ---
$formatOK = $true
try {
    $null = $stripped | ConvertFrom-Json -ErrorAction Stop
    Write-Output "[通过][格式] JSON 格式校验通过"
} catch {
    $formatOK = $false
    Write-Output "[问题][格式] JSON解析失败: $($_.Exception.Message)"
}

# ========== 字段检查（仅格式通过时）==========
$fieldIssues = @()

if ($formatOK) {
    $data = $stripped | ConvertFrom-Json

    # --- 非法字段检测 ---
    if ($data.PSObject.Properties.Name -contains 'mcpServers') {
        $fieldIssues += "非法字段 mcpServers（应为 mcp）"
        Write-Output "[问题][字段] 非法字段: mcpServers（应为 mcp），会导致 Server fatal 退出"
    }

    # --- MCP 字段值校验 ---
    if ($data.mcp -and $data.mcp -is [PSCustomObject]) {
        foreach ($name in $data.mcp.PSObject.Properties.Name) {
            $entry = $data.mcp.$name
            if ($entry -isnot [PSCustomObject]) {
                $fieldIssues += "mcp.$name 类型错误（应为对象）"
                Write-Output "[问题][字段] mcp.$name 类型错误（应为对象）"
                continue
            }
            $props = $entry.PSObject.Properties.Name

            # type 校验
            if ($props -contains 'type') {
                if ($entry.type -notin @('local', 'remote')) {
                    $fieldIssues += "mcp.$name.type 值不合法: $($entry.type)（应为 local 或 remote）"
                    Write-Output "[问题][字段] mcp.$name.type 值不合法: $($entry.type)（应为 local 或 remote）"
                }
            }

            # enabled 类型校验
            if ($props -contains 'enabled') {
                if ($entry.enabled -is [string]) {
                    $fieldIssues += "mcp.$name.enabled 类型错误: 字符串（应为布尔值）"
                    Write-Output "[问题][字段] mcp.$name.enabled 类型错误: `"$($entry.enabled)`"（应为布尔值 true/false）"
                }
            }

            # timeout 类型校验
            if ($props -contains 'timeout') {
                $val = $entry.timeout
                if ($val -is [string] -or $val -is [bool]) {
                    $fieldIssues += "mcp.$name.timeout 类型错误（应为正整数）"
                    Write-Output "[问题][字段] mcp.$name.timeout 类型错误: $val（应为正整数毫秒）"
                } elseif ($val -lt 1) {
                    $fieldIssues += "mcp.$name.timeout 值不合法: $val（应为正整数）"
                    Write-Output "[问题][字段] mcp.$name.timeout 值不合法: $val（应为正整数毫秒）"
                }
            }

            # command 类型校验
            if ($props -contains 'command') {
                if ($entry.command -isnot [System.Array]) {
                    $fieldIssues += "mcp.$name.command 类型错误（应为数组）"
                    Write-Output "[问题][字段] mcp.$name.command 类型错误: $($entry.command)（应为字符串数组）"
                }
            }

            # environment 类型校验
            if ($props -contains 'environment') {
                if ($entry.environment -isnot [System.Management.Automation.PSCustomObject]) {
                    $fieldIssues += "mcp.$name.environment 类型错误（应为对象）"
                    Write-Output "[问题][字段] mcp.$name.environment 类型错误（应为对象 {`"KEY`": `"value`"}）"
                }
            }
        }
    }

    # --- permission.skill 值校验 ---
    if ($data.permission -and $data.permission.skill -and $data.permission.skill -is [PSCustomObject]) {
        foreach ($skillId in $data.permission.skill.PSObject.Properties.Name) {
            $val = $data.permission.skill.$skillId
            if ($val -notin @('allow', 'deny')) {
                $fieldIssues += "permission.skill.$skillId 值不合法: $val（应为 allow 或 deny）"
                Write-Output "[问题][字段] permission.skill.$skillId 值不合法: $val（应为 allow 或 deny）"
            }
        }
    }

    if ($fieldIssues.Count -eq 0) {
        Write-Output "[通过][字段] 字段校验通过，无非法字段或值类型错误"
    }
} else {
    Write-Output "[跳过][字段] 格式有误，跳过字段检查"
}

# ========== 路径检查（仅格式通过时）==========
$pathIssues = @()

if ($formatOK) {
    if ($data.mcp -and $data.mcp -is [PSCustomObject]) {
        foreach ($name in $data.mcp.PSObject.Properties.Name) {
            $entry = $data.mcp.$name

            # 检查 command 路径
            if ($entry.command -is [System.Array]) {
                for ($j = 0; $j -lt $entry.command.Count; $j++) {
                    $cmdPart = $entry.command[$j]
                    $looksLikePath = ($cmdPart -match '\\') -or ($cmdPart -match '^[A-Za-z]:') -or ($cmdPart -match '^/') -or ($cmdPart -match '\.(js|py|ts|exe|cmd|sh)$')
                    if ($looksLikePath) {
                        $expanded = [System.Environment]::ExpandEnvironmentVariables($cmdPart)
                        if (-not (Test-Path $expanded)) {
                            $pathIssues += "mcp.$name command[$j]: $expanded"
                            Write-Output "[问题][路径] mcp.$name | command[$j] | 路径不存在: $expanded"
                        }
                    }
                }
            }

            # 检查 environment.PATH 目录
            if ($entry.environment -and $entry.environment.PATH) {
                $envParts = $entry.environment.PATH -split ';' | Where-Object { $_ -and $_ -notmatch '^\$\{' }
                foreach ($p in $envParts) {
                    $expandedP = [System.Environment]::ExpandEnvironmentVariables($p)
                    if (-not (Test-Path $expandedP -PathType Container)) {
                        $pathIssues += "mcp.$name environment.PATH: $expandedP"
                        Write-Output "[问题][路径] mcp.$name | environment.PATH | 目录不存在: $expandedP"
                    }
                }
            }
        }
    }

    if ($pathIssues.Count -eq 0) {
        Write-Output "[通过][路径] 路径校验通过，所有路径存在"
    }
} else {
    Write-Output "[跳过][路径] 格式有误，跳过路径检查"
}

# ========== 输出汇总 ==========
Write-Output ""
Write-Output "========== 诊断汇总 =========="

$formatProblems = 0
if ($hasBOM) { $formatProblems++ }
if ($controlCharFound) { $formatProblems++ }
if ($fullwidthFound) { $formatProblems++ }
$formatProblems += $trailingCommas.Count + $doubleCommas.Count + $bracketIssues.Count
if (-not $formatOK) { $formatProblems++ }

if ($formatProblems -eq 0 -and $fieldIssues.Count -eq 0 -and $pathIssues.Count -eq 0) {
    Write-Output "[通过] 配置文件检查全部通过，无任何问题"
} else {
    $suggestions = @()
    if ($hasBOM) { $suggestions += "移除 UTF-8 BOM" }
    if ($controlCharFound) { $suggestions += "清除控制字符" }
    if ($fullwidthFound) { $suggestions += "替换全角符号" }
    if ($trailingCommas.Count -gt 0) { $suggestions += "移除尾逗号" }
    if ($doubleCommas.Count -gt 0) { $suggestions += "修复连续逗号" }
    if ($bracketIssues.Count -gt 0) { $suggestions += "修复括号匹配" }
    if (-not $formatOK) { $suggestions += "修复 JSON 语法" }
    if ($fieldIssues.Count -gt 0) { $suggestions += "修正字段问题" }
    if ($suggestions.Count -gt 0) {
        Write-Output "[建议] 修复方案: $($suggestions -join ' + ')"
        Write-Output "[自动修复] 可通过 fix-teleagent-jsonc 脚本自动修复"
    }
    if ($pathIssues.Count -gt 0) {
        Write-Output "[建议] 路径问题需通过 mcp-check-paths / mcp-fix-paths 脚本单独处理"
    }
}
