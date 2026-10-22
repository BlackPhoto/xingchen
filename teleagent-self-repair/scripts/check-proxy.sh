#!/usr/bin/env bash
# ============================================================
# TeleAgent 代理环境诊断脚本 (macOS / Linux, Bash)
# ============================================================
# 功能：基础网络排除 + 代理环境检测 + 目标URL连通性 + TeleAgent 云端存活自检
# 用法：
#   ./check-proxy.sh                      # 完整诊断（只读，输出 JSON）
#   ./check-proxy.sh -H                   # 仅 TeleAgent 云端存活自检
#   ./check-proxy.sh -u <url>            # 附加目标 URL 直连/带代理对比
# 输出：JSON 格式诊断结果，供 Agent 解析判断
# ============================================================

set -u
OS="$(uname -s)"

# --- TeleAgent 云端接入点（实测国内云） ---
CLOUD_HOST="150.223.245.6"
CLOUD_PORT=443

HEALTH=0
TARGET=""
while [ $# -gt 0 ]; do
  case "$1" in
    -H|--health) HEALTH=1 ;;
    -u|--target) TARGET="${2:-}"; shift ;;
    *) ;;
  esac
  shift
done

# --- TCP 连通测试（带超时） ---
tcp_ok() {
  local host="$1" port="$2" timeout="${3:-8}"
  if command -v nc >/dev/null 2>&1; then
    nc -z -w "$timeout" "$host" "$port" >/dev/null 2>&1 && return 0
  elif command -v curl >/dev/null 2>&1; then
    curl -s -o /dev/null --max-time "$timeout" --connect-timeout "$timeout" "http://$host:$port" >/dev/null 2>&1 && return 0
  fi
  if command -v timeout >/dev/null 2>&1; then
    timeout "$timeout" bash -c "exec 3<>/dev/tcp/$host/$port" >/dev/null 2>&1 && return 0
  else
    bash -c "exec 3<>/dev/tcp/$host/$port" >/dev/null 2>&1 && return 0
  fi
  return 1
}

# --- TeleAgent 云端存活自检 ---
cloud_ok=0
tcp_ok "$CLOUD_HOST" "$CLOUD_PORT" && cloud_ok=1

if [ "$HEALTH" -eq 1 ]; then
  status="$([ "$cloud_ok" -eq 1 ] && echo ok || echo failed)"
  if [ "$cloud_ok" -eq 1 ]; then c=true; else c=false; fi
  cat <<EOF
{"status":"$status","cloud_ok":$c,"cloud_host":"$CLOUD_HOST","cloud_port":$CLOUD_PORT}
EOF
  exit 0
fi

# --- 基础网络层 ---
adapter_up=0
if [ "$OS" = "Darwin" ]; then
  command -v ifconfig >/dev/null 2>&1 && ifconfig 2>/dev/null | grep -qi "status: active" && adapter_up=1
else
  command -v ip >/dev/null 2>&1 && ip -o link show 2>/dev/null | grep -qi "state UP" && adapter_up=1
fi

dns_ok=0
if command -v getent >/dev/null 2>&1; then
  getent hosts www.microsoft.com >/dev/null 2>&1 && dns_ok=1
elif command -v dig >/dev/null 2>&1; then
  dig +short www.microsoft.com >/dev/null 2>&1 && dns_ok=1
fi

internet_ok=$cloud_ok

# --- 系统代理 ---
sys_proxy_enabled="false"
sys_proxy_server=""
if [ "$OS" = "Darwin" ] && command -v networksetup >/dev/null 2>&1; then
  # 尽力检测活动服务（常见服务名）
  for svc in "Wi-Fi" "Ethernet" "USB 10/100/1000 LAN" "Thunderbolt Bridge"; do
    state=$(networksetup -getwebproxy "$svc" 2>/dev/null)
    if [ -n "$state" ]; then
      if echo "$state" | grep -qi "Enabled: Yes"; then
        sys_proxy_enabled="true"
        sys_proxy_server=$(echo "$state" | awk -F': ' '/Server/{print $2}')
      fi
      break
    fi
  done
elif command -v gsettings >/dev/null 2>&1; then
  mode=$(gsettings get org.gnome.system.proxy mode 2>/dev/null | tr -d "'")
  [ "$mode" = "manual" ] && sys_proxy_enabled="true"
  host=$(gsettings get org.gnome.system.proxy.http host 2>/dev/null | tr -d "'")
  [ -n "$host" ] && sys_proxy_server="$host"
fi

# --- 环境变量代理 ---
env_http="${HTTP_PROXY:-}"
env_https="${HTTPS_PROXY:-}"
env_all="${ALL_PROXY:-}"
env_no="${NO_PROXY:-}"
env_proxy_set=0
{ [ -n "$env_http" ] || [ -n "$env_https" ] || [ -n "$env_all" ]; } && env_proxy_set=1

