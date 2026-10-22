# IR 语义分类字典（转换端参考）

本文档是转换器的内部参考：转换器把自由 HTML 中的语义 class + 结构特征，归约识别为 25 种 IR 语义类型，再映射到 Word / PDF / Markdown 对应结构。

**生成端不需要读本文档**（生成端只读 `semantic-classes.md`）。本文档供转换脚本开发与调试使用，也是影响分析、兼容性矩阵的依据。

---

## 25 种 IR 语义（分四层）

### 核心层（6 种，覆盖 90% 场景）

| IR 语义 | 说明 |
|---|---|
| title_page | 封面/首页 |
| heading | 章节标题（1/2/3 级） |
| paragraph | 正文段落 |
| bullet_list | 有序/无序列表 |
| table | 数据表格 |
| image | 图片 |

### 增强层（4 种）

| IR 语义 | 说明 |
|---|---|
| stat_block | 数字指标卡片 |
| callout | 提示/警告/引用 |
| timeline | 时间线/里程碑 |
| code_block | 代码块 |

### 场景层（5 种）

| IR 语义 | 说明 |
|---|---|
| hero_banner | 大图/海报头部 |
| card_grid | 卡片网格 |
| divider | 分隔线 |
| tab_group | Tab 切换组（交互增强组件） |
| collapse_group | 折叠展开组（交互增强组件） |

### 高级层（10 种）

| IR 语义 | 说明 |
|---|---|
| quote | 引用语录/金句 |
| columns | 多栏并排布局 |
| compare_cards | 并排对比卡片（推荐卡渐变+白字） |
| comparison | 左右对比（A vs B） |
| faq | 问答对 |
| badge_group | 标签/徽章组 |
| gallery | 图片画廊网格 |
| pricing_table | 定价/方案对比表 |
| icon_list | 带图标列表 |
| end_page | 尾页/致谢页 |

---

## 语义归约规则（按优先级）

转换器按以下优先级归约语义 class 到 IR 语义：

| 语义 class | 结构特征判断 | 归约到 IR 语义 | 说明 |
|---|---|---|---|
| title | （无条件） | title_page | 封面 |
| heading | 含 h1/h2/h3 子元素 | heading | data-level 由 h1→1，h2→2，h3→3 推断 |
| paragraph | （无条件） | paragraph | 正文 |
| card | 含多个并列 .card 子元素 | card_grid | data-cols 由并列数量推断 |
| card | 含 2 个 .card 且结构对称 | comparison | 左右对比 |
| card | 单个 .card 含 h3+p | columns | 多栏 |
| table | 含 thead | table | 普通表格 |
| table | 含高亮列 | pricing_table | 定价表 |
| timeline | 含时间点+事件 | timeline | 时间线 |
| stat | 含大数字+标签 | stat_block | 指标卡片 |
| code | 含 pre+code | code_block | 代码块 |
| callout | 含 data-variant 属性 | callout | 提示/警告 |
| image | 含 img | image | 图片 |
| list | 含 ul/ol | bullet_list | 列表 |
| （无 class） | 含 blockquote 子元素 | quote | 引用 |
| （无 class） | 含 Q:/问题 模式 | faq | 问答 |
| （无 class） | 含 details | faq | 可折叠问答 |
| （无 class） | 含 badge/tag 子元素 | badge_group | 标签组 |
| （无 class） | 含多个 img 网格 | gallery | 画廊 |
| （无 class） | 含 icon+文字行 | icon_list | 图标列表 |
| （无 class） | 含 短线+菱形+短线 span | divider | 章节饰线 |
| （无 class） | 含 3 个圆点 span（旧样式兼容） | divider | 分隔线 |
| （无 class） | 含 .tab-nav + .tab-panel | tab_group | Tab 切换组 |
| （无 class） | 含 .collapse-trigger + .collapse-body | collapse_group | 折叠展开组 |
| （无 class） | 含 .compare-grid > .compare-card | compare_cards | 并排对比卡片 |
| （无 class） | 底部居中+致谢 | end_page | 尾页 |

