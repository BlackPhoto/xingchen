#!/usr/bin/env python3
"""
html2docx_core.py — 核心层处理（6 种 IR，覆盖 90% 场景）

IR 类型：title_page / heading / paragraph / bullet_list / table / image

被 html2docx.py 主入口 import。
被 html2docx_scene.py / html2docx_advanced.py 跨层 import（process_table / _extract_img_bytes）。
"""

import base64
import io
import re

from bs4 import Tag

from sem_common import get_text_content, parse_table_data
from docx_utils import (
    DEFAULT_FONT, CODE_FONT,
    hex_to_rgb, is_dark_color,
    extract_bg_with_gradient_fallback, extract_bg_from_styles,
    extract_color_from_styles, extract_text_align_from_styles,
    extract_font_size_from_styles,
    extract_img_width_px, get_inline_style_prop,
    set_run_font, add_page_break, inject_page_break_before, flush_pending_page_break,
    set_cell_margins, set_table_borders_nil, set_table_borders,
    apply_shading, apply_shading_to_cell, apply_shading_to_run,
    blend_rgba_with_bg, set_table_width_percent,
)
from docx.shared import Inches, Pt, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT, WD_ROW_HEIGHT_RULE
from docx.oxml import OxmlElement


def process_title_page(doc, section, palette, first_block, parsed_styles=None, soup=None):
    """封面页 → 深色渐变底色 + 居中白字标题 + accent 副标题 + 装饰横线，封面独占一页

    实现方式：1x1 表格承载封面内容，单元格设置垂直居中 + 水平居中，
    达到封面内容在页面"上下居中 + 左右居中"的效果。
    背景色优先级：内联 style > <style> 块 .title 选择器 > 调色板主色
    """
    if not first_block:
        add_page_break(doc)
    # 背景色：先内联 style，再从 <style> 块选择器提取（渐变→中间色）
    # 选择器优先级：.slide.hero（mode-deck 深色渐变封面）> .title > section.title
    bg_color = extract_bg_with_gradient_fallback(section.get("style", ""))
    if not bg_color:
        bg_color = extract_bg_from_styles(
            parsed_styles, [".slide.hero", ".title", "section.title"], soup)
    # 封面底色降级：无背景时用调色板主色/主色浅色（优先深色渐变感）
    if not bg_color:
        bg_color = palette.get("primary", "1e293b")
    # 深底 → 白字；浅底 → 主色字
    dark_bg = is_dark_color(bg_color)
    # 主标题颜色：优先读取 HTML 中 .slide.hero h1 / .title h1 的 color 定义
    title_color = extract_color_from_styles(
        parsed_styles,
        [".slide.hero h1", ".title h1", "section.title h1", ".title > h1"],
        soup,
        default="#ffffff" if dark_bg else palette.get("primary", "1e293b"),
    )
    accent_color = palette.get("accent", "64748b")
    # 副标题颜色：优先读取 HTML 中 .slide.hero p / .title p 的 color 定义
    sub_color = extract_color_from_styles(
        parsed_styles,
        [".slide.hero p", ".title p", "section.title p", ".title > p"],
        soup,
        default="#f1f5f9" if dark_bg else accent_color,
    )

    h1 = section.find("h1")
    ps = section.find_all("p")
    title_text = get_text_content(h1) if h1 else ""

    # 检测封面 eyebrow 标签（小字号胶囊样式）
    eyebrow = section.find(class_="eyebrow")
    eyebrow_text = get_text_content(eyebrow) if eyebrow else ""

    # 检测封面标题前的裸 div（无语义 class，如"ANNUAL REVIEW"、"2026 全新一代"）
    # mode-deck 封面常在 h1 之前用裸 div 承载 eyebrow 文字（可能有 display:inline-block 胶囊，
    # 也可能无 display 属性）。此前只识别 inline-block 裸 div，导致无 display 的裸 div
    # （如"ANNUAL REVIEW"）落入末尾兜底分支、输出顺序错误（沉底）。
    # 放宽：收集 h1 之前所有含文本的裸 div（除非带语义 class），按 HTML 顺序输出为 eyebrow。
    _extra_eyebrow_items = []  # [(text, element), ...] 保持 HTML 顺序
    if not eyebrow_text and h1:
        for child in section.children:
            if not isinstance(child, Tag):
                continue
            if child.name == "h1":
                break  # 遇到 h1 停止（只看标题前的元素）
            child_classes = child.get("class", []) or []
            # 跳过有语义 class 的元素（accent-line / title-meta / badge-row / hero-year 等）
            if any(c in child_classes for c in ("accent-line", "title-meta", "badge-row", "hero-year")):
                continue
            # 捕获 h1 之前含文本的裸 div（不再要求 display:inline-block）
            # 排除含 h1 的 div（如 div.hero-body）：它不是 eyebrow，而是标题容器，
            # 若误判为 eyebrow 会将整个 hero-body 内容（h1+副标题）重复输出。
            if child.name == "div":
                if child.find("h1"):
                    continue
                t = get_text_content(child)
                if t:
                    _extra_eyebrow_items.append((t, child))
    # 检测封面 title-meta（数据指标行）
    title_meta = section.find(class_="title-meta")
    meta_items = []
    if title_meta:
        for item in title_meta.find_all(class_="meta-item"):
            val_el = item.find(class_="value")
            label_el = item.find(class_="label")
            if val_el and label_el:
                meta_items.append((get_text_content(val_el), get_text_content(label_el)))

    # 检测封面内嵌图片（.hero-img img 或直接 img）
    img = section.find("img")
    img_bytes = _extract_img_bytes(img) if img else None

    # 1x1 表格承载封面，实现垂直居中
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_table_borders_nil(table)
    set_table_width_percent(table, 100)
    cell = table.cell(0, 0)
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    set_cell_margins(cell, top=120, start=120, bottom=120, end=120)
    # 行高动态计算：按页面实际可用高度设置（A4 纵向 29.7cm − 上下边距 1.5cm×2 = 26.7cm），
    # 避免写死 24cm 导致封面内容偏上（未占满整页，垂直居中只在表格内部生效）。
    # AT_LEAST 规则保证内容超长时自动扩展不会被截断。
    _page_h = 29.7  # A4 纵向（默认值，docx 尚未设置 section 时用默认）
    try:
        _sec = doc.sections[0]
        _page_h = _sec.page_height / 360000.0  # EMU → cm (1cm=360000EMU)
    except Exception:
        pass
    _top_m = 1.5
    _bot_m = 1.5
    try:
        _top_m = doc.sections[0].top_margin / 360000.0
        _bot_m = doc.sections[0].bottom_margin / 360000.0
    except Exception:
        pass
    _avail_h = max(_page_h - _top_m - _bot_m, 20.0)  # 兜底不低于 20cm
    row = table.rows[0]
    row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
    row.height = Cm(_avail_h)

    # 机密信息（page-header / confidential-watermark）→ 封面左上角
    # 从 soup 全局查找这些元素（它们是 body 直接子元素，不在 section.title 内），
    # 提取文本后以左对齐、小字号输出在封面单元格顶部。
    _conf_prefix_lines = []  # [(text, is_bold), ...]
    if soup:
        wm = soup.find(class_="confidential-watermark")
        if wm:
            wm_text = get_text_content(wm)
            if wm_text:
                _conf_prefix_lines.append((wm_text, True))
        hdr = soup.find(class_="page-header")
        if hdr:
            hdr_text = get_text_content(hdr)
            if hdr_text:
                _conf_prefix_lines.append((hdr_text, False))

    if _conf_prefix_lines:
        # 机密信息占用第一个段落（左对齐），后续标题/副标题新建段落
        conf_para = cell.paragraphs[0]
        conf_para.alignment = WD_ALIGN_PARAGRAPH.LEFT
        conf_para.paragraph_format.space_before = Pt(0)
        conf_para.paragraph_format.space_after = Pt(10)
        if bg_color:
            apply_shading(conf_para, bg_color)
        for ci, (ctext, cbold) in enumerate(_conf_prefix_lines):
            if ci > 0:
                conf_para.add_run("\n")
            run_c = conf_para.add_run(ctext)
            c_color = "#ffffff" if dark_bg else palette.get("primary", "1e293b")
            set_run_font(run_c, size=Pt(10), bold=cbold, color=hex_to_rgb(c_color))
        _title_para_pool = None  # 标题段落需要新建
    else:
        _title_para_pool = cell.paragraphs[0]  # 无机密信息时，标题用第一个段落

    # ===== 封面徽章（.badge-row .status-pill）：标题上方，与 HTML 顺序一致 =====
    # HTML 中封面可能是 <div class="badge-row"><span class="status-pill danger">…</span>…
    # 转换脚本此前不认识 badge-row，会落入下方"兜底输出"分支被追加到封面末尾。
    # 这里显式识别，在标题之前按 HTML 顺序输出，视觉降级为字符底纹胶囊。
    badge_row = section.find(class_="badge-row")
    badge_pills = []
    if badge_row:
        for pill in badge_row.find_all(class_="status-pill"):
            pill_text = get_text_content(pill)
            if not pill_text:
                continue
            # 提取前景/背景色：内联 style 优先，再从 <style> 块按类选择器提取
            pill_style = pill.get("style", "") or ""
            pill_classes = pill.get("class", [])
            pill_sel = ".".join(["." + c for c in pill_classes])
            pill_bg = extract_bg_with_gradient_fallback(pill_style)
            if not pill_bg:
                pill_bg = extract_bg_from_styles(
                    parsed_styles, [pill_sel, ".title " + pill_sel], soup)
            pill_fg = extract_color_from_styles(
                parsed_styles, [pill_sel, ".title " + pill_sel], soup,
                inline_style=pill_style)
            # rgba 半透明背景（如 info 徽章 rgba(255,255,255,0.2)）与封面底色混合成不透明色
            if pill_bg and pill_bg.startswith("rgba"):
                pill_bg = blend_rgba_with_bg(pill_bg, bg_color)
            # 前景色兜底：danger → 深红；其余 → 白/主色
            if not pill_fg:
                if "danger" in pill_classes:
                    pill_fg = "c62828"
                elif "warning" in pill_classes:
                    pill_fg = "e65100"
                elif "success" in pill_classes:
                    pill_fg = "2e7d32"
                else:
                    pill_fg = "ffffff" if dark_bg else accent_color
            # 背景色兜底：danger 浅粉底；info/其余 半透明白混合后的浅色
            if not pill_bg:
                if "danger" in pill_classes:
                    pill_bg = "fce4ec"
                elif "warning" in pill_classes:
                    pill_bg = "fff3e0"
                elif "success" in pill_classes:
                    pill_bg = "e8f5e9"
                else:
                    # info / 未知徽章：深色封面上用半透明白混合出的浅色底
                    pill_bg = blend_rgba_with_bg("rgba(255,255,255,0.25)", bg_color) or "eef3f9"
            badge_pills.append((pill_text, pill_fg, pill_bg))

    if badge_pills:
        if _title_para_pool is not None:
            # 无机密信息：徽章占用第一个段落，标题/eyebrow 后续新建
            badge_para = _title_para_pool
            _title_para_pool = None
        else:
            badge_para = cell.add_paragraph()
        badge_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        badge_para.paragraph_format.space_before = Pt(0)
        badge_para.paragraph_format.space_after = Pt(12)
        if bg_color:
            apply_shading(badge_para, bg_color)
        for bi, (btxt, bfg, bbg) in enumerate(badge_pills):
            if bi > 0:
                # 徽章之间用全角空格分隔（Word 中并排效果）
                sep_run = badge_para.add_run("\u3000")
                sep_run.font.name = DEFAULT_FONT
                set_run_font(sep_run, size=Pt(12), color=hex_to_rgb(bfg))
            run_b = badge_para.add_run(btxt)
            set_run_font(run_b, size=Pt(12), bold=True, color=hex_to_rgb(bfg))
            if bbg:
                apply_shading_to_run(run_b, bbg)

    # eyebrow 标签（小字号胶囊样式，标题之前）
    # 支持多个：.eyebrow 单个 + h1 前裸 div 列表（_extra_eyebrow_items），按 HTML 顺序输出
    _eyebrow_paras = []
    if eyebrow_text:
        _eyebrow_paras.append(eyebrow_text)
    if _extra_eyebrow_items:
        _eyebrow_paras.extend([t for t, _el in _extra_eyebrow_items])

    # hero-year（.hero-year 类，如"2026"）：标题后、装饰线前输出大号年份
    # 读取内联/CSS font-size，映射 Pt；颜色用 palette accent 金色（CSS 渐变无法还原）
    hero_year_text = ""
    hero_year_size = None
    hero_year = section.find(class_="hero-year")
    if hero_year:
        _t = get_text_content(hero_year)
        if _t:
            hero_year_text = _t
            # 字号：内联 font-size 优先，再查 <style> 块 .hero-year
            inline_fs = get_inline_style_prop(hero_year.get("style", ""), "font-size")
            if inline_fs:
                hero_year_size = inline_fs
            else:
                hero_year_size = extract_font_size_from_styles(
                    parsed_styles, [".hero-year", ".title .hero-year"], soup)

    if _eyebrow_paras:
        if _title_para_pool is not None:
            # 无机密信息：eyebrow 占用第一个段落，标题新建
            eb_para = _title_para_pool
            _title_para_pool = None
        else:
            # 有机密信息：eyebrow 和标题都新建段落
            eb_para = cell.add_paragraph()
        eb_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        eb_para.paragraph_format.space_before = Pt(0)
        eb_para.paragraph_format.space_after = Pt(12)
        if bg_color:
            apply_shading(eb_para, bg_color)
        eb_color = "#ffffff" if dark_bg else accent_color
        # 多个 eyebrow 项目：同一段落内用全角空格分隔，保持视觉在同一行
        for ei, eb_text in enumerate(_eyebrow_paras):
            if ei > 0:
                sep_eb = eb_para.add_run("\u3000")
                set_run_font(sep_eb, size=Pt(11), color=hex_to_rgb(eb_color))
            run_eb = eb_para.add_run(eb_text)
            set_run_font(run_eb, size=Pt(11), bold=True, color=hex_to_rgb(eb_color))
        title_para = cell.add_paragraph()
    else:
        title_para = _title_para_pool if _title_para_pool is not None else cell.add_paragraph()

    # 标题（居中）
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_para.paragraph_format.space_before = Pt(0)
    title_para.paragraph_format.space_after = Pt(8)
    if bg_color:
        apply_shading(title_para, bg_color)
    run = title_para.add_run(title_text)
    set_run_font(run, size=Pt(28), bold=True, color=hex_to_rgb(title_color))

    # hero-year 大号年份：标题后、装饰线前（与 HTML 顺序一致）
    if hero_year_text:
        hy_para = cell.add_paragraph()
        hy_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        hy_para.paragraph_format.space_before = Pt(0)
        hy_para.paragraph_format.space_after = Pt(8)
        if bg_color:
            apply_shading(hy_para, bg_color)
        run_hy = hy_para.add_run(hero_year_text)
        # 渐变无法还原：用金色系 #b79a4a（CSS 起始色）
        hy_color = "#b79a4a" if dark_bg else accent_color
        set_run_font(run_hy, size=Pt(hero_year_size if hero_year_size else 48), bold=True,
                     color=hex_to_rgb(hy_color))

    # 装饰横线（accent 色）
    line_para = cell.add_paragraph()
    line_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    line_para.paragraph_format.space_before = Pt(0)
    line_para.paragraph_format.space_after = Pt(8)
    if bg_color:
        apply_shading(line_para, bg_color)
    run_line = line_para.add_run("─" * 8)
    set_run_font(run_line, size=Pt(12), color=hex_to_rgb(accent_color))

    # 副标题（居中）— 用 _add_rich_text_runs 写入以保留 <br> 换行
    for p in ps:
        text = get_text_content(p)
        if not text:
            continue
        para2 = cell.add_paragraph()
        para2.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para2.paragraph_format.space_before = Pt(2)
        para2.paragraph_format.space_after = Pt(2)
        if bg_color:
            apply_shading(para2, bg_color)
        _add_rich_text_runs(para2, p, default_size=Pt(14), default_color=sub_color)

    # title-meta 数据指标行（嵌套在封面单元格内的多列表格）
    if meta_items:
        # 分隔线（封面单元格内）
        sep_para = cell.add_paragraph()
        sep_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        sep_para.paragraph_format.space_before = Pt(8)
        sep_para.paragraph_format.space_after = Pt(4)
        if bg_color:
            apply_shading(sep_para, bg_color)
        sep_run = sep_para.add_run("─" * 40)
        set_run_font(sep_run, size=Pt(8), color=hex_to_rgb(accent_color))

        # 嵌套在封面单元格内的多列表格（cell.add_table 避免 doc.add_table 导致 title-meta 溢出到下一页）
        meta_table = cell.add_table(rows=1, cols=len(meta_items))
        meta_table.alignment = WD_TABLE_ALIGNMENT.CENTER
        set_table_borders_nil(meta_table)
        set_table_width_percent(meta_table, 100)
        for j, (val, label) in enumerate(meta_items):
            m_cell = meta_table.cell(0, j)
            m_cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            # 单元格级底色（apply_shading_to_cell 避免段落级 shading 干扰嵌套表格内容）
            if bg_color:
                apply_shading_to_cell(m_cell, bg_color)
            # 数值（大字号加粗）
            p_val = m_cell.paragraphs[0]
            p_val.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p_val.paragraph_format.space_before = Pt(2)
            p_val.paragraph_format.space_after = Pt(2)
            run_val = p_val.add_run(val)
            set_run_font(run_val, size=Pt(15), bold=True,
                         color=hex_to_rgb("#ffffff" if dark_bg else title_color))
            # 标签（小字号浅色）
            p_label = m_cell.add_paragraph()
            p_label.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p_label.paragraph_format.space_before = Pt(0)
            p_label.paragraph_format.space_after = Pt(2)
            run_label = p_label.add_run(label)
            set_run_font(run_label, size=Pt(9), color=hex_to_rgb(sub_color))

    # 封面内嵌图片插入单元格内（副标题之后、分页之前）
    if img_bytes:
        try:
            img_para = cell.add_paragraph()
            img_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            img_para.paragraph_format.space_before = Pt(8)
            img_para.paragraph_format.space_after = Pt(4)
            if bg_color:
                apply_shading(img_para, bg_color)
            run = img_para.add_run()
            run.add_picture(io.BytesIO(img_bytes), width=Inches(3.5))
        except Exception as e:
            print(f"[WARN] 封面图片处理失败: {e}")

    # 兜底：输出封面内未被前面逻辑处理的含文本子元素（div/span 等）
    # 避免封面内非标准标签承载的内容丢失（如 .meta/.subtitle 等 div 元素）
    # 已处理的标签：h1（标题）、p（副标题）、.eyebrow、.title-meta、.accent-line、img
    handled_tags = {"h1"}
    for child in section.children:
        if not isinstance(child, Tag):
            continue
        child_classes = child.get("class", [])
        # 跳过已处理的类型
        if child.name in handled_tags:
            continue
        if child.name == "p":
            continue  # 已在副标题循环中输出
        if "eyebrow" in child_classes or "title-meta" in child_classes:
            continue
        if "hero-year" in child_classes:
            continue  # 大号年份已在标题后输出
        if "badge-row" in child_classes:
            continue  # 徽章已在封面标题上方输出
        if "accent-line" in child_classes:
            continue
        if child.name == "img":
            continue
        # 跳过含 h1 的 div（如 div.hero-body）：它是标题容器，
        # 内部的 h1 和 p 已由前面逻辑处理，整体输出会导致内容重复。
        if child.name == "div" and child.find("h1"):
            continue
        # 跳过已作为 eyebrow 输出的裸 div（如"ANNUAL REVIEW"、"2026 全新一代"）
        if _extra_eyebrow_items and child.name == "div":
            if any(get_text_content(child) == t for t, _el in _extra_eyebrow_items):
                continue
        # 提取文本内容（递归获取所有子文本）
        text = get_text_content(child)
        if not text:
            continue
        # 按副标题样式输出
        extra_para = cell.add_paragraph()
        # 读取内联 font-size，有则用，无则用副标题字号 13pt（提前读取，供 _add_rich_text_runs 使用）
        inline_fs = get_inline_style_prop(child.get("style", ""), "font-size")
        extra_size = Pt(inline_fs) if inline_fs else Pt(13)
        # 读取内联 color，有则用，无则用副标题颜色
        inline_color = get_inline_style_prop(child.get("style", ""), "color")
        extra_color = inline_color or sub_color
        # 读取 text-align：内联优先，再从 <style> 块按 class 查�找，最后降级 CENTER
        inline_align = get_inline_style_prop(child.get("style", ""), "text-align")
        if not inline_align and child_classes:
            # 构造候选 selector：.class1、.class1.class2、section.title .class1
            class_sel = ".".join(["." + c for c in child_classes])
            inner_sel = class_sel
            title_child_sel = ".title " + class_sel
            inline_align = extract_text_align_from_styles(
                parsed_styles, [inner_sel, title_child_sel], soup)
        # 检查 display: inline-block：封面 .title 设 text-align:center，
        # inline-block 子元素的 text-align 只控制其内部文字对齐，整体仍由
        # 父容器居中。Word 无 inline-block 概念，段落对齐直接决定视觉位置，
        # 因此 inline-block 元素应继承封面居中（CENTER），不用自身 text-align。
        is_inline_block = False
        raw_style = child.get("style", "") or ""
        if re.search(r'display\s*:\s*inline-block', raw_style, re.IGNORECASE):
            is_inline_block = True
        if not is_inline_block and child_classes:
            class_sel = ".".join(["." + c for c in child_classes])
            candidates = [class_sel, ".title " + class_sel]
            # 优先走 parsed_styles（cssutils 预解析）
            if parsed_styles:
                for sel in candidates:
                    props = parsed_styles.get(sel)
                    if props and props.get("display", "").strip().lower() == "inline-block":
                        is_inline_block = True
                        break
            # cssutils 不可用时正则兜底：从 <style> 块原始文本提取 display
            if not is_inline_block and soup is not None:
                for style_tag in soup.find_all("style"):
                    style_text = style_tag.string or ""
                    for sel in candidates:
                        pattern = re.escape(sel) + r'\s*\{[^}]*?display\s*:\s*inline-block'
                        if re.search(pattern, style_text, re.IGNORECASE | re.DOTALL):
                            is_inline_block = True
                            break
                    if is_inline_block:
                        break
        if is_inline_block:
            extra_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif inline_align == "left":
            extra_para.alignment = WD_ALIGN_PARAGRAPH.LEFT
        elif inline_align == "right":
            extra_para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        elif inline_align == "justify":
            extra_para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        else:
            extra_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        extra_para.paragraph_format.space_before = Pt(2)
        extra_para.paragraph_format.space_after = Pt(2)
        if bg_color:
            apply_shading(extra_para, bg_color)
        # 用 _add_rich_text_runs 写入子节点：保留 <br> 换行、<b>/<i>/<u> 及内联样式，
        # 避免 get_text_content 把 <br> 合并成一行（如 .doc-info 四行信息挤成一行）。
        # 文本为空但存在 <br> 等空标签时，get_text_content 返回空会提前 continue，
        # 此处 text 非空才进入，行为与原先一致。
        _add_rich_text_runs(extra_para, child, default_size=extra_size, default_color=extra_color)

    # 封面后不再主动添加分页符：
    # 封面使用 1×1 表格承载（行高 ≈ 一页），Word 自然在下一页继续。
    # 主动 add_page_break 会产生 pending 标记，被后续段落 inject 后导致空白页。



