# 设计系统速查

本文档是生成 HTML 时的视觉规范速查（推荐级别，非强制约束）。LLM 在保持整体美观的前提下可自由发挥，但推荐遵循以下基准保证视觉质量。

## 字体栈（跨平台）

```
正文: -apple-system, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Segoe UI", "Noto Sans SC", sans-serif
代码: "Cascadia Code", "Fira Code", "SF Mono", "Source Code Pro", Consolas, monospace
```

覆盖平台：macOS（PingFang / SF Mono）、Windows（YaHei / Segoe UI）、Linux（Noto Sans SC）。

## 字号层级（mode-doc 基准）

| 层级 | 字号 |
|---|---|
| H1 | 28px |
| H2 | 22px |
| H3 | 18px |
| 正文 | 15px |
| 注释/标签 | 12px |

行高：正文 `line-height: 1.8`，标题 `line-height: 1.3`。

## 间距栅格（8px 基数）

| 空间类型 | 值 |
|---|---|
| section 间距 | 32px (8×4) |
| 块间距 | 16px (8×2) |
| 内边距 | 24px (8×3) |

## 视觉规范

| 属性 | 值 |
|---|---|
| 卡片圆角 | 12px |
| 标签圆角 | 6px（胶囊 20px） |
| 卡片阴影 | `0 2px 12px rgba(0,0,0,0.08)` |
| 页面最大宽度 | 820px（mode-doc 基准） |

## 图表组件规范（柱状图 / 条形图 / 占比图）

> **背景**：曾因图表组件类名（`.chart-row` / `.bar` 等）只在某个具体卡片容器（如 `.trend-card`）下定义了样式，导致其他卡片（如 `.sparkline-card`）复用这些类名时样式全部缺失、图表塌陷为满幅色条堆叠。本规范固定图表的**组件类命名与配套样式**，防止再犯。

### 组件类（通用，不挂在具体容器下）

| 类名 | 作用 | 必备属性 |
|---|---|---|
| `.chart-row` | 条形容器（横向排列所有条形） | `display:flex; gap; align-items:flex-end; height` |
| `.bar` | 单个条形 | `flex:1; min-height; border-radius; background` |
| `.chart-labels` | 条形下方的分类标签行 | `display:flex; gap; margin-top` |
| `.stat-inline` | 图表下方的行内数字/说明 | `display:flex; gap; margin-top; padding-top; border-top` |

**组件类必须定义为独立通用类**（选择器不挂在具体卡片容器下），任何卡片内复用都生效：

```css
/* ✅ 正确：独立通用类，任何卡片内都能用 */
.chart-row { display: flex; gap: 6px; align-items: flex-end; height: 64px; margin: 0 0 10px 0; }
.chart-row .bar { flex: 1; border-radius: 3px 3px 0 0; min-height: 4px; background: linear-gradient(180deg, #3b82f6, #e8f0fe); }
.chart-labels { display: flex; gap: 6px; margin-top: 2px; }
.chart-labels span { flex: 1; text-align: center; font-size: 10px; color: #5b6b80; }
.stat-inline { display: flex; gap: 24px; margin-top: 12px; padding-top: 12px; border-top: 1px solid #dbe4ef; }
.stat-inline .item .v { font-size: 20px; font-weight: 800; color: #0f1e33; }
.stat-inline .item .l { font-size: 11px; color: #5b6b80; margin-top: 2px; }

/* ❌ 禁止：挂在具体卡片下，换卡片就失效 */
.trend-card .chart-row { ... }
```

> 若同一页面存在多个不同风格的图表卡片，可用**复合选择器**把多个容器一并纳入（等价于通用类）：
> ```css
> .trend-card .chart-row, .sparkline-card .chart-row { display: flex; ... }
> ```

### 2. 配套选择器清单（必须成套出现）

凡使用图表组件类名，`<style>` 中**必须同时定义以下选择器**，缺一即可能导致图表塌陷：

| 若使用了 | 必须同时有 |
|---|---|
| `.bar` | `.chart-row`（flex 布局） |
| `.chart-row` | `.chart-row .bar`（条形外观） |
| `.chart-labels` | `.chart-labels span`（标签 flex） |
| `.stat-inline` | `.stat-inline .item .v` 和 `.stat-inline .item .l` |

