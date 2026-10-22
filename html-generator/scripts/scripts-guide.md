# scripts-guide.md — 脚本加载说明

> html-generator 技能 `scripts/` 目录的模块拆分架构与加载指南。
> 适用于 LLM 选择加载脚本、开发者修改维护、排查转换问题。

## 目录结构

```
scripts/
├── sem_common.py            # 公共语义识别层
├── docx_utils.py            # Word OXML 工具层（字体/调色板/OXML操作）
├── html2docx_core.py        # 核心层处理
├── html2docx_enhanced.py    # 增强层处理
├── html2docx_scene.py       # 场景层处理
├── html2docx_advanced.py    # 高级层处理
├── html2docx.py             # 主入口 + 分发器
├── html2md.py               # HTML→Markdown 转换
├── impact_analyzer.py       # 转换前影响分析
├── html2pdf.py              # HTML→PDF 转换（独立）
├── requirements.txt         # Python 依赖清单
├── win/convert.ps1           # Windows 入口脚本
└── unix/convert.sh           # Unix 入口脚本
```

## 依赖关系图

```
                    ┌──────────────────────────────────────────────┐
                    │              sem_common.py                   │
                    │  （语义识别 / IR 归约 / 数据解析）            │
                    └──────┬───────────┬───────────────────────────┘
                           │           │
               ┌───────────┘           └───────────────┐
               ▼                                       ▼
      html2md.py                             impact_analyzer.py
      （Markdown 渲染）                       （影响分析）
      只加载 sem_common                       只加载 sem_common


                    ┌──────────────────────────────────────────────┐
                    │              docx_utils.py                   │
                    │  （字体 / 调色板 / 颜色解析 / OXML 操作）     │
                    └──┬───────────────────────────────────────────┘
                       │
           ┌───────────┼───────────────────┐
           ▼           ▼                   ▼
       html2docx_core   html2docx_enhanced   html2docx_scene    html2docx_advanced
       （6种核心IR）     （4种增强IR）         （5种场景IR）       （10种高级IR）
               │                               ↑                   ↑
               └───────────────────────────────┘                   │
                      跨层依赖：                                     │
                      scene → core.process_table                    │
                      advanced → core.process_table                 │
                      advanced → core._extract_img_bytes             │
                       │                   │                   │
                       └───────────────────┴───────────────────┘
                                          ▼
                                html2docx.py
                                （主入口 + 分发器）
                                import 全部模块


  html2pdf.py — 独立，不依赖任何其他模块
```

## 按需加载矩阵

| 场景 | 需要加载的脚本 |
|------|---------------|
| HTML → Word 转换 | html2docx.py（自动加载 sem_common → docx_utils → core → enhanced → scene → advanced） |
| HTML → Markdown 转换 | html2md.py（自动加载 sem_common） |
| HTML → PDF 转换 | html2pdf.py（独立，无依赖） |
| 转换前影响分析 | impact_analyzer.py（自动加载 sem_common） |
| 修改语义识别逻辑 | sem_common.py（一处修改，三份脚本同步生效） |
| 修改 Word OXML 操作 | docx_utils.py |
| 修改封面/标题/段落/表格/图片处理 | html2docx_core.py |
| 修改指标卡/callout/时间线/代码块处理 | html2docx_enhanced.py |
| 修改卡片网格/分隔线/Tab组/折叠组/Hero处理 | html2docx_scene.py |
| 修改引用/多栏/对比卡/FAQ/标签/画廊/定价表/图标列表/尾页处理 | html2docx_advanced.py |
| 修改分发逻辑/全局样式/页面背景 | html2docx.py |

## 各模块职责

### sem_common.py — 公共语义识别层
被 html2docx / html2md / impact_analyzer 三份脚本共用，消除重复维护。