def process_heading(doc, section, palette, need_page_break=False):
    """章节标题 → Heading 1/2/3"""
    # 语义块自身可能是 h1/h2/h3（class="heading" 直接挂在标题标签上）
    is_heading_tag = section.name in ("h1", "h2", "h3")
    heading_tag = section if is_heading_tag else section.find(["h1", "h2", "h3"])
    level = int(section.get("data-level", 1))
    # 从标签推断层级（h1→1，h2→2，h3→3），无 data-level 时
    if not section.get("data-level"):
        tag_map = {"h1": 1, "h2": 2, "h3": 3}
        if heading_tag and heading_tag.name in tag_map:
            level = tag_map[heading_tag.name]
    text = get_text_content(heading_tag) if heading_tag else get_text_content(section)
    # 标题颜色：优先读取 HTML 内联 color（如深色底上的白字标题），回退调色板主色
    inline_color = get_inline_style_prop(heading_tag.get("style", "") if heading_tag else "", "color")
    title_color = inline_color or palette.get("primary", "1e293b")
    if level <= 3:
        h = doc.add_heading(text, level=level)
        for run in h.runs:
            set_run_font(
                run,
                size=Pt(18 if level == 1 else (16 if level == 2 else 14)),
                bold=True,
                color=hex_to_rgb(title_color),
            )
        if need_page_break or flush_pending_page_break(doc):
            inject_page_break_before(h)
    else:
        para = doc.add_paragraph()
        run = para.add_run(text)
        set_run_font(run, size=Pt(14), bold=True, color=hex_to_rgb(title_color))