**硬性检查**：生成完成后自查一遍——凡是 HTML 里出现上述类名，`<style>` 里必须能匹配到对应选择器；查不到就补上。

### 3. 标准 HTML 结构模板（可直接复制）

```html
<div class="sparkline-card">  <!-- 或任意卡片容器 -->
  <h3>各维度平均得分对比</h3>
  <!-- 条形图：条形数 = 标签数 = 数字行 item 数，三者一一对应 -->
  <div class="chart-row">
    <div class="bar" style="height:85%;background:linear-gradient(180deg,#3b82f6,#e8f0fe);"></div>
    <div class="bar" style="height:82%;background:linear-gradient(180deg,#2563eb,#dbe7f6);"></div>
    <div class="bar" style="height:88%;background:linear-gradient(180deg,#3b82f6,#e8f0fe);"></div>
  </div>
  <div class="chart-labels">
    <span>准确性</span><span>完整性</span><span>一致性</span>
  </div>
  <div class="stat-inline">
    <div class="item"><div class="v">84.9</div><div class="l">准确性均分</div></div>
    <div class="item"><div class="v">81.8</div><div class="l">完整性均分</div></div>
    <div class="item"><div class="v">86.4</div><div class="l">一致性均分</div></div>
  </div>
</div>
```

**一致性要求**：条形数量 = 标签数量 = 数据项数量，三者必须一一对应（HTML 结构层面肉眼可核对）。

### 4. 内联样式兜底（可选加固）

若担心类名缺失，可在 `.bar` 的内联 `style` 中带上关键布局属性（`flex:1;border-radius:3px 3px 0 0;`），即使 `<style>` 中该选择器漏定义，条形也不会满幅撑开。

## 语义色位（20 个）

每套调色板统一提供以下 20 个语义色位，模板和转换脚本统一引用语义名而非具体色值：

| 色位 | CSS 变量 | 用途 |
|---|---|---|
| primary | `--c-primary` | 主色：标题、强调文字 |
| accent | `--c-accent` | 辅色：数值、标签、装饰线 |
| bg | `--c-bg` | 页面基础背景色（纯色降级时使用） |
| bg_deep | `--c-bg_deep` | 深一档背景（章节交替底色/浅色区块） |
| bg_gradient_a | `--c-bg_gradient_a` | 页面背景渐变起始色（浅色系） |
| bg_gradient_b | `--c-bg_gradient_b` | 页面背景渐变结束色（浅色系） |
| card | `--c-card` | 卡片背景色 |
| text | `--c-text` | 正文文字色 |
| text_secondary | `--c-text_secondary` | 次要文字色（注释、说明） |
| border | `--c-border` | 边框色 |
| primary_light | `--c-primary_light` | 主色浅色版（浅底高亮） |
| accent_light | `--c-accent_light` | 辅色浅色版（浅底标签） |
| primary_dark | `--c-primary_dark` | 主色深色版（深色标题/渐变深端） |
| accent_dark | `--c-accent_dark` | 辅色深色版（深色装饰） |
| accent_bg | `--c-accent_bg` | 辅色倾向浅色背景（重点区块/hero 浅色变体） |
| gradient_start | `--c-gradient_start` | 渐变起始色（hero/封面深色端） |
| gradient_mid | `--c-gradient_mid` | 渐变中间色（hero/封面三色渐变的过渡色） |
| gradient_end | `--c-gradient_end` | 渐变结束色（hero/封面浅色端） |
| success | `--c-success` | 成功/推荐色 |
| warning | `--c-warning` | 警告/注意色 |

**完整色值见 `references/palettes.json`**。

## 背景层次规范（五层体系）

生成 HTML 时按以下 5 层构建背景，营造丰富层次（骨架已内置，LLM 生成时保持）：

| 层级 | 实现 | 说明 |
|---|---|---|
| ① 页面底 | `body { background: linear-gradient(160deg, {bg_gradient_a} 0%, {card} 45%, {bg_gradient_b} 100%); }` | 整页浅色三色渐变（a→白→带色相 b），替代死白纯色；三色让过渡层次更丰富、方向感更强 |
| ② 全局光斑 | `body::before` 叠加两个 `radial-gradient` 白色光晕（`position:fixed; z-index:0; pointer-events:none`） | 页面呼吸感、柔和 |
| ③ 封面 Hero | `section.title` 用深色三色渐变 `linear-gradient(135deg, {gradient_start} 0%, {gradient_mid} 50%, {gradient_end} 100%)` + `::before` 白色光斑 + 白字 + 半透明徽章 | 视觉锚点；三色过渡让同色相渐变层次更分明 |
| ④ 正文区 | 章节容器白底圆角卡片 `{card}`，或交替 `{bg_deep}` 浅色区块；表格表头 `{primary_light}→{accent_light}` 渐变 | 深浅交替、区块分明 |
| ⑤ 尾页 | `end_page` 用 `{primary_light}→{accent_light}` 渐变（或深色渐变呼应封面） | 首尾呼应 |

