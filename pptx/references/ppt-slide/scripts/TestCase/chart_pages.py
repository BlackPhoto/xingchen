# -*- coding: utf-8 -*-
"""
chart_pages.py — 图表 / SmartArt 转换测试集。

覆盖 Excel/PPT 常见图表与 SmartArt 布局在 HTML 中的主流实现技法。
每页 = 一个技法；分数低不一定是引擎错（技法本身有降级），但必须"内容不丢、
形态可辨"。预期结果标注在各页注释里。
"""
from bench_pages import _HEAD, _TAIL

def _page(body):
    return _HEAD + body + _TAIL

PAGES = {}

# ---- 1. SVG dasharray 环形图（本次修复的回归页）----
PAGES['chart_donut_dash'] = {'min_pct': 88, 'html': _page("""
<svg style="position:absolute;left:120px;top:100px" width="240" height="240" viewBox="0 0 140 140">
<circle cx="70" cy="70" r="56" fill="none" stroke="#a8c4e8" stroke-width="20" stroke-dasharray="80.1 351.7" transform="rotate(-90 70 70)"/>
<circle cx="70" cy="70" r="56" fill="none" stroke="#4a90e2" stroke-width="20" stroke-dasharray="89.4 351.7" stroke-dashoffset="-80.1" transform="rotate(-90 70 70)"/>
<circle cx="70" cy="70" r="56" fill="none" stroke="#0d3a7a" stroke-width="20" stroke-dasharray="182.3 351.7" stroke-dashoffset="-169.5" transform="rotate(-90 70 70)"/>
<text x="70" y="66" text-anchor="middle" font-size="14" fill="#334155">Q3</text>
<text x="70" y="84" text-anchor="middle" font-size="16" font-weight="bold" fill="#0d3a7a">52%</text>
</svg>
<div style="position:absolute;left:420px;top:120px;font-size:16px;line-height:2">
<div><span style="display:inline-block;width:14px;height:14px;background:#0d3a7a;border-radius:3px"></span> 输出 51.8%</div>
<div><span style="display:inline-block;width:14px;height:14px;background:#4a90e2;border-radius:3px"></span> 缓存未命中 25.4%</div>
<div><span style="display:inline-block;width:14px;height:14px;background:#a8c4e8;border-radius:3px"></span> 缓存命中 22.8%</div>
</div>
""")}

# ---- 2. conic-gradient 环形图（预期：截图兜底，内容保留）----
PAGES['chart_donut_conic'] = {'min_pct': 80, 'html': _page("""
<div style="position:absolute;left:140px;top:110px;width:240px;height:240px;border-radius:50%;
background:conic-gradient(#0d3a7a 0 52%, #4a90e2 52% 77%, #a8c4e8 77% 100%)"></div>
<div style="position:absolute;left:200px;top:170px;width:120px;height:120px;border-radius:50%;background:#fff"></div>
<div style="position:absolute;left:220px;top:215px;width:80px;text-align:center;font-size:18px;font-weight:700;color:#0d3a7a">52%</div>
<div style="position:absolute;left:450px;top:200px;font-size:17px;color:#334155">conic-gradient 环形图（截图兜底）</div>
""")}

# ---- 3. SVG 扇形饼图（A 弧命令路径填充）----
PAGES['chart_pie_sectors'] = {'min_pct': 85, 'html': _page("""
<svg style="position:absolute;left:130px;top:90px" width="260" height="260" viewBox="0 0 200 200">
<path d="M100 100 L100 20 A80 80 0 0 1 176 60 Z" fill="#1e5bb5"/>
<path d="M100 100 L176 60 A80 80 0 0 1 180 108 Z" fill="#4a90e2"/>
<path d="M100 100 L180 108 A80 80 0 0 1 100 180 Z" fill="#a8c4e8"/>
<path d="M100 100 L100 180 A80 80 0 0 1 100 20 Z" fill="#dbe7f7"/>
</svg>
<div style="position:absolute;left:440px;top:130px;font-size:16px;line-height:2.2">
<div><span style="display:inline-block;width:14px;height:14px;background:#1e5bb5"></span> A 业务 40%</div>
<div><span style="display:inline-block;width:14px;height:14px;background:#4a90e2"></span> B 业务 15%</div>
<div><span style="display:inline-block;width:14px;height:14px;background:#a8c4e8"></span> C 业务 25%</div>
<div><span style="display:inline-block;width:14px;height:14px;background:#dbe7f7"></span> 其他 20%</div>
</div>
""")}

