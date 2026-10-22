# 修复方案：磁盘空间清理

> **对应场景**：用户反馈"磁盘空间不足""C盘满了""电脑运行卡慢""想清理垃圾文件""想清理缓存"等，或 TeleAgent 因磁盘空间不足导致写入失败、数据库报错等问题
> **典型表现**：系统盘剩余空间不足、TeleAgent 写入文件失败（数据库错误、日志写入失败、下载失败）、运行卡顿
> **重要**：本检查项的脚本只负责**检测和评估**，不直接删除任何文件。清理操作由 Agent 在获得用户确认后执行。

---

## 触发条件

用户说出以下任一意图时触发：

| 触发表述 | 实际意图 |
| --- | --- |
| "磁盘空间不足" / "C盘满了" | 系统盘空间告急，想释放 |
| "电脑太卡 / 运行慢" | 怀疑垃圾文件堆积影响性能 |
| "想清理缓存 / 清理垃圾文件" | 主动要求清理 |
| "TeleAgent 写入失败 / 数据库报错" | 间接因磁盘空间不足导致 |

---

## 扫描范围（跨平台）

本检查项对用户电脑进行**整体检查**，覆盖系统级、应用级和 TeleAgent 相关目录。

### Windows 扫描项

| 类别 | 路径 |
| --- | --- |
| 系统临时文件 | `%TEMP%`（`C:\Users\<用户名>\AppData\Local\Temp`） |
| 回收站 | `C:\$Recycle.Bin` |
| Windows 更新缓存 | `C:\Windows\SoftwareDistribution\Download` |
| Windows 旧版本备份 | `C:\Windows.old` |
| Windows 错误报告 | `C:\ProgramData\Microsoft\Windows\WER` |
| 缩略图缓存 | `%LOCALAPPDATA%\Microsoft\Windows\Explorer\thumbcache_*.db` |
| 浏览器缓存 | Chrome: `%LOCALAPPDATA%\Google\Chrome\User Data\*\Cache`<br>Edge: `%LOCALAPPDATA%\Microsoft\Edge\User Data\*\Cache`<br>Firefox: `%LOCALAPPDATA%\Mozilla\Firefox\Profiles\*\cache2` |
| npm 缓存 | `%APPDATA%\npm-cache` 或 `%LOCALAPPDATA%\npm-cache` |
| pip 缓存 | `%LOCALAPPDATA%\pip\Cache` |
| Docker 未使用资源 | 通过 `docker system df` 检测（Docker 未安装则跳过） |
| TeleAgent Cache | `%LOCALAPPDATA%\TeleAgent\Cache` |
| TeleAgent GPUCache | `%LOCALAPPDATA%\TeleAgent\GPUCache` |
| TeleAgent Code Cache | `%LOCALAPPDATA%\TeleAgent\Code Cache` |
| TeleAgent Crashpad | `%LOCALAPPDATA%\TeleAgent\Crashpad\reports` |
| TeleAgent 旧版本残留 | `%LOCALAPPDATA%\TeleAgent*` 中非当前数据目录的文件夹 |
| TeleAgent 日志 | 当前账号数据根 `users\<账号ID>\log\`（优先 `$SUPER_AGENT_LOG_DIR`）下的 `.log` 文件 |

### macOS 扫描项

| 类别 | 路径 |
| --- | --- |
| 系统临时文件 | `/tmp`、`$TMPDIR` |
| 废纸篓 | `~/.Trash/` |
| 用户缓存 | `~/Library/Caches/`（逐个子目录扫描，含 TeleAgent） |
| 系统日志 | `/private/var/log/` |
| 浏览器缓存 | Chrome: `~/Library/Caches/Google/Chrome/*/Cache`<br>Safari: `~/Library/Caches/com.apple.Safari`<br>Firefox: `~/Library/Caches/Firefox/*/cache2` |
| Homebrew 缓存 | `~/Library/Caches/Homebrew/` |
| npm 缓存 | `~/.npm/_cacache` |
| pip 缓存 | `~/Library/Caches/pip` |
| Docker 未使用资源 | 通过 `docker system df` 检测 |
| TeleAgent Cache | `~/Library/Caches/TeleAgent/`、`~/Library/Application Support/TeleAgent/Cache/` |
| TeleAgent GPUCache | `~/Library/Caches/TeleAgent/GPUCache/` |
| TeleAgent Code Cache | `~/Library/Application Support/TeleAgent/Code Cache/` |
| TeleAgent Crashpad | `~/Library/Application Support/TeleAgent/Crashpad/reports/` |
| TeleAgent 日志 | `~/Library/Logs/TeleAgent/` 下的 `.log` 文件 |

### Linux 扫描项

| 类别 | 路径 |
| --- | --- |
| 系统临时文件 | `/tmp` |
| 系统日志 | `/var/log/` |
| 用户缓存 | `~/.cache/`（含 TeleAgent） |
| 回收站 | `~/.local/share/Trash/` |
| apt 缓存 | `/var/cache/apt/archives/` |
| npm 缓存 | `~/.npm/_cacache` |
| pip 缓存 | `~/.cache/pip` |
| 浏览器缓存 | Chrome: `~/.cache/google-chrome/*/Cache`<br>Firefox: `~/.cache/mozilla/firefox/*/cache2` |
| Docker 未使用资源 | 通过 `docker system df` 检测 |
| 旧内核 | `/boot/` 下的旧内核文件 |
| TeleAgent Cache | `~/.cache/TeleAgent/`、`~/.config/TeleAgent/Cache/` |
| TeleAgent GPUCache | `~/.cache/TeleAgent/GPUCache/` |
| TeleAgent Code Cache | `~/.config/TeleAgent/Code Cache/` |
| TeleAgent Crashpad | `~/.config/TeleAgent/Crashpad/reports/` |
| TeleAgent 日志 | 当前账号 `<用户数据根>/users/<账号ID>/log/` 下的 `.log` 文件 |

> macOS 和 Linux 脚本合并为一个 `.sh`，通过 `uname -s` 判断系统后选择对应路径列表。

---

## 三级分类

Agent 将扫描到的所有目录和文件分为三类：

### 第一类：可安全清理

删除后不影响功能，部分会自动重建。

| 项目 | 清理影响 | 是否需要关闭程序 |
| --- | --- | --- |
| 系统临时文件（未被锁定的） | 无影响，程序运行残留 | 部分被占用，需关闭后清 |
| 回收站 / 废纸篓 | 用户已删除的文件，清空后不可恢复 | 否 |
| Windows 更新缓存 | 已安装的更新安装包 | 否 |
| Windows.old | 旧系统备份，删除后无法回退旧版本 | 否（升级 10 天后已不可回退） |
| Windows 错误报告 | 已提交或过期的崩溃报告 | 否 |
| 缩略图缓存 | 删除后资源管理器自动重建 | 否 |
| 浏览器缓存 | 首次打开网页加载稍慢，正常浏览后恢复 | 是（需关闭对应浏览器） |
| npm / pip / Homebrew / apt 缓存 | 下次安装时重新下载 | 否 |
| TeleAgent Cache / GPUCache / Code Cache | 首次启动略慢，重启后自动重建 | 是（需关闭 TeleAgent） |
| TeleAgent Crashpad 报告 | 已过期的崩溃转储 | 否 |
| TeleAgent 旧版本残留 | 当前版本不再使用 | 否 |
| Docker 未使用资源 | 未被容器使用的镜像/卷 | 否 |
| Xcode DerivedData（macOS） | 编译缓存，重新编译时重建 | 否 |

### 第二类：谨慎清理

需要用户判断，有条件保留或需确认后才能清。

| 项目 | 说明 |
| --- | --- |
| 系统日志 | 建议保留最近 7 天，清理更旧的 |
| TeleAgent 日志 | 建议保留最近 7 天，排查问题需要 |
| 下载目录大文件（>100MB） | 需用户确认哪些可删 |
| Linux 旧内核 | 建议保留最近 2 个版本，清理更旧的 |
| TeleAgent Session 临时文件 | 可能丢失未保存的会话上下文 |

### 第三类：不可清理

| 项目 | 原因 |
| --- | --- |
| 用户文档 / 桌面 / 用户下载文件 | 用户数据 |
| 系统核心文件（`System32` / 当前内核 / `/usr`） | 系统运行必需 |
| TeleAgent 数据库 / 配置 / memory / skills | 核心数据 |
| 其他应用的用户数据目录 | 不属于清理范围 |

---

## 修复前安全检查

| 序号 | 安全检查项 | 确认内容 |
| --- | --- | --- |
| 1 | 用户确认 | 清理前必须向用户展示评估结果并获得确认 |
| 2 | 分类标注 | 每个待清理项都标注了分类级别和影响说明 |
| 3 | 被锁定项提示 | 被进程占用的目录标注 `is_locked`，不强制删除 |
| 4 | 备份机制 | 谨慎清理类项目清理前自动备份到 `.temp/` |

---

## 修复流程

```
Step 1  运行 check-disk-usage 脚本（全盘扫描 → 三级分类 → 评估 → 输出 JSON）
Step 2  向用户展示评估结果，等待确认
Step 3  第一轮清理（TeleAgent 运行中可直接清理的项目）
Step 4  生成独立清理脚本（需关闭 TeleAgent / 浏览器后清理的项目）
Step 5  告知用户后续操作
Step 6  用户重启后验证（可选）
```

---

### Step 1：运行检测脚本

**Windows：**
```powershell
.\scripts\check-disk-usage.ps1
```

**macOS / Linux：**
```bash
chmod +x ./scripts/check-disk-usage.sh && ./scripts/check-disk-usage.sh
```

脚本执行内容：
1. 检测所有磁盘/分区的剩余空间和使用率
2. 逐项扫描各平台路径表中的目录，计算每个目录体积（MB）
3. 对每个目录判定分类（可安全清理 / 谨慎清理 / 不可清理）
4. 检测目录是否被进程占用，被锁定的标记 `is_locked`
5. 检测 TeleAgent / Chrome / Edge / Firefox 等进程是否正在运行
6. 检测是否有管理员/root 权限
7. 输出结构化 JSON 评估结果

---

### Step 2：向用户展示评估结果，等待确认

Agent 输出格式：

```
磁盘空间评估结果：