def _add_rich_text_runs(para, element, default_size=None, default_color=None, default_bold=False):
    """将元素内的文本按子节点写入段落，保留 <b>/<strong> 加粗、<em>/<i> 斜体、
    <u> 下划线、<br> 换行与 <span style="color/font-size"> 内联样式。

    递归遍历：文本节点 → 普通 run；<b>/<strong> → 加粗 run；<em>/<i> → 斜体 run；
    <u> → 下划线 run；<br> → 段内换行；<span> 读取内联 color/font-size。
    其他标签（a/span 等）递归其子节点，尽量不丢失文本。
    default_size/default_color/default_bold：未命中任何内联样式时的兜底值。

    空白处理：只压缩连续空白为单空格（保留跨节点文本中的单个空格，
    避免中文语境下"和 落地"被合并为"和落地"）。
    """
    from bs4 import NavigableString
    from docx_utils import get_inline_style_prop, set_run_font, add_hyperlink, add_internal_hyperlink

    def append_text(text, bold=False, italic=False, underline=False, size=None, color=None):
        text = re.sub(r"\s+", " ", text)
        if not text:
            return
        run = para.add_run(text)
        final_color = color if color is not None else default_color
        set_run_font(
            run,
            size=size if size is not None else default_size,
            bold=bold if bold is not None else default_bold,
            color=None if final_color is None else hex_to_rgb(final_color),
        )
        if italic:
            run.italic = True
        if underline:
            run.underline = True
        return run

    def walk(node, bold=False, italic=False, underline=False, size=None, color=None):
        if isinstance(node, NavigableString):
            append_text(str(node), bold, italic, underline, size, color)
            return
        if not isinstance(node, Tag):
            return
        if node.name == "br":
            run = para.add_run()
            run.add_break()
            return
        node_bold = bold or node.name in ("b", "strong")
        node_italic = italic or node.name in ("em", "i")
        node_underline = underline or node.name == "u"
        node_size = size
        node_color = color
        # <a href> 超链接：提取链接文本并插入可点击超链接，不再递归子节点
        if node.name == "a" and node.get("href"):
            href = node.get("href", "").strip()
            # cite 引用标识（锚点跳转）：#source-N → 内部超链接 + 上标
            if href.startswith("#source-") or ("cite" in (node.get("class") or [])):
                link_text = get_text_content(node) or href
                link_text = re.sub(r"\s+", " ", link_text).strip()
                if link_text:
                    # 锚点名：#source-1 → source_1（横杠换下划线，符合 Word 书签命名规范）
                    anchor = href.lstrip("#").replace("-", "_")
                    add_internal_hyperlink(
                        para, anchor, link_text,
                        size=size if size is not None else default_size,
                        color=node_color if node_color is not None else None,
                        superscript=True,
                    )
                    return
            # 过滤锚点/纯 JS 链接（无外部跳转价值）
            if href and not href.startswith(("#", "javascript:", "mailto:")):
                link_text = get_text_content(node) or href
                link_text = re.sub(r"\s+", " ", link_text).strip()
                if link_text:
                    add_hyperlink(para, href, text=link_text,
                                  size=size if size is not None else default_size,
                                  color=node_color if node_color is not None else "0563c1")
                    return
        # span 内联样式：读取 color / font-size（就近覆盖）
        if node.name in ("span", "font", "a"):
            style_str = node.get("style", "")
            if style_str:
                c = get_inline_style_prop(style_str, "color")
                if c:
                    node_color = c
                fs = get_inline_style_prop(style_str, "font-size")
                if fs:
                    node_size = fs
                if get_inline_style_prop(style_str, "bold"):
                    node_bold = True
        for child in node.children:
            walk(child, node_bold, node_italic, node_underline, node_size, node_color)

    walk(element)


