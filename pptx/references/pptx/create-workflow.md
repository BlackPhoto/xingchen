# .pptx 创建工作流

> 本文档是 `.pptx` 创建路线的执行指南。开始创建前必须完整阅读本文件，并按需读取引用的 reference。

## 内容预处理（必做）

**关键要求**：在开始创建或修改任何PPT之前，必须先完成内容规划。直接动手生成PPT而不做规划，是导致内容混乱、信息丢失、排版灾难的根因。

**必做 - 完整阅读**：任何 PPT 创建或编辑任务开始前，都要完整阅读 [`references/shared/content-planner.md`](references/shared/content-planner.md)。该指南包含：
- 需求分析与内容结构化（从自然语言中提取结构化数据）
- 内容提炼与信息分层（提炼要点而非搬运原文）
- 页面规划与大纲设计
- 内容-模板映射（评估内容密度、类型与模板匹配度）
- 文字截断预防
- 质量自查清单

### 速查：内容预处理清单

在动手写任何代码之前，必须完成以下步骤：

1. **结构化提取**：将用户需求整理为结构化表格/列表，确保所有条目完整、无遗漏
2. **内容精简**：每页文字控制在80字以内，每条要点不超过25字
3. **受众适配**：根据受众类型（技术专家/小白/管理层）调整内容深度
4. **页面大纲**：先写出完整的页面大纲，包含每页标题和要点
5. **模板映射**：评估每页内容密度，选择匹配的模板布局
6. **截断预防**：计算目标shape可容纳的字符数，超长内容先精简再填充

### 强制规则
1. 关于解决方案的说明，**只允许输出 1 次**，输出后永久禁止重复打印。
2. 一旦确认解决方案，立即进入代码编写环节，不再重复描述原因。
3. 禁止循环输出相同的解决方案描述。

### 从外部内容源创建PPT时的特殊要求

当用户要求"基于PDF/文档内容创建PPT"时，**绝对禁止逐字搬运原文**：

- **提炼而非复制**：每页提取1-2个核心论点，精简为≤25字的要点
- **信息分层**：原文 → 核心论点 → 幻灯片文字 → 可视化图表
- **术语处理**：对小白受众，每个专业术语必须附带简短解释或类比
- **视觉优先**：能用图表/图示表达的，不用文字；能用关键词的，不用完整句子

## 创建一个**不使用模板**的新 PowerPoint 演示文稿

### 工作流：从零创建（PptxGenJS）

**适用场景：没有可用模板或参考演示文稿。**
**关键要求**：生成前和生成过程中，都必须阅读 `references/` 目录中的相关参考文件，以确保 API 用法和样式规则正确。

#### 步骤 1：调研与需求
通过搜索和分析明确用户需求，包括主题、受众、目的、语气和内容深度。

#### 步骤 2：选择配色与字体
使用 [Design System](references/shared/design-system.md) 选择匹配主题的色板。中文文本优先遵循上方字体规范，例如 Microsoft YaHei。

#### 步骤 3：选择设计风格
使用 [Design System](references/shared/design-system.md) 中的风格配方，选择与演示语气匹配的视觉风格（Sharp、Soft、Rounded 或 Pill）。

#### 步骤 3.1：图标表现方式

PptxGenJS 路线不选择 SVG 图标库。根据视觉风格规划统一的原生图形语言：

| 视觉风格 | 原生图形建议 | 备注 |
|---|---|---|
| 商务简约 / 正式庄重 / 高端品牌 | 细线、圆形、方形、单色强调 | 保持克制、投影清晰 |
| 温润亲和 / 中国风 | 圆角形状、柔和色块、印章式标签 | 不使用外部 SVG 图标 |
| 科技专业 / 炫彩科技 | 几何线框、节点、连接线、双色原生形状 | 用层叠形状实现，不栅格化 |

真实品牌 Logo 仅在用户提供或取得可靠的 PNG/JPEG 素材时使用，并通过 `slide.addImage({ path })` 嵌入；不得通过 SVG data URI、`simple-icons` 或伪 PNG 方式生成。

#### 步骤 4：规划幻灯片大纲
将每一页准确归类为 [Slide Types](references/pptx/slide-types.md) 中说明的 5 种页面类型之一。规划内容和版式，并确保视觉上有变化。

> **⏱ 检查点 1**：按 `references/shared/timebox.md` 核对累计用时。内容规划阶段（澄清+大纲）预算 10 分钟，超出立即停止，按 timebox 模板汇报已完成/未完成/PPT 问题/优先修改建议。

#### 步骤 4.1：原生图形清单（大纲确认后执行）

大纲稳定后，按页面枚举需要表达的图标概念，并把每项映射为原生 PowerPoint 对象。禁止搜索或登记 SVG 文件名。

示例映射：

| 语义 | 原生实现 |
|---|---|
| 成功 / 优点 | 绿色圆形 + 白色 `✓` |
| 失败 / 缺点 | 红色圆形 + 白色 `×` |
| 信息 / 提示 | 蓝色圆形 + 白色 `i` |
| 警告 | 橙色三角形 + 白色 `!` |
| 趋势 / 流程 | 原生箭头、连接线或折线 |
| 分类 / 编号 | 圆角矩形、圆点或数字标签 |