**兜底规则**：无法归约的元素一律映射为 paragraph（普通段落）。

---

## 转换映射

### Word 映射

| IR 语义 | Word 映射 |
|---|---|
| title_page | 居中段落（分页符）+ 背景色 shading |
| heading | Heading 1/2/3（压缩间距, keep_with_next） |
| paragraph | Body 段落（1.15 倍行距） |
| bullet_list | 列表段落 |
| table | Word Table（紧凑 padding） |
| image | InlineShape（data-float → 表格定位） |
| stat_block | 无边框表格（数值 18pt + 标签 9pt 分行）+ 卡片 shading |
| callout | 底色 + 左边框段落 |
| timeline | 两列表格（时间列 accent 加粗 + 事件描述） |
| code_block | Consolas 9.5pt + 浅灰底色 |
| hero_banner | 标题 + 底线（单次分页） |
| card_grid | 无边框表格（标题加粗 + 内容分行）+ 卡片 shading |
| divider | 字符饰线（── ◆ ──） |
| tab_group | 标签→面板交替展开（全部面板内容保留） |
| collapse_group | 标题+正文全展开（折叠交互丢失） |
| quote | 缩进段落（左侧竖线 + 斜体 + 出处）+ 背景色 shading |
| columns | 无边框表格列 + 卡片背景色 shading |
| compare_cards | 并排表格列（推荐卡渐变+白字） |
| comparison | 两列对比表格 |
| faq | 加粗问题 + 缩进段落 |
| badge_group | 逗号分隔文本 |
| gallery | 图片纵列 |
| pricing_table | 对比表格（shading 高亮列） |
| icon_list | 普通列表（图标丢失） |
| end_page | 分页 + 居中段落 + 背景色 shading |

### PDF 兼容

| IR 语义 | PDF 映射 |
|---|---|
| 全部 | 保留（几乎 1:1 还原，仅动画/过渡不可静态呈现，浮动定位分页处可能偏移） |

### Markdown 兼容

| IR 语义 | Markdown 映射 |
|---|---|
| title_page | `# 标题` |
| heading | `# / ## / ###` |
| paragraph | 正文文本 |
| bullet_list | `- / 1.` 列表 |
| table | Markdown 表格 |
| image | `![alt](data:...)` |
| stat_block | 加粗数字文本 |
| callout | `> 引用` |
| timeline | 有序列表 |
| code_block | 围栏代码块 |
| hero_banner | `# 标题` |
| card_grid | 分组标题 + 列表 |
| divider | `---`（转换后为 ── ◆ ── 饰线） |
| tab_group | 全部面板内容保留（展开） |
| collapse_group | 全部折叠内容保留（展开） |
| quote | `> 引用` |
| columns | 分组标题 + 列表 |
| compare_cards | 两组标题 + 列表 |
| comparison | 两组标题 + 列表 |
| faq | 加粗问题 + 正文 |
| badge_group | 逗号分隔文本 |
| gallery | 图片逐个输出 |
| pricing_table | Markdown 表格 |
| icon_list | 普通列表（图标丢失） |
| end_page | 标题 + 致谢文本 |

---

## Word 分页规则

- `hero_banner` / `end_page` → 内容后分页符（去重：连续出现只分页一次）
- `hero_banner`（非首块）→ 前置分页符，Hero 横幅独占一页
- `title_page` → 内容后分页符，由后续语义块自然承接
- `heading`（data-level=1）→ **不再强制分页**，内容顺延（若前一语义块已设置待分页标记则自动承接，避免重复空白页）
- `heading` → `keep_with_next=True`（标题与后续内容保持在同一页）
- 其余内容顺延，段间距统一压缩（Normal: space_before=2pt, space_after=4pt, line_spacing=1.15）

## PDF 分页规则

- `title_page` / `end_page` → 新起一页
- `heading`（data-level=1）→ 新起一页
- 内容溢出自动分页
- `divider` → 空白间隔
- PDF 注入 `@media print` CSS：body padding 归零、title_page/end_page padding 减小至 40px

## Markdown 分页规则

- 无分页概念，以 `---` 分隔线切分章节
