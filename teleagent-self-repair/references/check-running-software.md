# 修复方案：正在运行的软件与显存占用

> **对应场景**：用户想了解当前电脑正在运行哪些软件、各软件的内存和显存占用情况
> **触发方式**：用户说"看看我电脑在跑什么""电脑好卡""哪些程序占用资源多""看看显存占用"等
> **重要**：本检查项只做信息采集和展示，不修改任何文件，不终止任何进程，属于纯只读检查项。

---

## 触发条件

用户说出以下任一意图时触发：

| 触发表述 | 实际意图 |
| --- | --- |
| "看看我电脑在跑什么" / "现在在运行什么软件" | 想了解当前运行中的软件 |
| "电脑好卡" / "电脑很慢" / "感觉资源不够" | 怀疑有软件占用过多资源 |
| "哪些程序占用资源多" / "内存/显存被谁占了" | 想找到资源占用大户 |
| "看看显存占用" / "GPU 被谁用了" | 重点关注 GPU/显存使用情况 |

---

## 两种检测场景

| 场景 | 检测方法 | 脚本行为 |
| --- | --- | --- |
| 场景A：查看正在运行的软件 | 枚举所有有窗口标题或可执行路径的进程，按进程名分组合并，统计内存占用 | 输出软件列表 + 内存占用 |
| 场景B：查看 GPU 显存占用 | 通过 `nvidia-smi`（NVIDIA）、`rocm-smi`（AMD）或系统工具获取 GPU 设备信息和逐进程显存占用 | 输出 GPU 信息 + 显存占用 |

---

## 检测范围

### 正在运行的软件

脚本枚举所有符合条件的进程，按进程名分组合并（同一软件的多个进程合并为一条），统计内存占用。

**筛选条件**（满足任一即纳入）：
- 进程有窗口标题（`MainWindowTitle` 非空）—— 用户可见的应用窗口
- 进程有可执行文件路径（`Path` 非空）—— 有明确来源的进程

**排除项**（系统核心进程，对用户无参考价值）：
| 系统 | 排除的进程名 |
| --- | --- |
| Windows | `System`、`Registry`、`smss`、`csrss`、`wininit`、`services`、`lsass`、`svchost`、`dwm`、`conhost`、`RuntimeBroker`、`SearchIndexer`、`sihost`、`taskhostw`、`fontdrvhost` |
| macOS | `kernel_task`、`loginwindow`、`WindowServer`、`launchd`、`syslogd` |
| Linux | `systemd`、`kthreadd`、`rcu_gp`、`migration`、`watchdog`、`ksoftirqd`、`kworker` |

**输出字段**：

| 字段 | 说明 |
| --- | --- |
| `name` | 进程名（合并后） |
| `pid` | 主进程 PID（合并组中第一个进程的 PID） |
| `instance_count` | 该软件的进程实例数 |
| `memory_mb` | 内存占用合计（MB），按 WorkingSet 计算 |
| `cpu_seconds` | CPU 累计时间（秒），作为占用参考值（PowerShell 5.1 无法直接获取瞬时 CPU 百分比） |
| `path` | 可执行文件路径 |

### GPU 显存占用

脚本按 GPU 厂商逐一尝试，能获取多少就报多少：

| GPU 厂商 | 检测工具 | 可获取信息 | 不可用时处理 |
| --- | --- | --- | --- |
| NVIDIA | `nvidia-smi` | GPU 设备名、总显存、已用显存、逐进程显存占用 | 标注 `nvidia-smi 不可用`，跳过 |
| AMD (Linux) | `rocm-smi` | GPU 设备名、总显存、已用显存 | 标注 `rocm-smi 不可用`，跳过 |
| AMD (Windows) | 无标准 CLI 工具 | — | 标注 `AMD 显存暂不支持逐进程查询` |
| Intel 集显 | 无标准 CLI 工具 | — | 标注 `Intel 集显暂不支持逐进程查询` |

**输出字段**：

GPU 设备级信息：

| 字段 | 说明 |
| --- | --- |
| `name` | GPU 设备名（如 NVIDIA GeForce RTX 4090） |
| `vendor` | GPU 厂商（nvidia / amd / intel / unknown） |
| `used_mb` | 已用显存（MB） |
| `total_mb` | 总显存（MB） |
| `usage_percent` | 显存使用率（%） |

GPU 逐进程信息：

| 字段 | 说明 |
| --- | --- |
| `name` | 进程名 |
| `pid` | 进程 PID |
| `gpu_memory_mb` | 该进程占用显存（MB） |

---

## 修复前安全检查

| 序号 | 安全检查项 | 确认内容 |
| --- | --- | --- |
| 1 | 只读操作 | 本检查项仅读取系统信息，不修改任何文件，无需备份 |
| 2 | 非红线区 | 进程和 GPU 信息获取属于纯只读，无需安全确认即可执行 |
| 3 | 用户知情 | 检测结果需向用户展示 |

---

## 检测流程

```
Step 1  运行 check-running-software 脚本（枚举进程 → 检测 GPU → 输出 JSON）
Step 2  Agent 解析脚本输出，格式化展示给用户
Step 3  （可选）若用户反馈"电脑卡"，Agent 可建议联动检查项 2（磁盘空间清理）
```

> **纯只读检查项例外**：与检查项 1（日志异常检测）相同，本检查项只执行 Step 1-2，不涉及修复。Agent 根据检测结果判断影响并告知用户后续操作。

---

### Step 1：运行检测脚本

**Windows：**
```powershell
.\scripts\check-running-software.ps1
```

**macOS / Linux：**
```bash
chmod +x ./scripts/check-running-software.sh && ./scripts/check-running-software.sh
```

