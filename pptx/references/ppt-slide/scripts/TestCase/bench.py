# -*- coding: utf-8 -*-
"""
bench.py — 转换保真度基准管线。

流程: 页面来源(bench_pages 合成页 + --dir 外部真实页) → 单个 Edge 会话逐页
(截图 + extract.js 提取 + build_slide) → 合成一个 bench.pptx → LibreOffice
渲染 → diffmap.score_pair 逐页评分 → scores.json + bench_report.md。

外部页: --dir <目录> 中的 *.html。嵌入式 deck(含 <script type="text/html"
id="slide-N"> 块)自动拆分为单页; 其余按独立页处理。默认及格线 75%,
可在 TestCase/bench_ext.json 按 {页名: 分数} 覆盖。

用法:
  python bench.py                          # 只跑合成基准页
  python bench.py --dir ../Test            # 只跑 Test 目录拆出的真实页
  python bench.py --dir ../Test text_mixed # 混合 + 名称过滤(子串匹配)
  python bench.py --strict                 # 有不及格页时退出码 1
"""
import io, json, os, re, shutil, subprocess, sys, time
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
os.chdir(HERE)

import html2pptx as h
import diffmap
from bench_pages import PAGES
from PIL import Image

SUITE = None   # --suite chart → 从 chart_pages 等模块载入页面集

WORK = os.path.join(os.environ.get('H2P_WORK') or HERE, 'bench_work')
EXT_DIR = os.path.join(WORK, 'ext')
PNG_DIR = os.path.join(WORK, 'render')
PROFILE = os.environ.get('H2P_LO_PROFILE') or os.path.join(HERE, 'lo_profile')
CDP_PORT = int(os.environ.get('H2P_CDP_PORT', '9361'))
TEXT_MODE = os.environ.get('H2P_TEXT_MODE', 'line')
SOFFICE = r'C:\Program Files\LibreOffice\program\soffice.exe'
EXT_MIN_PCT = 75


def load_external(dirpath):
    """拆分嵌入式 deck / 复制独立页 -> bench_work/ext/。
       页名带目录前缀，避免不同目录的 slide_01 同名冲突。
       -> {name: {'path', 'min_pct'}}"""
    os.makedirs(EXT_DIR, exist_ok=True)
    overrides = {}
    ovr_path = os.path.join(HERE, 'bench_ext.json')
    if os.path.exists(ovr_path):
        with open(ovr_path, encoding='utf-8') as f:
            overrides = json.load(f)
    dirkey = os.path.basename(os.path.abspath(dirpath).rstrip('/\\'))[:8]
    pages = {}
    for fn in sorted(os.listdir(dirpath)):
        if not fn.lower().endswith('.html'):
            continue
        key = '%s-%s' % (dirkey, os.path.splitext(fn)[0][:10])
        src = io.open(os.path.join(dirpath, fn), encoding='utf-8').read()
        blocks = re.findall(
            r'<script type="text/html" id="slide-(\d+)">\n?(.*?)</script>', src, re.S)
        if blocks:
            for num, content in blocks:
                name = '%s_%02d' % (key, int(num))
                p = os.path.join(EXT_DIR, name + '.html')
                io.open(p, 'w', encoding='utf-8').write(content)
                pages[name] = {'path': p, 'min_pct': overrides.get(name, EXT_MIN_PCT)}
        else:
            name = key + '_solo'
            p = os.path.join(EXT_DIR, name + '.html')
            shutil.copyfile(os.path.join(dirpath, fn), p)
            pages[name] = {'path': p, 'min_pct': overrides.get(name, EXT_MIN_PCT)}
    return pages


def render_pptx(pptx_path, outdir, prefix='c'):
    """soffice → pdf → 每页 96dpi PNG。专用 profile；超时按 PID 树杀后用全新
    临时 profile 重试一次(被杀实例可能锁住共享 profile)。"""
    os.makedirs(outdir, exist_ok=True)
    base = [SOFFICE, '--headless', '--convert-to', 'pdf', '--outdir', outdir, pptx_path]
    pdf = os.path.join(outdir, os.path.splitext(os.path.basename(pptx_path))[0] + '.pdf')
    import tempfile as _tf
    for attempt, prof in ((1, PROFILE), (2, _tf.mkdtemp(prefix='h2p_lo_'))):
        if os.path.exists(pdf):
            os.remove(pdf)
        p = subprocess.Popen(base[:1] + ['-env:UserInstallation=file:///' + prof.replace(os.sep, '/')] + base[1:],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            p.communicate(timeout=600)
        except subprocess.TimeoutExpired:
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(p.pid)], capture_output=True)
            time.sleep(1)
            continue
        if os.path.exists(pdf) and os.path.getsize(pdf) > 1000:
            break
    if not os.path.exists(pdf):
        raise RuntimeError('soffice conversion failed: %s' % pptx_path)
    import fitz
    doc = fitz.open(pdf)
    pngs = []
    for i, page in enumerate(doc):
        f = os.path.join(outdir, '%s_%03d.png' % (prefix, i + 1))
        page.get_pixmap(matrix=fitz.Matrix(96 / 72, 96 / 72)).save(f)
        pngs.append(f)
    doc.close()
    return pngs


