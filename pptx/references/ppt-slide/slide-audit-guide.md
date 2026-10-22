---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: '5cf4b0b4-7d19-4a31-832c-51026c2ffeb9'
  PropagateID: '5cf4b0b4-7d19-4a31-832c-51026c2ffeb9'
  ReservedCode1: 'fb847299-909a-4346-b704-1a0fa27c5705'
  ReservedCode2: 'fb847299-909a-4346-b704-1a0fa27c5705'
---

# slide-audit — HTML 幻灯片几何体检引擎

检测 HTML 幻灯片中的排版问题（溢出、重叠、遮挡、裁切、越界、截断、低对比度、字号过小），
使用真实无头浏览器测量几何数据，不依赖视觉模型。专为 AI 生成的 HTML 幻灯片设计——
把视觉模型才能发现的问题，用数值计算在 ~0.5 秒/页内完成。

## Purpose

用真实无头浏览器（Chrome/Edge）的 `getBoundingClientRect` / `Range` / `elementFromPoint` 等精确几何 API，
检测 HTML 幻灯片中的排版问题。全部判定基于真实 layout 结果，
能覆盖字体度量、自动换行、flex/grid、绝对定位叠加等静态解析无法处理的场景。

## When to use

- 步骤 3.6（逐页几何体检）和步骤 6.5（打包后全量体检）执行此引擎
- 用户要求检查 slide 溢出/越界/重叠/被挡住/排版问题时
- 幻灯片截图前或转 PPTX 前的快速预检
- 迭代修稿时用 --baseline 只看新增问题

## What it checks

| 规则 | 严重级别 | 检测内容 |
|------|----------|----------|
| TEXT_OVERFLOW | error / warning | 文字内容大于容器内容区。使用 Range rects 测量自动换行和行高。容器有背景色时升级为 error。 |
| CHILD_OUT_OF_PARENT | warning | 子元素超出父容器可视范围。父级同一轴向已报 TEXT_OVERFLOW 时自动去重。 |
| TEXT_CLIPPED | error | 文字被祖先 overflow:hidden 裁切——完全不可见。 |
| OUT_OF_CANVAS | error | 内容超出 1280×768 画布。PPTX 会丢弃这部分。 |
| OVERLAP | error / warning | 兄弟元素相互碰撞。过滤 1-3px 行盒贴边。 |
| OCCLUDED | error / warning | 文字被上层元素遮挡。通过 elementFromPoint 网格采样检测。可用 --no-occlusion 关闭（最慢的规则）。 |
| TEXT_TRUNCATED | warning | white-space:nowrap 且 scrollWidth > clientWidth。 |
| LOW_CONTRAST | error / warning | WCAG 对比度低于阈值。渐变背景取第一个颜色做近似（标注 approx）。 |
| FONT_TOO_SMALL | info | 字号 < 18px（本技能默认阈值）。 |
| CONSOLE | warning | 页面 JS 错误。 |

## Quick start

### 单页检查（步骤 3.6 最常用）

```powershell
# Windows (PowerShell)
node scripts/slide-audit.mjs "{主题}_output/slide_01.html" --fail-on error --json "{主题}_output/slide_01.audit.json"
```
```bash
# macOS / Linux (zsh/bash)
node scripts/slide-audit.mjs "{主题}_output/slide_01.html" --fail-on error --json "{主题}_output/slide_01.audit.json"
```

### 批量检查 + 可视化报告（步骤 6.5 常用）

```powershell
# Windows (PowerShell)
node scripts/slide-audit.mjs "{主题}_output/" --open
```
```bash
# macOS / Linux (zsh/bash)
node scripts/slide-audit.mjs "{主题}_output/" --open
```

`--open` 生成带标注截图的可视化报告并自动在浏览器打开（Windows: `start`，macOS: `open`，Linux: `xdg-open`）。

### 迭代修稿

