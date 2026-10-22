#!/bin/bash
# ============================================================
# TeleAgent 日志异常检测脚本 (macOS / Linux，依赖 Python 3.6+)
# ============================================================
# 功能：定位日志 → 读取末尾 → 扫描异常关键词 → 提取上下文 → 输出 JSON
# 用法：./check-log-anomalies.sh
# 输出：JSON 格式诊断结果，供 Agent 解析判断
# ============================================================

# 兼容处理：部分 Linux 发行版 python3 不在 PATH，回退到 python
if command -v python3 > /dev/null 2>&1; then
    PYTHON=python3
elif command -v python > /dev/null 2>&1; then
    PYTHON=python
else
    echo '{"status": "no_log", "log_file": "", "last_start_status": "unknown", "anomalies": [], "summary": "未找到 Python 3，无法运行检测脚本"}'
    exit 0
fi

$PYTHON << 'PYEOF'
import os, sys, json, glob, re

# ============================================================
# 配置
# ============================================================

TAIL_LINES = 2000  # 读取日志末尾行数上限

# 异常关键词列表（不区分大小写匹配）
ANOMALY_PATTERNS = [
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
    "EBUSY resource busy",
]

# 启动成功标记
START_SUCCESS_MARKERS = [
    "app ready",
    "Server started",
    "listening on",
    "ready in",
    "started successfully",
]

# 启动尝试标记
START_ATTEMPT_MARKERS = [
    "starting",
    "launching",
    "booting",
    "initializing",
]

# 退出标记
EXIT_MARKERS = [
    "exiting",
    "shutting down",
    "process exit",
    "fatal error",
]

# ============================================================
# 定位日志文件
# ============================================================

def find_log_file():
    """按优先级搜索候选路径，返回最新修改的 .log 文件路径"""
    home = os.path.expanduser("~")
    system = os.uname().sysname if hasattr(os, 'uname') else sys.platform

    def _resolve_data_dir():
        env_dir = os.environ.get("TELEAGENT_DATA_DIR")
        if env_dir and os.path.isdir(env_dir):
            return env_dir
        base = os.path.join(home, ".local", "share", "TeleAgent")
        owner_file = os.path.join(base, "current-owner.json")
        if os.path.isfile(owner_file):
            try:
                with open(owner_file, "r", encoding="utf-8") as f:
                    owner = json.load(f).get("ownerDir")
                if owner:
                    d = os.path.join(base, "users", owner)
                    if os.path.isdir(d):
                        return d
            except Exception:
                pass
        return base

    candidates = []
    # 优先级1：TeleAgent 注入的日志环境变量
    log_env = os.environ.get("SUPER_AGENT_LOG_DIR")
    if log_env:
        candidates.append(log_env)
    # 优先级2：当前账号数据目录的 log\（单数）
    data_dir = _resolve_data_dir()
    if data_dir:
        candidates.append(os.path.join(data_dir, "log"))
        candidates.append(data_dir)

    if system == "Darwin" or (isinstance(system, str) and "darwin" in system.lower()):
        # macOS 候选路径
        candidates.append(os.path.join(home, "Library/Logs/TeleAgent"))
        candidates.append(os.path.join(home, "Library/Application Support/TeleAgent"))
        candidates.append(os.path.join(home, ".local/share/TeleAgent"))
    else:
        # Linux 候选路径
        candidates.append(os.path.join(home, ".local/share/TeleAgent"))
        # 检查 XDG_CONFIG_HOME
        xdg = os.environ.get("XDG_CONFIG_HOME")
        if xdg:
            candidates.append(os.path.join(xdg, "TeleAgent"))
        candidates.append(os.path.join(home, ".config/TeleAgent"))

    for dir_path in candidates:
        if os.path.isdir(dir_path):
            # 优先在根目录找 .log 文件
            log_files = glob.glob(os.path.join(dir_path, "*.log"))
            if log_files:
                log_files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
                return log_files[0]

            # 检查 runtime 子目录
            runtime_dir = os.path.join(dir_path, "runtime")
            if os.path.isdir(runtime_dir):
                runtime_logs = glob.glob(os.path.join(runtime_dir, "*.log"))
                if runtime_logs:
                    runtime_logs.sort(key=lambda f: os.path.getmtime(f), reverse=True)
                    return runtime_logs[0]

            # 递归搜索一层（兼容 logs/ 子目录）
            for entry in os.listdir(dir_path):
                subdir = os.path.join(dir_path, entry)
                if os.path.isdir(subdir):
                    sub_logs = glob.glob(os.path.join(subdir, "*.log"))
                    if sub_logs:
                        sub_logs.sort(key=lambda f: os.path.getmtime(f), reverse=True)
                        return sub_logs[0]

    return None


# ============================================================
# 提取异常上下文
# ============================================================

