#!/bin/bash
# ============================================================
# MCP 路径校验脚本 (macOS / Linux，依赖 Python 3.6+)
# ============================================================
# 功能：备份配置 → 解析 MCP 条目 → 校验路径 → 推测正确路径 → 输出诊断结果
# 用法：./mcp-check-paths.sh
# 输出：结构化诊断信息，供 Agent 展示给用户确认
# ============================================================

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
import json, os, re, glob, sys, shutil

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
user_data_dir = _resolve_dir(os.path.join(home, ".local", "share", "TeleAgent"), "TELEAGENT_DATA_DIR")
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

# --- Step 1: 备份 ---
shutil.copy2(jsonc_file, jsonc_file + ".bak")
print(f"[信息] 已备份: {jsonc_file} -> {jsonc_file}.bak")

# --- Step 2: 读取并解析 JSONC ---
with open(jsonc_file, "r", encoding="utf-8") as f:
    content = f.read()


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


try:
    data = json.loads(strip_jsonc(content))
except json.JSONDecodeError as e:
    print(f"[错误] JSONC 解析失败: {e}")
    sys.exit(1)

# --- Step 3: 校验 MCP 路径 ---
issues = []

if "mcp" not in data or not data["mcp"]:
    print("[通过] 配置中无 MCP 段，无需校验")
    sys.exit(0)

for name, entry in data["mcp"].items():
    # --- 检查 command 数组中所有像路径的元素 ---
    cmd = entry.get("command", [])
    for j, part in enumerate(cmd):
        # 路径特征判断：含反斜杠、以/或./或~/开头、或以脚本扩展名结尾
        looks_like_path = (
            "\\" in part
            or part.startswith("/")
            or part.startswith("./")
            or part.startswith("~/")
            or re.search(r"\.(js|py|ts|exe|cmd|sh)$", part)
        )
        if looks_like_path:
            expanded = os.path.expandvars(os.path.expanduser(part))
            if not os.path.exists(expanded):
                issues.append(
                    {
                        "server": name,
                        "field": f"command[{j}]",
                        "bad_path": part,
                        "expanded": expanded,
                    }
                )

    # --- 检查 environment.PATH 中的目录 ---
    env = entry.get("environment", {})
    if env and "PATH" in env:
        # 同时处理 ; 和 : 分隔符，过滤掉 ${...} 变量引用
        parts = [
            p
            for p in env["PATH"].replace(";", ":").split(":")
            if p and not p.startswith("${")
        ]
        for p in parts:
            exp = os.path.expandvars(os.path.expanduser(p))
            if not os.path.isdir(exp):
                issues.append(
                    {
                        "server": name,
                        "field": "environment.PATH",
                        "bad_path": p,
                        "expanded": exp,
                    }
                )

if not issues:
    print("[通过] 所有 MCP 路径校验通过，无路径错误")
    sys.exit(0)

# --- Step 4: 推测正确路径 ---
print(f"[发现 {len(issues)} 个路径问题]")
print()

for iss in issues:
    suggested = None
    bad_path = iss["bad_path"]

    # 场景1: 用户名目录拼错 → 替换为当前用户
    if re.search(r"/(home|Users)/[^/]+/", bad_path):
        candidate = re.sub(r"/(home|Users)/[^/]+/", home + "/", bad_path)
        if os.path.exists(candidate):
            suggested = candidate

    # 场景2: 运行时路径错误 → 在标准目录下搜索同名文件
    if not suggested and "runtimes" in bad_path:
        filename = os.path.basename(bad_path)
        runtimes_dir = os.path.join(user_data_dir, "runtimes")
        if filename and os.path.isdir(runtimes_dir):
            matches = glob.glob(
                os.path.join(runtimes_dir, "**", filename), recursive=True
            )
            if matches:
                suggested = matches[0]

    # 场景3: 斜杠方向错误（反斜杠写成了正斜杠）→ 尝试替换
    if not suggested and "\\" in bad_path:
        candidate = bad_path.replace("\\", "/")
        candidate_exp = os.path.expanduser(candidate)
        if os.path.exists(candidate_exp):
            suggested = candidate

    print(f"[问题] MCP '{iss['server']}' | {iss['field']}")
    print(f"  当前错误路径: {iss['expanded']}")
    if suggested:
        print(f"  建议修正路径: {suggested}")
    else:
        print("  建议修正路径: [无法自动推测，需手动确认]")
    print()

PYEOF
