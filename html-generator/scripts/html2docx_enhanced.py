#!/usr/bin/env python3
"""
html2docx_enhanced.py — 增强层处理（4 种 IR）

IR 类型：stat_block / callout / timeline / code_block

被 html2docx.py 主入口 import。
依赖 docx_utils（OXML 工具），不依赖其他处理层。
"""

import re
import copy

from bs4 import Tag, NavigableString, Comment

from sem_common import (
    get_text_content, find_semantic_class, semantic_children,
    parse_table_data,
)
from docx_utils import (
    CALLOUT_COLORS,
    CODE_FONT,
    hex_to_rgb,
    extract_bg_with_gradient_fallback,
    extract_color_from_styles, extract_font_size_from_styles,
    set_run_font, add_cell_paragraph, flush_pending_page_break, inject_page_break_before,
    set_cell_margins, set_table_borders_nil, set_cell_borders, set_table_width_percent,
    apply_shading, apply_shading_to_cell, get_inline_style_prop,
)
from docx.shared import Pt, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from html2docx_core import _add_rich_text_runs


def _collect_stat_cards(element, group_info):
    """从聚合组或单元素中提取指标卡片列表

    每个条目: {value, labels, bg}
      value: 第一个有文本的 div（大数字）
      labels: 其余所有有文本的 div 文本列表（标签+子指标等，逐行输出避免丢失）
    """
    def _extract_one(stat_el):
        divs = stat_el.find_all("div")
        texts = [d.get_text(strip=True) for d in divs if d.get_text(strip=True)]
        if not texts:
            return {"value": stat_el.get_text(strip=True), "labels": [],
                    "bg": extract_bg_with_gradient_fallback(stat_el.get("style", ""))}
        value = texts[0]
        labels = texts[1:]  # 其余全部作为标签行输出
        bg = extract_bg_with_gradient_fallback(stat_el.get("style", ""))
        return {"value": value, "labels": labels, "bg": bg}

    cards = []
    if group_info and group_info[0] == "stat":
        for stat_el in group_info[1]:
            cards.append(_extract_one(stat_el))
        return cards
    # 单元素：直接找 stat 子元素或自身 div
    if find_semantic_class(element) == "stat":
        return [_extract_one(element)]
    # 容器内多个 stat
    for el in semantic_children(element, "stat"):
        cards.append(_extract_one(el))
    return cards


def process_stat_block(doc, section, palette, group_info=None):
    """数字指标卡片 → 无边框表格（数值 18pt + 标签 9pt）+ 卡片 shading + 淡边框 + 顶部 accent 线"""
    cards = _collect_stat_cards(section, group_info)
    if not cards:
        flush_pending_page_break(doc)
        return
    num_cols = len(cards)
    table = doc.add_table(rows=1, cols=num_cols)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_table_borders_nil(table)
    set_table_width_percent(table, 100)
    if flush_pending_page_break(doc):
        first_cell = table.cell(0, 0)
        if first_cell.paragraphs:
            inject_page_break_before(first_cell.paragraphs[0])
    accent_color = palette.get("accent", "6366f1")
    border_color = palette.get("border", "e2e8f0")
    for j, card in enumerate(cards):
        cell = table.cell(0, j)
        if card["bg"]:
            apply_shading_to_cell(cell, card["bg"])
        # 卡片边框：淡色细边框 + 顶部 accent 粗线
        set_cell_borders(cell, top_color=accent_color, color=border_color)
        p_val = cell.paragraphs[0]
        p_val.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run_val = p_val.add_run(card["value"])
        set_run_font(run_val, size=Pt(18), bold=True, color=hex_to_rgb(accent_color))
        # 所有标签行逐行输出（label + sub 等），避免中间内容丢失
        for label_text in card.get("labels", []):
            p_label = add_cell_paragraph(cell)
            p_label.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run_label = p_label.add_run(label_text)
            set_run_font(run_label, size=Pt(9), color=hex_to_rgb("64748b"))
        set_cell_margins(cell, top=40, start=40, bottom=40, end=40)


