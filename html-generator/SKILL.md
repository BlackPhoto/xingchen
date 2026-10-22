---
name: html-generator
description: 专业 HTML 文档生成。触发词：生成HTML、写文档、做方案、做报告、生成页面、做个页面、生成网页、写个HTML、做个HTML、转Word、转PDF、转Markdown、导出文档。当用户需要生成 HTML 文档（报告/方案/方案对比/攻略/周报/数据简报/长页等）时使用此技能，支持一键转换为 Word、PDF、Markdown 格式。
name_cn: html-生成器
description_cn: 专业 HTML 文档生成工具，可快速生成报告、方案、攻略、周报、数据简报、方案对比、长页面等内容的HTML页面，并支持一键转换为 Word、PDF、Markdown 格式。
---

# HTML Generator — 通用 HTML 文档生成

**一次内容编排 · 四种格式输出（HTML / Word / PDF / Markdown）**

**核心理念**：生成放开、转换归约。生成端不设固定块模板，LLM 自由设计 HTML 结构与视觉样式；转换端通过轻量语义 class 将自由结构归约到 IR 语义，保证四种格式的转换保真度。

**视觉风格**：用户未指定时，默认按大众审美生成（排版整洁、色调舒适、整体清爽好看）。用户提出风格偏好（如"大气""炫丽""简约"）时，在保证整体美观的前提下尽量贴合。

---

## 核心工作流

### Phase 1：意图分析（自动执行，不与用户确认）

收到用户需求后，LLM 自动完成三件事：

1. **确定文档模式**：从 7 种模式中选择最合适的页面骨架（选择规则见下方，详细结构见 `references/skeletons/`）
2. **确定调色板**：从 8 组调色板中选择最合适的（选择规则见下方，读取 `references/palettes.json` 获取完整色值）
3. **确定图片策略**：默认不加图——仅当用户明确要求配图、提供本地图片或指定 URL 图片时，才插入图片并 base64 内嵌；否则不插入任何 `<img>` 标签

**不与用户确认，直接进入生成阶段。** 用户可在后续消息中显式指定模式或调色板来覆盖自动判断。

### Phase 2：生成 HTML（自动执行）

根据 Phase 1 的分析结果，按照模式骨架 + 语义 class 规范生成完整 HTML 文件。

**生成前必须 Read 以下 reference 文件（强制）**：

在编写任何 HTML 之前，LLM 必须使用 Read 工具逐个读取以下文件（前 4 个必读，第 5 个按需读取），确保使用最新规范而非凭记忆生成：

1. `references/semantic-classes.md` — 12 种块级 + 2 种辅助语义 class 的完整定义（生成端唯一必读）
2. `references/palettes.json` — 选定调色板的 20 个语义色位精确色值
3. `references/design-system.md` — 字体/字号/间距/视觉规范速查
4. 选定模式对应的 `references/skeletons/mode-{模式}.html` — 模式骨架（结构特征 + 配色引用 + 打印优化）
5. `references/interactive-pack.md` — 交互增强组件（仅当用户明确要求可交互时读取）

> **禁止凭记忆生成 HTML 模板**：如果不 Read 这些文件，生成的 HTML 会退化出裸内联样式、缺少语义 class 与模式结构，导致视觉单调且转换保真度下降。

**生成规则**（强制）：