将清单追加到 `spec_lock_lite.md`：

```markdown
## native_icons
- style: [line / solid / rounded / geometric]
- inventory: success, failure, info, warning, arrow-right, numbered-label
- rule: native PowerPoint shapes only; no SVG data URI
```

#### 步骤 4.2：路由修正 + spec_lock_lite 生成

> 本步骤只在 **A（改着顺手）或 C（全程可编辑）** 进入本文件时执行。B 和 D 从一开始就走 `references/pptx-svg/create-workflow.md`，不会到达此处。

**路由说明**（本文件只在 A 或 C 进入，无路由切换）：

- A / C 始终保持 PptxGenJS，不切换引擎
- 遇到 SVG-only 图表（桑基/瀑布/漏斗/旭日/弦/复杂雷达等）时，保持 PptxGenJS，告知用户「该图表将以可编辑方式近似实现，数值和文字均可编辑」，继续后续步骤

**spec_lock_lite 生成**：

在 `{工作目录}/.temp/` 下生成 `spec_lock_lite.md`，内容如下（根据实际配置填写）：

```markdown
# Spec Lock Lite

> PptxGenJS 路线轻量防漂移锁。每 3 页重读一次。

## canvas
- format: PPT 16:9

## colors
- bg: #FFFFFF
- primary: #......
- accent: #......
- secondary_accent: #......
- text: #......
- text_secondary: #......
- border: #......

## typography
- font_family: "Microsoft YaHei", Arial, sans-serif
- title_family: [根据视觉风格填写]
- body_family: "Microsoft YaHei", "PingFang SC", Arial, sans-serif
- title: 32
- body: 22
- subtitle: 24

## native_icons
- style: [根据视觉风格填写]
- inventory: [Step 4.1 完成后填入，逗号分隔]
- rule: native PowerPoint shapes only; no SVG data URI
```

> `## native_icons` 节在步骤 4.1 完成后回填；路由修正判定完成后再生成本文件也可——先留空，步骤 4.1 跑完后补上。

#### 步骤 5：可选 AI 图片计划
如果用户选择“视觉素材来源 → 需要 AI 生成”，在编写 slide 代码前阅读 [`references/shared/image-gen.md`](references/shared/image-gen.md) 和 [`references/shared/image-prompts.md`](references/shared/image-prompts.md)。

大纲稳定后、编写 slide JS 前，创建 AI 图片计划：

| 页面 | 用途 | 图片类型 | 宽高比 | 尺寸 | 输出路径 | 槽位 |
|-------|---------|------------|--------------|------|-------------|------|

规则：
- 在执行摘要和图片计划中写明预计生成图片数量。
- 如果图片生成服务报告额度或可用性限制，让用户减少图片数量、改用 PPT 原生组件，或切换路线。
- `.pptx` 过程图片保存到 `{工作目录}/.temp/images/`。
- 不要要求 AI 图片生成关键文字、精确数字、Logo、水印、页面框架或法律/品牌文案。准确内容使用 PPT 原生文本和图表承载。
- 保持一个整套演示级别的风格前缀，使所有生成图片匹配选定设计系统。
- 如果使用图生图模式，优先使用无文字的风格参考图；不要默认使用内容密集的成品页作为风格参考。
- 单张图片失败时重试一次；仍失败则用原生形状或色块替代该图片位置，然后继续。PptxGenJS 路线不得以 SVG data URI 图标作为兜底。

**图像校验（排版 `.pptx` 配图）：** 所有 AI 配图生成完毕后，按照 `references/shared/image-gen.md` 的"图像校验"章节对每张图片进行校验。校验可并行执行。

校验 FAIL 的重试仍 FAIL 时，该配图位置改用原生形状或色块占位，继续完成整份文档（排版 PPT 的核心信息由原生文字承载，配图只是装饰素材，降级不影响信息传达），并在执行摘要中标注降级页码。

#### 步骤 6：生成 slide JS 文件
在 `slides/` 目录下为每页创建一个 JS 文件。每个文件必须导出同步的 `createSlide(pres, theme)` 函数。
- **关键 API 参考**：必须阅读 [PptxGenJS Reference](references/pptx/pptxgenjs-api.md)，确认添加文本、形状和图表的准确 API 语法。
- 告诉 subagent 严格遵循参考文件中规定的 Theme Object Contract 和 Slide Output Format。
- 使用 `slide.addImage({ path })` 引用生成图片，并保留源 PNG，直到最终 PPTX QA 完成。

**PptxGenJS 路线图标兼容性规范（强制）**：

PptxGenJS 路线禁止通过 SVG data URI 嵌入图标。以下写法均禁止：

- `data:image/svg+xml;base64,...`
- `data:image/svg+xml;utf8,...`
- 将 SVG/XML 字符串传给 `slide.addImage({ data })`
- 将 SVG 内容保存或伪装成 `.png` 后再嵌入

原因：部分 PptxGenJS、PowerPoint、WPS 和预览器组合会为 SVG 生成无效的 PNG fallback；当客户端读取该 fallback 时，图标会显示为红叉。该限制只适用于 PptxGenJS 路线，不改变独立的 SVG 整页生成路线。

