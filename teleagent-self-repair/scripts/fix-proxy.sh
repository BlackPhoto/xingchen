#!/usr/bin/env bash
# ============================================================
# TeleAgent 代理操作脚本 (macOS / Linux, Bash)
# ============================================================
# 功能：代理协助操作（启动/修复/回滚/清理/补NO_PROXY）
# 用法：
#   ./fix-proxy.sh assist        # 启动代理软件并等待端口（写快照）
#   ./fix-proxy.sh repair        # 尽力修复接管方式（无API则no_action）
#   ./fix-proxy.sh rollback      # 按快照回滚
#   ./fix-proxy.sh cleanup       # 清理系统代理残留
#   ./fix-proxy.sh fix-noproxy   # 补全 NO_PROXY
# 输出：JSON 格式结果，供 Agent 解析判断
# ============================================================

set -u
OS="$(uname -s)"
SNAPSHOT="/tmp/teleagent-proxy-snapshot.json"
ACTION="${1:-}"

PROXY_APP_REGEX="clash|verge|mihomo|v2ray|xray|surge|sing-box|shadowsocks"

# --- 检测代理进程 ---
running_proxy_pids() {
  pgrep -f -i "$PROXY_APP_REGEX" 2>/dev/null | tr '\n' ','
}

port_listening() {
  local p="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -ltn 2>/dev/null | grep -q ":$p " && return 0
  elif command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1 && return 0
  elif command -v netstat >/dev/null 2>&1; then
    netstat -ltn 2>/dev/null | grep -q ":$p " && return 0
  fi
  return 1
}

# 归属验证：仅当监听者是代理进程时才算代理端口，
# 避免 8080 等通用端口被非代理程序占用时误判（assist 假就绪 / cleanup 永不清理）
port_owned_by_proxy() {
  local p="$1" info owner
  if command -v ss >/dev/null 2>&1; then
    info=$(ss -ltnp 2>/dev/null | grep ":$p ")
    [ -n "$info" ] || return 1
    owner=$(echo "$info" | grep -o -i -E "$PROXY_APP_REGEX" | head -1)
  elif command -v lsof >/dev/null 2>&1; then
    info=$(lsof -nP -iTCP:"$p" -sTCP:LISTEN 2>/dev/null | awk 'NR>1')
    [ -n "$info" ] || return 1
    owner=$(echo "$info" | awk '{print $1}' | head -1 | grep -o -i -E "$PROXY_APP_REGEX")
  else
    # netstat 拿不到监听者进程信息 → 无法验证归属，保守判定为非代理
    return 1
  fi
  [ -n "$owner" ] && return 0 || return 1
}

first_listening_port() {
  local out=""
  for p in $PORTS_ORDERED; do
    port_owned_by_proxy "$p" && { [ -n "$out" ] && out="$out,$p" || out="$p"; }
  done
  echo "$out"
}

PORTS_ORDERED="7897 7890 1080 2080 8888 8080"

# --- 查找代理应用（通用探测链：固定位置 → 运行中进程路径推导 → mdfind） ---
find_proxy_app() {
  local name pid exe hit
  if [ "$OS" = "Darwin" ]; then
    for name in "Clash Verge" "Clash for Windows" "Stash" "Surge"; do
      [ -d "/Applications/$name.app" ] && { echo "/Applications/$name.app"; return 0; }
    done
    # Spotlight 索引兜底（覆盖自定义安装位置）
    if command -v mdfind >/dev/null 2>&1; then
      hit=$(mdfind "kMDItemKind == 'Application'" 2>/dev/null | grep -i -E "clash|verge|mihomo" | grep -E "\.app$" | head -1)
      [ -n "$hit" ] && { echo "$hit"; return 0; }
    fi
  else
    for name in clash verge mihomo v2ray sing-box; do
      if command -v "$name" >/dev/null 2>&1; then command -v "$name"; return 0; fi
    done
  fi
  # 运行中的代理进程可执行路径推导（覆盖任意安装位置）
  for pid in $(pgrep -f -i "$PROXY_APP_REGEX" 2>/dev/null); do
    if [ -r "/proc/$pid/exe" ]; then
      exe=$(readlink -f "/proc/$pid/exe" 2>/dev/null)
      [ -n "$exe" ] && [ -x "$exe" ] && { echo "$exe"; return 0; }
    fi
  done
  # macOS：从进程可执行路径提取 .app 根目录（open 需要 .app）
  if [ "$OS" = "Darwin" ] && command -v ps >/dev/null 2>&1; then
    hit=$(ps -axo comm 2>/dev/null | grep -i -E "/Applications/[^ ]+\.app" | grep -i -E "$PROXY_APP_REGEX" | head -1 | sed -E 's#(/Applications/[^ /]+\.app)/.*#\1#')
    [ -n "$hit" ] && { echo "$hit"; return 0; }
  fi
  return 1
}

