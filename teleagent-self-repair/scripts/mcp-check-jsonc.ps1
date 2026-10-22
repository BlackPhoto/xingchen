#requires -version 5.1
# ============================================================
# MCP JSONC 格式诊断脚本 (Windows PowerShell 5.1+)
# ============================================================
# 功能：定位配置文件 → 检测编码/格式错误 → 输出诊断结果
# 用法：.\mcp-check-jsonc.ps1
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

# --- Step 2: 检测 UTF-8 BOM ---
$bytes = [System.IO.File]::ReadAllBytes($jsoncFile)
$hasBOM = ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)

if ($hasBOM) {
    Write-Output "[问题] UTF-8 BOM: 文件前3字节为 EF BB BF"
}

# --- Step 3: 读取文本内容 ---
$content = [System.IO.File]::ReadAllText($jsoncFile, [System.Text.Encoding]::UTF8)

# --- Step 4: 检测控制字符（除 \t \n \r 外的 0x00-0x1F）---
$lines = $content -split "`n"
$controlCharFound = $false
for ($ln = 0; $ln -lt $lines.Length; $ln++) {
    $line = $lines[$ln]
    for ($ci = 0; $ci -lt $line.Length; $ci++) {
        $code = [int]$line[$ci]
        if (($code -ge 0x00 -and $code -le 0x08) -or $code -eq 0x0B -or $code -eq 0x0C -or ($code -ge 0x0E -and $code -le 0x1F)) {
            if (-not $controlCharFound) {
                Write-Output "[问题] 控制字符: 文件包含不可见控制字符"
                $controlCharFound = $true
            }
            Write-Output ("  第 " + ($ln + 1) + " 行第 " + ($ci + 1) + " 列: 0x" + $code.ToString("X2"))
        }
    }
}

# --- Step 5: 检测全角符号 ---
$fullwidthMap = @{
    [char]0xFF0C = ','
    [char]0xFF1A = ':'
    [char]0x201C = '"'
    [char]0x201D = '"'
    [char]0xFF08 = '('
    [char]0xFF09 = ')'
    [char]0xFF3B = '['
    [char]0xFF3D = ']'
    [char]0xFF5B = '{'
    [char]0xFF5D = '}'
    [char]0xFF1B = ';'
}

$fullwidthFound = $false
for ($ln = 0; $ln -lt $lines.Length; $ln++) {
    $line = $lines[$ln]
    for ($ci = 0; $ci -lt $line.Length; $ci++) {
        $c = $line[$ci]
        if ($fullwidthMap.ContainsKey($c)) {
            if (-not $fullwidthFound) {
                Write-Output "[问题] 全角符号: 文件包含全角符号混入"
                $fullwidthFound = $true
            }
            $hw = $fullwidthMap[$c]
            Write-Output ("  第 " + ($ln + 1) + " 行第 " + ($ci + 1) + " 列: $c -> $hw")
        }
    }
}

# --- Step 6: 剥离 JSONC 注释（位置保持：注释替换为空格，换行保留）---
# 用于后续结构检测和 JSON 解析，位置与原文件一一对应
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
                # 单行注释：替换为空格直到行尾
                while ($i -lt $Text.Length -and $Text[$i] -ne "`n") {
                    $result[$i] = ' '
                    $i++
                }
            }
            elseif ($nxt -eq '*') {
                # 多行注释：替换为空格，保留换行
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
                    if ($Text[$i] -ne "`n") {
                        $result[$i] = ' '
                    }
                    $i++
                }
            }
            else {
                $i++
            }
        }
        else {
            $i++
        }
    }

    return -join $result
}

$stripped = Strip-JsoncPreservePosition $content

