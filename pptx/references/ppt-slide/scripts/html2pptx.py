# -*- coding: utf-8 -*-
"""
html2pptx.py — Generic HTML slide -> native PPTX converter.

Pipeline: headless Edge (CDP) renders the real page -> extract.js collects every
element's exact rect + computed style + inline run structure (+pseudo elements,
inline SVG geometry, tables) -> this engine maps them 1:1 onto PPTX shapes.

Incompatible CSS features are emulated by composing multiple native elements:
  linear/radial-gradient  -> gradFill XML (angle converted CSS->OOXML)
  gradient text           -> gradFill inside run rPr
  border-radius (partial) -> roundRect / round2SameRect (+rotation)
  box-shadow              -> outerShdw effectLst
  rgba colors             -> srgbClr + alpha
  letter-spacing          -> run rPr @spc
  per-side borders        -> shape line + overlay edge rects
  SVG shapes/paths        -> native freeform/oval/rect (bezier sampled)
  pseudo-elements         -> measured via DOM probe, emitted as real shapes

Usage:  python html2pptx.py page1.html page2.html ... -o deck.pptx [--dump DIR]
"""
import argparse, base64, io, json, math, os, platform, re, shutil, socket, subprocess, sys, tempfile, time, traceback
import urllib.request
from urllib.parse import quote
import websocket
from pptx import Presentation
from pptx.util import Emu, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn, nsdecls
from pptx.oxml import parse_xml

EMU_PX = 9525
import h2p_config
from h2p_config import CFG, load_profile

_INSTALLED_FONTS = None

