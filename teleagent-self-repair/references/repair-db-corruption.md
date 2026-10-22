# 修复方案：数据库文件损坏

> **对应场景**：用户反馈"数据库坏了""数据库异常""定时任务失效""IM渠道授权失效"等
> **典型表现**：定时任务不执行或全部消失、IM渠道授权状态丢失、日志中出现 SQLite 相关错误（database disk image is malformed、database is locked、no such table 等）

---

## 涉及的两个数据库文件

| 数据库文件 | 存储内容 | 关联文件 |
| --- | --- | --- |
| `scheduler.db` | 定时任务定义（jobs 表）、任务执行历史（job_runs 表）、应用元数据（app_meta 表） | `scheduler.db-wal`、`scheduler.db-shm`、`scheduler-daemon-state.json` |
| `im-service.db` | IM 渠道授权配置（im_channel_profile 表，含钉钉/企业微信/飞书等渠道的授权状态和凭证）、IM 消息记录（im_message 表） | `im-service.db-wal`、`im-service.db-shm` |

---

## 数据目录路径

> ⚠️ **TeleAgent 2.6+ 多用户结构**：当前账号数据库位于 `users\<账号ID>\scheduler\` 与 `users\<账号ID>\im-service\` 下，优先用环境变量 `TELEAGENT_DATA_DIR` 定位当前账号数据根。根目录 `~/.local/share/TeleAgent/` 下的同名数据库为旧版残留，**不是修复目标**。

| 操作系统 | 当前账号数据根 |
| --- | --- |
| 全部（2.6+） | `$TELEAGENT_DATA_DIR`（环境变量，最准）→ `%USERPROFILE%\.local\share\TeleAgent\users\<账号ID>\` |
| macOS | `~/.local/share/TeleAgent/users/<账号ID>/` |
| Linux | `~/.local/share/TeleAgent/users/<账号ID>/` |

具体文件路径（相对当前账号数据根）：

| 文件 | 路径 |
| --- | --- |
| scheduler.db | `<数据根>\scheduler\scheduler.db` |
| im-service.db | `<数据根>\im-service\im-service.db` |

> macOS 和 Linux 路径结构完全一致，脚本逻辑相同，合并为一个脚本。

---

## 损坏原因

| 原因 | 说明 |
| --- | --- |
| 非正常退出 | TeleAgent 进程被强杀或崩溃时正在写数据库，WAL 未正常 checkpoint 回主库 |
| 磁盘空间不足 | 写入时磁盘满，导致数据库文件截断 |
| 文件被外部程序篡改 | 杀毒软件、其他进程占用或修改 |
| 系统断电/蓝屏 | 写入中途断电，文件系统损坏 |

---

## 修复前安全检查

| 序号 | 安全检查项 | 确认内容                    |
| --- | --- |-------------------------|
| 1 | 已备份 | 确认待修复文件已创建备份（由修复脚本自动完成） |
| 2 | 红线区 | 数据库文件属于红色区，用户不可自行修改     |
| 3 | 用户知情 | 确认已向用户展示诊断结果并获得修复确认     |
| 4 | 可回滚 | 确认修复失败时可通过备份回滚          |

---

## 修复流程

```
Step 1  运行 db-check 脚本（完整性检测 + 损坏分级）
Step 2  向用户展示诊断结果，等待确认
Step 3  运行 db-repair 脚本（三级修复 + 验证 + 回滚兜底）
Step 4  告知用户重启 TeleAgent 生效
```

---

### Step 1：运行诊断脚本

**Windows：**
```powershell
.\scripts\db-check.ps1
```

**macOS / Linux：**
```bash
chmod +x ./scripts/db-check.sh && ./scripts/db-check.sh
```

脚本执行内容：
1. 定位数据目录（`~/.local/share/TeleAgent/`，找不到时报错退出）
2. 检查 `scheduler.db` 和 `im-service.db` 是否存在
3. 检查文件头：SQLite 文件前 16 字节应为 `SQLite format 3\000`
4. 用 Python `sqlite3` 模块执行 `PRAGMA integrity_check;`
5. 检查 WAL 文件状态（是否存在、大小是否为 0、文件头是否损坏）
6. 输出结构化诊断结果，标注损坏级别

---

### Step 2：向用户展示诊断结果，等待确认

Agent 输出格式：

```
数据库健康检查结果：

| 数据库文件 | 完整性检查 | 损坏级别 | 详情 |
| --- | --- | --- | --- |
| scheduler.db | 失败 | 中度损坏 | WAL文件异常，主库部分表页损坏 |
| im-service.db | 通过 | 未损坏 | — |

