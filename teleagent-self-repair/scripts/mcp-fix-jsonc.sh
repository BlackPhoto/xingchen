#!/bin/bash
# ============================================================
# MCP JSONC 格式修复脚本 (macOS / Linux，依赖 Python 3.6+)
# ============================================================
# 功能：自动修复 JSONC 格式错误（备份 → 修复 → 验证 → 回滚兜底）
# 用法：./mcp-fix-jsonc.sh
# 前置：需先运行 mcp-check-jsonc.sh 创建备份
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
import json, os, sys, shutil, glob, re

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
    print(f"[错误] 配置文件不存在: {config_dir}")
    sys.exit(1)

# --- 验证备份存在 ---
if not os.path.exists(jsonc_file + ".bak"):
    print("[信息] 未找到备份文件，先创建备份")
    shutil.copy2(jsonc_file, jsonc_file + ".bak")

print(f"[信息] 配置文件: {jsonc_file}")
print(f"[信息] 备份文件: {jsonc_file}.bak")


# --- 辅助函数 ---
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


def test_json_parse(text):
    """剥离注释后尝试 JSON 解析，成功返回 True"""
    try:
        json.loads(strip_jsonc_preserve_position(text))
        return True
    except (json.JSONDecodeError, ValueError):
        return False


# --- 读取内容 ---
with open(jsonc_file, 'rb') as f:
    raw_bytes = f.read()

with open(jsonc_file, 'r', encoding='utf-8') as f:
    content = f.read()

fixes_applied = []

# --- 修复 1: 移除 UTF-8 BOM ---
if len(raw_bytes) >= 3 and raw_bytes[0] == 0xEF and raw_bytes[1] == 0xBB and raw_bytes[2] == 0xBF:
    new_bytes = raw_bytes[3:]
    with open(jsonc_file, 'wb') as f:
        f.write(new_bytes)
    content = new_bytes.decode('utf-8')
    raw_bytes = new_bytes
    fixes_applied.append("移除 UTF-8 BOM")
    print("[修复] 移除 UTF-8 BOM")

# --- 修复 2: 清除控制字符 ---
control_pattern = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1F]')
control_matches = control_pattern.findall(content)
if control_matches:
    content = control_pattern.sub('', content)
    with open(jsonc_file, 'w', encoding='utf-8') as f:
        f.write(content)
    fixes_applied.append(f"清除 {len(control_matches)} 个控制字符")
    print(f"[修复] 清除 {len(control_matches)} 个控制字符")

# --- 修复 3: 替换全角符号（字符串外）---
fullwidth_map = {
    '\uff0c': ',',
    '\uff1a': ':',
    '\u201c': '"',
    '\u201d': '"',
    '\uff08': '(',
    '\uff09': ')',
    '\uff3b': '[',
    '\uff3d': ']',
    '\uff5b': '{',
    '\uff5d': '}',
    '\uff1b': ';',
}

chars = list(content)
fullwidth_count = 0
in_str = False
esc = False

for i, c in enumerate(chars):
    if in_str:
        if esc:
            esc = False
        elif c == '\\':
            esc = True
        elif c == '"':
            in_str = False
        continue

    if c == '"':
        in_str = True
        continue

    if c in fullwidth_map:
        chars[i] = fullwidth_map[c]
        fullwidth_count += 1

if fullwidth_count > 0:
    content = ''.join(chars)
    with open(jsonc_file, 'w', encoding='utf-8') as f:
        f.write(content)
    fixes_applied.append(f"替换 {fullwidth_count} 处全角符号")
    print(f"[修复] 替换 {fullwidth_count} 处全角符号")

# --- 尝试解析 → 成功则结束 ---
if test_json_parse(content):
    print("[通过] 修复后 JSON 格式校验通过")
    print(f"[完成] 已应用修复: {', '.join(fixes_applied)}")
    sys.exit(0)

# --- 修复 4: 移除尾逗号（字符串外，保留原始注释）---
# 逐字符扫描原始内容，字符串外遇到逗号时跳过空白和注释看后面是否紧跟 } 或 ]
result_chars = []
in_str = False
esc = False
trailing_count = 0
i = 0

while i < len(content):
    c = content[i]

    if in_str:
        result_chars.append(c)
        if esc:
            esc = False
        elif c == '\\':
            esc = True
        elif c == '"':
            in_str = False
        i += 1
        continue

    if c == '"':
        in_str = True
        result_chars.append(c)
        i += 1
        continue

    if c == ',':
        # 向后查找：跳过空白和注释
        j = i + 1
        is_trailing = False
        while j < len(content):
            if content[j].isspace():
                j += 1
            elif content[j] == '/' and j + 1 < len(content) and content[j + 1] == '/':
                # 跳过单行注释
                while j < len(content) and content[j] != '\n':
                    j += 1
            elif content[j] == '/' and j + 1 < len(content) and content[j + 1] == '*':
                # 跳过多行注释
                j += 2
                while j < len(content):
                    if content[j] == '*' and j + 1 < len(content) and content[j + 1] == '/':
                        j += 2
                        break
                    j += 1
            else:
                break
        if j < len(content) and content[j] in ('}', ']'):
            # 尾逗号：跳过不写入
            trailing_count += 1
            i += 1
            continue

    result_chars.append(c)
    i += 1

