---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: '44deb9c1-8b8a-45a4-8f55-bb51f4f87e1d'
  PropagateID: '44deb9c1-8b8a-45a4-8f55-bb51f4f87e1d'
  ReservedCode1: '1909ed75-97a7-41b2-9cd5-de03f1d43f41'
  ReservedCode2: '1909ed75-97a7-41b2-9cd5-de03f1d43f41'
---

# html2pptx — HTML 幻灯片 → 原生 PPTX 转换引擎

将 HTML 幻灯片转换为**原生 PPTX**：文本框、形状、连接线、表格、图片、渐变、阴影、
线端箭头——全部为可直接编辑的 PPT 对象，**不使用整页截图**。

保真策略：由无头浏览器实测真实布局（元素几何、计算样式、逐字符文本行盒），
再 1:1 映射为 OOXML；浏览器侧无法原生映射的内容（canvas、iframe、旋转卡片、
SVG 透明渐变、data-uri SVG 背景等）自动降级为**精准区域的截图裁剪**，保证内容
不丢失，并在转换报告中标注。

## 转换流水线

```
html2pptx.py  一条命令完成：
  1. 启动无头 Edge/Chrome（CDP，端口被占自动递增，用完按 PID 精确回收）
  2. 加载 HTML（load 事件 + fonts.ready + 图片解码 + 双 rAF 就绪后才采集；
     加载失败自动重试，仍失败放红色占位页并继续）
  3. 注入执行 extract.js —— 浏览器内实测：
       每个元素的几何 / 计算样式 / 行内结构（含伪元素、SVG、表格、图片）
       文本按逐字符 Range 聚类成视觉行盒（schema 2）
       不可原生映射的内容打 fallback 标记
  4. Python 侧 build_slide —— 1:1 映射为原生 PPTX 形状：
       文本 = 逐行文本框（行宽按标定因子微缩）
       SVG 直线/两点路径 = 原生连接线；marker-end = 原生线端箭头
       fallback 元素 = 页面截图按 rect 裁剪贴图
  5. 存盘（失败页放占位符，deck 始终完整保存）
     + 输出 report.json：逐页降级(warned)/丢失(dropped)清单及 DOM 路径
```

单文件多页 deck（`<script type="text/html" id="slide-N">` 内嵌块）自动按文档
顺序拆分为多页。

## 用法

```bash
# 输入：单文件 / 多文件 / 目录(其中 slide_*.html) / 内嵌多页 deck，均可
python html2pptx.py <页面.html | slides_dir> -o out.pptx

# 可选参数
--dump DIR        每页提取 JSON 落盘（排查用）
--profile JSON    覆盖启发式常数 / 字体映射 / 标定数据路径（见 h2p_config.py）
--text-mode line  文本模式：line=逐行实测(默认) / flow=旧版整段估算(回退)
--port N          CDP 端口（默认 9223，被占自动递增）
--spacing         输出字距（LibreOffice 预览对 spc 有丢字 bug，默认关闭）

# 输出
out.pptx                    转换结果
out.pptx.report.json        逐页转换报告（人工验收的的第一入口）
```

依赖：`pip install python-pptx pillow websocket-client`；本机需 Edge 或 Chrome
（路径自动探测，适配 Windows / macOS / Linux）。LibreOffice 仅标定/QA 渲染需要，转换本身不需要。

## 文件

| 文件 | 作用 |
|------|------|
| `html2pptx.py` | 转换引擎（CDP 驱动 + PPTX 映射 + 逐页容错 + 报告） |
| `extract.js` | 浏览器端采集（几何/样式/视觉行盒/伪元素/SVG/表格/fallback 标记） |
| `h2p_config.py` | 配置唯一来源：启发式常数 + 字体映射 + 实测标定数据管理（全字段用途注释） |
| `TestCase/` | 标定与回归工具链，见下 |

## TestCase/ — 标定与回归

| 文件 | 作用 |
|------|------|
| `CALIBRATION.md` | **标定工作流文档（先读这个）** |
| `calibrate_all.py` | 标定一键入口：宽度 / 垂直 / 阴影三项（可单跑） |
| `measure.py` | 宽度标定 → `font_metrics.json`（浏览器 advance 宽 vs LO 墨迹宽） |
| `vcalib.py` | 垂直标定（徽章数字居中 / bullet 对齐，px 级偏差报告） |
| `shadow_calib.py` | 阴影标定（LO/browser 浓度比，逐条带） |
| `font_metrics.json` | 实测字体宽度因子（引擎启动时读取，measure.py 再生） |
| `bench.py` + `bench_pages.py` + `chart_pages.py` | 回归闸门：19 合成页 + 23 图表/SmartArt 页（`--suite chart_pages`）+ `--dir` 接真实语料 |
| `diffmap.py` | 对比评分（逐通道差异 + ±3px 对齐搜索 + AA 边缘降权） |
| `test_units.py` | 33 项纯函数单元断言 |
| `check_one.py` | 通用单页快速验证（转换 + 渲染） |

