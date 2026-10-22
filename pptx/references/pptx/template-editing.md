# 编辑已有演示文稿

## 基于模板的工作流

使用已有演示文稿作为模板时：

1. **复制并分析**：
   ```bash
   cp /path/to/user-provided.pptx template.pptx
   python -m markitdown template.pptx > template.md
   ```
   查看 `template.md`，了解占位文本和幻灯片结构。

2. **规划页面映射**：为每一段内容选择一页模板。

   **使用多样化版式**。单调的演示文稿是常见失败模式。不要默认使用“标题 + 项目符号”的基础页，应主动寻找：
   - 多栏布局（两栏、三栏）
   - 图片 + 文本组合
   - 全幅图片叠加文本
   - 引用页或强调说明页
   - 章节分隔页
   - 统计数字强调页
   - 图标网格，或图标 + 文本行

   **避免：** 每一页都重复同一种文字密集版式。

   让内容类型匹配版式风格，例如：关键点对应项目符号页，团队信息对应多栏页，用户评价对应引用页。

3. **解包**：使用 Python 的 `zipfile` 模块把 PPTX 解成可编辑的 XML 树。为了便于阅读，对 XML 做 pretty-print。

4. **搭出演示文稿结构**（这一步自己完成，不交给 subagent）：
   - 删除不需要的幻灯片（从 `<p:sldIdLst>` 移除）
   - 复制需要复用的幻灯片（复制 slide XML、relationships，并更新 `Content_Types.xml` 和 `presentation.xml`）
   - 在 `<p:sldIdLst>` 中重排幻灯片
   - **第 5 步前必须完成全部结构调整**

5. **编辑内容**：更新每个 `slide{N}.xml` 中的文本。
   **如果可用，这一步可以使用 subagent**，因为每页是独立 XML 文件，可以并行编辑。

6. **清理**：移除孤立文件，包括不在 `<p:sldIdLst>` 中的 slide、未引用媒体、孤立 rels。

7. **打包**：把 XML 树重新打包为 PPTX。执行校验、修复、XML 压缩，并重新编码智能引号。

   始终先写入 `/tmp/`，再复制到最终路径。Python 的 `zipfile` 模块内部会使用 `seek`，在某些卷挂载场景（例如 Docker bind mount）会失败；先写本地临时路径可以避开这个问题。

## 输出结构

把用户提供的文件复制为当前工作目录下的 `template.pptx`。这样既保留原文件，又给后续步骤提供稳定文件名。

```bash
cp /path/to/user-provided.pptx template.pptx
```

```text
./
├── template.pptx               # 用户提供文件的副本，不直接修改
├── template.md                 # markitdown 提取结果
├── unpacked/                   # 可编辑 XML 树
└── edited.pptx                 # 最终重新打包的演示文稿
```

最低交付物：`edited.pptx`。

## 幻灯片操作

幻灯片顺序位于 `ppt/presentation.xml` -> `<p:sldIdLst>`。

**重排**：调整 `<p:sldId>` 元素顺序。

**删除**：移除 `<p:sldId>`，然后清理孤立文件。

**添加**：复制源 slide 的 XML 文件及其 `.rels` 文件，并更新 `Content_Types.xml` 和 `presentation.xml`。不要只手动复制 slide 文件而不更新引用；这样会造成 notes 引用断裂或 relationship ID 缺失。

## 编辑内容

**Subagent：** 如果可用，在完成第 4 步后可在这里使用。每页都是单独 XML 文件，因此 subagent 可以并行编辑。在给 subagent 的提示中包含：
- 要编辑的 slide 文件路径
- **“所有改动都使用 Edit 工具”**
- 下方的格式规则和常见问题

对每一页：
1. 读取该页 XML
2. 识别全部占位内容，包括文本、图片、图表、图标、说明文字
3. 把每个占位内容替换为最终内容

**使用 Edit 工具，不使用 sed 或 Python 脚本。** Edit 工具会迫使替换位置和替换内容更明确，可靠性更高。

## 格式规则

- **所有标题、副标题和行内标签都加粗**：在 `<a:rPr>` 上使用 `b="1"`。包括：
  - 幻灯片标题
  - 页内小节标题
  - 行首的行内标签，例如 `"Status:"`、`"Description:"`
- **不要使用 unicode 项目符号**：用 `<a:buChar>` 或 `<a:buAutoNum>` 的正规列表格式
- **保持项目符号一致**：让项目符号从 layout 继承。只在必要时指定 `<a:buChar>` 或 `<a:buNone>`。

## 常见问题：模板编辑

### 模板适配

当源内容条目少于模板占位数量时：
- **完整删除多余元素**（图片、形状、文本框），不要只是清空文本
- 清空文本后检查是否留下孤立视觉元素
- 用 `markitdown` 做内容 QA，捕捉数量不匹配

当替换文本长度与原文本不同：
- **更短的替换**：通常安全
- **更长的替换**：可能溢出或发生意外换行
- 改完文本后用 `markitdown` 校验
- 必要时截短或拆分内容，以适配模板的设计约束

**模板槽位 != 源内容条目**：如果模板有 4 个团队成员，而源内容只有 3 个用户，要删除第 4 个成员的整个组（图片 + 文本框），不要只删文字。

### 多条目内容

如果源内容包含多条项目（编号列表、多个小节），每一条都创建单独的 `<a:p>` 元素，**不要拼接成一个字符串**。

**错误**：所有条目塞在同一个段落里：
```xml
<a:p>
  <a:r><a:rPr .../><a:t>Step 1: Do the first thing. Step 2: Do the second thing.</a:t></a:r>
</a:p>
```

**正确**：用独立段落和加粗标题：
```xml
<a:p>
  <a:pPr algn="l"><a:lnSpc><a:spcPts val="3919"/></a:lnSpc></a:pPr>
  <a:r><a:rPr lang="en-US" sz="2799" b="1" .../><a:t>Step 1</a:t></a:r>
</a:p>
<a:p>
  <a:pPr algn="l"><a:lnSpc><a:spcPts val="3919"/></a:lnSpc></a:pPr>
  <a:r><a:rPr lang="en-US" sz="2799" .../><a:t>Do the first thing.</a:t></a:r>
</a:p>
<a:p>
  <a:pPr algn="l"><a:lnSpc><a:spcPts val="3919"/></a:lnSpc></a:pPr>
  <a:r><a:rPr lang="en-US" sz="2799" b="1" .../><a:t>Step 2</a:t></a:r>
</a:p>
<!-- 按相同模式继续 -->
```

从原段落复制 `<a:pPr>` 以保留行距。标题 run 使用 `b="1"`。

### 智能引号

Edit 工具会把智能引号转换成 ASCII。**添加带引号的新文本时，使用 XML entity：**

```xml
<a:t>the &#x201C;Agreement&#x201D;</a:t>
```

| 字符 | 名称 | Unicode | XML Entity |
|-----------|------|---------|------------|
| \u201c | 左双引号 | U+201C | `&#x201C;` |
| \u201d | 右双引号 | U+201D | `&#x201D;` |
| \u2018 | 左单引号 | U+2018 | `&#x2018;` |
| \u2019 | 右单引号 | U+2019 | `&#x2019;` |

### 其他

- **空白**：如果 `<a:t>` 首尾有空格，使用 `xml:space="preserve"`
- **XML 解析**：使用 `defusedxml.minidom`，不要使用 `xml.etree.ElementTree`，后者会破坏 namespace