if trailing_count > 0:
    content = ''.join(result_chars)
    with open(jsonc_file, 'w', encoding='utf-8') as f:
        f.write(content)
    fixes_applied.append(f"移除 {trailing_count} 处尾逗号")
    print(f"[修复] 移除 {trailing_count} 处尾逗号")

# --- 尝试解析 → 成功则结束 ---
if test_json_parse(content):
    print("[通过] 修复后 JSON 格式校验通过")
    print(f"[完成] 已应用修复: {', '.join(fixes_applied)}")
    sys.exit(0)

# --- 修复 5: 修复连续逗号（字符串外，注释感知，将 ,, 合并为 ,）---
result_chars = []
in_str = False
esc = False
prev_comma = False
double_count = 0
i = 0

while i < len(content):
    c = content[i]

    if in_str:
        result_chars.append(c)
        if esc:
            esc = False
        elif c == '\\':
            esc = True
        elif c == '"':
            in_str = False
        prev_comma = False
        i += 1
        continue

    if c == '"':
        in_str = True
        prev_comma = False
        result_chars.append(c)
        i += 1
        continue

    # 跳过单行注释（注释内容不参与逗号判断）
    if c == '/' and i + 1 < len(content) and content[i + 1] == '/':
        while i < len(content) and content[i] != '\n':
            result_chars.append(content[i])
            i += 1
        prev_comma = False
        continue

    # 跳过多行注释
    if c == '/' and i + 1 < len(content) and content[i + 1] == '*':
        result_chars.append(content[i])
        result_chars.append(content[i + 1])
        i += 2
        while i < len(content):
            if content[i] == '*' and i + 1 < len(content) and content[i + 1] == '/':
                result_chars.append(content[i])
                result_chars.append(content[i + 1])
                i += 2
                break
            result_chars.append(content[i])
            i += 1
        prev_comma = False
        continue

    if c == ',':
        if prev_comma:
            # 连续逗号：跳过第二个
            double_count += 1
            i += 1
            continue
        prev_comma = True
    elif not c.isspace():
        prev_comma = False

    result_chars.append(c)
    i += 1

if double_count > 0:
    content = ''.join(result_chars)
    with open(jsonc_file, 'w', encoding='utf-8') as f:
        f.write(content)
    fixes_applied.append(f"修复 {double_count} 处连续逗号")
    print(f"[修复] 修复 {double_count} 处连续逗号")

# --- 尝试解析 → 成功则结束 ---
if test_json_parse(content):
    print("[通过] 修复后 JSON 格式校验通过")
    print(f"[完成] 已应用修复: {', '.join(fixes_applied)}")
    sys.exit(0)

# --- 修复 6: 补全缺少闭合的括号 ---
stack = []
in_str = False
esc = False
stripped = strip_jsonc_preserve_position(content)

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
            stack.append(c)
        elif c in ('}', ']'):
            if stack:
                top = stack[-1]
                expected = '{' if c == '}' else '['
                if top == expected:
                    stack.pop()

if stack:
    closers = ''.join('}' if c == '{' else ']' for c in reversed(stack))
    content = content.rstrip() + '\n' + closers + '\n'
    with open(jsonc_file, 'w', encoding='utf-8') as f:
        f.write(content)
    fixes_applied.append(f"补全 {len(stack)} 个闭合括号")
    print(f"[修复] 补全 {len(stack)} 个闭合括号: {closers}")

# --- 尝试解析 → 成功则结束 ---
if test_json_parse(content):
    print("[通过] 修复后 JSON 格式校验通过")
    print(f"[完成] 已应用修复: {', '.join(fixes_applied)}")
    sys.exit(0)

# --- 修复 7: 修复未闭合的多行注释 ---
in_str = False
esc = False
in_block = False
i = 0

while i < len(content):
    c = content[i]

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
                i += 2
            elif content[i + 1] == '/':
                while i < len(content) and content[i] != '\n':
                    i += 1
            else:
                i += 1
        else:
            i += 1

if in_block:
    content = content.rstrip() + '\n*/\n'
    with open(jsonc_file, 'w', encoding='utf-8') as f:
        f.write(content)
    fixes_applied.append("修复未闭合注释")
    print("[修复] 修复未闭合注释: 在末尾追加 */")

# --- 最终验证 ---
if test_json_parse(content):
    print("[通过] 修复后 JSON 格式校验通过")
    print(f"[完成] 已应用修复: {', '.join(fixes_applied)}")
    sys.exit(0)

# --- 所有自动修复用尽，回滚 ---
print("[失败] 自动修复后仍无法通过 JSON 格式校验")
shutil.copy2(jsonc_file + ".bak", jsonc_file)
print(f"[回滚] 已恢复备份文件: {jsonc_file}.bak")
print("[建议] 请手动编辑配置文件修复格式错误")
sys.exit(1)

PYEOF
