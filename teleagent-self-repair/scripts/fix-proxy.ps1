#requires -version 5.1
# ============================================================
# TeleAgent 代理操作脚本 (Windows PowerShell 5.1+)
# ============================================================
# 功能：代理协助操作（启动/修复/回滚/清理/补NO_PROXY）
# 用法：
#   .\fix-proxy.ps1 -Action assist        # 启动代理软件并等待端口（写快照）
#   .\fix-proxy.ps1 -Action repair        # 尽力修复接管方式（关TUN/切规则，无API则no_action）
#   .\fix-proxy.ps1 -Action rollback      # 按快照回滚（关代理/还原系统代理）
#   .\fix-proxy.ps1 -Action cleanup       # 清理系统代理残留（ProxyEnable 置 0）
#   .\fix-proxy.ps1 -Action fix-noproxy   # 补全 NO_PROXY（追加 localhost,127.0.0.1）
# 输出：JSON 格式结果，供 Agent 解析判断
# ============================================================

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("assist", "repair", "rollback", "cleanup", "fix-noproxy")]
    [string]$Action
)

$ErrorActionPreference = "SilentlyContinue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$SnapshotFile = Join-Path $env:TEMP "teleagent-proxy-snapshot.json"
$CommonPorts = @(7890, 7897, 1080, 2080, 8080, 8888)
$ProxyAppRegex = "clash|verge|mihomo|v2ray|xray|surge|sing-box|shadowsocks"

function Get-RunningProxyPids {
    return @(Get-Process -ErrorAction SilentlyContinue |
        Where-Object { $_.ProcessName -match $ProxyAppRegex } |
        Select-Object -ExpandProperty Id)
}

function Get-ProxyExe {
    # 通用探测链：固定路径 → 运行中代理服务进程路径推导 → 注册表卸载信息 → 开始菜单快捷方式 → LOCALAPPDATA 递归
    # 覆盖任意盘符/自定义安装位置（如 E:\clash）
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\clash-verge\clash-verge.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Clash Verge\clash-verge.exe"),
        (Join-Path ${env:ProgramFiles} "Clash Verge\clash-verge.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\clash\clash.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\mihomo\mihomo.exe")
    )
    foreach ($c in $candidates) {
        if ($c -and (Test-Path $c)) { return $c }
    }
    # ② 运行中的代理服务进程路径推导（如 clash-verge-service 在 <安装目录>\resources\ → 逐级向上找主程序）
    try {
        $svcProcs = @(Get-CimInstance Win32_Process -Filter "Name LIKE '%clash%' OR Name LIKE '%verge%' OR Name LIKE '%mihomo%'" -ErrorAction SilentlyContinue)
        foreach ($sp in $svcProcs) {
            $exePath = [string]$sp.ExecutablePath
            if (-not $exePath) { continue }
            $dir = Split-Path -Parent $exePath
            for ($i = 0; $i -lt 3; $i++) {
                foreach ($name in @("clash-verge.exe", "verge-mihomo.exe", "mihomo.exe", "clash.exe")) {
                    $guess = Join-Path $dir $name
                    if (Test-Path -LiteralPath $guess) { return $guess }
                }
                $parent = Split-Path -Parent $dir
                if ($parent -eq $dir) { break }
                $dir = $parent
            }
        }
    } catch {}
    # ③ 注册表卸载信息（DisplayName 匹配 → InstallLocation）
    try {
        $uninstPaths = @(
            "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
            "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*",
            "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*"
        )
        foreach ($up in $uninstPaths) {
            $apps = @(Get-ItemProperty -Path $up -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -match "clash|verge|mihomo" })
            foreach ($app in $apps) {
                if ($app.InstallLocation) {
                    foreach ($name in @("clash-verge.exe", "clash.exe", "mihomo.exe")) {
                        $guess = Join-Path $app.InstallLocation $name
                        if (Test-Path -LiteralPath $guess) { return $guess }
                    }
                }
            }
        }
    } catch {}
    # ④ 开始菜单快捷方式解析
    try {
        $lnkDirs = @(
            (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"),
            (Join-Path $env:ProgramData "Microsoft\Windows\Start Menu\Programs")
        )
        $sh = New-Object -ComObject WScript.Shell
        foreach ($ld in $lnkDirs) {
            $lnks = @(Get-ChildItem -Path $ld -Filter "*.lnk" -Recurse -Depth 2 -ErrorAction SilentlyContinue | Where-Object { $_.Name -match "clash|verge|mihomo" })
            foreach ($lnk in $lnks) {
                $target = $sh.CreateShortcut($lnk.FullName).TargetPath
                if ($target -and (Test-Path -LiteralPath $target)) { return $target }
            }
        }
    } catch {}
    # ⑤ LOCALAPPDATA 递归兜底
    $base = Join-Path $env:LOCALAPPDATA "Programs"
    if (Test-Path $base) {
        $hit = Get-ChildItem -Path $base -Recurse -Filter "*.exe" -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match $ProxyAppRegex } |
            Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    return $null
}