def installed_fonts():
    """family names from the OS font registry, lowercase set.
    Windows: winreg; macOS/Linux: system_profiler / fontconfig fallback."""
    global _INSTALLED_FONTS
    if _INSTALLED_FONTS is not None: return _INSTALLED_FONTS
    out = set()
    if sys.platform == 'win32':
        try:
            import winreg
            for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    k = winreg.OpenKey(root, r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts')
                except OSError:
                    continue
                with k:
                    i = 0
                    while True:
                        try: name, _, _ = winreg.EnumValue(k, i); i += 1
                        except OSError: break
                        fam = re.sub(r'\s*\((TrueType|OpenType|PostScript|Bitmap|TrueTypeK)[^)]*\)$', '', name, flags=re.I)
                        for one in fam.split(' & '):
                            one = one.strip()
                            if one: out.add(one.lower())
        except Exception:
            pass
    elif sys.platform == 'darwin':
        try:
            r = subprocess.run(['system_profiler', 'SPFontsDataType'], capture_output=True, text=True, timeout=15)
            for line in r.stdout.splitlines():
                fam = line.strip()
                if fam and not fam.startswith(('-', ' ', 'Fonts:', 'Typeface')):
                    out.add(fam.lower())
        except Exception:
            pass
    else:
        # Linux: try fontconfig
        try:
            r = subprocess.run(['fc-list', ':', 'family'], capture_output=True, text=True, timeout=10)
            for line in r.stdout.splitlines():
                fam = line.strip()
                if fam: out.add(fam.lower())
        except Exception:
            pass
    _INSTALLED_FONTS = out
    return out

def resolve_font(ff):
    """CSS font-stack fallback, browser-style: walk the stack family by family.
    For each family: explicit alias map hit (e.g. cross-platform CJK swap) ->
    the alias target; installed on this machine -> pass through as-is;
    otherwise skip it and try the next family (same as a browser skipping a
    missing webfont). Only when every family fails do we fall back to the
    profile default. This keeps HTML and PPTX on the same effective font:
    the HTML renderer skips missing families, so must the converter.
    On macOS/Linux, installed_fonts() uses system_profiler/fc-list."""
    if not ff: return CFG.typography.default_font
    inst = installed_fonts()
    for fam in [f.strip().strip(chr(39) + '"') for f in ff.split(',')]:
        if not fam: continue
        hit = CFG.font_map.get(fam)
        if hit:
            # alias hit: honor it only when this machine can actually use it
            # (target installed), or when we have no way to know (empty set).
            if not inst or hit.lower() in inst: return hit
            continue
        if fam.lower() in inst: return fam
        # generic families (serif/sans-serif/...) and uninstalled names:
        # skip, same as a browser would
    return CFG.typography.default_font
NO_STYLE = '{2D5ABB26-0587-4C30-8999-92F81FD0307C}'
ROUND2 = getattr(MSO_SHAPE, 'ROUND_2_SAME_RECTANGLE', MSO_SHAPE.ROUNDED_RECTANGLE)

def E(px): return Emu(int(round(px * EMU_PX)))
def PT(px): return Pt(px * 0.75)

# ---------------- CSS value parsing ----------------
def parse_color(s):
    """-> (hex6, alpha01|None)"""
    if not s or s in ('none', 'transparent'): return None, None
    m = re.match(r'rgba?\(([^)]+)\)', s)
    if m:
        parts = [p.strip() for p in m.group(1).split(',')]
        r, g, b = (int(float(p)) for p in parts[:3])
        a = float(parts[3]) if len(parts) > 3 else None
        return f'{r:02X}{g:02X}{b:02X}', a
    m = re.match(r'#?([0-9a-fA-F]{6})$', s)
    if m: return m.group(1).upper(), None
    m = re.match(r'#?([0-9a-fA-F]{3})$', s)
    if m: return ''.join(c*2 for c in m.group(1)).upper(), None
    return None, None

def split_layers(s):
    """split a multi-layer background-image on top-level commas"""
    out, depth, cur = [], 0, ''
    for ch_ in s or '':
        if ch_ == '(': depth += 1
        elif ch_ == ')': depth -= 1
        if ch_ == ',' and depth == 0:
            out.append(cur); cur = ''
        else:
            cur += ch_
    if cur.strip(): out.append(cur)
    return [l_.strip() for l_ in out if l_.strip()]

def parse_gradient(s):
    """-> ('linear'|'radial', [(pos%, hex, alpha), ...], css_deg).
    Layer-scoped: parses only the first gradient layer, so stop colors of
    other layers (e.g. a url() beneath) can't leak into the stop list."""
    if not s or s == 'none': return None
    grad_layer = next((l_ for l_ in split_layers(s)
                       if re.match(r'(linear|radial)-gradient', l_)), None)
    if grad_layer is None: return None
    s = grad_layer
    kind = 'linear' if s.startswith('linear') else ('radial' if s.startswith('radial') else None)
    if kind is None: return None
    am = re.search(r'([-\d.]+)deg', s)
    if am:
        deg = float(am.group(1))
    else:
        deg = 180.0
        km = re.search(r'\bto\s+((?:top|bottom|left|right)(?:\s+(?:top|bottom|left|right))*)', s)
        if km:
            dirs = {'top': 0.0, 'right': 90.0, 'bottom': 180.0, 'left': 270.0}
            ws_ = km.group(1).split()
            if ws_: deg = sum(dirs[w_] for w_ in ws_) / len(ws_)
    stops = []
    for m in re.finditer(r'(rgba?\([^)]*\)|#[0-9a-fA-F]{3,8})\s*(-?[\d.]+)?%?', s):
        hexs, a = parse_color(m.group(1))
        pos = float(m.group(2)) if m.group(2) else None
        stops.append([pos, hexs, a])
    stops = [st for st in stops if st[1]]
    if len(stops) < 2: return None
    for i, st in enumerate(stops):
        if st[0] is None:
            st[0] = 100.0 * i / (len(stops) - 1)
    return kind, [tuple(st) for st in stops], deg

def parse_shadow(s, item=None):
    if not s or s == 'none': return None
    if re.search(r'\binset\b', s):
        warn('inset box-shadow unsupported', item)
        return None
    cm = re.search(r'(rgba?\([^)]*\)|#[0-9a-fA-F]{3,8})', s)
    if not cm: return None
    hexs, alpha = parse_color(cm.group(1))
    nums = re.findall(r'([-\d.]+)px', s)
    if len(nums) < 3: return None
    ox, oy, blur = float(nums[0]), float(nums[1]), float(nums[2])
    spread = float(nums[3]) if len(nums) > 3 else 0.0
    # OOXML has no spread radius; approximate by widening the blur
    return dict(hexs=hexs, alpha=alpha if alpha is not None else 1.0, ox=ox, oy=oy,
                blur=max(0.0, blur + 2 * spread))

def parse_radius(box, w=1, h=1):
    vals, pct = [], []
    m_ = min(w, h)
    for v in box['radius']:
        v = v or ''
        mp = re.match(r'([\d.]+)%', v)
        if mp: vals.append(float(mp.group(1)) / 100.0 * m_); pct.append(True); continue
        mp = re.match(r'([-\d.]+)px', v)
        vals.append(float(mp.group(1)) if mp else 0.0); pct.append(False)
    # 50% on every corner = ellipse (correct for non-square boxes, unlike a capped roundRect)
    if pct and all(pct) and all(v >= m_ * CFG.geometry.oval_pct for v in vals) and max(w, h) > min(w, h) * CFG.geometry.oval_aspect:
        return None  # signal: use oval
    return vals  # tl,tr,br,bl

def border_sides(box):
    """-> dict side->(w, hex, alpha) for visible sides"""
    out = {}
    for key, side in (('bt','T'), ('br_','R'), ('bb','B'), ('bl','L')):
        w, style, col = box[key]
        if w > CFG.geometry.border_px and style not in ('none', 'hidden'):
            hexs, a = parse_color(col)
            if hexs and (a is None or a > 0.01):  # skip fully transparent borders
                out[side] = (w, hexs, a, style)
    return out

def line_ratio(lh, fs):
    t = CFG.typography
    if lh in (None, 'normal'): return t.lh_default
    lh = str(lh)
    if lh.endswith('px'): return max(t.lh_min, float(lh[:-2]) / max(fs, 1))
    try: return max(t.lh_min, float(lh))
    except ValueError: return t.lh_default

def _char_w(ch, fs):
    cw = CFG.typography.char_w
    o = ord(ch)
    if o > 0x2E80: return fs * cw['cjk']
    if ch == ' ': return fs * cw['space']
    if ch.isdigit() or ch.isupper(): return fs * cw['digit_upper']
    if ch.islower(): return fs * cw['lower']
    return fs * cw['other']

def est_paras_width(paras, fs_def):
    return sum(_char_w(c, r['st'].get('fs') or fs_def) for para in paras for r in para for c in r['t'])

def autofit_scale(paras, w, h, fs_def, lh_ratio, shrink=1.0, align='left', allow_label=True, metric_slack=None):
    """-> (fontScale, wrap). Single-line content never wraps (renderers measure
    latin slightly wider than the browser -> wrapping would clip); multi-line
    content that overflows shrinks via normAutofit fontScale."""
    import math as _m
    af = CFG.autofit
    if metric_slack is None: metric_slack = af.metric_slack
    justified = align == 'justify'
    line_hs = []
    widths = []
    for para in paras:
        fs = max((r['st'].get('fs') or fs_def) for r in para) if para else fs_def
        width = sum(_char_w(c, r['st'].get('fs') or fs_def) for r in para for c in r['t'])
        cap = max(w - af.cap_reserve_chars * fs_def, af.cap_floor_px)   # reserve ~1 char for renderer wrap variance
        lines = 1 if width <= w else _m.ceil(width / cap - af.line_round_eps)
        widths.append((width, lines, fs))
        line_hs.append(lines * fs * max(lh_ratio, 1.0))
    total_h = sum(line_hs) + (len(paras) - 1) * fs_def * af.para_gap if paras else 0.0
    multi = any(l[1] > 1 for l in widths)
    if not widths: return 1.0, True
    if total_h <= h:
        if multi: return 1.0, True
        # single-line content with wrap disabled: cannot clip, keep natural size
        return 1.0, False
    fs_max = max((r['st'].get('fs') or fs_def) for para in paras for r in para) if paras else fs_def
    line_h = fs_max * max(lh_ratio, 1.0)
    if allow_label and len(paras) == 1 and widths[0][1] >= 2 and h < line_h * af.label_lines:
        # label: content wraps to >=2 lines but the box only fits one —
        # drop wrapping and micro-shrink so one line fits in every renderer
        scale = min(1.0, w / (max(widths[0][0], 1.0) * metric_slack))
        return _m.floor(scale * af.step) / af.step, False
    scale = max(af.scale_floor, min(1.0, h * shrink / total_h))
    return _m.floor(scale * af.step) / af.step, True

def scale_paras(paras, scale, fs_def):
    if not paras or scale >= 1.0: return paras
    return [[dict(rr_, st=dict(rr_['st'], fs=(rr_['st'].get('fs') or fs_def) * scale)) for rr_ in p_] for p_ in paras]

ALIGN = {'left': PP_ALIGN.LEFT, 'start': PP_ALIGN.LEFT, 'center': PP_ALIGN.CENTER,
         'right': PP_ALIGN.RIGHT, 'end': PP_ALIGN.RIGHT, 'justify': PP_ALIGN.JUSTIFY}

# ---------------- text: measured per-line mode (schema 2) ----------------
TEXT_MODE = ['line']   # 'line' = one textbox per browser-measured visual line; 'flow' = legacy estimation
# 标定数据的加载与查询已整合进 h2p_config（含 font_metrics.json 路径与回退策略）
_load_font_metrics = h2p_config.load_font_metrics
_font_width_factor = h2p_config.font_width_factor

_load_font_metrics()

def emit_line_texts(slide, item, op=1.0):
    """one textbox per browser-measured visual line: wrap off, rect = line box,
    no width estimation. The only remaining guess is the per-font renderer width
    factor from font_metrics.json (1.0 when unmeasured)."""
    box = item.get('box') or {}
    col_def, _ = parse_color(box.get('col'))
    col_def = col_def or CFG.typography.default_color
    font = resolve_font(box.get('ff'))
    fs_box = box.get('fs') or CFG.typography.default_fs
    lh_ratio = line_ratio(box.get('lh'), fs_box)
    tbs = []
    for ln_i, ln in enumerate(item.get('lines') or []):
        runs = [r for r in (ln.get('runs') or []) if r.get('t')]
        if not runs: continue
        rect = ln['rect']
        # measured safety: if this font lays out wider in the renderer than in the
        # browser (ratio > 1, e.g. DengXian latin in LO), shrink by exactly that factor
        den = sum(len(r['t']) for r in runs)
        wf = sum(_font_width_factor(font, r['t']) * len(r['t']) for r in runs) / den if den else 1.0
        # bold variants lay out wider than the measured regular-weight factors
        if any(str(r['st'].get('fw') or '') in ('bold', 'bolder') or
               (str(r['st'].get('fw') or '').isdigit() and int(r['st'].get('fw')) >= CFG.typography.bold_threshold)
               for r in runs):
            wf = max(wf, 1.0) * 1.07
        scale = max(0.5, 1.0 / wf) if wf > 1.0 else 1.0
        para = [dict(r, st=dict(r['st'], fs=(r['st'].get('fs') or fs_box) * scale)) if scale < 1.0 else r
                for r in runs]
        # width headroom: renderers draw runs a few % wider than the browser
        # (esp. bold) — without slack LibreOffice wraps at the exact-fit box
        # reconstruct the true line box: Range rects measure the GLYPH box, which
        # sits centered inside the CSS line box — a box shorter than its exact
        # line spacing makes LO misposition vertically (lists with line-height>1)
        # reconstruction must use the RUN's own size, not the box default —
        # a 13px run in a 16px box would over-expand and neighbouring line
        # boxes would overlap (small multi-line cards)
        fs_line = max((r['st'].get('fs') or fs_box) for r in runs)
        need_h = fs_line * lh_ratio
        ry = rect['y']
        if rect['h'] + 1 < need_h:
            ry -= (need_h - rect['h']) / 2
        tb = slide.shapes.add_textbox(E(rect['x']), E(ry),
                                      E(rect['w'] * 1.05 + 8), E(max(rect['h'], need_h)))
        tf = tb.text_frame
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        tf.word_wrap = False
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        fs_def = max((r['st'].get('fs') or fs_box) for r in runs)
        _fill_frame(tf, [para], box, 'left', lh_ratio, fs_def, col_def, op=op, font=font, line_spacing=False)
        tbs.append(tb)
    return tbs

# ---------------- low-level pptx helpers ----------------
def _spPr(shape): return shape._element.spPr

def _no_theme(shape):
    """drop the <p:style> theme ref add_shape injects: its effectRef idx=2 is a
    35%-black outer shadow which LibreOffice renders even under an explicit
    empty <a:effectLst/> — the source of the 'shadow abuse' on every converted
    deck. All our shapes declare fill/line/effects explicitly, so the theme
    reference is pure noise."""
    el = shape._element
    st = el.find(qn('p:style'))
    if st is not None: el.remove(st)

def _grad_xml(stops, css_deg):
    ang = int(round(((css_deg - 90) % 360) * 60000))
    gs = ''
    for pos, hexs, a in stops:
        al = f'<a:alpha val="{int(a*100000)}"/>' if a is not None else ''
        gs += f'<a:gs pos="{int(pos*1000)}"><a:srgbClr val="{hexs}">{al}</a:srgbClr></a:gs>'
    return f'<a:gradFill {nsdecls("a")} rotWithShape="1"><a:gsLst>{gs}</a:gsLst><a:lin ang="{ang}" scaled="0"/></a:gradFill>'

def _radial_xml(stops):
    gs = ''
    for pos, hexs, a in stops:
        al = f'<a:alpha val="{int(a*100000)}"/>' if a is not None else ''
        gs += f'<a:gs pos="{int(pos*1000)}"><a:srgbClr val="{hexs}">{al}</a:srgbClr></a:gs>'
    return (f'<a:gradFill {nsdecls("a")} rotWithShape="1"><a:gsLst>{gs}</a:gsLst>'
            f'<a:path path="circle"><a:fillToRect l="50000" t="50000" r="50000" b="50000"/></a:path></a:gradFill>')

def set_fill_grad(shape, grad):
    sp = _spPr(shape)
    for t in ('a:noFill','a:solidFill','a:gradFill','a:blipFill','a:pattFill','a:grpFill'):
        for e in sp.findall(qn(t)): sp.remove(e)
    kind, stops, deg = grad
    xml = _radial_xml(stops) if kind == 'radial' else _grad_xml(stops, deg)
    geom = sp.find(qn('a:prstGeom'))
    if geom is None: geom = sp.find(qn('a:custGeom'))
    geom.addnext(parse_xml(xml))

def solid(shape, hexs, alpha=None):
    shape.fill.solid(); shape.fill.fore_color.rgb = RGBColor.from_string(hexs)
    if alpha is not None:
        sF = _spPr(shape).find(qn('a:solidFill')); clr = sF.find(qn('a:srgbClr'))
        clr.append(clr.makeelement(qn('a:alpha'), {'val': str(int(alpha*100000))}))

def _add_line(slide, x1, y1, x2, y2, sh):
    """native straight connector for SVG <line> / two-point <path> — crisper
    than a sampled freeform, editable, and supports native line-end arrows"""
    from pptx.enum.shapes import MSO_CONNECTOR
    conn = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, E(x1), E(y1), E(x2), E(y2))
    _no_theme(conn)
    conn.shadow.inherit = False
    st_hex, st_a = parse_color(sh.get('stroke'))
    sw = sh.get('sw') or 1
    if not st_hex:
        st_hex = '000000'
    conn.line.color.rgb = RGBColor.from_string(st_hex)
    conn.line.width = PT(sw)
    if st_a is not None and st_a < 0.999:
        lnEl = _spPr(conn).find(qn('a:ln'))
        clr = lnEl.find(qn('a:solidFill'))
        clr = clr.find(qn('a:srgbClr')) if clr is not None else None
        if clr is not None:
            clr.append(clr.makeelement(qn('a:alpha'), {'val': str(int(st_a * 100000))}))
    dash = sh.get('dash')
    if dash:
        lnEl = _spPr(conn).find(qn('a:ln'))
        d = lnEl.find(qn('a:prstDash'))
        if d is None:
            d = lnEl.makeelement(qn('a:prstDash'), {}); lnEl.append(d)
        nums = [float(x) for x in re.findall(r'[\d.]+', dash)]
        d.set('val', 'sysDot' if (nums and nums[0] <= 2) else 'sysDash')
    if sh.get('cap') == 'round':
        lnEl = _spPr(conn).find(qn('a:ln'))
        lnEl.set('cap', 'rnd')
    if sh.get('markerEnd'):
        lnEl = _spPr(conn).find(qn('a:ln'))
        lnEl.append(parse_xml('<a:tailEnd %s type="triangle" w="med" len="med"/>' % nsdecls('a')))
    return conn


def add_shadow(shape, sh):
    sp = _spPr(shape)
    old = sp.find(qn('a:effectLst'))
    if old is not None: sp.remove(old)
    import math
    dist = math.hypot(sh['ox'], sh['oy'])
    dirdeg = (math.degrees(math.atan2(sh['oy'], sh['ox']))) % 360
    xml = (f'<a:effectLst {nsdecls("a")}><a:outerShdw blurRad="{int(sh["blur"]*EMU_PX)}" '
           f'dist="{int(dist*EMU_PX)}" dir="{int(dirdeg*60000)}" rotWithShape="0">'
           f'<a:srgbClr val="{sh["hexs"]}"><a:alpha val="{int(sh["alpha"]*100000)}"/></a:srgbClr>'
           f'</a:outerShdw></a:effectLst>')
    sp.append(parse_xml(xml))

# ---------------- text ----------------
SPACING = [False]

