---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: '89bc07ef-14a3-4d76-8b4f-d6add2a91f3d'
  PropagateID: '89bc07ef-14a3-4d76-8b4f-d6add2a91f3d'
  ReservedCode1: '46076fe2-6886-415a-a9bc-492f898ce522'
  ReservedCode2: '46076fe2-6886-415a-a9bc-492f898ce522'
---

# 排版 PPT 生成工作流

## 这个 Skill 做什么

将PPT大纲、Markdown素材或结构化内容转换为可翻页浏览的HTML演示文稿，并默认转换为可编辑PPTX文件。

## Context

当前工作目录: !`pwd`
输出目录: `{主题}_output/`（根据用户输入的PPT大纲主题动态生成，例如"xx产品规划方案" → `xx产品规划方案_output/`，自动创建）
**文件归档总规则**：`{主题}_output/` 仅存放最终交付物——PPTX 文件。所有 HTML 文件（slide_XX.html、index.html、单文件HTML）、截图PNG、几何体检 JSON、体检报告 HTML/JSON、转换报告 JSON 均为中间过程文件，统一存放到 `.temp/`（先执行 `New-Item -ItemType Directory -Force -Path ".temp" | Out-Null` 创建，macOS/Linux 用 `mkdir -p .temp`）。`.temp/` 为隐藏归档区，不向用户展示、不列入交付清单
风格指引: `references/style-guide.md`
配色主题: `references/color-themes.json`
设计Prompt模板: `references/design-prompt-template.md`
打包脚本: `scripts/pack_slides.py`
PPTX转换引擎: `scripts/html2pptx.py`（将HTML幻灯片转换为可编辑的PPTX，依赖 extract.js + h2p_config.py + TestCase/font_metrics.json）
转换引擎指南: `references/html2pptx-guide.md`（转换前必读，了解引擎能力、用法参数与已知限制）
排版体检指南: `references/slide-audit-guide.md`（步骤3.6执行前必读，了解引擎规则、阈值与已知限制）
排版体检引擎: `scripts/slide-audit.mjs` + `scripts/engine.js`（无头Chrome真实几何测量，不依赖多模态模型）

## Your task

将用户提供的原始素材（PPT大纲、Markdown内容等）转换为可直接在浏览器中翻页浏览的HTML演示文稿幻灯片。

## 工作流程

按以下步骤顺序执行，不可跳过。核心流程为：**对每一页执行【生成HTML → 布局自检 → 几何体检 → 截图+多模态检查 → 修复 → 再检查】单页闭环**，全部页面通过后才进入打包 → 全量体检 → 转换PPTX。**禁止先批量生成多页再统一检查**。

### 步骤0：检查输入素材完整性

**必须首先执行此步骤**，判断用户输入是否包含可直接生成幻灯片的素材。

**判定逻辑**：
- 如果用户只提供了一个**主题/标题**（如"xx产品规划方案"、"新员工培训"），而没有逐页的大纲内容 → **素材不完整**
- 如果用户提供了**分页大纲**（包含各页标题和内容要点）、或完整的Markdown结构化内容、或素材文件 → **素材完整，继续步骤1**

**素材不完整时的处理**：

使用 question 工具询问用户选择：

> 当前只有主题"xxx"，尚未提供分页PPT大纲。请选择：
> 1. **自行输入大纲** — 我提供完整的分页大纲内容
> 2. **帮我生成大纲** — 根据主题帮我生成一份分页PPT大纲，确认后再开始制作

- 如果用户选择"自行输入"，等待用户输入后继续
- 如果用户选择"帮我生成大纲"，根据主题生成一份分页大纲（建议8-12页，每页含标题+3-5个要点），展示给用户确认后再继续
- 用户确认大纲后，**将确认后的大纲作为后续步骤的输入素材**，进入步骤1

**素材完整时**：直接进入步骤1。

### 步骤1：分析素材，确认页面清单、输出目录与配色主题

阅读用户提供的素材文件，识别所有页面：
- 确认总页数 N
- 为每页提取：页码、标题、内容要点、建议布局
- 向用户确认页面清单（如页数过多可建议合并/拆分）

**确定输出目录**：
- 从用户输入的PPT大纲标题/文件名中提取主题（去除"大纲""方案"等无意义后缀及 `\/:*?"<>|` 等Windows / macOS 非法文件名字符；macOS 仅 `:` 和 `/` 为非法）
- 输出目录 = `{主题}_output/`，在工作目录下创建
- 示例：用户输入"xx产品规划方案大纲" → 主题="xx产品规划方案" → 输出目录=`xx产品规划方案_output/`
- 后续所有步骤中引用的输出目录均使用此动态目录

**确定配色主题**：
- 读取 `references/color-themes.json`，解析 `selection_guide` 数组
- 将用户素材的标题、内容关键词与每条 `selection_guide` 的 `match_keywords` 进行匹配
- 命中关键词最多的主题即为选定主题；若无任何命中，使用 `default_theme`（tech-blue）
- **不向用户确认**，静默选定后在步骤5的首条进度报告中顺带提及主题名称
- 选定后，后续所有步骤的色值均取自 `themes.{选定主题}` 的字段

### 步骤2：逐页生成设计Prompt

对每一页，使用 `references/design-prompt-template.md` 中的模板，结合 `references/style-guide.md` 中的风格规范，生成该页的**画面设计Prompt**。

设计Prompt必须包含：
- 页面元信息（编号、标题、画布尺寸1280×768px、基调、逻辑关系）
- 空间布局（基于逻辑关系选择布局模式，必须遵守"页面结构规范"和"布局约束规则"）
- 文字层（每个文字元素的精确位置、字号、颜色）
- 图形与图表层
- 颜色系统（取自选定主题，与 color-themes.json 一致）
- 层级与叠放顺序
- 技术实现约束

### 步骤3：逐页生成HTML

**单页边界：本步骤仅生成当前页的 HTML，写完立即进入步骤3.5（布局自检）→ 步骤3.6（几何体检）→ 步骤4（多模态检查），不得连续生成多页后再检查。**

#### 图片嵌入（如有图片元素）

当某页设计 Prompt 中包含图片（封面图、背景图、配图等）时，必须在生成 HTML 之前完成图片准备：

1. **获取图片来源**：
   - AI 生图：使用 ImageGen 工具生成图片，保存到 `{主题}_output/images/` 目录
   - 用户提供的图片：确认图片路径

2. **读取图片为 base64**：使用 Python 脚本将图片转为 base64 字符串：
   ```python
   import base64
   with open("images/cover.jpg", "rb") as f:
       b64 = base64.b64encode(f.read()).decode()
   src = f"data:image/jpeg;base64,{b64}"
   ```

3. **写入 HTML**：将 base64 字符串直接写入 `<img>` 标签的 `src` 属性或 CSS `background-image: url(...)` 中，不使用外部文件路径

4. **体积控制**：单张图片原始大小建议不超过 500KB（base64 编码后约 670KB），整个 deck 图片总量建议不超过 5MB；过大图片应先用 Python 缩放或压缩再编码