# NO_PROXY 为空也应视为缺失（否则开代理后 localhost/127.0.0.1 可能被塞进代理）
no_proxy_ok=1
echo "$env_no" | grep -qi "localhost" || no_proxy_ok=0
echo "$env_no" | grep -q "127.0.0.1" || no_proxy_ok=0

persistent_http_proxy=""
if [ -r /etc/environment ]; then
  val=$(grep -i '^HTTP_PROXY=' /etc/environment 2>/dev/null | head -1 | cut -d= -f2-)
  [ -n "$val" ] && persistent_http_proxy="$val"
fi

# --- 代理软件进程 ---
PROXY_APP_REGEX="clash|verge|mihomo|v2ray|xray|surge|sing-box|shadowsocks"
proxy_names=""
if command -v ps >/dev/null 2>&1; then
  proxy_names=$(ps -eo comm 2>/dev/null | grep -i -E "$PROXY_APP_REGEX" | sort -u | tr '\n' ',' | sed 's/,$//')
fi
proxy_running=0
[ -n "$proxy_names" ] && proxy_running=1

# --- 代理端口监听（归属验证） ---
# 仅当监听者是代理进程时才算代理端口，避免 8080 等通用端口被非代理程序占用时误报；
# 在监听但监听者非代理进程的端口记入 suspect，仅供人工参考，不参与任何判定
listening=""
listening_count=0
suspect_listening=""
for p in 7890 7897 1080 2080 8080 8888; do
  found=0
  owner=""
  if command -v ss >/dev/null 2>&1; then
    info=$(ss -ltnp 2>/dev/null | grep ":$p ")
    [ -n "$info" ] && found=1
    [ -n "$info" ] && owner=$(echo "$info" | grep -o -i -E "$PROXY_APP_REGEX" | head -1)
  elif command -v lsof >/dev/null 2>&1; then
    info=$(lsof -nP -iTCP:"$p" -sTCP:LISTEN 2>/dev/null | awk 'NR>1')
    [ -n "$info" ] && found=1
    [ -n "$info" ] && owner=$(echo "$info" | awk '{print $1}' | head -1 | grep -o -i -E "$PROXY_APP_REGEX")
  elif command -v netstat >/dev/null 2>&1; then
    # netstat 拿不到监听者进程信息 → 无法验证归属，保守归入疑似
    netstat -ltn 2>/dev/null | grep -q ":$p " && found=1
  fi
  if [ "$found" -eq 1 ]; then
    if [ -n "$owner" ]; then
      [ -n "$listening" ] && listening="$listening,$p" || listening="$p"
      listening_count=$((listening_count+1))
    else
      [ -n "$suspect_listening" ] && suspect_listening="$suspect_listening,$p" || suspect_listening="$p"
    fi
  fi
done

# --- TUN / 虚拟网卡接管（归属验证） ---
# wintun/tap/wireguard/utun 是通用驱动或系统接口名（企业 VPN、macOS 系统自带 utun0~3 均使用），
# 不能仅凭它们判定代理 TUN：仅当“网卡名匹配代理软件名”，或“疑似 TUN 且代理进程在跑且默认路由被 TUN 类接口接管”才算 active，
# 其余记入 tun_suspect 仅提示
tun_active=0
tun_suspect=""
if [ "$OS" = "Darwin" ]; then
  tun_ifs=$(ifconfig -l 2>/dev/null | tr ' ' '\n' | grep -E "^utun[0-9]+$|^tun[0-9]+$|^tap[0-9]+$" | head -3 | tr '\n' ',' | sed 's/,$//')
  if [ -n "$tun_ifs" ]; then
    if [ "$proxy_running" -eq 1 ]; then
      def_if=$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')
      case "$def_if" in
        utun*|tun*|tap*) tun_active=1 ;;
        *) tun_suspect="$tun_ifs" ;;
      esac
    else
      tun_suspect="$tun_ifs"
    fi
  fi
else
  named_ifs=$(ip -o link show 2>/dev/null | awk -F': ' '{print $2}' | grep -i -E "mihomo|clash|verge|sing-box|stash" | head -3 | tr '\n' ',' | sed 's/,$//')
  if [ -n "$named_ifs" ]; then
    tun_active=1
  else
    drv_ifs=$(ip -o link show 2>/dev/null | awk -F': ' '{print $2}' | grep -i -E "^tun[0-9]*|^tap[0-9]*|^wg[0-9]+|wintun" | head -3 | tr '\n' ',' | sed 's/,$//')
    if [ -n "$drv_ifs" ]; then
      if [ "$proxy_running" -eq 1 ]; then
        def_dev=$(ip route show default 2>/dev/null | grep -o -E "dev [a-z0-9_-]+" | awk '{print $2}' | head -1)
        case "$def_dev" in
          tun*|tap*|wg*) tun_active=1 ;;
          *) tun_suspect="$drv_ifs" ;;
        esac
      else
        tun_suspect="$drv_ifs"
      fi
    fi
  fi
fi

