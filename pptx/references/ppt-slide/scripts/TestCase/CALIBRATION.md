# 标定工作流（CALIBRATION WORKFLOW）

目的：把引擎里"对渲染器/字体/版式的假设"从**拍脑袋**变成**量出来**。
任何"转换结果与浏览器不一致"的问题，先走这条流水线定量定位，再改代码。

## 流水线总览

```
TestCase/calibrate_all.py          ← 一键入口（可单跑某步）
 ├─ 1. measure.py      宽度标定  → TestCase/font_metrics.json
 │      标本: 10 字体 × {cjk,大写,小写,数字} × {16,24,32}px
 │      方法: 同文本 浏览器 Range 宽度 vs LibreOffice 墨迹 bbox，取比值
 │      消费方: html2pptx.emit_line_texts 按字体×字符类微缩字号
 │
 ├─ 2. vcalib.py       垂直标定  → 报告徽章/bullet 垂直偏差(px)
 │      标本: {24,32,40,48}px 圆/方徽章内数字 + lh{2.0,1.4} bullet 列表
 │      方法: 浏览器 vs LO 渲染图的墨迹垂直中心差
 │      消费方: extract.js 列表 marker 的 +0.06em 垂直补偿系数
 │
 └─ 3. shadow_calib.py 阴影标定  → LO/browser 阴影浓度比（逐条带）
        标本: {alpha,blur,oy} 6 组合的白卡 + 卡周 6 条带
        方法: 同参数双渲染，条带暗度比值
        消费方: 诊断性——确认 add_shadow 忠实（元凶是主题 effectRef，已修）

回归闸门:  python bench.py            （19 合成页全绿才算过）
           python bench.py --dir ../Test --strict   （真实语料回归）
```

## 什么时候跑

| 触发 | 跑什么 |
|---|---|
| 换机器 / 换 LibreOffice 版本 / 换字体 | 全部三项 |
| 文字偏宽溢出 / 折行异常 | measure（先看 ratio 表） |
| 列表圆点/徽章数字与文字错位 | vcalib |
| 阴影过重/过轻 | shadow_calib |
| 改了引擎任何常数（h2p_config.py） | bench.py 全量 + 涉及项的标定 |

## 数据与代码的对应关系（谁消费哪个数）

| 标定产物 | 消费位置 | 说明 |
|---|---|---|
| `TestCase/font_metrics.json` → `{font:{class:ratio}}` | `h2p_config.font_width_factor` → `emit_line_texts` 行宽微缩 | ratio>1 按比例缩字号 |
| vcalib 的 bullet delta | `extract.js` marker 盒 `+fsM*0.06` 垂直补偿 | \|delta\|>0.5px 时调系数 |
| vcalib 的 badge delta | 应恒为 0（行距单位已修复）；偏离 → 查 `_fill_frame` 的 px/pt 换算 | 回归哨兵 |
| shadow_calib 比例 | 无自动消费；>1.3 时在 `add_shadow` 加浓度校正 | 诊断性 |

## 手调常数 vs 实测常数（h2p_config.py 数据溯源）

- **实测**: 宽度因子（measure）、bullet 垂直补偿 0.06em（vcalib）、
  行距换算 ×0.75（px→pt 推导）、阴影忠实性结论（shadow_calib）
- **手调基线（未标定，改动须过 bench 回归）**: default_fs 19、default_color
  1A1A2E、lh_default 1.22、bold_threshold 550、autofit 全部、geometry 阈值、
  table 参数——历史手工迭代遗产，等基准显示某项失真时再升级为实测

## 已知边界

- measure 只标定 4 类字符（cjk/大写/小写/数字），标点/符号按未标定处理（因子 1.0）
- 标定只在 LibreOffice 上做；PowerPoint/WPS 的 profile 尚未生成（接口已留）：
  `--profile wps.json` + `font_metrics_path` 指向对应标定文件
- vcalib 的补偿系数写在 extract.js 里（浏览器侧），自动化回写未实现——按
  calibrate_all 结束时的人工判定清单操作
