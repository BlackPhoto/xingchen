# QA 流程与常见问题

## QA 流程

**默认认为一定存在问题。你的任务是把它们找出来。**

第一次渲染几乎不会完全正确。把 QA 当成找 bug，而不是确认无误。如果第一次检查就没有发现任何问题，说明检查还不够仔细。

### 内容 QA

```bash
python -m markitdown output.pptx
```

检查是否有内容缺失、错别字或顺序错误。

**检查是否残留占位文本：**

```bash
python -m markitdown output.pptx | grep -iE "xxxx|lorem|ipsum|placeholder|this.*(page|slide).*layout"
```

如果 grep 返回结果，先修复这些问题，再声明完成。

### 验证循环

1. 生成 slides -> 用 `python -m markitdown output.pptx` 提取文本 -> 审阅内容
2. **列出发现的问题**；如果没有发现问题，要更严格地再看一遍
3. 修复问题
4. **重新验证受影响的页面**，因为一次修复经常会引入另一个问题
5. 重复上述步骤，直到一次完整检查没有发现新问题

**至少完成一次“修复并复验”循环后，才可以声明成功。**

### 单页 QA（用于从零创建）

```bash
python -m markitdown slide-XX-preview.pptx
```

检查是否有内容缺失、占位文本、页码标识缺失。

### 布局自动检测（视觉检查前先跑）

客观检测层：用 `detect_layout.py` 逐页核验版式缺陷，不依赖渲染，基于 PPTX 内部 XML 坐标精确计算，结果作为视觉检查的必查清单。

```bash
python scripts/detect_layout.py <pptx文件路径>
```

脚本检测范围与判定规则：
- **文字重叠/模板遮挡**：坐标系矩形相交计算，重叠>5% 即报告。重叠≤5% 且视觉无法察觉的不计入缺陷。
- **文字溢出**：文本框坐标越界检测。
- **页面空白**：50×50 网格采样法计算内容面积占比，仅正文页空白>90% 记缺陷（首页、目录页、章节过渡页、尾页豁免）。
- **字号层级**：按占位符类型（标题/正文/副标题）分组统计字号差。

处理规则：
- 脚本报告的所有问题，修复后需重新跑脚本确认清零。
- 对重叠问题，若重叠≤5% 且视觉无法察觉，可判为误报（需截图复核）。
- 修复后若引入新问题，需重新检测。
- **脚本无报错的页面跳过视觉检查**，仅对脚本报出问题的页面渲染截图做人工复核。

> 脚本依赖 `lxml` 库，若缺失则 `pip install lxml`。

### 视觉检查（仅针对布局检测报出问题的页面）

> **LibreOffice 不可用时的降级**：如果 LibreOffice 安装失败或环境缺失，`detect_layout.py` 仍已完成且无报错，则跳过本节渲染级视觉检查。向用户说明"已完成布局自动检测，未做渲染级视觉检查（LibreOffice 不可用）"，不得宣称完整视觉 QA 已通过。详见 `SKILL.md` 降级规则。

渲染脚本报出问题的页面。

