# 语义 class 清单（生成端唯一必读）

本文档定义 **12 种块级语义 class + 2 种辅助 class**。生成 HTML 时，**只需在关键结构最外层元素加上语义 class**，视觉样式完全自由——不设固定块模板，同一语义 class 可有完全不同的视觉呈现。

---

## 为什么需要语义 class？

HTML 转换 Word / PDF / Markdown 时，转换器无法"看懂"视觉样式，只能靠语义 class 判断"这块内容是什么"。

- 加语义 class → 转换器按 IR 语义精确映射（标题变标题、表格变表格）
- 不加语义 class → 转换器兜底处理为普通段落（内容不丢，但结构语义丢失）

所以：**关键结构必加语义 class，装饰性结构可加可不加。**

## 使用原则

1. 只需在关键结构**最外层元素**加一个语义 class
2. 同一语义 class 可有完全不同的视觉呈现
3. 未加语义 class 的元素，转换器兜底处理为普通段落
4. 可选 `data-*` 属性提供附加语义信息（heading 层级、callout 变体、布局列数等）

---

## 12 种块级语义 class

> 以下 12 种 class 对应转换器 `SEMANTIC_CLASSES` 集合（`sem_common.py`），会作为独立语义块被切分并映射到 IR 语义。

### 1. title — 封面/大标题

- **含义**：文档封面、首页大标题区
- **典型元素**：`<section class="title">`
- **结构**：通常含 `<h1>`（标题）+ `<p>`（副标题），可含装饰元素
- **可选 data-***：无
- **视觉自由度**：居中/左对齐均可，可加渐变背景、装饰线、图标

```html
<section class="title" style="padding:60px 40px;text-align:center;background:linear-gradient(135deg,{bg},{primary_light});border-radius:12px;">
  <h1 style="font-size:32px;color:{primary};font-weight:800;">校园音乐节活动策划方案</h1>
  <div style="width:48px;height:3px;background:{accent};margin:12px auto;"></div>
  <p style="font-size:15px;color:{text_secondary};">2026 年秋季 · 深圳校区</p>
</section>
```

### 2. heading — 章节标题

- **含义**：章节/小节标题
- **典型元素**：`<h1 class="heading">`、`<h2 class="heading">`、`<h3 class="heading">`
- **可选 data-***：`data-level`（1/2/3，可由标签推断，不写也行）
- **视觉**：可加左侧强调线、底部分隔线、前缀符号等装饰

```html
<h1 class="heading" style="font-size:28px;color:{primary};border-left:4px solid {accent};padding-left:16px;">一、项目背景</h1>
<h2 class="heading" style="font-size:22px;color:{primary};border-bottom:2px solid {primary_light};padding-bottom:8px;">1.1 行业现状</h2>
```

### 3. paragraph — 正文段落

- **含义**：正文段落
- **典型元素**：`<p class="paragraph">`
- **可选 data-***：无
- **视觉**：字号/行高/缩进自由

```html
<p class="paragraph" style="font-size:15px;color:{text};line-height:1.8;">随着移动互联网的普及，校园营销场景正在发生深刻变化。</p>
```

### 4. card — 卡片/独立区块

- **含义**：卡片式独立内容块。是**最灵活的语义 class**，可表达单卡、卡片网格、多栏、对比等多种结构
- **典型元素**：`<div class="card">`
- **可选 data-***：`data-cols`（并列卡片数）
- **视觉**：白底圆角、描边大圆角、渐变反白、左侧竖线均可

```html
<!-- 单张卡片 -->
<div class="card" style="background:{card};border-radius:12px;box-shadow:0 2px 12px rgba(0,0,0,0.06);padding:24px;">
  <h3 style="font-size:18px;color:{primary};">{卡片标题}</h3>
  <p style="font-size:14px;color:{text_secondary};">{卡片内容}</p>
</div>

<!-- 三张并列卡片（外层容器带 data-cols 标注） -->
<div data-cols="3" style="display:flex;gap:16px;">
  <div class="card" style="flex:1;background:{card};border-radius:12px;padding:24px;box-shadow:0 2px 12px rgba(0,0,0,0.06);">...</div>
  <div class="card" style="flex:1;background:{card};border-radius:12px;padding:24px;box-shadow:0 2px 12px rgba(0,0,0,0.06);">...</div>
  <div class="card" style="flex:1;background:{card};border-radius:12px;padding:24px;box-shadow:0 2px 12px rgba(0,0,0,0.06);">...</div>
</div>
```