**导出内容：**
- 常量：`SEMANTIC_CLASSES`（12种块级语义class + cite/source-list 2种辅助）、`GROUPABLE`（可聚合类型）
- 基础工具：`get_text_content`、`find_semantic_class`、`semantic_children`、`get_data_cols`、`is_visible_text`
- 语义识别：`classify_element`（单元素→IR类型）、`flatten_semantic_blocks`（body→语义块列表）
- 数据解析：`parse_table_data`（HTML表格→二维列表）、`parse_style_blocks`（预解析`<style>`块）

**升级收益：** html2md 和 impact_analyzer 升级到 sem_common 完整版后，新增对 Tab组/compare-grid/折叠组的识别（原先各自维护的子集版本不识别这些结构）。

### docx_utils.py — Word OXML 工具层
Word 文档操作的底层工具，被 html2docx 的四个处理层共用。

**导出内容：**
- 字体：`DEFAULT_FONT`、`CODE_FONT`（跨平台自动适配）
- 调色板：`PALETTES`、`CALLOUT_COLORS`
- 颜色工具：`hex_to_rgb`、`is_dark_color`、`extract_bg_with_gradient_fallback`、`extract_bg_from_styles`、`extract_color_from_styles`、`extract_body_background`、`extract_img_width_px`
- OXML 操作：`set_run_font`、`add_page_break`、`inject_page_break_before`、`flush_pending_page_break`、`set_cell_margins`、`set_table_borders_nil`、`set_table_borders`、`set_cell_borders`、`set_table_width_percent`、`apply_shading`、`apply_shading_to_cell`、`set_page_background`

### html2docx_core.py — 核心层处理（6种 IR）
覆盖 90% 场景的基础内容类型。

| IR 类型 | 处理函数 | 说明 |
|---------|---------|------|
| title_page | process_title_page | 封面页（1x1表格垂直居中 + 深色底 + 白字） |
| heading | process_heading | 章节标题（Heading 1/2/3） |
| paragraph | process_paragraph | 正文段落 |
| bullet_list | process_bullet_list | 无序/有序列表 |
| table | process_table | 数据表格（全宽 + 表头shading） |
| image | process_image | 图片（data-float → 表格定位） |

被 `html2docx_scene.py` 跨层调用 `process_table`（Tab面板内嵌套表格）；
被 `html2docx_advanced.py` 跨层调用 `process_table`（对比兜底）和 `_extract_img_bytes`（画廊图片提取）。

### html2docx_enhanced.py — 增强层处理（4种 IR）

| IR 类型 | 处理函数 | 说明 |
|---------|---------|------|
| stat_block | process_stat_block | 指标卡片（无边框表格 + 顶部accent线） |
| callout | process_callout | 提示/警告/引用（底色 + 左边框段落） |
| timeline | process_timeline | 时间线（两列表格） |
| code_block | process_code_block | 代码块（等宽字体 + 浅灰底色） |

不依赖其他处理层，只依赖 docx_utils。

### html2docx_scene.py — 场景层处理（5种 IR）

| IR 类型 | 处理函数 | 说明 |
|---------|---------|------|
| card_grid | process_card_grid | 卡片网格（无边框表格 + 顶部accent线） |
| divider | process_divider | 章节饰线（── ◆ ──） |
| tab_group | process_tab_group | Tab切换组（标签→面板交替展开） |
| collapse_group | process_collapse_group | 折叠展开组（标题+正文全展开） |
| hero_banner | process_hero_banner | Hero横幅（标题段落 + 装饰横线） |

跨层依赖：`_output_tab_panel` 调 `html2docx_core.process_table` 处理面板内嵌套表格。

### html2docx_advanced.py — 高级层处理（10种 IR）