# ---- 4. 柱状图（flex-end 对齐柱 + 基线 + 数值标签）----
PAGES['chart_column_flex'] = {'min_pct': 88, 'html': _page("""
<div style="position:absolute;left:80px;top:80px;width:640px;height:380px;display:flex;align-items:flex-end;gap:36px;border-bottom:2px solid #94a3b8;padding:0 30px">
<div style="flex:1;height:55%;background:#1e5bb5;position:relative"><span style="position:absolute;top:-26px;left:50%;transform:translateX(-50%);font-size:15px;color:#334155">120</span></div>
<div style="flex:1;height:80%;background:#1e5bb5;position:relative"><span style="position:absolute;top:-26px;left:50%;transform:translateX(-50%);font-size:15px;color:#334155">175</span></div>
<div style="flex:1;height:42%;background:#4a90e2;position:relative"><span style="position:absolute;top:-26px;left:50%;transform:translateX(-50%);font-size:15px;color:#334155">92</span></div>
<div style="flex:1;height:96%;background:#4a90e2;position:relative"><span style="position:absolute;top:-26px;left:50%;transform:translateX(-50%);font-size:15px;color:#334155">210</span></div>
<div style="flex:1;height:65%;background:#a8c4e8;position:relative"><span style="position:absolute;top:-26px;left:50%;transform:translateX(-50%);font-size:15px;color:#334155">143</span></div>
</div>
<div style="position:absolute;left:110px;top:470px;width:640px;display:flex;gap:36px;padding:0 30px;text-align:center;font-size:14px;color:#64748b">
<div style="flex:1">Q1</div><div style="flex:1">Q2</div><div style="flex:1">Q3</div><div style="flex:1">Q4</div><div style="flex:1">Q1'</div></div>
""")}

# ---- 5. 堆叠柱状图（柱内分段）----
PAGES['chart_column_stacked'] = {'min_pct': 86, 'html': _page("""
<div style="position:absolute;left:80px;top:80px;width:660px;height:400px;display:flex;align-items:flex-end;gap:60px;border-bottom:2px solid #94a3b8;padding:0 40px">
<div style="flex:1;height:88%;display:flex;flex-direction:column"><div style="height:35%;background:#0d3a7a"></div><div style="height:40%;background:#4a90e2"></div><div style="height:25%;background:#a8c4e8"></div></div>
<div style="flex:1;height:70%;display:flex;flex-direction:column"><div style="height:25%;background:#0d3a7a"></div><div style="height:30%;background:#4a90e2"></div><div style="height:45%;background:#a8c4e8"></div></div>
<div style="flex:1;height:95%;display:flex;flex-direction:column"><div style="height:45%;background:#0d3a7a"></div><div style="height:20%;background:#4a90e2"></div><div style="height:35%;background:#a8c4e8"></div></div>
<div style="flex:1;height:60%;display:flex;flex-direction:column"><div style="height:20%;background:#0d3a7a"></div><div style="height:35%;background:#4a90e2"></div><div style="height:45%;background:#a8c4e8"></div></div>
</div>
<div style="position:absolute;left:790px;top:100px;font-size:15px;line-height:2">
<div><span style="display:inline-block;width:13px;height:13px;background:#0d3a7a"></span> 硬件</div>
<div><span style="display:inline-block;width:13px;height:13px;background:#4a90e2"></span> 推理</div>
<div><span style="display:inline-block;width:13px;height:13px;background:#a8c4e8"></span> 运维</div></div>
""")}

# ---- 6. 条形图（横向）----
PAGES['chart_bar_h'] = {'min_pct': 88, 'html': _page("""
<div style="position:absolute;left:220px;top:100px;width:660px;font-size:15px">
<div style="margin:14px 0;color:#334155">模型 A<div style="margin-top:4px;height:26px;width:95%;background:#0d3a7a;border-radius:4px"></div></div>
<div style="margin:14px 0;color:#334155">模型 B<div style="margin-top:4px;height:26px;width:72%;background:#1e5bb5;border-radius:4px"></div></div>
<div style="margin:14px 0;color:#334155">模型 C<div style="margin-top:4px;height:26px;width:58%;background:#4a90e2;border-radius:4px"></div></div>
<div style="margin:14px 0;color:#334155">模型 D<div style="margin-top:4px;height:26px;width:34%;background:#a8c4e8;border-radius:4px"></div></div>
<div style="position:absolute;left:0;top:-30px;font-size:13px;color:#94a3b8">准确率对比（%）</div>
</div>
<div style="position:absolute;left:120px;top:100px;height:330px;width:1px;background:#cbd5e1"></div>
""")}

