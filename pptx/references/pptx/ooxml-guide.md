# PowerPoint 的 Office Open XML 技术参考

**重要：开始前请完整阅读本文档。** 文档中包含关键 XML schema 规则和格式要求；实现不正确会生成无效的 PPTX，导致 PowerPoint 无法打开。

## 技术准则

### Schema 合规
- **`<p:txBody>` 中的元素顺序**：`<a:bodyPr>`、`<a:lstStyle>`、`<a:p>`
- **空白字符**：如果 `<a:t>` 元素首尾有空格，添加 `xml:space='preserve'`
- **Unicode**：ASCII 内容中的字符要转义，例如 `"` 写成 `&#8220;`
- **图片**：放入 `ppt/media/`，在 slide XML 中引用，并设置适合页面边界的尺寸
- **Relationships**：每页使用到的资源都要更新到 `ppt/slides/_rels/slideN.xml.rels`
- **Dirty 属性**：在 `<a:rPr>` 和 `<a:endParaRPr>` 元素上添加 `dirty="0"`，表示状态干净

## 演示文稿结构

### 基础幻灯片结构
```xml
<!-- ppt/slides/slide1.xml -->
<p:sld>
  <p:cSld>
    <p:spTree>
      <p:nvGrpSpPr>...</p:nvGrpSpPr>
      <p:grpSpPr>...</p:grpSpPr>
      <!-- 形状放在这里 -->
    </p:spTree>
  </p:cSld>
</p:sld>
```

### 文本框 / 带文本的形状
```xml
<p:sp>
  <p:nvSpPr>
    <p:cNvPr id="2" name="Title"/>
    <p:cNvSpPr>
      <a:spLocks noGrp="1"/>
    </p:cNvSpPr>
    <p:nvPr>
      <p:ph type="ctrTitle"/>
    </p:nvPr>
  </p:nvSpPr>
  <p:spPr>
    <a:xfrm>
      <a:off x="838200" y="365125"/>
      <a:ext cx="7772400" cy="1470025"/>
    </a:xfrm>
  </p:spPr>
  <p:txBody>
    <a:bodyPr/>
    <a:lstStyle/>
    <a:p>
      <a:r>
        <a:t>幻灯片标题</a:t>
      </a:r>
    </a:p>
  </p:txBody>
</p:sp>
```

### 文本格式
```xml
<!-- 加粗 -->
<a:r>
  <a:rPr b="1"/>
  <a:t>加粗文本</a:t>
</a:r>

<!-- 斜体 -->
<a:r>
  <a:rPr i="1"/>
  <a:t>斜体文本</a:t>
</a:r>

<!-- 下划线 -->
<a:r>
  <a:rPr u="sng"/>
  <a:t>带下划线文本</a:t>
</a:r>

<!-- 高亮 -->
<a:r>
  <a:rPr>
    <a:highlight>
      <a:srgbClr val="FFFF00"/>
    </a:highlight>
  </a:rPr>
  <a:t>高亮文本</a:t>
</a:r>

<!-- 字体和字号 -->
<a:r>
  <a:rPr sz="2400" typeface="Arial">
    <a:solidFill>
      <a:srgbClr val="FF0000"/>
    </a:solidFill>
  </a:rPr>
  <a:t>24pt 彩色 Arial 文本</a:t>
</a:r>

<!-- 完整格式示例 -->
<a:r>
  <a:rPr lang="en-US" sz="1400" b="1" dirty="0">
    <a:solidFill>
      <a:srgbClr val="FAFAFA"/>
    </a:solidFill>
  </a:rPr>
  <a:t>已设置格式的文本</a:t>
</a:r>
```

### 列表
```xml
<!-- 项目符号列表 -->
<a:p>
  <a:pPr lvl="0">
    <a:buChar char="•"/>
  </a:pPr>
  <a:r>
    <a:t>第一条项目</a:t>
  </a:r>
</a:p>

<!-- 编号列表 -->
<a:p>
  <a:pPr lvl="0">
    <a:buAutoNum type="arabicPeriod"/>
  </a:pPr>
  <a:r>
    <a:t>第一条编号项目</a:t>
  </a:r>
</a:p>

<!-- 第二层缩进 -->
<a:p>
  <a:pPr lvl="1">
    <a:buChar char="•"/>
  </a:pPr>
  <a:r>
    <a:t>缩进项目</a:t>
  </a:r>
</a:p>
```

