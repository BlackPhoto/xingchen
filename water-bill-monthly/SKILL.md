---
name: water-bill-monthly
description: "Monthly water bill processing. Covers: (1) creating year-month folder, (2) logging into WeChat water bill system and downloading current month invoices, (3) parsing invoice PDFs and generating detailed summary Excel with 3 sheets, (4) renaming bank deduction receipt PDFs as 日期-水表号-金额 based on PDF content. Use when user mentions 水费发票, 下载水费, 水费月度处理, 水费报表, 银行扣款回单, 回单重命名, 水费回单, or needs to download/process water bill invoices or receipts."
name_cn: 月度水费发票与扣款回单处理
description_cn: 每月水费处理：下载水费PDF发票生成汇总报表并填写报账表，按日期-水表号-金额重命名银行扣款回单
create_source: super-agent-skill-creator
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: 'b9909fee-99bc-4704-97ba-28c5d493fc8d'
  PropagateID: 'b9909fee-99bc-4704-97ba-28c5d493fc8d'
  ReservedCode1: '87a546de-890b-4053-a195-91c1ca0c61a3'
  ReservedCode2: '87a546de-890b-4053-a195-91c1ca0c61a3'
---

# 月度水费发票与扣款回单处理

本技能覆盖每月水费处理的两类周期任务，按用户请求路由：

| 用户意图 | 任务 | 流程位置 |
|---|---|---|
| 下载当月水费发票、生成汇总报表、填写报账表 | 任务 A：发票下载与报表生成 | 本文"任务 A 工作流程" |
| 读取银行扣款回单 PDF，按「时间-水表号-扣款金额」重命名 | 任务 B：银行扣款回单重命名 | [references/bank_receipt_rename.md](references/bank_receipt_rename.md) |

## 任务 A 工作流程：发票下载与报表生成

完整执行以下 5 步，顺序不可跳步。

### 第 1 步：创建当月目录

1. 获取当前本机年月（格式：`YYYY年MM月`，如 `2026年07月`）
2. 检查 `O:\WORK\水电费周转房\自有房屋水电费\YYYY年MM月\` 是否已存在
3. 若不存在则新建该文件夹
4. 确认目录可写入

### 第 2 步：下载当月水费发票

#### 2.1 登录水费系统

1. 用 Playwright 打开水费系统链接（见 [water_bill_config.md](references/water_bill_config.md) 中"系统访问"章节）
2. 检查页面状态：
   - 若已登录（可见户号信息）：直接进入 2.2
   - 若未登录（出现微信授权页面）：**暂停并提示用户扫码登录**，等待用户确认登录成功后继续
3. 登录成功后，确认页面已加载完毕

#### 2.2 逐户号下载发票

对 12 个户号逐一执行（户号列表见 [water_bill_config.md](references/water_bill_config.md)）：

1. 选择对应户号，进入开票/发票列表页面
2. 筛选**当月**发票（只下载当月，不下载其他月份）
3. 下载 PDF 发票
4. 按命名规则重命名 PDF：`年月日-水表号-发票类型-金额.pdf`（规则详见 [water_bill_config.md](references/water_bill_config.md)）
5. 保存到第 1 步创建的当月目录

注意事项：
- 部分户号当月可能无发票，跳过即可
- 每个户号可能有多张发票（专票+普票）
- 下载失败时记录失败户号，继续处理其余户号

### 第 3 步：生成详细汇总报表

1. 读取当月目录下所有已下载的 PDF 发票
2. 用 OCR 或视觉模型识别每张发票的关键字段（详见 [water_bill_config.md](references/water_bill_config.md) 中"发票结构"章节）
3. 校验用水量数据：若本期读数被截断，用发票"数量"字段修正
4. 生成 Excel 汇总表（文件名：`水费发票详细汇总_YYYYMM.xlsx`），包含 3 个 sheet：
   - **费用类目明细**：每行一个独立费用项（基本水费/不征增值税自来水/污水处理费分开），方便内网报账直接复制粘贴
   - **按户号类目汇总**：按户号×费用类目聚合的金额与用水量
   - **按费用类目汇总**：按费用类目聚合的金额合计
5. 保存到当月目录下

### 第 4 步：填写报账表格

1. 读取当月目录下已有的 6 张报账 XLS 表格（详见 [water_bill_config.md](references/water_bill_config.md) 中"报账表格"章节）
2. 将第 3 步解析的发票数据填入对应表格，字段包括：抄表日期、上次读数、本次读数、用水量、费用含税、发票类型、税率、税额等
3. 抄表日期规则：上次 = 上月 14 号，本次 = 当月 14 号
4. 按"费用类目"匹配对应表格（基本水费→基本水费表，不征增值税自来水→不征收增值税水费表，污水处理费→污水费表）
5. 保存填写后的表格

### 第 5 步：数据校验

1. 三项费用合计 = 发票价税合计（逐户号校验）
2. 用水量 = 本期读数 - 上期读数（必须为正数）
3. 3% 税额 = 金额 × 3%（专票逐条校验）
4. 若校验不通过，标记异常并提示用户确认

## 任务 B：银行扣款回单重命名

每月银行代扣水费后，工行生成电子回单 PDF（原始文件名含付款账号、扣款日期、交易流水号等），需读取 PDF 内容并按「时间-水表号-扣款金额」重命名，如 `20261008-2001024-72.90.pdf`。

完整流程、回单字段结构、零依赖 PDF 读取方案与重命名脚本见 [references/bank_receipt_rename.md](references/bank_receipt_rename.md)，核心要点：

1. **定位回单目录**：每月子目录不固定（2026年09月在 `水费\`，2026年10月在 `回单\Desktop\`）；用户给的路径不存在时，对当月目录执行 `Get-ChildItem -Recurse -Filter *.pdf` 定位实际位置
2. **读取 PDF**：本机无 PDF 库且 pip 被网络策略拦截，用「`Start-Process` 启动本地 http.server + Playwright 截图 + 视觉模型识别」方案（`Start-Job` 会被终止，勿用）；文件名中的 `#` 在 URL 中编码为 `%23`
3. **提取字段**：交易日期、水费代扣编号（即水表号）、扣款金额（数字+大写）；勿把电子回单号码、交易流水号、银行账号误当水表号
4. **交叉核对**：水表号与户号列表（water_bill_config.md）及上月回单比对；每月有费用记录的水表可能变化，新出现的水表号应能在户号列表中找到，可疑回单放大 embed 宽度后复核
5. **重命名**：PowerShell 哈希表键含 `#` 必须用单引号字面量；`Test-Path`/`Rename-Item` 用 `-LiteralPath`；完成后核对文件列表并向用户汇总表格与合计金额

## 关键规则

- **只下载当月发票**，不下载历史月份
- **专票**含基本水费（3%税率），**普票**含不征增值税自来水+污水处理费
- **3103829 户号特殊**：仅 1 张普票，同时含三项费用（基本水费+自来水+污水费），需拆分填入
- 用水量 = 本期读数 - 上期读数，必须为正数；若异常则从发票数量字段修正
- PDF 命名中的金额为价税合计的真实金额
- 抄表日期与开票日期相同

## 资源

- 户号列表、命名规则、发票结构、汇总表格式、报账表格配置 → [references/water_bill_config.md](references/water_bill_config.md)
- 银行扣款回单重命名流程、回单字段结构、零依赖 PDF 读取方案、重命名脚本坑点 → [references/bank_receipt_rename.md](references/bank_receipt_rename.md)