根据每页的设计Prompt，使用 `references/style-guide.md` 中的CSS变量和组件样式，生成该页的完整HTML文件。

文件命名规则：`slide_XX.html`（XX为两位页码，如01、02、03...）

每个HTML文件必须：
- 精确 1280×768px 画布
- 使用 `position: absolute` 精确定位所有元素
- 所有CSS写在 `<style>` 标签内
- 所有矢量图形使用内联SVG
- 不使用任何外部CDN资源
- 图片使用 base64 内嵌（`<img src="data:image/png;base64,...">` 或 CSS `background-image: url(data:image/png;base64,...)`），不使用外部文件路径引用；单张图片原始大小建议不超过 500KB（base64 编码后约 670KB），整个 deck 图片总量建议不超过 5MB
- 不使用JavaScript（纯静态HTML+CSS+SVG）
- 字体栈：`"PingFang SC", "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif`
- 包含页码标记（第 X / N 页）
- 文字最小字号不低于18px
- 保存到 `{主题}_output/` 目录
- **严格遵守以下所有规则**

---

### 页面结构规范

每页必须遵循以下纵向分区结构（除非是全幅封面/分节页等特殊页面）：

```
┌──────────────────────────────────── 1280px ────────────────────────────────────┐
│ [顶部标题栏]  top:0 ~ top:80px                                          │
│   左侧：页面标题（left:48px）                     右侧：Logo区（right:48px）     │
├─────────────────────────────────────────────────────────────────────────────┤
│ [主内容区]  top:80px ~ bottom:60px (高度=628px)                            │
│   所有主要内容（卡片、图表、流程图等）必须在此区域内                       │
│   内容应充分填充此区域，不得大面积留白                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│ [底部数据/信息栏]  bottom:60px ~ bottom:0 (高度=60px)                       │
│   KPI数据、案例引用、补充信息等                                           │
│   页码标记放在此栏右侧                                                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Logo 区域规则**：
- 右上角 `top:24px; right:48px` 区域保留给 Logo
- Logo 区域宽约 160px，高约 40px
- **禁止在 Logo 区域放置任何标题标签、角标、badge 等内容**

**主内容区填充规则**：
- 主内容区的所有子区块（如左右面板、流程卡片组、数据网格等）的 top 和 bottom 坐标必须与主内容区边界对齐
- 主内容区内不得出现超过 100px 的纯空白间隙（区块之间 20-48px 间距是正常的）
- 如果内容量不足以填满主内容区，应通过增大字号、增大卡片间距、增大元素尺寸来适配，而非留出大片空白

---

### 色彩约束规则

**配色由 `references/color-themes.json` 唯一定义。** 步骤1 会根据素材内容自动选定一套配色主题，所有页面的色值必须严格取自该主题的字段，禁止自造色值。

**色值来源映射**：

| CSS 变量 | JSON 字段路径 | 用途 |
|----------|--------------|------|
| `--primary-blue` `--primary-dark` `--primary-light` `--accent-blue` | `themes.{theme}.primary.*` | 主强调、图标、按钮、数据 |
| （直接取值，非CSS变量） `aux1` `aux2` `aux3` | `themes.{theme}.secondary_palette.aux1/aux2/aux3` | 辅助区分、次级强调 |
| （直接取值，非CSS变量） `neutral_dark` `neutral_mid` `neutral_light` | `themes.{theme}.secondary_palette.neutral_*` | 中性文字、分隔线 |
| `--text-primary` `--text-secondary` `--text-muted` | `themes.{theme}.text.*` | 标题/正文/辅助文字 |
| `--white` `--bg-gray` | `themes.{theme}.background.main/secondary` | 页面/分区/卡片底色 |
| （直接取值，非CSS变量） `background.tertiary` | `themes.{theme}.background.tertiary` | 三级背景色 |
| `--border-light` `--border-card-tint` | `themes.{theme}.border.*` | 边框、卡片淡边 |
| `--gradient-blue` `--gradient-light` `--gradient-card` | `themes.{theme}.gradients.main/light/card` | 渐变背景 |
| （直接取值，非CSS变量） `gradients.radial` | `themes.{theme}.gradients.radial` | 径向渐变 |
| `--shadow-sm` `--shadow-md` `--shadow-lg` `--shadow-xl` | `themes.{theme}.shadows.*` | 阴影系统 |
| `--text-on-primary` | `themes.{theme}.text_on_primary` | 渐变底/主色底上的文字色 |
| `--tag-bg-on-primary` | `themes.{theme}.tag_bg_on_primary` | 渐变底上的标签底色 |

> **变量名以 `references/style-guide.md` 的 `:root` 定义为准。** JSON 中 `secondary_palette` 和 `background.tertiary`、`gradients.radial` 未定义为 CSS 变量，生成 HTML 时直接从 JSON 取值内联使用。

**配色合规**：遵守选定主题的 `qa_rules` 字段。`strictness: strict` 的主题（如 tech-blue）逐色检查，禁止使用主题色系以外的色相；`strictness: standard` 的主题检查整体色调一致性，允许中性色合理搭配。

**区分场景/类别时**：使用主题色系内的深浅明暗变化或灰度变化来区分，禁止自造主题外的色值。

---

### 布局约束规则

**1. 左右分栏对齐（slide_03 类页面）**
- 左面板和右面板必须共享相同的 `top` 和 `bottom` 值（即同高、上下对齐）
- 例如：左面板 `top:80px; bottom:60px`，右面板也必须 `top:80px; bottom:60px`

**2. 卡片内容密度**
- 卡片内部不得出现超过卡片面积 40% 的空白区域
- 如果卡片内只有 1-2 个数字，不得将卡片做得很大；应使用紧凑布局或与其他内容合并
- 卡片的 padding 应为 16-32px，内容与卡片边缘距离合理

**3. 流程/步骤类布局（slide_04 类页面）**
- 流程区域（如横向三步卡片）应占据主内容区 60-75% 的高度
- 底部数据栏紧接流程区域下方，两者之间的间距为 20-32px（不得出现超过 100px 的空白带）
- 如果流程区域无法自然填满，应增大流程卡片高度或增加数据栏内容

**4. 中心辐射布局（slide_02 类页面）**
- 中心节点必须位于主内容区的几何中心
- 外围节点均匀分布在以中心为圆心的圆上，角度间隔 = 360° / N
- 节点到中心的连接线必须完整（每条线从中心边缘到节点边缘，N 个节点 = N 条线）
- 所有节点必须在主内容区内，不得超出边界

---

### 步骤3.5：布局差异化自检（从第2页起，不可跳过）

在生成每页HTML后、截图前，**必须将当前页与已生成的所有前一页进行布局差异对比**，避免视觉单调。

#### 自检维度

| 维度 | 检查内容 | 判定 |
|------|----------|------|
| 布局框架 | 当前页的布局模式是否与前1页不同？是否与前2页也不同？ | 连续2页相同框架 → 需调整 |
| 主区域样式 | 核心内容区是否使用了与前页不同的卡片/背景样式？（如前页是白卡+蓝侧栏，本页应换为蓝渐变全幅卡或三栏式） | 连续2页同一样式 → 需调整 |
| 视觉重心 | 页面的视觉重心位置是否有变化？（如前页重心偏左，本页应居中或偏右/偏上/偏下） | 连续3页重心相同 → 需调整 |

#### 常用布局模式库（按需轮换，不要反复用同一种）

1. **3×2 / 2×3 卡片网格** — 适合总览、并列数据
2. **上KPI横排 + 中全幅产品条 + 下左右双栏** — 适合产品介绍（优势+技术分离）
3. **上KPI + 中双产品对比（左白右蓝） + 底战略条** — 适合双线产品/场景
4. **三栏式（窄指标列 | 产品规格 | 生态安全）** — 适合指标密集型
5. **上KPI + 上下对比 + 侧边竖条** — 适合桌面/服务器双线对比
6. **上KPI + 横向三等分特性卡 + 底聚焦条** — 适合三大特性并列
7. **中心辐射布局** — 适合一个核心+多个外围
8. **左右对称分栏** — 适合矩阵对比
9. **全幅封面/分节页** — 适合章节切换

#### 调整原则

- 如果自检发现布局与前页雷同，**不需要重新写设计Prompt**，只需调整HTML中的布局实现方式（如换一种卡片排列、换一个区域背景样式、调整分区比例）
- 风格统一≠布局统一：颜色系统、字体、圆角、阴影保持一致，但分区方式、卡片样式、视觉重心应变化
- 总页数≤3时，每页布局应各不相同；总页数>3时，允许相隔2页以上的页面使用相似布局

---

### 步骤3.6：几何体检（强制步骤，每页必检）

每生成一页 HTML 并完成步骤3.5 布局差异自检后，运行几何体检。引擎用真实无头 Chrome 测量页面几何，~0.5秒/页，不依赖多模态模型。规则细节、参数说明与已知限制详见 `references/slide-audit-guide.md`。

```powershell
# Windows (PowerShell)
# 先确保 .temp/ 存在（首次运行时）
New-Item -ItemType Directory -Force -Path ".temp" | Out-Null
# --no-out 跳过可视化报告和截图生成（步骤3.6 逐页体检只需 JSON 结果，报告会被下一页覆盖，省时间）
node scripts/slide-audit.mjs "{主题}_output/slide_XX.html" --fail-on error --json ".temp/slide_XX.audit.json" --no-out
```
```bash
# macOS / Linux (zsh/bash)
mkdir -p .temp
node scripts/slide-audit.mjs "{主题}_output/slide_XX.html" --fail-on error --json ".temp/slide_XX.audit.json" --no-out
```

处理逻辑：
- **0 error** → 进入步骤4（多模态视觉检查）
- **有 error** → 按报告中的修复建议（含精确像素值与源码行号）修改 HTML，重新体检；最多重试 3 次
- **warning** → 判断是否可接受后继续（OVERLAP / LOW_CONTRAST 建议修复，其余评估）

分工：几何体检能快速精确修掉大部分数值问题（溢出/重叠/遮挡/裁切/越界/截断/字号/对比度），减少后续多模态检查的次数和误判。但几何体检不是万能的，步骤4 多模态检查仍照常执行，可能发现几何体检漏掉的情况。

---

### 步骤4：多模态视觉检查（强制步骤，每页必检，无需用户额外说明）

**每生成一页 HTML 后，立即进行截图 + 视觉检查。无需等待用户指示，这是默认强制流程。** 使用系统截图工具对 HTML 文件生成截图，然后对截图进行视觉审查。

**单页闭环边界：上一页通过全部检查（或达 3 次重试上限）后，才允许开始生成下一页 HTML；未通过检查前禁止先批量生成后续页面。**

#### 4.1 截图方法

**Windows (PowerShell)** — 使用 Edge/Chrome 无头模式截图：

```powershell
$edgePath = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
# $outDir 为步骤1确定的输出目录，替换为实际目录名（如 "xx产品规划方案_output"）
$outDir = "{主题}_output"
# 截图是中间质检文件，存放到 .temp/（绝对路径，须先创建 .temp/ 目录）
New-Item -ItemType Directory -Force -Path ".temp" | Out-Null
# HTML 输入必须转成自动百分号编码的 file URI：含中文的相对路径会被无头浏览器
# 当作 URL 解析（中文被当域名 → DNS 错误页）。Resolve-Path 转绝对，[System.Uri] 负责编码
$slideUri = ([System.Uri] (Resolve-Path "$outDir/slide_XX.html").Path).AbsoluteUri
# 必须使用独立的 --user-data-dir 临时目录：与用户正在使用的浏览器完全隔离，
# 防止无头 Edge 复用用户配置目录导致截图失败或误关用户浏览器
$tmpProfile = Join-Path $env:TEMP ("slide-screenshot-" + (Get-Random))
$shotAbs = (Resolve-Path ".temp").Path + "\slide_XX.png"
$params = @{
  FilePath = $edgePath
  ArgumentList = "--headless","--disable-gpu",("--user-data-dir=" + '"' + $tmpProfile + '"'),
    "--hide-scrollbars",
    "--screenshot=$shotAbs","--window-size=1280,768","--force-device-scale-factor=1","$slideUri"
}
Start-Process @params -Wait -NoNewWindow
# 临时目录位于 %TEMP% 下，由系统定期自动清理，无需手动删除（手动删除会触发安全护栏确认弹窗）
# 截图失败检测：PNG 未生成时换新临时目录重试一次
if (-not (Test-Path $shotAbs)) {
  $tmpProfile2 = Join-Path $env:TEMP ("slide-screenshot-" + (Get-Random))
  $params2 = @{
    FilePath = $edgePath
    ArgumentList = "--headless","--disable-gpu",("--user-data-dir=" + '"' + $tmpProfile2 + '"'),
      "--hide-scrollbars",
      "--screenshot=$shotAbs","--window-size=1280,768","--force-device-scale-factor=1","$slideUri"
  }
  Start-Process @params2 -Wait -NoNewWindow
}
```

**macOS / Linux (zsh/bash)** — 使用系统已安装的 Chrome 或 Edge 无头模式截图：

```bash
# 自动探测浏览器路径（Chrome 优先，其次 Edge / Chromium）
CHROME="$(ls "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" "/Applications/Chromium.app/Contents/MacOS/Chromium" /usr/bin/google-chrome /usr/bin/google-chrome-stable /usr/bin/chromium 2>/dev/null | head -1)"