function Get-SystemProxyState {
    $path = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
    $item = Get-ItemProperty -Path $path -ErrorAction SilentlyContinue
    return @{
        enabled = ($item.ProxyEnable -eq 1)
        server = [string]$item.ProxyServer
    }
}

function Set-SystemProxy {
    param([bool]$Enabled, [string]$Server = "")
    $path = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
    if ($Enabled) {
        Set-ItemProperty -Path $path -Name ProxyEnable -Value 1
        if ($Server -ne "") { Set-ItemProperty -Path $path -Name ProxyServer -Value $Server }
    } else {
        Set-ItemProperty -Path $path -Name ProxyEnable -Value 0
    }
}

function Test-PortListening {
    param([int]$Port)
    $n = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return ($null -ne $n)
}

function Get-ListeningProxyPorts {
    # 归属验证：仅当监听者是代理进程时才算代理端口，
    # 避免 8080 等通用端口被 TeleAgent node 等非代理程序占用时误判（assist 假就绪 / cleanup 永不清理）
    $result = @()
    try {
        $conns = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue)
        foreach ($p in $CommonPorts) {
            $hitConns = @($conns | Where-Object { $_.LocalPort -eq $p })
            if ($hitConns.Count -eq 0) { continue }
            $ownerProc = Get-Process -Id $hitConns[0].OwningProcess -ErrorAction SilentlyContinue
            if ($ownerProc -and $ownerProc.ProcessName -match $ProxyAppRegex) { $result += $p }
        }
    } catch {}
    return $result
}

function Write-Snapshot {
    param([object]$Data)
    $Data | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $SnapshotFile -Encoding UTF8
}

