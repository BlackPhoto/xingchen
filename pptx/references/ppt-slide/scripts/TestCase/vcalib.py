# -*- coding: utf-8 -*-
"""vcalib.py — 垂直居中偏差标定：圆中数字 / bullet 对齐，浏览器 vs LO 实测。"""
import io, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
os.chdir(HERE)

import html2pptx as h
from urllib.parse import quote

WORK = os.path.join(HERE, 'finalwork', 'vcalib')
os.makedirs(WORK, exist_ok=True)

# 数字徽章: 圆/方 24x24..48x48, 数字 12..24px; bullet 列表
rows = []
y = 40
cases = []
for size, fs, shape in [(24, 12, '50%'), (32, 16, '50%'), (40, 20, '50%'), (32, 16, '8px'), (48, 24, '50%')]:
    rows.append('<div style="position:absolute;left:60px;top:%dpx;width:%dpx;height:%dpx;background:#1e5bb5;'
                'border-radius:%s;display:flex;align-items:center;justify-content:center">'
                '<span style="font-size:%dpx;color:#fff;font-weight:700">5</span></div>' % (y, size, size, shape, fs))
    cases.append(('badge %dx%d fs%d' % (size, size, fs), 60, y, size, size))
    y += 70
# bullet 列表
rows.append('<ul style="position:absolute;left:400px;top:40px;font-size:19px;line-height:2;width:300px">'
            '<li>平台化架构演进</li><li>数据中台建设</li><li>组织协同机制</li></ul>')
rows.append('<ul style="position:absolute;left:400px;top:220px;font-size:19px;line-height:1.4;width:300px">'
            '<li>平台化架构演进</li><li>数据中台建设</li></ul>')
html = ('<!DOCTYPE html><html><head><meta charset="utf-8"><style>*{margin:0;padding:0;box-sizing:border-box}'
        'html,body{width:1280px;height:720px}body{font-family:"Microsoft YaHei",Arial,sans-serif;background:#fff}'
        '</style></head><body>' + ''.join(rows) + '</body></html>')
hp = os.path.join(WORK, 'v.html')
io.open(hp, 'w', encoding='utf-8').write(html)

cdp = h.CDP(9397)
cdp.start()
try:
    cdp.load('file:///' + quote(hp.replace(os.sep, '/'), safe='/:'))
    with open(os.path.join(WORK, 'shot.png'), 'wb') as f:
        f.write(cdp.screenshot())
    data = cdp.evaluate(h.EXTRACT_JS)
finally:
    pid = cdp.proc.pid
    try:
        if cdp.ws: cdp.ws.close()
    except Exception:
        pass
    cdp.proc.kill()
    subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)], capture_output=True)

prs = h.Presentation()
prs.slide_width = h.Emu(int(1280 * 9525)); prs.slide_height = h.Emu(int(720 * 9525))
h.build_slide(prs, data['page'], data['els'])
pp = os.path.join(WORK, 'v.pptx')
prs.save(pp)

prof = tempfile.mkdtemp(prefix='lo_vc_')
p = subprocess.Popen([r'C:\Program Files\LibreOffice\program\soffice.exe',
    '-env:UserInstallation=file:///' + prof.replace(os.sep, '/'),
    '--headless', '--convert-to', 'pdf', '--outdir', WORK, pp],
    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
try:
    p.communicate(timeout=180)
except subprocess.TimeoutExpired:
    subprocess.run(['taskkill', '/F', '/T', '/PID', str(p.pid)], capture_output=True)
    print('LO timeout'); sys.exit(1)
import fitz
doc = fitz.open(os.path.join(WORK, 'v.pdf'))
doc[0].get_pixmap(matrix=fitz.Matrix(96 / 72, 96 / 72)).save(os.path.join(WORK, 'render.png'))
doc.close()

from PIL import Image
A = Image.open(os.path.join(WORK, 'shot.png')).convert('RGB')
B = Image.open(os.path.join(WORK, 'render.png')).convert('RGB')

def ink_vcenter(im, x0, y0, x1, y1, dark_on_light=True, bg=None):
    """glyph ink vertical center within a region; for badge: white ink on blue"""
    px = im.crop((x0, y0, x1, y1)).load()
    w, hh = x1 - x0, y1 - y0
    tot, s = 0, 0
    for yy in range(hh):
        row = 0
        for xx in range(w):
            r, g, b = px[xx, yy][:3]
            ink = (r + g + b) < 384 if dark_on_light else (r + g + b) > 500
            if ink: row += 1
        if row:
            tot += row; s += row * yy
    return (s / tot + y0) if tot else None

print('%-22s %10s %10s %8s' % ('case', 'br_center', 'LO_center', 'delta'))
for name, x, y, w, hh in cases:
    cb = ink_vcenter(A, x, y - 6, x + w, y + hh + 6, dark_on_light=False)
    cl = ink_vcenter(B, x, y - 6, x + w, y + hh + 6, dark_on_light=False)
    if cb and cl:
        print('%-22s %10.1f %10.1f %8.1f' % (name, cb, cl, cl - cb))

# bullet: 圆点与首行文字的垂直中心差 (dark ink)
for ly, tag in [(40, 'lh2.0'), (220, 'lh1.4')]:
    # marker 区域 x 400-420, 文字区 x 425-600 (第一行)
    bm = ink_vcenter(A, 396, ly, 424, ly + 50)
    lm = ink_vcenter(B, 396, ly, 424, ly + 50)
    bt = ink_vcenter(A, 428, ly, 600, ly + 34)
    lt = ink_vcenter(B, 428, ly, 600, ly + 34)
    if bm and lm and bt and lt:
        print('bullet %-6s orig(m-t)=%.1f conv(m-t)=%.1f  delta=%.1f' %
              (tag, bm - bt, lm - lt, (lm - lt) - (bm - bt)))
