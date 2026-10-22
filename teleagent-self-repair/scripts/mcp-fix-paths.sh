#!/bin/bash
# ============================================================
# MCP 路径修复脚本 (macOS / Linux，依赖 Python 3.6+)
# ============================================================
# 功能：读取修复清单 JSON 文件 → 写入修正路径 → JSON 格式校验 → 失败回滚
# 用法：./mcp-fix-paths.sh <修复清单JSON文件路径>
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

FIXES_FILE="$1"

if [ -z "$FIXES_FILE" ]; then
    echo "用法: ./mcp-fix-paths.sh <修复清单JSON文件路径>"
    exit 1
fi

# 通过环境变量传递文件路径给 Python（避免 heredoc 内引号/转义问题）
export TELEAGENT_FIXES_FILE="$FIXES_FILE"

# 兼容处理：部分 Linux 发行版 python3 不在 PATH，回退到 python
if command -v python3 > /dev/null 2>&1; then
    PYTHON=python3
elif command -v python > /dev/null 2>&1; then
    PYTHON=python
else
    echo "[错误] 未找到 Python 3，请先安装"
    exit 1
fi

$PYTHON << 'PYEOF'
import json, os, sys, shutil, glob

fixes_file = os.environ["TELEAGENT_FIXES_FILE"]
def _resolve_dir(base, env_key):
    """按 环境变量 → owner标记 → 探测活跃子目录 → 回退 解析账号目录"""
    env_dir = os.environ.get(env_key)
    if env_dir and os.path.isdir(env_dir):
        return env_dir
    owner_file = os.path.join(os.path.expanduser("~"), ".local", "share", "TeleAgent", "current-owner.json")
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
    users_root = os.path.join(base, "users")
    if os.path.isdir(users_root):
        dirs = [os.path.join(users_root, x) for x in os.listdir(users_root)
                if os.path.isdir(os.path.join(users_root, x))]
        if dirs:
            return max(dirs, key=lambda p: os.path.getmtime(p))
    return base

home = os.path.expanduser("~")
_xdg = os.environ.get("XDG_CONFIG_HOME")
_cfg_base = os.path.join(_xdg, "TeleAgent") if _xdg else os.path.join(home, ".config", "TeleAgent")
config_dir = _resolve_dir(_cfg_base, "TELEAGENT_CONFIG_DIR")
jsonc_file = os.path.join(config_dir, "TeleAgent.jsonc")

# 配置文件不在标准路径时，搜索目录下疑似配置文件
if not os.path.exists(jsonc_file):
    if os.path.isdir(config_dir):
        for ext in ("*.jsonc", "*.json", "*.jsonc.bak"):
            matches = glob.glob(os.path.join(config_dir, ext))
            if matches:
                jsonc_file = matches[0]
                break

if not os.path.exists(jsonc_file):
    print(f"[错误] 配置文件不存在: {jsonc_file}")
    sys.exit(1)

if not os.path.exists(jsonc_file + ".bak"):
    print("[警告] 未找到备份文件 (.bak)，请确认已运行 mcp-check-paths.sh")

# --- 读取修复清单 ---
if not os.path.exists(fixes_file):
    print(f"[错误] 修复清单文件不存在: {fixes_file}")
    sys.exit(1)

with open(fixes_file, "r", encoding="utf-8") as f:
    fixes = json.load(f)


# --- 读取并解析 JSONC ---
def strip_jsonc(s):
    """去除 JSONC 注释（状态机方式，正确处理字符串内的注释语法）"""
    result = []
    i = 0
    in_string = False
    while i < len(s):
        if in_string:
            if s[i] == "\\" and i + 1 < len(s):
                result.append(s[i : i + 2])
                i += 2
                continue
            if s[i] == '"':
                in_string = False
            result.append(s[i])
            i += 1
        elif s[i] == '"':
            in_string = True
            result.append(s[i])
            i += 1
        elif s[i : i + 2] == "//":
            while i < len(s) and s[i] != "\n":
                i += 1
        elif s[i : i + 2] == "/*":
            i += 2
            while i + 1 < len(s) and s[i : i + 2] != "*/":
                i += 1
            i += 2
        else:
            result.append(s[i])
            i += 1
    return "".join(result)


with open(jsonc_file, "r", encoding="utf-8") as f:
    content = f.read()

try:
    data = json.loads(strip_jsonc(content))
except json.JSONDecodeError as e:
    print(f"[错误] JSONC 解析失败: {e}")
    sys.exit(1)

# --- 应用修复 ---
for fix in fixes:
    server = fix["server"]
    field = fix["field"]

    if server not in data.get("mcp", {}):
        print(f'[警告] MCP Server "{server}" 不存在，跳过')
        continue

    entry = data["mcp"][server]

    if field.startswith("command["):
        # 提取索引: command[N]
        index = int(field.replace("command[", "").rstrip("]"))
        old_value = entry["command"][index]
        entry["command"][index] = fix["new_path"]
        print(f'[修复] {server} | command[{index}] | {old_value} -> {fix["new_path"]}')
    elif field == "environment.PATH":
        old_bad = fix["old_bad"]
        # 按分隔符拆分后逐个匹配替换，避免误伤包含子串的其他路径
        sep = ";" if ";" in entry["environment"]["PATH"] else ":"
        path_parts = entry["environment"]["PATH"].split(sep)
        replaced = False
        for pi, part in enumerate(path_parts):
            if part == old_bad:
                path_parts[pi] = fix["new_path"]
                replaced = True
        if replaced:
            entry["environment"]["PATH"] = sep.join(path_parts)
        print(f'[修复] {server} | environment.PATH | {old_bad} -> {fix["new_path"]}')
    else:
        print(f"[警告] 未知字段: {field}，跳过")

# --- 写入文件（注意：JSONC 注释会丢失，转为标准 JSON）---
with open(jsonc_file, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

# --- JSON 格式校验 ---
try:
    with open(jsonc_file, "r", encoding="utf-8") as f:
        json.load(f)
    print("[通过] 修正后 JSON 格式校验通过")
except json.JSONDecodeError:
    print("[失败] 修正后 JSON 格式校验失败，正在回滚...")
    shutil.copy2(jsonc_file + ".bak", jsonc_file)
    print("[回滚] 已恢复备份文件")
    sys.exit(1)

PYEOF