# --- 关闭系统代理 ---
disable_sys_proxy() {
  if [ "$OS" = "Darwin" ] && command -v networksetup >/dev/null 2>&1; then
    for svc in "Wi-Fi" "Ethernet" "USB 10/100/1000 LAN" "Thunderbolt Bridge"; do
      networksetup -setwebproxystate "$svc" off >/dev/null 2>&1
      networksetup -setsecurewebproxystate "$svc" off >/dev/null 2>&1
    done
  elif command -v gsettings >/dev/null 2>&1; then
    gsettings set org.gnome.system.proxy mode 'none' >/dev/null 2>&1
  fi
}

# --- 读取系统代理是否启用（写快照用） ---
get_sys_proxy_enabled() {
  if [ "$OS" = "Darwin" ] && command -v networksetup >/dev/null 2>&1; then
    for svc in "Wi-Fi" "Ethernet" "USB 10/100/1000 LAN" "Thunderbolt Bridge"; do
      state=$(networksetup -getwebproxy "$svc" 2>/dev/null)
      if [ -n "$state" ]; then
        if echo "$state" | grep -qi "Enabled: Yes"; then echo "true"; else echo "false"; fi
        return 0
      fi
    done
  elif command -v gsettings >/dev/null 2>&1; then
    mode=$(gsettings get org.gnome.system.proxy mode 2>/dev/null | tr -d "'")
    [ "$mode" = "manual" ] && echo "true" || echo "false"
    return 0
  fi
  echo "false"
}

# ============================================================
# Action: assist
# ============================================================
if [ "$ACTION" = "assist" ]; then
  # 判定语义（防"仅辅助/服务进程在跑"的假就绪）：
  #   "代理已运行"的唯一标准 = 代理端口有监听（归属验证过）；
  #   仅匹配到辅助/服务进程而端口无监听时，仍需启动主程序。
  existing=$(running_proxy_pids | xargs)
  before_ports=$(first_listening_port)
  already=0
  [ -n "$before_ports" ] && already=1

  started=""
  app=""
  if [ "$already" -eq 0 ]; then
    if app=$(find_proxy_app); then
      if [ "$OS" = "Darwin" ]; then
        open -n "$app" >/dev/null 2>&1
      else
        nohup "$app" >/dev/null 2>&1 &
      fi
    fi
  fi

  ready=0
  for i in $(seq 1 30); do
    p=$(first_listening_port)
    [ -n "$p" ] && { ready=1; break; }
    sleep 1
  done

  sys_before_val=$(get_sys_proxy_enabled)
  sys_json="false"
  [ "$sys_before_val" = "true" ] && sys_json="true"
  cat > "$SNAPSHOT" <<EOF
{"created":"$(date -u +%Y-%m-%dT%H:%M:%SZ)","already_running":$already,"sys_proxy_before":{"enabled":$sys_json}}
EOF

  if [ "$ready" -eq 1 ]; then status="started"; detail="proxy port ready"
  else status="failed"; detail="no proxy port listening"; fi

  cat <<EOF
{"action":"assist","status":"$status","detail":"$detail","already_running":$([ $already -eq 1 ] && echo true || echo false),"listening_ports":"$(first_listening_port)","proxy_app":"$app","snapshot":"$SNAPSHOT"}
EOF
  exit 0
fi

# ============================================================
# Action: repair
# ============================================================
if [ "$ACTION" = "repair" ]; then
  result=0
  reason="no_api"
  # 归属验证：9090 也是其他服务常用端口，仅当监听者是代理进程时才尝试调用其 controller API
  ctl_ok=0
  if command -v ss >/dev/null 2>&1; then
    info9090=$(ss -ltnp 2>/dev/null | grep ":9090 ")
    [ -n "$info9090" ] && echo "$info9090" | grep -q -i -E "$PROXY_APP_REGEX" && ctl_ok=1
  elif command -v lsof >/dev/null 2>&1; then
    info9090=$(lsof -nP -iTCP:9090 -sTCP:LISTEN 2>/dev/null | awk 'NR>1')
    [ -n "$info9090" ] && echo "$info9090" | awk '{print $1}' | head -1 | grep -q -i -E "$PROXY_APP_REGEX" && ctl_ok=1
  fi
  if [ "$ctl_ok" -eq 1 ]; then
    # 尝试 mihomo API 切回规则模式
    secret=""
    for cf in "$HOME/.config/mihomo/config.yaml" "$HOME/.config/clash/config.yaml" "$HOME/.config/clash-verge/config.yaml"; do
      [ -r "$cf" ] && { secret=$(sed -n 's/^secret:[[:space:]]*"\{0,1\}\([^"]*\)"\{0,1\}.*/\1/p' "$cf" | head -1); break; }
    done
    auth=""
    [ -n "$secret" ] && auth="Authorization: Bearer $secret"
    res=$(curl -s -o /dev/null -w "%{http_code}" -X PATCH -H "Content-Type: application/json" -H "$auth" \
      --data '{"mode":"rule"}' --max-time 5 "http://127.0.0.1:9090/configs" 2>/dev/null)
    if [ "$res" = "200" ] || [ "$res" = "204" ]; then
      result=1; reason="switch_rule_mode"
    fi
  fi
  [ "$result" -eq 1 ] && s=true || s=false
  cat <<EOF
{"action":"repair","success":$s,"reason":"$reason"}
EOF
  exit 0