def _style_run(r, st, default_fs, default_col, default_lh=None, op=1.0, font=None):
    font = font or CFG.typography.default_font
    fs = st.get('fs') or default_fs
    hexs, a = parse_color(st.get('color')) or (None, None)
    col = hexs or default_col
    f = r.font
    f.size = PT(fs)
    fw = str(st.get('fw') or '400')
    f.bold = (fw in ('bold', 'bolder')) or (fw.isdigit() and int(fw) >= CFG.typography.bold_threshold)
    if str(st.get('fst')) in ('italic', 'oblique'): f.italic = True
    f.name = font
    rPr = r._r.get_or_add_rPr()
    for tag in ('a:ea', 'a:cs'):
        e = rPr.find(qn(tag))
        if e is None: e = rPr.makeelement(qn(tag), {}); rPr.append(e)
        e.set('typeface', font)
    ls = st.get('ls') or 0
    if ls and SPACING[0]: rPr.set('spc', str(int(round(ls * 75))))
    td = str(st.get('td') or '')
    if 'underline' in td: f.underline = True
    if 'line-through' in td: rPr.set('strike', 'sngStrike')
    grad = parse_gradient(st.get('bgImg')) if st.get('bgClip') == 'text' else None
    if grad and grad[0] == 'linear':
        # gradient text degrades to primary stop color (LibreOffice/WPS paint an opaque block otherwise)
        f.color.rgb = RGBColor.from_string(grad[1][0][1])
    elif col:
        f.color.rgb = RGBColor.from_string(col)
        eff = (a if a is not None else 1.0) * (op if op is not None else 1.0)
        if eff < 0.999:
            sF = rPr.find(qn('a:solidFill')); clr = sF.find(qn('a:srgbClr'))
            clr.append(clr.makeelement(qn('a:alpha'), {'val': str(int(eff*100000))}))

def _fill_frame(tf, paras, box, align, lh_ratio, fs_def, col_def, op=1.0, font=None, line_spacing=True):
    # NOTE: word_wrap is owned by the caller (autofit policy decides per box)
    first = True
    for para in paras:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.alignment = ALIGN.get(align, PP_ALIGN.LEFT)
        # exact line height in points (CSS fs*lh) — float multiples drift because
        # PPT/LO "single spacing" is font-metric based, accumulating offsets per line
        fs_para = max((r_['st'].get('fs') or fs_def) for r_ in para) if para else fs_def
        # fs is in CSS px; Pt() expects points — px→pt is ×0.75. Passing px as pt
        # inflated every exact line spacing by 4/3, sinking all text and clipping
        # small boxes (line box 48px in a 36px box)
        # single-line boxes (line mode) must NOT set exact spacing: LO places the
        # baseline at the BOTTOM of a fixed-height line (top+lnSpc-descent), while
        # the browser half-leads around the glyphs — at line-height:2 that sinks
        # text ~6px; anchor=ctr on the natural line matches the browser instead
        if line_spacing:
            p.line_spacing = Pt(fs_para * lh_ratio * 0.75)
        # trim outer whitespace across runs (unless white-space:pre content)
        if para and not para[0]['st'].get('pre'):
            para[0]['t'] = para[0]['t'].lstrip()
            para[-1]['t'] = para[-1]['t'].rstrip()
        for sp_ in para:
            if not sp_['t']: continue
            r = p.add_run()
            r.text = sp_['t']
            _style_run(r, sp_['st'], sp_.get('st', {}).get('fs') or fs_def, col_def, op=op, font=font)

def flex_text_align(box, align):
    """flex centering (justify/align) implies text centering for single text blocks"""
    if str(box.get('display', '')).startswith('flex') and box.get('jc') == 'center':
        return 'center'
    return align

def emit_text(slide, item):
    if TEXT_MODE[0] == 'line' and item.get('lines'):
        tbs = emit_line_texts(slide, item, op=(item.get('box') or {}).get('opacity', 1) or 1)
        if tbs: return tbs[-1]
        # lines unusable -> fall through to flow
    r = item['rect']; box = item['box']
    tb = slide.shapes.add_textbox(E(r['x']), E(r['y']), E(r['w']), E(r['h']))
    tf = tb.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    fs_def = box.get('fs') or CFG.typography.default_fs
    lh_ratio = line_ratio(box['lh'], fs_def)
    scale, wrap = autofit_scale(item['paras'], r['w'], r['h'], fs_def, lh_ratio, align=box['ta'])
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE if not wrap else MSO_ANCHOR.TOP
    tf.word_wrap = wrap
    hexs, _ = parse_color(box['col'])
    _fill_frame(tf, scale_paras(item['paras'], scale, fs_def), box, flex_text_align(box, box['ta']), lh_ratio, fs_def, hexs or CFG.typography.default_color, op=box.get('opacity', 1) or 1, font=resolve_font(box.get('ff')))
    return tb

# ---------------- images ----------------
PAGE_URL = ['']

def parse_bg_url(bgImg):
    if not bgImg or bgImg == 'none': return None
    for l_ in split_layers(bgImg):
        m = re.match(r'url\((["\']?)([^"\')]+)\1\)', l_)
        if m: return m.group(2)
    return None

def resolve_src(src):
    import base64 as _b64, io as _io
    if src.startswith('data:image'):
        try:
            return _io.BytesIO(_b64.b64decode(src.split(',', 1)[1]))
        except Exception:
            return None
    if src.startswith(('http://', 'https://')):
        try:
            return _io.BytesIO(urllib.request.urlopen(src, timeout=15).read())
        except Exception:
            return None
    from urllib.parse import urljoin, urlparse, unquote
    full = urljoin(PAGE_URL[0], src)
    if full.startswith('file:'):
        p = unquote(urlparse(full).path)
        m = re.match(r'^/([A-Za-z]:.*)$', p)
        return m.group(1) if m else p
    return full

def _cover_srcRect(src, w, h):
    try:
        import io as _io, io
        from PIL import Image
        if isinstance(src, (_io.BytesIO,)):
            src.seek(0)
            im = Image.open(_io.BytesIO(src.getvalue()))
        else:
            im = Image.open(src)
        iw, ih = im.size
    except Exception:
        return ''
    if iw < 2 or ih < 2: return ''
    ba, ia = w / max(h, 1), iw / max(ih, 1)
    if abs(ba - ia) < 0.02: return ''
    if ia > ba:
        off = (1 - ba / ia) / 2
        return f' l="{int(off*100000)}" r="{int(off*100000)}"'
    off = (1 - ia / ba) / 2
    return f' t="{int(off*100000)}" b="{int(off*100000)}"'

def apply_blip_fill(slide, shp, bg_url, box, item=None):
    try:
        src = resolve_src(bg_url)
        if src is None:
            warn('background image unresolvable: %s' % bg_url[:80], item); return False
        image_part, rId = slide.part.get_or_add_image_part(src)
        sp = _spPr(shp)
        for tg in ('a:noFill','a:solidFill','a:gradFill','a:blipFill','a:pattFill','a:grpFill'):
            for e in sp.findall(qn(tg)): sp.remove(e)
        crop = ''
        if 'cover' in str(box.get('bs') or ''):
            crop = _cover_srcRect(src, shp.width / EMU_PX, shp.height / EMU_PX)
        xml = (f'<a:blipFill {nsdecls("a","r")}><a:blip r:embed="{rId}"/><a:srcRect{crop}/>'
               f'<a:stretch><a:fillRect/></a:stretch></a:blipFill>')
        geom = sp.find(qn('a:prstGeom'))
        if geom is None: geom = sp.find(qn('a:custGeom'))
        geom.addnext(parse_xml(xml))
        return True
    except Exception as e:
        warn('background image failed: %s' % e, item)
        return False

def emit_image(slide, item, page):
    r = item['rect']
    src = resolve_src(item['src'])
    if src is None:
        warn('image unresolvable: %s' % str(item.get('src'))[:80], item, dropped=True)
        return None
    try:
        pic = slide.shapes.add_picture(src, E(r['x']), E(r['y']), E(r['w']), E(r['h']))
    except Exception as e:
        warn('image embed failed: %s' % e, item, dropped=True)
        return None
    pic.shadow.inherit = False
    fit = item.get('fit')
    if fit == 'cover':
        try:
            from PIL import Image as _im
            src.seek(0) if hasattr(src, 'seek') else None
            _i = _im.open(src if hasattr(src, 'getvalue') or hasattr(src, 'seek') else src)
            iw, ih = _i.size
            ba, ia = r['w'] / max(r['h'], 1), iw / max(ih, 1)
            if abs(ba - ia) >= 0.02:
                if ia > ba:
                    off = int((1 - ba / ia) / 2 * 100000)
                    crop_attrs = f' l="{off}" r="{off}"'
                else:
                    off = int((1 - ia / ba) / 2 * 100000)
                    crop_attrs = f' t="{off}" b="{off}"'
                bf = pic._element.find(qn('p:blipFill'))
                if bf is not None:
                    sr = parse_xml(f'<a:srcRect {nsdecls("a")}{crop_attrs}/>')
                    bf.find(qn('a:blip')).addnext(sr)
        except Exception as e:
            warn('img cover crop failed: %s' % e, item)
    elif fit and fit not in ('fill', 'none', 'scale-down'):
        warn('img object-fit:%s approximated as fill' % fit, item)
    rad = parse_radius({'radius': [item.get('radius') or '0'] * 4}, r['w'], r['h'])
    if rad and max(rad) > CFG.geometry.img_radius_min:
        try:
            sp = pic._element.spPr
            g = sp.find(qn('a:prstGeom'))
            if g is not None: sp.remove(g)
            av = max(0.0, min(CFG.geometry.adj_cap, max(rad) / min(r['w'], r['h'])))
            sp.append(parse_xml(f'<a:prstGeom {nsdecls("a")} prst="roundRect">'
                                f'<a:avLst><a:gd name="adj" fmla="val {int(av*100000)}"/></a:avLst></a:prstGeom>'))
        except Exception as e:
            warn('image radius failed: %s' % e, item)
    return pic

def _set_line_dash(shp, style):
    lnEl = _spPr(shp).find(qn('a:ln'))
    if lnEl is None: return
    d = lnEl.find(qn('a:prstDash'))
    if d is None:
        d = lnEl.makeelement(qn('a:prstDash'), {}); lnEl.append(d)
    d.set('val', 'sysDash' if style == 'dashed' else 'sysDot')