# $outDir 为步骤1确定的输出目录，替换为实际目录名（如 "xx产品规划方案_output"）
outDir="{主题}_output"

# HTML 输入必须转成自动百分号编码的 file URI：含中文的相对路径会被无头浏览器
# 当作 URL 解析（中文被当域名 → DNS 错误页）。resolve 转绝对，as_uri 负责编码
SLIDE_URI="$(python3 -c 'import sys,pathlib;print(pathlib.Path(sys.argv[1]).resolve().as_uri())' "$outDir/slide_XX.html")"

# 必须使用独立的 --user-data-dir 临时目录：与用户正在使用的浏览器完全隔离，
# 防止无头 Chrome 复用用户配置目录导致截图失败或误关用户浏览器
TMP_PROFILE="$(mktemp -d /tmp/chrome-screenshot.XXXXXX)"

# 截图是中间质检文件，存放到 .temp/（绝对路径）
mkdir -p .temp
SHOT_ABS="$(cd .temp && pwd)/slide_XX.png"
"$CHROME" --headless=new --disable-gpu --no-first-run --no-default-browser-check --user-data-dir="$TMP_PROFILE" --hide-scrollbars --screenshot="$SHOT_ABS" --window-size=1280,768 --force-device-scale-factor=1 "$SLIDE_URI"
# 临时目录位于 /tmp 下，由系统自动清理，无需手动删除（rm -rf 会触发安全护栏确认弹窗）
# 截图失败检测：PNG 未生成时换新临时目录重试一次
if [ ! -f "$SHOT_ABS" ]; then
  TMP_PROFILE2="$(mktemp -d /tmp/chrome-screenshot.XXXXXX)"
  "$CHROME" --headless=new --disable-gpu --no-first-run --no-default-browser-check --user-data-dir="$TMP_PROFILE2" --hide-scrollbars --screenshot="$SHOT_ABS" --window-size=1280,768 --force-device-scale-factor=1 "$SLIDE_URI"