1. **零 JS 依赖（默认）**：默认不使用任何 JavaScript，所有内容硬编码到 HTML 中。用户明确要求"可交互/可筛选/Tab 切换/可折叠"等交互功能时，从 `references/interactive-pack.md` 选取对应组件内联到 HTML 中（见下方"交互增强规则"）
2. **离线自包含**：不引用任何外部 CSS/JS/图片/字体，任何浏览器可直接打开
3. **轻量语义标记**：关键结构最外层元素必须加语义 class（12 种块级 + cite/source-list 2 种辅助，见 `references/semantic-classes.md`），转换器靠它识别内容含义。**视觉样式完全自由，不限制块模板**
4. **占位符替换（强制）**：模式骨架中所有 `{xxx}` 占位符（如 `{primary}`、`{bg_gradient_a}`、`{accent}`、`{card}`、`{text}` 等）**必须替换为 `palettes.json` 中选定调色板的真实色值**，绝不能原样保留占位符文字。例如骨架中 `background: linear-gradient(160deg, {bg_gradient_a} 0%, {card} 45%, {bg_gradient_b} 100%)` 必须替换为 `background: linear-gradient(160deg, #f8fafc 0%, #ffffff 45%, #d5e2f4 100%)`（以墨蓝调色板为例）。**未替换占位符会导致浏览器无法解析 CSS，背景色/文字色/边框色全部失效。** 替换范围包括 `<style>` 块内所有 CSS 属性值和 `data-palette` 属性
5. **当启用图片时**，图片内嵌：本地图片 → base64 内嵌；AI 生成图片 → base64 内嵌（失败降级 CSS 渐变）；外部 URL 图片 → 自动下载转 base64 内嵌；SVG 内联
6. **当启用图片时**，图片压缩：所有图片 base64 内嵌前自动压缩至 200KB 以下（压缩发生在生成端，依赖 Pillow；生成环境缺失 Pillow 时保留原图并提示，不影响转换）
7. **当启用图片时**，图片布局：通过 `data-float` 属性标注（`left|right|center|full/wrap`），转换脚本读取 data 属性而非 CSS float
8. **命名规则**：`{主题}.html`（必须使用中文主题名，如`投资尽职调查报告.html`），保存到用户工作目录
9. **div 嵌套**：不超过 5 层（正常 3-4 层够用，5 层为宽松上限）
10. **语义 class 必须配套样式**：HTML body 中出现的所有语义 class（包括 `.cite`、`.source-list`、`.src-id`、`.chart-row`、`.bar`、`.chart-labels`、`.stat-inline` 等），必须在 `<style>` 中定义对应选择器（组件类须为独立通用类，禁止挂在特定卡片容器下）。图表组件还须满足"条形数 = 标签数 = 数据项数"一一对应。自定义与模板见 `references/design-system.md` 的「图表组件规范」章节。**生成完成后自查（强制）**：遍历 HTML body 中所有 `class="xxx"`，在 `<style>` 中搜索 `.xxx` 选择器，缺失则从模式骨架中补齐对应 CSS 规则
11. **cite 与 source-list 配对使用**：当文档包含数据来源时，cite 和 source-list 必须配对使用——正文引用数据处必须插入 `<a class="cite" href="#source-N">[N]</a>` 内联标记，末尾 source-list 中对应 `<li id="source-N">` 作为跳转目标，N 一一对应。不允许只写 source-list 而正文无 cite 标记
12. **`<style>` 块**：允许使用，转换脚本会预解析提取样式规则；模式骨架的全局 `<style>` 应保留在 `<head>` 中
13. **表格列宽按内容比例分配**：每列的 `width:X%` 应根据该列实际内容字符数按比例分配，而非拍脑袋给固定值。方法：先扫描每列所有单元格，取最长一行内容的字符数，再按各列最长字符数的比例计算百分比。例如4列分别最长4字/2字/20字/25字，总量51字，则分配约8%/4%/39%/49%。这样短词列不会太窄导致断行，长内容列也有足够空间
14. **甘特图规则**：当用户要求生成甘特图时，必须使用 `table.table` 语义 class（不要创建 `.gantt-*` 等自定义 class），时间维度按季度合并（如26Q4/27Q1/27Q2），总列数不超过8列（任务名1列+季度≤7列）。禁止使用 `overflow-x: auto` 或 `overflow-x: scroll` 实现横向滚动——Word/PDF/Markdown 无滚动条概念，宽表会溢出或截断。进度条用 `<td>` 内联背景色区分（如 `style="background:{accent};"`），里程碑用文字标记（如 ★）。若用户坚持要月度级别（18列以上），生成时允许 `overflow-x: auto`，但须在转换前通过 impact_analyzer 提醒用户"甘特图列数过多，Word/PDF 可读性可能下降"
15. **SVG 图表坐标必须程序计算（强制）**：生成含 SVG 图表（饼图、环形图、折线图等）的 HTML 时，**禁止手写 path 的 `d` 属性坐标**。必须先用 Python `math.sin/cos` 按公式精确计算每个端点坐标（`x = cx + r * sin(radians(angle))`、`y = cy - r * cos(radians(angle))`），`large-arc-flag` 按 `sweep > 180° ? 1 : 0` 计算，再将计算结果写入 HTML。生成前**必须 Read `references/chart-guide.md`** 获取公式、Python 代码片段和标准 HTML 模板。颜色值必须用数组统一管理，path 的 `fill` 与 legend 的 `swatch` 引用同一份数据，禁止分别手写
16. **SVG 图表生成后强制运行 chart_validator.py 校验**：HTML 中包含 SVG 图表（饼图/环形图/柱状图/折线图/面积图/雷达图/散点图等）时，生成完成后**必须运行** `python scripts/chart_validator.py {html文件}` 进行数学校验。校验项包括：饼图/环形图（path 坐标连续性、角度总和=360°、large-arc-flag 匹配、path fill 与 legend swatch 颜色一致性）、柱状图（条形数=标签数=数据项数）、折线图（数据点数=标签数、坐标在 viewBox 范围内、多线数据点数一致）、面积图（path 闭合性、坐标在 viewBox 范围内、数据点与标签对应）、雷达图（顶点数=维度数、多边形闭合、轴角度均匀分布）、散点图（散点数=数据项数、坐标在 viewBox 范围内、半径可见）。校验失败时修复 HTML 后重新校验，直到通过。校验脚本为只读，不修改任何文件
17. **SVG 图表生成后强制截图+视觉模型检查（通用兜底）**：无论何种图表类型，生成完成后**必须**对包含图表的页面区域截图，并用视觉模型（image_understanding）检查图表形状是否正确。检查要点：饼图/环形图是否为完整圆形且扇形比例与数据匹配、折线图趋势方向是否正确、柱状图高度比例是否合理、图例颜色与图表颜色是否一致。这是 chart_validator.py 无法覆盖的图表类型（如折线图、面积图）的兜底保障，也是所有图表的最终视觉确认