def crop_pair(a_img, b_img):
    cw, ch = min(a_img.size[0], b_img.size[0]), min(a_img.size[1], b_img.size[1])
    return a_img.crop((0, 0, cw, ch)), b_img.crop((0, 0, cw, ch))


def make_vis(rendered, shots):
    """每页拼 左HTML原稿/右PPTX转换 对比图。chart_pages 套件落 vis_chart,
       其余(合成页/外部页)落 vis_final。"""
    from PIL import ImageDraw
    outdir = os.path.join(WORK, 'vis_chart' if SUITE == 'chart_pages' else 'vis_final')
    os.makedirs(outdir, exist_ok=True)
    W = 640
    for n, png in rendered.items():
        shot = shots.get(n)
        if not shot or not os.path.exists(shot):
            continue
        a = Image.open(shot).convert('RGB')
        b = Image.open(png).convert('RGB')

        def fit(im):
            r = W / im.width
            return im.resize((W, max(1, int(im.height * r))))
        a, b = fit(a), fit(b)
        canvas = Image.new('RGB', (W * 2 + 12, max(a.height, b.height) + 26), 'white')
        canvas.paste(a, (0, 26))
        canvas.paste(b, (W + 12, 26))
        d = ImageDraw.Draw(canvas)
        d.text((4, 6), 'HTML original', fill=(200, 0, 0))
        d.text((W + 16, 6), 'PPTX converted', fill=(0, 120, 0))
        safe = re.sub(r'[^\w\-.]', '_', n)
        canvas.save(os.path.join(outdir, safe + '.png'))
    return outdir


