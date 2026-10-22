# -*- coding: utf-8 -*-
"""
measure.py — LibreOffice 字宽标定管线。

生成两份同内容样本: HTML(浏览器实测 advance 宽度) 与 PPTX(wrap=False 的
文本框) → LibreOffice 渲染 → 实测墨迹宽度 → 比值写入 font_metrics.json:
  {font: {class: ratio, ...}, "_meta": {...}}
ratio = LO 墨迹宽 / 浏览器 advance 宽，>1 表示渲染器排得更宽(溢出风险)。
P3 逐行文本模式用它做行宽安全系数——取代拍脑袋的字宽常数。

用法: python measure.py [--twice]   # --twice 跑两遍验证确定性
"""
import io, json, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
os.chdir(HERE)

import html2pptx as h
from pptx import Presentation
from pptx.util import Emu, Pt
from PIL import Image

WORK = os.path.join(HERE, 'bench_work', 'measure')
PROFILE = os.path.join(HERE, 'lo_profile')
SOFFICE = r'C:\Program Files\LibreOffice\program\soffice.exe'
FONTS_DIR = r'C:\Windows\Fonts'

# 字体 → 判定已安装的字体文件
FONTS = {
    'Microsoft YaHei': ['msyh.ttc', 'msyh.ttf'],
    'DengXian': ['Deng.ttf', 'Dengl.ttf', 'denge.ttf'],
    'SimSun': ['simsun.ttc'],
    'SimHei': ['simhei.ttf'],
    'KaiTi': ['simkai.ttf', 'KAITI.TTF'],
    'Arial': ['arial.ttf'],
    'Times New Roman': ['times.ttf'],
    'Georgia': ['georgia.ttf', 'GEORGIA.TTF'],
    'Segoe UI': ['segoeui.ttf'],
    'Verdana': ['verdana.ttf'],
    'Helvetica Neue': ['helveticaneue.ttf'],
    'Noto Sans SC': ['NotoSansSC-Regular.otf'],
}
CLASSES = {
    'cjk': '培训管理工作手册方向业绩',
    'lower': 'abcdefghij',
    'upper': 'ABCDEFGHIJ',
    'digits': '0123456789',
}
SIZES = [16, 24, 32]
ROW_H = 50
PAGE_W, PAGE_H = 1280, 800


def installed_fonts():
    out = []
    for fam, files in FONTS.items():
        if any(os.path.exists(os.path.join(FONTS_DIR, f)) for f in files):
            out.append(fam)
    return out


def build_samples(fonts):
    """-> samples [(font, cls, size, text)], rows at y=40+i*ROW_H"""
    samples = []
    for font in fonts:
        for cls, text in CLASSES.items():
            for size in SIZES:
                samples.append((font, cls, size, text))
    return samples


def make_html(samples):
    rows = []
    for i, (font, cls, size, text) in enumerate(samples):
        y = 40 + i * ROW_H
        rows.append(
            '<span data-i="%d" style="position:absolute;left:100px;top:%dpx;'
            'font-family:\'%s\';font-size:%dpx;white-space:nowrap;color:#000">%s</span>'
            % (i, y, font, size, text))
    page_h = 40 + len(samples) * ROW_H + 60
    return ('<!DOCTYPE html><html><head><meta charset="utf-8"><style>*{margin:0;padding:0}'
            'html,body{width:%dpx;height:%dpx}body{background:#fff;overflow:hidden}</style>'
            '</head><body>%s</body></html>' % (PAGE_W, page_h, ''.join(rows))), samples, page_h


ROWS_PER_SLIDE = 20   # keep each slide within the 56-inch PPTX size limit

def make_pptx(samples, page_h, path):
    prs = Presentation()
    prs.slide_width = Emu(int(PAGE_W * 9525))
    prs.slide_height = Emu(int((40 + ROWS_PER_SLIDE * ROW_H + 40) * 9525))
    slide = None
    for i, (font, cls, size, text) in enumerate(samples):
        if i % ROWS_PER_SLIDE == 0:
            slide = prs.slides.add_slide(prs.slide_layouts[6])
        y = 40 + (i % ROWS_PER_SLIDE) * ROW_H
        tb = slide.shapes.add_textbox(h.E(100), h.E(y - 20), h.E(1000), h.E(40))
        tf = tb.text_frame
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        tf.word_wrap = False
        from pptx.enum.text import MSO_ANCHOR
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        p = tf.paragraphs[0]
        r = p.add_run()
        r.text = text
        h._style_run(r, {'fs': size, 'color': 'rgb(0, 0, 0)', 'fw': '400',
                         'ls': 0, 'fst': 'normal'}, size, '000000', font=font)
    prs.save(path)