图标按以下优先级实现：

1. 优先使用 PptxGenJS / PowerPoint 原生形状，确保对象可编辑且跨客户端兼容。
2. 对勾、叉号、提示、警告等语义图标使用“基础形状 + 文本或线条”组合绘制。
3. 箭头、星形、三角形、圆形、信息标签直接使用原生 shape。
4. 装饰性图标可降级为圆点、色块、编号或简短字符。
5. 无法可靠用原生对象表达时，宁可省略装饰图标，不得恢复使用 SVG data URI。

常见语义图标建议：

- 优点/成功：绿色圆形 + 白色 `✓`
- 缺点/失败：红色圆形 + 白色 `×`
- 提示/信息：蓝色圆形 + 白色 `i`
- 警告：橙色三角形 + 白色 `!`
- 流程方向：原生箭头或连接线

图标应作为可编辑的原生对象写入 PPT，不创建 `icon-helper.js`，也不依赖 `svgIcon()`、`react-icons` 或 SVG 栅格化 helper。

**漂移防护纪律**：

> **批次自检**（每 3 页执行一次）：每生成完第 3、6、9…页 JS 文件后，重读 `.temp/spec_lock_lite.md`，对**本批**代码中出现的色值和字体名做即时核对；发现偏离立即在本批内修正，再继续生成后续页面。
>
> 自检范围：① 代码中出现的色值是否与 spec_lock_lite 声明的一致（允许视觉不可辨的近似）；② 字体名是否在 spec_lock_lite 白名单中；③ 不得出现 `data:image/svg+xml`、`svgIcon()` 或内容与扩展名不一致的图片。路径错误属于显性 bug，在 node 执行阶段处理。

#### 步骤 7：编译为最终 PPTX
创建 `slides/compile.js`，用于组合所有 slide 模块。

> **⏱ 检查点 2**：按 `references/shared/timebox.md` 核对累计用时。生成/执行阶段预算 20 分钟，超出立即停止，按 timebox 模板汇报已完成/未完成/PPT 问题/优先修改建议。

#### 步骤 7.5：全局漂移复核（SVG 集成新增）

全部页面 JS 文件生成完毕后，重读 `.temp/spec_lock_lite.md`，对整份代码做最终漂移扫描：

- 逐页检查所有色值是否与 spec_lock_lite 声明一致
- 逐页检查所有字体名是否在白名单中
- 发现偏离的页面：立即修正该页代码，再继续后续步骤

#### 步骤 8：QA（必做）
必须阅读 [Pitfalls & QA](references/pptx/pitfalls.md)，并执行其中的 QA 流程，在最终确定 PPTX 前捕捉常见渲染错误。

**媒体格式一致性检查（强制）**：

- PPTX 包内扩展名为 `.png` 的媒体必须是真实 PNG，文件头应为 PNG 签名；不得以 `<svg`、`<?xml` 或其他文本内容开头。
- 若发现伪 PNG 或 SVG data URI 生成的双媒体 fallback，视为 QA 失败；必须将对应图标改成原生形状后重新编译。
- 预览或渲染中出现红叉、空白图片框时，不得仅依赖当前渲染器结果继续交付，必须检查媒体文件内容与关系引用。

> **⏱ 检查点 3**：按 `references/shared/timebox.md` 核对累计用时。QA + 交付阶段预算 10 分钟（全程硬上限 40 分钟），超出立即停止，改用 timebox 的「超时快速 QA 清单」（4 项快检），并按模板汇报已完成/未完成/PPT 问题/优先修改建议。

### 设计原则

**关键**：创建任何演示文稿前，先分析内容并选择合适的设计元素：
1. **考虑主题内容**：这份演示文稿讲什么？它暗示了什么语气、行业或情绪？
2. **检查品牌线索**：如果用户提到公司/组织，考虑其品牌色和视觉身份
3. **让配色匹配内容**：选择能体现主题的颜色
4. **说明设计方法**：写代码前先解释你的设计选择

**要求**：
- ✅ 写代码前说明基于内容得出的设计方法
- ✅ 根据内容语言选择合适字体：
  - **中文内容（推荐）**：微软雅黑、思源黑体、思源宋体、阿里巴巴普惠体、华文细黑
  - **英文内容/通用**：Arial, Helvetica, Times New Roman, Georgia, Courier New, Verdana, Tahoma, Trebuchet MS, Impact
  - **Web-safe fonts（兼容性）**：上述所有字体均为常用字体，跨平台兼容性好
- ✅ 通过字号、字重和颜色建立清晰视觉层级
- ✅ 保证可读性：强对比、合适字号、干净对齐
- ✅ 保持一致：跨页复用模式、间距和视觉语言
- ✅ 中文内容默认优先使用“微软雅黑”（Microsoft YaHei）

#### 配色选择