def get_anomaly_context(lines, match_index, context_radius=3):
    """提取匹配行前后各 context_radius 行作为上下文"""
    start = max(0, match_index - context_radius)
    end = min(len(lines) - 1, match_index + context_radius)
    context_lines = []
    for i in range(start, end + 1):
        context_lines.append(f"[{i + 1}] {lines[i]}")
    return "\n".join(context_lines)


# ============================================================
# 从日志行提取时间戳
# ============================================================

def get_timestamp_from_line(line):
    """提取日志行中的时间戳"""
    # 匹配 ISO 8601: 2026-08-01T10:23:45.123Z
    m = re.search(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[\.\d]*Z?)', line)
    if m:
        return m.group(1)
    # 匹配常见日志时间戳: [2026-08-01 10:23:45.123]
    m = re.search(r'(\d{4}-\d{2}-\d{2}[\s T]\d{2}:\d{2}:\d{2}(?:\.\d+)?)', line)
    if m:
        return m.group(1)
    return ""


# ============================================================
# 判断最近一次启动是否成功
# ============================================================

def get_last_start_status(lines):
    """从日志末尾向前搜索最近的启动尝试标记，判断启动是否成功"""
    # 从末尾向前搜索启动尝试标记
    last_attempt_index = -1
    for i in range(len(lines) - 1, -1, -1):
        lower = lines[i].lower()
        for marker in START_ATTEMPT_MARKERS:
            if marker in lower:
                last_attempt_index = i
                break
        if last_attempt_index >= 0:
            break

    if last_attempt_index < 0:
        return "unknown"

    # 从启动尝试位置向后搜索成功标记
    for i in range(last_attempt_index, len(lines)):
        lower = lines[i].lower()
        for marker in START_SUCCESS_MARKERS:
            if marker in lower:
                return "success"

    # 从启动尝试位置向后搜索退出标记
    for i in range(last_attempt_index, len(lines)):
        lower = lines[i].lower()
        for marker in EXIT_MARKERS:
            if marker in lower:
                return "failed"

    # 有启动尝试但没有成功/退出标记，认为启动失败
    if last_attempt_index >= 0:
        return "failed"

    return "unknown"


# ============================================================
# 主流程
# ============================================================

log_file = find_log_file()

if not log_file:
    result = {
        "status": "no_log",
        "log_file": "",
        "last_start_status": "unknown",
        "anomalies": [],
        "summary": "找不到 TeleAgent 日志文件，请检查 TeleAgent 是否曾正常安装"
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0)

# 读取日志文件
try:
    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
        all_lines = f.read().splitlines()
except Exception as e:
    result = {
        "status": "no_log",
        "log_file": log_file,
        "last_start_status": "unknown",
        "anomalies": [],
        "summary": f"读取日志文件失败: {e}"
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0)

total_lines = len(all_lines)
if total_lines == 0:
    result = {
        "status": "empty_log",
        "log_file": log_file,
        "last_start_status": "unknown",
        "anomalies": [],
        "summary": "日志文件为空，无法诊断"
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0)

# 截取末尾 TAIL_LINES 行
if total_lines > TAIL_LINES:
    lines = all_lines[total_lines - TAIL_LINES:]
    offset = total_lines - TAIL_LINES
else:
    lines = all_lines
    offset = 0

# 判断最近一次启动状态
last_start = get_last_start_status(lines)

# 扫描异常关键词
anomalies = []
seen_lines = set()
for i, line in enumerate(lines):
    line_lower = line.lower()
    for pattern in ANOMALY_PATTERNS:
        pattern_lower = pattern.lower()
        if pattern_lower in line_lower:
            abs_line = offset + i + 1
            if abs_line not in seen_lines:
                seen_lines.add(abs_line)
                ts = get_timestamp_from_line(line)
                context = get_anomaly_context(lines, i)
                anomalies.append({
                    "type": pattern,
                    "timestamp": ts,
                    "message": line.strip(),
                    "context": context,
                    "line_number": i + 1,
                    "absolute_line": abs_line,
                })
            break  # 同一行只匹配一个关键词

# 生成 summary
if len(anomalies) == 0 and last_start == "success":
    status = "normal"
    summary = "未检测到异常，最近一次启动成功"
elif len(anomalies) == 0 and last_start == "failed":
    status = "anomaly_found"
    summary = "最近一次启动失败（日志中有启动尝试但未出现成功标记）"
elif len(anomalies) == 0 and last_start == "unknown":
    status = "normal"
    summary = "未检测到异常"
else:
    status = "anomaly_found"
    last_anomaly = anomalies[-1]
    if last_start == "failed":
        summary = f"最近一次启动失败，异常原因：{last_anomaly['message']}"
    else:
        summary = f"检测到异常：{last_anomaly['message']}"

result = {
    "status": status,
    "log_file": log_file,
    "last_start_status": last_start,
    "anomalies": anomalies,
    "summary": summary,
}

print(json.dumps(result, ensure_ascii=False, indent=2))
PYEOF
