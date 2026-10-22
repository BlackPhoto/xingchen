---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: '83746f08-6c4b-4112-9084-3bd5c57a44e4'
  PropagateID: '83746f08-6c4b-4112-9084-3bd5c57a44e4'
  ReservedCode1: '67016b3b-79b0-4c90-b92c-a42af36c5feb'
  ReservedCode2: '67016b3b-79b0-4c90-b92c-a42af36c5feb'
---

# 银行扣款回单重命名参考

## 任务说明

每月银行代扣水费后，工行生成电子回单 PDF，原始文件名形如：

`1208013009021015348_20260901_26244000020_0000#0100#00001#65381638_00937.pdf`
（付款账号_扣款日期_批次序号_网点#柜员#序号#交易流水号_回单号.pdf）

用户要求按「时间-水表号-扣款金额」重命名为：`YYYYMMDD-水表号-金额.pdf`
示例：`20261008-2001024-72.90.pdf`（金额保留两位小数）

注意与发票命名规则区分：发票为 `年月日-水表号-发票类型-金额.pdf`（多"发票类型"段），回单无该段。

## 回单目录

- 根目录：`E:\WORK\水电费周转房\自有房屋水电费\YYYY年MM月\`（water_bill_config.md 发票部分记为 `O:\WORK`，以本机实际可访问盘符为准）
- 子目录每月不固定：2026年09月在 `水费\`，2026年10月在 `回单\Desktop\`
- 用户给的路径不存在时，对当月目录执行 `Get-ChildItem -Recurse -Filter *.pdf` 定位实际存放位置

## 回单字段结构（工行电子回单）

| 字段 | 示例/说明 |
|---|---|
| 交易日期 | 扣款时间，文件名第一段（如 2026年10月08日 → 20261008） |
| 付款方 | 中国电信股份有限公司金华分公司，账号 1208013009021015348 |
| 收款方 | 浦江县城乡自来水有限公司，账号 1208070019200014120 |
| 扣款金额 | 数字金额（¥72.90）+ 大写金额（柒拾贰元玖角），两者应一致 |
| 水费代扣编号 | 即水表号/户号，文件名第二段 |
| 摘要 | 水费 |

易混淆编号（不要误当作水表号）：电子回单号码（9700-xxxx-xxxx-xxxx）、交易流水号、记账网点编号（0100）、记账柜员编号（00001）、双方银行账号。

水费代扣编号应能在 [water_bill_config.md](water_bill_config.md) 的户号列表中找到（5050900 既是供水系统户号也作为水表号出现在回单中，属正常）。

## 零依赖 PDF 读取方案

本机 Python 无 pdfplumber/pypdf/fitz，pip 安装被网络策略拦截（403）。以下路径均不可行，不要重复尝试：

| 尝试 | 结果 |
|---|---|
| pip install pypdf | 403 Forbidden（镜像被拦） |
| zlib 解压 PDF 流提取 Tj/TJ 文本 | 回单为自定义字体编码，输出乱码 |
| Word COM 打开 PDF 提取文本 | 超时挂起（>120s），勿用 |
| Chrome `--headless --screenshot` 截 file:/// PDF | headless 不渲染 PDF 查看器，得到"无法访问您的文件"错误页 |
| Playwright 直接访问 `file://` | file 协议被阻止 |
| `Start-Job` 启动 http.server | 后台 Job 在工具调用间被终止，连接拒绝 |

### 可用方案：本地 HTTP 服务器 + Playwright 截图 + 视觉模型

```powershell
# 必须用 Start-Process 启动独立进程（Start-Job 会被终止）
$proc = Start-Process -FilePath "python" -ArgumentList "-m","http.server","8765","--bind","127.0.0.1" -WorkingDirectory "<回单目录>" -WindowStyle Hidden -PassThru
$proc.Id | Out-File "E:\AI工作区\.temp\http_server_pid.txt"
Start-Sleep -Seconds 3
# 验证：(Invoke-WebRequest -Uri "http://127.0.0.1:8765/" -UseBasicParsing).StatusCode 应为 200
```

然后逐张处理：
1. `playwright_browser_navigate` 到 `http://127.0.0.1:8765/<文件名>`（文件名中的 `#` 必须编码为 `%23`；URL 需与实际文件名逐字核对，抄错编号会得到 Error response 页）
2. `playwright_browser_take_screenshot`（fullPage: true）——截图实际落在 `E:\AI工作区\`，不在 playwright-mcp 目录
3. `image_understanding` 识别字段

换月处理时：先读 pid 文件 `Stop-Process` 旧服务器，再以新目录重启。

### 视觉识别 Prompt 要点

常规识别：要求逐项列出 1)交易/记账日期 2)付款方 3)收款方 4)扣款金额（数字+大写）5)水费代扣编号/水表号 6)摘要。

复核识别：要求"把回单上所有编号字段及数值逐项列出，并注明字段名"，可避免把流水号/账号误当水表号。

### 放大复核技巧

对可疑回单，先放大再截图重识别：

```js
() => { const embed = document.querySelector('embed'); if (embed) { embed.style.width = '1800px'; } return 'resized'; }
```

## 交叉核对（防 VLM 误读）

- 识别出的水表号与户号列表（water_bill_config.md）比对；列表外的新号需放大复核
- 与上月回单水表号集合比对：每月有费用记录的水表可能变化（如 10 月新增 2001024/834968/8505859/110940，缺失 922658/3135537/3103829），变化本身正常，但每个新号都应能在户号列表中找到
- 数字金额与大写金额一致；完成后向用户汇总表格与合计金额

## 重命名执行

```powershell
$dir = "<回单目录>"
$map = [ordered]@{
  '1208013009021015348_20261008_26281000022_0000#0100#00001#72142714_02459.pdf' = '20261008-2001024-72.90.pdf'
  # ... 其余条目
}
foreach ($k in $map.Keys) {
  $old = Join-Path $dir $k
  if (Test-Path -LiteralPath $old) {
    Rename-Item -LiteralPath $old -NewName $map[$k]
    Write-Host "OK: $($map[$k])"
  } else { Write-Host "MISS: $k" }
}
```

坑点：
- 哈希表键含 `#` 时必须用**单引号**字面量；双引号形式会报 `IncompleteHashLiteral` 解析错误
- `Test-Path` / `Rename-Item` 一律用 `-LiteralPath`（文件名含 `#` 等特殊字符）
- 重命名后 `Get-ChildItem ... | Sort-Object Name` 核对最终列表，向用户输出汇总表（新文件名/日期/水表号/金额）与合计金额