# ---------------- box emitter ----------------
def corner_geom(vals, w, h, has_text=False):
    """-> (geom, adjustments tuple|None, rotation). ROUND2's adj1 rounds the two
    TOP corners and adj2 the two BOTTOM ones, so top/bottom pairs need no
    rotation at all. Left/right pairs need rot=90/270, which turns the whole
    shape sideways (a wide bar becomes a tall sliver, embedded text included)
    -> only safe for square-ish, text-free boxes; else fall back to square."""
    tl, tr, br, bl = vals
    m = min(w, h)
    def adj(r): return max(0.0, min(0.5, r / m))
    def plain(): return (MSO_SHAPE.RECTANGLE, None, 0)
    if tl == tr == br == bl:
        return (MSO_SHAPE.ROUNDED_RECTANGLE, (adj(tl),), 0) if tl > CFG.geometry.corner_min else plain()
    if tl > 0.5 and tr > 0.5 and br <= 0.5 and bl <= 0.5:
        return (ROUND2, (adj(max(tl, tr)), 0.0), 0)
    if br > 0.5 and bl > 0.5 and tl <= 0.5 and tr <= 0.5:
        return (ROUND2, (0.0, adj(max(br, bl))), 0)
    sideways_ok = abs(w - h) <= CFG.geometry.corner_square_eps and not has_text
    if tl > 0.5 and bl > 0.5 and tr <= 0.5 and br <= 0.5:
        return (ROUND2, (adj(max(tl, bl)), 0.0), 90) if sideways_ok else plain()
    if tr > 0.5 and br > 0.5 and tl <= 0.5 and bl <= 0.5:
        return (ROUND2, (adj(max(tr, br)), 0.0), 270) if sideways_ok else plain()
    mx = max(vals)
    return (MSO_SHAPE.ROUNDED_RECTANGLE, (adj(mx),), 0) if mx > CFG.geometry.corner_min else plain()

def emit_box(slide, item):
    r = item['rect']; box = item['box']
    if item.get('kind') == 'polyclip' or item.get('pts'):
        # clip-path polygon -> native freeform with the box's fill; text emits
        # as an overlay textbox (kept editable)
        pts = [(r['x'] + nx * r['w'], r['y'] + ny * r['h']) for nx, ny in item['pts']]
        shp = _freeform(slide, pts, True)
        op = box.get('opacity', 1) or 1
        grad = parse_gradient(box.get('bgImg'))
        bgs, bga = parse_color(box.get('bg'))
        if grad:
            if op < 0.999:
                k, stops, dg = grad
                grad = (k, [(p_, h_, (a_ if a_ is not None else 1.0) * op) for p_, h_, a_ in stops], dg)
            set_fill_grad(shp, grad)
        elif bgs and not (bga is not None and bga <= 0.001):
            eff = (bga if bga is not None else 1.0) * op
            solid(shp, bgs, eff if eff < 0.999 else None)
        else:
            shp.fill.background()
        if item.get('lines') and TEXT_MODE[0] == 'line':
            emit_line_texts(slide, item, op=op)
        elif item.get('paras'):
            emit_text(slide, dict(item, kind='text'))
        return shp
    x, y, w, h = r['x'], r['y'], r['w'], r['h']
    if w <= 0.5 or h <= 0.5:
        # degenerate styled box with visible text: emit a text box at extract.js's
        # minimum content size instead of a 0-size shape
        if item.get('paras'):
            return emit_text(slide, dict(item, rect=dict(r, w=max(w, 8.0), h=max(h, 14.0))))
        return None
    grad = parse_gradient(box['bgImg'])
    bg_url = parse_bg_url(box['bgImg'])
    bgs, bga = parse_color(box['bg'])
    if bgs and bga is not None and bga <= 0.001: bgs, bga = None, None  # fully transparent
    op = box.get('opacity', 1) or 1
    radius = parse_radius(box, w, h)
    if radius is None:
        shp = slide.shapes.add_shape(MSO_SHAPE.OVAL, E(x), E(y), E(w), E(h))
        _no_theme(shp)
        shp.shadow.inherit = False
        grad0 = parse_gradient(box['bgImg'])
        bgs0, bga0 = parse_color(box['bg'])
        if bgs0 and bga0 is not None and bga0 <= 0.001: bgs0, bga0 = None, None
        if grad0: set_fill_grad(shp, grad0)
        elif bgs0:
            eff0 = (bga0 if bga0 is not None else 1.0) * op
            solid(shp, bgs0, eff0 if eff0 < 0.999 else None)
        elif bg_url: apply_blip_fill(slide, shp, bg_url, box)
        else: shp.fill.background()
        sides0 = border_sides(box)
        if sides0 and len(sides0) == 4:
            sw0, shex0, sa0, sty0 = list(sides0.values())[0]
            shp.line.color.rgb = RGBColor.from_string(shex0); shp.line.width = PT(sw0)
            if sty0 in ('dashed', 'dotted'): _set_line_dash(shp, sty0)
        else:
            shp.line.fill.background()
        if box.get('shadow'):
            sh0 = parse_shadow(box['shadow'], item)
            if sh0: add_shadow(shp, sh0)
        if TEXT_MODE[0] == 'line' and item.get('lines'):
            emit_line_texts(slide, item, op=op)
        elif item.get('paras'):
            tf0 = shp.text_frame
            tf0.margin_left, tf0.margin_right = E(box['pl']), E(box['pr'])
            tf0.margin_top, tf0.margin_bottom = E(box['pt']), E(box['pb'])
            fs0 = box.get('fs') or CFG.typography.default_fs
            lh0 = line_ratio(box['lh'], fs0)
            sc0, wr0 = autofit_scale(item['paras'], w - box['pl'] - box['pr'], h - box['pt'] - box['pb'], fs0, lh0, align=box['ta'])
            vcenter0 = str(box.get('display', '')).startswith('flex') and box.get('ai') == 'center'
            if not wr0: vcenter0 = True
            tf0.vertical_anchor = MSO_ANCHOR.MIDDLE if vcenter0 else MSO_ANCHOR.TOP
            tf0.word_wrap = wr0
            hexs0, _ = parse_color(box['col'])
            _fill_frame(tf0, scale_paras(item['paras'], sc0, fs0), box, box['ta'], lh0, fs0, hexs0 or CFG.typography.default_color, op=op)
        return shp
    geom, adjs, rot = corner_geom(radius, w, h, has_text=bool(item.get('paras')))
    shp = slide.shapes.add_shape(geom, E(x), E(y), E(w), E(h))
    _no_theme(shp)
    shp.shadow.inherit = False
    if adjs:
        try:
            for i, v in enumerate(adjs): shp.adjustments[i] = v
        except Exception as e:
            warn('shape adjustment failed: %s' % e, item)
    if rot: shp.rotation = rot
    # CSS triangle: small box with exactly one thick colored border (arrowhead pattern)
    sides_all = border_sides(box)
    if not grad and not bgs and len(sides_all) == 1 and not item.get('paras'):
        side, (sw_, shex_, sa_, _sty) = next(iter(sides_all.items()))
        if sw_ >= CFG.geometry.tri_sw_min and w <= sw_ * CFG.geometry.tri_w_factor and h <= sw_ * CFG.geometry.tri_h_factor:
            if side == 'L':   pts = [(x, y), (x + w, y + h / 2), (x, y + h)]
            elif side == 'R': pts = [(x + w, y), (x, y + h / 2), (x + w, y + h)]
            elif side == 'T': pts = [(x, y), (x + w / 2, y + h), (x + w, y)]
            else:             pts = [(x, y + h), (x + w / 2, y), (x + w, y + h)]
            tri = _freeform(slide, pts, True)
            solid(tri, shex_, sa_)
            tri.line.fill.background()
            shp._element.getparent().remove(shp._element)
            return tri
    # fill
    if grad:
        if op < 0.999:
            k, stops, dg = grad
            stops = [(p_, h_, (a_ if a_ is not None else 1.0) * op) for p_, h_, a_ in stops]
            grad = (k, stops, dg)
        set_fill_grad(shp, grad)
    elif bg_url: apply_blip_fill(slide, shp, bg_url, box)
    elif bgs:
        eff = (bga if bga is not None else 1.0) * op
        solid(shp, bgs, eff if eff < 0.999 else None)
    else: shp.fill.background()
    # borders (composite)
    sides = border_sides(box)
    if sides:
        keyset = {(round(v[0], 1), v[1]) for v in sides.values()}
        if len(keyset) == 1 and len(sides) == 4:
            sw, shex, sa, sty = list(sides.values())[0]
            shp.line.color.rgb = RGBColor.from_string(shex); shp.line.width = PT(sw)
            if sty in ('dashed', 'dotted'): _set_line_dash(shp, sty)
            if sa is not None:
                lnEl = _spPr(shp).find(qn('a:ln')); sF = lnEl.find(qn('a:solidFill'))
                clr = sF.find(qn('a:srgbClr'))
                clr.append(clr.makeelement(qn('a:alpha'), {'val': str(int(sa*100000))}))
        else:
            shp.line.fill.background()
            base = {}
            for side, (sw, shex, sa, sty) in sides.items(): base.setdefault((sw, shex), 0)
            for side, (sw, shex, sa, sty) in sides.items(): base[(sw, shex)] += 1
            uniform = max(base, key=base.get)
            # draw uniform ring if >=3 sides share it
            cnt = base[uniform]
            if cnt >= 3:
                sw, shex = uniform
                shp.line.color.rgb = RGBColor.from_string(shex); shp.line.width = PT(sw)
            for side, (sw, shex, sa, sty) in sides.items():
                if cnt >= 3 and (sw, shex) == uniform: continue
                if side == 'T': ov = add_rect(slide, x, y, w, sw, fill=shex)
                elif side == 'B': ov = add_rect(slide, x, y + h - sw, w, sw, fill=shex)
                elif side == 'L': ov = add_rect(slide, x, y, sw, h, fill=shex)
                else: ov = add_rect(slide, x + w - sw, y, sw, h, fill=shex)
    else:
        shp.line.fill.background()
    if box.get('shadow'):
        sh = parse_shadow(box['shadow'], item)
        if sh: add_shadow(shp, sh)
    # text inside shape
    if TEXT_MODE[0] == 'line' and item.get('lines'):
        emit_line_texts(slide, item, op=op)
    elif item.get('paras'):
        tf = shp.text_frame
        tf.margin_left, tf.margin_right = E(box['pl']), E(box['pr'])
        tf.margin_top, tf.margin_bottom = E(box['pt']), E(box['pb'])
        vcenter = str(box.get('display', '')).startswith('flex') and box.get('ai') == 'center'
        fs_def = box.get('fs') or CFG.typography.default_fs
        lh_ratio = line_ratio(box['lh'], fs_def)
        cw, chh = w - box['pl'] - box['pr'], h - box['pt'] - box['pb']
        scale, wrap = autofit_scale(item['paras'], cw, chh, fs_def, lh_ratio, align=box['ta'])
        if not wrap: vcenter = True   # single-line labels center vertically
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE if vcenter else MSO_ANCHOR.TOP
        tf.word_wrap = wrap
        hexs, _ = parse_color(box['col'])
        _fill_frame(tf, scale_paras(item['paras'], scale, fs_def), box, flex_text_align(box, box['ta']), lh_ratio, fs_def, hexs or CFG.typography.default_color, op=op, font=resolve_font(box['ff']))
    return shp

# ---------------- SVG ----------------
def _tok_path(d):
    return re.findall(r'([MmZzLlHhVvCcSsQqTtAa])|([+-]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?)', d)