fi
```

> macOS 上 Chrome 无头截图必须带 `--user-data-dir` 指向临时目录，避免与已运行的 Chrome 冲突。**禁止使用 `pkill -f "Google Chrome"` 等按进程名方式关闭浏览器——这会关闭用户正在使用的所有浏览器窗口和标签页。** 若截图文件未生成，使用 `mktemp -d` 换一个新的临时目录重试（旧临时目录可能残留 Chrome 单实例锁）。

#### 4.2 截图识别通道（原生多模态优先），必须执行，不可跳过

截图生成后，**必须按以下优先级顺序**对截图进行视觉审查：

1. **首选：原生多模态能力直接读取截图**
   - 使用 Read 工具直接读取截图 PNG 文件（Read 工具原生支持图片文件的多模态读取）
   - 读取成功后，基于返回的图片内容完成 4.3 节检查清单的结构化审查
   - 若 Read 工具成功返回图片内容且能完成全部 16 项检查 → **直接通过，无需降级**

2. **降级：图像理解工具**
   - **仅当**满足以下任一条件时才降级：
     - 当前模型不具备视觉能力（Read 工具读取图片返回空或报错）
     - 原生多模态读取成功但无法有效完成结构化审查（如图片内容无法解析）
   - 降级时调用 `image_understanding` 工具，传入截图路径作为 `file_path` 参数

3. **降级必须留痕**：
   - 若发生降级，在当页进度报告中**显式标注降级原因**，格式如：
     `slide_03（XXX）— CHECK_PASSED (3/5) [降级:image_understanding，原因: 原生多模态读取返回空]`
   - 不得静默降级，不得跳过原生多模态直接调用 image_understanding

#### 4.3 检查清单（16 项，每项 PASS/FAIL）

基于截图内容进行结构化审查，使用以下 prompt：

```
请作为PPT视觉质检员，逐项严格检查这张幻灯片截图，每项给出 PASS 或 FAIL。

【页面结构】
S1. Logo区域：右上角(top:24px right:48px)是否为Logo区？该区域是否放置了标签/badge/角标等非Logo内容？（是→FAIL）
S2. 页面纵向分区：页面是否分为标题栏(顶部80px) + 主内容区(中间) + 底部栏(底部52px)？主内容区是否从top:80px开始？
S3. 区块间距：主内容区内的各个区块之间，是否出现了超过100px的空白间隙？（是→FAIL）
S4. 区块衔接：主内容区底端与底部栏之间，是否存在超过50px的空白带？（是→FAIL）

【布局对齐】
S5. 左右面板对齐：如果页面有左右分栏，左右两个面板的上下边界是否对齐（同top同bottom）？（否→FAIL）
S6. 卡片对齐：同级别的卡片/列表项是否水平或垂直对齐一致？（否→FAIL）

【内容密度】
S7. 大空白卡片：是否存在明显过大但内容极少的卡片（空白面积超过卡片40%）？（是→FAIL）
S8. 内容填充：主内容区整体是否被合理填充，没有大面积无意义的空白？（是→FAIL）

【基础质量】
S9. 内容溢出：是否有文字/图片/卡片超出画布边界（1280×768px）？
S10. 元素重叠：是否有两个或多个内容元素互相遮盖导致无法阅读？
S11. 文字截断：是否有文字被截断、显示不完整？
S12. 字号合规：所有可见文字是否≥18px？
S13. 配色合规检测（致命项）：页面色值是否全部来自选定主题？是否出现主题 qa_rules 中禁止的色相？（strict 主题：逐色检查，色系外色相→FAIL；standard 主题：检查整体色调是否与主题 primary_tone 一致，明显偏离→FAIL）。数据趋势指示器（绿涨红跌）豁免。
S14. 可读性：对比度是否足够？文字颜色与背景色是否区分明显？
S15. 语义完整：设计Prompt中要求的所有内容元素是否都已呈现？
S16. 布局差异化：当前页的布局模式是否与前一页有明显区别？连续2页是否使用了不同的布局框架和主区域样式？（连续2页相同布局→FAIL）

判定标准：
- S1~S16 全部 PASS → "CHECK_PASSED"
- 任何一项 FAIL → "CHECK_FAILED"，列出所有 FAIL 项 + 具体修复建议（需说明修复什么、怎么改）
```

#### 4.4 检查结果处理

- **CHECK_PASSED**：该页通过检查，进入下一页生成。
- **CHECK_FAILED**：根据多模态模型的修复建议，直接编辑 `slide_XX.html` 修复问题，然后**重新截图检查**。
- **最多重试 3 次**：如果 3 次检查后仍失败，保留最佳版本并标记，继续下一页，最后统一汇报。

### 步骤5：循环处理所有页面

对每一页依次执行单页闭环，伪代码如下：

```
for 页码 = 1..N {
    步骤2（设计Prompt）→ 步骤3（生成HTML）→ 步骤3.5（布局自检）
    → 步骤3.6（几何体检，error 修复后复检）
    → 步骤4（截图+多模态检查，FAIL 修复后重检）
}
```

**循环约束**：内层任何一步未通过（或未达重试上限）时，不得进入下一轮的步骤2/步骤3，即上一页通过检查后才允许开始下一页。

每完成一页，向用户简要报告进度，格式如：
```
配色主题：商务科技蓝（tech-blue）
slide_01（五大核心痛点）— CHECK_PASSED (1/1)
slide_02（七大场景总览）— CHECK_FAILED，修复后 PASSED (2/2)
```
首行显示配色主题名称（仅第一页报告中输出），后续页面报告中省略主题行。

### 步骤6：生成导航与打包

所有 slide 生成并通过检查后，运行打包脚本一次性生成两个导航文件：

```
python scripts/pack_slides.py {主题}_output/ "{主题}" {主题key}
```

第二个参数传入步骤1确定的主题，确保单文件命名前缀与输出目录名一致（`{任务名称}` = `{主题}`）；不传时脚本会自动从第一页 `<title>` 提取，可能与目录名不一致。

第三个参数（可选）传入主题 key（如 `party-red-gold`），让导航栏强调色（输入框聚焦、翻页按钮 hover、底部圆点 active）跟随主题 `primary.accent` 色，而非默认硬编码蓝色。主题 key 为 `references/color-themes.json` 中 `themes` 下的键（`tech-blue` / `party-red-gold` / `celadon-newchinese` / `ink-dark-gray` / `tech-neon-dark` / `green-natural`）。不传时回退到经典蓝色 `#2b7de9`，行为与旧版完全一致。