# ---- 7. 折线图（SVG polyline + 圆点 marker + 网格）----
PAGES['chart_line'] = {'min_pct': 84, 'html': _page("""
<svg style="position:absolute;left:90px;top:80px" width="660" height="400" viewBox="0 0 660 400">
<line x1="40" y1="20" x2="640" y2="20" stroke="#e2e8f0" stroke-width="1"/>
<line x1="40" y1="110" x2="640" y2="110" stroke="#e2e8f0" stroke-width="1"/>
<line x1="40" y1="200" x2="640" y2="200" stroke="#e2e8f0" stroke-width="1"/>
<line x1="40" y1="290" x2="640" y2="290" stroke="#e2e8f0" stroke-width="1"/>
<line x1="40" y1="380" x2="40" y2="20" stroke="#94a3b8" stroke-width="2"/>
<line x1="40" y1="380" x2="640" y2="380" stroke="#94a3b8" stroke-width="2"/>
<polyline points="40,300 190,210 340,240 490,120 640,60" fill="none" stroke="#1e5bb5" stroke-width="4" stroke-linejoin="round"/>
<polyline points="40,340 190,320 340,330 490,290 640,260" fill="none" stroke="#a8c4e8" stroke-width="4" stroke-dasharray="10 7"/>
<circle cx="190" cy="210" r="7" fill="#fff" stroke="#1e5bb5" stroke-width="4"/>
<circle cx="490" cy="120" r="7" fill="#fff" stroke="#1e5bb5" stroke-width="4"/>
<text x="176" y="190" font-size="15" fill="#0d3a7a" font-weight="bold">175</text>
<text x="476" y="100" font-size="15" fill="#0d3a7a" font-weight="bold">262</text>
<text x="60" y="398" font-size="13" fill="#64748b">1月</text>
<text x="210" y="398" font-size="13" fill="#64748b">2月</text>
<text x="360" y="398" font-size="13" fill="#64748b">3月</text>
<text x="510" y="398" font-size="13" fill="#64748b">4月</text>
<text x="616" y="398" font-size="13" fill="#64748b">5月</text>
</svg>
""")}

# ---- 8. 面积图（填充路径）----
PAGES['chart_area'] = {'min_pct': 84, 'html': _page("""
<svg style="position:absolute;left:90px;top:80px" width="660" height="400" viewBox="0 0 660 400">
<path d="M40 380 L40 260 C120 180, 220 240, 300 180 C380 120, 480 170, 640 60 L640 380 Z" fill="#dbe7f7"/>
<path d="M40 260 C120 180, 220 240, 300 180 C380 120, 480 170, 640 60" fill="none" stroke="#1e5bb5" stroke-width="4"/>
<line x1="40" y1="380" x2="640" y2="380" stroke="#94a3b8" stroke-width="2"/>
</svg>
<div style="position:absolute;left:90px;top:490px;font-size:16px;color:#475569">月度 token 消耗趋势（百万）</div>
""")}

# ---- 9. 复合图（柱 + 折线双轴）----
PAGES['chart_combo'] = {'min_pct': 82, 'html': _page("""
<svg style="position:absolute;left:80px;top:70px" width="680" height="420" viewBox="0 0 680 420">
<rect x="60" y="220" width="70" height="160" fill="#1e5bb5"/>
<rect x="190" y="180" width="70" height="200" fill="#1e5bb5"/>
<rect x="320" y="250" width="70" height="130" fill="#1e5bb5"/>
<rect x="450" y="150" width="70" height="230" fill="#1e5bb5"/>
<polyline points="95,160 225,120 355,180 485,80" fill="none" stroke="#e8743b" stroke-width="4"/>
<circle cx="95" cy="160" r="6" fill="#e8743b"/><circle cx="225" cy="120" r="6" fill="#e8743b"/>
<circle cx="355" cy="180" r="6" fill="#e8743b"/><circle cx="485" cy="80" r="6" fill="#e8743b"/>
<line x1="40" y1="380" x2="640" y2="380" stroke="#94a3b8" stroke-width="2"/>
</svg>
<div style="position:absolute;left:80px;top:500px;font-size:16px;color:#475569">
<span style="color:#1e5bb5;font-weight:700">■ 调用量</span>&nbsp;&nbsp;<span style="color:#e8743b;font-weight:700">● 环比增速</span></div>
""")}

