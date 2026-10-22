# -*- coding: utf-8 -*-
"""PPT布局缺陷自动检测脚本
检测：文字重叠、文字溢出、模板遮挡、页面大片空白、元素对齐、字号层级
输出JSON供LLM判定缺陷严重程度
v2: 动态读取slide尺寸、视觉形状解析、重叠检测内边距补偿
"""
import sys, io, json, re, zipfile, os
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

EMU_PER_PT = 12700
EMU_PER_CM = 360000
SLIDE_W_EMU_DEFAULT = 9144000  # 10 inch default
SLIDE_H_EMU_DEFAULT = 6858000  # 7.5 inch default
OVERLAP_THRESHOLD_PX = 2  # px, minimum overlap area to flag
BLANK_RATIO_THRESHOLD = 0.90  # 90% blank = flag（仅超过90%空白的页面才记缺陷）
MIN_TEXT_LEN = 2  # ignore decorative single chars
TEXT_PADDING_EMU = 72000  # ~0.2cm, text box internal padding (lIns/rIns/tIns/bIns default ~91440EMU≈0.254cm, use 0.2cm as visual margin)

# Module-level slide dimensions (will be overridden by actual slide size)
SLIDE_W_EMU = SLIDE_W_EMU_DEFAULT
SLIDE_H_EMU = SLIDE_H_EMU_DEFAULT

def parse_emu(val):
    if val is None: return None
    m = re.match(r'(-?\d+)', str(val))
    return int(m.group(1)) if m else None

def emu_to_pt(emu):
    return emu / EMU_PER_PT if emu else 0

def emu_to_cm(emu):
    return emu / EMU_PER_CM if emu else 0

def rect_intersect_area(a, b):
    x1 = max(a['x'], b['x'])
    y1 = max(a['y'], b['y'])
    x2 = min(a['x']+a['w'], b['x']+b['w'])
    y2 = min(a['y']+a['h'], b['y']+b['h'])
    if x2 <= x1 or y2 <= y1: return 0
    return (x2-x1) * (y2-y1)

def rect_area(r):
    return r['w'] * r['h']

def rect_union_area(a, b):
    return rect_area(a) + rect_area(b) - rect_intersect_area(a, b)

def shrink_rect(r, margin):
    """Shrink a rectangle by margin on each side for overlap detection (accounts for text box internal padding)"""
    return {
        'x': r['x'] + margin,
        'y': r['y'] + margin,
        'w': max(0, r['w'] - 2 * margin),
        'h': max(0, r['h'] - 2 * margin),
    }

