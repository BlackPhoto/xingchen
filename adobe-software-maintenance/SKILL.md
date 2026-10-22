---
name: adobe-software-maintenance
description: Install, update, and verify Adobe desktop software (Photoshop, Camera Raw, Bridge) on Windows, and troubleshoot Photoshop plugins (UXP panels, third-party) that fail to load or report license/login errors. Covers Adobe official download link resolution, silent installation, version verification, and UXP plugin data/license repair. Trigger when the user asks to install or upgrade Adobe software, or to fix a Photoshop plugin that cannot be used.
name_cn: Adobe软件安装与插件维护
description_cn: 在Windows上安装、升级、验证Adobe软件（Photoshop、Camera Raw等），并排查Photoshop插件加载失败、许可证报错等故障，含官方下载链接解析、静默安装与UXP插件数据修复。
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: '2dd7145e-e4cd-40ba-b3c3-b6710b50e505'
  PropagateID: '2dd7145e-e4cd-40ba-b3c3-b6710b50e505'
  ReservedCode1: '4534c5e3-502a-4960-9725-baff18462c16'
  ReservedCode2: '4534c5e3-502a-4960-9725-baff18462c16'
---

# Adobe 软件安装升级与 Photoshop 插件维护（Windows）

## 适用场景
- 安装、升级 Adobe 桌面软件/组件（Camera Raw、Photoshop、Bridge 等）
- Photoshop 插件（UXP 面板、第三方插件）打不开、加载失败、报许可证/登录错误
- 验证 Adobe 软件/插件版本、测试功能可用性

## 一、安装/升级 Adobe 软件（以 Camera Raw 为例）

### 1. 环境与版本检查
- 查已装 Adobe 软件（注册表卸载项）：
  ```powershell
  Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*","HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*" -ErrorAction SilentlyContinue | Where-Object {$_.DisplayName -match "Adobe"} | Select-Object DisplayName, DisplayVersion, InstallLocation
  ```
- Camera Raw 版本看插件文件 VersionInfo（标准位置 `C:\Program Files\Common Files\Adobe\Plug-Ins\CC\File Formats\Camera Raw.8bi`）：
  ```powershell
  (Get-Item "C:\Program Files\Common Files\Adobe\Plug-Ins\CC\File Formats\Camera Raw.8bi").VersionInfo.FileVersion
  ```
- Adobe 安装包通常 1-2GB，下载与安装前确认磁盘剩余空间。

### 2. 解析官方下载链接（关键技巧）
- Adobe 官方帮助页（helpx.adobe.com）给出的下载入口是 `https://www.adobe.com/go/<代号>` 短链（如 Camera Raw 为 `acr_installer_win`）。
- 陷阱：`Invoke-WebRequest` 访问该短链会返回 403（即使跟随重定向）。改用系统自带 curl 解析：
  ```powershell
  curl.exe -sIL "https://www.adobe.com/go/acr_installer_win" | Select-String "HTTP|Location|content-length"
  ```
- 从 301 的 `Location` 头取真实地址（形如 `https://download.adobe.com/pub/adobe/...exe`），记录 `Content-Length` 用于完整性校验。
- 下载用 `curl.exe -L -o`，完成后将文件字节数与 `Content-Length` 严格比对，一致才算下载完整。

### 3. 安装前准备（顺序重要）
1. 关闭所有 Adobe 应用进程（Photoshop、Bridge 等），否则插件文件被占用导致更新失败；AdobeIPCBroker 可不关。关闭 Photoshop 可能丢失未保存内容，必须先用 question 工具征得用户确认。
2. 备份将被覆盖的插件文件（如 Camera Raw.8bi）到工作区 `.temp` 目录，便于回滚。

### 4. 静默安装与版本验证
- Adobe 独立安装器支持 `/s` 静默参数：
  ```powershell
  $p = Start-Process -FilePath $exe -ArgumentList "/s" -PassThru -Wait; $p.ExitCode
  ```
- 退出码 0 后重新读取插件文件 VersionInfo，确认版本号已变更为目标版本。

### 5. 功能测试（Photoshop COM 自动化）
- 启动 Photoshop，确认进程正常、内存持续加载。
- 无界面验证图像处理链路：
  ```powershell
  $ps = New-Object -ComObject "Photoshop.Application"
  $doc = $ps.Open("<任意测试图片路径>")   # 打开成功即链路正常
  $doc.Close(2)                            # 2 = 不保存关闭
  ```
- 陷阱：UXP 插件与 .8bi 文件格式插件不会出现在 COM 的 `$ps.PlugIns` 集合中（该集合常返回 0），不能据此判断插件未加载。

## 二、Photoshop UXP 插件故障排查

### 1. UXP 插件存储结构（核心知识）
- 插件本体：`C:\Program Files\Adobe\Adobe Photoshop <年份>\Plug-ins\<插件目录>\`（manifest.json + index.js + assets 等）。Photoshop 启动时扫描 Plug-ins 目录识别 UXP 插件。
- 运行数据/许可证：`%APPDATA%\Adobe\UXP\PluginsStorage\PHSP\<PS主版本>\External\<插件ID>\PluginData\`
  - `PHSP` 表示 Photoshop；主版本号如 `27` 对应 Photoshop 2026；插件 ID 取自 manifest.json 的 `"id"` 字段。
  - 许可证文件（如 lic.json）位于 PluginData 下。
- 识别验证：重启 Photoshop 后观察 `External\<插件ID>\PluginData` 目录的 LastWriteTime 是否被更新，被更新说明 Photoshop 已识别并访问该插件。

### 2. 许可证/登录报错的排查路径
1. 读插件 manifest.json，确认插件 ID、版本、入口文件。
2. 检查上述真实 PluginData 路径下许可证文件是否存在。
3. 若缺失，全盘搜索该许可证文件名（常被放在错误路径）。
4. 将文件复制到正确路径（保留源文件不删），重启 Photoshop 验证。
5. 插件 index.js 常为混淆加密代码，无法通过读代码分析许可证逻辑，应从文件位置与完整性入手排查。

### 3. 路径陷阱（重要）
- 用户提供的路径可能是非标准路径（例如缺少 `Users\<用户名>` 或 `Adobe` 层级的路径）。这类路径即使真实存在，Photoshop 也不会读取。
- 一律以 `$env:APPDATA` 环境变量为准推导软件实际读取的路径，不直接采信用户给的路径；当两个路径下都存在同名文件时，用 `Get-FileHash` 比对内容。

### 4. manifest 图标规范（避免误判）
- manifest.json 中图标写 `"icons/xx.png"` 且 `scale: [1,2]` 时，实际文件名应为 `xx@1x.png`、`xx@2x.png`，这是 UXP 规范的自动查找约定，不是文件缺失错误。

## 三、脚本与环境注意
- Windows 10 默认的 Windows PowerShell 5.1 不支持三元运算符（`? :`）等 PowerShell 7 语法，写脚本时避免使用。
- `curl.exe` 位于 `C:\Windows\system32\curl.exe`（系统自带）。其进度条输出在 PowerShell 中会以 NativeCommandError 形式出现，属正常噪音；判断下载是否完成以文件字节数与 Content-Length 比对为准。

## 四、操作确认原则
- 下载 GB 级安装包、关闭正在运行的 Photoshop 前，用 question 工具征得用户确认。
- 覆盖系统文件前先备份到 `.temp`；修复性复制保留源文件不删。