# ---- 10. 半环仪表盘（dasharray 半圆）----
PAGES['chart_gauge'] = {'min_pct': 80, 'html': _page("""
<svg style="position:absolute;left:140px;top:120px" width="280" height="180" viewBox="0 0 140 90">
<path d="M 10 80 A 60 60 0 0 1 130 80" fill="none" stroke="#e2e8f0" stroke-width="16" stroke-linecap="round"/>
<path d="M 10 80 A 60 60 0 0 1 130 80" fill="none" stroke="#1e5bb5" stroke-width="16" stroke-linecap="round" stroke-dasharray="155 377"/>
<text x="70" y="70" text-anchor="middle" font-size="22" font-weight="bold" fill="#0d3a7a">72</text>
<text x="70" y="88" text-anchor="middle" font-size="11" fill="#64748b">健康分</text>
</svg>
<div style="position:absolute;left:480px;top:170px;font-size:16px;color:#334155">半环仪表盘（stroke-dasharray 弧）</div>
""")}

# ---- 11. 雷达图（SVG polygon 网格 + 数据多边形）----
PAGES['chart_radar'] = {'min_pct': 80, 'html': _page("""
<svg style="position:absolute;left:150px;top:70px" width="300" height="300" viewBox="0 0 200 200">
<polygon points="100,20 171,60 171,140 100,180 29,140 29,60" fill="none" stroke="#e2e8f0" stroke-width="1.5"/>
<polygon points="100,50 146,75 146,125 100,150 54,125 54,75" fill="none" stroke="#e2e8f0" stroke-width="1.5"/>
<polygon points="100,80 121,92 121,108 100,120 79,108 79,92" fill="none" stroke="#e2e8f0" stroke-width="1.5"/>
<line x1="100" y1="100" x2="100" y2="20" stroke="#e2e8f0" stroke-width="1"/>
<line x1="100" y1="100" x2="171" y2="60" stroke="#e2e8f0" stroke-width="1"/>
<line x1="100" y1="100" x2="171" y2="140" stroke="#e2e8f0" stroke-width="1"/>
<line x1="100" y1="100" x2="100" y2="180" stroke="#e2e8f0" stroke-width="1"/>
<line x1="100" y1="100" x2="29" y2="140" stroke="#e2e8f0" stroke-width="1"/>
<line x1="100" y1="100" x2="29" y2="60" stroke="#e2e8f0" stroke-width="1"/>
<polygon points="100,35 156,68 140,128 100,158 48,132 62,70" fill="#4a90e2" fill-opacity="0.35" stroke="#1e5bb5" stroke-width="2.5"/>
<text x="100" y="14" text-anchor="middle" font-size="11" fill="#475569">速度</text>
<text x="184" y="60" text-anchor="middle" font-size="11" fill="#475569">质量</text>
<text x="184" y="146" text-anchor="middle" font-size="11" fill="#475569">成本</text>
<text x="100" y="195" text-anchor="middle" font-size="11" fill="#475569">稳定</text>
<text x="16" y="146" text-anchor="middle" font-size="11" fill="#475569">生态</text>
<text x="16" y="60" text-anchor="middle" font-size="11" fill="#475569">安全</text>
</svg>
""")}

