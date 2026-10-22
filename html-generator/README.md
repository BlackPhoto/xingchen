# html-generator — 通用 HTML 文档生成技能

**一次内容编排 · 四种格式输出（HTML / Word / PDF / Markdown）**

通用 HTML 文档生成技能：用户说"生成HTML / 写文档 / 做方案 / 做报告 / 生成页面"，即生成一个视觉精良、离线自包含的 HTML 文档；用户需要时，可一键转换为 Word、PDF、Markdown。

## 核心理念

**生成放开、转换归约。**

- **生成端**：不设固定块模板，LLM 自由设计 HTML 结构与视觉样式（仅需在关键结构的最外层元素挂 12 种轻量语义 class）。
- **转换端**：通过语义 class + 结构特征，把自由 HTML 归约到 25 种 IR 语义，再映射到 Word / PDF / Markdown 的对应结构。

HTML 是源文件，Word / PDF / Markdown 是派生格式——以 HTML 为准，转换是尽力而为的语义归约。

## 目录结构

```
html-generator/
├── SKILL.md                        # 技能主文档（LLM 执行流程）
├── README.md                       # 本文件（技能说明）
├── references/
│   ├── semantic-classes.md         # 12 种语义 class 定义（生成端必读）
│   ├── ir-blocks.md                # 25 种 IR 语义分类字典（转换端内部参考）
│   ├── palettes.json               # 8 组调色板 × 19 语义色位
│   ├── design-system.md            # 字体/字号/间距/视觉规范速查
│   ├── interactive-pack.md         # 交互增强组件（L1 级，跨模式可选叠加）
│   └── skeletons/
│       ├── mode-doc.html           # 结构化长文（全组件示例）
│       ├── mode-compare.html       # 方案对比/产品选型
│       ├── mode-status.html        # 项目周报/进度汇报
│       ├── mode-explainer.html     # 教程/使用指南
│       ├── mode-dashboard.html     # 数据概览/经营简报
│       ├── mode-deck.html          # 产品介绍长页/品牌故事/活动专题
│       └── mode-auto.html          # 兜底（精简骨架，LLM 自由填组件）
└── scripts/
    ├── sem_common.py            # 公共语义识别层（三份脚本共用）
    ├── docx_utils.py            # Word OXML 工具层（字体/调色板/OXML操作）
    ├── html2docx_core.py        # 核心层：封面/标题/段落/列表/表格/图片
    ├── html2docx_enhanced.py    # 增强层：指标卡/callout/时间线/代码块
    ├── html2docx_scene.py       # 场景层：卡片网格/分隔线/Tab组/折叠组/Hero
    ├── html2docx_advanced.py    # 高级层：引用/多栏/对比卡/FAQ/画廊/尾页等
    ├── html2docx.py             # 主入口 + 分发器（HTML → Word）
    ├── html2md.py               # HTML → Markdown（语义归约）
    ├── html2pdf.py              # HTML → PDF（Playwright 无头 Chromium）
    ├── impact_analyzer.py      # 转换前影响分析（降级清单）
    ├── scripts-guide.md         # 脚本加载说明（模块依赖与按需加载）
    ├── requirements.txt         # Python 依赖
    ├── win/
    │   └── convert.ps1           # Windows 入口脚本
    └── unix/
        └── convert.sh            # macOS / Linux 入口脚本
```

## 使用方式

技能由 Agent 按 SKILL.md 中的三阶段工作流驱动，用户通常只需一句话：

### 1. 生成 HTML

> "帮我生成一份《2026 年智能家居行业调研报告》"

Agent 自动完成：确定文档模式（7 选 1）→ 确定调色板（8 选 1）→ 确定图片策略 → 生成 `{主题拼音}.html` 到用户工作目录，并展示预览。

### 2. 转换格式（用户主动触发）

> "转 Word" / "导出 PDF" / "顺便给我一份 Markdown"

- **Word / PDF**：先做影响分析（列出会降级的视觉特性），Agent 询问用户确认后执行转换。
- **Markdown**：只保留结构（标题/列表/表格/代码块），做精简版影响分析（只报结构降级，不报视觉降级），有结构降级时询问用户确认后执行。

### 3. 转换命令示例（手动执行）

```bash
# 影响分析（Word/PDF 转换前）
python scripts/impact_analyzer.py report.html --format docx --json
# 输出：{"need_remind": true/false, "items": [...], "format": "docx"}

# Windows 转换
powershell -File scripts/win/convert.ps1 -Format docx -InputFile report.html -OutputFile report.docx -Yes

# macOS / Linux 转换
bash scripts/unix/convert.sh --format pdf --input report.html --output report.pdf --yes
```

脚本自动管理 Python 虚拟环境（conda 优先，env 名 `html-convert`，fallback 到 `~/.html-convert-env`），首次运行自动安装依赖（含 Playwright Chromium 下载）。依赖清单见 `scripts/requirements.txt`（python-docx、beautifulsoup4、lxml、playwright；cssutils 为可选增强，未安装自动跳过）。

## 兼容性矩阵（概要）

| 语义 class | 归约 IR | Word | PDF | Markdown |
|---|---|---|---|---|
| title | title_page | 居中 + shading | 新页 + 居中 + 渐变 | `# 标题` |
| heading | heading | Heading 1/2/3 | 保留，level=1 新页 | `# / ## / ###` |
| paragraph | paragraph | 正文段落 | 保留 | 正文 |
| card | card_grid/comparison/columns | 无边框表格 | 保留 | 分组标题 + 列表 |
| table | table/pricing_table | Word Table | 保留 | Markdown 表格 |
| timeline | timeline | 两列表格（时间列 accent 加粗） | 保留 | 有序列表 |
| stat | stat_block | 无边框表格 | 保留 | 加粗数字 |
| code | code_block | Consolas + 浅灰底 | 保留 | 围栏代码块 |
| callout | callout | 底色 + 左边框 | 保留 | > 引用 |
| image | image | InlineShape | 保留 | ![alt](data:...) |
| list | bullet_list | 列表段落 | 保留 | 列表 |
| end_page | end_page | 新起一页 | 新起一页 | `# 标题` |

完整降级规则、分页规则见 `SKILL.md` 的"兼容性矩阵"与"分页规则"章节。

## 常见问题

**Q：转换保真度如何？**
A：HTML → Word 语义 95% / 视觉 70%（卡片/时间线等降级为表格/段落）；HTML → PDF 语义 95% / 视觉 95%（近乎 1:1）；HTML → Markdown 语义 90%（结构保留，视觉不保留）。

**Q：能加交互功能吗？**
A：能。用户明确要求"可交互/可筛选/Tab 切换/可折叠"等时，从 `interactive-pack.md` 选取对应组件（Tab 切换、表格搜索、折叠展开、代码复制、返回顶部），CSS 和 JS 直接内联到 HTML 中。交互功能转 Word/PDF/Markdown 时按降级表处理——交互丢失但内容完整保留。

**Q：为什么 Word 里渐变、圆角没了？**
A：Word 文档模型不支持 CSS 渐变/圆角/阴影。纯色背景保留为单元格 shading，渐变降级为最饱和纯色，圆角/阴影按预期丢失——转换前影响分析会逐项列明，转换后 Agent 也会主动告知。

**Q：图片能带进 Word/PDF 吗？**
A：能。所有图片在 HTML 生成阶段即 base64 内嵌，转换时直接提取嵌入。Word 里 SVG 降级为 PNG，PDF 保留。

**Q：需要联网吗？**
A：HTML 生成完全离线；转换脚本首次运行需下载依赖（Playwright Chromium），之后离线可用。
