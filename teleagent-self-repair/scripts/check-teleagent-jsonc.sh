#!/bin/bash
# ============================================================
# TeleAgent.jsonc 配置文件诊断脚本 (macOS / Linux，依赖 Python 3.6+)
# ============================================================
# 功能：备份 → 格式检查 → 字段检查 → 路径检查 → 输出诊断结果
# 用法：./check-teleagent-jsonc.sh
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
import json, os, glob, sys, shutil, re

# --- 定位当前账号配置目录（环境变量优先 → owner标记 → 探测兜底）---
def resolve_user_config_dir():
    env_dir = os.environ.get("TELEAGENT_CONFIG_DIR")
    if env_dir and os.path.isdir(env_dir):
        return env_dir
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        base = os.path.join(xdg, "TeleAgent")
    else:
        base = os.path.join(os.path.expanduser("~"), ".config", "TeleAgent")
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
config_dir = resolve_user_config_dir()
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
    print(f"[错误] 配置文件不存在: {config_dir}")
    sys.exit(1)

print(f"[信息] 配置文件: {jsonc_file}")

# --- Step 1: 备份 ---
shutil.copy2(jsonc_file, jsonc_file + ".bak")
print(f"[信息] 已备份: {jsonc_file} -> {jsonc_file}.bak")


# --- 辅助函数：剥离 JSONC 注释（位置保持）---
def strip_jsonc_preserve_position(text):
    """剥离 JSONC 注释，将注释替换为空格（保留换行），位置与原文件一一对应"""
    result = list(text)
    i = 0
    in_string = False
    escape = False

    while i < len(text):
        c = text[i]
        if in_string:
            if escape:
                escape = False
            elif c == '\\':
                escape = True
            elif c == '"':
                in_string = False
            i += 1
        elif c == '"':
            in_string = True
            i += 1
        elif c == '/' and i + 1 < len(text):
            nxt = text[i + 1]
            if nxt == '/':
                while i < len(text) and text[i] != '\n':
                    result[i] = ' '
                    i += 1
            elif nxt == '*':
                result[i] = ' '
                result[i + 1] = ' '
                i += 2
                while i < len(text):
                    if text[i] == '*' and i + 1 < len(text) and text[i + 1] == '/':
                        result[i] = ' '
                        result[i + 1] = ' '
                        i += 2
                        break
                    if text[i] != '\n':
                        result[i] = ' '
                    i += 1
            else:
                i += 1
        else:
            i += 1

    return ''.join(result)


# ========== 格式检查 ==========

# --- Step 2: 检测 UTF-8 BOM ---
with open(jsonc_file, 'rb') as f:
    raw_bytes = f.read()

has_bom = len(raw_bytes) >= 3 and raw_bytes[0] == 0xEF and raw_bytes[1] == 0xBB and raw_bytes[2] == 0xBF
if has_bom:
    print("[问题][格式] UTF-8 BOM: 文件前3字节为 EF BB BF")

# --- Step 3: 读取文本内容 ---
with open(jsonc_file, 'r', encoding='utf-8') as f:
    content = f.read()

lines = content.split('\n')

# --- Step 4: 检测控制字符 ---
control_found = False
for ln, line in enumerate(lines):
    for ci, ch in enumerate(line):
        code = ord(ch)
        if (0x00 <= code <= 0x08) or code == 0x0B or code == 0x0C or (0x0E <= code <= 0x1F):
            if not control_found:
                print("[问题][格式] 控制字符: 文件包含不可见控制字符")
                control_found = True
            print(f"  第 {ln + 1} 行第 {ci + 1} 列: 0x{code:02X}")

# --- Step 5: 检测全角符号 ---
fullwidth_map = {
    '\uff0c': ',', '\uff1a': ':', '\u201c': '"', '\u201d': '"',
    '\uff08': '(', '\uff09': ')', '\uff3b': '[', '\uff3d': ']',
    '\uff5b': '{', '\uff5d': '}', '\uff1b': ';',
}