# ---- 12. 热力矩阵（CSS grid 色块 + 文字）----
PAGES['chart_heatmap'] = {'min_pct': 86, 'html': _page("""
<div style="position:absolute;left:200px;top:110px;display:grid;grid-template-columns:repeat(5,110px);gap:8px;font-size:15px">
<div></div><div style="text-align:center;color:#64748b">低并发</div><div style="text-align:center;color:#64748b">中并发</div><div style="text-align:center;color:#64748b">高并发</div><div style="text-align:center;color:#64748b">峰值</div>
<div style="color:#64748b;padding-top:16px">DeepSeek</div><div style="height:56px;background:#dbe7f7;border-radius:6px"></div><div style="height:56px;background:#a8c4e8;border-radius:6px"></div><div style="height:56px;background:#4a90e2;border-radius:6px"></div><div style="height:56px;background:#1e5bb5;border-radius:6px"></div>
<div style="color:#64748b;padding-top:16px">GLM</div><div style="height:56px;background:#eef3fb;border-radius:6px"></div><div style="height:56px;background:#dbe7f7;border-radius:6px"></div><div style="height:56px;background:#a8c4e8;border-radius:6px"></div><div style="height:56px;background:#4a90e2;border-radius:6px"></div>
<div style="color:#64748b;padding-top:16px">混合</div><div style="height:56px;background:#f5f8fd;border-radius:6px"></div><div style="height:56px;background:#eef3fb;border-radius:6px"></div><div style="height:56px;background:#dbe7f7;border-radius:6px"></div><div style="height:56px;background:#a8c4e8;border-radius:6px"></div>
</div>
""")}

# ---- 13. 瀑布图（定位条）----
PAGES['chart_waterfall'] = {'min_pct': 82, 'html': _page("""
<div style="position:absolute;left:80px;top:90px;width:700px;height:400px">
<div style="position:absolute;left:40px;bottom:0;width:90px;height:250px;background:#1e5bb5"></div>
<div style="position:absolute;left:190px;bottom:250px;width:90px;height:70px;background:#4a90e2"></div>
<div style="position:absolute;left:340px;bottom:320px;width:90px;height:45px;background:#a8c4e8"></div>
<div style="position:absolute;left:490px;bottom:275px;width:90px;height:45px;background:#e8743b"></div>
<div style="position:absolute;left:560px;bottom:0;width:90px;height:320px;background:#0d3a7a"></div>
<svg style="position:absolute;left:0;top:0" width="700" height="400" viewBox="0 0 700 400">
<line x1="130" y1="180" x2="190" y2="180" stroke="#94a3b8" stroke-dasharray="4 4"/>
<line x1="280" y1="110" x2="340" y2="110" stroke="#94a3b8" stroke-dasharray="4 4"/>
<line x1="430" y1="65" x2="490" y2="65" stroke="#94a3b8" stroke-dasharray="4 4"/>
</svg>
<div style="position:absolute;left:40px;bottom:-26px;font-size:13px;color:#64748b">基线</div>
<div style="position:absolute;left:190px;bottom:-26px;font-size:13px;color:#64748b">+新增</div>
<div style="position:absolute;left:340px;bottom:-26px;font-size:13px;color:#64748b">+扩容</div>
<div style="position:absolute;left:490px;bottom:-26px;font-size:13px;color:#64748b">-优化</div>
<div style="position:absolute;left:560px;bottom:-26px;font-size:13px;color:#64748b">终态</div>
<div style="position:absolute;left:0;top:0;width:100%;height:1px"></div>
</div>
<div style="position:absolute;left:80px;top:70px;width:700px;height:400px;border-bottom:2px solid #94a3b8"></div>
""")}

# ---- 14. 漏斗图（clip-path 梯形 → 原生 freeform）----
PAGES['chart_funnel'] = {'min_pct': 84, 'html': _page("""
<div style="position:absolute;left:150px;top:80px;width:560px;font-size:16px;color:#fff">
<div style="height:64px;width:100%;background:#0d3a7a;clip-path:polygon(0 0,100% 0,88% 100%,12% 100%);margin:6px 0;display:flex;align-items:center;justify-content:center">访问 100%</div>
<div style="height:64px;width:88%;margin:0 auto;background:#1e5bb5;clip-path:polygon(0 0,100% 0,86% 100%,14% 100%);margin:6px auto;display:flex;align-items:center;justify-content:center">注册 72%</div>
<div style="height:64px;width:72%;background:#4a90e2;clip-path:polygon(0 0,100% 0,84% 100%,16% 100%);margin:6px auto;display:flex;align-items:center;justify-content:center">激活 48%</div>
<div style="height:64px;width:56%;background:#a8c4e8;clip-path:polygon(0 0,100% 0,82% 100%,18% 100%);margin:6px auto;display:flex;align-items:center;justify-content:center;color:#0d3a7a">付费 21%</div>
</div>
""")}

