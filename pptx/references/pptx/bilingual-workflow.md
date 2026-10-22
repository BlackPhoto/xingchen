# PPT 双语专项工作流

> 仅在用户明确要求中英双语、bilingual 或添加英文翻译时启用。普通单语 PPT 禁止读取本文档、运行 `scripts/bilingual/` 或应用本流程的布局规则。

## 隔离边界

- 双语分析、规划、写入和专项校验只使用 `scripts/bilingual/`。
- 不修改通用生成器、模板系统、`detect_layout.py` 或普通 PPT 的 QA 行为。
- 不得仅因 PPT 同时出现中文和英文术语而触发本流程。
- 所有脚本以输入 PPTX 为只读源，输出到新文件；不得覆盖原稿。
- 本流程只使用 PowerPoint 原生文本框、形状、图片、表格和图表进行布局重写；不得调用 SVG 模板、整页 SVG 或图片化页面作为版式替代。

## 内容锁（硬约束）

- 原中文、数字、表格单元格、图表数据、内容图片、来源说明和演讲者备注必须保留。
- 允许改变对象坐标、尺寸、层级、文本换行和视觉样式；不得改写、摘要、删除或合并原内容。
- 默认保持页数和内容所属页面不变。单页无法容纳时，规划必须失败并把拆页作为需用户确认的候选，不得自动拆页。
- `analyze_bilingual_layout.py` 生成 `content_inventory`；`plan_bilingual.py` 将其写入操作计划；`apply_bilingual.py` 写入前、`validate_bilingual.py` 交付前均执行内容守恒检查。

## 输出背景优化

- 源 PPT 只读；背景优化只发生在新生成的 PPTX 中。
- 分析器将小尺寸、承担信息表达的图片标为 `content-picture` 并纳入内容锁；将底层满版图片标为 `background-picture`，将底层大色块标为 `background-shape`。
- 背景策略支持 `keep`、`simplify`、`restyle`、`replace`。后三种只能作用于 manifest 中列出的背景对象。
- 优化背景使用 PowerPoint 原生幻灯片背景和原生形状，不使用 SVG 或整页图片化方案。
- Logo、产品截图、人物照片、图表截图等内容图片不得因靠近页面边缘或面积较大而自动当作背景；低置信度时按内容图片保护，并回退到模型判断。

## 双语写入模式

### `inline`：同框双段落（默认）

在中文文本框的 `txBody` 中追加一个合法 `<a:p>` 英文段落。适用于标题、正文、卡片标题、说明和紧凑布局。保留中文段落格式；英文段落默认 Arial、灰色 `888888`、不生成重复项目符号。

### `separate`：独立英文框

保留中文框，新增独立英文框。适用于目录、需要独立对齐的标签或页面空间明确充足的场景。英文框名称固定为 `BilingualEN_s{slide}_id{shape_id}`。

两种模式共同禁止：

- 在 `<a:t>` 中写入 `\n`、`\r`、`&#10;` 或 `&#13;`。
- 使用空白 run 或字符串拼接模拟换行。
- 临时脚本直接遍历、修改 `slide*.xml`。

## 原生布局重排

双语内容导致空间不足时，先识别页面版式，再明确规划对象移动和尺寸变化。不得把页面与全部对象统一缩放后视为完成重排。

1. 先运行只读分析：

   `python scripts/bilingual/analyze_bilingual_layout.py input.pptx layout_manifest.json`

2. `layout_manifest.json` 中的几何坐标统一为 slide 坐标，并保留 `local_box_in`、`group_path` 和 `transform_supported`。旋转或翻转 group 的 `transform_supported=false`，自动规划必须回退。
3. 每页读取 `layout_health.score`、`issues`、`slide_type` 和 `recommended_strategy`，再选择：
   - `preserve`：原布局健康，只为英文增加空间并微调。
   - `reflow`：局部重排，调整对齐、间距、分栏、容器和下游对象。
   - `rebuild`：源布局存在越界、多个内容碰撞或无法容纳双语，使用原生对象重新建立整页网格。
   - `layout_health` 中的 `bilingual_collision_risk` 预测了双语写入后的碰撞数。`bilingual_collision_risk >= 3` 时分析器自动推荐 `rebuild`；`>= 1` 时推荐 `reflow`。优先采纳该预测值，不要在已预判碰撞的页面上逐框微调坐标。