### 5. table — 数据表格

- **含义**：数据表格
- **典型元素**：`<table class="table">`
- **可选 data-***：`data-caption`（表格标题）、`data-highlight`（高亮列序号，用于定价表）
- **视觉**：表头底色、斑马纹、边框样式自由

```html
<table class="table" data-caption="{表格标题}">
  <thead>
    <tr><th>{列1}</th><th>{列2}</th></tr>
  </thead>
  <tbody>
    <tr><td>{数据}</td><td>{数据}</td></tr>
  </tbody>
</table>
```

### 6. timeline — 时间线/步骤

- **含义**：时间线、里程碑、步骤序列
- **典型元素**：`<ol class="timeline">`、`<ul class="timeline">`、`<div class="timeline">`
- **可选 data-***：无
- **视觉**：竖线 + 圆点、编号步骤条、时间轴均可

```html
<ol class="timeline" style="list-style:none;padding:0;">
  <li style="border-left:2px solid {accent_light};padding-left:20px;margin-bottom:16px;">
    <strong style="color:{accent};">{时间/阶段}</strong>
    <p style="color:{text};">{事件描述}</p>
  </li>
</ol>
```

### 7. stat — 数字指标

- **含义**：大数字指标卡片
- **典型元素**：`<div class="stat">`
- **可选 data-***：无
- **视觉**：大数字 + 小标签，可渐变背景、可加 icon

```html
<div class="stat" style="text-align:center;padding:24px;background:{card};border-radius:12px;box-shadow:0 2px 12px rgba(0,0,0,0.06);">
  <div style="font-size:32px;color:{accent};font-weight:800;">87%</div>
  <div style="font-size:12px;color:{text_secondary};">用户满意度</div>
</div>
```

### 8. code — 代码块

- **含义**：代码块
- **典型元素**：`<pre class="code"><code>...</code></pre>`
- **可选 data-***：`data-lang`（语言）
- **视觉**：深色/浅色背景均可

```html
<pre class="code" data-lang="python" style="background:#1e293b;color:#e2e8f0;padding:16px 24px;border-radius:8px;font-size:14px;"><code>def hello():
    print("Hello World")</code></pre>
```

### 9. callout — 提示/警告/引用

- **含义**：提示框、警告框、引用块
- **典型元素**：`<aside class="callout">`、`<div class="callout">`
- **可选 data-***：`data-variant`（tip/warning/quote）

```html
<aside class="callout" data-variant="tip" style="background:{primary_light};border-left:4px solid {accent};padding:16px 24px;border-radius:8px;">
  <p style="margin:0;">{提示内容}</p>
</aside>
```

### 10. image — 图片

- **含义**：图片（可带说明）
- **典型元素**：`<figure class="image">`
- **可选 data-***：`data-caption`（图注）、`data-float`（left/right/center/full/wrap）

```html
<figure class="image" data-caption="{图片说明}" data-float="center" style="text-align:center;">
  <img src="data:image/png;base64,{base64}" alt="{说明}" style="max-width:100%;border-radius:8px;">
  <figcaption style="font-size:12px;color:{text_secondary};">{图片说明}</figcaption>
</figure>
```

### 11. list — 列表

- **含义**：有序/无序列表
- **典型元素**：`<ul class="list">`、`<ol class="list">`
- **可选 data-***：无
- **视觉**：自定义圆点、编号、icon 前缀均可

```html
<ul class="list" style="padding-left:24px;line-height:1.8;">
  <li>{条目1}</li>
  <li>{条目2}</li>
</ul>
```

---

### 12. end_page — 尾页/结语

- **含义**：文档末尾的结语、致谢、联系方式页
- **典型元素**：`<section class="title end_page">`（与 title 组合，如 `<section class="title end_page">`）
- **可选 data-***：无
- **视觉**：底部居中 + 致谢，可加背景色/渐变区分
- **转换行为**：Word / PDF 中**新起一页**，Markdown 中作为 `# 标题` 输出