def process_paragraph(doc, section, palette=None):
    """正文段落 → Body 段落（保留加粗/斜体/下划线/局部字号颜色 + <br> 换行）

    段落默认字号/颜色优先读取 HTML 内联 style，回退调色板 text 色。
    支持传入 NavigableString（bare text 兜底为 paragraph 时的场景）。
    """
    from docx_utils import get_inline_style_prop
    from bs4 import NavigableString
    # NavigableString 兜底：直接作为纯文本段落输出
    if isinstance(section, NavigableString):
        text = re.sub(r"\s+", " ", str(section)).strip()
        if not text:
            flush_pending_page_break(doc)
            return
        para = doc.add_paragraph()
        default_color = (palette or {}).get("text") or "1f2d3d"
        run = para.add_run(text)
        set_run_font(run, color=hex_to_rgb(default_color))
        para.paragraph_format.space_before = Pt(2)
        para.paragraph_format.space_after = Pt(4)
        if flush_pending_page_break(doc):
            inject_page_break_before(para)
        return
    p = section.find("p")
    if p is None:
        p = section
    if not get_text_content(p):
        flush_pending_page_break(doc)
        return
    para = doc.add_paragraph()
    # 内联样式：font-size（px→pt 换算）与 color（hex）
    inline_size = get_inline_style_prop(p.get("style", ""), "font-size") or get_inline_style_prop(section.get("style", ""), "font-size")
    inline_color = get_inline_style_prop(p.get("style", ""), "color") or get_inline_style_prop(section.get("style", ""), "color")
    default_size = Pt(inline_size) if inline_size else None  # None → 继承 Normal 11pt
    default_color = inline_color or ((palette or {}).get("text") or "1f2d3d")
    _add_rich_text_runs(para, p, default_size=default_size, default_color=default_color)
    if flush_pending_page_break(doc):
        inject_page_break_before(para)
    para.paragraph_format.space_before = Pt(2)
    para.paragraph_format.space_after = Pt(4)