4. `rebuild` 必须为该页每个内容锁对象提供 `layout_edits` 或对应翻译 entry；规划不完整时禁止执行。
5. 内容密集页面可改成双栏、三栏、列表、时间轴或 2×2，但版式选择必须服从内容容量。
6. 文本框增高时，必须同步调整所属容器和下游对象；不得靠碰撞豁免掩盖问题。
7. 仅允许删除被分析器明确识别为无内容装饰的对象。正文、标题、图片、表格、图表、Logo 和带文字对象受内容锁保护。
8. `plan_bilingual.py` 规划失败时，若 stderr 中出现 `STRATEGY_UPGRADE: slide N: ... Consider upgrading to rebuild`，必须将该页策略升级为 `rebuild` 并为该页全部内容锁对象重新生成完整 `layout_edits`，不得继续在旧策略下逐框修正坐标。单页碰撞/越界报错累计 >= 3 条时同样适用此规则。

## 规划 JSON

```json
{
  "slide_size": {"width_in": 13.333, "height_in": 7.5},
  "slide_strategies": {"3": "rebuild"},
  "background_edits": [
    {"slide": 3, "action": "replace", "fill_color": "F5F7FA"}
  ],
  "layout_edits": [
    {
      "slide": 3,
      "shape_id": 4,
      "action": "move_resize",
      "target": {"left_in": 6.7, "top_in": 0.9, "width_in": 6.0, "height_in": 4.8}
    }
  ],
  "entries": [
    {
      "slide": 3,
      "shape_id": 7,
      "english": "An Agent is...",
      "mode": "inline",
      "font_name": "Arial",
      "font_size_pt": 9,
      "color": "888888",
      "gap_pt": 2,
      "target": {"left_in": 0.6, "top_in": 1.5, "width_in": 5.5, "height_in": 1.0}
    }
  ]
}
```

### `layout_edits`

- `move_resize`：移动或调整现有对象；`target` 可只提供需要改变的字段。
- `delete`：仅删除无内容装饰对象；内容锁对象会被规划器拒绝。
- `bring_to_front`：将对象移动到同一父级的最前层。
- `send_to_back`：将现有对象移到同一父级底层。
- `set_style`：可修改填充、线条、字体、字号、字色、粗斜体、对齐和文本框边距；不得修改文字内容。
- `add_shape`：新增矩形或圆角矩形容器；需提供 `target`，可设置 `shape_kind`、填充、线条和 `z_order: "back"`。新增容器只用于双语重排，不得覆盖未规划的原内容。

### `background_edits`

- `keep`：保留输出页的源背景。
- `simplify`：删除已识别的背景图片/背景形状，并设置简洁的原生纯色背景。
- `restyle`：重配背景形状颜色；背景图片会替换为原生纯色背景。
- `replace`：删除已识别的背景对象并设置新的原生背景。
- `fill_color` 使用六位 RGB。可选 `shape_ids` 只能引用 `content_inventory.slides[].backgrounds` 中的对象；内容图片 ID 会被拒绝。

### `entries`

- `slide`、`shape_id`、`english` 必填。
- `mode` 默认 `inline`。
- `target` 是目标文本框，不是相对增量。进行版式重排时必须明确提供。
- `inline` 的显式目标高度必须满足保守的最小高度估算；显式提供 `height_in` 不会跳过校验。
- `separate` 可用 `container_shape_id` 声明所属背景容器；仅当几何包含关系成立时才自动识别容器。
- `ignore_shape_ids` 仅用于已确认的背景、装饰、容器或水印，并必须提供非空 `ignore_reason`。正文、标题、标签和页码默认不可忽略；plan 会结合 manifest 交叉验证。