# ---- 15. KPI 进度条组 ----
PAGES['chart_kpi_progress'] = {'min_pct': 88, 'html': _page("""
<div style="position:absolute;left:100px;top:100px;width:500px;font-size:16px">
<div style="margin:18px 0"><div style="display:flex;justify-content:space-between;color:#334155"><span>Token 效率</span><b>86%</b></div>
<div style="margin-top:6px;height:14px;background:#e2e8f0;border-radius:7px"><div style="width:86%;height:100%;background:#1e5bb5;border-radius:7px"></div></div></div>
<div style="margin:18px 0"><div style="display:flex;justify-content:space-between;color:#334155"><span>缓存命中</span><b>70%</b></div>
<div style="margin-top:6px;height:14px;background:#e2e8f0;border-radius:7px"><div style="width:70%;height:100%;background:#4a90e2;border-radius:7px"></div></div></div>
<div style="margin:18px 0"><div style="display:flex;justify-content:space-between;color:#334155"><span>人工介入率</span><b>12%</b></div>
<div style="margin-top:6px;height:14px;background:#e2e8f0;border-radius:7px"><div style="width:12%;height:100%;background:#e8743b;border-radius:7px"></div></div></div>
</div>
""")}

# ---- 16. SmartArt 流程（方框 + marker-end 箭头连接线）----
PAGES['sa_process'] = {'min_pct': 84, 'html': _page("""
<svg style="position:absolute;left:80px;top:200px" width="760" height="60" viewBox="0 0 760 60">
<defs><marker id="pa" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto"><polygon points="0 0,10 3.5,0 7" fill="#1e5bb5"/></marker></defs>
<line x1="170" y1="30" x2="250" y2="30" stroke="#1e5bb5" stroke-width="3" marker-end="url(#pa)"/>
<line x1="420" y1="30" x2="500" y2="30" stroke="#1e5bb5" stroke-width="3" marker-end="url(#pa)"/>
</svg>
<div style="position:absolute;left:80px;top:180px;width:170px;height:100px;background:#1e5bb5;border-radius:10px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:20px">需求</div>
<div style="position:absolute;left:330px;top:180px;width:170px;height:100px;background:#4a90e2;border-radius:10px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:20px">开发</div>
<div style="position:absolute;left:580px;top:180px;width:170px;height:100px;background:#a8c4e2;border-radius:10px;display:flex;align-items:center;justify-content:center;color:#0d3a7a;font-size:20px">上线</div>
""")}

# ---- 17. SmartArt 组织架构（树 + 连接线）----
PAGES['sa_hierarchy'] = {'min_pct': 82, 'html': _page("""
<div style="position:absolute;left:330px;top:90px;width:180px;height:60px;background:#0d3a7a;border-radius:8px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:19px">CTO</div>
<svg style="position:absolute;left:0;top:150px" width="840" height="220" viewBox="0 0 840 220">
<line x1="420" y1="0" x2="420" y2="40" stroke="#94a3b8" stroke-width="2"/>
<line x1="160" y1="40" x2="680" y2="40" stroke="#94a3b8" stroke-width="2"/>
<line x1="160" y1="40" x2="160" y2="70" stroke="#94a3b8" stroke-width="2"/>
<line x1="420" y1="40" x2="420" y2="70" stroke="#94a3b8" stroke-width="2"/>
<line x1="680" y1="40" x2="680" y2="70" stroke="#94a3b8" stroke-width="2"/>
<line x1="160" y1="150" x2="160" y2="180" stroke="#94a3b8" stroke-width="2"/>
<line x1="80" y1="180" x2="240" y2="180" stroke="#94a3b8" stroke-width="2"/>
</svg>
<div style="position:absolute;left:70px;top:220px;width:180px;height:56px;background:#1e5bb5;border-radius:8px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:17px">平台部</div>
<div style="position:absolute;left:330px;top:220px;width:180px;height:56px;background:#1e5bb5;border-radius:8px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:17px">算法部</div>
<div style="position:absolute;left:590px;top:220px;width:180px;height:56px;background:#1e5bb5;border-radius:8px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:17px">数据部</div>
""")}