def sample_path(d, sx, sy, ox, oy):
    toks = _tok_path(d)
    subs = []; cur = []; closed = False
    i = 0; cmd = None; cx = cy = 0.0; sx0 = sy0 = 0.0; pcx = pcy = None; qcx = qcy = None
    nums = []
    def flush():
        nonlocal cur, closed
        if len(cur) >= 2: subs.append((cur, closed))
        cur = []; closed = False
    def P(x, y):
        cur.append((x * sx + ox, y * sy + oy))
    def cubic(x0, y0, x1, y1, x2, y2, x3, y3, n=12):
        for k in range(1, n + 1):
            t = k / n; mt = 1 - t
            bx = mt**3*x0 + 3*mt*mt*t*x1 + 3*mt*t*t*x2 + t**3*x3
            by = mt**3*y0 + 3*mt*mt*t*y1 + 3*mt*t*t*y2 + t**3*y3
            P(bx, by)
    def quad(x0, y0, x1, y1, x2, y2, n=10):
        for k in range(1, n + 1):
            t = k / n; mt = 1 - t
            P(mt*mt*x0 + 2*mt*t*x1 + t*t*x2, mt*mt*y0 + 2*mt*t*y1 + t*t*y2)
    def arc(x0, y0, rx, ry, phi, laf, sf, x1, y1, n=20):
        rx, ry = abs(rx), abs(ry)
        if rx == 0 or ry == 0: P(x1, y1); return
        phi = math.radians(phi)
        dx2, dy2 = (x0 - x1) / 2, (y0 - y1) / 2
        x1p = math.cos(phi)*dx2 + math.sin(phi)*dy2
        y1p = -math.sin(phi)*dx2 + math.cos(phi)*dy2
        lam = x1p**2/rx**2 + y1p**2/ry**2
        if lam > 1: s = math.sqrt(lam); rx *= s; ry *= s
        num = rx**2*ry**2 - rx**2*y1p**2 - ry**2*x1p**2
        den = rx**2*y1p**2 + ry**2*x1p**2
        co = math.sqrt(max(0.0, num/den)) * (1 if laf != sf else -1)
        cxp = co*rx*y1p/ry; cyp = -co*ry*x1p/rx
        ccx = math.cos(phi)*cxp - math.sin(phi)*cyp + (x0+x1)/2
        ccy = math.sin(phi)*cxp + math.cos(phi)*cyp + (y0+y1)/2
        def ang(ux, uy, vx, vy):
            d = math.hypot(ux, uy) * math.hypot(vx, vy)
            c = max(-1, min(1, (ux*vx + uy*vy) / d))
            a = math.acos(c)
            if ux*vy - uy*vx < 0: a = -a
            return a
        th1 = ang(1, 0, (x1p-cxp)/rx, (y1p-cyp)/ry)
        dth = ang((x1p-cxp)/rx, (y1p-cyp)/ry, (-x1p-cxp)/rx, (-y1p-cyp)/ry)
        # SVG sweep=1 draws in the positive-angle direction (screen coords, y down);
        # sweep=0 draws negative. (Signs were inverted, drawing huge wrong-way arcs.)
        if not sf and dth > 0: dth -= 2*math.pi
        if sf and dth < 0: dth += 2*math.pi
        for k in range(1, n + 1):
            t = k / n; th = th1 + dth*t
            P(ccx + rx*math.cos(th)*math.cos(phi) - ry*math.sin(th)*math.sin(phi),
              ccy + rx*math.cos(th)*math.sin(phi) + ry*math.sin(th)*math.cos(phi))
    while i < len(toks):
        t = toks[i]
        if t[0]:
            cmd = t[0]
            if cmd == 'Z' or cmd == 'z':
                if cur: P(sx0, sy0)
                closed = True; flush()
                i += 1; continue
            i += 1
        else:
            if cmd is None: i += 1; continue
        def nextf():
            nonlocal i
            v = float(toks[i][1]); i += 1; return v
        try:
            if cmd in 'Mm':
                x, y = nextf(), nextf()
                if cmd == 'm': x += cx; y += cy
                flush(); P(x, y); cx, cy = x, y; sx0, sy0 = x, y; cmd = 'L' if cmd == 'M' else 'l'
                pcx = pcy = qcx = qcy = None
            elif cmd in 'Ll':
                x, y = nextf(), nextf()
                if cmd == 'l': x += cx; y += cy
                P(x, y); cx, cy = x, y; pcx = pcy = qcx = qcy = None
            elif cmd in 'Hh':
                x = nextf()
                if cmd == 'h': x += cx
                P(x, cy); cx = x; pcx = pcy = qcx = qcy = None
            elif cmd in 'Vv':
                y = nextf()
                if cmd == 'v': y += cy
                P(cx, y); cy = y; pcx = pcy = qcx = qcy = None
            elif cmd in 'Cc':
                x1, y1, x2, y2, x, y = (nextf() for _ in range(6))
                if cmd == 'c': x1 += cx; y1 += cy; x2 += cx; y2 += cy; x += cx; y += cy
                cubic(cx, cy, x1, y1, x2, y2, x, y); pcx, pcy = x2, y2; qcx = qcy = None; cx, cy = x, y
            elif cmd in 'Ss':
                x2, y2, x, y = (nextf() for _ in range(4))
                if cmd == 's': x2 += cx; y2 += cy; x += cx; y += cy
                x1 = 2*cx - pcx if pcx is not None else cx; y1 = 2*cy - pcy if pcy is not None else cy
                cubic(cx, cy, x1, y1, x2, y2, x, y); pcx, pcy = x2, y2; cx, cy = x, y
            elif cmd in 'Qq':
                x1, y1, x, y = (nextf() for _ in range(3))
                if cmd == 'q': x1 += cx; y1 += cy; x += cx; y += cy
                quad(cx, cy, x1, y1, x, y); qcx, qcy = x1, y1; pcx = pcy = None; cx, cy = x, y
            elif cmd in 'Tt':
                x, y = nextf(), nextf()
                if cmd == 't': x += cx; y += cy
                x1 = 2*cx - qcx if qcx is not None else cx; y1 = 2*cy - qcy if qcy is not None else cy
                quad(cx, cy, x1, y1, x, y); qcx, qcy = x1, y1; cx, cy = x, y
            elif cmd in 'Aa':
                rx, ry, ro, laf, sf, x, y = (nextf() for _ in range(7))
                if cmd == 'a': x += cx; y += cy
                arc(cx, cy, rx, ry, ro, laf, sf, x, y); cx, cy = x, y; pcx = pcy = qcx = qcy = None
        except (IndexError, ValueError):
            break
    flush()
    return subs

def _ctm(p, m):
    x, y = p
    return (m[0]*x + m[2]*y + m[4], m[1]*x + m[3]*y + m[5])

def svg_grad_to_tuple(g, bbox):
    """SVG linear gradient def -> (kind, [(pos%, hex, alpha)], css_deg) using bbox projection."""
    x, y, bw, bh = bbox
    def _stop(st):
        h, a = parse_color(st['hex'])
        alpha = st['so'] * (a if a is not None else 1.0)
        return (st['off'], h or '000000', alpha)

    if g['kind'] == 'radial':
        return 'radial', [_stop(st) for st in g['stops']], 0
    units = g.get('units', 'objectBoundingBox')
    if units == 'userSpaceOnUse':
        p1 = (g['x1'], g['y1']); p2 = (g['x2'], g['y2'])
        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        L2 = dx*dx + dy*dy
        if L2 <= 0.0001: return None
        corners = [(x, y), (x+bw, y), (x+bw, y+bh), (x, y+bh)]
        ts = [((cx-p1[0])*dx + (cy-p1[1])*dy) / L2 for cx, cy in corners]
        t0, t1 = min(ts), max(ts)
        if t1 - t0 <= 0.0001: return None
        stops = [((st['off']/100.0 - t0) / (t1 - t0) * 100.0, st['hex'], st['so']) for st in g['stops']]
        ux, uy = dx / L2**0.5, dy / L2**0.5
        css_deg = _m_deg(ux, uy)
        return 'linear', [(max(0.0, min(100.0, p_)), h_, a_) for p_, h_, a_ in stops], css_deg
    # objectBoundingBox: x1/y1/x2/y2 in 0..100 percentages
    x1, y1 = g['x1'], g['y1']; x2, y2 = g['x2'], g['y2']
    dx, dy = x2 - x1, y2 - y1
    if abs(dx) + abs(dy) <= 0.0001: return None
    css_deg = _m_deg(dx, dy)
    return 'linear', [_stop(st) for st in g['stops']], css_deg

def _m_deg(ux, uy):
    """unit vector (screen coords, y down) -> CSS gradient angle"""
    import math as _m
    n = _m.hypot(ux, uy)
    if n < 1e-9: return 180.0
    return _m.degrees(_m.atan2(ux / n, -uy / n)) % 360.0