fullwidth_found = False
for ln, line in enumerate(lines):
    for ci, ch in enumerate(line):
        if ch in fullwidth_map:
            if not fullwidth_found:
                print("[问题][格式] 全角符号: 文件包含全角符号混入")
                fullwidth_found = True
            hw = fullwidth_map[ch]
            print(f"  第 {ln + 1} 行第 {ci + 1} 列: {ch} -> {hw}")

# --- Step 6: 剥离 JSONC 注释 ---
stripped = strip_jsonc_preserve_position(content)

# --- Step 7: 检测尾逗号 ---
trailing_commas = []
in_str = False
esc = False
line_num = 1
col_num = 1

for i, c in enumerate(stripped):
    if in_str:
        if esc:
            esc = False
        elif c == '\\':
            esc = True
        elif c == '"':
            in_str = False
    else:
        if c == '"':
            in_str = True
        elif c == ',':
            j = i + 1
            while j < len(stripped) and stripped[j].isspace():
                j += 1
            if j < len(stripped) and stripped[j] in ('}', ']'):
                trailing_commas.append((line_num, col_num))

    if c == '\n':
        line_num += 1
        col_num = 1
    else:
        col_num += 1

if trailing_commas:
    print(f"[问题][格式] 尾逗号: 发现 {len(trailing_commas)} 处")
    for ln, col in trailing_commas:
        print(f"  第 {ln} 行第 {col} 列")

# --- Step 8: 检测连续逗号 ---
double_commas = []
in_str = False
esc = False
prev_comma = False
prev_comma_line = 0
prev_comma_col = 0
line_num = 1
col_num = 1

for c in stripped:
    if in_str:
        if esc:
            esc = False
        elif c == '\\':
            esc = True
        elif c == '"':
            in_str = False
        prev_comma = False
    else:
        if c == '"':
            in_str = True
            prev_comma = False
        elif c == ',':
            if prev_comma:
                double_commas.append((prev_comma_line, prev_comma_col))
            prev_comma = True
            prev_comma_line = line_num
            prev_comma_col = col_num
        elif not c.isspace():
            prev_comma = False

    if c == '\n':
        line_num += 1
        col_num = 1
    else:
        col_num += 1

if double_commas:
    print(f"[问题][格式] 连续逗号: 发现 {len(double_commas)} 处")
    for ln, col in double_commas:
        print(f"  第 {ln} 行第 {col} 列")

# --- Step 9: 检测括号不匹配 ---
bracket_issues = []
stack = []
in_str = False
esc = False
line_num = 1
col_num = 1

for c in stripped:
    if in_str:
        if esc:
            esc = False
        elif c == '\\':
            esc = True
        elif c == '"':
            in_str = False
    else:
        if c == '"':
            in_str = True
        elif c in ('{', '['):
            stack.append((c, line_num, col_num))
        elif c in ('}', ']'):
            if not stack:
                bracket_issues.append(("多余闭合", c, line_num, col_num))
            else:
                top_c, _, _ = stack[-1]
                expected = '{' if c == '}' else '['
                if top_c == expected:
                    stack.pop()
                else:
                    bracket_issues.append(("类型不匹配", c, line_num, col_num))

    if c == '\n':
        line_num += 1
        col_num = 1
    else:
        col_num += 1

for top_c, ln, col in stack:
    close = '}' if top_c == '{' else ']'
    bracket_issues.append(("缺少闭合", close, ln, col))

if bracket_issues:
    missing = sum(1 for b in bracket_issues if b[0] == "缺少闭合")
    extra = sum(1 for b in bracket_issues if b[0] == "多余闭合")
    mismatch = sum(1 for b in bracket_issues if b[0] == "类型不匹配")
    print(f"[问题][格式] 括号不匹配: 缺少闭合 {missing} 处, 多余闭合 {extra} 处, 类型不匹配 {mismatch} 处")
    for bi in bracket_issues:
        if bi[0] == "缺少闭合":
            print(f"  第 {bi[2]} 行: 缺少闭合 {bi[1]}")
        elif bi[0] == "多余闭合":
            print(f"  第 {bi[2]} 行第 {bi[3]} 列: 多余闭合 {bi[1]}")
        else:
            print(f"  第 {bi[2]} 行第 {bi[3]} 列: 类型不匹配 {bi[1]}")