# --- 目标 URL ---
# proxy_ok = 真实经代理端口请求目标 URL：收到任意 HTTP 响应（含 403 风控码，curl 返回非 000 状态码）即链路可用；
# 连接失败/超时为不可用；无真实代理端口（listening 为空）时直接为 false
direct_ok="null"
proxy_ok="null"
proxy_test_port=""
if [ -n "$TARGET" ]; then
  host=$(echo "$TARGET" | sed -E 's#https?://##; s#/.*##; s#:.*##')
  if [ -n "$host" ]; then
    if tcp_ok "$host" 443 6; then direct_ok="true"; else direct_ok="false"; fi
  fi
  proxy_ok="false"
  if command -v curl >/dev/null 2>&1; then
    oldifs="$IFS"
    IFS=','
    for pp in $listening; do
      [ -z "$pp" ] && continue
      code=$(curl -s -o /dev/null -w "%{http_code}" -x "http://127.0.0.1:$pp" --connect-timeout 6 --max-time 10 "$TARGET" 2>/dev/null)
      if [ -n "$code" ] && [ "$code" != "000" ]; then
        proxy_ok="true"
        proxy_test_port="$pp"
        break
      fi
    done
    IFS="$oldifs"
  fi
fi

# --- 汇总问题 ---
issues="[]"
status="normal"

issue_json=""
add_issue() {
  if [ -n "$issue_json" ]; then issue_json="$issue_json,"; fi
  issue_json="$issue_json{\"code\":\"$1\",\"severity\":\"$2\",\"detail\":\"$3\"}"
}

if [ "$cloud_ok" -ne 1 ]; then
  add_issue "CLOUD_UNREACHABLE" "failed" "TeleAgent cloud endpoint unreachable"
  status="failed"
fi
if [ "$env_proxy_set" -eq 1 ] && [ "$no_proxy_ok" -eq 0 ]; then
  add_issue "NO_PROXY_MISSING_LOCAL" "warning" "env proxy set but NO_PROXY missing localhost/127.0.0.1"
  [ "$status" != "failed" ] && status="warning"
fi
if [ -n "$persistent_http_proxy" ] && [ "$no_proxy_ok" -eq 0 ]; then
  add_issue "PERSISTENT_NO_PROXY_MISSING" "warning" "persistent HTTP_PROXY without NO_PROXY (risk after TeleAgent restart)"
  [ "$status" != "failed" ] && status="warning"
fi
if [ "$sys_proxy_enabled" = "true" ] && [ "$proxy_running" -eq 0 ] && [ "$listening_count" -eq 0 ]; then
  add_issue "SYSTEM_PROXY_STALE" "warning" "system proxy enabled but no proxy software/port active (stale)"
  [ "$status" != "failed" ] && status="warning"
fi
if [ "$tun_active" -eq 1 ]; then
  add_issue "TUN_ACTIVE" "warning" "TUN adapter active; may intercept TeleAgent traffic"
  [ "$status" != "failed" ] && status="warning"
fi
if [ "$adapter_up" -eq 0 ]; then
  add_issue "NO_UP_ADAPTER" "warning" "no network adapter in Up state"
  [ "$status" != "failed" ] && status="warning"
fi
if [ "$dns_ok" -eq 0 ]; then
  add_issue "DNS_FAIL" "warning" "DNS resolution failed"
  [ "$status" != "failed" ] && status="warning"
fi

if [ -n "$issue_json" ]; then
  issues="[$issue_json]"
fi

# bool helpers
if [ "$adapter_up" -eq 1 ]; then a=true; else a=false; fi
if [ "$dns_ok" -eq 1 ]; then b=true; else b=false; fi
if [ "$internet_ok" -eq 1 ]; then c=true; else c=false; fi
if [ "$cloud_ok" -eq 1 ]; then d=true; else d=false; fi
if [ "$proxy_running" -eq 1 ]; then e=true; else e=false; fi
if [ "$tun_active" -eq 1 ]; then f=true; else f=false; fi
if [ "$no_proxy_ok" -eq 1 ]; then g=true; else g=false; fi

cat <<EOF
{
  "status": "$status",
  "base_network": {"adapter_up": $a, "dns_ok": $b, "internet_ok": $c},
  "system_proxy": {"enabled": $sys_proxy_enabled, "server": "$sys_proxy_server"},
  "env_proxy": {"http_proxy": "$env_http", "https_proxy": "$env_https", "all_proxy": "$env_all", "no_proxy": "$env_no", "no_proxy_ok": $g, "persistent_http_proxy": "$persistent_http_proxy"},
  "proxy_app": {"running": $e, "names": "$proxy_names"},
  "proxy_port": {"listening": "$listening", "suspect": "$suspect_listening"},
  "tun_active": $f,
  "tun_suspect": "$tun_suspect",
  "cloud_health": $d,
  "target_url": {"url": "$TARGET", "direct_ok": $direct_ok, "proxy_ok": $proxy_ok, "proxy_test_port": "$proxy_test_port"},
  "issues": $issues
}
EOF