磁盘整体情况：
| 磁盘 | 总容量 | 已用 | 剩余 | 使用率 |
| --- | --- | --- | --- | --- |
| C: | 512 GB | 468 GB | 44 GB | 91% |

【可安全清理】（共 6.4 GB）：
| 项目 | 体积 | 状态 |
| --- | --- | --- |
| 回收站 | 1.8 GB | 可直接清理 |
| Windows更新缓存 | 856 MB | 可直接清理 |
| 系统临时文件 | 620 MB | 可直接清理 |
| 浏览器缓存(Chrome) | 423 MB | 需关闭Chrome后清 |
| 浏览器缓存(Edge) | 210 MB | 需关闭Edge后清 |
| TeleAgent缓存 | 156 MB | 需关闭TeleAgent后清 |
| npm缓存 | 312 MB | 可直接清理 |
| 旧版本残留 | 320 MB | 可直接清理 |

【谨慎清理】（共 5.4 GB）：
| 项目 | 体积 | 说明 |
| --- | --- | --- |
| 下载目录大文件 | 5.2 GB | 需您确认哪些可删 |
| 系统日志 | 180 MB | 建议保留最近7天 |

【不可清理】：
| 项目 | 原因 |
| --- | --- |
| TeleAgent数据库+配置+记忆 | 核心数据 |
| 用户文档/桌面文件 | 用户数据 |

