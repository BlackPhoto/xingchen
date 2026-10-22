---
name: c-drive-cleaner
description: Scan and clean C drive junk files on Windows. Use when user mentions cleaning C drive, freeing disk space, removing temp files, clearing cache, disk cleanup, or similar disk space management tasks. Supports safe scanning with user confirmation before deletion.
name_cn: C盘清理助手
description_cn: 扫描并安全清理C盘无用文件，释放磁盘空间。扫描后需确认才删除，不误删系统及用户文件。
create_source: super-agent-skill-creator
---

# C盘清理助手

安全扫描并清理 Windows C 盘中的无用文件，释放磁盘空间。

## 工作流程

1. **扫描阶段** — 运行 `scripts/c-drive-scanner.ps1`，扫描 13 类安全可清理项
2. **报告阶段** — 将扫描结果以表格形式展示，标注可释放空间和需谨慎处理项
3. **确认阶段** — 询问用户是否确认清理（仅安全项，谨慎项不自动删除）
4. **清理阶段** — 用户确认后运行 `scripts/c-drive-cleaner.ps1` 执行删除
5. **结果阶段** — 展示清理后 C 盘剩余空间

## 扫描范围

### 安全可删除项（SafeToDelete = true）

| 项目 | 路径 | 说明 |
|------|------|------|
| Windows 临时文件 | `C:\Windows\Temp` | 系统临时文件 |
| 用户临时文件 | `%TEMP%` | 用户临时文件 |
| 回收站 | `C:\$Recycle.Bin` | 已删除但未清空的文件 |
| Windows 更新缓存 | `C:\Windows\SoftwareDistribution\Download` | 已下载的更新包 |
| 缩略图缓存 | `%LOCALAPPDATA%\Microsoft\Windows\Explorer\thumbcache_*.db` | 图片缩略图 |
| Edge 缓存 | `%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\Cache` | 浏览器缓存 |
| Chrome 缓存 | `%LOCALAPPDATA%\Google\Chrome\User Data\Default\Cache` | 浏览器缓存 |
| Windows 日志 | `C:\Windows\Logs` | 系统日志文件 |
| 更新数据存储 | `C:\Windows\SoftwareDistribution\DataStore` | 更新数据 |
| 崩溃转储 | `%LOCALAPPDATA%\CrashDumps` | 程序崩溃转储 |
| Windows 错误报告 | `C:\ProgramData\Microsoft\Windows\WER` | 错误报告文件 |

### 谨慎处理项（SafeToDelete = false，仅报告不自动删除）

| 项目 | 路径 | 说明 |
|------|------|------|
| 预读取数据 | `C:\Windows\Prefetch` | 系统预读取，删除可能短暂影响启动速度 |
| 下载文件夹大文件 | `%USERPROFILE%\Downloads` | >100MB 文件，需用户手动判断 |

## 执行脚本

### 扫描：`scripts/c-drive-scanner.ps1`

```powershell
powershell -ExecutionPolicy Bypass -File scripts/c-drive-scanner.ps1
```

输出包含：
- C 盘空间概览（总量/已用/剩余）
- 可安全清理项列表及大小
- 谨慎处理项列表
- JSON 数据段（供程序解析）

### 清理：`scripts/c-drive-cleaner.ps1`

```powershell
powershell -ExecutionPolicy Bypass -File scripts/c-drive-cleaner.ps1
```

输出包含：
- 每项清理结果（成功/跳过/失败）
- 总释放空间大小
- 清理后 C 盘剩余空间

## 安全规则

- **禁止**自动删除标记为 SafeToDelete = false 的项目
- **禁止**删除用户个人文件（文档、图片、视频等）
- **禁止**删除系统关键文件（Windows、Program Files 等）
- 清理浏览器缓存前提示用户可能需重新登录网站
- 清理完成前先运行扫描，确保用户知情并确认