脚本会自动生成：
- **`index.html`** — 多文件预览版（iframe src 引用各 slide 文件，需保持同目录）
- **`{任务名称}{MMDD}.html`** — 单文件分享+编辑版（`<script type="text/html">` 块内嵌原始HTML，通过 `iframe.srcdoc` 加载，零外部依赖）

**单文件命名规则**：
- 文件名 = 任务名称（去除非法字符） + 当日MMDD + `.html`
- 例如：`星辰培训0627.html`、`智能体演讲0627.html`
- 任务名称来自打包脚本的第二个参数，或自动从第一页 `<title>` 提取
- 日期后缀自动取当天日期，无需手动指定

**单文件内嵌格式**：
- 每页幻灯片HTML存储在 `<script type="text/html" id="slide-N">` 块中（浏览器不会执行此类 script 块）
- 导航JS通过 `document.getElementById('slide-N').textContent` 读取内容，设置 `iframe.srcdoc` 加载
- 用户可直接在HTML源码中找到对应的 `slide-N` 块进行编辑，修改后刷新浏览器即可看到效果
- 相比v4的base64编码方式，srcdoc方式让HTML源码完全可读可编辑

两个版本共享相同的导航体验：
- 深色背景（#1a1a2e）+ 毛玻璃效果
- 顶部信息栏（标题 + 页码跳转输入框 + 键盘提示）
- 左右两侧翻页按钮
- 底部圆点指示器（多页时自动滚动到当前页）
- JavaScript 动态缩放（自适应任意屏幕尺寸）
- 键盘快捷键（←→↑↓ 翻页，Home/End 首末页）
- 触摸滑动支持

如需自定义标题（覆盖主题名），可传入 `python scripts/pack_slides.py {主题}_output/ "我的演示文稿"`；此时单文件前缀与目录名不一致属预期行为。

### 步骤6.5：打包后全量体检（推荐执行）

打包生成的单文件 HTML（`<script type="text/html">` 内嵌块）会被引擎自动拆分逐页体检，行号映射回源码：

```powershell
# Windows (PowerShell)
node scripts/slide-audit.mjs "{主题}_output/{任务名称}{MMDD}.html" --out ".temp/audit-report.html" --json ".temp/audit-report.json"
```
```bash
# macOS / Linux (zsh/bash)
node scripts/slide-audit.mjs "{主题}_output/{任务名称}{MMDD}.html" --out ".temp/audit-report.html" --json ".temp/audit-report.json"
```

- 有 error：按报告修复对应页 HTML，重新打包（步骤6）后再体检
- 通过后进入步骤7（PPTX转换）

---

### 步骤7：转换为PPTX（默认执行）

步骤6打包完成后，默认执行HTML→PPTX转换，将幻灯片转为可编辑的PPTX文件。

#### 7.0 读取转换引擎指南

执行转换前，先读取 `references/html2pptx-guide.md`，了解引擎的转换能力、用法参数与已知限制，确保带着理解去执行和验收。

#### 7.1 检查依赖

确认以下依赖已安装：
```
python -c "import pptx, PIL, websocket; print('deps OK')"
```
如缺失，安装：`pip install python-pptx pillow websocket-client`

#### 7.2 执行转换

使用步骤6生成的单文件HTML（`{任务名称}{MMDD}.html`，内嵌 `<script type="text/html" id="slide-N">` 块）作为输入：

```powershell
# Windows (PowerShell)
python scripts/html2pptx.py "{主题}_output/{任务名称}{MMDD}.html" -o "{主题}_output/{任务名称}{MMDD}.pptx"
```
```bash
# macOS / Linux (zsh/bash)
python3 scripts/html2pptx.py "{主题}_output/{任务名称}{MMDD}.html" -o "{主题}_output/{任务名称}{MMDD}.pptx"
```

转换引擎会自动将内嵌的多页 deck 拆分为独立页面，逐页转换为原生PPTX对象（文本框、形状、连接线、表格、图片等，非整页截图）。

#### 7.3 检查转换报告

转换完成后，读取 `{任务名称}{MMDD}.pptx.report.json`，检查：
- 每页是否有 `warned`（降级为截图）或 `dropped`（内容丢失）项
- **warned 含义**：该元素在 PPT 中以截图图片形式呈现，非原生可编辑对象。即该区域在 PPT 中是一张图片而非可编辑的文本框/形状。canvas/iframe/video/SVG透明渐变等浏览器侧无法原生映射的元素降级为截图属正常行为，但若降级区域包含文字，该文字在 PPT 中将不可编辑
- 如有降级项，评估是否影响演示效果（canvas/iframe/video 等本身无法原生映射，降级为截图是正常行为）
- 如有内容丢失，检查对应DOM路径，尝试修复HTML后重新转换

验收完成后，将转换报告归档到 `.temp/`（该文件为中间过程文件，不列入交付清单）：

```powershell
# Windows (PowerShell)
Move-Item -Path "{主题}_output/{任务名称}{MMDD}.pptx.report.json" -Destination ".temp/" -Force
```
```bash
# macOS / Linux (zsh/bash)
mv "{主题}_output/{任务名称}{MMDD}.pptx.report.json" ".temp/"
```

#### 7.4 重试

- 如果转换报告显示较多降级或丢失项，可修改HTML后重新执行转换（最多重试2次）
- 如果转换命令本身失败（如Edge进程未启动、端口冲突），检查Edge是否被其他进程占用，重试1次
- **转换彻底失败时必须报错**：明确告知用户"PPTX 转换失败，请重试"并附带失败原因（如依赖缺失、端口冲突、引擎异常等），不得静默跳过、不得将未转换的 HTML 作为交付物提供给用户

#### 7.5 HTML 归档

PPTX 转换成功且验收通过后（步骤7.2~7.4 全部完成），将 `{主题}_output/` 目录中的所有 HTML 文件归档到 `.temp/`。此时 HTML 的使命已完成（作为 PPTX 的生产原料），不再需要保留在输出目录中。