将幻灯片转换为图片（参见[转换为图片](#转换为图片)），然后使用以下提示：

```
视觉检查这些幻灯片。假设存在问题——找到它们。

检查以下方面：
- 元素重叠（文字穿过形状、线条穿过文字、元素堆叠）
- 文本溢出或在边缘/框边界处被截断
- 为单行文本定位的装饰线，但标题换成了两行
- 来源引用或页脚与上方内容冲突
- 元素间距过小（< 0.3" 间隙）或卡片/区域几乎相接
- 间距不均（某处大面积留白，另一处过于紧凑）
- 距幻灯片边缘的边距不足（< 0.5"）
- 列或类似元素未一致对齐
- 低对比度文字（如浅灰色文字在奶油色背景上）
- 低对比度图标（如深色图标在深色背景上且没有对比色圆圈）
- 文本框过窄导致过度换行
- 残留的占位符内容

对每张幻灯片列出问题或关注点，即使是小问题也要列出。

读取并分析这些图片：
1. /path/to/slide-01.jpg（预期：[简要描述]）
2. /path/to/slide-02.jpg（预期：[简要描述]）

报告发现的所有问题，包括轻微问题。
```

### 验证循环

1. 生成幻灯片 → 转换为图片 → 检查
2. **列出发现的问题**（如果没发现问题，用更严格的标准再检查一遍）
3. 修复问题
4. **重新验证受影响的幻灯片**——一个修复往往会引发另一个问题
5. 重复直到完整检查一遍不再发现新问题

**在完成至少一个修复-验证循环之前，不要宣布成功。**

---

### 转换为图片

将演示文稿转换为单独的幻灯片图片以进行视觉检查：

```bash
python scripts/soffice.py --headless --convert-to pdf output.pptx
pdftoppm -jpeg -r 150 output.pdf slide
```

这将创建 `slide-01.jpg`、`slide-02.jpg` 等文件。

修复后重新渲染特定幻灯片：

```bash
pdftoppm -jpeg -r 150 -f N -l N output.pdf slide-fixed
```



---

## 需要避免的常见错误

- **不要重复同一种版式**：跨页面改变栏数、卡片和强调块
- **不要把正文居中**：段落和列表左对齐，只让标题居中
- **不要忽视字号对比**：标题需要 36pt 以上，才能明显区别于 14-16pt 正文
- **不要默认使用蓝色**：根据具体主题选择颜色
- **不要随意混用间距**：选择 0.3" 或 0.5" 的间距，并保持一致
- **不要只设计一页，其他页面保持朴素**：要么整体执行设计，要么全篇保持简洁
- **不要创建纯文本页面**：添加图片、图标、图表或其他视觉元素，避免普通标题 + 项目符号
- **不要忘记文本框 padding**：当线条或形状需要对齐文本边缘时，将文本框 `margin` 设为 0，或按 padding 偏移形状
- **不要使用低对比元素**：图标和文字都需要与背景有足够对比
- **绝不在标题下使用强调线**：这是 AI 生成幻灯片的典型痕迹；改用留白或背景色
- **绝不在十六进制颜色中使用 `#`**：这会导致 PptxGenJS 文件损坏
- **绝不把透明度编码进十六进制字符串**：改用 `opacity` 属性
- **绝不在 `createSlide()` 中使用 async/await**：`compile.js` 不会 await
- **绝不在多个 PptxGenJS 调用间复用 option 对象**：PptxGenJS 会原地修改对象

---

## PptxGenJS 关键陷阱

### 不要在 createSlide() 中使用 async/await

```javascript
// 错误：compile.js 不会 await
async function createSlide(pres, theme) { ... }

// 正确
function createSlide(pres, theme) { ... }
```

### 十六进制颜色不要带 "#"

```javascript
color: "FF0000"      // 正确
color: "#FF0000"     // 会损坏文件
```

### 不要把透明度编码进十六进制字符串

```javascript
shadow: { color: "00000020" }              // 会损坏文件
shadow: { color: "000000", opacity: 0.12 } // 正确
```

### 防止标题换行

```javascript
// 长标题使用 fit:'shrink'
slide.addText("Long Title Here", {
  x: 0.5, y: 2, w: 9, h: 1,
  fontSize: 48, fit: "shrink"
});
```

### 不要跨调用复用 option 对象

```javascript
// 错误
const shadow = { type: "outer", blur: 6, offset: 2, color: "000000", opacity: 0.15 };
slide.addShape(pres.shapes.RECTANGLE, { shadow, ... });
slide.addShape(pres.shapes.RECTANGLE, { shadow, ... });

// 正确：使用工厂函数
const makeShadow = () => ({ type: "outer", blur: 6, offset: 2, color: "000000", opacity: 0.15 });
slide.addShape(pres.shapes.RECTANGLE, { shadow: makeShadow(), ... });
slide.addShape(pres.shapes.RECTANGLE, { shadow: makeShadow(), ... });
```