```bash
# 所有平台通用
# 第一次：保存基线
node scripts/slide-audit.mjs "{主题}_output/" --json v1.json

# 修完 slide 后：只看新增问题
node scripts/slide-audit.mjs "{主题}_output/" --baseline v1.json --open
```

### CI 门禁

```bash
# 所有平台通用
node scripts/slide-audit.mjs "{主题}_output/" --fail-on error --quiet
```

有 error 时退出码为 1，可接入自动转换或截图前的门禁。

## Input formats accepted

- 单个 .html 文件（slide_01.html, slide_02.html, ...）
- 目录（递归扫描）
- glob（slide_*.html）
- 单文件多页 deck：`<script type="text/html">` 模板格式——自动拆分逐页检查，行号映射回原始文件
- 单个 HTML 含多个 .slide 元素

页面没有 .slide 容器但含 iframe 时，判定为播放器外壳页并跳过（用 --include-shell 强制检查）。

## Reading the report

每个问题包含：
- **Path**：CSS selector 链（含 nth-child），在源文件中匹配定位
- **Line**：问题 style 所在的源码行号（兄弟元素共用同一段 inline style 时按 nth-occurrence 定位）
- **Rect**：问题区域在幻灯片局部坐标系中的位置
- **Suggestions**：至少一条具体的 old → new 修复值（如 height:100px → height:146px）。如果加高后会超出画布底部，还会附带 top 调整建议

## CLI options

| 选项 | 说明 |
|------|------|
| --out \<file\> | 输出可视化 HTML 报告（默认 audit-report.html） |
| --json \<file\> | 输出 JSON 结果（默认 audit-report.json） |
| --md \<file\> | 输出 Markdown 报告 |
| --open | 跑完自动打开 HTML 报告 |
| --shots \<dir\> | 导出每页带标注框的 PNG |
| --fail-on \<level\> | error\|warning\|none，命中则退出码 1（默认 none） |
| --baseline \<json\> | 与上次 JSON 对比，只报告新增/变化的问题 |
| --min-font \<n\> | 最小字号阈值（默认 18，已与技能规则一致） |
| --min-contrast \<n\> | 最小对比度阈值（默认 3.0） |
| --tol \<n\> | 几何容差 px（默认 1.5） |
| --no-contrast | 关闭对比度检查 |
| --no-occlusion | 关闭遮挡检查（最耗时的一项） |
| --no-out | 不生成 HTML 可视化报告和截图（步骤3.6 逐页体检时使用，步骤6.5 全量体检仍用 --out） |
| --chrome \<path\> | 指定浏览器可执行文件 |
| --quiet | 只输出汇总行 |
| --include-shell | 强制检查外壳页 |

## Iterating on false positives

如果工具标记了刻意的装饰性重叠或对比度：

1. engine.js 顶部定义了所有阈值常量：minOverlapDim, occludeRatio, minFontSize, minContrast, overflowTol, sampleStep
2. CLI 覆盖：--min-contrast 4.5, --no-contrast, --no-occlusion, --tol 0.5
3. 永久关闭某条规则：在 engine.js 中设置 RULES.\<NAME\> = { run: () => {} }

## Limits

- 渐变背景：对比度检查取第一个颜色，结果为近似值（报告中标注 approx）
- Web 字体未加载完成时：回退到系统度量，可能误判宽度
- elementFromPoint 需要内容在视口内；多 slide 单文件时运行器自动扩展视口到 document.scrollHeight
- 浏览器必须已安装：Chrome 或 Edge（任意较新版本）。运行器会自动查找各平台默认安装路径（Windows: Program Files；macOS: /Applications；Linux: /usr/bin）

## Files

- scripts/engine.js — 页面内注入的几何审计引擎。规则定义和阈值常量在文件顶部
- scripts/slide-audit.mjs — Node 运行器。零 npm 依赖，手写极简 CDP 客户端驱动无头 Chrome/Edge
- 各平台统一通过 `node scripts/slide-audit.mjs` 调用，无需启动器

> AI生成