## 可选候选布局规划器

`layout_planner.py` 当前只处理高置信度、无旋转/翻转变换的卡片网格，并只输出 `reflow`。它不是完整重建器；manifest 推荐 `rebuild`、不能识别或无法容纳时，必须回退到模型规划，为该页全部内容锁对象生成完整的原生 `layout_edits`。

1. 先准备只含翻译内容和样式要求的 `bilingual_content.json`，其中每个 entry 至少包含 `slide`、`shape_id` 和 `english`。
2. 生成候选方案：

   `python scripts/bilingual/layout_planner.py layout_manifest.json bilingual_content.json translations.json`

3. 返回非 0、置信度不足或存在 `failure_reason` 时，不得自动应用；改为手工生成 `layout_edits + entries`。

## 固定执行顺序

1. 按 `edit-workflow.md` 完成结构分析和内容映射。
2. 运行 `analyze_bilingual_layout.py`，生成只读对象清单。
3. 根据输出设计决定每页 `background_edits`；对高置信度卡片页可运行 `layout_planner.py`，其他页面直接生成包含 `background_edits`、`layout_edits` 与 `entries` 的 UTF-8 JSON。
4. 规划：`python scripts/bilingual/plan_bilingual.py input.pptx translations.json bilingual_ops.json --manifest layout_manifest.json`
5. 规划失败时修正目标坐标、容器关系或版式；不得绕过错误。若 stderr 出现 `STRATEGY_UPGRADE` 提示，按上节第8条升级策略后重新规划，不要在同一策略下反复调坐标。
6. 写入新文件：`python scripts/bilingual/apply_bilingual.py input.pptx bilingual_ops.json output.pptx`
7. 专项校验：`python scripts/bilingual/validate_bilingual.py output.pptx --plan bilingual_ops.json --source input.pptx`
8. 布局自动检测：`python scripts/detect_layout.py output.pptx`；修复后重跑确认。
9. 每次修改输出后都重新执行步骤 7、8，并基于最终 PPTX 渲染全部页面；不得继承上一版本的“干净”结论或跳过页面。
10. 面向 PowerPoint/WPS 时在目标环境打开验收。

禁止上游脚本用 clamp/截断坐标或压扁高度来生成可通过边界检查的畸形目标框。禁止把真实内容批量加入 `ignore_shape_ids`。自动规划不得处理 `transform_supported=false` 的对象。
禁止在双语原生重排中调用 `scripts/svg/`、`svg-templates/` 或 `references/pptx-svg/`。

## 字体与空间规则

- 英文字号按文本角色确定，不使用单一比例：页面标题通常为中文的 50%–70%，正文通常为 80%–90%。
- 英文正文默认不得低于 8pt；空间不足时优先调整版式、容器和文案。
- 独立英文框启用自动换行、禁用自动缩放、边距为 0。
- 页码、编号、水印、品牌名和无需翻译的专有名词不得自动添加英文。
- 同框英文段落不得复制中文项目符号，但应继承对齐、缩进等段落结构。

## 专项门禁

- `validate_bilingual.py` 非 0：禁止交付。
- 内容守恒检查出现任何原文、表格、图表、内容图片或备注变化：禁止交付；经规划允许变化的背景不参与内容一致性比较。
- `detect_layout.py` 报出的非预期问题必须修复并重跑。
- 视觉检查为必做项；LibreOffice 不可用时只能声明完成自动布局检测，不能声称完整视觉 QA 通过。
- QA 渲染必须基于最终 PPTX 重新生成。

## 与普通 PPT 的隔离

普通 PPT 不读取本文档，不运行 `scripts/bilingual/`，不执行双语专项校验。双语流程的任何失败不得改变普通 PPT 的创建、编辑或 QA 路径。