```powershell
# Windows (PowerShell)
Move-Item -Path "{主题}_output\*.html" -Destination ".temp/" -Force
```
```bash
# macOS / Linux (zsh/bash)
mv {主题}_output/*.html .temp/
```

> **归档时机**：必须在步骤7.4 重试逻辑全部结束后执行。若转换失败（步骤7.4 已报错终止），不执行归档——此时 HTML 保留在 `.temp/` 之前的原始位置，不影响诊断排查。

### 步骤8：最终交付与质量汇报

#### 8.0 交付前验证（强制）

执行 `report_final_files` 前，必须确认 `{主题}_output/` 目录中**仅包含 `.pptx` 文件**：

```powershell
# 列出输出目录中所有非 .pptx 文件，应为空
Get-ChildItem -Path "{主题}_output" | Where-Object { $_.Extension -ne ".pptx" }
```

- 如有 HTML 文件未归档 → 回退执行步骤7.5 归档后再继续
- 如有 JSON 报告等其他中间产物 → 一并移到 `.temp/`
- 验证通过（无输出）后才继续 8.1 交付

向用户提供：
1. **交付文件**（`{主题}_output/` 目录内仅保留以下最终交付物）：
   - `{任务名称}{MMDD}.pptx`（可编辑PPTX，唯一交付格式）
   - **调用 `report_final_files` 时只传 PPTX 文件路径**
2. **质量汇报**：每页的检查结果（通过次数、是否经过修复）+ PPTX转换报告摘要（如有降级/丢失项则列出）
3. 如有页面在 3 次检查后仍未通过，明确列出问题并建议手动调整
4. 如PPTX转换有降级项，说明降级原因（canvas/iframe/video 等不可原生映射的元素会降级为截图，属正常行为）

> **中间文件已归档**：所有 HTML 文件（slide_XX.html、index.html、单文件HTML）、截图PNG、几何体检JSON、体检报告HTML/JSON、转换报告JSON 均存放于 `.temp/`（隐藏归档区），不向用户展示、不列入交付清单。

## Rules

1. 所有页面必须使用 `references/style-guide.md` 中定义的CSS变量和配色系统，色值来源为 `references/color-themes.json` 中选定主题的字段
2. 每页画布精确 1280×768px
3. 所有文字直接硬编码，不使用数据绑定
4. 不使用任何JavaScript动画或CSS动画（静态呈现）
5. 不使用外部资源（CDN、字体链接、图标库）
6. 每页必须包含页码标记
7. 文字最小字号不低于18px
8. 保持风格一致性：使用步骤1选定的配色主题色调
9. 页面之间不要有重复的页眉/页脚（导航页面统一处理）
10. 向用户展示进度，每生成一页后简要报告
11. **配色合规**：所有色值必须取自 `references/color-themes.json` 中选定主题的字段，禁止自造色值。遵守该主题的 `qa_rules`（strict 主题禁止色系外色相，standard 主题检查整体一致性）
12. **主题内深浅区分**：区分不同场景/类别时，使用选定主题色系内的深浅明暗变化或灰度变化，不得跨色系取色
13. **Logo 区域保护**：右上角 top:24px right:48px 区域仅用于 Logo，禁止放置标签/badge/角标
14. **左右面板必须同高**：分栏布局时，左右面板的 top 和 bottom 值必须完全一致
15. **主内容区必须充实**：区块之间间距 ≤ 48px，不得出现超过 100px 的空白间隙
16. **卡片内容密度**：卡片空白面积不得超过 40%；内容少时用紧凑布局，不得做超大空卡片
17. **布局差异化（防单调）**：连续页面不得使用相同的布局模式。每页必须在以下至少2个维度与前一页有所区别：(a)布局框架（左右分栏/三栏/上下分区/全幅/横向卡片等）(b)主区域样式（深色渐变卡/白色卡/浅底色块等）(c)视觉重心（偏上/居中/偏下/偏侧等）。总览页之后的内容页禁止全部使用同一套"左KPI右详情"模板
18. **默认输出PPTX**：步骤6打包完成后，必须执行步骤7将HTML转换为PPTX。PPTX 是唯一交付格式，HTML 为中间产物（转换成功后归档到 `.temp/`）。转换失败必须报错，不得将 HTML 作为交付物提供给用户
19. **转换前必须完成打包**：步骤7（PPTX转换）依赖步骤6生成的单文件HTML（内嵌 `<script type="text/html" id="slide-N">` 块），不可在打包前执行转换
20. **几何体检强制前置**：步骤4 多模态检查前必须先执行步骤3.6 几何体检并修复所有 error 项；规则细节与参数以 `references/slide-audit-guide.md` 为准
21. **截图识别原生多模态优先**：步骤4 截图生成后，必须首选使用 Read 工具原生多模态能力直接读取截图 PNG 并完成结构化审查。仅当模型无视觉能力、或原生多模态读取失败/返回为空时，才降级调用 image_understanding 工具。降级时必须在进度报告中显式标注降级原因（格式见步骤4.2），不得静默降级
22. **跨平台适配**：本技能同时支持 Windows（PowerShell）与 macOS（zsh/bash）环境。所有 shell 命令均提供双平台版本，浏览器路径检测、字体枚举、文件名非法字符处理均自适应操作系统。Linux 环境同样适用（bash）
23. **严格单页闭环**：每页必须完成【生成HTML → 布局自检 → 几何体检 → 截图+多模态检查 → 修复 → 再检查】闭环（或达 3 次重试上限）后，才能开始生成下一页 HTML。未通过视觉检查前生成下一页 HTML 视为流程违规

## Layout Decision Guide

| 内容类型 | 推荐布局 | 逻辑关系 |
|----------|----------|----------|
| 要点列表(3-5项) | 横向卡片均分 / 纵向卡片 | 并列列表 |
| 流程/时间线 | 横向流程 / 纵向时间线 | 连续流程 |
| 对比(2项) | 左右对称分栏（必须同高） | 矩阵对比 |
| 关系图/生态图 | 中心辐射布局 | 中心辐射 |
| KPI数据展示 | 顶部标题+数字卡片横排 | 并列+对比 |
| 目录/议程 | 左侧窄栏+右侧宽栏（必须同高） | 层次 |
| 引言/金句 | 全幅居中 | — |
| 金字塔/层级 | 棱锥递进 | 棱锥递进 |

## Gotchas