当前可选择：
  [1] 只清可安全清理 → 释放约 6.4 GB
  [2] 全部清理（含谨慎清理，需逐项确认）→ 释放约 11.8 GB
  [3] 暂不清理
```

| 用户选择 | Agent 行为 |
| --- | --- |
| 只清可安全清理 | 进入 Step 3 + Step 4 |
| 全部清理 | 先处理谨慎清理类（逐项确认），再进入 Step 3 + Step 4 |
| 暂不清理 | 告知用户评估结果已保存，随时可再次触发清理 |

---

### Step 3：第一轮清理（TeleAgent 运行中可直接清理的）

Agent 获得用户确认后，立即清理**不被进程占用**的可安全清理项：

| 可直接清理（运行中） | 需关闭后清理（生成独立脚本） |
| --- | --- |
| 回收站 / 废纸篓 | 浏览器缓存（Chrome/Edge/Firefox/Safari） |
| Windows 更新缓存 | TeleAgent Cache / GPUCache / Code Cache |
| npm / pip / Homebrew / apt 缓存 | Docker 未使用资源（需 Docker 服务） |
| Windows 错误报告 | |
| 缩略图缓存 | |
| 系统临时文件（未被锁定的） | |
| TeleAgent 旧版本残留 | |
| TeleAgent Crashpad 报告 | |
| Windows.old（如用户确认） | |

清理操作规则：
- 删除目标目录下的**内容**，保留目录本身（让程序重启时自动填充）
- 对"谨慎清理"类项目，清理前自动备份到 `.temp/cleanup-backup-<timestamp>/`
- 清理失败的目录跳过，继续处理下一个
- 清理完成后统计实际释放空间

---

### Step 4：生成独立清理脚本

对于被进程占用、需要关闭程序后才能清理的项目，Agent 生成一个独立清理脚本：

- Windows → `.temp/cleanup-locked-items.ps1`
- macOS / Linux → `.temp/cleanup-locked-items.sh`

脚本内容：
1. 检测目标程序是否仍在运行（如果在运行则提示先关闭）
2. 检测是否有管理员/root 权限（部分目录需要）
3. 逐个清理被锁定的缓存目录
4. 输出清理结果（释放空间总量）

---

### Step 5：告知用户后续操作

```
清理完成：

