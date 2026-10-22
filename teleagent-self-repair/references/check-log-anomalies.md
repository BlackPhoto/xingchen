# 修复方案：日志异常检测与处置

> **对应场景**：用户反馈 TeleAgent 出错、崩溃、闪退或启动失败时，通过查看日志定位异常原因
> **触发方式**：用户说"我的 TeleAgent 出错了""刚才崩了""刚才闪退了""刚才启动没成功""有没有异常"等
> **重要**：本检查项只做日志检测和原因告知，不直接修改任何文件。Agent 根据检测结果判断影响并告知用户后续操作。

---

## 触发条件

用户说出以下任一意图时触发：

| 触发表述 | 实际意图 |
| --- | --- |
| "我的 TeleAgent 出错了" | 不确定哪里有问题，要求排查 |
| "刚才崩了 / 刚才闪退了" | 运行中突然退出 |
| "刚才启动没成功" | 启动失败 |
| "有没有异常" | 想确认最近运行状态 |

---

## 两种检测场景

| 场景 | 检测方法 | 脚本行为 |
| --- | --- | --- |
| 场景A：最近一次启动失败 | 日志中最后一次启动标记后未出现成功标记，或启动标记后紧跟随 fatal/exit | 扫描日志末尾段，判断启动流程是否完整 |
| 场景B：最近有 fatal/crash/panic 错误 | 在日志最近时间窗口内搜索 `fatal` `crash` `panic` `FATAL ERROR` `uncaughtException` `Segmentation fault` 等关键词 | 命中后提取上下文信息 |

---

## 日志位置（跨平台，自动搜索）