def emit_svg(slide, item):
    sc = item['sc']
    TX, TY = item['rect']['x'], item['rect']['y']  # svg viewport origin
    for sh in item['shapes']:
        st_hex, st_a = parse_color(sh.get('stroke'))
        fl_hex, fl_a = parse_color(sh.get('fill'))
        sw = sh.get('sw') or 0
        grad = None
        if sh.get('grad') and sh.get('rect'):
            rr0 = sh['rect']
            grad = svg_grad_to_tuple(sh['grad'], (rr0['x'], rr0['y'], rr0['w'], rr0['h']))
        tag = sh['tag']
        shp = None
        if tag == 'arccaps':
            # round linecap of a stroked arc: native cap circles at both ends
            fhex_c, fa_c = parse_color(sh.get('fill'))
            if fhex_c:
                eff_c = (fa_c if fa_c is not None else 1.0) * (sh.get('op') or 1.0)
                for pt in sh.get('pts') or []:
                    d_ = sh['d']
                    cap = slide.shapes.add_shape(MSO_SHAPE.OVAL,
                        E(pt[0] - d_ / 2), E(pt[1] - d_ / 2), E(d_), E(d_))
                    _no_theme(cap); cap.shadow.inherit = False
                    solid(cap, fhex_c, eff_c if eff_c < 0.999 else None)
                    cap.line.fill.background()
            continue
        if tag == 'arcseg':
            rr = sh['rect']
            fhex, fa = parse_color(sh.get('fill'))
            eff = (fa if fa is not None else 1.0) * (sh.get('op') or 1.0)
            # OOXML block arc: adj1/adj2 = start/end angle (deg*0.6 normalized,
            # clockwise from 3 o'clock — same convention as SVG screen space),
            # adj3 = ring thickness / min(w,h). LO clamps endAngle at 360 (no
            # wrap) — an arc crossing 0° must be split into two shapes.
            spans = []
            a0, sweep = sh['a0'], sh['sweep']
            if a0 + sweep <= 360.01:
                spans.append((a0, a0 + sweep))
            else:
                spans.append((a0, 360.0))
                if a0 + sweep - 360.0 > 0.5:
                    spans.append((0.0, a0 + sweep - 360.0))
            for s0, s1 in spans:
                shp = slide.shapes.add_shape(MSO_SHAPE.BLOCK_ARC, E(rr['x']), E(rr['y']), E(rr['w']), E(rr['h']))
                _no_theme(shp)
                shp.shadow.inherit = False
                try:
                    shp.adjustments[0] = s0 * 0.6
                    shp.adjustments[1] = s1 * 0.6
                    shp.adjustments[2] = max(0.01, sh['holeT'])
                except Exception as e:
                    warn('arc adjustments failed: %s' % e, sh)
                if fhex:
                    solid(shp, fhex, eff if eff < 0.999 else None)
                else:
                    shp.fill.background()
                shp.line.fill.background()
            continue
        if tag in ('circle', 'ellipse') and sh.get('rect'):
            rr = sh['rect']
            if rr['w'] < CFG.geometry.svg_min_size or rr['h'] < CFG.geometry.svg_min_size: continue
            shp = slide.shapes.add_shape(MSO_SHAPE.OVAL, E(rr['x']), E(rr['y']), E(rr['w']), E(rr['h']))
        elif tag == 'rect' and sh.get('rect'):
            rr = sh['rect']
            if rr['w'] < CFG.geometry.svg_min_size or rr['h'] < CFG.geometry.svg_min_size: continue
            rad = (sh.get('rx') or 0) * sc['sx']
            if rad > CFG.geometry.svg_rad_min:
                shp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, E(rr['x']), E(rr['y']), E(rr['w']), E(rr['h']))
                try: shp.adjustments[0] = min(0.5, rad / max(min(rr['w'], rr['h']), 1))
                except Exception as e: warn('svg rect radius failed: %s' % e, sh)
            else:
                shp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, E(rr['x']), E(rr['y']), E(rr['w']), E(rr['h']))
        elif tag == 'line':
            m = sh.get('ctm')
            if m:
                p1 = _ctm((sh['x1'], sh['y1']), m); p2 = _ctm((sh['x2'], sh['y2']), m)
                x1, y1 = p1[0]+TX, p1[1]+TY
                x2, y2 = p2[0]+TX, p2[1]+TY
            else:
                x1, y1 = sh['x1']*sc['sx']+sc['ox']+TX, sh['y1']*sc['sy']+sc['oy']+TY
                x2, y2 = sh['x2']*sc['sx']+sc['ox']+TX, sh['y2']*sc['sy']+sc['oy']+TY
            shp = _add_line(slide, x1, y1, x2, y2, sh)
            continue
        elif tag in ('polyline', 'polygon') and sh.get('pts'):
            m = sh.get('ctm')
            if m:
                pts = [(lambda q: (q[0]+TX, q[1]+TY))(_ctm((px_, py_), m)) for px_, py_ in sh['pts']]
            else:
                pts = [(px_*sc['sx']+sc['ox']+TX, py_*sc['sy']+sc['oy']+TY) for px_, py_ in sh['pts']]
            shp = _freeform(slide, pts, tag == 'polygon')
        elif tag == 'path' and sh.get('straight'):
            x1, y1, x2, y2 = sh['straight']
            m = sh.get('ctm')
            if m:
                p1 = _ctm((x1, y1), m); p2 = _ctm((x2, y2), m)
                x1, y1 = p1[0]+TX, p1[1]+TY
                x2, y2 = p2[0]+TX, p2[1]+TY
            else:
                x1, y1 = x1*sc['sx']+sc['ox']+TX, y1*sc['sy']+sc['oy']+TY
                x2, y2 = x2*sc['sx']+sc['ox']+TX, y2*sc['sy']+sc['oy']+TY
            shp = _add_line(slide, x1, y1, x2, y2, sh)
            continue
        elif tag == 'path' and sh.get('d'):
            m = sh.get('ctm')
            if m:
                raw = sample_path(sh['d'], 1.0, 1.0, 0.0, 0.0)
                subs = [([ (lambda q: (q[0]+TX, q[1]+TY))(_ctm(p_, m)) for p_ in pts ], cl) for pts, cl in raw]
            else:
                subs = sample_path(sh['d'], sc['sx'], sc['sy'], sc['ox']+TX, sc['oy']+TY)
            for pts, closed in subs:
                shp = _freeform(slide, pts, closed or (fl_hex is not None) or (grad is not None))
                _svg_style(shp, st_hex, st_a, sw, fl_hex, fl_a, sh, grad=grad)
            continue
        elif tag == 'image' and sh.get('href') and sh.get('rect'):
            rr = sh['rect']
            src = resolve_src(sh['href'])
            if src:
                try:
                    pic = slide.shapes.add_picture(src, E(rr['x']), E(rr['y']), E(rr['w']), E(rr['h']))
                    pic.shadow.inherit = False
                    aspect_ok = 0.7 <= (rr['w'] / max(rr['h'], 1)) <= 1.4
                    if sh.get('clipShape') in ('ellipse', 'circle') or (
                       sh.get('clipShape') == 'path' and sh.get('clipCurved')
                       and not sh.get('clipStraight') and aspect_ok):
                        try:
                            sp = pic._element.spPr
                            g = sp.find(qn('a:prstGeom'))
                            if g is not None: sp.remove(g)
                            sp.append(parse_xml(f'<a:prstGeom {nsdecls("a")} prst="ellipse"><a:avLst/></a:prstGeom>'))
                        except Exception as e:
                            warn('svg image clip failed: %s' % e)
                except Exception as e:
                    warn('svg image embed failed: %s' % e)
            else:
                warn('svg image unresolvable', sh)
            continue
        elif tag == 'text' and sh.get('tspans') and sh.get('fs'):
            anchor = {'middle': 'center', 'end': 'right'}.get(sh.get('anchor', 'start'), 'left')
            for ln in sh['tspans']:
                rr = ln['rect']
                runs_ln = [{'t': ln['text'], 'st': {'fs': sh['fs'], 'color': fl_hex or CFG.typography.default_color,
                           'fw': str(sh.get('fw') or '400'), 'ls': 0, 'fst': 'normal'}}]
                # measured single line -> line mode (width headroom + font factor)
                emit_text(slide, {'kind': 'text', 'rect': rr,
                  'lines': [{'rect': rr, 'runs': runs_ln}], 'paras': [runs_ln],
                  'box': {'fs': sh['fs'], 'lh': sh.get('lh'), 'ta': anchor, 'col': fl_hex or CFG.typography.default_color,
                          'display': 'block', 'ai': 'center', 'ff': '', 'opacity': 1}})
            continue
        elif tag == 'text' and sh.get('content') and sh.get('rect'):
            rr = sh['rect']
            hexs_t, a_t = parse_color(sh.get('fill'))
            anchor = {'middle':'center','end':'right'}.get(sh.get('anchor','start'), 'left')
            fs_t = sh.get('fs') or 16
            runs_t = [{'t': sh['content'], 'st': {'fs': fs_t, 'color': hexs_t or CFG.typography.default_color,
                      'fw': str(sh.get('fw') or '400'), 'ls': 0, 'fst': 'normal'}}]
            emit_text(slide, {'kind': 'text', 'rect': rr,
              'lines': [{'rect': rr, 'runs': runs_t}], 'paras': [runs_t],
              'box': {'fs': fs_t, 'lh': sh.get('lh'), 'ta': anchor, 'col': hexs_t or CFG.typography.default_color,
                      'display': 'block', 'ai': 'center', 'ff': ''}})
            continue
        if shp is None: continue
        _svg_style(shp, st_hex, st_a, sw, fl_hex, fl_a, sh, grad=grad)
        if sh.get('capEnds') and st_hex:
            # round linecap on a stroked freeform: LO ignores ln@cap here —
            # draw native cap circles at both endpoints
            eff_c = (st_a if st_a is not None else 1.0)
            for pt in sh['capEnds']:
                cap = slide.shapes.add_shape(MSO_SHAPE.OVAL,
                    E(pt[0] - sw / 2), E(pt[1] - sw / 2), E(sw), E(sw))
                _no_theme(cap); cap.shadow.inherit = False
                solid(cap, st_hex, eff_c if eff_c < 0.999 else None)
                cap.line.fill.background()

def _svg_style(shp, st_hex, st_a, sw, fl_hex, fl_a, sh, grad=None):
    _no_theme(shp)
    shp.shadow.inherit = False
    if grad: set_fill_grad(shp, grad)
    elif fl_hex: solid(shp, fl_hex, fl_a)
    else: shp.fill.background()
    if st_hex and sw > 0:
        shp.line.color.rgb = RGBColor.from_string(st_hex); shp.line.width = PT(sw)
        if st_a is not None:
            lnEl = _spPr(shp).find(qn('a:ln')); sF = lnEl.find(qn('a:solidFill'))
            clr = sF.find(qn('a:srgbClr'))
            clr.append(clr.makeelement(qn('a:alpha'), {'val': str(int(st_a*100000))}))
        lnEl = _spPr(shp).find(qn('a:ln'))
        if sh.get('dash'):
            try:
                nums = [float(x) for x in re.findall(r'[\d.]+', sh['dash'])]
                dv = 'sysDot' if (nums and nums[0] <= 2) else 'dash'
                d = lnEl.find(qn('a:prstDash'))
                if d is None:
                    d = lnEl.makeelement(qn('a:prstDash'), {}); lnEl.append(d)
                d.set('val', dv)
            except Exception:
                pass
        if sh.get('cap') == 'round':
            lnEl.set('cap', 'rnd')
            lnEl.append(lnEl.makeelement(qn('a:round'), {}))
        if sh.get('markerEnd'):
            # SVG marker-end -> native OOXML line-end arrow (PPT/WPS/LO render natively)
            lnEl.append(parse_xml('<a:tailEnd %s type="triangle" w="med" len="med"/>' % nsdecls('a')))
    else:
        shp.line.fill.background()

def _freeform(slide, pts, close):

    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    mx, my = min(xs), min(ys)
    loc = [(E(px_ - mx), E(py_ - my)) for px_, py_ in pts]
    fb = slide.shapes.build_freeform(loc[0][0], loc[0][1])
    fb.add_line_segments(loc[1:], close=close)
    shp = fb.convert_to_shape(E(mx), E(my))
    _no_theme(shp)
    return shp