第一轮已清理：3.2 GB（回收站、Windows更新缓存、系统临时文件、npm缓存等）

剩余可清理：3.2 GB（浏览器缓存、TeleAgent缓存等被占用文件）
→ 已生成清理脚本：.temp/cleanup-locked-items.ps1

操作步骤：
1. 关闭 TeleAgent 和浏览器
2. 右键 cleanup-locked-items.ps1 → 用 PowerShell 运行
   （macOS/Linux：在终端执行 bash cleanup-locked-items.sh）
3. 运行完成后重新打开 TeleAgent

重启后 TeleAgent 会自动重建必要缓存，首次启动可能略慢，属正常现象。
```

> Agent 不应直接执行重启命令（会杀死自身进程），只告知用户手动操作。

---

### Step 6：用户重启后验证（可选）

用户重新打开 TeleAgent 后，Agent 可再次运行 `check-disk-usage` 脚本对比清理前后空间变化：

```
清理验证结果：
| 磁盘 | 清理前剩余 | 清理后剩余 | 释放空间 |
| --- | --- | --- | --- |
| C: | 44 GB | 50.4 GB | 6.4 GB |
```

---

## Agent 判断"可安全清理"部分是否真正可清理

| 验证项 | 验证方法 | 判定 |
| --- | --- | --- |
| **目标程序是否在运行** | 检测 Chrome/Edge/TeleAgent 等进程 | 在运行 → 标记 `is_locked`，走独立脚本 |
| **目录是否被文件锁占用** | Windows: 尝试打开目录内文件测试锁定；macOS/Linux: `lsof` 检查 | 被锁定 → 标记 `is_locked` |
| **是否有管理员权限** | Windows: 检查当前用户权限；macOS/Linux: `id -u` 检查 | 需管理员权限的目录单独标注 |
| **整体可清理量是否值得操作** | 可安全清理总量 > 100MB 才建议执行 | 不足 100MB 告知用户空间节省有限 |
| **Windows.old 是否在 10 天期限内** | 检查目录创建时间 | 10 天内告知用户"删除后无法回退旧系统"，让用户自行决定 |

---

## 脚本设计

- **check-disk-usage.ps1**（Windows，PowerShell 5.1+）
- **check-disk-usage.sh**（macOS / Linux 合并，Bash + 内嵌 Python）

macOS 和 Linux 合并为一个 `.sh`，通过 `uname -s` 判断系统后选择对应路径列表。macOS 有 `~/Library` 系列路径，Linux 有 `/var/cache/apt` 等特有路径，脚本内部按系统区分。

脚本只负责**检测和评估**，不负责删除。清理操作由 Agent 在获得用户确认后执行。

脚本输出 JSON 格式：

```json
{
  "disk_info": [
    {
      "drive": "C:",
      "free_gb": 44.0,
      "total_gb": 512.0,
      "usage_percent": 91.4
    }
  ],
  "running_processes": {
    "teleagent": true,
    "chrome": true,
    "edge": false,
    "firefox": false,
    "docker": false
  },
  "has_admin": false,
  "categories": {
    "safe_to_clean": [
      {
        "name": "回收站",
        "path": "C:\\$Recycle.Bin",
        "size_mb": 1800.0,
        "exists": true,
        "is_locked": false,
        "needs_admin": false,
        "note": "可直接清理"
      },
      {
        "name": "TeleAgent缓存",
        "path": "C:\\Users\\xxx\\AppData\\Local\\TeleAgent\\Cache",
        "size_mb": 156.0,
        "is_locked": true,
        "needs_admin": false,
        "note": "需关闭TeleAgent后清理"
      }
    ],
    "caution_clean": [
      {
        "name": "系统日志",
        "path": "/var/log/",
        "size_mb": 180.0,
        "note": "建议保留最近7天"
      }
    ],
    "not_cleanable": [
      {
        "name": "TeleAgent数据库与配置",
        "paths": ["...\\scheduler.db", "...\\im-service.db", "...\\config.json"],
        "size_mb": 102.4,
        "note": "核心数据，不可删除"
      }
    ]
  },
  "safe_cleanable_total_mb": 6400.0,
  "caution_cleanable_total_mb": 5400.0,
  "locked_items_need_script": [
    {
      "name": "浏览器缓存(Chrome)",
      "path": "...\\Chrome\\...\\Cache",
      "size_mb": 423.0,
      "blocking_process": "chrome"
    },
    {
      "name": "TeleAgent缓存",
      "path": "...\\TeleAgent\\Cache",
      "size_mb": 156.0,
      "blocking_process": "teleagent"
    }
  ],
  "cleanup_suggestion": "safe_only"
}
```

| 字段 | 说明 |
| --- | --- |
| `disk_info` | 各磁盘的剩余/总量/使用率 |
| `running_processes` | 关键进程运行状态（影响清理方式） |
| `has_admin` | 是否有管理员/root 权限 |
| `categories` | 三分类目录列表，每项含名称、路径、体积、是否锁定、是否需管理员、说明 |
| `safe_cleanable_total_mb` | 可安全清理项体积合计 |
| `caution_cleanable_total_mb` | 谨慎清理项体积合计 |
| `locked_items_need_script` | 需生成独立清理脚本的项目列表 |
| `cleanup_suggestion` | `safe_only`（建议只清安全类）/ `all`（建议都清）/ `no_need`（无需清理） |

---

## 边界与限制

| 场景 | 处理方式 |
| --- | --- |
| 磁盘使用率 < 80% | 告知用户当前空间充足，无需清理 |
| 可安全清理总量 < 100MB | 告知用户可清理空间有限，收益不大 |
| 需管理员权限的目录 | 独立脚本中标注，提示用户以管理员身份运行 |
| 浏览器/TeleAgent 正在运行 | 生成独立脚本，告知用户关闭后运行 |
| 目录不存在 | 跳过，不报错（如未安装 Docker 则跳过 Docker 项） |
| 清理失败（权限/锁定） | 记录失败目录，跳过继续清理其他项，最终汇总失败列表 |
| Linux 旧内核检测 | 列出当前内核版本，只建议清理更旧的，不自动删除 |
| Windows.old 在 10 天期限内 | 告知用户删除后无法回退旧系统，由用户决定 |
| 用户选择清理"谨慎清理"类 | 先备份再清理，告知用户备份位置和保留期限 |
| Crashpad 目录不存在 | 正常情况（未发生过崩溃），不报错 |
| 清理后 TeleAgent 启动变慢 | 正常现象（缓存重建），告知用户首次启动可能略慢 |