# ---- 18. SmartArt 循环（圆弧箭头 + 节点）----
PAGES['sa_cycle'] = {'min_pct': 70, 'html': _page("""
<svg style="position:absolute;left:220px;top:60px" width="400" height="400" viewBox="0 0 200 200">
<path d="M 100 30 A 70 70 0 0 1 163 128" fill="none" stroke="#1e5bb5" stroke-width="10" marker-end="url(#ca)"/>
<path d="M 152 152 A 70 70 0 0 1 48 152" fill="none" stroke="#4a90e2" stroke-width="10" marker-end="url(#ca)"/>
<path d="M 37 128 A 70 70 0 0 1 100 30" fill="none" stroke="#a8c4e8" stroke-width="10" marker-end="url(#ca)"/>
<defs><marker id="ca" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><polygon points="0 0,8 3,0 6" fill="#1e5bb5"/></marker></defs>
</svg>
<div style="position:absolute;left:330px;top:230px;width:180px;height:60px;background:#0d3a7a;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff;font-size:19px">持续迭代</div>
<div style="position:absolute;left:355px;top:90px;width:130px;height:44px;background:#fff;border:2px solid #1e5bb5;border-radius:22px;display:flex;align-items:center;justify-content:center;font-size:16px;color:#1e5bb5">创建</div>
<div style="position:absolute;left:500px;top:250px;width:130px;height:44px;background:#fff;border:2px solid #4a90e2;border-radius:22px;display:flex;align-items:center;justify-content:center;font-size:16px;color:#1e5bb5">测试</div>
<div style="position:absolute;left:210px;top:250px;width:130px;height:44px;background:#fff;border:2px solid #a8c4e8;border-radius:22px;display:flex;align-items:center;justify-content:center;font-size:16px;color:#1e5bb5">反馈</div>
""")}

# ---- 19. SmartArt 金字塔（clip-path 三角层 → freeform）----
PAGES['sa_pyramid'] = {'min_pct': 80, 'html': _page("""
<div style="position:absolute;left:220px;top:120px;width:400px;font-size:15px;color:#fff;text-align:center">
<div style="height:52px;width:30%;background:#a8c4e8;clip-path:polygon(35% 0,65% 0,100% 100%,0 100%);margin:4px auto;display:flex;align-items:center;justify-content:center;color:#0d3a7a">战略</div>
<div style="height:52px;width:55%;background:#4a90e2;clip-path:polygon(18% 0,82% 0,100% 100%,0 100%);margin:4px auto;display:flex;align-items:center;justify-content:center">战术</div>
<div style="height:52px;width:80%;background:#1e5bb5;clip-path:polygon(10% 0,90% 0,100% 100%,0 100%);margin:4px auto;display:flex;align-items:center;justify-content:center">执行</div>
<div style="height:52px;width:100%;background:#0d3a7a;clip-path:polygon(0 0,100% 0,100% 100%,0 100%);margin:4px auto;display:flex;align-items:center;justify-content:center">基础平台</div>
</div>
""")}

# ---- 20. SmartArt V 形列表（clip-path chevron）----
PAGES['sa_chevron'] = {'min_pct': 80, 'html': _page("""
<div style="position:absolute;left:100px;top:130px;width:700px;font-size:17px;color:#fff">
<div style="height:58px;width:62%;background:#0d3a7a;clip-path:polygon(0 0,calc(100% - 24px) 0,100% 50%,calc(100% - 24px) 100%,0 100%,24px 50%);margin:8px 0;display:flex;align-items:center;justify-content:center">第一阶段：需求澄清</div>
<div style="height:58px;width:74%;background:#1e5bb5;clip-path:polygon(0 0,calc(100% - 24px) 0,100% 50%,calc(100% - 24px) 100%,0 100%,24px 50%);margin:8px 0;display:flex;align-items:center;justify-content:center">第二阶段：方案设计</div>
<div style="height:58px;width:86%;background:#4a90e2;clip-path:polygon(0 0,calc(100% - 24px) 0,100% 50%,calc(100% - 24px) 100%,0 100%,24px 50%);margin:8px 0;display:flex;align-items:center;justify-content:center">第三阶段：交付落地</div>
<div style="height:58px;width:98%;background:#a8c4e8;clip-path:polygon(0 0,calc(100% - 24px) 0,100% 50%,calc(100% - 24px) 100%,0 100%,24px 50%);margin:8px 0;display:flex;align-items:center;justify-content:center;color:#0d3a7a">第四阶段：持续运营</div>
</div>
""")}