**交互增强规则（可选，用户触发）**：

- 仅当用户明确要求交互功能时启用，不主动添加
- 从 `references/interactive-pack.md` 选取对应组件，将 CSS 片段追加到 `<style>` 块尾部，JS 片段内联到 `</body>` 前
- 交互组件的色值占位符（如 `{primary}`、`{border}`）必须替换为 `palettes.json` 中选定调色板的真实色值，与骨架占位符替换规则一致
- 多个交互组件的 JS 片段合并到同一个 `<script>` 标签内，总量控制在 ~2KB 以内
- 交互组件属于 L1 级（轻量 JS），转 Word/PDF/Markdown 时按降级表处理（见 `references/interactive-pack.md` 降级总表），影响分析会列出

**CSS 写法约束（分档策略）**：

| 等级 | CSS 特性 | HTML 生成 | 转 Word | 转 PDF | 转 Markdown |
|---|---|---|---|---|---|
| 自由使用 | 内联 style、margin/padding/font/color/border、width/height 百分比 | 全部允许 | 保留结构性属性 | 几乎 1:1 保留 | 保留文本与结构 |
| 允许但标注降级（装饰性） | background（纯色/渐变）、border-radius、box-shadow | 允许 | 纯色 background → shading 保留；渐变/圆角/阴影 → 丢失 | 保留 | 忽略（纯装饰） |
| 允许但标注降级 | Flexbox、Grid | 允许（必须带 data-* 标注） | 脚本按 data-* 重建表格布局 | 保留 | 按 data-* 重建列表 |
| 允许但标注丢失 | position、float、transform、animation、transition | 允许 | 丢失，列入影响清单 | 保留 | 忽略 |
| 允许但需特殊处理 | `<style>` 块、CSS 变量 var()、calc()、clamp() | 允许 | 脚本预解析 style 块提取样式 | 保留 | 忽略 |
| 禁止 | 外部 CSS 引用（`<link>`）、外部字体（@font-face 外部 URL）、外部 JS 引用（`<script src>`）、`overflow-x: auto/scroll`（横向滚动容器） | 禁止 | — | — | — |
| 允许（L1 级，用户触发） | 内联 `<script>`（交互增强，仅用户要求时） | 允许 | 交互丢失，内容保留 | 交互丢失，内容保留 | 交互丢失，内容保留 |