## 质量验证流程

```bash
python TestCase/calibrate_all.py           # 1. 标定（新机器/换 LO 版本/装新字体时）
python TestCase/test_units.py              # 2. 单元断言
python TestCase/bench.py                   # 3. 合成基准回归（19 页，应全绿）
python TestCase/bench.py --dir <deck目录>   # 4. 真实语料回归（自动拆分内嵌 deck）
```

当前基线（LibreOffice 渲染链）：合成基准 19/19 通过（9 页满分，中位数 99.8%）；
图表/SmartArt 套件 23/23 通过（16 页满分）；真实语料 145 页全部通过、
0 渲染失败（中位数 98.8%，最低为 iframe 页 79.4%）。
流水线原理与分数判读见 `TestCase/CALIBRATION.md`。

## 能力

- **布局**：绝对定位 / flex / block 流；负 z-index；opacity 子树累计传播
- **文本**：逐行实测定位（换行位置与浏览器一致）、行内混排、`<br>`、
  `text-align`、行高、下划线/删除线（含祖先传播）、text-transform、
  `white-space:pre`；列表 marker 悬挂定位（含垂直补偿）
- **样式**：线性/径向渐变（多层背景拆层解析）；四边独立边框（含虚线点线）；
  圆角（全/部分/椭圆/胶囊）；阴影（spread 近似，inset 跳过并报告）；
  CSS 三角形启发式
- **SVG**：circle/ellipse/rect/line/polyline/polygon/path、`<text>`（tspan 按行
  拆分、viewBox 缩放）、渐变、`<image>` 裁剪；直线与两点路径 → 原生连接线；
  marker-end → 原生线端箭头；dasharray 环形图 → 原生 BLOCK_ARC（跨 0° 自动
  拆分；round linecap 时两端以等径圆叠加为圆帽）；fill-opacity 折算进填充色；
  conic-gradient → 截图兜底；clip-path:polygon → 原生 freeform（文本保持可编辑）
- **表格**：colspan/rowspan 合并、逐格填充/边框、单元格深度提取、按实测宽度
  因子逐格缩放
- **图片**：`<img>`（object-fit:cover 裁剪）、`background:url()`、body 背景图
- **字体**：Windows 使用 winreg 枚举已安装字体；macOS 使用 system_profiler；Linux 使用 fc-list。CSS stack 浏览器式逐名回退：别名命中且目标字体本机已装→用别名目标；本机已装→原名直通（西文保留 Arial/Georgia 等）；未装→跳过试下一个名字；全栈落空→default_font。别名表 PingFang SC→PingFang SC（仅已装时生效，Windows 未装自动落到 Microsoft YaHei）
- **兜底**：canvas/iframe/video/embed、filter/transform/clip-path（限自样式且
  有实质内容）、SVG 透明渐变、data-uri SVG 背景 → 页面截图按 rect 裁剪贴图

## 已知限制

- `text-shadow`、多栏布局、竖排、`<input>` 控件：跳过
- `sup/sub` 上下标：平排（基线偏移未映射）
- 行内 content 伪元素（如 ::after 箭头字符）：不产生文本节点，丢弃
- `repeating-gradient` 降级；SVG 渐变描边、原生曲线（贝塞尔采样为折线）、
  fill-rule 孔洞：降级；渐变下层的 url 背景层丢弃（报告标注）
- SVG marker 箭头仅 triangle 样式且尺寸为原生档位（原稿用超大装饰箭头时会偏小）；列表 marker 为独立文本框方案
  （原生 buChar 因 LO 折行缺陷回退）
- BLOCK_ARC 圆帽为帽圆叠加近似（原稿 linecap:round 且弧极短时略有接缝）
- 逐行文本模式牺牲整段编辑性（`--text-mode flow` 可换回）
- 渲染器断行差异：行宽余量 +5%+8px、bold ×1.07、实测宽度因子兜底
- 中西文混排间距：LO/PowerPoint 自动加空格，与浏览器渲染存在固有小差异

> AI生成