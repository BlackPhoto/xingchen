#!/bin/bash
# ============================================================
# TeleAgent.jsonc 配置文件修复脚本 (macOS / Linux，依赖 Python 3.6+)
# ============================================================
# 功能：格式修复（渐进式）→ 字段修复 → 验证 → 回滚兜底
# 用法：./fix-teleagent-jsonc.sh
# 前置：需先运行 check-teleagent-jsonc.sh 创建备份
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

# ========== 格式修复 ==========

# --- 修复 1: 移除 UTF-8 BOM ---
if len(raw_bytes) >= 3 and raw_bytes[0] == 0xEF and raw_bytes[1] == 0xBB and raw_bytes[2] == 0xBF:
    new_bytes = raw_bytes[3:]
    with open(jsonc_file, 'wb') as f:
        f.write(new_bytes)
    content = new_bytes.decode('utf-8')
    raw_bytes = new_bytes
    fixes_applied.append("移除 UTF-8 BOM")
    print("[修复][格式] 移除 UTF-8 BOM")

# --- 修复 2: 清除控制字符 ---
control_pattern = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1F]')
control_matches = control_pattern.findall(content)
if control_matches:
    content = control_pattern.sub('', content)
    with open(jsonc_file, 'w', encoding='utf-8') as f:
        f.write(content)
    fixes_applied.append(f"清除 {len(control_matches)} 个控制字符")
    print(f"[修复][格式] 清除 {len(control_matches)} 个控制字符")