脚本执行内容：
1. 枚举所有符合条件的进程（有窗口或有路径，排除系统核心进程）
2. 按进程名分组合并，统计每组的实例数和内存占用合计
3. 按内存占用从高到低排序
4. 检测 GPU 设备（NVIDIA / AMD / Intel），获取显存使用情况
5. 获取 GPU 逐进程显存占用（仅 NVIDIA 支持）
6. 输出结构化 JSON 结果

---

### Step 2：向用户展示检测结果

Agent 输出格式：

```
正在运行的软件（按内存占用排序）：

| 软件 | 进程数 | 内存占用 | 路径 |
| --- | --- | --- | --- |
| chrome | 12 | 2,048.5 MB | C:\...\chrome.exe |
| TeleAgent | 3 | 512.3 MB | C:\...\TeleAgent.exe |
| WeChat | 1 | 384.2 MB | C:\...\WeChat.exe |
| ... | ... | ... | ... |

GPU 显存使用情况：

| GPU 设备 | 已用 / 总量 | 使用率 |
| --- | --- | --- |
| NVIDIA GeForce RTX 4090 | 2,048 MB / 24,576 MB | 8.3% |

GPU 显存占用 Top 进程：

| 进程 | PID | 显存占用 |
| --- | --- | --- |
| chrome | 6789 | 512 MB |
| TeleAgent | 12345 | 256 MB |
```

**无 GPU 或 GPU 信息不可用时**：

```
GPU 显存使用情况：
未检测到 NVIDIA GPU（或 nvidia-smi 不可用），无法获取逐进程显存信息。
AMD / Intel 集显暂不支持逐进程显存查询。
```

---

### Step 3：联动建议（可选）

若用户触发原因是"电脑好卡"或"电脑很慢"，Agent 可在展示完检测结果后追加建议：

> 检测到内存占用较高的软件较多，如果需要进一步排查，可以：
> 1. 检查磁盘空间是否充足（加载 `clean-disk-space.md`）
> 2. 手动关闭不需要的软件释放资源

---

## 脚本设计

- **check-running-software.ps1**（Windows，PowerShell 5.1+）
- **check-running-software.sh**（macOS / Linux 合并，Bash + 内嵌 Python）

macOS 和 Linux 合并为一个 `.sh`，通过 `uname -s` 判断系统后选择对应的进程枚举方式。macOS 使用 `ps` + `ioreg` 获取 GPU 信息，Linux 使用 `ps` + `lspci` / `nvidia-smi` / `rocm-smi`。

脚本**只负责检测和输出**，不修改任何文件，不终止任何进程。

脚本输出 JSON 格式：

```json
{
  "running_software": [
    {
      "name": "chrome",
      "pid": 6789,
      "instance_count": 12,
      "memory_mb": 2048.5,
      "cpu_seconds": 5.2,
      "path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
    }
  ],
  "total_memory_mb": 8192.0,
  "system_memory": {
    "total_gb": 32.0,
    "available_gb": 12.5,
    "usage_percent": 60.9
  },
  "gpu": [
    {
      "name": "NVIDIA GeForce RTX 4090",
      "vendor": "nvidia",
      "used_mb": 2048,
      "total_mb": 24576,
      "usage_percent": 8.3
    }
  ],
  "gpu_processes": [
    {
      "name": "chrome",
      "pid": 6789,
      "gpu_memory_mb": 512
    },
    {
      "name": "TeleAgent",
      "pid": 12345,
      "gpu_memory_mb": 256
    }
  ],
  "gpu_detection_notes": []
}
```

| 字段 | 说明 |
| --- | --- |
| `running_software` | 正在运行的软件列表，按内存占用从高到低排序，每项含名称、主PID、实例数、内存、CPU、路径 |
| `total_memory_mb` | 所有列出软件的内存占用合计（MB） |
| `system_memory` | 系统总内存、可用内存、使用率 |
| `gpu` | GPU 设备信息列表，每项含设备名、厂商、已用显存、总显存、使用率 |
| `gpu_processes` | GPU 逐进程显存占用列表（仅 NVIDIA 支持），每项含进程名、PID、显存占用 |
| `gpu_detection_notes` | GPU 检测备注（如厂商不支持、工具不可用等提示信息） |

---

## 边界与限制

| 场景 | 处理方式 |
| --- | --- |
| 无 GPU 设备 | `gpu` 输出空数组，`gpu_processes` 输出空数组，`gpu_detection_notes` 标注"未检测到 GPU 设备" |
| NVIDIA 驱动未安装 / nvidia-smi 不可用 | `gpu` 输出空数组，`gpu_detection_notes` 标注"nvidia-smi 不可用，请确认 NVIDIA 驱动已安装" |
| AMD GPU（Windows） | `gpu_detection_notes` 标注"AMD GPU 暂不支持逐进程显存查询"，尝试通过 WMI 获取设备名和总显存 |
| Intel 集显 | `gpu_detection_notes` 标注"Intel 集显暂不支持逐进程显存查询" |
| 进程名重复（如多个 chrome 窗口） | 按进程名分组合并，`instance_count` 标注实例数，内存为合计值 |
| 系统进程无窗口且无路径 | 不纳入输出（对用户无参考价值） |
| 权限不足无法获取某些进程信息 | 尽力获取，获取失败的进程跳过，不报错 |
| macOS/Linux 无 nvidia-smi | 同 NVIDIA 不可用处理，`gpu_detection_notes` 标注 |
| `cpu_seconds` 在 PowerShell 5.1 中获取不精确 | 使用 `Get-Process` 的 `CPU` 属性累计秒数作为参考值，非瞬时 CPU 百分比 |