### 形状
```xml
<!-- 矩形 -->
<p:sp>
  <p:nvSpPr>
    <p:cNvPr id="3" name="矩形"/>
    <p:cNvSpPr/>
    <p:nvPr/>
  </p:nvSpPr>
  <p:spPr>
    <a:xfrm>
      <a:off x="1000000" y="1000000"/>
      <a:ext cx="3000000" cy="2000000"/>
    </a:xfrm>
    <a:prstGeom prst="rect">
      <a:avLst/>
    </a:prstGeom>
    <a:solidFill>
      <a:srgbClr val="FF0000"/>
    </a:solidFill>
    <a:ln w="25400">
      <a:solidFill>
        <a:srgbClr val="000000"/>
      </a:solidFill>
    </a:ln>
  </p:spPr>
</p:sp>

<!-- 圆角矩形 -->
<p:sp>
  <p:spPr>
    <a:prstGeom prst="roundRect">
      <a:avLst/>
    </a:prstGeom>
  </p:spPr>
</p:sp>

<!-- 圆形 / 椭圆 -->
<p:sp>
  <p:spPr>
    <a:prstGeom prst="ellipse">
      <a:avLst/>
    </a:prstGeom>
  </p:spPr>
</p:sp>
```

### 图片
```xml
<p:pic>
  <p:nvPicPr>
    <p:cNvPr id="4" name="图片">
      <a:hlinkClick r:id="" action="ppaction://media"/>
    </p:cNvPr>
    <p:cNvPicPr>
      <a:picLocks noChangeAspect="1"/>
    </p:cNvPicPr>
    <p:nvPr/>
  </p:nvPicPr>
  <p:blipFill>
    <a:blip r:embed="rId2"/>
    <a:stretch>
      <a:fillRect/>
    </a:stretch>
  </p:blipFill>
  <p:spPr>
    <a:xfrm>
      <a:off x="1000000" y="1000000"/>
      <a:ext cx="3000000" cy="2000000"/>
    </a:xfrm>
    <a:prstGeom prst="rect">
      <a:avLst/>
    </a:prstGeom>
  </p:spPr>
</p:pic>
```

### 表格
```xml
<p:graphicFrame>
  <p:nvGraphicFramePr>
    <p:cNvPr id="5" name="表格"/>
    <p:cNvGraphicFramePr>
      <a:graphicFrameLocks noGrp="1"/>
    </p:cNvGraphicFramePr>
    <p:nvPr/>
  </p:nvGraphicFramePr>
  <p:xfrm>
    <a:off x="1000000" y="1000000"/>
    <a:ext cx="6000000" cy="2000000"/>
  </p:xfrm>
  <a:graphic>
    <a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table">
      <a:tbl>
        <a:tblGrid>
          <a:gridCol w="3000000"/>
          <a:gridCol w="3000000"/>
        </a:tblGrid>
        <a:tr h="500000">
          <a:tc>
            <a:txBody>
              <a:bodyPr/>
              <a:lstStyle/>
              <a:p>
                <a:r>
                  <a:t>单元格 1</a:t>
                </a:r>
              </a:p>
            </a:txBody>
          </a:tc>
          <a:tc>
            <a:txBody>
              <a:bodyPr/>
              <a:lstStyle/>
              <a:p>
                <a:r>
                  <a:t>单元格 2</a:t>
                </a:r>
              </a:p>
            </a:txBody>
          </a:tc>
        </a:tr>
      </a:tbl>
    </a:graphicData>
  </a:graphic>
</p:graphicFrame>
```

### 幻灯片版式

```xml
<!-- 标题页版式 -->
<p:sp>
  <p:nvSpPr>
    <p:nvPr>
      <p:ph type="ctrTitle"/>
    </p:nvPr>
  </p:nvSpPr>
  <!-- 标题内容 -->
</p:sp>

<p:sp>
  <p:nvSpPr>
    <p:nvPr>
      <p:ph type="subTitle" idx="1"/>
    </p:nvPr>
  </p:nvSpPr>
  <!-- 副标题内容 -->
</p:sp>

<!-- 内容页版式 -->
<p:sp>
  <p:nvSpPr>
    <p:nvPr>
      <p:ph type="title"/>
    </p:nvPr>
  </p:nvSpPr>
  <!-- 幻灯片标题 -->
</p:sp>

<p:sp>
  <p:nvSpPr>
    <p:nvPr>
      <p:ph type="body" idx="1"/>
    </p:nvPr>
  </p:nvSpPr>
  <!-- 正文内容 -->
</p:sp>
```

## 文件更新

添加内容时，需要更新以下文件：

**`ppt/_rels/presentation.xml.rels`:**
```xml
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>
```

**`ppt/slides/_rels/slide1.xml.rels`:**
```xml
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image1.png"/>
```

**`[Content_Types].xml`:**
```xml
<Default Extension="png" ContentType="image/png"/>
<Default Extension="jpg" ContentType="image/jpeg"/>
<Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>
```