> ⚠️ **TeleAgent 2.6+ 多用户结构**：当前账号日志位于 `users\<账号ID>\log\`（单数 `log`）子目录。优先使用环境变量 `SUPER_AGENT_LOG_DIR` 精确定位，否则回退到账号数据目录下的 `log\`。脚本不做硬编码，按优先级依次搜索多个可能路径，命中即用：

| 系统 | 候选路径（按优先级） |
| --- | --- |
| 全部 | `$SUPER_AGENT_LOG_DIR`（环境变量，最准）→ `<当前账号数据根>/log/`（即 `users\<账号ID>\log\`）→ 兜底搜索 `%LOCALAPPDATA%\TeleAgent\` / `%USERPROFILE%\.local\share\TeleAgent\` / `%APPDATA%\TeleAgent\` |
| macOS | `~/Library/Logs/TeleAgent/` → `~/Library/Application Support/TeleAgent/` → `~/.local/share/TeleAgent/users/<账号ID>/log/` |
| Linux | `~/.local/share/TeleAgent/users/<账号ID>/log/` → `~/.config/TeleAgent/` |

日志文件识别：优先找最新修改的 `.log` 文件（主日志，如 `super-agent-server-*.log`、`super-agent-runtime.log`），同时检查是否存在 `runtime/` 子目录（runtime 日志）。若存在多个日志文件，取最近修改的。

---

## 修复前安全检查

| 序号 | 安全检查项 | 确认内容 |
| --- | --- | --- |
| 1 | 只读操作 | 本检查项仅读取日志文件，不修改任何文件，无需备份 |
| 2 | 非红线区 | 日志检测属于绿色区（纯只读），无需安全确认即可执行 |
| 3 | 用户知情 | 检测结果需向用户展示，由 Agent 判断影响并告知 |

---

## 检测流程

```
Step 1  运行 check-log-anomalies 脚本（定位日志 → 扫描异常 → 提取原因 → 输出结果）
Step 2  Agent 根据脚本结果，判断对当前 TeleAgent 有没有影响
Step 3  按影响情况告知用户
```

---

### Step 1：运行检测脚本

**Windows：**
```powershell
.\scripts\check-log-anomalies.ps1
```

**macOS / Linux：**
```bash
chmod +x ./scripts/check-log-anomalies.sh && ./scripts/check-log-anomalies.sh
```

脚本执行内容：
1. 定位日志文件（多路径候选搜索，取最新修改的 `.log` 文件）
2. 读取日志末尾（最后 2000 行），避免全量读取大文件
3. 确定最近一次启动记录的位置（匹配 `app ready` / `Server started` / `listening` 等成功标记）
4. 扫描最近时间窗口内的异常关键词（`fatal` `crash` `panic` `FATAL ERROR` `uncaughtException` `Segmentation fault` 等）
5. 提取异常上下文信息（异常类型 + 相关日志片段）
6. 输出结构化诊断结果（JSON 格式，供 Agent 解析）

---

### Step 2：Agent 判断影响

脚本输出异常信息后，Agent 判断当前 TeleAgent 是否正常运行。

**判断依据**：用户能触发本技能（即能与 Agent 对话），说明当前 TeleAgent 可用，属于"没有影响"。若用户明确表示当前无法正常使用 TeleAgent（如功能异常、反复闪退），属于"有影响"。

| 判断结果 | 条件                        |
| --- |---------------------------|
| 没有影响 | 当前 TeleAgent 正在运行且用户能正常交流 |
| 有影响 | 用户明确表示当前 TeleAgent 部分功能异常 |

---

### Step 3：告知用户

**情况一：没有影响（当前 TeleAgent 正常运行）**

告知用户：

> 上一次 TeleAgent 没能正常打开，原因是：[日志中的具体原因]。目前 TeleAgent 运行正常，上次的问题没有对当前使用造成影响。

**情况二：有影响（当前 TeleAgent 无法正常使用或功能异常）**

告知用户：

> 上一次 TeleAgent 没能正常打开，原因是：[日志中的具体原因]。非常抱歉，这个问题还没有添加到 TeleAgent 自我修复的 skill 中，无法确定具体原因，建议您重启电脑后重新打开 TeleAgent，若还有问题，可联系客服支持。

---

## 脚本设计

- **check-log-anomalies.ps1**（Windows，PowerShell 5.1+）
- **check-log-anomalies.sh**（macOS/Linux 合并，Bash）

macOS 和 Linux 合并为一个 `.sh`，通过 `uname -s` 判断系统动态选择候选路径。macOS 有 `~/Library` 系列路径，Linux 没有，脚本内部按系统区分。

脚本职责：
1. 定位日志文件（多路径候选搜索）
2. 确定最近一次启动记录的位置
3. 扫描最近时间窗口内的异常关键词
4. 提取异常上下文信息（异常类型 + 相关日志片段）
5. 输出结构化诊断结果（JSON 格式，供 Agent 解析）

脚本**只负责检测**，不负责修复。修复处置完全由 Agent 根据上述流程与用户沟通完成。

脚本输出 JSON 格式：

```json
{
  "status": "normal | anomaly_found | no_log | empty_log",
  "log_file": "/path/to/TeleAgent.log",
  "last_start_status": "success | failed | unknown",
  "anomalies": [
    {
      "type": "fatal | crash | panic | uncaughtException | ...",
      "timestamp": "2026-08-01T10:23:45.123Z",
      "message": "FATAL ERROR: ...",
      "context": "相关日志片段（前后各3行）"
    }
  ],
  "summary": "最近一次启动失败的异常原因概述"
}
```

| 字段 | 说明 |
| --- | --- |
| `status` | `normal`（无异常）/ `anomaly_found`（发现异常）/ `no_log`（找不到日志）/ `empty_log`（日志为空） |
| `log_file` | 实际使用的日志文件路径 |
| `last_start_status` | 最近一次启动是否成功：`success` / `failed` / `unknown`（无法判断） |
| `anomalies` | 异常列表，每项含类型、时间戳、消息、上下文 |
| `summary` | 异常原因的一行概述，供 Agent 直接引用告知用户 |

---

## 边界与限制

| 场景 | 处理方式 |
| --- | --- |
| 找不到日志文件 | 输出 `status: no_log`，提示用户检查 TeleAgent 是否曾正常安装 |
| 日志为空 | 输出 `status: empty_log`，告知用户未检测到日志内容，无法诊断 |
| 日志中没有启动标记 | `last_start_status` 输出 `unknown`，仅执行关键词搜索 |
| 日志中没有异常关键词 | 输出 `status: normal`，告知用户未检测到异常 |
| 日志文件过大 | 脚本只读取末尾 2000 行 + 从最近启动标记处开始扫描，避免全量读取 |
| 匹配到异常但当前正常运行 | 走"没有影响"流程，告知原因 + 当前正常 |
| 匹配到异常且当前无法使用 | 走"有影响"流程，告知原因 + 建议重启电脑 |
| Agent 无法判断当前是否正常运行 | 默认走"有影响"流程，保守处理 |