def _apply_callout_style(para, variant, style_str=""):
    """callout 段落：底色 + 左边框
    优先读取 HTML 内联色值（所见即所得），无内联时回退 CALLOUT_COLORS 兜底"""
    colors = CALLOUT_COLORS.get(variant, CALLOUT_COLORS["tip"])
    bg = None
    border = None
    if style_str:
        bg = extract_bg_with_gradient_fallback(style_str)
        m = re.search(r'border(?:-left)?:\s*(?:4px|3px|2px)?\s*solid\s*(#[0-9a-fA-F]{3,8})', style_str)
        if not m:
            m = re.search(r'border-left-color:\s*(#[0-9a-fA-F]{3,8})', style_str)
        if m:
            border = m.group(1).lstrip("#")
    bg = bg or colors["bg"]
    border = border or colors["border"]
    shading = OxmlElement("w:shd")
    shading.set(qn("w:fill"), bg)
    shading.set(qn("w:val"), "clear")
    para.paragraph_format.element.get_or_add_pPr().append(shading)
    pPr = para.paragraph_format.element.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    left_bdr = OxmlElement("w:left")
    left_bdr.set(qn("w:val"), "single")
    left_bdr.set(qn("w:sz"), "12")
    left_bdr.set(qn("w:space"), "4")
    left_bdr.set(qn("w:color"), border)
    pBdr.append(left_bdr)
    pPr.append(pBdr)
    para.paragraph_format.left_indent = Cm(0.3)
    para.paragraph_format.space_before = Pt(4)
    para.paragraph_format.space_after = Pt(4)


def process_callout(doc, section, palette):
    """提示/警告/引用 → 底色 + 左边框段落（多段落完整输出，保留 <strong>/<span> 等富文本）

    标题处理：<span class="callout-title"> 输出为加粗标题段落（使用变体强调色）。
    正文处理：优先遍历所有块级子元素（p/div/pre/ul/ol 等），避免只取 <p>
    导致 callout 内的代码/列表被吞。
    兼容旧结构：无 .callout-title 的 callout 行为不变；无 p 标签时整体文本兜底。
    """
    variant = section.get("data-variant", "tip")
    prefix = {}  # 不自动加前缀，靠底色 + 左边框区分类型

    # 先输出标题（若存在），作为独立加粗段落
    title_el = section.find(class_="callout-title")
    title_para = None
    if title_el is not None:
        text = get_text_content(title_el)
        if text:
            title_para = doc.add_paragraph()
            if flush_pending_page_break(doc):
                inject_page_break_before(title_para)
            colors = CALLOUT_COLORS.get(variant, CALLOUT_COLORS["tip"])
            run = title_para.add_run(text)
            set_run_font(run, size=Pt(11), bold=True, color=hex_to_rgb(colors["border"]))
            title_para.paragraph_format.space_after = Pt(2)

    # 正文段落列表排除标题段落（标题可能在 p 标签内，已在上方单独输出，避免重复）
    # 用 class 判断而非文本内容判断：正文可能恰好出现与标题相同的字句，
    # 按文本去重会误删正文；按 class 去重只命中标题本身。
    ps = [p for p in section.find_all("p")
          if "callout-title" not in (p.get("class") or [])]
    if not ps:
        # 无 p 标签时取全文本（可能为裸文本或 pre/ul 等）
        text = get_text_content(section)
        if not text:
            flush_pending_page_break(doc)
            return
        # 遍历块级子元素输出；无块级子元素时整体兜底
        _emit_callout_children(doc, section, variant, palette,
                               first_para=title_para is None)
        return

    first_para = title_para is None
    for idx, p in enumerate(ps):
        if not get_text_content(p):
            continue
        para = doc.add_paragraph()
        if first_para:
            if flush_pending_page_break(doc):
                inject_page_break_before(para)
            first_para = False
        # 首段加前缀（单独 run，再加富文本 run 保留 <strong>/<span style> 等格式）
        if idx == 0:
            prefix_text = prefix.get(variant, "")
            if prefix_text:
                run_prefix = para.add_run(prefix_text)
                set_run_font(run_prefix, size=Pt(11))
        _add_rich_text_runs(para, p, default_size=Pt(11))
        _apply_callout_style(para, variant, section.get("style", ""))