def run(entries, strict=False):
    """entries: {name: {'path','min_pct'}}，按插入顺序处理。
       Phase A: 单 Edge 会话采集全部页面; Phase B: 逐页构建 pptx → LO 渲染 →
       评分。单页转换隔离超时：坏页单独标记，不拖累其它页；每页留有独立
       pptx (bench_work/pages/) 便于随时人工检查。"""
    os.makedirs(PNG_DIR, exist_ok=True)
    PAGE_DIR = os.path.join(WORK, 'pages')
    os.makedirs(PAGE_DIR, exist_ok=True)
    names = list(entries)
    shots = {}
    datas = {}
    h.TEXT_MODE[0] = TEXT_MODE
    cdp = h.CDP(CDP_PORT)
    cdp.start()
    skipped = []
    try:
        for n in names:
            url = 'file:///' + quote(os.path.abspath(entries[n]['path']).replace(os.sep, '/'), safe='/:')
            # per-page retry: a stalled page / dead websocket restarts the
            # browser fresh instead of sinking the whole collection
            data = None
            for attempt in (1, 2):
                try:
                    cdp.load(url)
                    data = cdp.evaluate(h.EXTRACT_JS)
                    break
                except Exception as e:
                    data = None
                    if attempt == 1:
                        try: cdp.close()
                        except Exception: pass
                        cdp = h.CDP(9361)
                        cdp.start()
                    else:
                        print('  SKIP', n, 'collection failed:', str(e)[:120], flush=True)
            if data is None:
                skipped.append(n)
                continue
            # 长页(架构图等)超出 1280x768 视口时整页截图
            tall = data['page'].get('h', 768) > 770 or data['page'].get('w', 1280) > 1282
            shots[n] = os.path.join(WORK, 'shot_%s.png' % re.sub(r'[^\w\-.]', '_', n))
            with open(shots[n], 'wb') as sf:
                sf.write(cdp.screenshot(beyond=tall))
            datas[n] = data
            h.finish_page_report(n)
            print('  built', n, len(data['els']), 'elements', flush=True)
    finally:
        cdp.close()

    scores = {}
    rows = []
    rendered = {}   # name -> LO 渲染 png 路径,供 vis 对比图
    n_pass = 0
    n_fail = 0
    for idx, n in enumerate(names):
        if n not in datas:
            scores[n] = {'match_pct': 0.0, 'min_pct': entries[n]['min_pct'],
                         'pass': False, 'error': 'collection skipped', 'regions': []}
            rows.append((n, 0.0, entries[n]['min_pct'], False, '-', []))
            continue
        prs = h.Presentation()
        prs.slide_width = h.Emu(int(datas[n]['page']['w'] * h.EMU_PX))
        prs.slide_height = h.Emu(int(datas[n]['page']['h'] * h.EMU_PX))
        shot = None
        if any(e.get('kind') == 'fallback' for e in datas[n]['els']):
            with open(shots[n], 'rb') as f:
                shot = f.read()
        h.build_slide(prs, datas[n]['page'], datas[n]['els'], shot=shot)
        safe = re.sub(r'[^\w\-.]', '_', n)[:40]
        pptx_path = os.path.join(PAGE_DIR, 'p%03d_%s.pptx' % (idx + 1, safe))
        prs.save(pptx_path)
        try:
            pngs = render_pptx(pptx_path, PNG_DIR, prefix='p%03d' % (idx + 1))
            b = Image.open(pngs[0]).convert('RGB')
            rendered[n] = pngs[0]
        except Exception as e:
            print('  [%d/%d] %s RENDER FAILED: %s' % (idx + 1, len(names), n, e), flush=True)
            scores[n] = {'match_pct': 0.0, 'min_pct': entries[n]['min_pct'], 'pass': False,
                         'error': str(e)[:200], 'regions': []}
            rows.append((n, 0.0, entries[n]['min_pct'], False, '-', []))
            n_fail += 1
            continue
        a = Image.open(shots[n]).convert('RGB')
        a, b = crop_pair(a, b)
        s = diffmap.score_pair(a, b)
        s['min_pct'] = entries[n]['min_pct']
        s['pass'] = s['match_pct'] >= s['min_pct']
        n_pass += s['pass']
        scores[n] = s
        rows.append((n, s['match_pct'], s['min_pct'], s['pass'],
                     s['offset'], [r[0] for r in s['regions'][:2]]))
        print('  [%d/%d] %s %.1f%%' % (idx + 1, len(names), n, s['match_pct']), flush=True)

    make_vis(rendered, shots)
    with open(os.path.join(WORK, 'scores.json'), 'w', encoding='utf-8') as f:
        json.dump({'pages': scores,
                   'reports': h.REPORTS[-len(names):]}, f, ensure_ascii=False, indent=1)
    with open(os.path.join(WORK, 'bench_report.md'), 'w', encoding='utf-8') as f:
        f.write('# bench 结果 %s\n\n| 页面 | 匹配率 | 及格线 | 结果 | 对齐偏移 | 最大差异区 |\n|--|--|--|--|--|--|\n' % time.strftime('%Y-%m-%d %H:%M'))
        for n, pct, mp, ok, off, regs in rows:
            rs = '; '.join('%dx%d@%d,%d' % (r[2], r[3], r[0], r[1]) for r in regs)
            f.write('| %s | %.1f%% | %d%% | %s | %s | %s |\n' %
                    (n, pct, mp, 'PASS' if ok else '**FAIL**', str(off), rs))
    print()
    print('%-26s %8s %6s %s' % ('page', 'match', 'min', 'result'))
    fails = []
    for n, pct, mp, ok, off, regs in rows:
        print('%-26s %7.1f%% %5d%% %s' % (n, pct, mp, 'PASS' if ok else 'FAIL'))
        if not ok:
            fails.append(n)
    print('\n%d/%d passed, %d render-failed  ->  %s' % (n_pass, len(names), n_fail, os.path.join(WORK, 'bench_report.md')))
    if fails:
        print('failed pages:', ' '.join(fails))
    if strict and n_pass < len(names):
        sys.exit(1)


def main():
    global SUITE
    argv = sys.argv[1:]
    strict = '--strict' in argv
    argv = [a for a in argv if a != '--strict']
    if '--suite' in argv:
        i = argv.index('--suite')
        SUITE = argv[i + 1]
        del argv[i:i + 2]
    dirs = []
    while '--dir' in argv:
        i = argv.index('--dir')
        dirs.append(argv[i + 1])
        del argv[i:i + 2]
    pages = PAGES
    if SUITE:
        import importlib
        pages = getattr(importlib.import_module(SUITE), 'PAGES')
    entries = {}
    for name, meta in pages.items():
        # 合成页运行时落盘,保证 ext 与 synthetic 走同一路径
        os.makedirs(os.path.join(WORK, 'html'), exist_ok=True)
        p = os.path.join(WORK, 'html', name + '.html')
        io.open(p, 'w', encoding='utf-8').write(meta['html'])
        entries[name] = {'path': p, 'min_pct': meta['min_pct']}
    for d in dirs:
        entries.update(load_external(os.path.abspath(d)))
    filters = argv
    if filters:
        entries = {n: e for n, e in entries.items()
                   if any(f.lower() in n.lower() for f in filters)}
    if not entries:
        sys.exit('no bench pages selected (filters: %s)' % filters)
    run(entries, strict)


if __name__ == '__main__':
    main()