**Flexbox/Grid 约定**：使用 Flexbox/Grid 布局时，必须在容器元素上携带 `data-*` 属性标注布局意图（如 `data-layout="row"`、`data-cols="3"`），转换脚本读取 data- 属性而非 CSS 计算布局。

**写后自检（强制）**：write 工具写入 HTML 后，检查 filePath 中的文件名是否为中文。若为拼音/英文，立即用正确中文名重新写入，并删除错误文件。

**生成完成后**：使用 `preview_url` 或 `open_result_view` 展示给用户，并交付提示语：

> 网页版报告已完成。如需转 Word / PDF / Markdown 格式，随时告诉我，我可一键转换。

### Phase 3：格式转换（用户主动触发，可选）

用户主动说"转 Word""转 PDF""转 Markdown""导出文档"时，执行转换流程。**在 Agent 场景中，确认逻辑由 LLM 负责而非脚本交互式提示。**

> **🚫 硬性禁令：禁止自行编写转换脚本**
>
> HTML → Word/PDF/Markdown 的转换**必须**通过技能内置脚本执行（`scripts/win/convert.ps1` 或 `scripts/unix/convert.sh`），**严禁**助手自行编写 Python/JavaScript 等转换脚本。
>
> 原因：内置脚本（`html2docx_scene.py` 的 `process_collapse_group`、`html2docx_enhanced.py` 的 `process_stat_block` 等）针对折叠卡片、指标卡、时间线等 25 种 IR 语义结构有专门处理逻辑，手写脚本无法覆盖这些结构，会导致大量数据丢失。已发生过助手绕过内置脚本手写转换脚本、导致折叠卡片内 12 条招标项目详情全部丢失的事故。
>
> 如内置脚本报错，应排查报错原因并修复调用方式（如安装缺失依赖、检查文件路径），而非自行编写替代脚本。
>
> **conda 环境故障时的 venv 兜底**：如 `convert.ps1` 因 conda 环境损坏（`python.exe` 缺失或依赖包缺失）而失败，可直接用 venv 的 python.exe（`$env:USERPROFILE\.html-convert-env\Scripts\python.exe`）调用转换脚本绕过 conda 层。

**两步确认流程**（LLM 执行）：

1. **第一步：影响分析**
   - LLM 调用 `impact_analyzer.py --json` 获取结构化影响清单
   - 命令：`python scripts/impact_analyzer.py {html文件} --format {docx|pdf|md} --json`
   - 解析返回的 JSON：`{"need_remind": true/false, "items": ["...", ...], "format": "docx"}`
   - 如 `need_remind` 为 `false`（全是基础语义 class 且无结构降级），直接执行转换（跳过第二步）
   - 如 `need_remind` 为 `true`，进入第二步
   - **Word/PDF**：报告视觉降级 + 结构降级
   - **Markdown**：只报结构降级（卡片→列表、时间线→有序列表等），不报视觉降级（颜色/渐变/阴影等天然不保留属预期行为）