| IR 类型 | 处理函数 | 说明 |
|---------|---------|------|
| quote | process_quote | 引用语录（斜体 + 左边框 + 缩进） |
| columns | process_columns | 多栏并排（无边框表格列） |
| compare_cards | process_compare_cards | 并排对比卡片（推荐卡渐变+白字） |
| comparison | process_comparison | 左右对比（两列表格） |
| faq | process_faq | 问答对（加粗问题 + 缩进段落） |
| badge_group | process_badge_group | 标签组（顿号分隔文本） |
| gallery | process_gallery | 图片画廊（图片纵列） |
| pricing_table | process_pricing_table | 定价对比表（高亮列shading） |
| icon_list | process_icon_list | 图标列表（普通列表，图标丢失） |
| end_page | process_end_page | 尾页/致谢页（1x1表格居中 + 背景色） |

跨层依赖：`process_comparison` 兜底调 `html2docx_core.process_table`；`process_gallery` 调 `html2docx_core._extract_img_bytes`。

### html2docx.py — 主入口 + 分发器
只保留：
1. `import` 全部模块
2. `convert_html_to_docx(html_path, docx_path)` — 主转换函数（创建Document、设置全局样式、遍历语义块、分发处理）
3. `process_block(doc, element, ir, group_info, palette, ...)` — IR分发器（25种IR → 对应处理函数）
4. `__main__` 入口

### html2md.py — HTML→Markdown 转换
从 sem_common 导入语义识别函数，只保留 Markdown 渲染逻辑。

### impact_analyzer.py — 转换前影响分析
从 sem_common 导入 `find_semantic_class` 和 `classify_element`，只保留影响分析逻辑。

### html2pdf.py — HTML→PDF 转换
独立脚本，不依赖任何其他模块。使用 Playwright（无头 Chromium）直接将 HTML 渲染为 PDF。
注入 `@media print` CSS 实现交互组件静态化：Tab 全部面板展开、折叠全部展开、搜索框/复制按钮/返回顶部按钮隐藏。

## 运行方式

### 通过入口脚本运行
```powershell
# Windows
.\scripts\win\convert.ps1 -Format docx -InputFile report.html -OutputFile report.docx
.\scripts\win\convert.ps1 -Format md -InputFile report.html -OutputFile report.md
.\scripts\win\convert.ps1 -Format pdf -InputFile report.html -OutputFile report.pdf
```

```bash
# Unix
./scripts/unix/convert.sh --format docx --input report.html --output report.docx
./scripts/unix/convert.sh --format md --input report.html --output report.md
./scripts/unix/convert.sh --format pdf --input report.html --output report.pdf
```

### 直接运行 Python 脚本
```bash
python scripts/html2docx.py input.html output.docx
python scripts/html2md.py input.html output.md
python scripts/html2pdf.py input.html output.pdf
python scripts/impact_analyzer.py input.html --format docx --json
```

> Python 运行时自动将 `scripts/` 目录加入 `sys.path`，同目录 `.py` 文件可直接 `import`，无需修改路径配置。

## 修改指南

### 添加新的 IR 类型
1. 在 `sem_common.py` 的 `classify_element` 中添加识别规则
2. 在 `sem_common.py` 的 `flatten_semantic_blocks` 中添加聚合/分块逻辑（如需要）
3. 在对应的处理层文件中添加 `process_xxx` 函数
4. 在 `html2docx.py` 的 `process_block` 分发器中添加 `elif` 分支
5. 在 `html2md.py` 的 `render_block` 的 `handlers` 字典中添加渲染函数（如需要）
6. 在 `impact_analyzer.py` 的 `WORD_DEGRADATION` 中添加降级说明（如需要）

### 修改已有处理逻辑
直接修改对应层级的文件即可，无需改动其他文件。例如修改指标卡片处理 → 只改 `html2docx_enhanced.py` 中的 `process_stat_block`。

### 修改语义识别逻辑
只改 `sem_common.py` 一处，html2docx / html2md / impact_analyzer 三份脚本同步生效。

## 拆分历史

- 2026-08：从单文件 `html2docx.py`（2314行/92KB）拆分为 6 个新模块 + 精简 3 个原文件，消除三份脚本间重复维护的语义识别代码。
