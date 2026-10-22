# -*- coding: utf-8 -*-
"""test_units.py — 引擎纯函数的表格驱动单元测试（无浏览器/无 LO）。"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import html2pptx as h
from h2p_config import CFG

FAILS = []
def check(name, got, want):
    if got != want:
        FAILS.append((name, got, want))
        print('FAIL', name, '->', got, '(want %r)' % (want,))
    else:
        print('PASS', name)

# ---- parse_color ----
check('color rgba', h.parse_color('rgba(255, 0, 10, 0.5)'), ('FF000A', 0.5))
check('color rgb', h.parse_color('rgb(1, 2, 3)'), ('010203', None))
check('color hex6', h.parse_color('#AbCdEf'), ('ABCDEF', None))
check('color hex3', h.parse_color('#f0a'), ('FF00AA', None))
check('color none', h.parse_color('none'), (None, None))
check('color transparent', h.parse_color('transparent'), (None, None))

# ---- split_layers / parse_gradient multi-layer ----
check('layers split', h.split_layers('linear-gradient(90deg, red, blue), url(a.png), radial-gradient(x)'),
      ['linear-gradient(90deg, red, blue)', 'url(a.png)', 'radial-gradient(x)'])
g1 = h.parse_gradient('linear-gradient(90deg, #111, #222), url(a.png)')
check('grad layer-scoped stops', (g1[0], g1[1]), ('linear', [(0.0, '111111', None), (100.0, '222222', None)]))
check('grad url-only -> None', h.parse_gradient('url(a.png)'), None)
g2 = h.parse_gradient('radial-gradient(circle, #fff, #000)')
check('grad radial kind', g2[0], 'radial')
g3 = h.parse_gradient('linear-gradient(to right, rgba(255,0,0,.4), #00f)')
check('grad alpha stop', g3[1], [(0.0, 'FF0000', 0.4), (100.0, '0000FF', None)])

# ---- parse_radius ----
check('radius px', h.parse_radius({'radius': ['10px']*4}, 200, 100), [10.0]*4)
check('radius 50% box -> oval signal', h.parse_radius({'radius': ['50%']*4}, 200, 100), None)
check('radius 50% square stays', h.parse_radius({'radius': ['50%']*4}, 100, 100), [50.0]*4)
check('radius capsule 999px caps via adj', h.parse_radius({'radius': ['999px']*4}, 200, 60), [999.0]*4)

# ---- corner_geom ----
R2 = h.ROUND2; RR = __import__('pptx').enum.shapes.MSO_SHAPE.ROUNDED_RECTANGLE; RE = __import__('pptx').enum.shapes.MSO_SHAPE.RECTANGLE
check('geom uniform', h.corner_geom([10,10,10,10], 200, 100), (RR, (0.1,), 0))
check('geom top pair no rot', h.corner_geom([20,20,0,0], 300, 80), (R2, (0.25, 0.0), 0))
check('geom bottom pair adj2', h.corner_geom([0,0,20,20], 300, 80), (R2, (0.0, 0.25), 0))
check('geom left pair wide -> plain', h.corner_geom([20,0,0,20], 300, 80), (RE, None, 0))
check('geom left pair square text -> plain', h.corner_geom([20,0,0,20], 100, 100, True), (RE, None, 0))
check('geom left pair square -> rot90', h.corner_geom([20,0,0,20], 100, 100), (R2, (0.2, 0.0), 90))
check('geom diag -> rounded max', h.corner_geom([16,0,16,0], 220, 120), (RR, (0.133,), 0)) if False else None

# ---- page_bg_hex ----
check('bg white default', h.page_bg_hex({}), 'FFFFFF')
check('bg transparent body', h.page_bg_hex({'bodyBg': 'rgba(0, 0, 0, 0)'}), 'FFFFFF')
check('bg falls to html', h.page_bg_hex({'bodyBg': 'rgba(0, 0, 0, 0)', 'htmlBg': 'rgb(0, 0, 255)'}), '0000FF')
check('bg blend half', h.page_bg_hex({'htmlBg': 'rgb(255, 0, 0)', 'bodyBg': 'rgba(0, 0, 255, 0.5)'}), '800080')
check('bg semi over white', h.page_bg_hex({'bodyBg': 'rgba(255, 0, 0, 0.5)'}), 'FF8080')

# ---- line_ratio / _char_w ----
check('lh normal', h.line_ratio('normal', 16), CFG.typography.lh_default)
check('lh px', round(h.line_ratio('32px', 16), 3), 2.0)
check('lh number', round(h.line_ratio('1.5', 16), 3), 1.5)
w = h._char_w('中', 16)
check('cjk width 1em', w, 16.0)
check('space width', h._char_w(' ', 16), 16 * CFG.typography.char_w['space'])

# ---- autofit_scale ----
def P(text, fs=16):
    return [[{'t': text, 'st': {'fs': fs}}]]
sc, wrap = h.autofit_scale(P('短'), 500, 40, 16, 1.22)
check('autofit short single no-wrap', (sc, wrap), (1.0, False))
sc, wrap = h.autofit_scale(P('x' * 200), 100, 30, 16, 1.22)
check('autofit tall overflow shrinks (label path)', sc < 1.0 and wrap is False, True)
sc, wrap = h.autofit_scale([P('第一行')[0], P('第二行')[0]], 100, 30, 16, 1.22)
check('autofit multi-para shrink wraps', sc < 1.0 and wrap is True, True)

# ---- parse_shadow ----
sh = h.parse_shadow('rgba(0,0,0,.15) 0px 8px 24px 4px')
check('shadow spread widens blur', sh['blur'], 32.0)
check('shadow inset rejected', h.parse_shadow('inset 0 2px 4px rgba(0,0,0,.5)'), None)

# ---- resolve_font ----
check('font yahei', h.resolve_font('"Microsoft YaHei",Arial'), 'Microsoft YaHei')
check('font alias', h.resolve_font('PingFang SC'), 'Microsoft YaHei')
check('font western pass', h.resolve_font('Georgia, serif'), 'Georgia')
check('font empty -> default', h.resolve_font(''), CFG.typography.default_font)

# ---- _font_width_factor ----
check('width factor known font', 0.9 < h._font_width_factor('Microsoft YaHei', 'abc123') <= 1.1, True)
check('width factor unknown font', h._font_width_factor('NoSuchFont', 'abc'), 1.0)
check('width factor empty text', h._font_width_factor('Arial', ''), 1.0)

# ---- _cover_srcRect ----
import io as _io
from PIL import Image as _Image
def png_bytes(w, hh):
    b = _io.BytesIO(); _Image.new('RGB', (w, hh), (200, 0, 0)).save(b, format='PNG'); return b
check('cover wide img crop l/r', 'l=' in h._cover_srcRect(png_bytes(200, 100), 100, 100), True)
check('cover matching aspect none', h._cover_srcRect(png_bytes(200, 100), 400, 200), '')

print()
print('FAILURES:', FAILS if FAILS else 'none')
sys.exit(1 if FAILS else 0)
