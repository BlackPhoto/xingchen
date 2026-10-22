# -*- coding: utf-8 -*-
"""shadow_calib.py — LO 阴影浓度标定：浏览器 vs LibreOffice 同参数实测。"""
import io, json, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
os.chdir(HERE)

import html2pptx as h
from pptx import Presentation
from pptx.util import Emu
from pptx.enum.shapes import MSO_SHAPE
from pptx.dml.color import RGBColor
from PIL import Image
from urllib.parse import quote

WORK = os.path.join(HERE, 'finalwork', 'shadowcalib')
os.makedirs(WORK, exist_ok=True)
# (alpha, blur_px, oy_px) — decks use light blue shadows on white cards
CASES = [(0.05, 16, 4), (0.12, 16, 4), (0.25, 16, 4),
         (0.12, 8, 4), (0.12, 24, 4), (0.12, 16, 12)]

# ---- HTML side ----
cells = []
for i, (a, b, oy) in enumerate(CASES):
    x, y = 60 + (i % 3) * 320, 60 + (i // 3) * 220
    cells.append('<div style="position:absolute;left:%dpx;top:%dpx;width:240px;height:120px;'
                 'background:#fff;box-shadow:0 %dpx %dpx rgba(30,91,181,%.2f)"></div>' % (x, y, oy, b, a))
html = ('<!DOCTYPE html><html><head><meta charset="utf-8"><style>*{margin:0;padding:0;box-sizing:border-box}'
        'html,body{width:1280px;height:720px}body{background:#fff}</style></head><body>' + ''.join(cells) + '</body></html>')
hp = os.path.join(WORK, 'shadows.html')
io.open(hp, 'w', encoding='utf-8').write(html)

cdp = h.CDP(9395)
cdp.start()
try:
    cdp.load('file:///' + quote(hp.replace(os.sep, '/'), safe='/:'))
    shot = os.path.join(WORK, 'shot.png')
    with open(shot, 'wb') as f:
        f.write(cdp.screenshot())
finally:
    pid = cdp.proc.pid
    try:
        if cdp.ws: cdp.ws.close()
    except Exception:
        pass
    cdp.proc.kill()
    subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)], capture_output=True)

# ---- PPTX side (same geometry, native add_shadow) ----
prs = Presentation()
prs.slide_width = Emu(int(1280 * 9525))
prs.slide_height = Emu(int(720 * 9525))
slide = prs.slides.add_slide(prs.slide_layouts[6])
bgs = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Emu(int(1280 * 9525)), Emu(int(720 * 9525)))
bgs.fill.solid(); bgs.fill.fore_color.rgb = RGBColor.from_string('FFFFFF')
bgs.line.fill.background(); bgs.shadow.inherit = False
for i, (a, b, oy) in enumerate(CASES):
    x, y = 60 + (i % 3) * 320, 60 + (i // 3) * 220
    shp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, h.E(x), h.E(y), h.E(240), h.E(120))
    shp.fill.solid(); shp.fill.fore_color.rgb = RGBColor.from_string('FFFFFF')
    shp.line.fill.background(); shp.shadow.inherit = False
    h.add_shadow(shp, {'hexs': '1E5BB5', 'alpha': a, 'ox': 0, 'oy': oy, 'blur': b})
pp = os.path.join(WORK, 'shadows.pptx')
prs.save(pp)

prof = tempfile.mkdtemp(prefix='lo_sc_')
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
doc = fitz.open(os.path.join(WORK, 'shadows.pdf'))
rp = os.path.join(WORK, 'render.png')
doc[0].get_pixmap(matrix=fitz.Matrix(96 / 72, 96 / 72)).save(rp)
doc.close()

# ---- measure: mean "blueness-darkness" in strips below/left of each card ----
def strip_dark(im, x0, y0, x1, y1):
    px = im.crop((x0, y0, x1, y1))
    data = list(px.getdata())
    # distance from white, averaged
    return sum(255 - min(r, g, b) for r, g, b in data) / len(data)

A = Image.open(shot).convert('RGB')
B = Image.open(rp).convert('RGB')
print('%-16s %10s %10s %7s' % ('case', 'browser', 'LO', 'LO/br'))
ratios = []
for i, (a, b, oy) in enumerate(CASES):
    x, y = 60 + (i % 3) * 320, 60 + (i // 3) * 220
    # strip below card: x+20..x+220, y+122..y+165
    db = strip_dark(A, x + 20, y + 124, x + 220, y + 165)
    dl = strip_dark(B, x + 20, y + 124, x + 220, y + 165)
    r = dl / db if db > 0.05 else float('nan')
    ratios.append(r)
    print('a=%.2f b=%2d oy=%2d %10.2f %10.2f %7.2f' % (a, b, oy, db, dl, r))
good = [r for r in ratios if r == r]
if good:
    print('mean LO/browser ratio: %.2f' % (sum(good) / len(good)))
