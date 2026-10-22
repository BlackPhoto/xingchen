# 修复方案：MCP 配置文件路径写错

> **对应场景**：用户反馈"MCP 连不上""MCP 报错""工具连不上"等
> **典型表现**：MCP Server 进程无法启动，日志中出现 spawn ENOENT 或 path not found

---

## 问题定位

TeleAgent.jsonc 中 `mcp` 段的标准结构：

```jsonc
{
  "mcp": {
    "<server-name>": {
      "type": "local",          // 或 "remote"
      "command": ["<执行器>", "<MCP Server 脚本文件路径>"],
      "enabled": true,          // 默认 true（不写即启用）
      "timeout": 60000,          // 默认 60000（毫秒），即60秒
      "environment": {
        "PATH": "<运行时目录>;${PATH}"
      }
    }
  }
}
```

路径可能写错的位置：

| 位置 | 对应字段 | 说明 |
| --- | --- | --- |
| B | `command[N]` 中的路径元素 | **最常出错**：用户名拼错、从别处拷贝的配置路径对不上 |
| A | `command[0]` 写了绝对路径时 | 执行器路径指向不存在的文件 |
| C | `environment.PATH` 中的目录 | 目录不存在时执行器命令本身找不到 |

> ⚠️ **TeleAgent 2.6+ 多用户结构**：配置文件位于 `当前账号配置根/TeleAgent.jsonc`（即 `users\<账号ID>\TeleAgent.jsonc`），脚本优先用 `TELEAGENT_CONFIG_DIR` 定位当前账号配置根，再在 `mcp` 段校验路径。

### 常见错误模式

| 错误类型 | 典型原因 |
| --- | --- |
| 用户名目录拼错 | 从别人机器拷的配置，用户名不一致 |
| 运行时目录不存在 | 升级/迁移后运行时未解压 |
| npm 包未安装 | 首次使用未装依赖，脚本文件不存在 |
| 跨平台路径格式错误 | Windows 路径拷到 macOS 或反过来 |

---

## 修复前安全检查

| 序号 | 安全检查项 | 确认内容 |
| --- | --- | --- |
| 1 | 已备份 | 确认待修改文件已创建 .bak 备份（由 mcp-check-paths 脚本自动完成） |
| 2 | 非红线区 | `TeleAgent.jsonc` 的 mcp 段属于黄色区，可修改但需 JSON 校验 |
| 3 | 用户知情 | 确认已向用户展示诊断结果并获得修复确认 |
| 4 | 可回滚 | 确认修复失败时可通过 .bak 备份回滚 |

---

## 修复流程

```
Step 1  运行 mcp-check-paths 脚本（自动备份 + 校验 + 推测）
Step 2  向用户展示诊断结果，等待确认
Step 3  生成修复清单 JSON 文件
Step 4  运行 mcp-fix-paths 脚本（写入 + 校验 + 回滚兜底）
Step 5  告知用户重启 TeleAgent 生效
```

---

### Step 1：运行诊断脚本

**Windows：**
```powershell
.\scripts\mcp-check-paths.ps1
```

**macOS / Linux：**
```bash
chmod +x ./scripts/mcp-check-paths.sh && ./scripts/mcp-check-paths.sh
```

脚本执行内容：
1. 定位配置文件（优先 `TELEAGENT_CONFIG_DIR` 环境变量，否则回退 `~/.config/TeleAgent/users/<账号ID>/`；找不到时搜索配置根下 `.jsonc`/`.json`/`.jsonc.bak` 疑似文件）
2. 自动备份 `TeleAgent.jsonc` 为 `.bak`
3. 解析 JSONC，遍历所有 MCP Server（含 local 和 remote 类型）
4. 校验 `command` 数组中所有含路径特征的元素（反斜杠、盘符开头、`/` 开头、脚本扩展名结尾）
5. 校验 `environment.PATH` 中每个目录段（过滤 `${PATH}` 变量引用）
6. 对路径不存在的条目，推测正确路径（用户名替换 / runtimes 目录搜索 / 斜杠修正）
7. 输出结构化诊断结果