# --- Step 10: 检测未闭合的多行注释 ---
in_str = False
esc = False
in_block = False
block_start_line = 0
line_num = 1

i = 0
while i < len(content):
    c = content[i]

    if c == '\n':
        line_num += 1
        i += 1
        continue

    if in_str:
        if esc:
            esc = False
        elif c == '\\':
            esc = True
        elif c == '"':
            in_str = False
        i += 1
    elif in_block:
        if c == '*' and i + 1 < len(content) and content[i + 1] == '/':
            in_block = False
            i += 2
        else:
            i += 1
    else:
        if c == '"':
            in_str = True
            i += 1
        elif c == '/' and i + 1 < len(content):
            if content[i + 1] == '*':
                in_block = True
                block_start_line = line_num
                i += 2
            elif content[i + 1] == '/':
                while i < len(content) and content[i] != '\n':
                    i += 1
            else:
                i += 1
        else:
            i += 1

if in_block:
    print(f"[问题][格式] 未闭合注释: 第 {block_start_line} 行存在未闭合的 /* 注释")

# --- Step 11: JSON 解析测试 ---
format_ok = True
try:
    json.loads(stripped)
    print("[通过][格式] JSON 格式校验通过")
except (json.JSONDecodeError, ValueError) as e:
    format_ok = False
    print(f"[问题][格式] JSON解析失败: {e}")

# ========== 字段检查（仅格式通过时）==========
field_issues = []

if format_ok:
    data = json.loads(stripped)

    # --- 非法字段检测 ---
    if 'mcpServers' in data:
        field_issues.append("非法字段 mcpServers（应为 mcp）")
        print("[问题][字段] 非法字段: mcpServers（应为 mcp），会导致 Server fatal 退出")

    # --- MCP 字段值校验 ---
    if 'mcp' in data and isinstance(data['mcp'], dict):
        for name, entry in data['mcp'].items():
            if not isinstance(entry, dict):
                field_issues.append(f"mcp.{name} 类型错误（应为对象）")
                print(f"[问题][字段] mcp.{name} 类型错误（应为对象）")
                continue

            # type 校验
            if 'type' in entry:
                if entry['type'] not in ('local', 'remote'):
                    field_issues.append(f"mcp.{name}.type 值不合法: {entry['type']}（应为 local 或 remote）")
                    print(f"[问题][字段] mcp.{name}.type 值不合法: {entry['type']}（应为 local 或 remote）")

            # enabled 类型校验
            if 'enabled' in entry:
                if isinstance(entry['enabled'], str):
                    field_issues.append(f"mcp.{name}.enabled 类型错误: 字符串（应为布尔值）")
                    print(f'[问题][字段] mcp.{name}.enabled 类型错误: "{entry["enabled"]}"（应为布尔值 true/false）')

            # timeout 类型校验
            if 'timeout' in entry:
                val = entry['timeout']
                if isinstance(val, str) or isinstance(val, bool):
                    field_issues.append(f"mcp.{name}.timeout 类型错误（应为正整数）")
                    print(f"[问题][字段] mcp.{name}.timeout 类型错误: {val}（应为正整数毫秒）")
                elif isinstance(val, (int, float)) and val < 1:
                    field_issues.append(f"mcp.{name}.timeout 值不合法: {val}（应为正整数）")
                    print(f"[问题][字段] mcp.{name}.timeout 值不合法: {val}（应为正整数毫秒）")

            # command 类型校验
            if 'command' in entry:
                if not isinstance(entry['command'], list):
                    field_issues.append(f"mcp.{name}.command 类型错误（应为数组）")
                    print(f"[问题][字段] mcp.{name}.command 类型错误: {entry['command']}（应为字符串数组）")

            # environment 类型校验
            if 'environment' in entry:
                if not isinstance(entry['environment'], dict):
                    field_issues.append(f"mcp.{name}.environment 类型错误（应为对象）")
                    print(f'[问题][字段] mcp.{name}.environment 类型错误（应为对象 {{"KEY": "value"}}）')

    # --- permission.skill 值校验 ---
    if 'permission' in data and isinstance(data['permission'], dict) and \
       'skill' in data['permission'] and isinstance(data['permission']['skill'], dict):
        for skill_id, val in data['permission']['skill'].items():
            if val not in ('allow', 'deny'):
                field_issues.append(f"permission.skill.{skill_id} 值不合法: {val}（应为 allow 或 deny）")
                print(f"[问题][字段] permission.skill.{skill_id} 值不合法: {val}（应为 allow 或 deny）")

    if not field_issues:
        print("[通过][字段] 字段校验通过，无非法字段或值类型错误")