# ---------------- table ----------------
def emit_table(slide, item):
    rows = item['rows']
    n = len(rows)
    x, y = item['rect']['x'], item['rect']['y']
    # place cells on the grid honouring colspan/rowspan
    occ = {}
    place = []
    for i, row in enumerate(rows):
        j = 0
        for cell in row:
            while (i, j) in occ: j += 1
            cs = cell.get('colspan') or 1
            rs = cell.get('rowspan') or 1
            for di in range(rs):
                for dj in range(cs): occ[(i+di, j+dj)] = True
            place.append((i, j, cs, rs, cell))
            j += cs
    m = (max(k[1] for k in occ) + 1) if occ else (len(rows[0]) if rows else 0)
    colw = [0.0] * m
    for (i, j, cs, rs, cell) in place:
        if cs == 1: colw[j] = max(colw[j], cell['rect']['w'])
    avg = item['rect']['w'] / max(m, 1)
    colw = [c if c > CFG.table.min_dim else avg for c in colw]
    sc_ = item['rect']['w'] / max(sum(colw), 1)
    colw = [c * sc_ for c in colw]
    rowh = [0.0] * n
    for (i, j, cs, rs, cell) in place:
        rowh[i] = max(rowh[i], cell['rect']['h'])
    rowh = [h if h > CFG.table.min_dim else CFG.table.default_row_h for h in rowh]
    gf = slide.shapes.add_table(n, m, E(x), E(y), E(sum(colw)), E(sum(rowh)))
    tb = gf.table
    tbl = gf._element.graphic.graphicData.tbl
    tblPr = tbl.tblPr
    tblPr.set('firstRow', '0'); tblPr.set('bandRow', '0')
    sid = tblPr.find(qn('a:tableStyleId'))
    if sid is None: sid = tblPr.makeelement(qn('a:tableStyleId'), {}); tblPr.append(sid)
    sid.text = NO_STYLE
    for j, wv in enumerate(colw): tb.columns[j].width = E(wv)
    for i, hv in enumerate(rowh): tb.rows[i].height = E(hv)
    for (i, j, cs, rs, cell) in place:
            pptx_cell = tb.cell(i, j)
            box = cell['box']
            bgs, bga = parse_color(box['bg'])
            if bgs:
                pptx_cell.fill.solid(); pptx_cell.fill.fore_color.rgb = RGBColor.from_string(bgs)
                if bga is not None:
                    sF = pptx_cell._tc.get_or_add_tcPr().find(qn('a:solidFill'))
                    clr = sF.find(qn('a:srgbClr'))
                    clr.append(clr.makeelement(qn('a:alpha'), {'val': str(int(bga*100000))}))
            else:
                pptx_cell.fill.background()
            pptx_cell.margin_left = E(box['pl']); pptx_cell.margin_right = E(box['pr'])
            pptx_cell.margin_top = E(box['pt']); pptx_cell.margin_bottom = E(box['pb'])
            pptx_cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            for side, key in (('L','bl'), ('R','br_'), ('T','bt'), ('B','bb')):
                wv, stv, colv = box[key]
                tag = 'a:ln' + side
                tcPr = pptx_cell._tc.get_or_add_tcPr()
                old = tcPr.find(qn(tag))
                if old is not None: tcPr.remove(old)
                if wv > CFG.geometry.border_px and stv not in ('none', 'hidden'):
                    hexs, a = parse_color(colv)
                    if hexs:
                        al = f'<a:alpha val="{int(a*100000)}"/>' if a is not None else ''
                        el = parse_xml(f'<{tag} {nsdecls("a")} w="{int(wv*EMU_PX)}" cap="flat" cmpd="sng" algn="ctr">'
                                       f'<a:solidFill><a:srgbClr val="{hexs}">{al}</a:srgbClr></a:solidFill></{tag}>')
                        ref = None
                        for t in ('a:solidFill','a:noFill','a:gradFill'):
                            ref = tcPr.find(qn(t))
                            if ref is not None: break
                        if ref is not None: ref.addprevious(el)
                        else: tcPr.append(el)
                else:
                    el = parse_xml(f'<{tag} {nsdecls("a")}><a:noFill/></{tag}>')
                    ref = None
                    for t in ('a:solidFill','a:noFill','a:gradFill'):
                        ref = tcPr.find(qn(t))
                        if ref is not None: break
                    if ref is not None: ref.addprevious(el)
                    else: tcPr.append(el)
            if cell.get('paras'):
                tf = pptx_cell.text_frame
                fs_def = box.get('fs') or CFG.typography.default_fs
                lh_ratio = line_ratio(box['lh'], fs_def)
                cw = sum(colw[j:j+cs]) - box['pl'] - box['pr']
                # table cells ignore normAutofit in LO/PPT -> bake scale into run sizes.
                # multi-line is judged from the CELL's own browser height (rowh[i]
                # is inflated by rowspan cells and would flip whole rows to 1.0);
                # single-line cells only shrink when the measured renderer width
                # (font_metrics factor) genuinely exceeds the column, so fonts
                # keep the browser's size unless they would overflow
                own_h = cell['rect']['h'] - box['pt'] - box['pb']
                line_h = fs_def * max(lh_ratio, 1.0)
                multi = own_h > line_h * CFG.table.single_line_factor
                if multi:
                    scale, wrap = 1.0, True
                else:
                    text_all = ''.join(r_['t'] for p_ in cell['paras'] for r_ in p_)
                    wf = _font_width_factor(resolve_font(box.get('ff')), text_all)
                    need = est_paras_width(cell['paras'], fs_def) * max(1.0, wf) * 1.08
                    scale, wrap = min(1.0, cw / need) if need > cw else 1.0, False
                paras = cell['paras']
                if scale < 1.0:
                    paras = [[dict(rr_, st=dict(rr_['st'], fs=(rr_['st'].get('fs') or fs_def) * scale)) for rr_ in p_] for p_ in paras]
                tf.word_wrap = wrap
                hexs, _ = parse_color(box['col'])
                _fill_frame(tf, paras, box, box['ta'], lh_ratio, fs_def, hexs or CFG.typography.default_color)
            if cs > 1 or rs > 1:
                try: pptx_cell.merge(tb.cell(i + rs - 1, j + cs - 1))
                except Exception as e: warn('cell merge failed: %s' % e, cell)
    # pure-graphic descendants collected from cells (rating dots, progress
    # bars...): paint AFTER the table so they sit on top; they live inside
    # cells, never covering cell text. Emitted as regular boxes -> 50%-radius
    # dots become native circles, gradient bars degrade via emit_box normally
    for shp_item in item.get('shapes') or []:
        shp_item = dict(shp_item, kind='box', order=-1, zIndex='1000')
        emit_box(slide, shp_item)
    return tb

def add_rect(slide, x, y, w, h, fill):
    shp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, E(x), E(y), E(w), E(h))
    _no_theme(shp)
    shp.shadow.inherit = False
    solid(shp, fill)
    shp.line.fill.background()
    return shp

# ---------------- page assembly ----------------
def page_bg_hex(page):
    """Flatten html/body background colors over the white canvas the way the
    browser composites them (body over html over white). parse_color() maps a
    transparent layer to '000000', so layers must be alpha-composited here,
    never picked by hex truthiness (transparent would render as black)."""
    r = g = b = 255.0
    for layer in (page.get('htmlBg'), page.get('bodyBg')):
        if not layer: continue
        hexs, a = parse_color(layer)
        if not hexs: continue
        tr, tg, tb = (int(hexs[i:i+2], 16) for i in (0, 2, 4))
        if a is None: a = 1.0
        r = tr*a + r*(1-a); g = tg*a + g*(1-a); b = tb*a + b*(1-a)
    return '%02X%02X%02X' % (int(round(r)), int(round(g)), int(round(b)))

def build_slide(prs, page, els, shot=None):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    PAGE_URL[0] = page.get('url', '')
    # page background
    bg = parse_gradient(page.get('bodyBgImg'))
    bgshape = add_rect(slide, 0, 0, page['w'], page['h'], page_bg_hex(page))
    if bg: set_fill_grad(bgshape, bg)
    elif parse_bg_url(page.get('bodyBgImg')):
        if not apply_blip_fill(slide, bgshape, parse_bg_url(page['bodyBgImg']), {'bs': 'cover'}):
            warn('body background image failed', dropped=True)
    def zof(it):
        try: z = int(str(it.get('zIndex')))
        except (TypeError, ValueError): z = 0
        return (z, it['order'])
    for item in sorted(els, key=zof):
        k = item['kind']
        if TEXT_MODE[0] == 'flow' and item.get('lineOnly'): continue
        if TEXT_MODE[0] == 'line' and item.get('flowOnly'): continue
        if k in ('box', 'pseudo') and k == item.get('kind', k):
            if item.get('paras'):
                bx = item['box']
                styled = (parse_color(bx['bg'])[0] or parse_gradient(bx['bgImg'])
                          or parse_bg_url(bx['bgImg'])
                          or border_sides(bx) or bx.get('shadow') is not None)
                if not styled:
                    item = dict(item, kind='text')
        if k in ('box', 'polyclip', 'pseudo'):
            if item.get('paras') and item['kind'] == 'text':
                emit_text(slide, item)
            else:
                emit_box(slide, item)
        elif k == 'text':
            emit_text(slide, item)
        elif k == 'svg':
            emit_svg(slide, item)
        elif k == 'table':
            emit_table(slide, item)
        elif k == 'image':
            emit_image(slide, item, page)
        elif k == 'fallback':
            warn('fallback %s -> screenshot crop' % item.get('why'), item)
            if shot:
                emit_fallback(slide, item, shot)
            else:
                warn('fallback %s without page shot' % item.get('why'), item, dropped=True)
    return slide

# ---------------- conversion report ----------------
# per-page collection of warnings (degraded but emitted) and drops (content lost)
REPORTS = []
_cur = {'warned': [], 'dropped': []}

def warn(reason, item=None, dropped=False):
    rec = {'reason': reason}
    if item:
        rec['tag'] = item.get('kind') or item.get('tag')
        rec['path'] = item.get('path')
        if item.get('rect'):
            rec['rect'] = {k: round(v, 1) for k, v in item['rect'].items()}
    _cur['dropped' if dropped else 'warned'].append(rec)

def finish_page_report(url):
    REPORTS.append({'page': os.path.basename(url or ''), 'warned': _cur['warned'], 'dropped': _cur['dropped']})
    _cur['warned'], _cur['dropped'] = [], []

def emit_fallback(slide, item, shot):
    """crop the element's rect from the page screenshot and place it as a picture"""
    from PIL import Image as _im
    r = item.get('rect') or {}
    try:
        im = _im.open(io.BytesIO(shot)) if isinstance(shot, (bytes, bytearray)) else _im.open(shot)
        x0, y0 = max(0, int(r.get('x', 0))), max(0, int(r.get('y', 0)))
        x1 = min(im.size[0], int(r.get('x', 0) + r.get('w', 0)))
        y1 = min(im.size[1], int(r.get('y', 0) + r.get('h', 0)))
        if x1 - x0 < 2 or y1 - y0 < 2:
            warn('fallback rect degenerate', item, dropped=True)
            return None
        buf = io.BytesIO()
        im.crop((x0, y0, x1, y1)).save(buf, format='PNG')
        buf.seek(0)
        pic = slide.shapes.add_picture(buf, E(r['x']), E(r['y']), E(r['w']), E(r['h']))
        pic.shadow.inherit = False
        return pic
    except Exception as e:
        warn('fallback crop failed: %s' % e, item, dropped=True)
        return None

