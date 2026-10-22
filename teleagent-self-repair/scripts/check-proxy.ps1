#requires -version 5.1
# ============================================================
# TeleAgent 代理环境诊断脚本 (Windows PowerShell 5.1+)
# ============================================================
# 功能：基础网络排除 + 代理环境检测 + 目标URL连通性 + TeleAgent 云端存活自检
# 用法：
#   .\check-proxy.ps1                      # 完整诊断（只读，输出 JSON）
#   .\check-proxy.ps1 -HealthCheck         # 仅 TeleAgent 云端存活自检（启动代理后自检用）
#   .\check-proxy.ps1 -TargetUrl <url>     # 附加目标 URL 直连/带代理对比
# 输出：JSON 格式诊断结果，供 Agent 解析判断
# ============================================================

param(
    [switch]$HealthCheck,
    [string]$TargetUrl = ""
)

$ErrorActionPreference = "SilentlyContinue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# --- TeleAgent 云端接入点（实测国内云） ---
$CloudHost = "150.223.245.6"
$CloudPort = 443

# --- TCP 连通测试（带超时） ---
function Test-TcpOk {
    param([string]$HostName, [int]$Port, [int]$TimeoutMs = 8000)
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $task = $client.ConnectAsync($HostName, $Port)
        if ($task.Wait($TimeoutMs) -and $client.Connected) {
            $client.Close()
            return $true
        }
        $client.Close()
        return $false
    } catch {
        return $false
    }
}

# --- TeleAgent 云端存活自检 ---
$cloudOk = Test-TcpOk -HostName $CloudHost -Port $CloudPort -TimeoutMs 8000

if ($HealthCheck) {
    $hcResult = @{
        status = if ($cloudOk) { "ok" } else { "failed" }
        cloud_ok = $cloudOk
        cloud_host = $CloudHost
        cloud_port = $CloudPort
    }
    $hcResult | ConvertTo-Json -Depth 3
    exit 0
}

# --- 基础网络层 ---
$adapterUp = $false
try {
    $upAdapters = Get-NetAdapter | Where-Object { $_.Status -eq "Up" }
    if ($upAdapters) { $adapterUp = $true }
} catch {}

$dnsOk = $false
try {
    $dnsResult = Resolve-DnsName -Name "www.microsoft.com" -Type A -ErrorAction SilentlyContinue
    if ($dnsResult) { $dnsOk = $true }
} catch {}

$internetOk = $cloudOk

# --- 系统代理（注册表） ---
$sysProxyEnabled = $false
$sysProxyServer = ""
try {
    $regInternet = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings"
    $regItem = Get-ItemProperty -Path $regInternet -ErrorAction SilentlyContinue
    if ($regItem.ProxyEnable -eq 1) { $sysProxyEnabled = $true }
    $sysProxyServer = [string]$regItem.ProxyServer
} catch {}

# --- 环境变量代理 ---
$envHttp = [string]$env:HTTP_PROXY
$envHttps = [string]$env:HTTPS_PROXY
$envAll = [string]$env:ALL_PROXY
$envNo = [string]$env:NO_PROXY
$envProxySet = ($envHttp -ne "" -or $envHttps -ne "" -or $envAll -ne "")

# NO_PROXY 为空也应视为缺失（否则开代理后 localhost/127.0.0.1 可能被塞进代理卡住）
$noProxyOk = $true
$noLower = $envNo.ToLower()
if (($noLower -notmatch "localhost") -or ($noLower -notmatch "127.0.0.1")) {
    $noProxyOk = $false
}

# 用户级 / 机器级持久化代理变量
$persistentHttpProxy = ""
try {
    $userEnv = Get-ItemProperty -Path "HKCU:\Environment" -ErrorAction SilentlyContinue
    $machineEnv = Get-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" -ErrorAction SilentlyContinue
    $userHttp = [string]$userEnv.HTTP_PROXY
    $machineHttp = [string]$machineEnv.HTTP_PROXY
    if ($userHttp -ne "") { $persistentHttpProxy = $userHttp }
    elseif ($machineHttp -ne "") { $persistentHttpProxy = $machineHttp }
} catch {}

# --- 代理软件 ---
$ProxyAppRegex = "clash|verge|mihomo|v2ray|xray|surge|sing-box|shadowsocks"
$proxyApps = @()
$proxyApps = @(Get-Process -ErrorAction SilentlyContinue |
    Where-Object { $_.ProcessName -match $ProxyAppRegex } |
    Select-Object -ExpandProperty ProcessName -Unique)

# --- 代理端口监听（归属验证） ---
# 仅当监听者是代理进程时才算代理端口，避免 8080 等通用端口被 TeleAgent node 等非代理程序占用时误报；
# 在监听但监听者非代理进程的端口记入 suspect，仅供人工参考，不参与任何判定
$listeningPorts = @()
$suspectPorts = @()
try {
    $commonPorts = @(7890, 7897, 1080, 2080, 8080, 8888)
    $listenConns = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue)
    foreach ($p in $commonPorts) {
        $hitConns = @($listenConns | Where-Object { $_.LocalPort -eq $p })
        if ($hitConns.Count -eq 0) { continue }
        $ownerProc = Get-Process -Id $hitConns[0].OwningProcess -ErrorAction SilentlyContinue
        if ($ownerProc -and $ownerProc.ProcessName -match $ProxyAppRegex) {
            $listeningPorts += $p
        } else {
            $suspectPorts += $p
        }
    }
} catch {}