else:
    print("[跳过][字段] 格式有误，跳过字段检查")

# ========== 路径检查（仅格式通过时）==========
path_issues = []

if format_ok:
    if 'mcp' in data and isinstance(data['mcp'], dict):
        for name, entry in data['mcp'].items():
            if not isinstance(entry, dict):
                continue

            # 检查 command 路径
            if 'command' in entry and isinstance(entry['command'], list):
                for j, cmd_part in enumerate(entry['command']):
                    if not isinstance(cmd_part, str):
                        continue
                    looks_like_path = ('\\' in cmd_part or
                                       cmd_part.startswith('/') or
                                       cmd_part.startswith('./') or
                                       cmd_part.startswith('~/') or
                                       re.search(r'\.(js|py|ts|exe|cmd|sh)$', cmd_part))
                    if looks_like_path:
                        expanded = os.path.expanduser(os.path.expandvars(cmd_part))
                        if not os.path.exists(expanded):
                            path_issues.append(f"mcp.{name} command[{j}]: {expanded}")
                            print(f"[问题][路径] mcp.{name} | command[{j}] | 路径不存在: {expanded}")

            # 检查 environment.PATH 目录
            if 'environment' in entry and isinstance(entry['environment'], dict) and \
               'PATH' in entry['environment']:
                env_path = entry['environment']['PATH']
                if isinstance(env_path, str):
                    env_parts = [p for p in env_path.replace(';', ':').split(':') if p and not p.startswith('${')]
                    for p in env_parts:
                        expanded_p = os.path.expanduser(os.path.expandvars(p))
                        if not os.path.isdir(expanded_p):
                            path_issues.append(f"mcp.{name} environment.PATH: {expanded_p}")
                            print(f"[问题][路径] mcp.{name} | environment.PATH | 目录不存在: {expanded_p}")

    if not path_issues:
        print("[通过][路径] 路径校验通过，所有路径存在")
else:
    print("[跳过][路径] 格式有误，跳过路径检查")

# ========== 输出汇总 ==========
print()
print("========== 诊断汇总 ==========")

format_problems = (
    (1 if has_bom else 0) +
    (1 if control_found else 0) +
    (1 if fullwidth_found else 0) +
    len(trailing_commas) +
    len(double_commas) +
    len(bracket_issues) +
    (1 if not format_ok else 0)
)

if format_problems == 0 and not field_issues and not path_issues:
    print("[通过] 配置文件检查全部通过，无任何问题")
else:
    suggestions = []
    if has_bom:
        suggestions.append("移除 UTF-8 BOM")
    if control_found:
        suggestions.append("清除控制字符")
    if fullwidth_found:
        suggestions.append("替换全角符号")
    if trailing_commas:
        suggestions.append("移除尾逗号")
    if double_commas:
        suggestions.append("修复连续逗号")
    if bracket_issues:
        suggestions.append("修复括号匹配")
    if not format_ok:
        suggestions.append("修复 JSON 语法")
    if field_issues:
        suggestions.append("修正字段问题")
    if suggestions:
        print(f"[建议] 修复方案: {' + '.join(suggestions)}")
        print("[自动修复] 可通过 fix-teleagent-jsonc 脚本自动修复")
    if path_issues:
        print("[建议] 路径问题需通过 mcp-check-paths / mcp-fix-paths 脚本单独处理")

PYEOF