- 风格指引中定义了CSS动画（fadeInUp等），但PPT用途下不应使用 —— 忽略动画相关CSS
- **步骤0是强制前置检查**：如果用户只输入了主题而未提供分页大纲，必须先引导用户补充大纲或帮用户生成大纲，确认后才能进入步骤1开始制作。不得在缺少大纲的情况下直接生成幻灯片
- 如果素材中的页号与输出页号不一致，在HTML中显示重新编排的页码（1/N, 2/N...）
- 打包脚本使用 `<script type="text/html">` + `iframe.srcdoc` 隔离各页 CSS，无需担心页面间样式冲突
- 打包脚本第二个参数传入步骤1确定的主题（见步骤6），确保单文件前缀与目录名一致；不传时自动从第一页 `<title>` 标签提取（可能导致前缀与目录名不一致）
- 输出目录为 `{主题}_output/`，由步骤1从PPT大纲标题中提取主题后动态确定，不再固定为 `output/`
- `{任务名称}{MMDD}.html` 的文件命名规则：任务名称去除 `\/:*?"<>|`（Windows）或 `/:`（macOS）等非法文件名字符后，拼接当天MMDD日期，例如 `星辰培训0627.html`
- 单文件中每个幻灯片的HTML存储在 `<script type="text/html" id="slide-N">` 块中，用户可在源码中直接搜索 `slide-N` 找到并编辑对应页面
- 编辑单文件中的slide HTML后，刷新浏览器即可看到修改效果，无需重新打包
- 风格指引字体栈以 PingFang SC 为首（跨平台优先），Windows 环境下浏览器会自动回退到 Microsoft YaHei，macOS 原生支持 PingFang SC，无需手动调整顺序
- **截图识别通道：原生多模态优先**：截图生成后，首选使用 Read 工具原生多模态能力直接读取截图 PNG 并完成结构化审查；仅当模型无视觉能力或原生读取失败/为空时才降级调用 image_understanding，降级必须在进度报告中显式标注原因
- **截图使用无头浏览器模式**：Windows 上为 `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`（Windows 10/11 默认已安装）；macOS 上为 `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome` 或 `/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge`（需用户安装）
- **最多重试 3 次**：3 次后保留最佳版本继续推进
- **QA检查从10项扩充到16项**：重点增加了页面结构（S1-S4）、布局对齐（S5-S6）、内容密度（S7-S8）的检测，这些是上一版本遗漏的根因
- **配色主题动态选择**：步骤1 根据 `color-themes.json` 的 `selection_guide` 关键词匹配自动选定主题，不向用户确认。所有色值由 JSON 唯一定义，SKILL.md/style-guide/design-prompt 中不再硬编码色值
- **默认输出PPTX**：步骤6打包后执行HTML→PPTX转换，PPTX 是唯一交付格式。转换成功后所有 HTML 文件归档到 `.temp/`；转换失败必须报错
- **PPTX转换依赖Edge/Chrome**：转换引擎通过CDP驱动无头浏览器采集布局数据，需系统安装Edge或Chrome。若浏览器被其他进程占用，端口会自动递增
- **转换报告必读**：`out.pptx.report.json` 是验收PPTX质量的第一入口，检查 warned（降级截图）和 dropped（内容丢失）项。canvas/iframe/video 等降级为截图属正常行为
- **PPTX转换必须成功**：转换失败时报错终止，不得将未转换的 HTML 作为交付物。HTML 仅作为生产 PPTX 的中间产物，转换成功后归档到 `.temp/`
- **几何体检是数值检测非美学判断**：slide-audit 用无头 Chrome 真实测量 getBoundingClientRect/Range/elementFromPoint，能发现多模态模型看不出的问题（如 overflow:hidden 静默裁剪、elementFromPoint 命中测试遮挡），但不能判断布局是否好看、内容是否完整
- **slide-audit 支持单文件模板格式**：pack_slides.py 生成的 `<script type="text/html" id="slide-N">` 格式会被 slide-audit 自动拆分逐页检查，行号映射回源文件
- **几何体检引擎跨平台**：slide-audit.mjs 的 `findChrome()` 已适配 Windows / macOS / Linux 浏览器路径，`--open` 自动选择平台对应打开命令（Windows: `start`，macOS: `open`，Linux: `xdg-open`）
- **slide-audit `--out` 会生成 audit-shots/ 目录**：slide-audit 写 HTML 可视化报告时，会在报告同目录下额外创建 `audit-shots/` 子目录存放每页标注截图 PNG。步骤6.5 传 `--out ".temp/audit-report.html"` 时该目录在 `.temp/` 内，属正常行为
- **步骤3.6 用 --no-out 跳过报告生成**：步骤3.6 逐页体检传 `--no-out`，只取 JSON 结果做 error 判断，不生成可视化报告和截图（逐页报告会被覆盖，生成无意义且浪费时间）。全量可视化报告在步骤6.5（打包后全量体检）用 `--out` 生成

## Pitfalls & Lessons Learned

> 以下均来自实际生成任务中踩过的坑，按严重程度排列。

### P0 - 元素定位错乱（会导致整页不可用）

**P0-1. 绝对定位元素必须显式设置 left/top**
- `position:absolute` 的元素如果只写 `position:absolute` 而不设置 `left/top/right/bottom`，浏览器会将其放在静态流位置，**在不同浏览器/渲染模式下位置不一致**
- 中心辐射布局的中心圆如果漏设坐标，Edge 会将其渲染在左上角而非居中
- **规则：每个 `position:absolute` 元素都必须有显式的 `left` 和 `top`（或 `right/bottom`），禁止依赖浏览器默认定位**

**P0-2. 中心辐射布局必须用三角函数预计算坐标**
- 禁止用 `top/right/bottom/left` 混合定位或肉眼估算坐标——7个节点的角度间隔是 51.43°，估算值一定会有累积偏差
- 正确做法：用三角函数预计算坐标，硬编码到 CSS 中
  ```powershell
  # Windows (PowerShell)
  $cx=592; $cy=394; $R=240; $N=7; $start=-90
  for($i=0;$i-lt$N;$i++){
    $a=($start+$i*(360/$N))*[Math]::PI/180
    "N{0}: left={1:F0}px top={2:F0}px" -f ($i+1),($cx+$R*[Math]::Cos($a)),($cy+$R*[Math]::Sin($a))
  }
  ```
  ```bash
  # macOS / Linux (zsh/bash)
  cx=592; cy=394; R=240; N=7; start=-90
  for i in $(seq 0 $((N-1))); do
    a=$(python3 -c "import math;a=($start+$i*(360/$N))*math.pi/180;print(f'{$cx+$R*math.cos(a)} {$cy+$R*math.sin(a)}')")
    echo "N$((i+1)): left=$(echo $a | cut -d' ' -f1 | cut -d'.' -f1)px top=$(echo $a | cut -d' ' -f2 | cut -d'.' -f1)px"
  done
  ```
- 主内容区几何参数：`left=48px, width=1184px, top=80px, height=628px` → 中心点 `(592, 394)`
- 节点使用 `transform:translate(-50%,-50%)` 使坐标点对准节点中心
- 半径 R 的选择需确保所有节点（含标签文字）不超出主内容区边界；建议 R=240~260，计算后检查四向 clearance ≥ 10px

**P0-3. SVG 连线坐标必须与 CSS 定位坐标完全一致**
- SVG `<line>` 的 `x1,y1`（中心）和 `x2,y2`（节点）必须与对应 DOM 元素的 `left/top` 坐标精确匹配
- 如果改了节点坐标但忘了同步 SVG 线条坐标，线条会悬空/错位
- **规则：修改节点位置时，必须同步更新 SVG 中对应的所有线条端点**