def process_bullet_list(doc, section):
    """列表 → Word 列表段落"""
    is_list_tag = section.name in ("ul", "ol")
    ul = section if is_list_tag else (section.find("ul") or section.find("ol"))
    if ul is None:
        ul = section
    if ul.name not in ("ul", "ol"):
        ul = None
    if not ul:
        # 直接遍历 li
        lis = section.find_all("li", recursive=False)
        is_ordered = False
    else:
        lis = ul.find_all("li", recursive=False)
        is_ordered = ul.name == "ol"
    if not lis:
        flush_pending_page_break(doc)
        return
    from docx_utils import add_bookmark
    first_li = True
    for li in lis:
        if not get_text_content(li):
            continue
        if is_ordered:
            para = doc.add_paragraph(style="List Number")
        else:
            para = doc.add_paragraph(style="List Bullet")
        # 为带 id 属性的 li 插入书签（支持 cite 引用标识跳转）
        li_id = li.get("id")
        if li_id:
            bookmark_name = li_id.replace("-", "_")
            add_bookmark(para, bookmark_name)
        # 富文本写入：保留 li 内 <b>/<em>/<span style> 等格式
        _add_rich_text_runs(para, li)
        if first_li:
            if flush_pending_page_break(doc):
                inject_page_break_before(para)
            first_li = False