**`ppt/presentation.xml`:**
```xml
<p:sldIdLst>
  <p:sldId id="256" r:id="rId1"/>
  <p:sldId id="257" r:id="rId2"/>
</p:sldIdLst>
```

**`docProps/app.xml`：** 更新幻灯片数量和统计信息
```xml
<Slides>2</Slides>
<Paragraphs>10</Paragraphs>
<Words>50</Words>
```

## 幻灯片操作

### 添加新幻灯片
在演示文稿末尾添加新幻灯片时：

1. **创建 slide 文件**（`ppt/slides/slideN.xml`）
2. **更新 `[Content_Types].xml`**：为新 slide 添加 Override
3. **更新 `ppt/_rels/presentation.xml.rels`**：为新 slide 添加 relationship
4. **更新 `ppt/presentation.xml`**：向 `<p:sldIdLst>` 添加 slide ID
5. **按需创建 slide relationship 文件**（`ppt/slides/_rels/slideN.xml.rels`）
6. **更新 `docProps/app.xml`**：增加幻灯片数量，并更新统计信息（如果存在）

### 复制幻灯片
1. 复制源 slide XML 文件并使用新文件名
2. 更新新 slide 中的所有 ID，确保唯一
3. 按上方“添加新幻灯片”的步骤更新相关文件
4. **关键**：删除或更新 `_rels` 文件中的 notes slide 引用
5. 移除对未使用媒体文件的引用

### 调整幻灯片顺序
1. **更新 `ppt/presentation.xml`**：重排 `<p:sldIdLst>` 中的 `<p:sldId>` 元素
2. `<p:sldId>` 元素顺序决定幻灯片顺序
3. 保持 slide ID 和 relationship ID 不变

示例：
```xml
<!-- 原始顺序 -->
<p:sldIdLst>
  <p:sldId id="256" r:id="rId2"/>
  <p:sldId id="257" r:id="rId3"/>
  <p:sldId id="258" r:id="rId4"/>
</p:sldIdLst>

<!-- 将第 3 页移动到第 2 位后 -->
<p:sldIdLst>
  <p:sldId id="256" r:id="rId2"/>
  <p:sldId id="258" r:id="rId4"/>
  <p:sldId id="257" r:id="rId3"/>
</p:sldIdLst>
```

### 删除幻灯片
1. **从 `ppt/presentation.xml` 移除**：删除对应的 `<p:sldId>` 条目
2. **从 `ppt/_rels/presentation.xml.rels` 移除**：删除对应 relationship
3. **从 `[Content_Types].xml` 移除**：删除对应 Override 条目
4. **删除文件**：移除 `ppt/slides/slideN.xml` 和 `ppt/slides/_rels/slideN.xml.rels`
5. **更新 `docProps/app.xml`**：减少幻灯片数量并更新统计信息
6. **清理未使用媒体**：从 `ppt/media/` 移除孤立图片

注意：不要重新编号剩余 slide，保留它们原本的 ID 和文件名。


## 常见错误

- **编码**：ASCII 内容中的 unicode 字符要转义，例如 `"` 写成 `&#8220;`
- **图片**：放入 `ppt/media/`，并更新 relationship 文件
- **列表**：列表标题不要带项目符号
- **ID**：UUID 使用合法的十六进制值
- **主题**：检查 `theme` 目录下所有主题文件的颜色

## 基于模板演示文稿的校验清单

### 打包前始终检查：
- **清理未使用资源**：删除未被引用的媒体、字体和 notes 目录
- **修正 Content_Types.xml**：声明包内存在的所有 slides、layouts 和 themes
- **修正 relationship ID**：
   - 如果没有使用嵌入字体，移除字体嵌入引用
- **移除断裂引用**：检查所有 `_rels` 文件，确认没有引用已删除资源

### 复制模板时常见问题：
- 复制后多页引用同一个 notes slide
- 保留了已经不存在的模板页图片/媒体引用
- 没有包含字体文件却保留字体嵌入引用
- layouts 12-25 缺少 slideLayout 声明
- `docProps` 目录可能不会被解包，这是可选内容

## 组形状坐标系

PPT 中的 `<p:grpSp>`（组形状）包含自己的坐标系。理解这一点对精确编辑甘特图等嵌套结构至关重要。

### 坐标变换原理

```xml
<p:grpSp>
  <p:grpSpPr>
    <a:xfrm>
      <!-- 父坐标系：组的实际位置和大小（相对于slide） -->
      <a:off x="432846" y="2345316"/>    <!-- 组的左上角在slide上的位置 -->
      <a:ext cx="11326308" cy="4200668"/> <!-- 组的实际宽高 -->
      <!-- 子坐标系：子shape使用的坐标范围 -->
      <a:chOff x="454017" y="2396975"/>  <!-- 子坐标原点（通常接近off） -->
      <a:chExt cx="10388794" cy="4200668"/> <!-- 子坐标系的宽高范围 -->
    </a:xfrm>
  </p:grpSpPr>
  <!-- 子shape的坐标是相对于chOff/chExt的 -->
  <p:sp>...</p:sp>
</p:grpSp>
```