def _emit_callout_children(doc, container, variant, palette, first_para=True):
    """callout 无 <p> 子元素时，遍历所有块级子元素输出（pre→code、ul/ol→列表、
    table→表格、其余按可见文本兜底），避免代码/列表被吞。"""
    from html2docx_enhanced import process_code_block as _pcode
    from html2docx_core import process_bullet_list as _pblist
    from html2docx_core import process_table as _ptable
    for child in container.children:
        if not isinstance(child, Tag):
            continue
        if isinstance(child, Comment):
            continue
        if child.name in ("style", "script"):
            continue
        if child.name == "span" and "callout-title" in (child.get("class") or []):
            continue  # 标题已单独输出，避免重复
        # 跳过交互辅助元素（复制按钮/搜索框/返回顶部等），避免误输出按钮文本
        if any(c in ("code-copy-btn", "table-search-input", "table-no-result",
                     "back-to-top", "dark-toggle-btn")
               for c in (child.get("class") or [])):
            continue
        if child.name == "pre":
            if first_para and flush_pending_page_break(doc):
                inject_page_break_before(doc.add_paragraph())
                first_para = False
            _pcode(doc, child)
            continue
        if child.name in ("ul", "ol"):
            if first_para and flush_pending_page_break(doc):
                inject_page_break_before(doc.add_paragraph())
                first_para = False
            _pblist(doc, child)
            continue
        if child.name == "table":
            if first_para and flush_pending_page_break(doc):
                inject_page_break_before(doc.add_paragraph())
                first_para = False
            _ptable(doc, child, palette, None, None)
            continue
        # 其余元素：按可见文本兜底输出（宁丑勿丢）
        text = get_text_content(child)
        if text:
            para = doc.add_paragraph()
            if first_para and flush_pending_page_break(doc):
                inject_page_break_before(para)
                first_para = False
            _add_rich_text_runs(para, child, default_size=Pt(11))
            _apply_callout_style(para, variant, container.get("style", ""))