def _error_slide(prs, name):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    shp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
    _no_theme(shp)
    solid(shp, 'FFF4F4')
    shp.line.color.rgb = RGBColor.from_string('CC0000'); shp.line.width = Pt(2)
    tf = shp.text_frame; tf.word_wrap = True
    tf.paragraphs[0].alignment = PP_ALIGN.CENTER
    r = tf.paragraphs[0].add_run(); r.text = f'CONVERT FAILED: {name}'
    r.font.size = Pt(24); r.font.color.rgb = RGBColor.from_string('CC0000')

# ---------------- CDP driver ----------------
# settle before extraction: webfonts + decoded images + two rAFs
SETTLE_JS = """(async () => {
  try { if (document.fonts && document.fonts.ready) await document.fonts.ready; } catch (e) {}
  const t0 = Date.now();
  while (Date.now() - t0 < 3000) {
    let imgs;
    try { imgs = Array.from(document.images || []); } catch (e) { break; }
    if (imgs.every(i => i.complete)) break;
    await new Promise(r => setTimeout(r, 50));
  }
  await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
  return true;})()"""

class CDP:
    def __init__(self, port=9322):
        self.port = port; self.proc = None; self.ws = None; self.mid = 0
        self.tmpd = None
    def _port_free(self, p):
        s = socket.socket()
        try:
            s.bind(('127.0.0.1', p)); return True
        except OSError:
            return False
        finally:
            s.close()
    def start(self):
        port = self.port
        while not self._port_free(port): port += 1
        self.port = port
        exe = None
        # 支持通过环境变量 CHROME_PATH 手动指定浏览器路径（与 slide-audit.mjs 对齐）
        if os.environ.get('CHROME_PATH') and os.path.exists(os.environ['CHROME_PATH']):
            exe = os.environ['CHROME_PATH']
        if sys.platform == 'win32':
            _cands = (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                      r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                      r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                      r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe")
        elif sys.platform == 'darwin':
            _cands = ("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                      "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                      "/Applications/Chromium.app/Contents/MacOS/Chromium")
        else:
            _cands = ("/usr/bin/google-chrome",
                      "/usr/bin/google-chrome-stable",
                      "/usr/bin/chromium",
                      "/usr/bin/chromium-browser")
        if exe is None:
            for p in _cands:
                if os.path.exists(p): exe = p; break
        if exe is None: raise RuntimeError('Edge/Chrome not found')
        self.tmpd = tempfile.mkdtemp(prefix='h2p_edge_')
        self.proc = subprocess.Popen([exe, '--headless=new', '--disable-gpu', '--no-first-run',
            '--window-size=1280,768', '--force-device-scale-factor=1',
            f'--remote-debugging-port={self.port}', f'--user-data-dir={self.tmpd}', 'about:blank'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            try:
                urllib.request.urlopen(f'http://127.0.0.1:{self.port}/json/version', timeout=1)
                return
            except Exception:
                time.sleep(0.4)
        raise RuntimeError('CDP not reachable')
    def _connect_ws(self):
        targets = json.loads(urllib.request.urlopen(
            f'http://127.0.0.1:{self.port}/json/list', timeout=5).read())
        page = next(t for t in targets if t.get('type') == 'page')
        self.ws = websocket.create_connection(page['webSocketDebuggerUrl'], timeout=60,
                                              suppress_origin=True)
    def _cmd(self, method, params=None):
        self.mid += 1
        payload = json.dumps({'id': self.mid, 'method': method, 'params': params or {}})
        try:
            self.ws.send(payload)
        except Exception:
            # long sessions can drop the socket (idle timeout, nav edge cases);
            # reconnect once and retry — the tab itself is still alive
            self._connect_ws()
            self.ws.send(payload)
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get('id') == self.mid: return msg
    def load(self, url, timeout=15):
        if self.ws is None:
            targets = json.loads(urllib.request.urlopen(
                f'http://127.0.0.1:{self.port}/json/list', timeout=5).read())
            page = next(t for t in targets if t.get('type') == 'page')
            self.ws = websocket.create_connection(page['webSocketDebuggerUrl'], timeout=60,
                                                  suppress_origin=True)
            self._cmd('Page.enable')
            # headless window chrome steals pixels -> force the exact layout viewport
            self._cmd('Emulation.setDeviceMetricsOverride',
                      {'width': 1280, 'height': 768, 'deviceScaleFactor': 1, 'mobile': False})
        self._cmd('Page.navigate', {'url': url})
        deadline = time.time() + timeout
        loaded = False
        while time.time() < deadline:
            try:
                msg = json.loads(self.ws.recv())
                if msg.get('method') == 'Page.loadEventFired': loaded = True; break
            except (websocket.WebSocketTimeoutException, TimeoutError):
                # raw socket.timeout leaks through the ws layer on stalls and
                # kills the socket — bounded by the deadline check above
                continue
        if not loaded:
            raise RuntimeError(f'page load timeout: {url}')
        self.evaluate(SETTLE_JS)
        time.sleep(0.2)
    def evaluate(self, js):
        msg = self._cmd('Runtime.evaluate', {'expression': js, 'returnByValue': True, 'awaitPromise': True})
        res = msg.get('result', {})
        if 'exceptionDetails' in res:
            raise RuntimeError('page JS error: ' + json.dumps(res['exceptionDetails'])[:800])
        return res.get('result', {}).get('value')
    def screenshot(self, beyond=False):
        params = {'format': 'png'}
        if beyond: params['captureBeyondViewport'] = True
        msg = self._cmd('Page.captureScreenshot', params)
        return base64.b64decode(msg['result']['data'])
    def close(self):
        # kill ONLY the tree we spawned — never by image name (would kill user's browser)
        try:
            if self.ws: self.ws.close()
        except Exception: pass
        if self.proc:
            pid = self.proc.pid
            try: self.proc.kill()
            except Exception: pass
            # taskkill 是 Windows 专有命令，macOS/Linux 上不存在
            if sys.platform == 'win32':
                subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)], capture_output=True)
        if self.tmpd:
            shutil.rmtree(self.tmpd, ignore_errors=True)

# ---------------- main ----------------
_HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_HERE, 'extract.js'), encoding='utf-8') as _f:
    EXTRACT_JS = _f.read()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('inputs', nargs='+')
    ap.add_argument('-o', '--output', required=True)
    ap.add_argument('--dump', help='dump extracted JSON per page for debugging')
    ap.add_argument('--port', type=int, default=9223)
    ap.add_argument('--spacing', action='store_true', help='emit letter-spacing (LibreOffice preview drops glyphs with spc)')
    ap.add_argument('--profile', help='JSON overriding heuristic constants (see h2p_config.py)')
    ap.add_argument('--text-mode', choices=['line', 'flow'], default='line',
                    help='line: one textbox per measured visual line (default); flow: legacy width estimation')
    args = ap.parse_args()

    files = []
    for inp in args.inputs:
        if os.path.isdir(inp):
            files += sorted(os.path.join(inp, f) for f in os.listdir(inp) if f.endswith('.html') and f.startswith('slide_'))
        else:
            files.append(inp)
    if not files: sys.exit('no input html files')

    # expand embedded multi-slide decks (<script type="text/html" id="slide-N">)
    # into individual pages, in document order
    expanded = []
    for f in files:
        try:
            with open(f, encoding='utf-8') as fh:
                src = fh.read()
        except OSError:
            expanded.append(f); continue
        blocks = re.findall(r'<script type="text/html" id="slide-(\d+)">\n?(.*?)</script>', src, re.S)
        if len(blocks) <= 1:
            expanded.append(f); continue
        tmpd = os.path.join(tempfile.gettempdir(), 'h2p_deck_' + os.path.splitext(os.path.basename(f))[0])
        os.makedirs(tmpd, exist_ok=True)
        for num, content in blocks:
            pf = os.path.join(tmpd, 'slide_%s.html' % num)
            with open(pf, 'w', encoding='utf-8') as fh:
                fh.write(content)
            expanded.append(pf)
        print(f'  [{os.path.basename(f)}] embedded deck -> {len(blocks)} slides')
    files = expanded

    SPACING[0] = args.spacing
    TEXT_MODE[0] = args.text_mode
    if args.profile: load_profile(args.profile)
    prs = Presentation()
    cdp = CDP(args.port)
    cdp.start()
    ok_pages = 0
    try:
        first = True
        for f in files:
            url = 'file:///' + quote(os.path.abspath(f).replace(os.sep, '/'), safe='/:')
            name = os.path.basename(f)
            data = None
            for attempt in (1, 2):
                try:
                    cdp.load(url)
                    data = cdp.evaluate(EXTRACT_JS)
                    break
                except Exception as e:
                    if attempt == 2:
                        warn('page failed: %s' % e, dropped=True)
                        print(f'  [{name}] LOAD/EXTRACT FAILED: {e}')
                    else:
                        time.sleep(0.5)
            if data is None:
                _error_slide(prs, name)
                finish_page_report(url)
                continue
            if first:
                # slide canvas follows the page design size (e.g. 1280x720 decks)
                prs.slide_width = Emu(int(data['page']['w'] * EMU_PX))
                prs.slide_height = Emu(int(data['page']['h'] * EMU_PX))
                first = False
            if args.dump:
                os.makedirs(args.dump, exist_ok=True)
                base = os.path.splitext(os.path.basename(f))[0]
                with open(os.path.join(args.dump, base + '.json'), 'w', encoding='utf-8') as df:
                    json.dump(data, df, ensure_ascii=False, indent=1)
            shot = None
            if any(e.get('kind') == 'fallback' for e in data['els']):
                tall = data['page'].get('h', 768) > 770 or data['page'].get('w', 1280) > 1282
                try:
                    shot = cdp.screenshot(beyond=tall)
                except Exception as e:
                    warn('page shot for fallback failed: %s' % e)
            try:
                build_slide(prs, data['page'], data['els'], shot=shot)
                ok_pages += 1
                print(f'  [{name}] {len(data["els"])} elements')
            except Exception as e:
                traceback.print_exc()
                warn('build failed: %s' % e, dropped=True)
                _error_slide(prs, name)
            finish_page_report(url)
    finally:
        cdp.close()

    prs.save(args.output)
    report_path = args.output + '.report.json'
    with open(report_path, 'w', encoding='utf-8') as rf:
        json.dump(REPORTS, rf, ensure_ascii=False, indent=1)
    n_warn = sum(len(p['warned']) for p in REPORTS)
    n_drop = sum(len(p['dropped']) for p in REPORTS)
    print(f'saved {args.output} ({ok_pages}/{len(files)} slides ok)  warnings={n_warn} dropped={n_drop}')
    print(f'report: {report_path}')

if __name__ == '__main__':
    main()