---

### Step 2：向用户展示诊断结果，等待确认

Agent 输出格式：

```
MCP 配置路径诊断结果：

| MCP Server | 字段 | 当前错误路径 | 建议修正路径 |
| --- | --- | --- | --- |
| <server-name> | command[1] | <当前错误路径> | <建议修正路径> |

是否按建议路径修复？[确认 / 拒绝 / 手动指定]
```

| 用户响应 | Agent 行为 |
| --- | --- |
| 确认 | 按 Step 3 生成修复清单，进入 Step 4 |
| 拒绝 | 不修改，告知用户当前路径仍存在问题 |
| 手动指定 | 用用户提供的路径覆盖，校验该路径存在后进入 Step 3 |

---

### Step 3：生成修复清单 JSON 文件

Agent 根据用户确认结果，在工作目录下生成修复清单文件 `.temp/mcp-fixes.json`：

```json
[
  {
    "server": "<MCP Server 名称>",
    "field": "command[1]",
    "old_bad": "<当前错误路径>",
    "new_path": "<修正后的路径>"
  }
]
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `server` | MCP Server 名称（对应 mcp 段中的 key） |
| `field` | 需修复的字段：`command[N]` 或 `environment.PATH` |
| `old_bad` | 当前错误路径（原文，用于 environment.PATH 的字符串替换） |
| `new_path` | 修正后的路径 |

---

### Step 4：运行修复脚本

**Windows：**
```powershell
.\scripts\mcp-fix-paths.ps1 -FixesFile .temp\mcp-fixes.json
```

**macOS / Linux：**
```bash
chmod +x ./scripts/mcp-fix-paths.sh && ./scripts/mcp-fix-paths.sh .temp/mcp-fixes.json
```

脚本执行内容：
1. 读取修复清单 JSON 文件
2. 读取 `TeleAgent.jsonc`，解析 JSONC
3. 逐条应用修复（替换 command 元素 / 替换 environment.PATH 中的路径段）
4. 写入文件（注意：JSONC 注释会丢失，转为标准 JSON）
5. JSON 格式校验 — 通过则成功，失败则自动从 .bak 回滚

---

### Step 5：告知用户重启

直接告诉用户：

> 修复完成，**请重启 TeleAgent 使配置生效**。重启后如果 MCP 仍连不上，请再次触发本技能做二次诊断。

> ⚠️ Agent 不应直接执行重启命令（会杀死自身进程），只告知用户手动重启。

---

## 修复后验证

用户重启 TeleAgent 后，Agent 再次运行 `mcp-check-paths` 脚本进行验证：

| 验证项 | 方法 | 预期 |
| --- | --- | --- |
| 所有路径存在 | 脚本输出 `[通过]` | 通过 |
| JSON 格式合法 | 脚本内置校验 | 通过 |
| MCP Server 连接 | 日志中 `MCP server connected` | 已连接 |

---

## 边界与限制

| 场景 | 处理方式 |
| --- | --- |
| `command` 中 `@scope/package` 格式的 npm 包名 | 不视为路径（不含 `\` 或脚本扩展名），不检查 |
| 用户手动指定路径仍不存在 | 提示用户确认路径，拒绝写入 |
| 配置文件无 `mcp` 段 | 输出 `[通过]`，退出 |
| 无法自动推测正确路径 | 标记 `[无法自动推测，需手动确认]`，由用户提供 |
| 标准路径找不到配置文件 | 搜索目录下 `.jsonc`/`.json`/`.jsonc.bak` 疑似文件，仍找不到则报错退出 |
| macOS/Linux 设置了 `XDG_CONFIG_HOME` | 使用该变量替代 `~/.config` 作为配置目录 |