def process_table(doc, section, palette=None, parsed_styles=None, soup=None):
    """数据表格 → Word Table（全宽 + 表标题行 + 统一淡边框 + 表头 shading）

    Args:
        parsed_styles: cssutils 预解析的 <style> 块样式字典（用于提取 th class 宽度）
        soup: 可选，BS4 文档对象（cssutils 不可用时正则兜底提取 class 宽度）
    """
    table_elem = section.find("table") if section.name != "table" else section
    if not table_elem:
        flush_pending_page_break(doc)
        return
    rows, merges, detail_map = parse_table_data(table_elem)
    if not rows:
        flush_pending_page_break(doc)
        return
    thead = table_elem.find("thead")
    has_header = thead is not None
    num_cols = max(len(r) for r in rows)
    num_data_rows = len(rows)
    # detail_map: [(after_row_idx, detail_text)] — 每个 detail 在对应数据行下方插入一行
    num_detail_rows = len(detail_map)
    total_rows = num_data_rows + num_detail_rows
    # 表标题（优先 .table-caption 父级容器 > data-caption 属性 > figcaption）
    # .table-caption 可能含更完整文本（如"表1："前缀），优先查找父级 .table-wrap 中的 .table-caption
    caption = ""
    # 先从父级 .table-wrap（或最近的含 .table-caption 的祖先）查找
    parent_wrap = section.find_parent(class_="table-wrap")
    if parent_wrap:
        cap_div = parent_wrap.find(class_="table-caption")
        if cap_div:
            caption = get_text_content(cap_div)
    if not caption:
        caption = section.get("data-caption", "")
    if not caption:
        figcaption = table_elem.find("figcaption")
        if figcaption:
            caption = get_text_content(figcaption)
    if not caption:
        cap_div = section.find(class_="table-caption")
        if cap_div:
            caption = get_text_content(cap_div)
    if caption:
        cap_para = doc.add_paragraph()
        cap_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        cap_para.paragraph_format.space_before = Pt(6)
        cap_para.paragraph_format.space_after = Pt(4)
        run_cap = cap_para.add_run(caption)
        run_cap.font.size = Pt(11)
        run_cap.bold = True
        run_cap.font.color.rgb = hex_to_rgb((palette or {}).get("primary", "1e293b"))

    table = doc.add_table(rows=total_rows, cols=num_cols)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    # 判断是否为"可横向滚动"的宽表（父容器有 overflow-x: auto/scroll）
    # 这类表格列多，均分列宽会导致每列过窄、文字密集换行
    # 宽表改用 autofit（按内容自动分配列宽）+ 减小 padding；普通表格保持全宽 100%
    # 检测方式：父容器内联 style 含 overflow-x:auto/scroll，或 class 名含滚动特征
    parent_elem = table_elem.parent
    is_scrollable = False
    if parent_elem and hasattr(parent_elem, 'get'):
        inline_style = parent_elem.get("style", "")
        import re as _re
        if _re.search(r'overflow[_-]x\s*:\s*(auto|scroll)', inline_style, _re.I) or \
           _re.search(r'overflow\s*:\s*(auto|scroll)', inline_style, _re.I):
            is_scrollable = True
    # 内联没找到，检查 class 名是否含滚动容器特征
    if not is_scrollable and parent_elem:
        parent_classes = parent_elem.get("class", []) or []
        scroll_keywords = ('gantt', 'scroll', 'overflow', 'horizontal-scroll')
        for cls in parent_classes:
            if any(kw in cls.lower() for kw in scroll_keywords):
                is_scrollable = True
                break

    if is_scrollable and num_cols > 5:
        # 宽表：autofit + 减小 padding（不缩字号）
        table.autofit = True
        # 设 tblLayout=autofit（让 Word 按内容自动分配列宽）
        from docx.oxml.ns import qn as _qn
        _tbl = table._tbl
        _tblPr = _tbl.tblPr
        if _tblPr is None:
            _tblPr = OxmlElement("w:tblPr")
            _tbl.insert(0, _tblPr)
        _existing = _tblPr.find(_qn("w:tblLayout"))
        if _existing is not None:
            _tblPr.remove(_existing)
        _layout = OxmlElement("w:tblLayout")
        _layout.set(_qn("w:type"), "autofit")
        _tblPr.append(_layout)
        # 删除 tblW（避免锁死表格总宽度）
        _existing_w = _tblPr.find(_qn("w:tblW"))
        if _existing_w is not None:
            _tblPr.remove(_existing_w)
        # 删除 tblGrid 中固定列宽值，让 Word 根据内容重新分配
        _grid = _tbl.find(_qn("w:tblGrid"))
        if _grid is not None:
            for _gc in _grid.findall(_qn("w:gridCol")):
                _gc.set(_qn("w:w"), "0")
        # 清除各单元格固定宽度（删除 tcW 元素）
        for _row in table.rows:
            for _cell in _row.cells:
                _tcPr = _cell._tc.get_or_add_tcPr()
                _tcW = _tcPr.find(_qn("w:tcW"))
                if _tcW is not None:
                    _tcPr.remove(_tcW)
    else:
        set_table_width_percent(table, 100)
        # 普通表格：三级提取各列宽度（colgroup > th 内联 > th class 样式），
        # 避免 Word 默认均分列宽（序号列和主要内容列一样宽）
        from docx.oxml.ns import qn as _qn
        import re as _re2
        # 1) <colgroup> 内 <col> 的 width（百分比或 px）
        colgroup_widths = []
        colgroup = table_elem.find("colgroup")
        if colgroup is not None:
            for col in colgroup.find_all("col"):
                col_style = col.get("style", "")
                m_pct = _re2.search(r'width\s*:\s*(\d+(?:\.\d+)?)\s*%', col_style, _re2.I)
                m_px = _re2.search(r'width\s*:\s*(\d+(?:\.\d+)?)\s*px', col_style, _re2.I)
                if m_pct:
                    colgroup_widths.append(("pct", float(m_pct.group(1))))
                elif m_px:
                    colgroup_widths.append(("px", float(m_px.group(1))))
                else:
                    colgroup_widths.append(None)
        # 2) th 内联 width（X% 或 Npx）
        th_tags = table_elem.find_all("th")
        if not th_tags:
            first_tr = table_elem.find("tr")
            if first_tr:
                th_tags = first_tr.find_all("th")
        # 3) th 的 class 在 <style> 块中的宽度（如 .swot-axis { width:60px }）
        th_inline_widths = []
        for th in th_tags:
            style_str = th.get("style", "")
            m_pct = _re2.search(r'width\s*:\s*(\d+(?:\.\d+)?)\s*%', style_str, _re2.I)
            m_px = _re2.search(r'width\s*:\s*(\d+(?:\.\d+)?)\s*px', style_str, _re2.I)
            if m_pct:
                th_inline_widths.append(("pct", float(m_pct.group(1))))
            elif m_px:
                th_inline_widths.append(("px", float(m_px.group(1))))
            else:
                # class 样式兜底：.cls { width: X% | Xpx }
                th_cls = th.get("class") or []
                cls_width = None
                for cls in th_cls:
                    cls_style = None
                    if parsed_styles:
                        for selector, props in parsed_styles.items():
                            if selector.strip() == "." + cls and "width" in props:
                                cls_style = props["width"]
                                break
                    if cls_style is None and soup is not None:
                        for style_tag in soup.find_all("style"):
                            style_text = style_tag.string or ""
                            m_cls = _re2.search(
                                r'\.' + _re2.escape(cls) + r'\s*\{[^}]*?width\s*:\s*([0-9.]+)\s*(%|px)',
                                style_text, _re2.I | _re2.DOTALL)
                            if m_cls:
                                cls_style = m_cls.group(1) + m_cls.group(2)
                                break
                    if cls_style:
                        m_cls_pct = _re2.match(r'([0-9.]+)\s*%', cls_style.strip())
                        m_cls_px = _re2.match(r'([0-9.]+)\s*px', cls_style.strip())
                        if m_cls_pct:
                            cls_width = ("pct", float(m_cls_pct.group(1)))
                        elif m_cls_px:
                            cls_width = ("px", float(m_cls_px.group(1)))
                        break
                th_inline_widths.append(cls_width)
        # 4) 合并：colgroup 优先，缺列用 th 值补充
        col_widths = []
        for i in range(num_cols):
            cg = colgroup_widths[i] if i < len(colgroup_widths) else None
            th_w = th_inline_widths[i] if i < len(th_inline_widths) else None
            col_widths.append(cg if cg is not None else th_w)
        # 5) px 归一化为百分比（相对页面可用宽度 17.4cm≈986px）
        #    同时统计已知百分比总和与未知列数
        container_width_px = 986.0  # A4 纵向 21cm − 左右边距 1.8cm×2 = 17.4cm
        known_sum = 0.0
        unknown_count = 0
        for w in col_widths:
            if w is None:
                unknown_count += 1
            elif w[0] == "px":
                known_sum += w[1] / container_width_px * 100
            else:
                known_sum += w[1]
        # 未知列均分剩余宽度
        if unknown_count > 0:
            avg = (100 - known_sum) / unknown_count if unknown_count else 0
            col_widths = [w if w is not None else ("pct", avg) for w in col_widths]
        # 全部列均为 None（无任何宽度信息）→ 放弃应用，走均分
        col_widths_pct = []
        for w in col_widths:
            if w[0] == "px":
                col_widths_pct.append(w[1] / container_width_px * 100)
            else:
                col_widths_pct.append(w[1])
        # 只在全部列都有有效宽度（>0）时应用，避免全部 None 导致除零
        if col_widths_pct and num_cols == len(col_widths_pct) and all(w > 0 for w in col_widths_pct):
            # A4 纵向可用宽度从 docx section 实际读取（twips）
            try:
                sec = doc.sections[0]
                page_w_twips = int(sec.page_width.twips) - int(sec.left_margin.twips) - int(sec.right_margin.twips)
            except Exception:
                page_width_twips = 10524
            else:
                page_width_twips = page_w_twips
            # 按百分比重算（确保总和=100%）
            total = sum(col_widths_pct)
            if total > 0:
                _tbl = table._tbl
                _grid = _tbl.find(_qn("w:tblGrid"))
                if _grid is not None:
                    grid_cols = _grid.findall(_qn("w:gridCol"))
                    for j, gc in enumerate(grid_cols):
                        if j < len(col_widths_pct):
                            w_twips = int(col_widths_pct[j] / total * page_width_twips)
                            gc.set(_qn("w:w"), str(w_twips))
                    # 同步设置第一行单元格宽度
                    for j, cell in enumerate(table.rows[0].cells):
                        if j < len(col_widths_pct):
                            w_twips = int(col_widths_pct[j] / total * page_width_twips)
                            _tcPr = cell._tc.get_or_add_tcPr()
                            _tcW = _tcPr.find(_qn("w:tcW"))
                            if _tcW is None:
                                _tcW = OxmlElement("w:tcW")
                                _tcPr.append(_tcW)
                            _tcW.set(_qn("w:type"), "dxa")
                            _tcW.set(_qn("w:w"), str(w_twips))
    border_color = (palette or {}).get("border", "dbe4ef")
    set_table_borders(table, color=border_color)
    # 表格承载待分页标记
    if flush_pending_page_break(doc):
        first_cell = table.cell(0, 0)
        if first_cell.paragraphs:
            inject_page_break_before(first_cell.paragraphs[0])
    # 获取 HTML 行元素（用于富文本写入，保留 <b>/<strong> 加粗等格式）
    # 跳过 .row-detail 行：parse_table_data 已将 row-detail 从 rows 中排除，
    # 此处必须同步过滤，否则 html_cells 与 rows 行数不一致，按下标写入时错位
    tr_tags = [tr for tr in table_elem.find_all("tr")
               if "row-detail" not in (tr.get("class") or [])]
    html_cells = []
    for tr in tr_tags:
        cells_in_row = tr.find_all(["td", "th"], recursive=False)
        html_cells.append(cells_in_row)

    # 构建 逻辑行→物理行 映射：每个 detail 占一行，插入到对应数据行后面
    # after_row 表示 detail 应紧跟在 rows[after_row] 之后
    # 例：detail_map = [(0, 'detail_0'), (1, 'detail_1')]
    #   row 0 → physical 0, detail_0 → physical 1, row 1 → physical 2, detail_1 → physical 3, ...
    logical_to_physical = {}
    phys = 0
    detail_after_rows = {}  # after_row_idx -> list of physical row indices for details
    detail_idx = 0
    for i in range(num_data_rows):
        logical_to_physical[i] = phys
        phys += 1
        # 插入属于当前行后的 detail 行
        while detail_idx < len(detail_map) and detail_map[detail_idx][0] == i:
            detail_after_rows.setdefault(i, []).append(phys)
            phys += 1
            detail_idx += 1
    # 处理 after_row == -1（表头前）的 detail
    pre_details = []
    for di in range(len(detail_map)):
        if detail_map[di][0] == -1:
            pre_details.append(di)

    for i, row_data in enumerate(rows):
        phys_row = logical_to_physical[i]
        for j, cell_text in enumerate(row_data):
            if j < num_cols:
                cell = table.cell(phys_row, j)
                # 富文本写入：优先遍历 HTML td/th 子节点，保留 <b> 加粗与 <br> 换行；
                # 取不到 HTML 元素时回退纯文本
                td_el = None
                if i < len(html_cells) and j < len(html_cells[i]):
                    td_el = html_cells[i][j]
                if td_el is not None:
                    para = cell.paragraphs[0]
                    # 读取 td/th 内联样式：font-size / color 优先，回退默认
                    td_inline_size = get_inline_style_prop(td_el.get("style", ""), "font-size")
                    td_inline_color = get_inline_style_prop(td_el.get("style", ""), "color")
                    if has_header and phys_row == 0:
                        d_size = Pt(td_inline_size) if td_inline_size else Pt(10.5)
                        d_color = td_inline_color or ((palette or {}).get("primary") or "1e293b")
                    else:
                        d_size = Pt(td_inline_size) if td_inline_size else Pt(11)
                        d_color = td_inline_color or ((palette or {}).get("text") or "1f2d3d")
                    _add_rich_text_runs(para, td_el, default_size=d_size, default_color=d_color)
                    if has_header and phys_row == 0:
                        # 表头行：HTML 未加粗时也保持加粗（表头语义）
                        for run in para.runs:
                            run.bold = True
                else:
                    cell.text = cell_text
                    if has_header and phys_row == 0:
                        for paragraph in cell.paragraphs:
                            for run in paragraph.runs:
                                run.bold = True
                                run.font.size = Pt(10.5)
                                set_run_font(run)
                    else:
                        for paragraph in cell.paragraphs:
                            for run in paragraph.runs:
                                run.font.size = Pt(11)
                                set_run_font(run)
                # 宽表减小 padding 挤出更多空间（不缩字号）
                if is_scrollable and num_cols > 5:
                    set_cell_margins(cell, top=20, start=30, bottom=20, end=30)
                else:
                    set_cell_margins(cell, top=30, start=60, bottom=30, end=60)

    # 填充 row-detail 行：合并所有列，写入详情文本，浅灰背景
    # detail_map: [(after_row, detail_text), ...] — after_row 是逻辑行索引
    # detail_after_rows: {after_row: [phys_row1, phys_row2, ...]}
    # 需要按顺序将 detail_map 中的文本分配到 detail_after_rows 的物理行
    for after_row, phys_rows in sorted(detail_after_rows.items()):
        # 找到所有属于此 after_row 的 detail 文本
        texts = [t for ar, t in detail_map if ar == after_row]
        for idx, pr in enumerate(phys_rows):
            if idx >= len(texts):
                break
            detail_text = texts[idx]
            # 合并整行所有列
            try:
                merged_cell = table.cell(pr, 0)
                for j in range(1, num_cols):
                    merged_cell = merged_cell.merge(table.cell(pr, j))
            except Exception:
                merged_cell = table.cell(pr, 0)
            # 合并后清除可能残留的默认空段落文本，写入详情
            para = merged_cell.paragraphs[0]
            # 清除默认空 run（python-docx 创建时可能有空段落）
            para.paragraph_format.space_before = Pt(2)
            para.paragraph_format.space_after = Pt(2)
            para.paragraph_format.left_indent = Cm(0.3)
            run = para.add_run(detail_text)
            set_run_font(run, size=Pt(9), color=hex_to_rgb("64748b"))
            # 浅灰背景
            apply_shading_to_cell(merged_cell, "f8fafc")
            set_cell_margins(merged_cell, top=20, start=60, bottom=20, end=60)

    # 表头行 shading（primary_light / th 内联色）
    if has_header and rows:
        th = table_elem.find("thead").find("th")
        th_style = th.get("style", "") if th else ""
        th_bg = extract_bg_with_gradient_fallback(th_style)
        if th_bg:
            for j in range(num_cols):
                apply_shading_to_cell(table.cell(0, j), th_bg)

    # 重建合并单元格（colspan/rowspan）—— 使用物理行索引
    # merges 中的 r 是逻辑行索引，需转换为物理行索引
    for m in sorted(merges, key=lambda x: (-x["r"], -x["c"])):
        r_logical, c, rs, cs = m["r"], m["c"], m["rs"], m["cs"]
        # 转换起始行为物理行
        r = logical_to_physical.get(r_logical, r_logical)
        # rowspan 跨度：逻辑行 r_logical..r_logical+rs-1 对应的物理行可能不连续
        # 简化处理：取逻辑范围内最后行的物理行 + 1 作为结束
        r_end_logical = min(r_logical + rs - 1, num_data_rows - 1)
        r_end = logical_to_physical.get(r_end_logical, r_end_logical)
        if r >= total_rows or c >= num_cols:
            continue
        c_end = min(c + cs - 1, num_cols - 1)
        if r_end == r and c_end == c:
            continue
        try:
            merged = table.cell(r, c).merge(table.cell(r_end, c_end))
            if merged is not None:
                pass
        except Exception:
            pass


