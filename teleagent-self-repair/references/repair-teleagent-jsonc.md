# 修复方案：TeleAgent.jsonc 配置文件检查与修复

> **对应场景**：用户在 TeleAgent.jsonc 上添加/删除/修改字段后，重启前主动检查格式是否正确
> **触发方式**：用户说"帮我看看改的对不对"，检查下格式"等
> **重要**：TeleAgent.jsonc 格式错误会导致 TeleAgent 无法启动，届时无法通过本技能修复，只能手动编辑配置文件。因此修改配置后、重启前务必先运行检查。

## 配置文件位置

> ⚠️ **TeleAgent 2.6+ 多用户结构**：配置文件位于 `users\<账号ID>\TeleAgent.jsonc`，优先用环境变量 `TELEAGENT_CONFIG_DIR` 定位当前账号配置根。

| 系统 | 标准路径 |
| --- | --- |
| 全部（2.6+） | `$TELEAGENT_CONFIG_DIR\TeleAgent.jsonc`（环境变量，最准）→ `%USERPROFILE%\.config\TeleAgent\users\<账号ID>\TeleAgent.jsonc` |
| macOS / Linux | `~/.config/TeleAgent/users/<账号ID>/TeleAgent.jsonc` |

> 若设置了 `XDG_CONFIG_HOME` 环境变量（macOS / Linux），则以该变量替代 `~/.config` 作为配置根。
> 标准路径找不到时，搜索配置目录下 `.jsonc`/`.json`/`.jsonc.bak` 疑似文件。

---

## 已知非法字段

| 非法字段 | 正确字段 | 说明 |
| --- | --- | --- |
| `mcpServers` | `mcp` | TeleAgent 使用 `mcp` 而非 `mcpServers`，写入会导致 Server fatal 退出 |

---

## 合法字段值校验规则

| 字段路径 | 合法值 / 类型 | 常见错误 |
| --- | --- | --- |
| `$schema` | 字符串 | 值被改成无效 URL |
| `permission.skill.<技能ID>` | `"allow"` 或 `"deny"` | 值写成 `true`/`"enabled"`/`"yes"` |
| `mcp.<服务器名>.type` | `"local"` 或 `"remote"` | 值缺失或写成 `"Local"`（大小写） |
| `mcp.<服务器名>.command` | 字符串数组 | 写成字符串而非数组，或路径不存在 |
| `mcp.<服务器名>.enabled` | 布尔值 `true`/`false` | 写成 `"true"` 字符串 |
| `mcp.<服务器名>.timeout` | 正整数（毫秒） | 写成字符串或负数 |
| `mcp.<服务器名>.environment` | 对象 `{"KEY": "value"}` | 写成数组或字符串 |
| `mcp.<服务器名>.url` | 字符串 | `type: "remote"` 时缺少 `url` |
| `disabled_providers` | 字符串数组 | 写成对象或逗号分隔字符串 |

---

## 修复前安全检查

| 序号 | 安全检查项 | 确认内容 |
| --- | --- | --- |
| 1 | 已备份 | 确认待修改文件已创建 .bak 备份（由诊断脚本自动完成） |
| 2 | 非红线区 | `TeleAgent.jsonc` 属于黄色区，可修改但需 JSON 校验 |
| 3 | 用户知情 | 确认已向用户展示诊断结果并获得修复确认 |
| 4 | 可回滚 | 确认修复失败时可通过 .bak 备份回滚 |

---

## 修复流程

```
Step 1  运行 check-teleagent-jsonc 脚本（备份 + 诊断）
Step 2  向用户展示诊断结果，等待确认
Step 3  运行 fix-teleagent-jsonc 脚本（修复 + 验证 + 回滚兜底）
Step 4  告知用户重启 TeleAgent 生效
```

---

### Step 1：运行诊断脚本

**Windows：**
```powershell
.\scripts\check-teleagent-jsonc.ps1
```

**macOS / Linux：**
```bash
chmod +x ./scripts/check-teleagent-jsonc.sh && ./scripts/check-teleagent-jsonc.sh
```

脚本执行内容：
1. 定位配置文件（macOS/Linux 优先 `XDG_CONFIG_HOME`，否则回退 `~/.config`；找不到时搜索目录下疑似文件）
2. 自动备份 `TeleAgent.jsonc` 为 `.bak`
3. **格式检查**：检测 UTF-8 BOM、控制字符、全角符号、尾逗号、连续逗号、括号不匹配、未闭合注释、JSON 解析
4. **字段检查**（格式通过后）：检测非法字段（如 `mcpServers`）、字段值类型/取值校验
5. **路径检查**（格式通过后）：校验 MCP `command` 路径和 `environment.PATH` 目录是否存在
6. 输出结构化诊断结果和修复建议

---

### Step 2：向用户展示诊断结果，等待确认

Agent 输出格式：