def parse_slide_xml(xml_str, slide_num, slide_files):
    """解析单页slide XML，提取文本框、图片、群组和视觉形状"""
    textboxes = []
    images = []
    groups = []
    visual_shapes = []

    try:
        from lxml import etree
    except ImportError:
        return textboxes, images, groups, visual_shapes

    try:
        root = etree.fromstring(xml_str.encode('utf-8') if isinstance(xml_str, str) else xml_str)
    except:
        return textboxes, images, groups, visual_shapes

    ns = {
        'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
        'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
        'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    }

    # Check slide layout reference for template elements
    slide_layout_rels = None
    rels_path = f'ppt/slides/_rels/slide{slide_num}.xml.rels'
    if rels_path in slide_files:
        from lxml import etree as et2
        try:
            rels_root = et2.fromstring(slide_files[rels_path])
            for rel in rels_root:
                rtype = rel.get('Type', '')
                if 'slideLayout' in rtype:
                    slide_layout_rels = rel.get('Target', '')
                    break
        except:
            pass

    def parse_sp(sp_elem, is_template=False):
        ph_type = None
        ph_idx = None
        nvSpPr = sp_elem.find('.//{http://schemas.openxmlformats.org/presentationml/2006/main}nvSpPr')
        if nvSpPr is not None and len(list(nvSpPr)) > 0:
            for child in nvSpPr:
                if 'nvPr' in child.tag:
                    nvSpPr_child = child
                    break
            if nvSpPr_child is not None:
                ph = nvSpPr_child.find('p:ph', ns)
                if ph is None:
                    for child in nvSpPr_child:
                        if 'ph' in child.tag and 'http://schemas.openxmlformats.org/presentationml/2006/main' in child.tag:
                            ph = child
                            break
                if ph is not None:
                    ph_type = ph.get('type', 'body')
                    ph_idx = ph.get('idx')

        xfrm = sp_elem.find('.//p:spPr/a:xfrm', ns)
        if xfrm is None:
            for elem in sp_elem.iter():
                if 'xfrm' in elem.tag and 'http://schemas.openxmlformats.org/drawingml/2006/main' in elem.tag:
                    xfrm = elem
                    break
        if xfrm is None: return None

        off = xfrm.find('a:off', ns)
        ext = xfrm.find('a:ext', ns)
        if off is None or ext is None: return None

        x = parse_emu(off.get('x'))
        y = parse_emu(off.get('y'))
        w = parse_emu(ext.get('cx'))
        h = parse_emu(ext.get('cy'))
        if any(v is None for v in [x, y, w, h]): return None
        if w <= 0 or h <= 0: return None

        # Extract text
        texts = []
        font_sizes = []
        for r_elem in sp_elem.iter('{http://schemas.openxmlformats.org/drawingml/2006/main}r'):
            t = r_elem.find('{http://schemas.openxmlformats.org/drawingml/2006/main}t')
            if t is not None and t.text and len(t.text.strip()) >= MIN_TEXT_LEN:
                texts.append(t.text.strip())
                rPr = r_elem.find('{http://schemas.openxmlformats.org/drawingml/2006/main}rPr')
                if rPr is not None:
                    sz = rPr.get('sz')
                    if sz: font_sizes.append(int(sz) / 100)

        text_preview = ' '.join(texts)[:80] if texts else ''
        has_text = len(texts) > 0

        return {
            'slide': slide_num,
            'type': 'template' if is_template else 'content',
            'ph_type': ph_type,
            'x': x, 'y': y, 'w': w, 'h': h,
            'text_preview': text_preview,
            'text_len': sum(len(t) for t in texts),
            'font_sizes': font_sizes,
            'is_template': is_template,
            'has_text': has_text,
        }

    def parse_visual_sp(sp_elem, slide_num):
        """Parse shapes with visual fill (cards, decorative shapes) even without text.
        These fill visual space and should be counted for blank area detection."""
        xfrm = sp_elem.find('.//p:spPr/a:xfrm', ns)
        if xfrm is None:
            for elem in sp_elem.iter():
                if 'xfrm' in elem.tag and 'http://schemas.openxmlformats.org/drawingml/2006/main' in elem.tag:
                    xfrm = elem
                    break
        if xfrm is None: return None

        off = xfrm.find('a:off', ns)
        ext = xfrm.find('a:ext', ns)
        if off is None or ext is None: return None

        x = parse_emu(off.get('x'))
        y = parse_emu(off.get('y'))
        w = parse_emu(ext.get('cx'))
        h = parse_emu(ext.get('cy'))
        if any(v is None for v in [x, y, w, h]): return None
        if w <= 0 or h <= 0: return None

        # Check for fill properties (solidFill, gradFill, pattFill)
        has_fill = False
        spPr = sp_elem.find('.//{http://schemas.openxmlformats.org/presentationml/2006/main}spPr')
        if spPr is None:
            for elem in sp_elem.iter():
                if 'spPr' in elem.tag:
                    spPr = elem
                    break

        if spPr is not None:
            for child in spPr:
                tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                if tag in ('solidFill', 'gradFill', 'pattFill', 'blipFill'):
                    has_fill = True
                    break

        if not has_fill: return None

        # Skip very small decorative elements (< 2cm²)
        area_cm2 = (w / EMU_PER_CM) * (h / EMU_PER_CM)
        if area_cm2 < 2.0:
            return None

        return {
            'slide': slide_num,
            'type': 'visual_shape',
            'x': x, 'y': y, 'w': w, 'h': h,
            'is_template': False,
            'has_text': False,
            'area': w * h,
        }

    def parse_pic(pic_elem, is_template=False):
        xfrm = None
        for elem in pic_elem.iter():
            if 'xfrm' in elem.tag and 'http://schemas.openxmlformats.org/drawingml/2006/main' in elem.tag:
                xfrm = elem
                break
        if xfrm is None: return None

        off = xfrm.find('a:off', ns)
        ext = xfrm.find('a:ext', ns)
        if off is None or ext is None: return None

        x = parse_emu(off.get('x'))
        y = parse_emu(off.get('y'))
        w = parse_emu(ext.get('cx'))
        h = parse_emu(ext.get('h'))
        if any(v is None for v in [x, y, w, h]): return None
        if w <= 0 or h <= 0: return None

        # Check if image is from template (no blipFill or embedded)
        blip = pic_elem.find('.//a:blip', ns)
        has_embedded = blip is not None

        return {
            'slide': slide_num,
            'type': 'image',
            'x': x, 'y': y, 'w': w, 'h': h,
            'is_template': is_template,
            'has_embedded': has_embedded,
            'area': w * h,
        }

    def parse_grp(grp_elem, is_template=False):
        xfrm = None
        for elem in grp_elem.iter():
            if 'xfrm' in elem.tag and 'http://schemas.openxmlformats.org/drawingml/2006/main' in elem.tag:
                # Only take the first xfrm (group level, not child level)
                if 'grpSpPr' in (elem.getparent().tag if elem.getparent() is not None else ''):
                    xfrm = elem
                    break
        if xfrm is None: return None

        off = xfrm.find('a:off', ns)
        ext = xfrm.find('a:ext', ns)
        if off is None or ext is None: return None

        x = parse_emu(off.get('x'))
        y = parse_emu(off.get('y'))
        w = parse_emu(ext.get('cx'))
        h = parse_emu(ext.get('cy'))
        if any(v is None for v in [x, y, w, h]): return None
        if w <= 0 or h <= 0: return None

        return {
            'slide': slide_num,
            'type': 'group',
            'x': x, 'y': y, 'w': w, 'h': h,
            'is_template': is_template,
        }

    # Parse shape tree
    sp_tree = root.find('.//p:spTree', ns)
    if sp_tree is None:
        return textboxes, images, groups, visual_shapes

    for child in sp_tree:
        tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
        if tag == 'sp':
            result = parse_sp(child, is_template=False)
            if result and result.get('has_text'):
                textboxes.append(result)
            elif result and not result.get('has_text'):
                # Shape without text - check if it has visual fill
                visual = parse_visual_sp(child, slide_num)
                if visual:
                    visual_shapes.append(visual)
            else:
                # parse_sp returned None, still try visual shape
                visual = parse_visual_sp(child, slide_num)
                if visual:
                    visual_shapes.append(visual)
        elif tag == 'pic':
            result = parse_pic(child, is_template=False)
            if result: images.append(result)
        elif tag == 'grpSp':
            result = parse_grp(child, is_template=False)
            if result: groups.append(result)

    return textboxes, images, groups, visual_shapes


def is_aigc_watermark(text):
    """判断文本框是否为系统AIGC水印/标识文字"""
    if not text:
        return False
    keywords = ['AI生成', '生成时间', 'AIGC标识', 'AIGC']
    return any(kw in text for kw in keywords)


def detect_overlaps(elements, slide_num, total_pages):
    """检测文本框之间的重叠（扣除文本框内部边距后再判定）"""
    issues = []
    text_elems = [e for e in elements if e.get('has_text') and not e.get('is_template')]

    for i in range(len(text_elems)):
        for j in range(i+1, len(text_elems)):
            a, b = text_elems[i], text_elems[j]
            # 跳过AIGC水印/标识文字与任何元素的重叠（系统后处理自动添加，不计缺陷）
            if is_aigc_watermark(a.get('text_preview', '')) or is_aigc_watermark(b.get('text_preview', '')):
                continue
            # Shrink bounding boxes by TEXT_PADDING_EMU to account for internal text margins
            a_shrunk = shrink_rect(a, TEXT_PADDING_EMU)
            b_shrunk = shrink_rect(b, TEXT_PADDING_EMU)
            inter = rect_intersect_area(a_shrunk, b_shrunk)
            if inter <= 0: continue
            # Only flag if overlap is significant relative to smaller element
            min_area = min(rect_area(a_shrunk), rect_area(b_shrunk))
            overlap_ratio = inter / min_area if min_area > 0 else 0
            if overlap_ratio > 0.05:  # >5% overlap of smaller element
                issues.append({
                    'defect': 'P-V4',
                    'name': '字体重叠',
                    'slide': slide_num,
                    'detail': f"第{slide_num}页: 「{a['text_preview'][:30]}」与「{b['text_preview'][:30]}」重叠，重叠面积占比{overlap_ratio:.1%}（较小元素，已扣除文本框内边距）",
                    'overlap_ratio': round(overlap_ratio, 4),
                    'elem_a': {'text': a['text_preview'][:40], 'bbox': f"({emu_to_cm(a['x']):.1f},{emu_to_cm(a['y']):.1f},{emu_to_cm(a['w']):.1f}x{emu_to_cm(a['h']):.1f}cm)"},
                    'elem_b': {'text': b['text_preview'][:40], 'bbox': f"({emu_to_cm(b['x']):.1f},{emu_to_cm(b['y']):.1f},{emu_to_cm(b['w']):.1f}x{emu_to_cm(b['h']):.1f}cm)"},
                })
    return issues


def detect_overflow(elements, slide_num, total_pages):
    """检测文字溢出：文本框溢出页面边界 + 文字内容超出文本框"""
    issues = []
    for e in elements:
        if not e.get('has_text') or e.get('is_template'): continue
        
        # --- 检测1：文本框溢出页面边界 ---
        overflow_right = max(0, (e['x'] + e['w']) - SLIDE_W_EMU)
        overflow_bottom = max(0, (e['y'] + e['h']) - SLIDE_H_EMU)
        overflow_left = max(0, -e['x'])
        overflow_top = max(0, -e['y'])
        total_overflow = overflow_right + overflow_bottom + overflow_left + overflow_top
        if total_overflow > 50000:  # > ~0.14cm
            issues.append({
                'defect': 'P-V5',
                'name': '字体溢出',
                'slide': slide_num,
                'detail': f"第{slide_num}页: 「{e['text_preview'][:30]}」溢出页面边界，"
                         f"上{emu_to_cm(overflow_top):.1f} 下{emu_to_cm(overflow_bottom):.1f} "
                         f"左{emu_to_cm(overflow_left):.1f} 右{emu_to_cm(overflow_right):.1f}cm",
            })
            continue
        
        # --- 检测2：文字内容超出文本框（按字体大小估算） ---
        if not e.get('font_sizes') or not e.get('text_len'):
            continue
        
        max_font_pt = max(e['font_sizes'])
        if max_font_pt <= 0:
            continue
        
        box_w_inch = e['w'] / EMU_PER_CM * 0.3937  # EMU to inches
        box_h_inch = e['h'] / EMU_PER_CM * 0.3937
        
        if box_w_inch <= 0 or box_h_inch <= 0:
            continue
        
        # 估算字符宽度：中文字符 ≈ font_size/72 inch，英文/数字 ≈ font_size/72 * 0.5 inch
        # 按混合比例估算，取中间值 0.75
        char_width_inch = (max_font_pt / 72.0) * 0.75
        line_height_inch = max_font_pt / 72.0 * 1.3  # 行高约1.3倍字号
        
        chars_per_line = int(box_w_inch / char_width_inch) if char_width_inch > 0 else 999
        if chars_per_line <= 0:
            chars_per_line = 1
        
        text_len = e['text_len']
        if text_len <= chars_per_line:
            continue  # 一行能放下
        
        # 需要换行
        lines_needed = (text_len + chars_per_line - 1) // chars_per_line
        needed_height = lines_needed * line_height_inch
        
        if needed_height > box_h_inch:
            excess_pct = (needed_height - box_h_inch) / box_h_inch
            issues.append({
                'defect': 'P-V5',
                'name': '字体溢出',
                'slide': slide_num,
                'detail': f"第{slide_num}页: 「{e['text_preview'][:30]}」文字内容超出文本框，"
                         f"文本框高{box_h_inch:.2f}inch，{max_font_pt:.0f}pt字号约需{lines_needed}行({needed_height:.2f}inch)，超出{excess_pct:.0%}",
            })
    
    return issues


def detect_template_occlusion(elements, slide_num, total_pages):
    """检测模板元素遮挡内容元素"""
    issues = []
    content_elems = [e for e in elements if e.get('has_text') and not e.get('is_template')]
    template_elems = [e for e in elements if e.get('is_template') or e.get('type') == 'group']

    if not template_elems or not content_elems: return issues

    for ce in content_elems:
        for te in template_elems:
            inter = rect_intersect_area(ce, te)
            if inter <= 0: continue
            overlap_ratio = inter / rect_area(ce) if rect_area(ce) > 0 else 0
            if overlap_ratio > 0.10:  # >10% of content element occluded
                te_desc = te.get('text_preview', '模板图形元素')[:30]
                issues.append({
                    'defect': 'P-V4',
                    'name': '模板遮挡',
                    'slide': slide_num,
                    'detail': f"第{slide_num}页: 模板元素「{te_desc}」遮挡内容「{ce['text_preview'][:30]}」，遮挡{overlap_ratio:.1%}",
                    'overlap_ratio': round(overlap_ratio, 4),
                })
    return issues


def is_toc_page(elements, slide_num):
    """检测目录页：含"目录"等关键词的页面"""
    text_elems = [e for e in elements if e.get('has_text') and not e.get('is_template')]
    toc_keywords = ['目录', '目 录', 'contents', 'Contents', 'CONTENTS', '目录页']
    for e in text_elems:
        text = e.get('text_preview', '')
        if any(kw in text for kw in toc_keywords):
            return True
    return False


def is_chapter_transition_page(elements, slide_num):
    """检测章节过渡页：有标题但无/极少正文内容的页面
    
    章节过渡页特征：
    - 有标题型placeholder（ctrTitle/title）
    - 无正文型placeholder或正文内容极少
    - 整体文本元素很少（通常仅标题+可能的副标题/装饰文字）
    """
    text_elems = [e for e in elements if e.get('has_text') and not e.get('is_template')]
    
    if not text_elems:
        return False
    
    has_title = False
    has_body = False
    body_text_len = 0
    
    for e in text_elems:
        ph = e.get('ph_type', '')
        if ph in ('title', 'ctrTitle'):
            has_title = True
        elif ph in ('body', 'obj'):
            has_body = True
            body_text_len += e.get('text_len', 0)
    
    # 有标题且无正文 → 章节过渡页
    if has_title and not has_body:
        return True
    
    # 有标题但正文极少（≤20字符） → 章节过渡页
    if has_title and body_text_len <= 20:
        return True
    
    # 整页仅有1-2个文本元素且内容很短 → 可能是章节过渡页
    if len(text_elems) <= 2 and sum(e.get('text_len', 0) for e in text_elems) <= 30:
        return True
    
    return False


def detect_blank_areas(elements, slide_num, total_pages):
    """检测页面大片空白（包含文本框、图片和视觉形状）
    
    豁免规则（仅检测正文页，以下结构页均豁免）：
    - 首页（封面页）：留白属于有意设计
    - 目录页：含"目录"关键词的页面
    - 章节过渡页：有标题但无/极少正文内容的页面
    - 尾页（末页）：留白属于有意设计
    """
    issues = []
    
    # 结构页豁免：首页、尾页的空白属于设计留白，不检测
    if slide_num == 1 or slide_num == total_pages:
        return issues
    
    # 目录页豁免
    if is_toc_page(elements, slide_num):
        return issues
    
    # 章节过渡页豁免
    if is_chapter_transition_page(elements, slide_num):
        return issues
    
    content_areas = []
    for e in elements:
        if e.get('has_text') and not e.get('is_template'):
            content_areas.append((e['x'], e['y'], e['w'], e['h']))
        elif e.get('type') == 'image' and e.get('has_embedded'):
            content_areas.append((e['x'], e['y'], e['w'], e['h']))
        elif e.get('type') == 'visual_shape':
            # Shapes with fill (cards, backgrounds) also fill visual space
            content_areas.append((e['x'], e['y'], e['w'], e['h']))

    if not content_areas:
        issues.append({
            'defect': 'P-V3',
            'name': '页面大片空白',
            'slide': slide_num,
            'detail': f"第{slide_num}页: 无实质内容元素（页面完全空白）",
            'blank_ratio': 1.0,
        })
        return issues

    # Calculate union of content areas using grid sampling
    grid_res = 50
    cell_w = SLIDE_W_EMU / grid_res
    cell_h = SLIDE_H_EMU / grid_res
    filled = 0
    total = grid_res * grid_res
    for gi in range(grid_res):
        for gj in range(grid_res):
            cx = gi * cell_w
            cy = gj * cell_h
            for (ax, ay, aw, ah) in content_areas:
                if ax <= cx < ax+aw and ay <= cy < ay+ah:
                    filled += 1
                    break

    blank_ratio = 1.0 - filled / total
    if blank_ratio > BLANK_RATIO_THRESHOLD:
        issues.append({
            'defect': 'P-V3',
            'name': '页面大片空白',
            'slide': slide_num,
            'detail': f"第{slide_num}页: 内容仅占{(1-blank_ratio):.0%}页面面积，空白区域约{blank_ratio:.0%}",
            'blank_ratio': round(blank_ratio, 4),
        })
    return issues


def detect_font_size_hierarchy(elements, slide_num, total_pages):
    """检测字号层级是否清晰"""
    issues = []
    text_elems = [e for e in elements if e.get('has_text') and e.get('font_sizes') and not e.get('is_template')]

    if len(text_elems) < 2: return issues

    # Collect all font sizes and their roles
    all_sizes = []
    for e in text_elems:
        ph = e.get('ph_type', '')
        max_sz = max(e['font_sizes']) if e['font_sizes'] else 0
        all_sizes.append({
            'ph_type': ph,
            'max_size': max_sz,
            'text': e['text_preview'][:40],
        })

    # Check: title vs body size difference
    titles = [s for s in all_sizes if s['ph_type'] in ('title', 'ctrTitle')]
    bodies = [s for s in all_sizes if s['ph_type'] in ('body', 'obj')]
    subtitles = [s for s in all_sizes if s['ph_type'] in ('subTitle',)]

    if titles and bodies:
        avg_title = sum(t['max_size'] for t in titles) / len(titles)
        avg_body = sum(b['max_size'] for b in bodies) / len(bodies)
        if avg_body > 0 and (avg_title - avg_body) < 4:  # <4pt difference
            issues.append({
                'defect': 'P-V7',
                'name': '字号层级混乱',
                'slide': slide_num,
                'detail': f"第{slide_num}页: 标题平均{avg_title:.0f}pt，正文平均{avg_body:.0f}pt，仅差{avg_title-avg_body:.0f}pt，层级不清晰",
                'title_size': round(avg_title, 1),
                'body_size': round(avg_body, 1),
            })

    if subtitles and bodies:
        avg_sub = sum(s['max_size'] for s in subtitles) / len(subtitles)
        avg_body = sum(b['max_size'] for b in bodies) / len(bodies)
        if avg_body > 0 and abs(avg_sub - avg_body) < 2:
            issues.append({
                'defect': 'P-V7',
                'name': '字号层级混乱',
                'slide': slide_num,
                'detail': f"第{slide_num}页: 副标题{avg_sub:.0f}pt与正文{avg_body:.0f}pt几乎无差异",
            })

    # Check: all elements same font size
    if len(all_sizes) >= 3:
        sizes = [s['max_size'] for s in all_sizes if s['max_size'] > 0]
        if sizes and (max(sizes) - min(sizes)) < 2:
            issues.append({
                'defect': 'P-V7',
                'name': '字号层级混乱',
                'slide': slide_num,
                'detail': f"第{slide_num}页: 所有文本元素字号几乎一致（{min(sizes):.0f}~{max(sizes):.0f}pt），无法区分信息层级",
            })

    return issues


def detect_alignment(elements, slide_num, total_pages):
    """检测元素对齐问题"""
    issues = []
    content_elems = [e for e in elements if e.get('has_text') and not e.get('is_template')]
    if len(content_elems) < 3: return issues

    # Check left alignment consistency
    left_edges = [e['x'] for e in content_elems]
    left_edges_sorted = sorted(left_edges)
    # Group by proximity (within 0.3cm)
    groups = []
    current_group = [left_edges_sorted[0]]
    for x in left_edges_sorted[1:]:
        if x - current_group[-1] < EMU_PER_CM * 0.3:
            current_group.append(x)
        else:
            groups.append(current_group)
            current_group = [x]
    groups.append(current_group)

    # If many different left edges, alignment is inconsistent
    unique_edges = len(groups)
    if unique_edges > len(content_elems) * 0.6:
        issues.append({
            'defect': 'P-V13',
            'name': '对齐不规范',
            'slide': slide_num,
            'detail': f"第{slide_num}页: {len(content_elems)}个文本元素有{unique_edges}个不同的左边缘位置，对齐不一致",
        })

    return issues


def detect_color_contrast(elements, slide_num, total_pages):
    """检测文字颜色与背景色对比度（基本检测）"""
    issues = []
    # This is a basic check - look for very light text colors that may indicate low contrast
    for e in elements:
        if not e.get('has_text') or e.get('is_template'): continue
        # We can't easily get background color from slide XML alone
        # But we can check for white/near-white text which often indicates issues
        # This is a placeholder for more sophisticated detection
        pass
    return issues


def read_slide_dimensions(all_files):
    """从presentation.xml读取实际slide尺寸"""
    global SLIDE_W_EMU, SLIDE_H_EMU
    pres_path = 'ppt/presentation.xml'
    if pres_path not in all_files:
        return

    try:
        from lxml import etree
        pres_xml = all_files[pres_path]
        pres_root = etree.fromstring(pres_xml if isinstance(pres_xml, bytes) else pres_xml.encode('utf-8'))

        # Find sldSz element
        ns_p = 'http://schemas.openxmlformats.org/presentationml/2006/main'
        sldSz = pres_root.find(f'{{{ns_p}}}sldSz')
        if sldSz is None:
            # Try without namespace
            for elem in pres_root:
                if 'sldSz' in elem.tag:
                    sldSz = elem
                    break

        if sldSz is not None:
            cx = parse_emu(sldSz.get('cx'))
            cy = parse_emu(sldSz.get('cy'))
            if cx and cx > 0:
                SLIDE_W_EMU = cx
            if cy and cy > 0:
                SLIDE_H_EMU = cy
    except Exception:
        pass  # Fallback to defaults


def run_detection(pptx_path):
    """主检测函数"""
    global SLIDE_W_EMU, SLIDE_H_EMU

    results = {
        'file': os.path.basename(pptx_path),
        'total_slides': 0,
        'slides_analyzed': 0,
        'slide_dimensions': {
            'width_inches': round(SLIDE_W_EMU / 914400, 2),
            'height_inches': round(SLIDE_H_EMU / 914400, 2),
        },
        'issues': {
            'P-V4': [],  # 文字重叠/遮挡
            'P-V5': [],  # 文字溢出
            'P-V3': [],  # 页面空白
            'P-V7': [],  # 字号层级
            'P-V13': [], # 对齐
        },
        'summary': {},
        'per_slide_elements': {},
    }

    try:
        zf = zipfile.ZipFile(pptx_path, 'r')
    except Exception as e:
        print(json.dumps({'error': f'无法打开文件: {e}'}, ensure_ascii=False))
        sys.exit(1)

    all_files = {name: zf.read(name) for name in zf.namelist()}

    # Read actual slide dimensions from presentation.xml
    read_slide_dimensions(all_files)
    results['slide_dimensions'] = {
        'width_inches': round(SLIDE_W_EMU / 914400, 2),
        'height_inches': round(SLIDE_H_EMU / 914400, 2),
    }

    # Find all slide files
    slide_files = {}
    slide_pattern = re.compile(r'^ppt/slides/slide(\d+)\.xml$')
    for name in all_files:
        slide_files[name] = all_files[name]

    slide_nums = []
    for name in all_files:
        m = slide_pattern.match(name)
        if m:
            slide_nums.append(int(m.group(1)))

    slide_nums.sort()
    results['total_slides'] = len(slide_nums)
    total = len(slide_nums)

    for sn in slide_nums:
        slide_path = f'ppt/slides/slide{sn}.xml'
        if slide_path not in all_files: continue

        xml_str = all_files[slide_path].decode('utf-8')
        textboxes, images, groups, visual_shapes = parse_slide_xml(xml_str, sn, slide_files)

        all_elements = textboxes + images + groups + visual_shapes
        results['per_slide_elements'][sn] = {
            'textboxes': len(textboxes),
            'images': len(images),
            'groups': len(groups),
            'visual_shapes': len(visual_shapes),
        }
        results['slides_analyzed'] += 1

        # Run all detectors
        for issue in detect_overlaps(all_elements, sn, total):
            results['issues']['P-V4'].append(issue)
        for issue in detect_overflow(all_elements, sn, total):
            results['issues']['P-V5'].append(issue)
        for issue in detect_template_occlusion(all_elements, sn, total):
            results['issues']['P-V4'].append(issue)
        for issue in detect_blank_areas(all_elements, sn, total):
            results['issues']['P-V3'].append(issue)
        for issue in detect_font_size_hierarchy(all_elements, sn, total):
            results['issues']['P-V7'].append(issue)
        # P-V13 对齐检测已取消（多栏/多卡片布局天然产生多个左边缘，属设计意图）
        # for issue in detect_alignment(all_elements, sn, total):
        #     results['issues']['P-V13'].append(issue)

    # Calculate total text elements across all slides
    total_text_elems = sum(
        results['per_slide_elements'].get(sn, {}).get('textboxes', 0)
        for sn in results['per_slide_elements']
    )

    # Build summary
    for defect_id, issues in results['issues'].items():
        affected_slides = list(set(i['slide'] for i in issues))
        results['summary'][defect_id] = {
            'count': len(issues),
            'affected_slides': len(affected_slides),
            'page_ratio': len(affected_slides) / total if total > 0 else 0,
            'slide_list': affected_slides,
            # Element-level ratio for low-page PPT correction
            'elem_ratio': 0.0,
            'defect_elem_count': 0,
            'total_text_elems': total_text_elems,
        }

    # Calculate element-level ratio for each defect
    for defect_id, issues in results['issues'].items():
        if not issues:
            continue
        # Count distinct defect elements (each issue = 1 element)
        defect_elem_count = len(issues)
        elem_ratio = defect_elem_count / total_text_elems if total_text_elems > 0 else 0
        results['summary'][defect_id]['elem_ratio'] = round(elem_ratio, 4)
        results['summary'][defect_id]['defect_elem_count'] = defect_elem_count

    zf.close()
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(json.dumps({'error': '用法: python detect_layout.py <pptx文件路径>'}, ensure_ascii=False))
        sys.exit(1)
    run_detection(sys.argv[1])