# --- TUN / 虚拟网卡接管（归属验证） ---
# wintun/tap/wireguard 是通用驱动名（企业 VPN 如 CorpLink、OpenVPN 均使用），不能作为代理 TUN 判定依据；
# 仅当网卡名匹配代理软件名（mihomo/clash/verge 等）才算代理 TUN，仅匹配通用驱动的记入 tun_suspect 仅提示
$tunActive = $false
$tunSuspects = @()
try {
    $allAdapters = @(Get-NetAdapter -ErrorAction SilentlyContinue)
    $tunAdapters = @($allAdapters | Where-Object { $_.Name -match "mihomo|clash|verge|sing-box|stash" })
    if ($tunAdapters.Count -gt 0) { $tunActive = $true }
    $driverOnly = @($allAdapters | Where-Object { $_.Name -match "wintun|tap|wireguard|tun" -and $_.Name -notmatch "mihomo|clash|verge|sing-box|stash" })
    if ($driverOnly.Count -gt 0) { $tunSuspects = @($driverOnly | Select-Object -ExpandProperty Name -Unique) }
} catch {}

# --- 目标 URL 连通性 ---
# proxy_ok = 真实经代理端口请求目标 URL：收到任意 HTTP 响应（含 403 风控码）即链路可用；
# 连接失败/超时为不可用；无真实代理端口（listening 为空）时直接为 false
$targetInfo = @{ url = $TargetUrl; direct_ok = $null; proxy_ok = $null; proxy_test_port = $null }
if ($TargetUrl -ne "") {
    try {
        $uriObj = New-Object System.Uri $TargetUrl
        $hostPart = $uriObj.Host
        $targetInfo.direct_ok = Test-TcpOk -HostName $hostPart -Port 443 -TimeoutMs 6000
        $targetInfo.proxy_ok = $false
        foreach ($p in $listeningPorts) {
            try {
                $null = Invoke-WebRequest -Uri $TargetUrl -Proxy "http://127.0.0.1:$p" -UseBasicParsing -TimeoutSec 10 -ErrorAction Stop
                $targetInfo.proxy_ok = $true
                $targetInfo.proxy_test_port = $p
                break
            } catch {
                # WebException 有 Response 说明代理链路已连通（403/407 等状态码也抛异常但带响应）
                if ($_.Exception.Response) {
                    $targetInfo.proxy_ok = $true
                    $targetInfo.proxy_test_port = $p
                    break
                }
            }
        }
    } catch {
        $targetInfo.direct_ok = $false
        $targetInfo.proxy_ok = $false
    }
}

# --- 汇总问题 ---
$issues = @()
$status = "normal"

if (-not $cloudOk) {
    $issues += @{ code = "CLOUD_UNREACHABLE"; severity = "failed"; detail = "TeleAgent cloud endpoint unreachable" }
    $status = "failed"
}
if ($envProxySet -and -not $noProxyOk) {
    $issues += @{ code = "NO_PROXY_MISSING_LOCAL"; severity = "warning"; detail = "env proxy set but NO_PROXY missing localhost/127.0.0.1" }
    if ($status -ne "failed") { $status = "warning" }
}
if ($persistentHttpProxy -ne "" -and -not $noProxyOk) {
    $issues += @{ code = "PERSISTENT_NO_PROXY_MISSING"; severity = "warning"; detail = "persistent HTTP_PROXY without NO_PROXY (risk after TeleAgent restart)" }
    if ($status -ne "failed") { $status = "warning" }
}
if ($sysProxyEnabled -and $proxyApps.Count -eq 0 -and $listeningPorts.Count -eq 0) {
    $issues += @{ code = "SYSTEM_PROXY_STALE"; severity = "warning"; detail = "system proxy enabled but no proxy software/port active (stale)" }
    if ($status -ne "failed") { $status = "warning" }
}
if ($tunActive) {
    $issues += @{ code = "TUN_ACTIVE"; severity = "warning"; detail = "TUN adapter active; may intercept TeleAgent traffic" }
    if ($status -ne "failed") { $status = "warning" }
}
if (-not $adapterUp) {
    $issues += @{ code = "NO_UP_ADAPTER"; severity = "warning"; detail = "no network adapter in Up state" }
    if ($status -ne "failed") { $status = "warning" }
}
if (-not $dnsOk) {
    $issues += @{ code = "DNS_FAIL"; severity = "warning"; detail = "DNS resolution failed" }
    if ($status -ne "failed") { $status = "warning" }
}

$result = @{
    status = $status
    base_network = @{ adapter_up = $adapterUp; dns_ok = $dnsOk; internet_ok = $internetOk }
    system_proxy = @{ enabled = $sysProxyEnabled; server = $sysProxyServer }
    env_proxy = @{ http_proxy = $envHttp; https_proxy = $envHttps; all_proxy = $envAll; no_proxy = $envNo; no_proxy_ok = $noProxyOk; persistent_http_proxy = $persistentHttpProxy }
    proxy_app = @{ running = ($proxyApps.Count -gt 0); names = @($proxyApps) }
    proxy_port = @{ listening = @($listeningPorts); suspect = @($suspectPorts) }
    tun_active = $tunActive
    tun_suspect = @($tunSuspects)
    cloud_health = $cloudOk
    target_url = $targetInfo
    issues = $issues
}
$result | ConvertTo-Json -Depth 6