def render_pngs(pptx_path):
    os.makedirs(WORK, exist_ok=True)
    args = [SOFFICE, '-env:UserInstallation=file:///' + PROFILE.replace(os.sep, '/'),
            '--headless', '--convert-to', 'pdf', '--outdir', WORK, pptx_path]
    pdf = os.path.join(WORK, os.path.splitext(os.path.basename(pptx_path))[0] + '.pdf')
    if os.path.exists(pdf):
        os.remove(pdf)
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        p.communicate(timeout=300)
    except subprocess.TimeoutExpired:
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(p.pid)], capture_output=True)
        raise RuntimeError('soffice timeout')
    if not os.path.exists(pdf):
        raise RuntimeError('soffice conversion failed')
    import fitz
    doc = fitz.open(pdf)
    pngs = []
    for i, page in enumerate(doc):
        png = os.path.join(WORK, 'measure_%02d.png' % i)
        page.get_pixmap(matrix=fitz.Matrix(96 / 72, 96 / 72)).save(png)
        pngs.append(png)
    doc.close()
    return pngs


def lo_ink_widths(pngs, n_rows):
    from PIL import ImageOps
    out = []
    for i in range(n_rows):
        png = pngs[i // ROWS_PER_SLIDE]
        y = 40 + (i % ROWS_PER_SLIDE) * ROW_H
        im = Image.open(png).convert('L')
        band = im.crop((0, max(0, y - 16), im.size[0], min(im.size[1], y + 36)))
        bbox = ImageOps.invert(band.point(lambda v: 0 if v < 160 else 255)).getbbox()
        out.append((bbox[2] - bbox[0]) if bbox else None)
    return out


def run_once():
    fonts = installed_fonts()
    print('installed fonts:', ', '.join(fonts))
    html, samples, page_h = make_html(build_samples(fonts))
    html_path = os.path.join(WORK, 'measure.html')
    os.makedirs(WORK, exist_ok=True)
    io.open(html_path, 'w', encoding='utf-8').write(html)

    # browser widths
    cdp = h.CDP(9365)
    cdp.start()
    try:
        from urllib.parse import quote
        cdp.load('file:///' + quote(os.path.abspath(html_path).replace(os.sep, '/'), safe='/:'))
        js = ("(() => { const out = []; document.querySelectorAll('span[data-i]').forEach(s => {"
              "const r = s.getBoundingClientRect(); out.push([+s.dataset.i, +r.width.toFixed(2)]);});"
              "return JSON.stringify(out); })()")
        import json as _json
        br = {i: w for i, w in _json.loads(cdp.evaluate(js))}
    finally:
        cdp.close()

    # LO widths
    pptx_path = os.path.join(WORK, 'measure.pptx')
    make_pptx(samples, page_h, pptx_path)
    lo = lo_ink_widths(render_pngs(pptx_path), len(samples))

    metrics = {}
    detail = []
    for i, (font, cls, size, text) in enumerate(samples):
        bw, lw = br.get(i), lo[i]
        if not bw or not lw:
            continue
        ratio = round(lw / bw, 3)
        metrics.setdefault(font, {}).setdefault(cls, []).append(ratio)
        detail.append((font, cls, size, bw, lw, ratio))
    out = {}
    for font, cls_map in metrics.items():
        out[font] = {cls: round(sum(v) / len(v), 3) for cls, v in cls_map.items()}
        out[font]['_n'] = sum(len(v) for v in cls_map.values())
    return out, detail


def main():
    twice = '--twice' in sys.argv
    out, detail = run_once()
    if twice:
        out2, _ = run_once()
        if out != out2:
            print('WARNING: non-deterministic results!')
            print('run1:', json.dumps(out, ensure_ascii=False))
            print('run2:', json.dumps(out2, ensure_ascii=False))
        else:
            print('determinism check: OK (two runs identical)')
    dst = os.path.join(HERE, 'font_metrics.json')
    with open(dst, 'w', encoding='utf-8') as f:
        json.dump({'_meta': {'renderer': 'LibreOffice', 'generated': time.strftime('%Y-%m-%d %H:%M')},
                   'fonts': out}, f, ensure_ascii=False, indent=1)
    print('\nfont_metrics.json ->', dst)
    print('%-18s %6s %6s %6s %7s %6s' % ('font', 'cjk', 'lower', 'upper', 'digits', 'n'))
    for font, m in out.items():
        print('%-18s %6s %6s %6s %7s %6d' %
              (font, m.get('cjk'), m.get('lower'), m.get('upper'), m.get('digits'), m.get('_n', 0)))


if __name__ == '__main__':
    main()