# --- 修复 3: 替换全角符号（字符串外）---
fullwidth_map = {
    '\uff0c': ',', '\uff1a': ':', '\u201c': '"', '\u201d': '"',
    '\uff08': '(', '\uff09': ')', '\uff3b': '[', '\uff3d': ']',
    '\uff5b': '{', '\uff5d': '}', '\uff1b': ';',
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
    print(f"[修复][格式] 替换 {fullwidth_count} 处全角符号")

# --- 尝试解析 → 成功则跳到字段修复 ---
format_fixed = test_json_parse(content)
if format_fixed:
    print("[通过][格式] 修复后 JSON 格式校验通过")

if not format_fixed:
    # --- 修复 4: 移除尾逗号（字符串外，保留原始注释）---
    result_chars = []
    in_str = False; esc = False; trailing_count = 0; i = 0

    while i < len(content):
        c = content[i]

        if in_str:
            result_chars.append(c)
            if esc: esc = False
            elif c == '\\': esc = True
            elif c == '"': in_str = False
            i += 1; continue

        if c == '"':
            in_str = True; result_chars.append(c); i += 1; continue

        if c == ',':
            j = i + 1
            while j < len(content):
                if content[j].isspace():
                    j += 1
                elif content[j] == '/' and j + 1 < len(content) and content[j + 1] == '/':
                    while j < len(content) and content[j] != '\n':
                        j += 1
                elif content[j] == '/' and j + 1 < len(content) and content[j + 1] == '*':
                    j += 2
                    while j < len(content):
                        if content[j] == '*' and j + 1 < len(content) and content[j + 1] == '/':
                            j += 2; break
                        j += 1
                else:
                    break
            if j < len(content) and content[j] in ('}', ']'):
                trailing_count += 1; i += 1; continue
            result_chars.append(c); i += 1; continue

        result_chars.append(c); i += 1

    if trailing_count > 0:
        content = ''.join(result_chars)
        with open(jsonc_file, 'w', encoding='utf-8') as f:
            f.write(content)
        fixes_applied.append(f"移除 {trailing_count} 处尾逗号")
        print(f"[修复][格式] 移除 {trailing_count} 处尾逗号")

    format_fixed = test_json_parse(content)
    if format_fixed:
        print("[通过][格式] 修复后 JSON 格式校验通过")

if not format_fixed:
    # --- 修复 5: 修复连续逗号（字符串外，注释感知）---
    result_chars = []
    in_str = False; esc = False; prev_comma = False; double_count = 0; i = 0

    while i < len(content):
        c = content[i]

        if in_str:
            result_chars.append(c)
            if esc: esc = False
            elif c == '\\': esc = True
            elif c == '"': in_str = False
            prev_comma = False; i += 1; continue

        if c == '"':
            in_str = True; prev_comma = False; result_chars.append(c); i += 1; continue

        if c == '/' and i + 1 < len(content) and content[i + 1] == '/':
            while i < len(content) and content[i] != '\n':
                result_chars.append(content[i]); i += 1
            prev_comma = False; continue

        if c == '/' and i + 1 < len(content) and content[i + 1] == '*':
            result_chars.append(content[i]); result_chars.append(content[i + 1]); i += 2
            while i < len(content):
                if content[i] == '*' and i + 1 < len(content) and content[i + 1] == '/':
                    result_chars.append(content[i]); result_chars.append(content[i + 1]); i += 2; break
                result_chars.append(content[i]); i += 1
            prev_comma = False; continue

        if c == ',':
            if prev_comma:
                double_count += 1; i += 1; continue
            prev_comma = True
        elif not c.isspace():
            prev_comma = False

        result_chars.append(c); i += 1

    if double_count > 0:
        content = ''.join(result_chars)
        with open(jsonc_file, 'w', encoding='utf-8') as f:
            f.write(content)
        fixes_applied.append(f"修复 {double_count} 处连续逗号")
        print(f"[修复][格式] 修复 {double_count} 处连续逗号")

    format_fixed = test_json_parse(content)
    if format_fixed:
        print("[通过][格式] 修复后 JSON 格式校验通过")

if not format_fixed:
    # --- 修复 6: 补全缺少闭合的括号 ---
    stack = []
    in_str = False; esc = False
    stripped = strip_jsonc_preserve_position(content)

    for c in stripped:
        if in_str:
            if esc: esc = False
            elif c == '\\': esc = True
            elif c == '"': in_str = False
        else:
            if c == '"': in_str = True
            elif c in ('{', '['): stack.append(c)
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
        print(f"[修复][格式] 补全 {len(stack)} 个闭合括号: {closers}")

    format_fixed = test_json_parse(content)
    if format_fixed:
        print("[通过][格式] 修复后 JSON 格式校验通过")

if not format_fixed:
    # --- 修复 7: 修复未闭合的多行注释 ---
    in_str = False; esc = False; in_block = False; i = 0

    while i < len(content):
        c = content[i]

        if in_str:
            if esc: esc = False
            elif c == '\\': esc = True
            elif c == '"': in_str = False
            i += 1
        elif in_block:
            if c == '*' and i + 1 < len(content) and content[i + 1] == '/':
                in_block = False; i += 2
            else:
                i += 1
        else:
            if c == '"': in_str = True; i += 1
            elif c == '/' and i + 1 < len(content):
                if content[i + 1] == '*':
                    in_block = True; i += 2
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
        print("[修复][格式] 修复未闭合注释: 在末尾追加 */")

    format_fixed = test_json_parse(content)
    if format_fixed:
        print("[通过][格式] 修复后 JSON 格式校验通过")

# --- 格式修复全部用尽仍失败 → 回滚 ---
if not format_fixed:
    print("[失败][格式] 自动修复后仍无法通过 JSON 格式校验")
    shutil.copy2(jsonc_file + ".bak", jsonc_file)
    print(f"[回滚] 已恢复备份文件: {jsonc_file}.bak")
    print("[建议] 请手动编辑配置文件修复格式错误")
    sys.exit(1)

# ========== 字段修复 ==========

# 剥离注释并解析 JSON（注释会丢失，文件转为标准 JSON）
stripped = strip_jsonc_preserve_position(content)
data = json.loads(stripped)
field_fixed = False

# --- 字段修复 1: 移除/重命名非法字段 mcpServers ---
if 'mcpServers' in data:
    if 'mcp' not in data:
        # mcp 不存在：将 mcpServers 重命名为 mcp
        data['mcp'] = data.pop('mcpServers')
        field_fixed = True
        fixes_applied.append("重命名非法字段 mcpServers -> mcp")
        print("[修复][字段] 重命名非法字段 mcpServers -> mcp")
    else:
        # mcp 已存在：删除 mcpServers
        del data['mcpServers']
        field_fixed = True
        fixes_applied.append("删除非法字段 mcpServers（mcp 已存在）")
        print("[修复][字段] 删除非法字段 mcpServers（mcp 已存在，请确认 MCP 配置）")

# --- 字段修复 2: 修正 MCP 字段值类型 ---
if 'mcp' in data and isinstance(data['mcp'], dict):
    for name, entry in list(data['mcp'].items()):
        if not isinstance(entry, dict):
            continue

        # type 大小写修正
        if 'type' in entry and isinstance(entry['type'], str):
            lower_type = entry['type'].lower()
            if entry['type'] != lower_type and lower_type in ('local', 'remote'):
                old_val = entry['type']
                entry['type'] = lower_type
                field_fixed = True
                fixes_applied.append(f"mcp.{name}.type 大小写修正: {old_val} -> {lower_type}")
                print(f"[修复][字段] mcp.{name}.type 大小写修正: {old_val} -> {lower_type}")

        # enabled 字符串 → 布尔值
        if 'enabled' in entry and isinstance(entry['enabled'], str):
            old_val = entry['enabled']
            lower_enabled = old_val.lower()
            if lower_enabled in ('true', 'yes', '1', 'enabled'):
                entry['enabled'] = True
            elif lower_enabled in ('false', 'no', '0', 'disabled', ''):
                entry['enabled'] = False
            else:
                entry['enabled'] = True
            field_fixed = True
            fixes_applied.append(f'mcp.{name}.enabled 类型修正: "{old_val}" -> {entry["enabled"]}')
            print(f'[修复][字段] mcp.{name}.enabled 类型修正: "{old_val}" -> {entry["enabled"]}')

        # timeout 字符串/浮点/布尓 → 正整数
        if 'timeout' in entry:
            val = entry['timeout']
            if isinstance(val, str):
                old_val = val
                try:
                    entry['timeout'] = int(val)
                except ValueError:
                    entry['timeout'] = 30000
                field_fixed = True
                fixes_applied.append(f'mcp.{name}.timeout 类型修正: "{old_val}" -> {entry["timeout"]}')
                print(f'[修复][字段] mcp.{name}.timeout 类型修正: "{old_val}" -> {entry["timeout"]}')
            elif isinstance(val, bool):
                entry['timeout'] = 30000
                field_fixed = True
                fixes_applied.append(f"mcp.{name}.timeout 类型修正: {val} -> 30000")
                print(f"[修复][字段] mcp.{name}.timeout 类型修正: {val} -> 30000")
            elif isinstance(val, float):
                entry['timeout'] = int(val)
                field_fixed = True
                fixes_applied.append(f"mcp.{name}.timeout 类型修正: {val} -> {entry['timeout']}")
                print(f"[修复][字段] mcp.{name}.timeout 类型修正: {val} -> {entry['timeout']}")
            elif isinstance(val, int) and val < 1:
                entry['timeout'] = 30000
                field_fixed = True
                fixes_applied.append(f"mcp.{name}.timeout 值修正: {val} -> 30000")
                print(f"[修复][字段] mcp.{name}.timeout 值修正: {val} -> 30000")

        # command 字符串 → 数组
        if 'command' in entry and not isinstance(entry['command'], list):
            old_val = entry['command']
            entry['command'] = [str(old_val)]
            field_fixed = True
            fixes_applied.append(f"mcp.{name}.command 类型修正: 字符串 -> 数组")
            print(f"[修复][字段] mcp.{name}.command 类型修正: {old_val} -> 数组")

        # environment 非对象 → 删除（无法安全转换）
        if 'environment' in entry and not isinstance(entry['environment'], dict):
            del entry['environment']
            field_fixed = True
            fixes_applied.append(f"mcp.{name}.environment 类型错误，已删除（无法安全转换）")
            print(f"[修复][字段] mcp.{name}.environment 类型错误，已删除（无法安全转换）")

# --- 字段修复 3: 修正 permission.skill 值 ---
if 'permission' in data and isinstance(data['permission'], dict) and \
   'skill' in data['permission'] and isinstance(data['permission']['skill'], dict):
    for skill_id in list(data['permission']['skill'].keys()):
        val = data['permission']['skill'][skill_id]
        if val not in ('allow', 'deny'):
            old_val = val
            if isinstance(val, bool):
                data['permission']['skill'][skill_id] = 'allow' if val else 'deny'
            else:
                lower_val = str(val).lower()
                if lower_val in ('true', 'yes', 'enabled', '1'):
                    data['permission']['skill'][skill_id] = 'allow'
                elif lower_val in ('false', 'no', 'disabled', '0'):
                    data['permission']['skill'][skill_id] = 'deny'
                else:
                    data['permission']['skill'][skill_id] = 'allow'
            field_fixed = True
            fixes_applied.append(
                f"permission.skill.{skill_id} 值修正: {old_val} -> {data['permission']['skill'][skill_id]}"
            )
            print(
                f"[修复][字段] permission.skill.{skill_id} 值修正: "
                f"{old_val} -> {data['permission']['skill'][skill_id]}"
            )

# --- 序列化回写 ---
if field_fixed:
    json_output = json.dumps(data, indent=2, ensure_ascii=False)
    with open(jsonc_file, 'w', encoding='utf-8') as f:
        f.write(json_output)
    print("[信息][字段] 字段修复完成，文件已转为标准 JSON（注释丢失）")

# --- 最终验证 ---
with open(jsonc_file, 'r', encoding='utf-8') as f:
    final_content = f.read()

if test_json_parse(final_content):
    print()
    print("========== 修复汇总 ==========")
    if fixes_applied:
        print(f"[完成] 已应用修复: {', '.join(fixes_applied)}")
    else:
        print("[完成] 无需修复，配置文件已通过所有检查")
    sys.exit(0)
else:
    print("[失败] 修复后仍无法通过 JSON 格式校验")
    shutil.copy2(jsonc_file + ".bak", jsonc_file)
    print(f"[回滚] 已恢复备份文件: {jsonc_file}.bak")
    print("[建议] 请手动编辑配置文件修复问题")
    sys.exit(1)

PYEOF