2. **第二步：用户确认 + 执行转换**
   - LLM 将 `items` 中的降级项以自然语言告知用户，使用 `question` 工具询问是否继续
   - 用户确认后，传 `-Yes`（Windows）或 `--yes`（Unix）跳过脚本内交互确认：
     - **Windows**：`scripts/win/convert.ps1 -Format {docx|pdf|md} -InputFile {html文件} -OutputFile {输出文件} -Yes`
     - **macOS / Linux**：`scripts/unix/convert.sh --format {docx|pdf|md} --input {html文件} --output {输出文件} --yes`
   - 用户拒绝则不执行转换

技能默认只生成 HTML，不主动运行转换脚本。

**Markdown 转换特别说明**：Markdown 只做结构保真（标题/列表/表格/代码块），所有视觉样式（颜色/渐变/阴影/布局）天然不保留，无需逐项提醒。但结构降级（卡片→列表、时间线→有序列表、对比→两组标题+列表等）仍需提醒。因此 Markdown 转换执行精简版影响分析（只报结构降级，不报视觉降级）：如 `need_remind` 为 `false`（全是基础语义 class），直接执行；否则进入第二步用户确认。

### 转换降级通知（强制）

**转换完成后，LLM 必须主动向用户报告降级/丢失的块和特性**，不得静默完成。

通知规则：

1. **Word 转换**：根据兼容性矩阵（见下方"兼容性矩阵"），逐一对照当前 HTML 中实际使用的语义 class 和 CSS 特性，列出所有会降级或丢失的项
2. **PDF 转换**：同上，但 PDF 降级极少（仅浮动定位分页偏移、动画不可静态呈现等）
3. **通知格式**：以简洁表格呈现，列为"HTML 效果 → Word/PDF 映射 → 涉及位置"
4. **无降级时**：如当前 HTML 仅使用基础语义 class（title/heading/paragraph/list/table/image）且无渐变/阴影/圆角等装饰性 CSS，则告知"无降级，内容完整保留"
5. **影响分析工具**：可调用 `impact_analyzer.py` 获取结构化降级清单（见上方两步确认流程第一步），LLM 转化为用户友好的自然语言描述

---

## 文档模式（7 种）

| 模式 | 适用场景 | 骨架文件 | 核心结构特征 |
|---|---|---|---|
| **mode-doc** | 技术方案、调研报告、通用文档 | `skeletons/mode-doc.html` | 标题→正文→小节，传统文档流 |
| **mode-compare** | 方案对比、产品选型 | `skeletons/mode-compare.html` | 多列并排卡片，推荐项高亮 |
| **mode-status** | 项目周报、进度汇报、事故报告 | `skeletons/mode-status.html` | 状态胶囊 + 时间线 + 指标数字 |
| **mode-explainer** | 教程、使用指南、概念讲解 | `skeletons/mode-explainer.html` | 正文 + 可折叠深挖 + 代码块 |
| **mode-dashboard** | 数据概览、经营简报 | `skeletons/mode-dashboard.html` | 大数字指标 + 迷你图 + 表格 |
| **mode-deck** | 产品介绍长页、品牌故事、活动专题、年度回顾 | `skeletons/mode-deck.html` | 整屏滚动吸附 + 视觉叙事 + Hero 全屏渐变 |
| **mode-auto** | 自定义/自由发挥（无匹配模式时） | `skeletons/mode-auto.html` | 精简骨架（封面+正文区+尾页），LLM 自由填组件 |

**模式选择规则（LLM 自动判断，用户可显式覆盖）**：

| 判断依据 | 选择模式 |
|---|---|
| 内容含"对比/选型/方案A vs B" | mode-compare |
| 内容含"周报/进度/事故/状态" | mode-status |
| 内容含"教程/指南/讲解/入门" | mode-explainer |
| 内容含"数据/指标/简报/概览"且含多个数字 | mode-dashboard |
| 内容含"长页/落地页/品牌故事/专题页/年度回顾" | mode-deck |
| 无法判断 | mode-doc（最通用） |

