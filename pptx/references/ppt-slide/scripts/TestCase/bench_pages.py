# -*- coding: utf-8 -*-
"""bench_pages.py — 转换保真度基准页集。

PAGES: {name: {'min_pct': 及格线, 'html': 页面}}
每页 1280x720、body margin 0、无外部资源。及格线含义：score_pair 的 match_pct
下限（对齐搜索 + AA 降权之后）。
"""

_HEAD = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:1280px;height:720px}
body{font-family:"Microsoft YaHei",Arial,sans-serif;background:#fff;overflow:hidden}
.p{position:absolute}
</style></head><body>"""
_TAIL = "</body></html>"

def _page(body, extra=""):
    return _HEAD + extra + body + _TAIL

PAGES = {}

PAGES['text_mixed'] = {'min_pct': 90, 'html': _page("""
<div class="p" style="left:80px;top:60px;font-size:44px;font-weight:700;color:#1a2b4a">数字化转型 <span style="color:#e8743b;font-size:30px;font-weight:400">2026</span> 年度报告</div>
<div class="p" style="left:80px;top:140px;font-size:16px;letter-spacing:2px;color:#8a94a6">ANNUAL REPORT OF DIGITAL TRANSFORMATION</div>
<div class="p" style="left:80px;top:210px;width:520px;font-size:18px;line-height:1.8;color:#333">
本年度围绕平台化、数据驱动与组织协同三大方向持续推进，各业务线在交付效率与质量指标上均取得显著进展。
核心系统完成容器化改造，平均发布周期从两周缩短至三天，线上故障率同比下降 <b style="color:#c0392b">42%</b>。
下一阶段将聚焦 <span style="background:#fff3cd;padding:1px 4px;border-radius:3px">智能运维</span> 与成本治理两条主线。</div>
<div class="p" style="left:80px;top:470px;font-size:20px"><i>斜体混排</i> 正常 <b>粗体</b> <span style="font-size:14px;color:#777">小号</span> <span style="font-size:26px;color:#2c6e49">大号</span> 结束</div>
""")}

PAGES['text_english'] = {'min_pct': 88, 'html': _page("""
<div class="p" style="left:80px;top:60px;width:600px;font-family:Arial,sans-serif;font-size:24px;line-height:1.5">
The quick brown fox jumps over the lazy dog. Pack my box with five dozen liquor jugs.</div>
<div class="p" style="left:80px;top:200px;width:600px;font-family:Georgia,serif;font-size:20px;line-height:1.6">
Sphinx of black quartz, judge my vow. How vexingly quick daft zebras jump!</div>
<div class="p" style="left:80px;top:340px;width:600px;font-family:'Times New Roman',serif;font-size:20px">
The five boxing wizards jump quickly. 0123456789 &mdash; mixed 42 units.</div>
""")}

PAGES['text_transform'] = {'min_pct': 88, 'html': _page("""
<div class="p" style="left:80px;top:60px;font-size:30px;text-transform:uppercase">chapter one: the beginning</div>
<div class="p" style="left:80px;top:130px;font-size:22px;text-transform:lowercase">ALL LOWERCASE EXPECTED HERE</div>
<div class="p" style="left:80px;top:190px;font-size:22px"><u><span>underlined via ancestor u</span></u> and <s>strikethrough</s> and <span style="text-decoration:overline">overline</span></div>
<div class="p" style="left:80px;top:250px;font-size:22px">baseline x<sup>2</sup> + y<sub>1</sub> = z</div>
""")}

PAGES['gradient_linear'] = {'min_pct': 80, 'html': _page("""
<div class="p" style="left:80px;top:80px;width:240px;height:120px;background:linear-gradient(90deg,#1d4ed8,#60a5fa)"></div>
<div class="p" style="left:360px;top:80px;width:240px;height:120px;background:linear-gradient(180deg,#059669,#a7f3d0)"></div>
<div class="p" style="left:640px;top:80px;width:240px;height:120px;background:linear-gradient(45deg,#f59e0b,#ef4444)"></div>
<div class="p" style="left:80px;top:240px;width:240px;height:120px;background:linear-gradient(to top right,#7c3aed,#ec4899)"></div>
<div class="p" style="left:360px;top:240px;width:240px;height:120px;background:linear-gradient(to right,rgba(29,78,216,.15),rgba(29,78,216,.9))"></div>
""")}

PAGES['gradient_radial'] = {'min_pct': 80, 'html': _page("""
<div class="p" style="left:120px;top:100px;width:200px;height:200px;border-radius:50%;background:radial-gradient(circle,#fef3c7,#f59e0b 60%,#b45309)"></div>
<div class="p" style="left:420px;top:100px;width:200px;height:200px;border-radius:50%;background:radial-gradient(circle at 30% 30%,#bfdbfe,#1d4ed8)"></div>
""")}

PAGES['shadow'] = {'min_pct': 82, 'html': _page("""
<div class="p" style="left:100px;top:100px;width:280px;height:160px;background:#fff;border:1px solid #e5e7eb;border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,.15)"></div>
<div class="p" style="left:480px;top:100px;width:280px;height:160px;background:#fff;border-radius:10px;box-shadow:0 2px 6px rgba(0,0,0,.25),0 12px 32px rgba(0,0,0,.18)"></div>
<div class="p" style="left:100px;top:340px;width:280px;height:160px;background:#f9fafb;box-shadow:4px 4px 0 #cbd5e1"></div>
""")}

PAGES['radius'] = {'min_pct': 88, 'html': _page("""
<div class="p" style="left:80px;top:80px;width:220px;height:120px;background:#1d4ed8;border-radius:16px"></div>
<div class="p" style="left:340px;top:80px;width:220px;height:120px;background:#059669;border-radius:24px 24px 0 0"></div>
<div class="p" style="left:600px;top:80px;width:220px;height:120px;background:#b45309;border-radius:0 0 24px 24px"></div>
<div class="p" style="left:80px;top:260px;width:300px;height:64px;background:#db2777;border-radius:999px"></div>
<div class="p" style="left:440px;top:240px;width:160px;height:160px;background:#7c3aed;border-radius:50%"></div>
<div class="p" style="left:660px;top:260px;width:220px;height:120px;background:#334155;border-radius:16px 0 16px 0"></div>
""")}

PAGES['table'] = {'min_pct': 85, 'html': _page("""
<table class="p" style="left:100px;top:100px;border-collapse:collapse;font-size:16px">
<tr><th colspan="2" style="border:1px solid #94a3b8;background:#1e293b;color:#fff;padding:10px 24px">季度汇总</th><th style="border:1px solid #94a3b8;background:#1e293b;color:#fff;padding:10px 24px">备注</th></tr>
<tr><td style="border:1px solid #cbd5e1;padding:8px 24px">Q1</td><td style="border:1px solid #cbd5e1;padding:8px 24px;text-align:right">1,204</td><td rowspan="2" style="border:1px solid #cbd5e1;padding:8px 24px">同比增长</td></tr>
<tr><td style="border:1px solid #cbd5e1;padding:8px 24px">Q2</td><td style="border:1px solid #cbd5e1;padding:8px 24px;text-align:right">1,568</td></tr>
<tr><td style="border:1px solid #cbd5e1;padding:8px 24px">Q3</td><td style="border:1px solid #cbd5e1;padding:8px 24px;text-align:right">2,090</td><td style="border:1px solid #cbd5e1;padding:8px 24px">创新高</td></tr>
</table>
""")}

PAGES['svg_shapes'] = {'min_pct': 85, 'html': _page("""
<svg class="p" style="left:100px;top:80px" width="480" height="280" viewBox="0 0 480 280">
<circle cx="80" cy="80" r="50" fill="#e0f2fe" stroke="#0284c7" stroke-width="3"/>
<rect x="170" y="35" width="130" height="90" rx="14" fill="#dcfce7" stroke="#16a34a" stroke-width="2"/>
<line x1="340" y1="40" x2="440" y2="120" stroke="#dc2626" stroke-width="4" stroke-linecap="round"/>
<polygon points="80,180 140,260 20,260" fill="#fef9c3" stroke="#ca8a04" stroke-width="2"/>
<path d="M 180 250 C 210 170, 300 170, 330 250" fill="none" stroke="#7c3aed" stroke-width="5"/>
<path d="M 360 250 L 390 190 L 420 250 Z" fill="#f3e8ff" stroke="#9333ea" stroke-width="2"/>
<line x1="20" y1="20" x2="460" y2="20" stroke="#94a3b8" stroke-width="2" stroke-dasharray="8 6"/>
</svg>
""")}

PAGES['svg_text'] = {'min_pct': 82, 'html': _page("""
<svg class="p" style="left:100px;top:100px" width="500" height="260" viewBox="0 0 500 260">
<text x="20" y="40" font-size="26" fill="#1e293b" font-weight="bold">SVG 标题文本</text>
<text x="20" y="110" font-size="18" fill="#475569">
  <tspan x="20" dy="0">第一行：数据驱动决策</tspan>
  <tspan x="20" dy="30">第二行：平台赋能业务</tspan>
</text>
<text x="200" y="210" font-size="20" fill="#0284c7" text-anchor="middle">居中文本</text>
</svg>
""")}

PAGES['list'] = {'min_pct': 88, 'html': _page("""
<ul class="p" style="left:100px;top:80px;font-size:19px;line-height:2;width:420px">
<li>平台化架构演进</li>
<li>数据中台建设
  <ul style="margin-left:28px"><li>指标体系统一</li><li>数据质量治理</li></ul></li>
<li>组织协同机制</li>
</ul>
<ol class="p" style="left:600px;top:80px;font-size:19px;line-height:2;width:420px">
<li>需求收集与评估</li>
<li>方案设计与评审</li>
<li>灰度发布与监控</li>
</ol>
""")}

PAGES['flex_center'] = {'min_pct': 88, 'html': _page("""
<div class="p" style="left:80px;top:80px;width:400px;height:200px;background:#f1f5f9;display:flex;align-items:center;justify-content:center"><span style="font-size:24px;color:#334155">水平垂直居中</span></div>
<div class="p" style="left:540px;top:80px;width:400px;height:200px;background:#f8fafc;display:flex;align-items:flex-end;justify-content:flex-end;padding:16px"><span style="font-size:18px;color:#64748b">右下对齐</span></div>
<div class="p" style="left:80px;top:340px;width:860px;height:120px;background:#ecfdf5;display:flex;align-items:center;justify-content:space-around">
<span style="font-size:20px;font-weight:600;color:#065f46">指标 A</span>
<span style="font-size:20px;font-weight:600;color:#065f46">指标 B</span>
<span style="font-size:20px;font-weight:600;color:#065f46">指标 C</span></div>
""")}

PAGES['chips'] = {'min_pct': 88, 'html': _page("""
<div class="p" style="left:80px;top:80px;font-size:0">
<span style="display:inline-flex;align-items:center;padding:6px 16px;border-radius:999px;background:#dbeafe;color:#1e40af;font-size:15px;font-weight:600">进行中</span>
<span style="display:inline-flex;align-items:center;padding:6px 16px;border-radius:999px;background:#dcfce7;color:#166534;font-size:15px;font-weight:600;margin-left:12px">已完成</span>
<span style="display:inline-flex;align-items:center;padding:6px 16px;border-radius:999px;border:1px solid #fca5a5;color:#b91c1c;font-size:15px;font-weight:600;margin-left:12px">已延期</span>
</div>
<div class="p" style="left:80px;top:180px;font-size:18px;color:#334155">状态 <span style="display:inline-block;padding:2px 10px;background:#fef3c7;border-radius:4px;color:#92400e;font-size:14px;margin-left:8px">阶段 2</span> 进行中</div>
""")}

PAGES['pseudo'] = {'min_pct': 86, 'html': _page("""
<style>
.tick::before{content:"\\2713  ";color:#16a34a;font-weight:700}
.arrowp::after{content:" \\2192";color:#2563eb;font-weight:700}
.cardp::before{content:"";display:block;width:44px;height:6px;background:#e8743b;border-radius:3px;margin-bottom:10px}
</style>
<div class="p" style="left:80px;top:80px;font-size:20px;line-height:2.2">
<div class="tick">需求评审通过</div>
<div class="tick">技术方案确定</div>
<div class="tick">灰度发布完成 <span class="arrowp">进入下一阶段</span></div>
</div>
<div class="p cardp" style="left:80px;top:330px;width:360px;font-size:17px;color:#374151;padding-top:6px">装饰条来自 ::before 块级伪元素</div>
""")}

PAGES['opacity_stack'] = {'min_pct': 80, 'html': _page("""
<div class="p" style="left:100px;top:100px;width:400px;height:240px;background:#0f172a">
<div class="p" style="left:40px;top:40px;width:220px;height:140px;background:#38bdf8;opacity:.45"></div>
<div class="p" style="left:160px;top:90px;width:220px;height:140px;background:#f472b6;opacity:.6"></div>
</div>
<div class="p" style="left:600px;top:100px;font-size:18px;color:#334155;opacity:.5">半透明文本行</div>
""")}

PAGES['background_img'] = {'min_pct': 80, 'html': _page("""
<div class="p" style="left:100px;top:80px;width:420px;height:240px;background-image:url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%22420%22 height=%22240%22><rect width=%22420%22 height=%22240%22 fill=%22%23dbeafe%22/><circle cx=%22100%22 cy=%22120%22 r=%2270%22 fill=%22%23f59e0b%22/><rect x=%22200%22 y=%2260%22 width=%22160%22 height=%22120%22 rx=%2216%22 fill=%22%231d4ed8%22/></svg>')"></div>
<div class="p" style="left:600px;top:80px;width:300px;height:300px;border-radius:16px;overflow:hidden">
<img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAFElEQVR4nGP8z8Dwn4EIwESMolGFI0AAAAD//wMAAAABSAJ-fQAAAABJRU5ErkJggg==" style="width:100%;height:100%">
</div>
""")}

PAGES['canvas_chart'] = {'min_pct': 40, 'html': _page("""
<canvas id="c" class="p" style="left:100px;top:80px" width="700" height="420"></canvas>
<script>
const ctx = document.getElementById('c').getContext('2d');
ctx.font = '16px sans-serif'; ctx.fillStyle = '#334155';
ctx.fillText('月度交付量', 10, 20);
const bars = [[60,180],[130,260],[200,220],[270,320],[340,150],[410,280],[480,350]];
bars.forEach(([x,h],i) => {
  ctx.fillStyle = '#3b82f6';
  ctx.fillRect(x, 400-h, 46, h);
  ctx.fillStyle = '#64748b';
  ctx.fillText(String(i+1)+'月', x+6, 418);
});
ctx.strokeStyle = '#94a3b8'; ctx.beginPath(); ctx.moveTo(40,60); ctx.lineTo(40,400); ctx.lineTo(560,400); ctx.stroke();
</script>
""")}

PAGES['transform_rotate'] = {'min_pct': 40, 'html': _page("""
<div class="p" style="left:140px;top:160px;width:220px;height:120px;background:#fde68a;transform:rotate(-8deg);display:flex;align-items:center;justify-content:center"><span style="font-size:18px">倾斜卡片</span></div>
<div class="p" style="left:480px;top:160px;width:220px;height:120px;background:#bfdbfe;transform:rotate(12deg)"></div>
<div class="p" style="left:820px;top:180px;width:160px;height:160px;background:#bbf7d0;transform:scale(1.15)"></div>
""")}

PAGES['borders'] = {'min_pct': 85, 'html': _page("""
<div class="p" style="left:80px;top:80px;width:260px;height:120px;border:2px dashed #94a3b8;background:#f8fafc"></div>
<div class="p" style="left:400px;top:80px;width:260px;height:120px;border-left:6px solid #e8743b;background:#fff7ed;padding:12px;font-size:16px">左边粗条卡片</div>
<div class="p" style="left:720px;top:80px;width:260px;height:120px;border-top:1px solid #cbd5e1;border-bottom:4px solid #1d4ed8"></div>
<div class="p" style="left:80px;top:260px;width:200px;height:70px;border-bottom:24px solid #0d9488;border-left:14px solid transparent"></div>
""")}
