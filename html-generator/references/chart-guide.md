# SVG 图表生成规范（强制参考）

生成含 SVG 图表的 HTML 时**必须读取本文档**。SVG 圆弧坐标必须用程序计算后写入，禁止手写坐标值。

---

## 一、饼图（Pie Chart）

### 1. 计算公式

从 12 点钟方向顺时针绘制，圆心 `(cx, cy)`，半径 `r`：

```python
import math

# 圆心与半径
cx, cy, r = 110, 110, 90

# 数据：[(标签, 百分比, 颜色), ...]
data = [
    ("天猫", 34, "#3b82f6"),
    ("京东", 27, "#4f8ef7"),
    ("抖音", 18, "#60a5fa"),
    ("拼多多", 12, "#93c5fd"),
    ("小红书", 6, "#dbe7f6"),
    ("其他", 3, "#e8f0fe"),
]

paths = []
cumulative = 0  # 累计角度（度）
for label, pct, color in data:
    start_angle = cumulative / 100 * 360
    end_angle = (cumulative + pct) / 100 * 360
    sweep = end_angle - start_angle

    # 关键公式：从 12 点钟顺时针
    #   x = cx + r * sin(angle)
    #   y = cy - r * cos(angle)
    sx = cx + r * math.sin(math.radians(start_angle))
    sy = cy - r * math.cos(math.radians(start_angle))
    ex = cx + r * math.sin(math.radians(end_angle))
    ey = cy - r * math.cos(math.radians(end_angle))

    # large-arc-flag: sweep > 180° 时为 1，否则为 0
    large_arc = 1 if sweep > 180 else 0

    d = f"M{cx},{cy} L{sx:.1f},{sy:.1f} A{r},{r} 0 {large_arc},1 {ex:.1f},{ey:.1f} Z"
    paths.append({"label": label, "pct": pct, "color": color, "d": d})
    cumulative += pct
```

### 2. 常见错误

| 错误 | 后果 | 原因 |
|---|---|---|
| 手写坐标值 | 扇形面积与数据不符 | 未用公式计算，凭感觉填值 |
| `large-arc-flag` 算错 | 扇形画了大弧而非小弧（面积放大或缩小） | sweep > 180° 时应为 1，< 180° 时应为 0 |
| 起止点不连续 | 扇形之间出现缝隙或重叠 | 前一个扇形的终点 != 后一个扇形的起点 |
| 颜色不一致 | path fill 与图例 swatch 色值不同 | 颜色手写了两遍，没统一管理 |

### 3. 标准 HTML 模板

```html
<div class="card">
  <h3>各渠道 GMV 占比（饼图）</h3>
  <svg viewBox="0 0 220 220" xmlns="http://www.w3.org/2000/svg"
       role="img" aria-label="渠道占比饼图"
       style="width:100%;max-width:240px;margin:0 auto;display:block;">
    <!-- 底圆（占位底色） -->
    <circle cx="110" cy="110" r="90" fill="#f0f4fa"/>
    <!-- 各扇形 path（坐标由 Python 计算） -->
    <path d="M110,110 L110.0,20.0 A90,90 0 0,1 186.0,158.2 Z" fill="#3b82f6"/>
    <path d="M110,110 L186.0,158.2 A90,90 0 0,1 52.6,179.3 Z" fill="#4f8ef7"/>
    <!-- ... 更多 path ... -->
    <!-- 白色描边圆 -->
    <circle cx="110" cy="110" r="90" fill="none" stroke="#ffffff" stroke-width="2"/>
  </svg>
  <!-- 图例：swatch 颜色必须与对应 path fill 完全一致 -->
  <div class="legend-list" data-layout="list">
    <div class="legend-item"><span class="swatch" style="background:#3b82f6;"></span>天猫<span class="pct">34%</span><span class="val">¥974万</span></div>
    <!-- ... 更多图例项 ... -->
  </div>
</div>
```

### 4. 颜色统一管理要求

**path fill 和 legend swatch 必须引用同一份颜色数组，禁止分别手写。** 在生成 HTML 时，颜色只在 Python 数据数组中定义一次，path 和 legend 都从该数组取值。

---

## 二、环形图（Donut Chart）

### 1. 与饼图的差异

环形图 = 饼图 + 中心白色圆遮罩。path 计算公式与饼图完全相同，只是多加一个白色 `<circle>` 作为中心孔：

```html
<!-- path 部分与饼图完全相同 -->
<svg viewBox="0 0 220 220" ...>
  <circle cx="110" cy="110" r="90" fill="#f0f4fc"/>
  <path d="..." fill="#3b82f6"/>
  <!-- ... 更多 path ... -->
  <!-- 中心白色圆（环形孔） -->
  <circle cx="110" cy="110" r="55" fill="#ffffff"/>
  <!-- 中心文字 -->
  <text x="110" y="106" text-anchor="middle" font-size="17" font-weight="800" fill="#0f1e33">41%</text>
  <text x="110" y="126" text-anchor="middle" font-size="10" fill="#5b6b80">天猫占订单</text>
</svg>
```

### 2. 尺寸要求

环形图的 `max-width` 不应过小（不低于 160px），否则截图视觉检查时细节不可辨识。

---

## 三、柱状图/条形图（Bar Chart）

柱状图使用 CSS flexbox 实现（非 SVG），规范见 `design-system.md` 的「图表组件规范」章节。核心要求：

- 组件类 `.chart-row` / `.bar` / `.chart-labels` / `.stat-inline` 必须定义为独立通用类
- **条形数 = 标签数 = 数据项数**，三者一一对应
- 每个条形的 `height` 百分比 = 该项数值 / 最大数值 * 100%

---

## 四、其他 SVG 图表类型

遇到饼图/环形图/柱状图以外的图表类型（如折线图、面积图、雷达图、散点图等）：

1. 优先用 Python 计算所有坐标点，禁止手写
2. 生成后必须截图 + 视觉模型检查形状完整性
3. 运行 `chart_validator.py` 校验（已实现的校验类型会自动检查，未覆盖类型会提示"该类型尚未实现，请依赖视觉检查"）

### 已覆盖的校验类型

| 图表类型 | 校验内容 |
|---|---|
| 折线图 | 数据点数=标签数、坐标在 viewBox 范围内、多线数据点数一致、每条线至少 2 个点 |
| 面积图 | path 闭合性（Z 命令）、坐标在 viewBox 范围内、数据点与标签对应、多面积数据点数一致 |
| 雷达图 | 顶点数=维度数、多边形闭合、轴角度均匀分布（360°/N）、多形状顶点数一致 |
| 散点图 | 散点数=标签数、坐标在 viewBox 范围内、半径可见（r≥1） |

---

## 五、生成后强制校验

生成含 SVG 图表的 HTML 后，必须运行校验脚本：

```bash
python scripts/chart_validator.py {html文件} --json
```

校验不通过时，根据报告中的具体 issue 修复 HTML（重新用 Python 计算坐标），修复后重新校验，通过后方可交付。