---

## 轻量语义标记（12 种块级 + 2 种辅助）

生成端唯一硬性要求：**关键结构加上语义 class**，让转换器知道"这是什么"。视觉样式完全自由。

| 语义 class | 含义 | 典型 HTML 元素 |
|---|---|---|
| `title` | 封面/大标题 | `<section class="title">` |
| `heading` | 章节标题 | `<h1 class="heading">` |
| `paragraph` | 正文段落 | `<p class="paragraph">` |
| `card` | 卡片/独立区块 | `<div class="card">` |
| `table` | 数据表格 | `<table class="table">` |
| `timeline` | 时间线/步骤 | `<ol class="timeline">` |
| `stat` | 数字指标 | `<div class="stat">` |
| `code` | 代码块 | `<pre class="code">` |
| `callout` | 提示/警告/引用 | `<aside class="callout">` |
| `image` | 图片 | `<figure class="image">` |
| `list` | 列表 | `<ul class="list">` |
| `end_page` | 尾页/结语 | `<section class="title end_page">` |
| `cite`（辅助·内联） | 数据来源引用标记 | `<a class="cite" href="#source-N">[N]</a>` |
| `source-list`（辅助·容器） | 数据来源列表 | `<div class="source-list">` |

> `cite` 与 `source-list` 是辅助 class（非块级语义 class，不在 `SEMANTIC_CLASSES` 集合）：`cite` 为段落内联标签，由段落处理流程内联转换为上标文本；`source-list` 为列表容器，内部 `class="list"` 已按列表处理。

可选 `data-*` 属性：

| 属性 | 值 | 用途 |
|---|---|---|
| `data-level` | 1/2/3 | heading 层级 |
| `data-variant` | tip/warning/quote | callout 变体 |
| `data-cols` | 2/3/4 | 多列布局列数 |
| `data-lang` | python/js/... | code 语言 |
| `data-caption` | 文本 | table/image 标题 |
| `data-float` | left/right/center/full/wrap | image 布局方向 |

**使用原则**：

- 只需在关键结构**最外层元素**加一个语义 class
- 同一语义 class 可有完全不同的视觉呈现（如 card 可以是白底圆角、渐变反白、左侧竖线等）
- 未加语义 class 的元素，转换器兜底处理为普通段落
- 详细定义见 `references/semantic-classes.md`

---

## 调色板选择规则（8 组）

根据内容类型自动匹配，用户可显式覆盖（"用暖金色""用紫韵色"）：

| 调色板 | 适用场景关键词 |
|---|---|
| **墨蓝** ink-blue | 技术、数据、项目、系统、架构 |
| **暖金** warm-gold | 活动、旅行、生活、人文、社区 |
| **青绿** teal | 教育、健康、环保、可持续 |
| **玫红** rose | 营销、创意、社交、活动 |
| **深蓝金** navy-gold | 简历、年报、商务、提案、合同 |
| **紫韵** violet | 设计、艺术、时尚、文化 |
| **橙韵** orange | 运动、餐饮、社群、活力 |
| **灰调** mono | 简历、学术、技术文档、极简 |

**完整色值请读取 `references/palettes.json`**。每套调色板统一提供 20 个语义色位（--c-primary、--c-accent、--c-bg、--c-bg_deep、--c-bg_gradient_a、--c-bg_gradient_b、--c-card、--c-text、--c-text_secondary、--c-border、--c-primary_light、--c-accent_light、--c-primary_dark、--c-accent_dark、--c-accent_bg、--c-gradient_start、--c-gradient_mid、--c-gradient_end、--c-success、--c-warning）。生成 HTML 时使用 JSON 中的精确色值。

---

## HTML 结构规范

### 基本骨架

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{文档标题}</title>
  <style>{模式骨架中的全局样式 + 响应式 + 打印优化}</style>