### P1 - 布局缺陷（QA 不会 PASS）

**P1-1. 左右分栏面板必须标题对齐**
- 如果左侧面板有 section-label 标题（如"智能体五大能力"），右侧面板也必须有同级标题（如"效果与案例"），否则视觉上顶部不对齐
- 两个 section-label 的字体、字号、margin 必须完全一致

**P1-2. 场景/分类标签不得放在 Logo 区域**
- 场景标签（如"核心场景"/"扩展场景"）必须紧跟页面标题后面（`margin-left:16px`），不能用 `margin-left:auto` 推到右侧
- 右上角 `top:24px; right:48px` 区域严禁放置任何非 Logo 内容

**P1-3. 卡片内容不足时需填充而非留白**
- 如果右侧面板只有 1 个效果数据卡片 + 1 个案例卡片，内容不够填满面板高度，应增加"适用材料"标签区等中间内容
- 空白面积 >40% 的卡片会被 QA 判 FAIL

**P1-4. 连续页面禁止使用同一布局模板（布局单调问题）**
- 实际踩坑：生成6页PPT时，slide_02~06全部使用"左KPI+右详情"的左右分栏布局，用户反馈"每张图的格式怎么都一样"，被迫全部重做
- 根因：步骤3生成HTML时只关注单页内容，没有跨页对比布局模式
- 解决：新增步骤3.5布局差异化自检 + S16 QA检查项，确保连续页面布局有变化
- 常见调整手段：(a)换布局框架（左右分栏→三栏→上下分区→横排卡片）(b)换卡片主样式（白卡→渐变蓝卡→浅底色块）(c)换视觉重心位置

### P2 - 截图与 QA 流程问题

**P2-1. 无头浏览器截图命令**
- **Windows**：必须用完整路径：`& "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"`
- **macOS / Linux**：自动探测 Chrome/Edge/Chromium 路径，使用 `"$CHROME" --headless ...` 方式调用
- **必须带 `--user-data-dir` 指向每次新建的临时目录**（Windows: `Join-Path $env:TEMP "slide-screenshot-$(Get-Random)"`；macOS/Linux: `mktemp -d`）。**用完无需手动删除**——临时目录位于系统 TEMP 下由 OS 自动清理，且 `Remove-Item -Recurse -Force` / `rm -rf` 会触发安全护栏确认弹窗，禁止在技能命令中使用。若浏览器已有进程在运行，截图可能写入失败（文件不存在但不报错）——**此时换一个新的临时目录重试即可，禁止使用 `Stop-Process -Name msedge -Force` / `pkill -f "Google Chrome"` 按进程名杀浏览器**，这会关闭用户正在使用的所有浏览器窗口和标签页
- 命令参数：`--headless --disable-gpu --user-data-dir=<临时目录> --hide-scrollbars --screenshot=<绝对路径>.png --window-size=1280,768 --force-device-scale-factor=1 <file URI>`；截图输出路径写入 `.temp/`（绝对路径）；HTML 输入必须用自动百分号编码的 file URI 绝对路径（PowerShell 用 `[System.Uri]`，bash 用 `python3 pathlib.as_uri()`），**禁止直接传含中文的相对路径**——无头浏览器会把相对路径当 URL 解析，中文被当作域名导致 DNS 错误页（实际踩坑）；同样禁止手拼未编码的 `file:///` + 中文路径
- `--hide-scrollbars` 隐藏滚动条，防止内容轻微溢出时截图出现滚动条伪影
- 截图完成后用 `Test-Path`（Windows）/ `[ -f ]`（macOS/Linux）检测 PNG 是否生成，未生成则换新临时目录重试一次
- macOS 上的 Google Chrome 无头模式必须用 `--user-data-dir` 指向 `mktemp -d` 创建的临时目录，避免与已运行的 Chrome 冲突

**P2-2. 截图识别通道注意事项**
- **原生多模态读取（首选）**：使用 Read 工具直接读取截图 PNG 文件，Read 原生支持图片。Windows 长路径（含中文、空格）或 macOS 特殊字符路径有时会导致读取失败，可先复制到短路径再读取
- **image_understanding 工具（降级）**：仅在原生多模态读取失败时使用。`file_path` 参数在 Windows 长路径下可能找不到文件，解决方案：复制到短路径后再读取
- `image_url` 参数也支持 `file:///` 协议，但不稳定；推荐用 `file_path`

**P2-3. QA 多模态模型已知偏差**
- **中心辐射布局（S5/S6）**：模型对均匀度的判断比实际更严格，即使数学上均匀（360°/N），模型仍可能因上下不对称（奇数节点）判 FAIL。3 次重试后应接受
- **底部空白（S4）**：即使 CSS 数学上填满空间（`height:628px` + `flex:1`），模型仍可能判 FAIL。使用 `justify-content:space-evenly` 可提高通过率
- **字号判定（S14）**：浅色文字（如 `#718096`）会被模型误判为"字号过小"，将颜色加深到 `#4a5568` 即可通过

### P3 - CSS 实现陷阱

**P3-1. body overflow:hidden 会裁剪超出的 flex 子项**
- `body{overflow:hidden}` + 绝对面板 `height:628px` + `flex:1` 的子列表：如果子项自然高度之和 + gap 超过了 flex 容器分配的高度，超出的内容会被静默裁剪（不出现滚动条）
- 症状：列表最后一项的文字被截断，但 DOM 结构正确
- 解决：不要给列表项设 `flex:1`（等分拉伸会压缩内容），改用 `justify-content:space-evenly` 让自然高度的子项均匀分布

**P3-2. section-label 的 margin-bottom 会挤压可用空间**
- 左右面板的 section-label 如果 margin-bottom 不一致（如 10px vs 0px），面板内的内容起始高度不同，视觉上顶部不对齐
- **规则：左右面板的 section-label 样式必须完全一致**，包括 margin、font-size、::before 装饰

**P3-3. 不要用 CSS shorthand 覆盖 position:absolute 元素的样式**
- 如 `.slide{padding:48px 72px!important}` 会重置 position:absolute 等所有属性
- 只能单独覆盖具体属性：`.slide{padding-left:48px!important; padding-right:48px!important}`

## References

- 设计Prompt模板：`references/design-prompt-template.md`
- 风格指引：`references/style-guide.md`
- 配色主题：`references/color-themes.json`
- 打包脚本：`scripts/pack_slides.py`
- 转换引擎指南：`references/html2pptx-guide.md`
- PPTX转换引擎：`scripts/html2pptx.py`
- 浏览器端采集脚本：`scripts/extract.js`
- 转换配置：`scripts/h2p_config.py`
- 标定与回归工具链：`scripts/TestCase/`
- 排版体检指南：`references/slide-audit-guide.md`
- 排版体检引擎（运行器）：`scripts/slide-audit.mjs`
- 排版体检引擎（规则引擎）：`scripts/engine.js`
- 各平台统一通过 `node scripts/slide-audit.mjs` 调用，无需启动器

> AI生成