fi

# ============================================================
# Action: rollback
# ============================================================
if [ "$ACTION" = "rollback" ]; then
  already=0
  sys_before=""
  if [ -f "$SNAPSHOT" ]; then
    already=$(sed -n 's/.*"already_running":\([01]\).*/\1/p' "$SNAPSHOT")
    sys_before=$(sed -n 's/.*"sys_proxy_before":{"enabled":true.*/true/p' "$SNAPSHOT")
    [ -z "$sys_before" ] && sys_before=$(sed -n 's/.*"sys_proxy_before":{"enabled":false.*/false/p' "$SNAPSHOT")
  fi
  [ -z "$already" ] && already=0

  terminated=false
  if [ "$already" -eq 0 ]; then
    # 本次 assist 自己启动了代理 → 终止本次启动的代理进程
    for pid in $(running_proxy_pids); do
      kill -9 "$pid" 2>/dev/null && terminated=true
    done
  fi

  # 还原系统代理：按快照原值（启动前已开启则保持，否则关闭）
  if [ "$sys_before" = "true" ]; then
    :
  else
    disable_sys_proxy
  fi

  [ "$terminated" = "true" ] && t=true || t=false
  cat <<EOF
{"action":"rollback","status":"done","terminated":$t,"sys_proxy_restored":true}
EOF
  exit 0
fi

# ============================================================
# Action: cleanup
# ============================================================
if [ "$ACTION" = "cleanup" ]; then
  pids=$(running_proxy_pids | xargs)
  ports=$(first_listening_port)

  changed=false
  detail="no_change"
  if [ -z "$pids" ] && [ -z "$ports" ]; then
    # 无代理进程且无端口 → 若是残留则关闭系统代理
    disable_sys_proxy
    changed=true
    detail="system proxy cleared"
  else
    detail="proxy still active, not modified"
  fi

  cat <<EOF
{"action":"cleanup","status":"$( [ "$changed" = "true" ] && echo changed || echo no_change )","detail":"$detail"}
EOF
  exit 0
fi

# ============================================================
# Action: fix-noproxy
# ============================================================
if [ "$ACTION" = "fix-noproxy" ]; then
  target="$HOME/.profile"
  line=""
  if [ -f "$target" ]; then
    line=$(grep -i 'NO_PROXY=' "$target" 2>/dev/null | tail -1 | sed 's/^[^=]*=//')
  fi

  changed=false
  if [ -z "$line" ] || ! echo "$line" | grep -qi "localhost" || ! echo "$line" | grep -q "127.0.0.1"; then
    parts=""
    echo "$line" | grep -qi "localhost" || parts="$parts,localhost"
    echo "$line" | grep -q "127.0.0.1" || parts="$parts,127.0.0.1"
    if [ -n "$line" ]; then new="$line$parts"; else new="${parts#,}"; fi
    # 确保目标文件存在；删除旧 NO_PROXY 行后追加（跨平台 sed，不带 -i）
    touch "$target"
    sed "/[Nn][Oo]_[Pp][Rr][Oo][Xx][Yy]=/d" "$target" > "$target.tmp"
    echo "export NO_PROXY=\"$new\"" >> "$target.tmp"
    mv "$target.tmp" "$target"
    line="$new"
    changed=true
  fi

  # 同步当前会话
  if [ "$changed" = "true" ]; then
    if [ -n "${NO_PROXY:-}" ]; then
      export NO_PROXY="$NO_PROXY,$new"
    else
      export NO_PROXY="${new#,}"
    fi
  fi

  [ "$changed" = "true" ] && c=true || c=false
  cat <<EOF
{"action":"fix-noproxy","changed":$c,"persistent_no_proxy":"$line","session_no_proxy":"${NO_PROXY:-}"}
EOF
  exit 0
fi

echo '{"action":"unknown","status":"failed"}'
exit 1