**创造性地选择颜色**：
- **跳出默认色**：哪些颜色真正匹配这个具体主题？避免自动驾驶式选择。
- **从多个角度考虑**：主题、行业、情绪、能量水平、目标受众、品牌身份（如果提到）
- **大胆一点**：尝试意料之外的组合；医疗演示不一定要绿色，金融演示也不一定要海军蓝
- **构建色板**：选择 3-5 个能协同工作的颜色（主色 + 辅助色调 + 强调色）
- **保证对比度**：文本在背景上必须清晰可读

**示例配色方案**（用于激发灵感，可直接选择、调整，或自行创建）：

### 中国风配色方案（适用于中文内容）

C1. **科技蓝**：科技蓝 (#0052D9), 深蓝 (#0033A0), 浅蓝 (#E6F0FF), 白色 (#FFFFFF)
C2. **党政红金**：中国红 (#DE2910), 金色 (#FFD700), 深红 (#8B0000), 米白 (#FFF8DC)
C3. **淡雅水墨**：墨黑 (#2C2C2C), 灰色 (#808080), 浅灰 (#D3D3D3), 宣纸白 (#F5F5DC)
C4. **新中式**：朱砂红 (#E86161), 青瓷色 (#7FB068), 米黄 (#F2E6CE), 深灰 (#4A4A4A)
C5. **商务深灰**：深灰 (#333333), 中灰 (#666666), 浅灰 (#CCCCCC), 白色 (#FFFFFF)
C6. **竹韵青**：竹青 (#789262), 浅绿 (#B5C99A), 米白 (#F7F7F0), 深绿 (#2F4F4F)
C7. **紫气东来**：紫罗兰 (#9370DB), 浅紫 (#DDA0DD), 金黄 (#FFD700), 白色 (#FFFFFF)
C8. **江南烟雨**：青灰 (#6B7A8F), 浅蓝灰 (#A8B8C8), 灰白 (#D9E4EC), 深蓝 (#2C3E50)

### 国际通用配色方案

1. **经典蓝**：深海军蓝 (#1C2833), 石板灰 (#2E4053), 银灰 (#AAB7B8), 暖白 (#F4F6F6)
2. **青绿与珊瑚**：青绿 (#5EA8A7), 深青绿 (#277884), 珊瑚红 (#FE4447), 白色 (#FFFFFF)
3. **强烈红色**：红色 (#C0392B), 亮红 (#E74C3C), 橙色 (#F39C12), 黄色 (#F1C40F), 绿色 (#2ECC71)
4. **暖粉色调**：灰紫 (#A49393), 浅粉 (#EED6D3), 玫瑰粉 (#E8B4B8), 奶油白 (#FAF7F2)
5. **酒红奢华**：酒红 (#5D1D2E), 深红 (#951233), 铁锈红 (#C15937), 金色 (#997929)
6. **深紫与祖母绿**：紫色 (#B165FB), 深蓝 (#181B24), 祖母绿 (#40695B), 白色 (#FFFFFF)
7. **奶油与森林绿**：奶油色 (#FFE1C7), 森林绿 (#40695B), 白色 (#FCFCFC)
8. **粉色与紫色**：粉色 (#F8275B), 珊瑚色 (#FF574A), 玫瑰色 (#FF737D), 紫色 (#3D2F68)
9. **青柠与李子紫**：青柠 (#C5DE82), 李子紫 (#7C3A5F), 珊瑚色 (#FD8C6E), 蓝灰 (#98ACB5)
10. **黑金**：金色 (#BF9A4A), 黑色 (#000000), 奶油白 (#F4F6F6)
11. **鼠尾草绿与陶土色**：鼠尾草绿 (#87A96B), 陶土色 (#E07A5F), 奶油白 (#F4F1DE), 炭黑 (#2C2C2C)
12. **炭灰与红色**：炭灰 (#292929), 红色 (#E33737), 浅灰 (#CCCBCB)
13. **活力橙**：橙色 (#F96D00), 浅灰 (#F2F2F2), 炭灰 (#222831)
14. **森林绿**：黑色 (#191A19), 绿色 (#4E9F3D), 深绿 (#1E5128), 白色 (#FFFFFF)
15. **复古彩虹**：紫色 (#722880), 粉色 (#D72D51), 橙色 (#EB5C18), 琥珀色 (#F08800), 金色 (#DEB600)
16. **复古大地色**：芥末黄 (#E3B448), 鼠尾草绿 (#CBD18F), 森林绿 (#3A6B35), 奶油白 (#F4F1DE)
17. **海岸玫瑰**：旧玫瑰色 (#AD7670), 海狸棕 (#B49886), 蛋壳色 (#F3ECDC), 灰绿色 (#BFD5BE)
18. **橙色与土耳其蓝**：浅橙 (#FC993E), 灰调土耳其蓝 (#667C6F), 白色 (#FCFCFC)

#### 视觉细节选项

**几何模式**：
- 使用斜向章节分隔，而不是水平分隔
- 使用非对称栏宽（30/70、40/60、25/75）
- 将文本标题旋转 90° 或 270°
- 为图片使用圆形/六边形框
- 在角落放置三角形强调形状
- 用重叠形状制造层次

**边框与框架处理**：
- 只在单侧使用粗实色边框（10-20pt）
- 使用对比色双线边框
- 用角标替代完整外框
- 使用 L 形边框（上+左或下+右）
- 在标题下方使用下划强调（3-5pt 粗）

**字体处理**：
- 使用极端字号对比（72pt 标题 vs 11pt 正文）
- 全大写标题并加大字距
- 用超大展示字体呈现编号章节
- 数据/统计/技术内容使用等宽字体（Courier New）
- 密集信息使用窄体字体（Arial Narrow）
- 用描边文字做强调

**图表与数据样式**：
- 单色图表，仅用一个强调色突出关键数据
- 用横向条形图替代竖向柱状图
- 用点图替代柱状图
- 使用极少网格线，或完全不使用网格线
- 数据标签直接放在元素上，不依赖图例
- 关键指标使用超大数字

**版式创新**：
- 全幅图片叠加文本
- 使用侧栏（20-30% 宽）承载导航/上下文
- 模块化网格系统（3×3、4×4 区块）
- Z 型或 F 型内容流
- 彩色形状上漂浮文本框
- 杂志风多栏布局

**背景处理**：
- 实色块占据页面 40-60%
- 渐变填充（仅垂直或对角）
- 分割背景（双色，对角或垂直）
- 边到边色带
- 将负空间作为设计元素

### 版式提示
**创建含图表或表格的页面时：**
- **双栏版式（推荐）**：使用跨全宽的页眉，下方分成两栏；一栏放文本/要点，另一栏放重点内容。这样更平衡，也能让图表/表格更易读。使用不等宽 flexbox（如 40%/60%）为不同内容类型优化空间。
- **整页版式**：让重点内容（图表/表格）占满整页，以获得最大视觉冲击和可读性。
- **绝不纵向堆叠**：不要在单栏中把图表/表格放到文本下方，这会造成可读性差和版式问题。

### 中文排版规则（Chinese Typography Guidelines）

#### 字号对照表（Font Size Reference）

中文常用字号与磅值(pt)对照：

| 中文称呼 | 磅值(pt) | 英文近似 | 用途 |
|---------|---------|---------|------|
| 初号 | 42pt | - | 标题/封面 |
| 小初 | 36pt | - | 大标题 |
| 一号 | 26pt | 32pt | 主标题 |
| 小一 | 24pt | 28pt | 副标题 |
| 二号 | 22pt | 24pt | 二级标题 |
| 小二 | 18pt | 20pt | 三级标题 |
| 三号 | 16pt | 18pt | 正文大标题 |
| 小三 | 15pt | 16pt | 正文小标题 |
| 四号 | 14pt | 14pt | 正文标题 |
| 小四 | 12pt | 12pt | **正文默认** |
| 五号 | 10.5pt | 10pt | 小字正文 |
| 小五 | 9pt | 9pt | 注释/说明 |

**推荐使用**：
- 标题：18-24pt（小二至二号）
- 正文：12-14pt（小四至四号）
- 注释：9-10pt（小五至五号）

#### 行首行尾禁则（Line Start/End Prohibition Rules）

以下标点符号不应出现在行首或行尾：

**不应出现在行尾**（需要与后续字符保持在一起）：
- 开括号：`(` `（` `[` `【` `{` `「` `『`
- 前置标点：`"` `"` `'` `'`

**不应出现在行首**（需要与前置字符保持在一起）：
- 闭括号：`)` `）` `]` `】` `}` `」` `』`
- 后置标点：`,` `,` `.` `.` `;` `；` `:` `：` `!` `！` `?` `？`
- 省略号：`......` `……`
- 破折号：`——`

#### 中英文间距（Chinese-English Spacing）

在中文字符与英文字符/数字之间添加适当间距（约0.25em）：

**示例**：
- ❌ 错误：使用PowerPoint创建演示文稿
- ✅ 正确：使用 PowerPoint 创建演示文稿
- ❌ 错误：2024年度报告
- ✅ 正确：2024 年度报告

**实现方式**（在HTML/CSS中）：
```css
.chinese-text {
    letter-spacing: 0.05em;
}
.chinese-text + .english-text,
.chinese-text + .number {
    margin-left: 0.25em;
}
```

#### 推荐的中文字体设置

**默认字体栈**（按优先级排序）：
```css
font-family: "Microsoft YaHei", "微软雅黑", "Source Han Sans CN",
             "思源黑体", "Alibaba PuHuiTi", "阿里巴巴普惠体",
             "STHeiti", "华文细黑", "SimHei", "黑体",
             sans-serif;
}
```

**标题使用**（更有力量感）：
- "Microsoft YaHei Bold" / "微软雅黑 Bold"
- "Source Han Sans CN Bold" / "思源黑体 Bold"

**正文使用**（易读性优先）：
- "Microsoft YaHei" / "微软雅黑"
- "Alibaba PuHuiTi" / "阿里巴巴普惠体"

#### 标点符号使用规范

**中文标点符号优先**：
- 在纯中文文本中使用中文标点：`，。；：？！""''（）【】`
- 在中英混排文本中，根据前后内容选择合适的标点

**数字与单位**：
- 数字与中文单位之间不加空格：100元、50公斤、25%
- 英文单位前加空格：100 kg, 25 %, 30 px

### PPT旧格式支持（Legacy PPT Format Support）

#### 转换旧版PPT为PPTX

当用户提供`.ppt`格式文件（旧版PowerPoint格式）时，需要先转换为`.pptx`格式：

```bash
# 使用LibreOffice进行格式转换
soffice --headless --convert-to pptx input.ppt
```

**注意事项**：
- 转换后的文件可能需要检查格式兼容性
- 某些旧版特效可能无法完美转换
- 建议转换后进行视觉验证

**自动检测与转换脚本**：
```bash
# 检测文件格式并自动转换
python scripts/convert_legacy_ppt.py input.ppt output.pptx
```

## 创建一个**使用模板**的新 PowerPoint 演示文稿

当需要创建遵循现有模板设计的演示文稿时，先复制并重排模板页，再替换占位内容。

### 工作流
1. **提取模板文本，并创建可视缩略图网格**：
   * 提取文本：`python -m markitdown template.pptx > template-content.md`
   * 阅读 `template-content.md`：完整阅读该文件，理解模板演示文稿的内容。**读取时不要设置任何范围限制。**
   * 创建缩略图网格：`python scripts/thumbnail_workflow.py template.pptx`
   * 更多细节见 [创建缩略图网格](#创建缩略图网格)

2. **分析模板，并把 inventory 保存到文件**：
   * **视觉分析**：查看缩略图网格，理解页面版式、设计模式和视觉结构
   * 创建并保存 `template-inventory.md` 模板清单文件，内容包含：
     ```markdown
     # 模板清单分析
     **总页数：[count]**
     **重要：slide 使用从 0 开始的索引（第一页 = 0，最后一页 = count-1）**

     ## [类别名称]
     - Slide 0: [如果可用，填写 layout code] - 描述/用途
     - Slide 1: [Layout code] - 描述/用途
     - Slide 2: [Layout code] - 描述/用途
     [... 每一页都必须按索引单独列出 ...]
     ```
   * **使用缩略图网格**：参考可视缩略图识别：
     - 版式模式（标题页、内容页、章节分隔页）
     - 图片占位区的位置和数量
     - 不同页面组之间的设计一致性
     - 视觉层级和结构
   * 下一步选择合适模板时，必须使用这个 inventory 文件

3. **基于模板清单创建演示文稿大纲**：
   * 查看第 2 步得到的可用模板。
   * 为第一页选择引入页或标题页模板；通常应从前几页模板中选择。
   * 其他页面选择安全的、以文本承载为主的版式。
   * **关键：让版式结构匹配真实内容**：
     - 单栏版式：用于统一叙事或单一主题
     - 双栏版式：只在确实有 2 个不同条目/概念时使用
     - 三栏版式：只在确实有 3 个不同条目/概念时使用
     - 图片 + 文本版式：只在确实有图片要插入时使用
     - 引用版式：只用于带来源的人物原话，不用于普通强调
     - 不要使用占位区数量多于内容数量的版式
     - 如果只有 2 个条目，不要强行塞进三栏版式
     - 如果有 4 个以上条目，考虑拆成多页或使用列表格式
   * 选择版式前，先数清楚真实内容块数量
   * 确认所选版式中的每个占位区都能填入有意义的内容
   * 为每个内容小节选择一个代表**最佳**版式的选项
   * 保存包含内容和模板映射的 `outline.md`，充分利用可用设计
   * 模板映射示例：
      ```
      # 要使用的模板页（从 0 开始索引）
      # 警告：确认索引在范围内！73 页模板的索引是 0-72
      # 映射：大纲中的页码 -> 模板页索引
      template_mapping = [
          0,   # 使用 slide 0（标题/封面）
          34,  # 使用 slide 34（B1：标题和正文）
          34,  # 再次使用 slide 34（复制成第二个 B1）
          50,  # 使用 slide 50（E1：引用）
          54,  # 使用 slide 54（F2：收尾 + 文本）
      ]
      ```

   * **可选 AI 图片**：如果用户选择 AI 生成视觉素材，在大纲和模板映射稳定后阅读 `references/shared/image-gen.md` 与 `references/shared/image-prompts.md`。生成一份计划，列出 slide 索引、占位区/槽位、图片类型、尺寸、输出路径和预计图片数量。生成图片保存到 `{工作目录}/.temp/images/`，只在替换或后处理步骤中引用。不要让图片承载关键文字或精确数据。组装前，所有 AI 图片都必须按 `references/shared/image-gen.md` 中“图像校验”章节校验；若重试后仍 FAIL，则用原生形状、SVG 图标或色块替代该槽位。

4. **使用 `rearrange_workflow.py` 复制、重排和删除幻灯片**：
   * 使用 `scripts/rearrange_workflow.py` 创建一个按目标顺序排列的新演示文稿：
     ```bash
     python scripts/rearrange_workflow.py template.pptx working.pptx 0,34,34,50,52
     ```
   * 该脚本会自动处理重复页复制、未使用页删除和顺序重排
   * slide 索引从 0 开始（第一页为 0，第二页为 1，依此类推）
   * 同一个 slide 索引可以出现多次，用于复制该页

5. **使用 `inventory_workflow.py` 脚本提取全部文本**：
   * **运行 inventory 提取**：
     ```bash
     python scripts/inventory_workflow.py working.pptx text-inventory.json
     ```
   * **阅读 text-inventory.json**：完整阅读该文件，理解全部 shape 及其属性。**读取时不要设置任何范围限制。**

   * inventory JSON 结构：
      ```json
        {
          "slide-0": {
            "shape-0": {
              "placeholder_type": "TITLE",  // 非占位 shape 时为 null
              "left": 1.5,                  // 位置，单位英寸
              "top": 2.0,
              "width": 7.5,
              "height": 1.2,
              "paragraphs": [
                {
                  "text": "Paragraph text",
                  // 可选属性（只有非默认值才会包含）：
                  "bullet": true,           // 检测到显式项目符号
                  "level": 0,               // bullet 为 true 时才包含
                  "alignment": "CENTER",    // CENTER、RIGHT（LEFT 不写）
                  "space_before": 10.0,     // 段前距，单位 pt
                  "space_after": 6.0,       // 段后距，单位 pt
                  "line_spacing": 22.4,     // 行距，单位 pt
                  "font_name": "Arial",     // 来自第一个 run
                  "font_size": 14.0,        // 字号，单位 pt
                  "bold": true,
                  "italic": false,
                  "underline": false,
                  "color": "FF0000"         // RGB 颜色
                }
              ]
            }
          }
        }
      ```

   * 关键特性：
     - **Slides**：命名为 `"slide-0"`、`"slide-1"` 等
     - **Shapes**：按视觉位置排序（从上到下、从左到右），命名为 `"shape-0"`、`"shape-1"` 等
     - **占位类型**：TITLE、CENTER_TITLE、SUBTITLE、BODY、OBJECT 或 null
     - **默认字号**：`default_font_size`，单位 pt，从 layout 占位区提取（如可用）
     - **页码会被过滤**：SLIDE_NUMBER 占位类型的 shape 会自动从 inventory 中排除
     - **项目符号**：当 `bullet: true` 时，总会包含 `level`（即使为 0）
     - **间距**：`space_before`、`space_after`、`line_spacing`，单位 pt（仅在设置时包含）
     - **颜色**：`color` 表示 RGB（如 `"FF0000"`），`theme_color` 表示主题色（如 `"DARK_1"`）
     - **属性**：输出中只包含非默认值

6. **生成替换文本，并把数据保存为 JSON 文件**
   基于上一步得到的文本 inventory：
   - **关键**：先确认 inventory 中存在哪些 shape，只引用实际存在的 shape
   - **校验**：`replace_workflow.py` 会校验替换 JSON 中的所有 shape 是否都存在于 inventory
     - 如果引用了不存在的 shape，错误会列出可用 shape
     - 如果引用了不存在的 slide，错误会说明该 slide 不存在
     - 脚本退出前会一次性展示所有校验错误
   - **重要**：`replace_workflow.py` 内部会使用 `inventory_workflow.py` 识别全部文本 shape
   - **自动清空**：除非为 shape 提供 `"paragraphs"`，否则 inventory 中的全部文本 shape 都会被清空
   - 需要内容的 shape 添加 `"paragraphs"` 字段，不使用 `"replacement_paragraphs"`
   - 替换 JSON 中没有 `"paragraphs"` 的 shape，其文本会自动清空
   - 带项目符号的段落会自动左对齐；当 `"bullet": true` 时不要设置 `alignment`
   - 为占位文本生成合适的替换内容
   - 根据 shape 尺寸决定合适的内容长度
   - **关键**：包含原始 inventory 中的段落属性，不要只提供文本
   - **重要**：当 `bullet: true` 时，文本里不要包含项目符号（`•`、`-`、`*`），脚本会自动添加
   - **必要格式规则**：
     - 标题通常应设置 `"bold": true`
     - 列表项应设置 `"bullet": true, "level": 0`（bullet 为 true 时必须有 level）
     - 保留已有对齐属性，例如居中文本的 `"alignment": "CENTER"`
     - 与默认值不同的字体属性也要包含，例如 `"font_size": 14.0`、`"font_name": "Lora"`
     - 颜色：RGB 使用 `"color": "FF0000"`，主题色使用 `"theme_color": "DARK_1"`
     - 替换脚本期望的是**格式正确的 paragraphs**，不是简单文本字符串
     - **重叠 shape**：优先选择 `default_font_size` 更大或 `placeholder_type` 更合适的 shape
   - 把带替换内容的更新后 inventory 保存为 `replacement-text.json`
   - **警告**：不同模板版式的 shape 数量不同，创建替换内容前必须检查真实 inventory

   正确格式的 paragraphs 字段示例：
   ```json
   "paragraphs": [
     {
       "text": "新的演示文稿标题文本",
       "alignment": "CENTER",
       "bold": true
     },
     {
       "text": "小节标题",
       "bold": true
     },
     {
       "text": "第一条不带项目符号的要点",
       "bullet": true,
       "level": 0
     },
     {
       "text": "红色文本",
       "color": "FF0000"
     },
     {
       "text": "主题色文本",
       "theme_color": "DARK_1"
     },
     {
       "text": "没有特殊格式的普通段落文本"
     }
   ]
   ```

   **替换 JSON 中没有列出的 shape 会自动清空**：
   ```json
   {
     "slide-0": {
       "shape-0": {
         "paragraphs": [...] // 这个 shape 会获得新文本
       }
       // inventory 中的 shape-1 和 shape-2 会自动清空
     }
   }
   ```

   **演示文稿常见格式模式**：
   - 标题页：加粗文本，有时居中
   - 页内小节标题：加粗文本
   - 项目符号列表：每一项需要 `"bullet": true, "level": 0`
   - 正文：通常不需要特殊属性
   - 引用：可能有特殊对齐或字体属性

7. **使用 `replace_workflow.py` 脚本应用替换**
   ```bash
   python scripts/replace_workflow.py working.pptx replacement-text.json output.pptx
   ```

   脚本会：
   - 先使用 `inventory_workflow.py` 中的函数提取全部文本 shape 的 inventory
   - 校验替换 JSON 中的所有 shape 是否存在于 inventory
   - 清空 inventory 中识别到的全部 shape 文本
   - 只向替换 JSON 中定义了 `"paragraphs"` 的 shape 写入新文本
   - 通过 JSON 中的段落属性保留格式
   - 自动处理项目符号、对齐、字体属性和颜色
   - 保存更新后的演示文稿

   校验错误示例：
   ```
   ERROR: Invalid shapes in replacement JSON:
     - Shape 'shape-99' not found on 'slide-0'. Available shapes: shape-0, shape-1, shape-4
     - Slide 'slide-999' not found in inventory
   ```

   ```
   ERROR: Replacement text made overflow worse in these shapes:
     - slide-0/shape-2: overflow worsened by 1.25" (was 0.00", now 1.25")
   ```

## 创建缩略图网格

如需创建 PowerPoint 幻灯片的可视缩略图网格，供快速分析和参考：

```bash
python scripts/thumbnail_workflow.py template.pptx [output_prefix]
```

**功能**：
- 创建：`thumbnails.jpg`；大文件会生成 `thumbnails-1.jpg`、`thumbnails-2.jpg` 等
- 默认：5 列，每张网格最多 30 页（5×6）
- 自定义前缀：`python scripts/thumbnail_workflow.py template.pptx my-grid`
  - 注意：如果希望输出到特定目录，输出前缀中应包含路径，例如 `workspace/my-grid`
- 调整列数：`--cols 4`，范围 3-6，会影响每张网格包含的页数
- 网格限制：3 列 = 每张 12 页，4 列 = 20 页，5 列 = 30 页，6 列 = 42 页
- slide 从 0 开始索引（Slide 0、Slide 1 等）

**用途**：
- 模板分析：快速理解页面版式和设计模式
- 内容审阅：可视化概览整份演示文稿
- 导航参考：根据视觉外观找到特定页面
- 质量检查：确认所有页面格式正确

**示例**：
```bash
# 基础用法
python scripts/thumbnail_workflow.py presentation.pptx

# 组合选项：自定义名称和列数
python scripts/thumbnail_workflow.py template.pptx analysis --cols 4
```

## 将幻灯片转换为图片

要对 PowerPoint 幻灯片做视觉分析，可以用两步流程将其转换为图片：

1. **将 PPTX 转为 PDF**：
   ```bash
   soffice --headless --convert-to pdf template.pptx
   ```

2. **将 PDF 页面转为 JPEG 图片**：
   ```bash
   pdftoppm -jpeg -r 150 template.pdf slide
   ```
   这会创建 `slide-1.jpg`、`slide-2.jpg` 等文件。

选项：
- `-r 150`：设置分辨率为 150 DPI，可按质量/体积平衡调整
- `-jpeg`：输出 JPEG 格式；如需 PNG，可改用 `-png`
- `-f N`：开始转换的第一页，例如 `-f 2` 表示从第 2 页开始
- `-l N`：最后转换的页码，例如 `-l 5` 表示到第 5 页停止
- `slide`：输出文件前缀

指定范围示例：
```bash
pdftoppm -jpeg -r 150 -f 2 -l 5 template.pdf slide  # 只转换第 2-5 页
```

## 代码风格指南
**重要**：生成 PPTX 操作代码时：
- 代码保持简洁
- 避免冗长变量名和冗余操作
- 避免不必要的打印语句

## 依赖

必需依赖（通常应已安装）：

- **markitdown**：`pip install "markitdown[pptx]"`，用于从演示文稿提取文本
- **pptxgenjs**：`npm install -g pptxgenjs`，用于通过 html2pptx 创建演示文稿

- **react-icons**：`npm install -g react-icons react react-dom`，用于图标
- **sharp**：`npm install -g sharp`，用于 SVG 栅格化和图片处理
- **LibreOffice**：`sudo apt-get install libreoffice`，用于 PDF 转换
- **Poppler**：`sudo apt-get install poppler-utils`，用于通过 pdftoppm 把 PDF 转成图片
- **defusedxml**：`pip install defusedxml`，用于安全 XML 解析

> AI生成