### 关键规则

1. **子shape的 `(x, y)` 是组内局部坐标**，不是幻灯片绝对坐标
2. **幻灯片绝对坐标** = `off` + `(child_x - chOff)` × `(ext / chExt)`
   - 简化版（当 `off ≈ chOff` 且 `ext ≈ chExt` 时）：绝对坐标 ≈ off + child_x - chOff
3. **python-pptx 的 `shape.left/top` 返回的是组内局部坐标**，不是slide绝对坐标
4. **inventory_workflow.py 报告的 overflow 是基于局部坐标的**，对于group内的shape可能不准确

### 实战建议

- 编辑甘特图时，如果需要让浮动shape精确对齐到表格行，直接在XML中操作坐标（使用OOXML workflow）
- 浮动shape的 `y` 坐标应与对应表格行的 `y` 坐标匹配（考虑行高和垂直偏移）
- 浮动shape的 `x` 和 `cx`（宽度）应根据任务对应的列范围计算

## 从模板中提取品牌图片

当需要从参考模板中提取Logo、背景图等品牌元素用于新PPT时，按以下流程操作：

### 步骤 1：解包模板

```bash
python ooxml/scripts/unpack_workflow.py template.pptx template-unpacked
```

### 步骤 2：列出并识别媒体文件

```bash
ls -la template-unpacked/ppt/media/
```

### 步骤 3：在 XML 中定位图片引用

图片可能在以下位置：
- `ppt/slides/slideN.xml` — 幻灯片中的图片
- `ppt/slideMasters/slideMasterN.xml` — 母版中的背景/Logo
- `ppt/slideLayouts/slideLayoutN.xml` — 版式中的装饰元素

```bash
# 查找所有图片引用（r:embed="rIdX" 指向图片）
grep -r 'r:embed.*image' template-unpacked/ppt/slides/
grep -r 'r:embed.*image' template-unpacked/ppt/slideMasters/
grep -r 'r:embed.*image' template-unpacked/ppt/slideLayouts/

# 查找图片的具体位置和尺寸
# 图片以 <p:pic> 元素存在，其中 <a:off> 是位置，<a:ext> 是尺寸
grep -A5 '<p:pic>' template-unpacked/ppt/slides/slide1.xml
```

### 步骤 4：从 relationship 文件确定图片文件名

图片引用通过relationship ID（如 `rId2`）映射到实际文件：

```bash
# 查看幻灯片的relationship文件
cat template-unpacked/ppt/slides/_rels/slide1.xml.rels
```

输出示例：
```xml
<Relationship Id="rId1" Type="...slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
<Relationship Id="rId2" Type="...image" Target="../media/image1.png"/>
<Relationship Id="rId3" Type="...image" Target="../media/image2.png"/>
```

### 步骤 5：提取图片位置和尺寸

从slide XML中提取图片的精确位置（用于在新PPT中复用）：

```xml
<!-- 图片在 <p:pic> 元素中 -->
<p:pic>
  <p:spPr>
    <a:xfrm>
      <a:off x="914400" y="228600"/>   <!-- 位置：x=1.0in, y=0.25in -->
      <a:ext cx="1005840" cy="480060"/> <!-- 尺寸：w=1.1in, h=0.525in -->
    </a:xfrm>
  </p:spPr>
  <p:blipFill>
    <a:blip r:embed="rId2"/>           <!-- 指向 image1.png -->
  </p:blipFill>
</p:pic>
```

### 步骤 6：在新 PPT 中复用

将提取的图片复制到工作目录，使用PptxGenJS添加：

```javascript
// 将提取的图片添加到新PPT的每页
slide.addImage({
    path: 'template-unpacked/ppt/media/image1.png',
    x: 1.0,     // 与模板相同的位置（英寸）
    y: 0.25,
    w: 1.1,     // 与模板相同的尺寸
    h: 0.525
});
```

### 注意事项

- **透明背景的Logo**（PNG格式）可以直接复用
- **JPEG背景图**可能有白色背景，注意与新PPT背景色的配合
- **母版中的背景图**通常通过 `<p:bg>` 元素引用，不要与幻灯片中的图片混淆
- 如果模板母版定义了背景色/渐变，需要在新 PPT 中通过 `slide.background` 属性设置
- **图片的层叠顺序很重要**：背景图应最先添加（底层），Logo 应在内容之上