# ============================================================
# Action: assist —— 启动代理软件并等待端口，写回滚快照
# ============================================================
if ($Action -eq "assist") {
    # 判定语义（防"仅服务进程在跑"的假就绪/假成功）：
    #   "代理已运行"的唯一标准 = 代理端口有监听（归属验证过）。
    #   后台服务进程（如 clash-verge-service）不提供代理端口，
    #   仅有服务/辅助进程时仍需启动主程序，不视为已运行。
    $existingPids = @(Get-RunningProxyPids)
    $beforePorts = @(Get-ListeningProxyPorts)
    $sysBefore = Get-SystemProxyState

    $startedPids = @()
    $exe = $null
    $alreadyRunning = ($beforePorts.Count -gt 0)

    if (-not $alreadyRunning) {
        $exe = Get-ProxyExe
        if ($exe) {
            try {
                $proc = Start-Process -FilePath $exe -WindowStyle Hidden -PassThru -ErrorAction SilentlyContinue
                if ($proc) { $startedPids += $proc.Id }
            } catch {}
        }
    }

    # 等待常见代理端口监听（最多 30s）
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        $ports = @(Get-ListeningProxyPorts)
        if ($ports.Count -gt 0) { $ready = $true; break }
    }

    # 写入回滚快照
    $snapshot = @{
        created = (Get-Date).ToString("o")
        started_pids = $startedPids
        sys_proxy_before = $sysBefore
    }
    Write-Snapshot $snapshot

    $finalPids = @(Get-RunningProxyPids)
    $finalPorts = @(Get-ListeningProxyPorts)

    # 状态判定：端口有监听才算 started（成功）；端口无监听一律 failed——
    # 即使有代理相关进程在跑（服务壳在跑但内核未起，代理同样不可用）。
    # 失败时区分原因，供 Agent 选择后续动作（探测不到主程序 → 提示用户准备代理软件）。
    if ($finalPorts.Count -gt 0) {
        $status = "started"
        if ($startedPids.Count -gt 0) { $detail = "proxy port ready (started by assist)" }
        elseif ($beforePorts.Count -gt 0) { $detail = "proxy port ready (already running)" }
        else { $detail = "proxy port ready" }
    } else {
        $status = "failed"
        if ($null -eq $exe -and $startedPids.Count -eq 0) { $detail = "proxy app not found; no port listening" }
        else { $detail = "no proxy port listening after assist" }
    }

    $out = @{
        action = "assist"
        status = $status
        detail = $detail
        already_running = $alreadyRunning
        started_pids = $startedPids
        running_pids = $finalPids
        listening_ports = $finalPorts
        proxy_exe = $exe
        snapshot = $SnapshotFile
    }
    $out | ConvertTo-Json -Depth 5
    exit 0
}

# ============================================================
# Action: repair —— 尝试修复接管方式（尽力而为，失败返回 no_action）
# ============================================================
if ($Action -eq "repair") {
    $result = @{ action = "repair"; success = $false; reason = "no_api" }
    $controllerPort = 9090
    # 归属验证：9090 也是其他服务常用端口，仅当监听者是代理进程时才尝试调用其 controller API
    $ctlOk = $false
    try {
        $ctlConn = Get-NetTCPConnection -LocalPort $controllerPort -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($ctlConn) {
            $ctlOwner = Get-Process -Id $ctlConn.OwningProcess -ErrorAction SilentlyContinue
            if ($ctlOwner -and $ctlOwner.ProcessName -match $ProxyAppRegex) { $ctlOk = $true }
        }
    } catch {}
    if ($ctlOk) {
        $secret = $null
        $configCandidates = @(
            (Join-Path $env:APPDATA "clash-verge\config.yaml"),
            (Join-Path $env:USERPROFILE ".config\mihomo\config.yaml"),
            (Join-Path $env:USERPROFILE ".config\clash\config.yaml")
        )
        foreach ($cf in $configCandidates) {
            if (Test-Path $cf) {
                $txt = Get-Content -LiteralPath $cf -Raw -ErrorAction SilentlyContinue
                if ($txt -match 'secret:\s*"?([^"\s]+)"?') { $secret = $Matches[1] }
                break
            }
        }
        try {
            $headers = @{}
            if ($secret) { $headers["Authorization"] = "Bearer $secret" }
            $body = '{"mode":"rule"}'
            $uri = "http://127.0.0.1:$controllerPort/configs"
            $resp = Invoke-WebRequest -Uri $uri -Method Patch -Headers $headers -ContentType "application/json" -Body $body -TimeoutSec 5 -ErrorAction SilentlyContinue
            if ($resp.StatusCode -in 200, 204) {
                $result = @{ action = "repair"; success = $true; reason = "switch_rule_mode" }
                $result | ConvertTo-Json -Depth 3
                exit 0
            }
        } catch {}
    }
    $result | ConvertTo-Json -Depth 3
    exit 0
}