# ---- 21. SmartArt 韦恩图（半透明圆叠加）----
PAGES['sa_venn'] = {'min_pct': 78, 'html': _page("""
<div style="position:absolute;left:230px;top:110px;width:400px;height:340px">
<div style="position:absolute;left:0;top:40px;width:220px;height:220px;border-radius:50%;background:#1e5bb5;opacity:.55"></div>
<div style="position:absolute;left:160px;top:40px;width:220px;height:220px;border-radius:50%;background:#4a90e2;opacity:.55"></div>
<div style="position:absolute;left:80px;top:120px;width:220px;height:220px;border-radius:50%;background:#a8c4e8;opacity:.55"></div>
<div style="position:absolute;left:60px;top:110px;width:100px;text-align:center;font-size:17px;color:#fff;font-weight:700">降本</div>
<div style="position:absolute;left:250px;top:110px;width:100px;text-align:center;font-size:17px;color:#fff;font-weight:700">增效</div>
<div style="position:absolute;left:155px;top:290px;width:100px;text-align:center;font-size:17px;color:#0d3a7a;font-weight:700">体验</div>
</div>
""")}

# ---- 22. SmartArt 时间轴（横线 + 圆点 + 交错卡片）----
PAGES['sa_timeline'] = {'min_pct': 84, 'html': _page("""
<div style="position:absolute;left:90px;top:230px;width:740px;height:4px;background:#cbd5e1"></div>
<div style="position:absolute;left:140px;top:222px;width:20px;height:20px;border-radius:50%;background:#1e5bb5"></div>
<div style="position:absolute;left:350px;top:222px;width:20px;height:20px;border-radius:50%;background:#4a90e2"></div>
<div style="position:absolute;left:560px;top:222px;width:20px;height:20px;border-radius:50%;background:#a8c4e8"></div>
<div style="position:absolute;left:90px;top:110px;width:220px;background:#f1f5f9;border-radius:10px;padding:14px">
<div style="font-weight:700;color:#0d3a7a;font-size:17px">2026 Q1 试点</div>
<div style="font-size:14px;color:#475569;margin-top:4px">3 个部门灰度接入</div></div>
<div style="position:absolute;left:300px;top:280px;width:220px;background:#f1f5f9;border-radius:10px;padding:14px">
<div style="font-weight:700;color:#0d3a7a;font-size:17px">2026 Q2 推广</div>
<div style="font-size:14px;color:#475569;margin-top:4px">全集团上线 200+ 技能</div></div>
<div style="position:absolute;left:510px;top:110px;width:220px;background:#f1f5f9;border-radius:10px;padding:14px">
<div style="font-weight:700;color:#0d3a7a;font-size:17px">2026 Q3 深化</div>
<div style="font-size:14px;color:#475569;margin-top:4px">与 OA/工单系统打通</div></div>
""")}

# ---- 23. 甘特条（时间轴定位条）----
PAGES['chart_gantt'] = {'min_pct': 84, 'html': _page("""
<div style="position:absolute;left:180px;top:110px;width:620px;font-size:15px">
<div style="position:relative;height:44px;margin:10px 0"><span style="position:absolute;left:-110px;color:#334155">需求分析</span>
<div style="position:absolute;left:0;top:8px;height:24px;width:30%;background:#0d3a7a;border-radius:5px"></div></div>
<div style="position:relative;height:44px;margin:10px 0"><span style="position:absolute;left:-110px;color:#334155">原型设计</span>
<div style="position:absolute;left:22%;top:8px;height:24px;width:26%;background:#1e5bb5;border-radius:5px"></div></div>
<div style="position:relative;height:44px;margin:10px 0"><span style="position:absolute;left:-110px;color:#334155">开发实施</span>
<div style="position:absolute;left:40%;top:8px;height:24px;width:40%;background:#4a90e2;border-radius:5px"></div></div>
<div style="position:relative;height:44px;margin:10px 0"><span style="position:absolute;left:-110px;color:#334155">验收上线</span>
<div style="position:absolute;left:74%;top:8px;height:24px;width:22%;background:#a8c4e8;border-radius:5px"></div></div>
<div style="position:absolute;left:0;top:196px;width:100%;height:2px;background:#cbd5e1"></div>
<div style="position:absolute;left:0;top:204px;width:100%;display:flex;justify-content:space-between;color:#94a3b8;font-size:13px">
<span>W1</span><span>W2</span><span>W3</span><span>W4</span><span>W5</span><span>W6</span></div>
</div>
""")}