# --- Step 7: 检测尾逗号（字符串外，逗号后紧跟 } 或 ]）---
$trailingCommas = @()
. {
    $inStr = $false
    $esc = $false
    $lineNum = 1
    $colNum = 1

    for ($i = 0; $i -lt $stripped.Length; $i++) {
        $c = $stripped[$i]

        if ($inStr) {
            if ($esc) { $esc = $false }
            elseif ($c -eq '\') { $esc = $true }
            elseif ($c -eq '"') { $inStr = $false }
        }
        else {
            if ($c -eq '"') { $inStr = $true }
            elseif ($c -eq ',') {
                # 向后跳过空白，检查是否紧跟 } 或 ]
                $j = $i + 1
                while ($j -lt $stripped.Length -and [char]::IsWhiteSpace($stripped[$j])) { $j++ }
                if ($j -lt $stripped.Length -and ($stripped[$j] -eq '}' -or $stripped[$j] -eq ']')) {
                    $trailingCommas += @{ Line = $lineNum; Col = $colNum }
                }
            }
        }

        if ($c -eq "`n") { $lineNum++; $colNum = 1 } else { $colNum++ }
    }
}

if ($trailingCommas.Count -gt 0) {
    Write-Output "[问题] 尾逗号: 发现 $($trailingCommas.Count) 处尾逗号"
    foreach ($tc in $trailingCommas) {
        Write-Output "  第 $($tc.Line) 行第 $($tc.Col) 列"
    }
}

# --- Step 8: 检测连续逗号（字符串外）---
$doubleCommas = @()
. {
    $inStr = $false
    $esc = $false
    $prevCommaLine = 0
    $prevCommaCol = 0
    $prevComma = $false
    $lineNum = 1
    $colNum = 1

    for ($i = 0; $i -lt $stripped.Length; $i++) {
        $c = $stripped[$i]

        if ($inStr) {
            if ($esc) { $esc = $false }
            elseif ($c -eq '\') { $esc = $true }
            elseif ($c -eq '"') { $inStr = $false }
            $prevComma = $false
        }
        else {
            if ($c -eq '"') { $inStr = $true; $prevComma = $false }
            elseif ($c -eq ',') {
                if ($prevComma) {
                    $doubleCommas += @{ Line = $prevCommaLine; Col = $prevCommaCol }
                }
                $prevComma = $true
                $prevCommaLine = $lineNum
                $prevCommaCol = $colNum
            }
            elseif (-not [char]::IsWhiteSpace($c)) {
                $prevComma = $false
            }
        }

        if ($c -eq "`n") { $lineNum++; $colNum = 1 } else { $colNum++ }
    }
}

if ($doubleCommas.Count -gt 0) {
    Write-Output "[问题] 连续逗号: 发现 $($doubleCommas.Count) 处连续逗号"
    foreach ($dc in $doubleCommas) {
        Write-Output "  第 $($dc.Line) 行第 $($dc.Col) 列"
    }
}

# --- Step 9: 检测括号不匹配（字符串外）---
$bracketIssues = @()
. {
    $stack = @()
    $inStr = $false
    $esc = $false
    $lineNum = 1
    $colNum = 1

    for ($i = 0; $i -lt $stripped.Length; $i++) {
        $c = $stripped[$i]

        if ($inStr) {
            if ($esc) { $esc = $false }
            elseif ($c -eq '\') { $esc = $true }
            elseif ($c -eq '"') { $inStr = $false }
        }
        else {
            if ($c -eq '"') { $inStr = $true }
            elseif ($c -eq '{' -or $c -eq '[') {
                $stack += @{ Char = $c; Line = $lineNum; Col = $colNum }
            }
            elseif ($c -eq '}' -or $c -eq ']') {
                if ($stack.Count -eq 0) {
                    $bracketIssues += @{ Type = "多余闭合"; Char = $c; Line = $lineNum; Col = $colNum }
                }
                else {
                    $top = $stack[$stack.Count - 1]
                    $expected = if ($c -eq '}') { '{' } else { '[' }
                    if ($top.Char -eq $expected) {
                        if ($stack.Count -le 1) {
                            $stack = @()
                        } else {
                            $stack = $stack[0..($stack.Count - 2)]
                        }
                    }
                    else {
                        $bracketIssues += @{ Type = "类型不匹配"; Char = $c; Expected = $expected; Found = $top.Char; Line = $lineNum; Col = $colNum }
                    }
                }
            }
        }

        if ($c -eq "`n") { $lineNum++; $colNum = 1 } else { $colNum++ }
    }

    # 栈中剩余的是缺少闭合的括号
    foreach ($s in $stack) {
        $close = if ($s.Char -eq '{') { '}' } else { ']' }
        $bracketIssues += @{ Type = "缺少闭合"; Char = $close; Line = $s.Line; Col = $s.Col }
    }
}

if ($bracketIssues.Count -gt 0) {
    $missing = @($bracketIssues | Where-Object { $_.Type -eq "缺少闭合" }).Count
    $extra = @($bracketIssues | Where-Object { $_.Type -eq "多余闭合" }).Count
    $mismatch = @($bracketIssues | Where-Object { $_.Type -eq "类型不匹配" }).Count
    Write-Output "[问题] 括号不匹配: 缺少闭合 $missing 处, 多余闭合 $extra 处, 类型不匹配 $mismatch 处"
    foreach ($bi in $bracketIssues) {
        if ($bi.Type -eq "缺少闭合") {
            Write-Output "  第 $($bi.Line) 行: 缺少闭合 $($bi.Char)"
        }
        elseif ($bi.Type -eq "多余闭合") {
            Write-Output "  第 $($bi.Line) 行第 $($bi.Col) 列: 多余闭合 $($bi.Char)"
        }
        else {
            Write-Output "  第 $($bi.Line) 行第 $($bi.Col) 列: 期望 $($bi.Expected)，实际 $($bi.Found)"
        }
    }
}

# --- Step 10: 检测未闭合的多行注释（在原始内容上检测）---
. {
    $inStr = $false
    $esc = $false
    $inBlock = $false
    $blockStartLine = 0
    $lineNum = 1

    for ($i = 0; $i -lt $content.Length; $i++) {
        $c = $content[$i]

        if ($c -eq "`n") { $lineNum++; continue }

        if ($inStr) {
            if ($esc) { $esc = $false }
            elseif ($c -eq '\') { $esc = $true }
            elseif ($c -eq '"') { $inStr = $false }
        }
        elseif ($inBlock) {
            if ($c -eq '*' -and ($i + 1) -lt $content.Length -and $content[$i + 1] -eq '/') {
                $inBlock = $false
                $i++
            }
        }
        else {
            if ($c -eq '"') { $inStr = $true }
            elseif ($c -eq '/' -and ($i + 1) -lt $content.Length) {
                if ($content[$i + 1] -eq '*') {
                    $inBlock = $true
                    $blockStartLine = $lineNum
                    $i++
                }
                elseif ($content[$i + 1] -eq '/') {
                    # 跳过单行注释
                    while ($i -lt $content.Length -and $content[$i] -ne "`n") { $i++ }
                }
            }
        }
    }

    if ($inBlock) {
        Write-Output "[问题] 未闭合注释: 第 $blockStartLine 行存在未闭合的 /* 注释"
    }
}

# --- Step 11: 尝试 JSON 解析 ---
# 用剥离注释后的内容尝试解析
try {
    $null = $stripped | ConvertFrom-Json -ErrorAction Stop
    Write-Output "[通过] JSON 格式校验通过"
}
catch {
    $parseError = $_.Exception.Message
    Write-Output "[问题] JSON解析失败: $parseError"

    # 尝试使用 node 获取更精确的错误信息
    $nodeExe = (Get-Command node -ErrorAction SilentlyContinue).Source
    if ($nodeExe) {
        try {
            $tmpFile = [System.IO.Path]::GetTempFileName()
            [System.IO.File]::WriteAllText($tmpFile, $stripped, [System.Text.Encoding]::UTF8)
            $nodeResult = & node -e "try{JSON.parse(require('fs').readFileSync(process.argv[1],'utf8'));console.log('OK')}catch(e){console.error(e.message)}" $tmpFile 2>&1
            Remove-Item $tmpFile -Force -ErrorAction SilentlyContinue
            if ($nodeResult -ne "OK" -and $nodeResult) {
                Write-Output "  [详细] Node.js: $nodeResult"
            }
        }
        catch { }
    }

    # 尝试使用 python 获取更精确的错误信息
    $pyExe = $null
    if (Get-Command python3 -ErrorAction SilentlyContinue) { $pyExe = (Get-Command python3 -ErrorAction SilentlyContinue).Source }
    elseif (Get-Command python -ErrorAction SilentlyContinue) { $pyExe = (Get-Command python -ErrorAction SilentlyContinue).Source }
    if ($pyExe) {
        try {
            $tmpFile = [System.IO.Path]::GetTempFileName()
            [System.IO.File]::WriteAllText($tmpFile, $stripped, [System.Text.Encoding]::UTF8)
            $pyResult = & $pyExe -c "import json,sys; json.loads(open(sys.argv[1],encoding='utf-8').read())" $tmpFile 2>&1
            Remove-Item $tmpFile -Force -ErrorAction SilentlyContinue
            if ($pyResult) {
                Write-Output "  [详细] Python: $pyResult"
            }
        }
        catch { }
    }
}

# --- Step 12: 输出修复建议 ---
$suggestions = @()
if ($hasBOM) { $suggestions += "移除 UTF-8 BOM" }
if ($controlCharFound) { $suggestions += "清除控制字符" }
if ($fullwidthFound) { $suggestions += "替换全角符号" }
if ($trailingCommas.Count -gt 0) { $suggestions += "移除尾逗号" }
if ($doubleCommas.Count -gt 0) { $suggestions += "修复连续逗号" }
if ($bracketIssues.Count -gt 0) { $suggestions += "修复括号匹配" }

if ($suggestions.Count -gt 0) {
    Write-Output "[建议] 修复方案: $($suggestions -join ' + ')"
    Write-Output "[自动修复] 可自动修复"
}
else {
    Write-Output "[通过] 未检测到 JSONC 格式问题"
}