def _write_timeline_table(doc, items, palette, parsed_styles=None, soup=None):
    """将 [(时间, 描述, li元素), ...] 渲染为两列表格（时间列 accent 加粗 + 描述列富文本）"""
    if not items:
        flush_pending_page_break(doc)
        return
    table = doc.add_table(rows=len(items), cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_table_borders_nil(table)
    set_table_width_percent(table, 100)
    if flush_pending_page_break(doc):
        first_cell = table.cell(0, 0)
        if first_cell.paragraphs:
            inject_page_break_before(first_cell.paragraphs[0])
    accent_color = palette.get("accent", "6366f1")
    border_color = palette.get("border", "e2e8f0")
    for i, item in enumerate(items):
        t = item[0]
        e = item[1]
        li_el = item[2] if len(item) > 2 else None
        c_time = table.cell(i, 0)
        c_desc = table.cell(i, 1)
        # 时间列：accent 加粗 + 浅色底
        apply_shading_to_cell(c_time, "f8fafc")
        set_cell_borders(c_time, color=border_color)
        set_cell_borders(c_desc, color=border_color)
        p_t = c_time.paragraphs[0]
        p_t.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run_t = p_t.add_run(t)
        set_run_font(run_t, size=Pt(11), bold=True, color=hex_to_rgb(accent_color))
        # 描述列：逐块级子元素写入，各独立成段落 + 读取内联 font-size/color
        if li_el is not None:
            _write_timeline_desc_cell(c_desc, li_el, palette, parsed_styles, soup)
        else:
            p_d = c_desc.paragraphs[0]
            run_d = p_d.add_run(e)
            set_run_font(run_d, size=Pt(11), color=hex_to_rgb("334155"))
        set_cell_margins(c_time, top=30, start=40, bottom=30, end=40)
        set_cell_margins(c_desc, top=30, start=60, bottom=30, end=60)
    # 列宽：时间列窄、描述列宽
    for row in table.rows:
        row.cells[0].width = Cm(3.5)
        row.cells[1].width = Cm(13.5)


def _write_timeline_desc_cell(cell, li_el, palette, parsed_styles=None, soup=None):
    """将 timeline <li> 的描述内容写入单元格，逐块级子元素各起新段落。

    遍历 li 的直接子节点：
    - <p> / <div> 等块级元素 → add_cell_paragraph 新建段落 + _add_rich_text_runs 富文本
      读取优先级：元素内联 style > <style> 块 CSS 选择器 > 调色板默认值
    - <strong> 已被上游 extract 移除，不会出现
    - 纯文本节点 → 合并写入当前段落
    """
    text_color = palette.get("text", "1f2d3d")

    def _build_selectors(child):
        """为子元素构建候选 CSS 选择器列表（从具体到泛化）"""
        sels = []
        classes = child.get("class", [])
        tag = child.name
        if classes:
            for cls in classes:
                sels.append(f".timeline {tag}.{cls}")
                sels.append(f".{cls}")
            sels.append(f".timeline {' '.join('.' + c for c in classes)}")
        sels.append(f".timeline {tag}")
        sels.append(tag)
        return sels

    def _resolve_font_size(child, default_pt):
        """读取 font-size：内联 style → <style> 块 → 默认值"""
        style_str = child.get("style", "")
        inline_size = get_inline_style_prop(style_str, "font-size")
        if inline_size:
            return Pt(inline_size)
        if parsed_styles or soup:
            sels = _build_selectors(child)
            fs = extract_font_size_from_styles(parsed_styles, sels, soup, inline_style=style_str)
            if fs:
                return Pt(fs)
        return Pt(default_pt)

    def _resolve_color(child, default_color):
        """读取 color：内联 style → <style> 块 → 默认值"""
        style_str = child.get("style", "")
        inline_color = get_inline_style_prop(style_str, "color")
        if inline_color:
            return inline_color
        if parsed_styles or soup:
            sels = _build_selectors(child)
            c = extract_color_from_styles(parsed_styles, sels, soup, inline_style=style_str)
            if c:
                return c
        return default_color

    first_para = True
    # 收集块级子元素和文本节点
    for child in li_el.children:
        if isinstance(child, NavigableString):
            text = re.sub(r"\s+", " ", str(child)).strip()
            if not text:
                continue
            p = cell.paragraphs[0] if first_para else add_cell_paragraph(cell)
            first_para = False
            run = p.add_run(text)
            set_run_font(run, size=Pt(11), color=hex_to_rgb(text_color))
        elif isinstance(child, Tag):
            child_name = child.name
            if child_name in ("p", "div", "span"):
                # 块级元素：新建段落（首块用 paragraphs[0]，后续 add_cell_paragraph）
                p = cell.paragraphs[0] if first_para else add_cell_paragraph(cell)
                first_para = False
                # 读取 font-size / color：内联 → <style> 块 → 调色板默认
                d_size = _resolve_font_size(child, 11)
                d_color = _resolve_color(child, text_color)
                _add_rich_text_runs(p, child, default_size=d_size, default_color=d_color)
            elif child_name == "br":
                if first_para:
                    p = cell.paragraphs[0]
                    first_para = False
                else:
                    p = add_cell_paragraph(cell)
                run = p.add_run()
                run.add_break()
            else:
                # 其他标签：提取文本写入当前段落
                text = get_text_content(child)
                if text:
                    p = cell.paragraphs[0] if first_para else add_cell_paragraph(cell)
                    first_para = False
                    _add_rich_text_runs(p, child, default_size=Pt(11), default_color=text_color)
    # 如果 li 内无任何子元素（纯文本已被上游提取），兜底
    if first_para:
        p = cell.paragraphs[0]
        run = p.add_run("")
        set_run_font(run, size=Pt(11), color=hex_to_rgb(text_color))


def _write_timeline_fallback(doc, lis, palette, parsed_styles=None, soup=None):
    """时间线兜底：5 种标准类名全找不到时，按 <li> 逐条展开为段落 + 列表

    不依赖特定类名，通用提取策略：
    - 标题行：<li> 内第一个有文本的 <strong>；没有则取第一个有文本的 <span>/<div>
    - 标题行作为加粗段落输出（包含版本号、状态、日期等所有信息）
    - 剩余子元素按原有结构输出（段落→段落，ul/ol→Word 列表）
    """
    text_color = palette.get("text", "1f2d3d")
    accent_color = palette.get("accent", "6366f1")
    first_li = True
    for li in lis:
        if not get_text_content(li):
            continue
        # 1) 提取标题行：优先 <strong>，没有则取第一个有文本的 <span> 或 <div>
        head_el = li.find("strong")
        if not head_el or not get_text_content(head_el):
            for el in li.find_all(["span", "div"]):
                t = get_text_content(el)
                if t and len(t) < 100:
                    head_el = el
                    break
        head_text = get_text_content(head_el) if head_el else ""

        # 2) 输出标题行（加粗，accent 色）
        if head_text:
            para = doc.add_paragraph()
            if first_li:
                if flush_pending_page_break(doc):
                    inject_page_break_before(para)
                first_li = False
            run = para.add_run(head_text)
            set_run_font(run, size=Pt(12), bold=True, color=hex_to_rgb(accent_color))
            para.paragraph_format.space_before = Pt(6)
            para.paragraph_format.space_after = Pt(2)
        elif first_li:
            flush_pending_page_break(doc)
            first_li = False

        # 3) 输出剩余内容：遍历 li 子元素，跳过已用作标题的元素
        for child in li.children:
            if not isinstance(child, Tag):
                text = re.sub(r"\s+", " ", str(child)).strip()
                if not text:
                    continue
                if head_el and head_el is child:
                    continue
                para = doc.add_paragraph()
                run = para.add_run(text)
                set_run_font(run, size=Pt(11), color=hex_to_rgb(text_color))
                para.paragraph_format.space_before = Pt(1)
                para.paragraph_format.space_after = Pt(2)
                continue
            if head_el and child is head_el:
                continue
            child_name = child.name
            # 段落
            if child_name == "p":
                if get_text_content(child):
                    from html2docx_core import process_paragraph
                    process_paragraph(doc, child, palette)
            # 列表
            elif child_name in ("ul", "ol"):
                from html2docx_core import process_bullet_list
                process_bullet_list(doc, child)
            # 嵌套容器（div/span）：提取文本输出
            elif child_name in ("div", "span"):
                inner = get_text_content(child)
                if inner:
                    para = doc.add_paragraph()
                    run = para.add_run(inner)
                    set_run_font(run, size=Pt(11), color=hex_to_rgb(text_color))
                    para.paragraph_format.space_before = Pt(1)
                    para.paragraph_format.space_after = Pt(2)
            # 其他有文本的元素
            elif get_text_content(child):
                inner = get_text_content(child)
                para = doc.add_paragraph()
                run = para.add_run(inner)
                set_run_font(run, size=Pt(11), color=hex_to_rgb(text_color))
                para.paragraph_format.space_before = Pt(1)
                para.paragraph_format.space_after = Pt(2)
    if first_li:
        flush_pending_page_break(doc)


def process_timeline(doc, section, palette, parsed_styles=None, soup=None):
    """时间线 → 两列表格（时间列 accent 加粗 + 描述列富文本）

    时间文本提取优先级：<div class="tl-time"> > <strong> > <span class="time"> >
    <span class="date"> > <span class="tl-year"> > 其他带时间特征（纯日期/时间格式的 span/em/b）

    .tl-time 结构：<div class="tl-time">14:32 <span class="tl-tag">T0 发现</span></div>
    时间文本取 .tl-time 的直接文本（不含 .tl-tag 标签内容），描述取 li 内其余内容。

    兜底：当所有 <li> 均无法提取到时间文本（5 种标准类名全不匹配）时，
    不输出空白左列表格，改为逐条展开为段落 + 列表（_write_timeline_fallback）。
    """
    lis = section.find_all("li", recursive=False) if section.name in ("ol", "ul") else section.find_all("li")
    if not lis:
        # 尝试 table 形式
        rows, _, _detail = parse_table_data(section.find("table")) if section.find("table") else ([], [], [])
        if rows:
            items = [(r[0].strip(), r[1].strip(), None) for r in rows if len(r) >= 2]
            _write_timeline_table(doc, items, palette, parsed_styles, soup)
            return
        flush_pending_page_break(doc)
        return
    items = []
    all_time_empty = True
    for li in lis:
        # 时间元素查找（优先级）：.tl-time → <strong> → .time → .date → .tl-year
        time_el = li.find(class_="tl-time")
        if not time_el or not get_text_content(time_el):
            time_el = li.find("strong")
        if not time_el or not get_text_content(time_el):
            time_el = li.find(class_="time")
        if not time_el or not get_text_content(time_el):
            time_el = li.find(class_="date")
        if not time_el or not get_text_content(time_el):
            time_el = li.find(class_="tl-year")
        time_text = get_text_content(time_el) if time_el else ""

        # 对于 .tl-time，提取时间文本（排除 .tl-tag 子元素）
        if time_el and time_el.name == "div" and "tl-time" in (time_el.get("class") or []):
            # .tl-time 的直接文本节点（不含 .tl-tag）
            direct_text = ""
            for node in time_el.children:
                if isinstance(node, NavigableString):
                    direct_text += str(node)
                elif isinstance(node, Tag) and "tl-tag" not in (node.get("class") or []):
                    direct_text += node.get_text()
            time_text = direct_text.strip()

        if time_text:
            all_time_empty = False

        desc = li.get_text(strip=True)
        # 删除开头的 time_text（避免误删正文中相同子串，只删前缀）
        if time_text and desc.startswith(time_text):
            desc = desc[len(time_text):].strip()
        # 构建 desc 元素用于富文本渲染（li 去除时间元素后的副本）
        desc_el = li
        if time_el:
            desc_el = copy.deepcopy(li)
            # 在副本中查找并移除时间元素
            # 优先匹配 .tl-time（div），再匹配 strong / .time / .date / .tl-year
            found_and_removed = False
            for tc in desc_el.find_all(class_="tl-time"):
                if get_text_content(tc) == time_text or \
                   get_text_content(tc).startswith(time_text):
                    tc.extract()
                    found_and_removed = True
                    break
            if not found_and_removed:
                time_in_copy = desc_el.find("strong")
                if time_in_copy and get_text_content(time_in_copy) == time_text:
                    time_in_copy.extract()
                    found_and_removed = True
            if not found_and_removed:
                for tc in desc_el.find_all(class_="time"):
                    if get_text_content(tc) == time_text:
                        tc.extract()
                        found_and_removed = True
                        break
            if not found_and_removed:
                for tc in desc_el.find_all(class_="date"):
                    if get_text_content(tc) == time_text:
                        tc.extract()
                        break
            if not found_and_removed:
                for tc in desc_el.find_all(class_="tl-year"):
                    if get_text_content(tc) == time_text:
                        tc.extract()
                        break
        # 移除装饰性箭头（折叠按钮 ▶ 等），避免残留到描述列
        for arrow_el in desc_el.find_all(class_="collapse-arrow"):
            arrow_el.extract()
        for arrow_el in desc_el.find_all(class_="collapse-trigger"):
            # 折叠触发按钮本身保留其文本（标题），仅移除按钮内箭头
            for span in arrow_el.find_all(class_="collapse-arrow"):
                span.extract()
        items.append((time_text, desc, desc_el))

    # 兜底：所有 li 的时间文本均为空 → 逐条展开，不输出空白左列表格
    if all_time_empty:
        _write_timeline_fallback(doc, lis, palette, parsed_styles, soup)
    else:
        _write_timeline_table(doc, items, palette, parsed_styles, soup)


def process_code_block(doc, section):
    """代码块 → Consolas + 浅灰底色（保留多行结构）

    换行处理：python-docx 的 add_run 不会把 \n 转成 Word 换行符，
    必须按行拆分、逐行 add_run + add_break()，否则代码会全部挤成一行。
    空行保留：空行用 add_break() 表示（不跳过），保持代码视觉结构。
    """
    code = section.find("code") or section.find("pre")
    if not code:
        flush_pending_page_break(doc)
        return
    text = code.get_text()
    # 统一换行符：\r\n / \r → \n，避免 Windows 残留 ^M
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    para = doc.add_paragraph()
    if flush_pending_page_break(doc):
        inject_page_break_before(para)
    for i, line in enumerate(lines):
        if i > 0:
            # 上一行与当前行之间插入段内换行（保留空行：直接 add_break 不写文本）
            para.add_run().add_break()
        if line:
            run = para.add_run(line)
            set_run_font(run, font_name=CODE_FONT, size=Pt(9.5))
    shading = OxmlElement("w:shd")
    shading.set(qn("w:fill"), "f1f5f9")
    shading.set(qn("w:val"), "clear")
    para.paragraph_format.element.get_or_add_pPr().append(shading)
    para.paragraph_format.space_before = Pt(4)
    para.paragraph_format.space_after = Pt(4)