# ============================================================
# Action: rollback —— 按快照回滚（终止启动的代理进程 + 还原系统代理）
# ============================================================
if ($Action -eq "rollback") {
    $snap = $null
    if (Test-Path $SnapshotFile) {
        try {
            $snap = Get-Content -LiteralPath $SnapshotFile -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json
        } catch {}
    }

    $terminatedPids = @()
    if ($snap -and $snap.started_pids) {
        foreach ($pidId in $snap.started_pids) {
            $p = Get-Process -Id $pidId -ErrorAction SilentlyContinue
            if ($p -and $p.ProcessName -match $ProxyAppRegex) {
                try {
                    Stop-Process -Id $pidId -Force -ErrorAction SilentlyContinue
                    $terminatedPids += $pidId
                } catch {}
            }
        }
    }

    if ($snap -and $snap.sys_proxy_before) {
        Set-SystemProxy -Enabled ([bool]$snap.sys_proxy_before.enabled) -Server ([string]$snap.sys_proxy_before.server)
    }

    $result = @{
        action = "rollback"
        status = "done"
        terminated_pids = $terminatedPids
        sys_proxy_restored = ($null -ne $snap)
    }
    $result | ConvertTo-Json -Depth 4
    exit 0
}

# ============================================================
# Action: cleanup —— 清理系统代理残留（仅当无代理进程/端口时置 0）
# ============================================================
if ($Action -eq "cleanup") {
    $sys = Get-SystemProxyState
    $runningPids = @(Get-RunningProxyPids)
    $ports = @(Get-ListeningProxyPorts)

    $changed = $false
    $detail = ""
    if ($sys.enabled -and $runningPids.Count -eq 0 -and $ports.Count -eq 0) {
        Set-SystemProxy -Enabled $false
        $changed = $true
        $detail = "system proxy stale; disabled"
    } elseif ($sys.enabled) {
        $detail = "system proxy enabled but proxy still active, not modified"
    } else {
        $detail = "system proxy already disabled"
    }

    $result = @{
        action = "cleanup"
        status = if ($changed) { "changed" } else { "no_change" }
        detail = $detail
        system_proxy_after = (Get-SystemProxyState).enabled
    }
    $result | ConvertTo-Json -Depth 4
    exit 0
}

# ============================================================
# Action: fix-noproxy —— 补全 NO_PROXY（追加 localhost,127.0.0.1）
# ============================================================
if ($Action -eq "fix-noproxy") {
    $persistPath = "HKCU:\Environment"
    $persistNoProxy = [string](Get-ItemProperty -Path $persistPath -Name NO_PROXY -ErrorAction SilentlyContinue).NO_PROXY
    $envNo = [string]$env:NO_PROXY

    $needLocal = ($persistNoProxy -notmatch "localhost")
    $needLoop = ($persistNoProxy -notmatch "127.0.0.1")
    $persistNo = $persistNoProxy

    $changed = $false
    if ($needLocal -or $needLoop) {
        $addParts = @()
        if ($needLocal) { $addParts += "localhost" }
        if ($needLoop) { $addParts += "127.0.0.1" }
        $persistNo = if ($persistNoProxy) { "$persistNoProxy,$($addParts -join ',')" } else { $addParts -join "," }
        Set-ItemProperty -Path $persistPath -Name NO_PROXY -Value $persistNo -ErrorAction SilentlyContinue
        $changed = $true
    }

    if ($envNo -notmatch "localhost" -or $envNo -notmatch "127.0.0.1") {
        $addParts = @()
        if ($envNo -notmatch "localhost") { $addParts += "localhost" }
        if ($envNo -notmatch "127.0.0.1") { $addParts += "127.0.0.1" }
        $env:NO_PROXY = if ($envNo) { "$envNo,$($addParts -join ',')" } else { $addParts -join "," }
        $changed = $true
    }

    $result = @{
        action = "fix-noproxy"
        changed = $changed
        persistent_no_proxy = $persistNo
        session_no_proxy = $env:NO_PROXY
    }
    $result | ConvertTo-Json -Depth 4
    exit 0
}