def _add_picture_to_cell(cell, doc, img_stream, width=Inches(2.5)):
    """在单元格段落中插入图片（python-docx 正确方式）"""
    from copy import deepcopy
    img_stream.seek(0)
    inline_shape = doc.add_picture(img_stream, width=width)
    last_para = doc.paragraphs[-1]
    shape_elem = deepcopy(inline_shape._inline)
    last_para._element.getparent().remove(last_para._element)
    run = cell.paragraphs[0].add_run()
    run._element.append(shape_elem)


def _extract_img_bytes(img):
    """从 img 标签提取 base64 图片字节；失败返回 None"""
    src = img.get("src", "")
    if not src.startswith("data:image/"):
        return None
    match = re.match(r"data:image/(\w+);base64,(.+)", src)
    if not match:
        return None
    try:
        return base64.b64decode(match.group(2))
    except Exception:
        return None


def process_image(doc, section):
    """图片 → InlineShape（data-float → 表格定位；宽度按 HTML 映射）"""
    img = section.find("img") if section.name != "img" else section
    if not img:
        flush_pending_page_break(doc)
        return
    float_attr = section.get("data-float", "center")
    img_bytes = _extract_img_bytes(img)
    # 从 HTML 提取宽度：百分比 → 按页面可用宽换算；像素 → 直接换算英寸
    page_content_width = 21.0 - 1.8 - 1.8  # A4 21cm - 左右边距(1.8cm*2，与 html2docx.py 一致)
    width_px = extract_img_width_px(img)
    if width_px is None:
        width_in = 5.0  # 默认 center 宽度
        if float_attr == "full":
            width_in = 6.5
        elif float_attr in ("left", "right", "wrap"):
            width_in = 2.5
    elif width_px <= 1.0:
        # 百分比（0.5 = 50%）
        width_in = page_content_width * width_px / 2.54
    else:
        # 像素值：按 96dpi 换算英寸
        width_in = width_px / 96.0
        width_in = max(1.0, min(width_in, 6.5))
    if img_bytes:
        try:
            img_stream = io.BytesIO(img_bytes)
            if float_attr in ("left", "right", "wrap"):
                # 使用双列表格定位实现浮动
                tbl = doc.add_table(rows=1, cols=2)
                set_table_borders_nil(tbl)
                if flush_pending_page_break(doc):
                    first_cell = tbl.cell(0, 0)
                    if first_cell.paragraphs:
                        inject_page_break_before(first_cell.paragraphs[0])
                if float_attr == "left":
                    cell_img = tbl.cell(0, 0)
                    cell_text = tbl.cell(0, 1)
                else:
                    cell_img = tbl.cell(0, 1)
                    cell_text = tbl.cell(0, 0)
                _add_picture_to_cell(cell_img, doc, io.BytesIO(img_bytes), width=Inches(width_in))
                cell_text.paragraphs[0].text = ""
            elif float_attr == "full":
                if flush_pending_page_break(doc):
                    pb_para = doc.add_paragraph()
                    inject_page_break_before(pb_para)
                    pb_para.paragraph_format.space_before = Pt(0)
                    pb_para.paragraph_format.space_after = Pt(0)
                    pb_para.paragraph_format.line_spacing = Pt(1)
                doc.add_picture(io.BytesIO(img_bytes), width=Inches(width_in))
                # 图片所在段落居中
                doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
            else:
                # center（默认）
                if flush_pending_page_break(doc):
                    pb_para = doc.add_paragraph()
                    inject_page_break_before(pb_para)
                    pb_para.paragraph_format.space_before = Pt(0)
                    pb_para.paragraph_format.space_after = Pt(0)
                    pb_para.paragraph_format.line_spacing = Pt(1)
                doc.add_picture(io.BytesIO(img_bytes), width=Inches(width_in))
                # 图片所在段落居中
                doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
        except Exception as e:
            print(f"[WARN] 图片处理失败: {e}")
    # 图注
    caption = section.get("data-caption", "")
    if not caption:
        figcaption = section.find("figcaption")
        if figcaption:
            caption = get_text_content(figcaption)
    if caption:
        para = doc.add_paragraph(caption)
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para.paragraph_format.space_before = Pt(2)
        for run in para.runs:
            run.font.size = Pt(10)
            run.font.color.rgb = hex_to_rgb("64748b")