</head>
<body class="{mode-xxx}" data-palette="{调色板ID}">
  <!-- 自由设计的 HTML 内容 + 轻量语义 class -->
</body>
</html>
```

`<body>` 上的 `class="mode-{模式}"` 与 `data-palette="{调色板ID}"` 是转换脚本识别模式与调色板的唯一依据，必须保留。

### 文档模式参数（mode-doc 基准）

| 属性 | 值 |
|---|---|
| body max-width | 820px |
| H1 字号 | 28px |
| H2 字号 | 22px |
| H3 字号 | 18px |
| 正文字号 | 15px |
| 注释字号 | 12px |
| section 间距 | 32px（8px 基数栅格） |
| 块间距 | 16px |

---

## 图片策略

| 策略 | 说明 | 离线自包含 | 转换兼容 |
|---|---|---|---|
| CSS 渐变/几何模拟 | 无图时的降级方案 | 是 | 装饰性，转换时忽略 |
| 用户本地图片 → base64 内嵌 | 用户提供本地路径，读取后转 base64 | 是 | 完全支持 |
| AI 生成图片 → base64 内嵌 | 调用 ImageGen 生成配图，自动 base64 内嵌；失败降级 CSS 渐变 | 是 | 完全支持 |
| 外部 URL 图片 → 下载后 base64 内嵌 | 生成 HTML 时自动下载转 base64 | 是（生成后） | 完全支持 |
| SVG 内联 | `<svg>` 内联，适合图标/图表/Logo | 是 | Word 降级为 PNG；PDF 保留 |
| 图片布局 | 通过 `data-float` 属性标注（left/right/center/full/wrap） | 是 | Word 映射为表格定位；PDF 保留 |

图片压缩：所有图片 base64 嵌入前自动压缩至 200KB 以下（压缩发生在生成端，依赖 Pillow；生成环境缺少 Pillow 时保留原图并提示，转换脚本不依赖 Pillow）。

---

## 文件输出

| 产出 | 命名规则 | 保存位置 |
|---|---|---|
| HTML | `{主题}.html`（中文主题名） | 用户工作目录 |
| Word | 同名 `.docx` | 用户工作目录 |
| PDF | 同名 `.pdf` | 用户工作目录 |
| Markdown | 同名 `.md` | 用户工作目录 |

---

## 转换保真度预期

| 格式 | 语义保真 | 视觉保真 | 说明 |
|---|---|---|---|
| HTML → Word | 95% | 70% | 内容完整；卡片/时间线/画廊等降级为表格/段落 |
| HTML → PDF | 95% | 95% | 近乎 1:1 还原；仅交互式动画不可静态呈现 |
| HTML → Markdown | 90% | — | 保留标题/列表/表格/代码块结构，视觉样式不保留 |

**HTML 是源文件，Word / PDF / Markdown 是派生格式**——以 HTML 为准，转换是尽力而为的语义归约。

---

## 转换脚本说明

详见技能目录 `scripts/` 下的脚本文件与 `scripts/scripts-guide.md` 加载说明。Python 转换脚本采用四层拆分架构：公共语义层（sem_common.py）→ Word 工具层（docx_utils.py）→ 处理层（core/enhanced/scene/advanced 四层）→ 主入口（html2docx.py 分发器），三份脚本（html2docx/html2md/impact_analyzer）共用同一份语义识别逻辑。html2pdf.py 独立无依赖。win/ 和 unix/ 子目录仅保留入口脚本。转换脚本自动管理 Python 虚拟环境（venv/conda），首次运行自动安装依赖（含 Playwright Chromium 下载）。依赖清单见 `scripts/requirements.txt`，cssutils 为可选增强（未安装自动跳过）。


### 兼容性矩阵

| 语义 class | 归约到 IR 语义 | Word 映射 | PDF 映射 | Markdown 映射 |
|---|---|---|---|---|
| title | title_page | 居中段落 + 背景色 shading | 新起一页 + 居中 + 渐变背景 | # 标题 |
| heading | heading | Heading 1/2/3（keep_with_next） | 保留，level=1 新起一页 | # / ## / ### |
| paragraph | paragraph | Body 段落 | 保留 | 正文文本 |
| card | card_grid / comparison / columns | 无边框表格 + 卡片 shading | 保留 | 分组标题 + 列表 |
| table | table / pricing_table | Word Table | 保留 | Markdown 表格 |
| timeline | timeline | 两列表格（时间列 accent 加粗） | 保留 | 有序列表 |
| stat | stat_block | 无边框表格 + 卡片 shading | 保留 | 加粗数字文本 |
| code | code_block | Consolas + 浅灰底色 | 保留 | 围栏代码块 |
| callout | callout | 底色 + 左边框段落 | 保留 | > 引用 |
| image | image | InlineShape | 保留 | ![alt](data:...) |
| list | bullet_list | 列表段落 | 保留 | 列表 |
| cite | cite | 上标文本（链接丢失，保留 `[N]` 文本） | 保留上标文本 | `[N]` 纯文本 |
| source-list | source_list | 有序列表 | 保留 | 有序列表 |
| 无 class 元素 | paragraph（兜底） | Body 段落 | 保留 | 普通文本 |
| 未知图表/图形容器（含 svg/canvas，flex/grid 布局无文本） | chart_unknown（兜底） | 三层降级：Playwright 截图插入 → 数据提取重建表格 → 跳过 | 保留 | 文本提取为列表 |
| 内联 `<script>`（交互增强） | —（非语义 class） | 交互丢失，内容保留（Tab→全部展开、折叠→全部展开、表格搜索→保留表格无搜索、复制按钮→丢失、返回顶部→丢失） | 交互丢失，内容保留（同 Word） | 交互丢失，内容保留（同 Word） |

> **上表中的 Word/PDF/Markdown 映射逻辑已全部内置在 `scripts/` 下的转换脚本中（25 种 IR × 3 种格式），助手无需也不应自行实现这些映射。转换时必须调用内置脚本，禁止手写转换逻辑。**

### 转换兜底策略（内置）

转换脚本内置以下兜底机制，助手无需手动处理，脚本自动执行：

| 场景 | 兜底逻辑 | 涉及脚本 |
|---|---|---|
| 封面/尾页行高不匹配 | 行高动态计算：从 docx section 页面高度减去上下边距，兜底 20cm，确保垂直居中生效 | html2docx_core.py / html2docx_advanced.py |
| 无文本容器（纯图片/SVG）被跳过 | flatten_semantic_blocks 增加媒体子元素检测（img/svg/figure/canvas/video），含媒体的容器不跳过 | sem_common.py |
| 未知图表/图形容器 | chart_unknown IR：三层降级——① Playwright 光栅化截图插入 PNG；② 递归提取 SVG 文本/数据属性重建表格；③ 零文本零数据装饰元素直接跳过 | sem_common.py + html2docx_scene.py |
| 尾部空白页 | 清理孤立空段落、压缩表格后必需段落到 1pt | html2docx.py |
| 格式健康 | 修正超宽表格（pct>5000→5000）、缩小超大图片、删除全空表格 | html2docx.py |

**chart_unknown 识别特征**（结构特征，不依赖 class 名）：含 `<svg>`/`<canvas>` 元素，或 flex/grid 布局且子元素无文本且 height 比例异常。识别后由 `process_chart_unknown` 执行三层降级。

### 分页规则

| 格式 | 分页规则 |
|---|---|
| Word | title / end_page → 分页符；heading(data-level=1) 不再强制分页（减少留白，内容顺延）；其余顺延 |
| PDF | title / end_page → 新起一页；heading(data-level=1) → 新起一页；内容溢出自动分页；divider 为空白间隔 |
| Markdown | 无分页概念，以 `---` 分隔线切分章节 |