```
TeleAgent.jsonc 配置诊断结果：

| 检查类别 | 问题类型 | 数量 | 详情 |
| --- | --- | --- | --- |
| 格式 | 全角符号 | 3 | 第8行第12列：：→ : 等 |
| 格式 | 尾逗号 | 2 | 第15行第5列、第23行第10列 |
| 字段 | 非法字段 | 1 | mcpServers（应为 mcp） |
| 字段 | 值类型错误 | 1 | mcp.xxx.enabled: "true"（应为布尔值 true） |
| 路径 | 路径不存在 | 1 | mcp.xxx command[1]: C:\...不存在 |

建议修复方案：替换全角符号 + 移除尾逗号 + 删除非法字段 + 修正值类型
可自动修复。是否执行修复？[确认 / 拒绝]
```

| 用户响应 | Agent 行为 |
| --- | --- |
| 确认 | 进入 Step 3 运行修复脚本 |
| 拒绝 | 不修改，告知用户当前配置仍存在问题 |

---

### Step 3：运行修复脚本

**Windows：**
```powershell
.\scripts\fix-teleagent-jsonc.ps1
```

**macOS / Linux：**
```bash
chmod +x ./scripts/fix-teleagent-jsonc.sh && ./scripts/fix-teleagent-jsonc.sh
```

脚本执行内容：
1. 验证备份文件存在
2. **格式修复**（渐进式，每类修复后尝试 JSON 解析，通过则跳过后续）：
   - 移除 UTF-8 BOM
   - 清除控制字符
   - 替换全角符号（字符串感知：仅替换语法位置，字符串值内保留）
   - 尝试解析 → 通过则跳到字段修复
   - 移除尾逗号（字符串感知 + 注释感知）
   - 修复连续逗号（字符串感知 + 注释感知）
   - 尝试解析 → 通过则跳到字段修复
   - 补全缺少闭合的括号
   - 修复未闭合的多行注释
   - 尝试解析 → 通过则跳到字段修复
3. **字段修复**（格式通过后）：
   - 删除非法字段 `mcpServers`（使用 JSON 解析器安全删除，不用正则）
   - 修正值类型：`"true"`→`true`、`"Local"`→`"local"`、字符串数字→整数等
4. **最终验证**：JSON 格式校验通过则成功，失败则自动从 `.bak` 回滚

**关键特性：**
- 格式修复保留 JSONC 注释（直接操作原始内容，不经过剥离-重写流程）
- 字段修复使用 JSON 解析器操作（注释会丢失，文件转为标准 JSON）
- 每类格式修复后立即验证，尽早停止
- 失败自动回滚到备份

> **关于路径修复**：路径不存在问题由 `mcp-check-paths` / `mcp-fix-paths` 脚本单独处理（需生成修复清单 JSON），参见 `references/repair-mcp-path-error.md`。

---

### Step 4：告知用户重启

直接告诉用户：

> 修复完成，**请重启 TeleAgent 使配置生效**。重启后如果仍有问题，请再次触发本技能做二次诊断。

> Agent 不应直接执行重启命令（会杀死自身进程），只告知用户手动重启。

---

## 修复后验证

用户重启 TeleAgent 后，Agent 再次运行 `check-teleagent-jsonc` 脚本进行验证：

| 验证项 | 方法 | 预期 |
| --- | --- | --- |
| JSON 格式合法 | 脚本输出 `[通过]` | 通过 |
| 无非法字段 | 脚本字段检查输出 `[通过]` | 通过 |
| 字段值正确 | 脚本值校验输出 `[通过]` | 通过 |
| Server 正常启动 | 日志中无 fatal 错误 | 正常 |

---

## 边界与限制

| 场景 | 处理方式 |
| --- | --- |
| 字符串值内的全角符号 | 不替换（字符串感知修复保留原文） |
| 全角引号混入 | 始终替换为半角引号（JSON 语法要求） |
| 尾逗号后有行注释再跟 } | 正确识别为尾逗号并移除 |
| 缺少逗号（相邻键值对间） | 由 JSON 解析失败间接识别，脚本不单独处理此类型 |
| 字段修复后注释丢失 | 使用 JSON 解析器操作字段时注释会丢失，文件转为标准 JSON |
| 配置文件无任何问题 | 输出 `[通过]`，退出 |
| 所有自动修复用尽仍失败 | 回滚到 .bak 备份，输出错误信息，建议用户手动修改 |
| 标准路径找不到配置文件 | 搜索目录下疑似文件，仍找不到则报错退出 |
| macOS/Linux 设置了 `XDG_CONFIG_HOME` | 使用该变量替代 `~/.config` 作为配置目录 |
| 路径不存在问题 | 由 `mcp-check-paths` / `mcp-fix-paths` 单独处理 |
| 场景 A（Agent 修改后检查） | Agent 先按用户意图修改文件，再运行诊断脚本校验格式和字段 |

