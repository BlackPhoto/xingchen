# -*- coding: utf-8 -*-
"""
diffmap.py — HTML 原始截图 与 PPTX 转换渲染 的对比工具。

评分模型（v2，修复旧版三缺陷）:
  1. 逐通道 max 差异，不做灰度投影（纯蓝 vs 黑的亮度差只有 29，会漏报）
  2. 全图 ±ALIGN px 平移搜索取最优（1px 全局偏移不再导致整页全红）
  3. 评分掩膜先 MinFilter(3) 收缩（文字 AA 边缘带 1px 噪声不计数），
     区块定位仍用原始掩膜

对每一页输出两张图到 cmp/:
  vis_XX.png   视觉对比:横向长方形页 -> 上下拼接; 竖向 -> 左右拼接。带标签。
  diff_XX.png  差异热力图:超阈值像素标红叠在 PPT 渲染图上,框出最大差异区块。

可导入复用: score_pair(a, b) -> dict(match_pct, bad_px, offset, regions)  (bench.py 使用)

用法:
  python diffmap.py            # 处理全部已找到的页
  python diffmap.py 4 16 17    # 只处理指定页
"""
import os, sys, re
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

BASE = os.path.dirname(os.path.abspath(__file__))
THRESHOLD = 32          # 0-255，任一通道差异超过该值视为"不匹配"
ALIGN = 3               # 平移搜索半径(px)
VIEW_W = 960            # 视觉对比图输出宽度
GAP = 6                 # 拼接间隔
LABEL_H = 30            # 标签条高度

try:
    FONT = ImageFont.truetype(r'C:\Windows\Fonts\msyh.ttc', 20)
except Exception:
    FONT = ImageFont.load_default()

def aligned_pair(i):
    """-> (原始图, 转换图) 裁剪到公共区域（严禁拉伸对齐）"""
    a_path = os.path.join(BASE, "shots", "shot_%02d.png" % i)    # HTML 截图
    b_path = os.path.join(BASE, "render", "slide_%02d.png" % i)  # PPTX 渲染
    if not (os.path.exists(a_path) and os.path.exists(b_path)):
        return None, None
    a = Image.open(a_path).convert("RGB")
    b = Image.open(b_path).convert("RGB")
    if b.size != a.size:
        cw, ch = min(a.size[0], b.size[0]), min(a.size[1], b.size[1])
        a = a.crop((0, 0, cw, ch))
        b = b.crop((0, 0, cw, ch))
    return a, b

def labeled(img, text):
    out = Image.new("RGB", (img.size[0], img.size[1] + LABEL_H), (24, 24, 32))
    d = ImageDraw.Draw(out)
    d.text((10, 5), text, fill=(230, 230, 230), font=FONT)
    out.paste(img, (0, LABEL_H))
    return out

def make_visual(i, a, b):
    """大体视觉对比:横向页上下拼接,竖向页左右拼接"""
    w, h = a.size
    if w >= h:   # 横向长方形 -> 上下拼接
        vis = Image.new("RGB", (w, (h + LABEL_H) * 2 + GAP), (18, 18, 24))
        vis.paste(labeled(a, "原始 HTML"), (0, 0))
        vis.paste(labeled(b, "转换后 PPTX"), (0, h + LABEL_H + GAP))
    else:        # 竖向长方形 -> 左右拼接
        vis = Image.new("RGB", (w * 2 + GAP, h + LABEL_H), (18, 18, 24))
        vis.paste(labeled(a, "原始 HTML"), (0, 0))
        vis.paste(labeled(b, "转换后 PPTX"), (w + GAP, 0))
    scale = VIEW_W / vis.size[0]
    vis = vis.resize((VIEW_W, int(vis.size[1] * scale)))
    out_path = os.path.join(BASE, "cmp", "vis_%02d.png" % i)
    vis.save(out_path)
    return out_path

def _shift(img, dx, dy):
    out = Image.new("RGB", img.size)
    out.paste(img, (dx, dy))
    return out

def _chan_mask(a, b, dx, dy):
    """per-channel max 差异掩膜：任一通道超阈值即标记"""
    d = ImageChops.difference(_shift(a, dx, dy), b)
    m = Image.new("L", a.size, 0)
    for ch in d.split():
        m = ImageChops.lighter(m, ch.point(lambda v: 255 if v > THRESHOLD else 0))
    return m