建议修复方案：对 scheduler.db 执行第一级修复（WAL恢复），保留主库数据
可自动修复。是否执行修复？[确认 / 拒绝]
```

| 诊断结果 | Agent 行为 |
| --- | --- |
| 两个数据库均正常 | 告知用户数据库未发现损坏，问题可能出在其他地方 |
| 有损坏（用户确认） | 进入 Step 3 运行修复脚本 |
| 有损坏（用户拒绝） | 不修改，告知用户数据库问题仍存在 |

---

### Step 3：运行修复脚本

脚本采用三级修复，逐级尝试，每级修复后自动验证：

**Windows：**
```powershell
.\scripts\db-repair.ps1
```

**macOS / Linux：**
```bash
chmod +x ./scripts/db-repair.sh && ./scripts/db-repair.sh
```

#### 修复前准备

1. **确认 TeleAgent 已关闭**：修复前必须确保数据库文件未被占用
2. **自动备份**：将 `.db`、`.db-wal`、`.db-shm` 三个文件备份到同目录下 `.bak` 后缀文件

#### 第一级：WAL 恢复（轻量修复）

**适用场景**：主库 `.db` 文件完好，但 WAL（`.db-wal`）或共享内存文件（`.db-shm`）损坏。

**操作步骤**：
1. 备份 `.db`、`.db-wal`、`.db-shm` 三个文件
2. 删除 `.db-wal` 和 `.db-shm` 文件（只删这两个，不删主 `.db` 文件）
3. 执行 `PRAGMA integrity_check;` 验证主库

**影响**：WAL 中尚未 checkpoint 的事务会丢失（通常是最近几秒到几分钟的数据），已写入主库的数据不受影响。

**结果判断**：
- 验证通过 → 修复成功
- 验证不通过 → 进入第二级

#### 第二级：数据恢复（中度修复）

**适用场景**：主数据库文件本身损坏，`integrity_check` 返回错误，但文件仍能被 SQLite 部分读取。

**操作步骤**：
1. 备份所有相关文件
2. 用 Python `sqlite3` 模块连接损坏的数据库
3. 执行 `SELECT * FROM sqlite_master;` 检查能否读取表结构
4. 如果能读取，逐表导出 `CREATE TABLE` 语句和 `INSERT` 数据
5. 创建全新的空数据库文件
6. 将导出的表结构和数据写入新数据库
7. 对新数据库执行 `PRAGMA integrity_check;` 验证

**备选方案**（逐表 SELECT 失败时）：
- 尝试用 SQLite 的 `.recover` 命令（通过 Python subprocess 调用，如果系统有 sqlite3 CLI）
- 逐表恢复失败时，尝试只恢复表结构（跳过损坏的行数据）

**影响**：损坏部分的数据可能丢失，未损坏部分的数据可以保留。恢复后的新数据库替换原损坏文件。

**结果判断**：
- 恢复成功且验证通过 → 修复成功
- 恢复失败（无法打开数据库或读取数据） → 进入第三级

#### 第三级：删除重建（终极方案）

**适用场景**：数据库损坏严重，第二级恢复完全失败。

**操作步骤**：
1. **向用户明确告知**：数据库损坏严重，已无法修复，需要删除损坏的数据库文件，重启 TeleAgent 后会自动重建全新空数据库
2. 在用户同意后，备份损坏的文件（以防后续需要）
3. 删除 `.db`、`.db-wal`、`.db-shm` 三个文件
4. 告知用户手动重启 TeleAgent，应用启动时自动创建新的空数据库并初始化表结构

**删除影响说明（必须告知用户）**：

| 删除文件 | 丢失内容 | 重启后影响 | 不受影响的功能 |
| --- | --- | --- | --- |
| `scheduler.db` | 所有定时任务定义、任务执行历史、应用元数据 | 数据库重建为空，需重新创建定时任务 | 对话记录、技能配置、MCP 配置、模型设置、IM渠道配置 |
| `im-service.db` | 所有 IM 渠道授权配置（钉钉/企业微信/飞书等）、IM 消息记录 | 数据库重建为空，需重新配置并授权 IM 渠道 | 对话记录、定时任务、技能配置、MCP 配置、模型设置 |

---

### Step 4：告知用户重启

直接告诉用户：

> 修复完成，**请重启 TeleAgent 使数据库生效**。重启后如果仍有问题，请再次触发本技能做二次诊断。

> Agent 不应直接执行重启命令（会杀死自身进程），只告知用户手动重启。

---

## 修复后验证

用户重启 TeleAgent 后，Agent 再次运行 `db-check` 脚本进行验证：

| 验证项 | 方法 | 预期 |
| --- | --- | --- |
| 数据库文件存在 | 脚本文件检查 | 文件存在 |
| 文件头正确 | 脚本头校验 | `SQLite format 3` |
| 完整性检查通过 | `PRAGMA integrity_check;` | 返回 `ok` |
| WAL 文件状态正常 | 脚本 WAL 检查 | 不存在或大小正常 |
| 功能恢复 | 定时任务/IM渠道功能正常 | 用户确认功能恢复 |

---

## 边界与限制

| 场景 | 处理方式 |
| --- | --- |
| 数据目录不存在 | 报错退出，提示用户检查 TeleAgent 安装 |
| 数据库文件不存在 | 告知用户文件不存在，可能是首次安装尚未创建，建议重启 TeleAgent |
| 数据库被进程占用（修复时） | 报错退出，提示用户先关闭 TeleAgent 再修复 |
| `teleagent.db` 损坏 | 不在本检查项范围内，告知用户联系客服 |
| WAL 文件不存在但主库正常 | 正常状态（WAL 在 checkpoint 后会被删除），不视为损坏 |
| WAL 文件大小为 0 | 可能是异常退出留下的空文件，第一级修复会清理 |
| 第二级恢复部分表成功 | 告知用户哪些表已恢复、哪些表数据丢失，由用户决定是否接受或直接进入第三级 |
| macOS/Linux 设置了自定义 TeleAgent 数据目录 | 脚本优先使用 `TELEAGENT_DATA_DIR` 环境变量（如设置），否则回退到标准路径 |