```html
<section class="title end_page" style="padding:60px 24px;text-align:center;background:linear-gradient(135deg,{bg},{primary_light});border-radius:12px;">
  <h1 style="font-size:28px;color:{primary};font-weight:800;">感谢阅读</h1>
  <p style="font-size:15px;color:{text_secondary};">联系人：{姓名}（{电话}）</p>
</section>
```

---

## 辅助 class（2 种，不进 SEMANTIC_CLASSES）

以下 2 种 class 服务于数据来源引用场景，但**不是块级语义 class**，不在 `SEMANTIC_CLASSES` 集合中：

- `cite` 是**段落内联标签**（`<a class="cite">` 嵌在正文段落里）。若把它加入 `SEMANTIC_CLASSES`，会被 `flatten_semantic_blocks` 当独立块切分、破坏所在段落；实际上由段落处理流程内联处理（Word 中转为上标文本 + 内部书签链接）。
- `source-list` 是**普通列表容器**，其内部 `class="list"` 的 `<ol>` 已按列表语义处理；容器本身无需独立 IR。

### 13. cite — 数据来源引用标记

- **含义**：正文中引用数据来源的上标编号标记，点击可跳转到来源列表对应条目
- **典型元素**：`<a class="cite" href="#source-N">[N]</a>`
- **结构**：`href` 指向来源列表中 `id="source-N"` 的锚点，`[N]` 为编号文本
- **可选 data-***：无
- **视觉**：小号上标文字，hover 时变色加下划线，cursor 为 pointer

```html
<p class="paragraph">电信业务收入 8873 亿元，同比下降 2.1%<a class="cite" href="#source-1">[1]</a>，创近年增速新低。</p>
```

### 14. source-list — 数据来源列表（辅助容器）

- **含义**：文档末尾的"主要数据来源"章节，列出所有引用来源的编号、机构名与详情
- **典型元素**：`<div class="source-list"><ol class="list">...</ol></div>`
- **结构**：`<ol>` 内每个 `<li>` 带 `id="source-N"` 作为锚点目标；`<span class="src-id">[N]</span>` 显示编号；`<a class="source-link" href="URL" target="_blank">机构名</a>` 可选超链接
- **可选 data-***：无
- **视觉**：小字号有序列表，编号 accent 色，机构名可点击跳转外部链接

```html
<h1 class="heading">主要数据来源</h1>
<div class="source-list">
  <ol class="list">
    <li id="source-1"><span class="src-id">[1]</span> <a class="source-link" href="https://www.miit.gov.cn/..." target="_blank">工业和信息化部</a>，"2026 年上半年通信业经济运行情况"发布稿（2026 年 7 月 31 日）——电信业务收入 8873 亿元（同比 -2.1%）</li>
    <li id="source-2"><span class="src-id">[2]</span> <a class="source-link" href="https://www.chinatelecom-h.com/" target="_blank">中国电信股份有限公司</a>，2026 年中期业绩报告（2026 年 8 月 20 日）——营业收入 2590.1 亿元</li>
  </ol>
</div>
```

> **cite 与 source-list 配合使用**：正文中用 `<a class="cite" href="#source-N">[N]</a>` 标注引用，来源列表中用 `<li id="source-N">` 接收跳转。两者通过编号 N 一一对应。

---

## 未覆盖的结构如何处理

未加语义 class 的元素，转换器兜底处理为普通段落。以下结构虽然没有语义 class，但转换器也能识别：

| 结构特征 | 识别为 |
|---|---|
| `<blockquote>` | quote（引用） |
| `Q:` 开头段落 / `<details>` | faq（问答） |
| 含 badge/tag 类名的元素 | badge_group（标签组） |
| 多个 `<img>` 网格 | gallery（画廊） |
| icon + 文字行 | icon_list（图标列表） |
| 短线 + 菱形 + 短线 span | divider（章节饰线） |
| 三个圆点 span（旧样式，兼容） | divider（分隔线） |
| 底部居中 + 致谢 | end_page（尾页） |

**最佳实践**：以上结构同样建议加语义 class（如 `<blockquote class="callout" data-variant="quote">`），转换更精确；不加也能被兜底识别。