def best_align(a, b, rng=ALIGN):
    """-> (mask, bad_px, (dx,dy)) 全图平移搜索，取差异像素最少的对齐"""
    best = (None, None, (0, 0))
    for dy in range(-rng, rng + 1):
        for dx in range(-rng, rng + 1):
            m = _chan_mask(a, b, dx, dy)
            n = m.histogram()[255]
            if best[1] is None or n < best[1]:
                best = (m, n, (dx, dy))
    return best

def diff_regions(m_full, min_area=2500):
    """差异掩膜 -> 连通域(4邻接, 4x降采样加速),返回按面积排序的区块
       [(bbox_fullres=(x,y,w,h), area_fullres, density), ...] 按面积降序"""
    w, h = m_full.size
    small = m_full.resize((max(1, w // 4), max(1, h // 4)))
    px = small.load()
    sw, sh = small.size
    seen = [[False] * sw for _ in range(sh)]
    regions = []
    for yy in range(sh):
        for xx in range(sw):
            if seen[yy][xx] or px[xx, yy] < 128: continue
            stack = [(xx, yy)]; seen[yy][xx] = True
            x0 = x1 = xx; y0 = y1 = yy; area = 0
            while stack:
                cx, cy = stack.pop(); area += 1
                x0 = min(x0, cx); x1 = max(x1, cx)
                y0 = min(y0, cy); y1 = max(y1, cy)
                for nx, ny in ((cx-1,cy),(cx+1,cy),(cx,cy-1),(cx,cy+1)):
                    if 0 <= nx < sw and 0 <= ny < sh and not seen[ny][nx] and px[nx, ny] >= 128:
                        seen[ny][nx] = True; stack.append((nx, ny))
            area_full = area * 16
            if area_full >= min_area:
                regions.append(((x0*4, y0*4, (x1-x0+1)*4, (y1-y0+1)*4), area_full,
                                area / max(1, (x1-x0+1) * (y1-y0+1))))
    regions.sort(key=lambda r: -r[1])
    return regions

def score_pair(a, b):
    """-> dict(match_pct, bad_px, offset, regions)。对齐搜索 + AA 降权评分"""
    m, _, off = best_align(a, b)
    total = a.size[0] * a.size[1]
    # 评分用收缩掩膜：1px 的 AA 边缘带消失，真实区块基本不受影响
    m_soft = m.filter(ImageFilter.MinFilter(3))
    bad = m_soft.histogram()[255]
    return {'match_pct': (total - bad) / total * 100.0, 'bad_px': bad,
            'offset': off, 'regions': diff_regions(m)}

def make_diff(i, a, b):
    """差异热力图:差异像素标红叠在 PPT 渲染图上 + 大区块定位
       -> (match_pct, path, regions, offset)"""
    s = score_pair(a, b)
    base = b.copy()
    base.paste(Image.new("RGB", a.size, (255, 0, 0)), (0, 0),
               _chan_mask(_shift(a, *s['offset']), b, 0, 0))
    dd = ImageDraw.Draw(base)
    for k, (bx, by, bw, bh) in enumerate([r[0] for r in s['regions'][:5]], 1):
        dd.rectangle((bx, by, bx + bw, by + bh), outline=(255, 255, 0), width=3)
        dd.text((bx + 4, by + 4), str(k), fill=(255, 255, 0))
    out_path = os.path.join(BASE, "cmp", "diff_%02d.png" % i)
    base.resize((960, int(960 * a.size[1] / a.size[0]))).save(out_path)
    return s['match_pct'], out_path, s['regions'], s['offset']

def make_diff_page(i):
    a, b = aligned_pair(i)
    if a is None:
        print("skip", i, "(缺少原图或截图)")
        return
    ok, diff_path, regions, off = make_diff(i, a, b)
    vis_path = make_visual(i, a, b)
    off_s = "(%d,%d)" % off if off != (0, 0) else "无"
    print("slide %02d: 匹配率=%.1f%%(对齐偏移%s)  热力图=%s  视觉对比=%s" %
          (i, ok, off_s, diff_path, vis_path))
    for k, (bbox, area, dens) in enumerate(regions[:5], 1):
        print("   差异区块%d: 位置(%d,%d) 大小%dx%d 面积%dpX 密度%.0f%%" %
              (k, bbox[0], bbox[1], bbox[2], bbox[3], area, dens * 100))

if __name__ == "__main__":
    os.makedirs(os.path.join(BASE, "cmp"), exist_ok=True)
    nums = [int(x) for x in sys.argv[1:]]
    if not nums:
        nums = []
        for f in sorted(os.listdir(os.path.join(BASE, "shots"))):
            m = re.match(r"shot_(\d+)\.png", f)
            if m: nums.append(int(m.group(1)))
    for n in nums:
        make_diff_page(n)