**注意**：
- body 背景渐变转 Word 时由 body 底色（`bg` 色位）接管；封面/尾页渐变转 Word 时降级为纯色（脚本 `extract_bg_with_gradient_fallback` 已支持）。
- `body::before` 光斑需 `position: fixed` 且 `pointer-events: none`，避免影响页面交互与内容布局。
- **渐变可见性要求**：`bg_gradient_b` 必须比 `bg_gradient_a` 深 25+ 亮度且带明确色相；`primary_light`/`accent_light` 渐变两端亮度差 15+ 且色相尽量不同（如蓝→紫、金→橙）；Hero 深色渐变两端亮度差 50+ 且**相邻色段需亮度递进、中间色与两端同色系但过渡明显**（三色方案缓解同色相过渡的人眼感知弱问题）。调色板色值已按此要求设计，生成时请勿把渐变色位替换成过于接近的浅色。

## 视觉增强建议（自由发挥方向）

生成 HTML 时可综合运用以下视觉增强手段提升质感（均为推荐，不强制）：

1. **卡片层次**：卡片用 `box-shadow` + `border-radius` + `overflow:hidden` 营造立体感
2. **标题装饰**：章节标题用 `border-left` 强调线 + `padding-left` 缩进；卡片标题用 `border-bottom` 分隔线
3. **渐变装饰**：封面/横幅用渐变背景增强视觉冲击
4. **伪元素装饰**：时间线用 `::before` 绘制圆点和连线；Hero 用 `::before` 绘制光斑
5. **色彩层次**：每个区块使用调色板 5+ 个色位营造深浅层次（primary → primary_light → bg → card → border）
6. **状态胶囊**：周报/状态类文档用圆角胶囊标签表示"进行中/已完成/风险"等状态
7. **深浅交替**：相邻章节可交替使用 `{card}` 与 `{bg_deep}` 底色，避免页面全白

## 标签系统（推荐色值）

| 标签类型 | 背景色 | 文字色 | 用途 |
|---|---|---|---|
| 推荐/成功 | `#E8F5E9` | `#2E7D32` | 推荐内容 |
| 预约/警告 | `#FFF3E0` | `#E65100` | 需预约 |
| 信息 | `#E3F2FD` | `#1565C0` | 免费内容 |
| 危险 | `#FCE4EC` | `#C62828` | 需注意 |

## callout 变体

| variant | 背景色 | 左边框色 | 用途 |
|---|---|---|---|
| tip | `#E8F5E9` | `#2E7D32` | 提示/建议 |
| warning | `#FFF3E0` | `#E65100` | 警告/注意 |
| quote | `#f0fdfa` | `#14b8a6` | 引用/摘录 |

> 生成时可用调色板的 `success`/`warning` 对应色位替代以上固定色值，保持文档色彩统一。

## 图片布局（data-float）

| data-float 值 | HTML 效果 | Word 映射 | PDF 映射 |
|---|---|---|---|
| center（默认） | 居中 | 居中 InlineShape | 保留 |
| left | 左浮动 | 表格定位左列 | 保留 |
| right | 右浮动 | 表格定位右列 | 保留 |
| full | 全宽 | 宽度 100% InlineShape | 保留 |
| wrap | 图文环绕 | 表格模拟环绕 | 保留 |

## 响应式 + 打印优化

模式骨架 HTML 的全局 `<style>` 块已包含响应式和打印优化规则（`@media print`），生成 HTML 时应在 `<head>` 中保留骨架的 `<style>` 块。

PDF 转换脚本（html2pdf.py）会额外注入 `@media print` CSS 解决留白和背景色问题（body padding 归零、title/end_page padding 减小至 40px、`print-color-adjust: exact` 等）。
