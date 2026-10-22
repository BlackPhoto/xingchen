#!/usr/bin/env python3
"""
html2docx_scene.py — 场景层处理（7 种 IR）

IR 类型：card_grid / divider / tab_group / collapse_group / hero_banner /
        task_list / mini_chart / auto_table / chart_unknown

被 html2docx.py 主入口 import。
依赖 docx_utils + sem_common，跨层依赖 html2docx_core（process_table）。
"""

import re
import os
import io
from urllib.parse import quote_from_bytes

from bs4 import Tag

from sem_common import (
    get_text_content, find_semantic_class, semantic_children,
    detect_repetitive_grid, extract_chart_data,
    is_hidden_chart_label, is_chart_card,
)
from docx_utils import (
    hex_to_rgb,
    extract_bg_with_gradient_fallback,
    set_run_font, add_cell_paragraph, flush_pending_page_break, inject_page_break_before,
    set_cell_margins, set_table_borders_nil, set_table_borders, set_cell_borders, set_table_width_percent,
    apply_shading, apply_shading_to_cell, apply_shading_to_run,
)
from docx.shared import Pt, Cm, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

# 跨层依赖：Tab 面板内嵌套表格、_add_rich_text_runs
from html2docx_core import process_table, _add_rich_text_runs


def _collect_cards(element, group_info):
    """从聚合组或单元素中提取卡片列表

    每个条目: {title, items, content_list, bg}
    items: 卡片内除 h3 外的有序内容列表，每项为 (kind, text)：
           kind ∈ {"tag", "paragraph", "price", "price_label", "cta", "badge",
                   "stars", "avatar", "name", "meta"}
    content_list: 卡片内 ul/ol 列表项文本列表（转换时逐行输出，避免内容丢失）
    """
    def _extract_one(card_el):
        h3 = card_el.find("h3") or card_el.find("h4") or card_el.find("strong")
        title = get_text_content(h3) if h3 else ""

        # 递归遍历卡片内所有元素（穿透 .feature-text / .reviewer-info 等嵌套容器），
        # 按 HTML 源码顺序收集内容项，避免只看直接子元素导致嵌套内容丢失。
        items = []
        _collected_ul_ols = set()  # 记录已处理的 ul/ol，避免 content_list 重复

        def _walk(el):
            """递归遍历元素，按源码顺序收集内容项"""
            for child in el.children:
                if not isinstance(child, Tag):
                    continue
                child_classes = child.get("class") or []
                # h3/h4/strong → 作为 title 类型
                if child.name in ("h3", "h4", "strong"):
                    items.append(("title", get_text_content(child)))
                    continue
                # a.cta-btn → cta 类型（立即购买/抢购等按钮文本）
                if child.name == "a" and "cta-btn" in child_classes:
                    items.append(("cta", get_text_content(child)))
                    continue
                # .badge → badge 类型（如"🔥 热销推荐"）
                if "badge" in child_classes:
                    items.append(("badge", get_text_content(child)))
                    continue
                # .stars → stars 类型（如"★★★★★"）
                if "stars" in child_classes:
                    items.append(("stars", get_text_content(child)))
                    continue
                # .avatar → avatar 类型（如"李"）
                if "avatar" in child_classes:
                    items.append(("avatar", get_text_content(child)))
                    continue
                # .name（reviewer-info 内）→ name 类型
                if "name" in child_classes:
                    items.append(("name", get_text_content(child)))
                    continue
                # .meta（reviewer-info 内）→ meta 类型
                if "meta" in child_classes:
                    items.append(("meta", get_text_content(child)))
                    continue
                # tag 标签（feature-tag 等）
                if "tag" in child_classes or "feature-tag" in child_classes:
                    items.append(("tag", get_text_content(child)))
                    continue
                # price 标签
                if "price" in child_classes:
                    items.append(("price", get_text_content(child)))
                    continue
                # price-label 标签
                if "price-label" in child_classes:
                    items.append(("price_label", get_text_content(child)))
                    continue
                # 段落
                if child.name == "p":
                    items.append(("paragraph", get_text_content(child)))
                    continue
                # ul/ol 列表由 content_list 处理，这里跳过但记录
                if child.name in ("ul", "ol"):
                    _collected_ul_ols.add(id(child))
                    continue
                # 跳过 SVG 图表元素
                if child.name == "svg":
                    continue
                # 跳过纯图片容器（feature-img-wrap 等，图片由 imgs 字段处理）
                if "feature-img-wrap" in child_classes:
                    continue
                # 嵌套容器（div 等）：递归进入，提取内部内容项
                if child.name in ("div", "span", "section"):
                    inner_text = get_text_content(child)
                    # 如果子元素中有语义内容（h3/p/a/span 等），递归进入
                    has_semantic_children = child.find(
                        ["h3", "h4", "p", "a", "span", "ul", "ol", "li", "div"]) is not None
                    if has_semantic_children:
                        _walk(child)
                    elif inner_text:
                        items.append(("paragraph", inner_text))
                    continue
                # 其他有文本的元素兜底为段落
                elif get_text_content(child):
                    items.append(("paragraph", get_text_content(child)))

        _walk(card_el)

        # 兜底：无 items 且无 h3 时取整体文本
        if not items and not title and not card_el.find(["ul", "ol"]):
            items.append(("paragraph", card_el.get_text(strip=True)))

        # 收集 ul/ol 列表项（完整保留，避免丢失）
        content_list = []
        for ul in card_el.find_all(["ul", "ol"]):
            for li in ul.find_all("li", recursive=False):
                t = get_text_content(li)
                if t:
                    content_list.append(t)
        # 检测卡片是否含 SVG 图表（饼图/环形图/折线图等）
        has_svg = card_el.find("svg") is not None
        # 卡片内图片（base64）：收集用于 Word 端插入（避免图片丢失）
        imgs = []
        for img_el in card_el.find_all("img"):
            if img_el.get("src", "").startswith("data:image/"):
                imgs.append(img_el)
        bg = extract_bg_with_gradient_fallback(card_el.get("style", ""))
        return {"title": title, "items": items, "content_list": content_list,
                "bg": bg, "has_svg": has_svg, "imgs": imgs}

    cards = []
    if group_info and group_info[0] == "card":
        for card_el in group_info[1]:
            cards.append(_extract_one(card_el))
        return cards
    # 单元素：自身是 card 或容器内多个 card
    if find_semantic_class(element) == "card":
        return [_extract_one(element)]
    cards_members = semantic_children(element, "card")
    for card_el in cards_members:
        cards.append(_extract_one(card_el))
    return cards


def process_card_grid(doc, section, palette, group_info=None, soup=None):
    """卡片网格 → 无边框表格（标题加粗 + 内容分行）+ 卡片 shading + 淡边框 + 顶部 accent 线

    含 SVG 图表的 card（饼图/环形图等）委托 process_chart_unknown 处理（截图优先），
    不走表格布局，避免 SVG <text> 被提取为混乱文本。
    """
    # 获取原始 card 元素列表，用于 SVG 检测和 chart_unknown 委托
    card_elements = []
    if group_info and group_info[0] == "card":
        card_elements = list(group_info[1])
    elif find_semantic_class(section) == "card":
        card_elements = [section]
    else:
        card_elements = semantic_children(section, "card")

    # 含 SVG 的 card → 委托 process_chart_unknown（截图优先，数据提取兜底）
    svg_cards = [el for el in card_elements if el.find("svg")]
    if svg_cards:
        for el in svg_cards:
            try:
                process_chart_unknown(doc, el, palette, soup=soup)
            except Exception:
                pass
        # 全部 card 都含 SVG → 不走 card_grid 表格布局
        if len(svg_cards) == len(card_elements):
            return
        # 部分 card 含 SVG → 仅处理不含 SVG 的 card
        card_elements = [el for el in card_elements if not el.find("svg")]
        if not card_elements:
            return
        # 更新 group_info 使 _collect_cards 只处理不含 SVG 的 card
        if group_info and group_info[0] == "card":
            group_info = ("card", card_elements)

    # 含 .chart-row 柱状图的 card（无 SVG、无表格）→ 委托 process_chart_card（截图优先）
    # 柱状图是纯 CSS 结构，不走表格文本提取，避免柱形视觉丢失
    chart_row_cards = [el for el in card_elements
                       if not el.find("svg")
                       and el.find(class_="chart-row")
                       and not el.find("table")]
    if chart_row_cards:
        for el in chart_row_cards:
            try:
                process_chart_card(doc, el, palette, soup=soup)
            except Exception:
                pass
        if len(chart_row_cards) == len(card_elements):
            return
        card_elements = [el for el in card_elements if el not in chart_row_cards]
        if not card_elements:
            return
        if group_info and group_info[0] == "card":
            group_info = ("card", card_elements)

    cards = _collect_cards(section, group_info)
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
        first_para = True
        # 按 HTML 源码顺序输出所有 items（tag/title/paragraph/price/cta 等）
        for kind, text in card.get("items", []):
            if not text:
                continue
            p_item = cell.paragraphs[0] if first_para else add_cell_paragraph(cell)
            first_para = False
            if kind == "tag":
                p_item.paragraph_format.space_before = Pt(0)
                p_item.paragraph_format.space_after = Pt(2)
            elif kind == "title":
                p_item.paragraph_format.space_before = Pt(0)
                p_item.paragraph_format.space_after = Pt(4)
            elif kind == "cta":
                p_item.paragraph_format.space_before = Pt(6)
                p_item.paragraph_format.space_after = Pt(2)
            elif kind == "badge":
                p_item.paragraph_format.space_before = Pt(0)
                p_item.paragraph_format.space_after = Pt(2)
            elif kind == "stars":
                p_item.paragraph_format.space_before = Pt(2)
                p_item.paragraph_format.space_after = Pt(2)
            elif kind == "name":
                p_item.paragraph_format.space_before = Pt(2)
                p_item.paragraph_format.space_after = Pt(0)
            elif kind == "meta":
                p_item.paragraph_format.space_before = Pt(0)
                p_item.paragraph_format.space_after = Pt(2)
            else:
                p_item.paragraph_format.space_before = Pt(1)
                p_item.paragraph_format.space_after = Pt(1)
            run = p_item.add_run(text)
            if kind == "tag":
                set_run_font(run, size=Pt(9), bold=True,
                             color=hex_to_rgb(palette.get("accent", "3b82f6")))
            elif kind == "title":
                set_run_font(run, size=Pt(12), bold=True,
                             color=hex_to_rgb(palette.get("primary", "1e293b")))
            elif kind == "price":
                set_run_font(run, size=Pt(16), bold=True,
                             color=hex_to_rgb(palette.get("primary", "1e293b")))
            elif kind == "price_label":
                set_run_font(run, size=Pt(9), color=hex_to_rgb("64748b"))
            elif kind == "cta":
                # 按钮：加粗 + 白字 + accent 背景色（视觉降级为底色段落）
                set_run_font(run, size=Pt(11), bold=True,
                             color=hex_to_rgb("ffffff"))
                apply_shading_to_run(run, palette.get("accent", "3b82f6"))
            elif kind == "badge":
                set_run_font(run, size=Pt(9), bold=True,
                             color=hex_to_rgb("ffffff"))
                apply_shading_to_run(run, palette.get("primary", "1e293b"))
            elif kind == "stars":
                set_run_font(run, size=Pt(11), color=hex_to_rgb("f59e0b"))
            elif kind == "avatar":
                # 头像首字母：加粗 + accent 色
                set_run_font(run, size=Pt(11), bold=True,
                             color=hex_to_rgb(palette.get("accent", "3b82f6")))
            elif kind == "name":
                set_run_font(run, size=Pt(10), bold=True,
                             color=hex_to_rgb(palette.get("primary", "1e293b")))
            elif kind == "meta":
                set_run_font(run, size=Pt(8), color=hex_to_rgb("64748b"))
            else:  # paragraph
                set_run_font(run, size=Pt(10), color=hex_to_rgb("475569"))
        # 卡片内列表项：逐行输出为 Word 列表段落（完整保留，避免内容丢失）
        for item in card.get("content_list", []):
            p_item = add_cell_paragraph(cell)
            p_item.paragraph_format.space_before = Pt(1)
            p_item.paragraph_format.space_after = Pt(1)
            run_item = p_item.add_run("• " + item)
            set_run_font(run_item, size=Pt(10), color=hex_to_rgb("475569"))
        # 卡片内图片（base64）：插入 Word 单元格，避免图片丢失
        for img_el in card.get("imgs", []):
            try:
                from html2docx_core import _extract_img_bytes
                from docx.shared import Inches as _Inches
                from copy import deepcopy
                img_bytes = _extract_img_bytes(img_el)
                if not img_bytes:
                    print(f"[INFO] card_grid: 卡片图片提取失败 {card.get('title','')[:20]}")
                    continue
                # 通过 doc.add_picture 注册图片到文档 part，再把 shape 移入单元格。
                # 注意：add_cell_paragraph 返回的 Paragraph 其 parent 是 CT_Tc（无 part），
                # 直接 run.add_picture() 会报 "'CT_Tc' object has no attribute 'part'"。
                inline_shape = doc.add_picture(io.BytesIO(img_bytes), width=_Inches(2.2))
                temp_para = doc.paragraphs[-1]
                shape_elem = deepcopy(inline_shape._inline)
                temp_para._element.getparent().remove(temp_para._element)
                p_img = add_cell_paragraph(cell)
                p_img.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p_img.paragraph_format.space_before = Pt(4)
                p_img.paragraph_format.space_after = Pt(4)
                run_img = p_img.add_run()
                run_img._element.append(shape_elem)
                print(f"[INFO] card_grid: 卡片图片已插入 {card.get('title','')[:20]}")
            except Exception as e:
                print(f"[WARN] card_grid: 图片插入失败 {card.get('title','')[:20]}: {e!r}")
        set_cell_margins(cell, top=40, start=60, bottom=40, end=60)


def process_divider(doc):
    """分隔线 → 居中饰线（短线 + ◆ + 短线）"""
    has_pending = flush_pending_page_break(doc)
    para = doc.add_paragraph()
    if has_pending:
        inject_page_break_before(para)
    para.paragraph_format.space_before = Pt(6)
    para.paragraph_format.space_after = Pt(6)
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run1 = para.add_run("─" * 6)
    set_run_font(run1, size=Pt(8), color=hex_to_rgb("cbd5e1"))
    run2 = para.add_run(" ◆ ")
    set_run_font(run2, size=Pt(9), color=hex_to_rgb("3b82f6"))
    run3 = para.add_run("─" * 6)
    set_run_font(run3, size=Pt(8), color=hex_to_rgb("cbd5e1"))


def process_tab_group(doc, section, palette, parsed_styles=None, soup=None):
    """Tab 切换组 → 标签→面板内容交替输出（Word 无 Tab 交互，展开全部）

    每个 tab 按钮标题输出为加粗小标题段落，其后跟随对应面板的完整内容。
    面板内容按"标题 + 正文 + 列表 + 卡片"逐项输出，保证内容不丢。
    """
    # 收集按钮标题（.tab-btn）与面板（.tab-panel）
    tab_nav = section if "tab-nav" in (section.get("class") or []) else section.find(class_="tab-nav")
    if tab_nav is None:
        tab_nav = section
    btns = tab_nav.find_all("button", class_="tab-btn") if tab_nav else []
    # 面板：取 tab-nav 之后连续的兄弟 .tab-panel（同一组，防止跨组串扰）
    panels = []
    if tab_nav is not None and tab_nav.parent is not None:
        siblings = [c for c in tab_nav.parent.children if isinstance(c, Tag)]
        try:
            idx = siblings.index(tab_nav)
        except ValueError:
            idx = -1
        for sib in siblings[idx + 1:] if idx >= 0 else []:
            if "tab-panel" in (sib.get("class") or []):
                panels.append(sib)
            else:
                break
    if not panels:
        panels = [p for p in section.find_all(class_="tab-panel")]
    # 无按钮时直接输出全部面板内容
    if not btns:
        for panel in panels:
            _output_tab_panel(doc, panel, palette, parsed_styles, soup)
        return
    # 按钮与面板按下标对齐输出
    for i, btn in enumerate(btns):
        btn_text = get_text_content(btn)
        # 标题段落（加粗，主色）
        para = doc.add_paragraph()
        if flush_pending_page_break(doc):
            inject_page_break_before(para)
        para.paragraph_format.space_before = Pt(8)
        para.paragraph_format.space_after = Pt(2)
        run = para.add_run(btn_text)
        set_run_font(run, size=Pt(13), bold=True,
                     color=hex_to_rgb(palette.get("primary", "1e293b")))
        # 对应面板内容
        if i < len(panels):
            _output_tab_panel(doc, panels[i], palette, parsed_styles, soup)


def _output_tab_panel(doc, panel, palette, parsed_styles=None, soup=None):
    """输出单个 Tab 面板的全部内容，严格保持 HTML DOM 顺序

    修复说明（2026-08）：
      - 旧实现"先整体输出特殊容器（gmv-hero/funnel/table-wrap），再输出语义块"
        会破坏 DOM 顺序，导致漏斗数据、表格标题等跑到其 h1/h2 标题之前。
      - 现改为按子元素顺序单遍遍历 + 容器递归：遇到即输出，顺序与 HTML 一致。
      - 同时保留对 gmv-hero / funnel / bar-chart 等结构的整体输出（数据不丢）。
    """
    from html2docx_core import (
        process_table, process_image, process_paragraph, process_heading,
        process_bullet_list,
    )
    from html2docx_enhanced import process_callout, process_stat_block
    from sem_common import get_text_content, find_semantic_class, classify_element

    def _emit(child):
        """按 DOM 顺序输出一个子元素（含容器递归）"""
        if not isinstance(child, Tag):
            return
        child_classes = child.get("class") or []
        # 交互辅助元素：无内容价值，跳过（与主流程 SKIP_INTERACTIVE_CLASSES 一致）
        if any(c in ("code-copy-btn", "table-search-input", "table-no-result", "back-to-top", "dark-toggle-btn")
               for c in child_classes):
            return
        # 隐藏的图表数据标签（.chart-labels 带 aria-hidden / display:none）：
        # 浏览器中不可见，是降级兜底标签，图表截图已覆盖信息，跳过避免重复输出
        if is_hidden_chart_label(child):
            return

        # 1) 特殊结构容器：整体输出（顺序即位置，数据不丢）
        if "gmv-hero" in child_classes:
            _output_gmv_hero(doc, child, palette)
            return
        # funnel-wrap 不再在此拦截：统一走 1.5) is_chart_card → process_chart_card 截图路径，
        # 截图失败时 process_chart_card 内部会回退文本结构（漏斗各级名称+数据）。
        if "bar-chart-wrap" in child_classes:
            _output_bar_chart(doc, child, palette, soup)
            return
        if "table-wrap" in child_classes:
            tbl = child.find("table")
            if tbl is not None:
                try:
                    process_table(doc, tbl, palette, parsed_styles, soup)
                except Exception:
                    pass
            return

        # 1.5) 图表卡容器（funnel-wrap / chart-card / trend-card…）→ 截图优先
        # 主流程经 classify_element 识别 mini_chart；但 Tab 面板内 _emit 走
        # find_semantic_class（仅查 SEMANTIC_CLASSES），这些图表 class 不在其中，
        # 会被当普通容器拆散为纯数字文本。此处先行识别，保证漏斗/柱状图截图。
        if is_chart_card(child):
            try:
                process_chart_card(doc, child, palette, parsed_styles, soup)
            except Exception:
                pass
            return

        # 2) stat 聚合组（直接子元素 ≥2 个 .stat → 整组输出）
        stats = [c for c in child.children
                 if isinstance(c, Tag) and "stat" in (c.get("class") or [])]
        if len(stats) >= 2:
            try:
                process_stat_block(doc, child, palette, ("stat", stats))
            except Exception:
                for s in stats:
                    try:
                        process_stat_block(doc, s, palette, None)
                    except Exception:
                        pass
            return

        # 3) 语义 class → 按类型分发（与主流程 process_block 一致）
        scls = find_semantic_class(child)
        if scls:
            ir = classify_element(child)
            if ir == "title_page":
                process_heading(doc, child, palette, False)
                return
            if ir == "end_page":
                return
            if ir == "heading":
                process_heading(doc, child, palette, False)
                return
            if ir == "paragraph":
                process_paragraph(doc, child, palette)
                return
            if ir == "bullet_list":
                process_bullet_list(doc, child)
                return
            if ir == "table":
                try:
                    process_table(doc, child, palette, parsed_styles, soup)
                except Exception:
                    pass
                return
            if ir == "image":
                process_image(doc, child)
                return
            if ir == "callout":
                process_callout(doc, child, palette)
                return
            if ir == "stat_block":
                process_stat_block(doc, child, palette, None)
                return
            if ir == "mini_chart":
                process_chart_card(doc, child, palette, parsed_styles, soup)
                return
            if ir == "card_grid":
                # card 内含 <table class="table"> 时走容器递归，
                # 避免 process_card_grid 拍平内部表格结构
                if child.find("table", class_="table"):
                    tag_children = [c for c in child.children if isinstance(c, Tag)]
                    if tag_children:
                        for c in child.children:
                            _emit(c)
                        return
                # card 内含 .chart-row 柱状图（无 SVG、无表格）→ 走截图路径，
                # 避免柱状图被拍平为纯数字文本（与 SVG 图表 card 处理一致）
                if child.find(class_="chart-row"):
                    process_chart_card(doc, child, palette, parsed_styles, soup)
                    return
                # card 内含 .funnel-wrap 漏斗图 → 走截图路径，
                # 避免漏斗各级数据被拍平为零散文本（与 chart-row 处理一致）
                if child.find(class_="funnel-wrap"):
                    process_chart_card(doc, child, palette, parsed_styles, soup)
                    return
                process_card_grid(doc, child, palette, None, soup=soup)
                return
            if ir == "collapse_group":
                process_collapse_group(doc, child, palette)
                return
            if ir == "tab_group":
                process_tab_group(doc, child, palette, parsed_styles, soup)
                return
            # 其余类型委托主流程 process_block（避免重复 27 项分发）
            from html2docx import process_block
            process_block(doc, child, ir, None, palette, False, parsed_styles, soup)
            return

        # 4) 裸结构标签
        if child.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            process_heading(doc, child, palette, False)
            return
        if child.name == "p":
            process_paragraph(doc, child, palette)
            return
        if child.name in ("ul", "ol"):
            process_bullet_list(doc, child)
            return
        if child.name == "table":
            try:
                process_table(doc, child, palette, parsed_styles, soup)
            except Exception:
                pass
            return
        if child.name in ("figure", "img") or "image" in child_classes:
            process_image(doc, child)
            return

        # 5) 无语义 class 的容器 → 递归子元素（保持内部顺序）
        if child.name in ("div", "section", "article", "header", "footer", "aside", "main"):
            tag_children = [c for c in child.children if isinstance(c, Tag)]
            if tag_children:
                for c in child.children:
                    _emit(c)
                return

        # 5.5) SVG / 图表容器 → 委托 chart_unknown 处理（截图优先，数据提取兜底）
        # 避免 SVG 内 <text> 元素被 get_text_content 提取为混乱段落
        if child.name == "svg" or child.find("svg"):
            try:
                process_chart_unknown(doc, child, palette, soup)
            except Exception:
                pass
            return

        # 6) 兜底：有可见文本 → 段落
        text = get_text_content(child)
        if text:
            process_paragraph(doc, child, palette)

    # 兼容：非 Tab 面板容器也按相同规则顺序输出
    for child in panel.children:
        _emit(child)


def _output_gmv_hero(doc, section, palette):
    """GMV 大数字横幅 → 居中大数字 + 标签 + 说明（内容保留）"""
    label_el = section.find(class_="gmv-label")
    num_el = section.find(class_="gmv-number") or section.find(class_="gmv-num")
    sub_el = section.find(class_="gmv-sub")
    text_color = palette.get("text", "1f2d3d")
    if label_el:
        text = get_text_content(label_el)
        if text:
            para = doc.add_paragraph()
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            para.paragraph_format.space_before = Pt(4)
            para.paragraph_format.space_after = Pt(0)
            run = para.add_run(text)
            set_run_font(run, size=Pt(11), color=hex_to_rgb("64748b"))
    if num_el:
        text = get_text_content(num_el)
        if text:
            para = doc.add_paragraph()
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            para.paragraph_format.space_before = Pt(0)
            para.paragraph_format.space_after = Pt(0)
            run = para.add_run(text)
            set_run_font(run, size=Pt(24), bold=True,
                         color=hex_to_rgb(palette.get("primary", "1e293b")))
    if sub_el:
        text = get_text_content(sub_el)
        if text:
            para = doc.add_paragraph()
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            para.paragraph_format.space_before = Pt(2)
            para.paragraph_format.space_after = Pt(6)
            run = para.add_run(text)
            set_run_font(run, size=Pt(10), color=hex_to_rgb(text_color))


def _output_funnel(doc, section, palette):
    """漏斗图 → 每级一行：名称 | 数据（保留数据不丢）"""
    stages = section.find_all(class_="funnel-stage")
    if not stages:
        # 兜底：输出所有可见文本
        text = get_text_content(section)
        if text:
            para = doc.add_paragraph()
            run = para.add_run(text)
            set_run_font(run, size=Pt(11), color=hex_to_rgb(palette.get("text", "1f2d3d")))
        return
    accent = palette.get("accent", "6366f1")
    text_color = palette.get("text", "1f2d3d")
    # 漏斗连接线（点击率 30.0% / 到达率 80.0% 等）→ 小字号段落，避免被静默丢弃（2026-09 修复）
    connectors = section.find_all(class_="funnel-connector")
    for stage in stages:
        # 类名兼容：优先 fs-name/fs-data（技能标准），兼容 f-name/f-value/f-pct（618 复盘等变体）
        name_el = stage.find(class_="fs-name") or stage.find(class_="f-name")
        data_el = stage.find(class_="fs-data") or stage.find(class_="f-value")
        name = get_text_content(name_el) if name_el else ""
        data = get_text_content(data_el) if data_el else ""
        # 百分比（f-pct 等）作为补充数据拼入
        pct_el = stage.find(class_="f-pct") or stage.find(class_="fs-pct")
        pct = get_text_content(pct_el) if pct_el else ""
        line = "  |  ".join(x for x in (name, data, pct) if x)
        if not line:
            # 兜底：字段类名全部不匹配时回退整级文本，杜绝静默丢失（2026-09 修复）
            whole = get_text_content(stage)
            if whole:
                para = doc.add_paragraph()
                para.paragraph_format.space_before = Pt(1)
                para.paragraph_format.space_after = Pt(1)
                run = para.add_run(whole)
                set_run_font(run, size=Pt(11), color=hex_to_rgb(text_color))
            continue
        para = doc.add_paragraph()
        para.paragraph_format.space_before = Pt(1)
        para.paragraph_format.space_after = Pt(1)
        if name:
            run_n = para.add_run(name)
            set_run_font(run_n, size=Pt(11), bold=True, color=hex_to_rgb(accent))
        if data:
            run_d = para.add_run("  " + data)
            set_run_font(run_d, size=Pt(11), color=hex_to_rgb(text_color))
        if pct:
            run_p = para.add_run("  " + pct)
            set_run_font(run_p, size=Pt(10), color=hex_to_rgb("8b8b8b"))
    # 连接线输出（在每个 stage 后紧随对应 connector，保持漏斗顺序）
    for conn in connectors:
        conn_text = get_text_content(conn)
        if conn_text:
            para = doc.add_paragraph()
            para.paragraph_format.space_before = Pt(1)
            para.paragraph_format.space_after = Pt(1)
            run = para.add_run(conn_text)
            set_run_font(run, size=Pt(10), color=hex_to_rgb("b08510"))
            run.font.italic = True


def _output_bar_chart(doc, section, palette, soup=None):
    """柱状图 → 纯图形截图优先，含表格走文本；截图失败回退为 排名 + 名称 + 数值（数据保留）"""
    # 判定：含内嵌数据表 → 可全部文本显示，不截图（与 mini_chart 一致）
    inner_table = section.find("table")
    if inner_table is None:
        # Playwright 截图优先（与 mini_chart / chart_unknown 一致）
        try:
            png_bytes = _rasterize_element(section, soup)
            if png_bytes:
                import io as _io
                from docx.shared import Inches as _Inches
                flush_pending_page_break(doc)
                p_img = doc.add_paragraph()
                p_img.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p_img.paragraph_format.space_before = Pt(4)
                p_img.paragraph_format.space_after = Pt(4)
                run_img = p_img.add_run()
                run_img.add_picture(_io.BytesIO(png_bytes), width=_Inches(5.5))
                print("[INFO] bar_chart: 已通过 Playwright 截图插入 Word")
                return
        except Exception as e:
            print(f"[INFO] bar_chart: Playwright 截图不可用（{e}），回退数据行")

    rows = section.find_all(class_="bar-row")
    if not rows:
        text = get_text_content(section)
        if text:
            para = doc.add_paragraph()
            run = para.add_run(text)
            set_run_font(run, size=Pt(11), color=hex_to_rgb(palette.get("text", "1f2d3d")))
        return
    text_color = palette.get("text", "1f2d3d")
    for row in rows:
        rank_el = row.find(class_="bar-rank")
        label_el = row.find(class_="bar-label")
        fill_el = row.find(class_="bar-fill")
        rank = get_text_content(rank_el) if rank_el else ""
        label = get_text_content(label_el) if label_el else ""
        value = get_text_content(fill_el) if fill_el else ""
        parts = []
        if rank:
            parts.append(rank)
        if label:
            parts.append(label)
        if value:
            parts.append(value)
        line = "  ".join(parts)
        if not line:
            # 兜底：bar-row 字段类名全部不匹配时回退整行文本，杜绝静默丢失（2026-09 修复）
            whole = get_text_content(row)
            if whole:
                para = doc.add_paragraph()
                para.paragraph_format.space_before = Pt(1)
                para.paragraph_format.space_after = Pt(1)
                run = para.add_run(whole)
                set_run_font(run, size=Pt(11), color=hex_to_rgb(text_color))
            continue
        para = doc.add_paragraph()
        para.paragraph_format.space_before = Pt(1)
        para.paragraph_format.space_after = Pt(1)
        run = para.add_run(line)
        set_run_font(run, size=Pt(11), color=hex_to_rgb(text_color))


def process_collapse_group(doc, section, palette):
    """折叠展开组件 → 标题加粗 + 正文完整展开（Word 无折叠交互，内容全部保留）

    每个 .collapse-trigger 的标题输出为加粗段落，对应 .collapse-body 内容
    按子元素结构化展开：段落→段落、列表→列表项、表格→process_table、
    callout→process_callout，避免拍平为纯文本丢失格式。
    """
    from html2docx_core import process_table as _ptable, process_paragraph as _ppara
    from html2docx_enhanced import process_callout as _pcallout

    collapse_items = section.find_all(class_="collapse-item")
    if not collapse_items:
        # 兼容平铺结构：容器直接包含 .collapse-trigger + .collapse-body（无 .collapse-item 包装层）
        # 例如 .bid-card 内部直接平铺 trigger/body，每对 trigger+body 视为一个折叠项
        direct_triggers = section.find_all(class_="collapse-trigger", recursive=False)
        if direct_triggers:
            for trig in direct_triggers:
                # 标题：去除箭头符号（▶/▸/› 等装饰字符）
                title = get_text_content(trig) if trig else ""
                title = re.sub(r"[▶▸►›>]", "", title).strip()
                if title:
                    para = doc.add_paragraph()
                    para.paragraph_format.space_before = Pt(6)
                    para.paragraph_format.space_after = Pt(2)
                    run = para.add_run(title)
                    set_run_font(run, size=Pt(12), bold=True,
                                 color=hex_to_rgb(palette.get("primary", "1e293b")))
                # 查找对应的 body：优先 data-body 属性匹配，否则下一个兄弟 .collapse-body
                idx = trig.get("data-collapse")
                body = None
                if idx is not None:
                    body = section.find(class_="collapse-body", attrs={"data-body": idx})
                if body is None:
                    body = trig.find_next_sibling(class_="collapse-body")
                _output_collapse_body(doc, body, palette)
            flush_pending_page_break(doc)
            return
        flush_pending_page_break(doc)
        return
    for i, item in enumerate(collapse_items):
        trigger = item.find(class_="collapse-trigger")
        body = item.find(class_="collapse-body")
        # 标题：去除箭头符号（▶/▸/› 等装饰字符）
        title = get_text_content(trigger) if trigger else ""
        title = re.sub(r"[▶▸►›>]", "", title).strip()
        # 标题段落（加粗，主色）
        if title:
            para = doc.add_paragraph()
            if i == 0 and flush_pending_page_break(doc):
                inject_page_break_before(para)
            para.paragraph_format.space_before = Pt(6)
            para.paragraph_format.space_after = Pt(2)
            run = para.add_run(title)
            set_run_font(run, size=Pt(12), bold=True,
                         color=hex_to_rgb(palette.get("primary", "1e293b")))
        # 正文：遍历 body 子元素，按类型分别输出
        if not body:
            continue
        _output_collapse_body(doc, body, palette)


def _output_collapse_body(doc, body, palette):
    """输出折叠体正文：段落→段落、列表→列表项、表格→process_table、
    callout→process_callout、timeline→process_timeline、impact-grid→表格卡片、
    rootcause-direct/deep→callout 样式

    穿透无语义包装层：遇到 div 且无语义 class（如 .collapse-body-inner / 裸 div[style]）
    时递归遍历其子元素，避免内容被 get_text_content 拍平为纯文本。
    """
    from html2docx_core import process_table as _ptable
    from html2docx_enhanced import process_callout as _pcallout, process_timeline as _ptimeline

    for child in body.children:
        if not isinstance(child, Tag):
            continue
        child_classes = child.get("class") or []

        # 穿透无语义包装层（.collapse-body-inner / 裸 div[style] 等）
        # 排除需要特殊处理的组件：demo-grid（→表格）
        if child.name == "div" and find_semantic_class(child) is None \
           and "impact-grid" not in child_classes \
           and "rootcause-direct" not in child_classes \
           and "rootcause-deep" not in child_classes \
           and "demo-grid" not in child_classes:
            # 尝试识别 flex 表格（裸 div 容器内含 display:flex 行）
            if _is_flex_table_container(child):
                _process_flex_table(doc, child, palette)
                continue
            _output_collapse_body(doc, child, palette)
            continue

        # demo-grid → 模拟 Excel 网格 → Word 表格
        if "demo-grid" in child_classes:
            _process_demo_grid(doc, child, palette)
            continue

        # 通用重复网格检测（兜底）：未识别 div 含规律性重复行列 → auto_table
        if child.name == "div" and find_semantic_class(child) is None \
           and detect_repetitive_grid(child) is not None:
            _process_auto_table_from_grid(doc, child, palette)
            continue

        # timeline → process_timeline
        if "timeline" in child_classes:
            _ptimeline(doc, child, palette)
            continue

        # impact-grid → _process_impact_grid
        if "impact-grid" in child_classes:
            _process_impact_grid(doc, child, palette)
            continue

        # rootcause-direct → _process_rootcause_direct
        if "rootcause-direct" in child_classes:
            _process_rootcause_direct(doc, child, palette)
            continue

        # rootcause-deep → _process_rootcause_deep
        if "rootcause-deep" in child_classes:
            _process_rootcause_deep(doc, child, palette)
            continue

        if child.name == "p":
            text = get_text_content(child)
            if text:
                p_body = doc.add_paragraph()
                p_body.paragraph_format.space_before = Pt(1)
                p_body.paragraph_format.space_after = Pt(4)
                p_body.paragraph_format.left_indent = Cm(0.3)
                _add_rich_text_runs(p_body, child, default_size=Pt(11),
                                    default_color=palette.get("text", "1f2d3d"))
        elif child.name in ("ul", "ol"):
            for li in child.find_all("li", recursive=False):
                text = get_text_content(li)
                if not text:
                    continue
                para = doc.add_paragraph(style="List Bullet")
                para.paragraph_format.left_indent = Cm(0.6)
                _add_rich_text_runs(para, li, default_size=Pt(11),
                                    default_color=palette.get("text", "1f2d3d"))
        elif child.name == "table":
            try:
                _ptable(doc, child, palette)
            except Exception:
                pass
        elif "callout" in child_classes:
            _pcallout(doc, child, palette)
        elif child.name in ("h3", "h4"):
            p_sub = doc.add_paragraph()
            p_sub.paragraph_format.space_before = Pt(4)
            p_sub.paragraph_format.space_after = Pt(2)
            run_sub = p_sub.add_run(get_text_content(child))
            set_run_font(run_sub, size=Pt(13), bold=True,
                         color=hex_to_rgb(palette.get("primary", "1e293b")))
        else:
            # 兜底：有文本则输出为段落（用富文本写入保留格式）
            text = get_text_content(child)
            if text:
                p_body = doc.add_paragraph()
                p_body.paragraph_format.space_before = Pt(1)
                p_body.paragraph_format.space_after = Pt(4)
                p_body.paragraph_format.left_indent = Cm(0.3)
                _add_rich_text_runs(p_body, child, default_size=Pt(11),
                                    default_color=palette.get("text", "1f2d3d"))


def _parse_grid_cols(element):
    """从 grid-template-columns style 解析列数"""
    style = element.get("style", "")
    for part in style.split(";"):
        part = part.strip()
        if part.startswith("grid-template-columns"):
            val = part.split(":", 1)[1].strip()
            fr_count = val.split()
            return len(fr_count)
    return None


def _is_flex_table_container(element):
    """判断裸 div 是否为 flex 表格容器：
    直接子元素都是 div 且 style 含 display:flex，
    每个 flex div 的直接子元素都是 span
    """
    children = [c for c in element.children if isinstance(c, Tag)]
    if len(children) < 2:
        return False
    for c in children:
        if c.name != "div":
            return False
        style = c.get("style", "")
        if "display:flex" not in style and "display: flex" not in style:
            return False
        spans = [s for s in c.children if isinstance(s, Tag)]
        if not spans or any(s.name != "span" for s in spans):
            return False
    return True


def _process_demo_grid(doc, element, palette):
    """demo-grid（模拟 Excel 网格）→ Word 表格

    将 CSS Grid 布局的 .demo-cell 平铺单元格按列数切片重建为 Word 表格。
    表头行（.head class）加粗+底色，合计行（内联 background:#e8f0fe）加底色。
    """
    cells = [c for c in element.children if isinstance(c, Tag) and "demo-cell" in (c.get("class") or [])]
    if not cells:
        cells = element.find_all(class_="demo-cell", recursive=False)
    if not cells:
        return

    # 解析列数
    num_cols = _parse_grid_cols(element)
    if not num_cols or num_cols < 2:
        total = len(cells)
        for n in [4, 3, 5, 2, 6]:
            if total % n == 0:
                num_cols = n
                break
        if not num_cols:
            num_cols = 4
    num_rows = (len(cells) + num_cols - 1) // num_cols

    border_color = palette.get("border", "dbe4ef")
    table = doc.add_table(rows=num_rows, cols=num_cols)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_table_borders(table, color=border_color)
    set_table_width_percent(table, 100)

    for ri in range(num_rows):
        for ci in range(num_cols):
            idx = ri * num_cols + ci
            if idx >= len(cells):
                break
            cell_el = cells[idx]
            wcell = table.rows[ri].cells[ci]
            cell_classes = cell_el.get("class") or []
            is_head = "head" in cell_classes
            text = get_text_content(cell_el)
            p = wcell.paragraphs[0]
            run = p.add_run(text)
            cell_style = cell_el.get("style", "")
            is_bold = is_head or "font-weight:600" in cell_style or "font-weight:700" in cell_style
            if is_head:
                set_run_font(run, size=Pt(10), bold=True,
                             color=hex_to_rgb(palette.get("primary", "0f1e33")))
                apply_shading_to_cell(wcell, "dbe7f6")
            else:
                set_run_font(run, size=Pt(10), bold=is_bold,
                             color=hex_to_rgb("1f2d3d"))
                if "background:#e8f0fe" in cell_style or "background: #e8f0fe" in cell_style:
                    apply_shading_to_cell(wcell, "e8f0fe")


def _process_auto_table_from_grid(doc, element, palette):
    """通用重复网格（auto_table）→ Word 表格

    复用 _process_demo_grid 的表格构建逻辑：detect_repetitive_grid 已
    验证行结构一致性，直接按其列数切片重建为 Word 表格。
    首行（class 含 head/header 或 font-weight 加粗）作为表头加粗+底色。
    """
    result = detect_repetitive_grid(element)
    if not result:
        return
    num_cols, rows_data = result
    num_rows = len(rows_data)

    border_color = palette.get("border", "dbe4ef")
    table = doc.add_table(rows=num_rows, cols=num_cols)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_table_borders(table, color=border_color)
    set_table_width_percent(table, 100)

    for ri, row_cells in enumerate(rows_data):
        for ci, cell_el in enumerate(row_cells):
            wcell = table.rows[ri].cells[ci]
            cell_classes = cell_el.get("class") or []
            cell_style = cell_el.get("style", "")
            is_head = ("head" in cell_classes or "header" in cell_classes
                       or "font-weight:600" in cell_style or "font-weight:700" in cell_style
                       or "font-weight: 600" in cell_style or "font-weight: 700" in cell_style)
            text = get_text_content(cell_el)
            p = wcell.paragraphs[0]
            run = p.add_run(text)
            if is_head:
                set_run_font(run, size=Pt(10), bold=True,
                             color=hex_to_rgb(palette.get("primary", "0f1e33")))
                apply_shading_to_cell(wcell, "dbe7f6")
            else:
                set_run_font(run, size=Pt(10), color=hex_to_rgb("1f2d3d"))


def _process_flex_table(doc, container, palette):
    """flex 布局表格（裸 div 容器内含 display:flex 行）→ Word 表格

    将 display:flex 布局的行式表格重建为 Word 表格。
    表头行（style 含 font-weight:600/700）加粗+底色。
    """
    rows_data = []
    for row_div in container.children:
        if not isinstance(row_div, Tag) or row_div.name != "div":
            continue
        spans = [s for s in row_div.children if isinstance(s, Tag) and s.name == "span"]
        texts = [get_text_content(s) for s in spans]
        rows_data.append((row_div, texts))

    if not rows_data:
        return

    num_cols = max(len(texts) for _, texts in rows_data)
    num_rows = len(rows_data)

    border_color = palette.get("border", "dbe4ef")
    table = doc.add_table(rows=num_rows, cols=num_cols)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_table_borders(table, color=border_color)
    set_table_width_percent(table, 100)

    for ri, (row_div, texts) in enumerate(rows_data):
        row_style = row_div.get("style", "")
        is_header = ("font-weight:600" in row_style or "font-weight:700" in row_style
                     or "font-weight: 600" in row_style or "font-weight: 700" in row_style)
        for ci in range(num_cols):
            text = texts[ci] if ci < len(texts) else ""
            wcell = table.rows[ri].cells[ci]
            p = wcell.paragraphs[0]
            run = p.add_run(text)
            if is_header:
                set_run_font(run, size=Pt(10), bold=True,
                             color=hex_to_rgb(palette.get("primary", "0f1e33")))
                apply_shading_to_cell(wcell, "dbe7f6")
            else:
                set_run_font(run, size=Pt(10), color=hex_to_rgb("1f2d3d"))


def _process_impact_grid(doc, element, palette):
    """影响范围网格 → 无边框表格，每列一张卡片（级别+标题+描述+明细）"""
    cards = element.find_all(class_="impact-card", recursive=False)
    if not cards:
        cards = element.find_all(class_="impact-card")
    if not cards:
        return
    num_cols = len(cards)
    table = doc.add_table(rows=1, cols=num_cols)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_table_borders_nil(table)
    set_table_width_percent(table, 100)

    severity_colors = {"p0": "dc2626", "p1": "ea580c", "p2": "2563eb"}
    border_color = palette.get("border", "e2e8f0")

    for j, card in enumerate(cards):
        cell = table.cell(0, j)
        card_classes = card.get("class", [])
        severity = "p0"
        for cls in card_classes:
            if cls in severity_colors:
                severity = cls
                break
        sev_color = severity_colors.get(severity, "6366f1")
        set_cell_borders(cell, top_color=sev_color, color=border_color)
        first_para = True

        # ic-head: 级别 + 标题
        head = card.find(class_="ic-head")
        if head:
            level = head.find(class_="ic-level")
            title = head.find(class_="ic-title")
            if level:
                p = cell.paragraphs[0] if first_para else add_cell_paragraph(cell)
                first_para = False
                p.paragraph_format.space_before = Pt(0)
                p.paragraph_format.space_after = Pt(2)
                run = p.add_run(get_text_content(level))
                set_run_font(run, size=Pt(11), bold=True, color=hex_to_rgb(sev_color))
            if title:
                p = cell.paragraphs[0] if first_para else add_cell_paragraph(cell)
                first_para = False
                p.paragraph_format.space_before = Pt(0)
                p.paragraph_format.space_after = Pt(4)
                run = p.add_run(get_text_content(title))
                set_run_font(run, size=Pt(10), bold=True, color=hex_to_rgb("334155"))

        # ic-desc: 描述
        desc = card.find(class_="ic-desc")
        if desc and get_text_content(desc):
            p = cell.paragraphs[0] if first_para else add_cell_paragraph(cell)
            first_para = False
            p.paragraph_format.space_before = Pt(1)
            p.paragraph_format.space_after = Pt(4)
            _add_rich_text_runs(p, desc, default_size=Pt(10), default_color="475569")

        # ic-detail: 明细（含 <strong> 标签 + <br> 换行）
        detail = card.find(class_="ic-detail")
        if detail and get_text_content(detail):
            p = cell.paragraphs[0] if first_para else add_cell_paragraph(cell)
            first_para = False
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after = Pt(2)
            _add_rich_text_runs(p, detail, default_size=Pt(9), default_color="64748b")

        set_cell_margins(cell, top=40, start=60, bottom=40, end=60)


def _process_rootcause_direct(doc, element, palette):
    """直接原因 → callout 样式段落（label 前缀 + 正文，浅红底 + 左边框）"""
    label = element.find(class_="rc-label")
    text_el = element.find(class_="rc-text")
    if not text_el or not get_text_content(text_el):
        text = get_text_content(element)
        if not text:
            return
    else:
        text = get_text_content(text_el)
    if not text:
        return

    para = doc.add_paragraph()
    para.paragraph_format.space_before = Pt(4)
    para.paragraph_format.space_after = Pt(4)
    para.paragraph_format.left_indent = Cm(0.3)

    if label:
        run_label = para.add_run(get_text_content(label) + "：")
        set_run_font(run_label, size=Pt(10), bold=True, color=hex_to_rgb("dc2626"))

    if text_el:
        _add_rich_text_runs(para, text_el, default_size=Pt(11), default_color="1f2d3d")
    else:
        run = para.add_run(text)
        set_run_font(run, size=Pt(11), color=hex_to_rgb("1f2d3d"))

    # callout 样式：浅红底 + 左边框
    shading = OxmlElement("w:shd")
    shading.set(qn("w:fill"), "fef2f2")
    shading.set(qn("w:val"), "clear")
    para.paragraph_format.element.get_or_add_pPr().append(shading)
    pPr = para.paragraph_format.element.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    left_bdr = OxmlElement("w:left")
    left_bdr.set(qn("w:val"), "single")
    left_bdr.set(qn("w:sz"), "12")
    left_bdr.set(qn("w:space"), "4")
    left_bdr.set(qn("w:color"), "dc2626")
    pBdr.append(left_bdr)
    pPr.append(pBdr)


def _process_rootcause_deep(doc, element, palette):
    """深层原因 → 编号列表（序号 + 标题加粗 + 描述段落）"""
    items = element.find_all(class_="rcd-item", recursive=False)
    if not items:
        items = element.find_all(class_="rcd-item")
    if not items:
        return

    accent = palette.get("accent", "6366f1")

    for item in items:
        num = item.find(class_="rcd-num")
        title = item.find(class_="rcd-title")
        desc = item.find(class_="rcd-desc")

        # 标题行："1. 代码评审未覆盖慢查询风险点"
        para = doc.add_paragraph()
        para.paragraph_format.space_before = Pt(6)
        para.paragraph_format.space_after = Pt(1)
        para.paragraph_format.left_indent = Cm(0.3)

        if num:
            run_num = para.add_run(get_text_content(num) + ". ")
            set_run_font(run_num, size=Pt(11), bold=True, color=hex_to_rgb(accent))
        if title:
            run_title = para.add_run(get_text_content(title))
            set_run_font(run_title, size=Pt(11), bold=True,
                         color=hex_to_rgb(palette.get("primary", "1e293b")))

        # 描述段落
        if desc and get_text_content(desc):
            p_desc = doc.add_paragraph()
            p_desc.paragraph_format.space_before = Pt(0)
            p_desc.paragraph_format.space_after = Pt(4)
            p_desc.paragraph_format.left_indent = Cm(0.6)
            _add_rich_text_runs(p_desc, desc, default_size=Pt(10), default_color="475569")


def process_task_list(doc, section, palette, group_info=None):
    """任务卡片列表（.task-item）→ 一行式卡片表格（编号 | 标题+描述 | 难度）

    每个 .task-item 输出为一行 3 列无边框表格：
      - 编号列：.task-num 文本（圆形蓝色编号，Word 中加粗 + accent 色）
      - 内容列：.task-title 加粗 + .task-desc 正文（按 HTML 源码顺序）
      - 难度列：.task-level 文本（按 easy/mid/hard 分别着色）
    内容完整保留，卡片布局归约为表格行（与 card_grid 策略一致）。

    group_info: ("task", [elements]) 表示连续同级 .task-item 兄弟的合并组，
                所有任务输出到同一张表；None 时从 section 自身/子元素收集。
    """
    # 收集任务卡片：
    #   - group_info 提供完整列表（连续同级 .task-item 合并场景）
    #   - section 自身是 .task-item → 单个
    #   - 否则取其直接子元素中的 .task-item，再递归兜底
    items = []
    if group_info and group_info[0] == "task":
        items = list(group_info[1])
    elif "task-item" in (section.get("class") or []):
        items = [section]
    else:
        items = [c for c in section.children if isinstance(c, Tag)
                 and "task-item" in (c.get("class") or [])]
        if not items:
            items = section.find_all(class_="task-item")
    if not items:
        flush_pending_page_break(doc)
        return

    accent = palette.get("accent", "3b82f6")
    primary = palette.get("primary", "1e293b")
    border_color = palette.get("border", "e2e8f0")
    # 难度等级配色（对应 HTML 端 .task-level.easy/mid/hard）
    level_colors = {
        "easy": ("E8F5E9", "2E7D32"),
        "mid": ("FFF3E0", "E65100"),
        "hard": ("FCE4EC", "C62828"),
    }

    # 一行一个任务卡片（3 列表格：编号 | 内容 | 难度）
    num_cols = 3
    table = doc.add_table(rows=0, cols=num_cols)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_table_borders_nil(table)
    set_table_width_percent(table, 100)

    for item in items:
        row = table.add_row()
        cells = row.cells

        # 1) 编号列
        num_el = item.find(class_="task-num")
        num_text = get_text_content(num_el) if num_el else ""
        cell0 = cells[0]
        cell0.width = Cm(1.2)
        set_cell_margins(cell0, top=40, start=80, bottom=40, end=40)
        if num_text:
            p0 = cell0.paragraphs[0]
            p0.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r0 = p0.add_run(num_text)
            set_run_font(r0, size=Pt(13), bold=True, color=hex_to_rgb(accent))

        # 2) 内容列：穿透无语义包装层（如 .task-body）收集 title/desc，按 HTML 源码顺序输出
        content_nodes = []
        def collect_content(node):
            for child in node.children:
                if not isinstance(child, Tag):
                    continue
                cls = child.get("class") or []
                if child.name == "button" or "task-num" in cls or "task-level" in cls:
                    continue
                if "task-title" in cls or "task-desc" in cls:
                    content_nodes.append(child)
                else:
                    # 无语义包装层（task-body / 裸 div）递归穿透，避免拍平
                    collect_content(child)
        collect_content(item)

        cell1 = cells[1]
        apply_shading_to_cell(cell1, "F8FAFC")
        set_cell_margins(cell1, top=40, start=80, bottom=40, end=80)
        first_para = True
        for child in content_nodes:
            cls = child.get("class") or []
            # 标题行：.task-title → 加粗
            if "task-title" in cls:
                t = get_text_content(child)
                if not t:
                    continue
                p = cell1.paragraphs[0] if first_para else add_cell_paragraph(cell1)
                first_para = False
                p.paragraph_format.space_before = Pt(1)
                p.paragraph_format.space_after = Pt(2)
                r = p.add_run(t)
                set_run_font(r, size=Pt(11), bold=True, color=hex_to_rgb(primary))
            # 描述行：.task-desc → 正文（小一号灰色）
            elif "task-desc" in cls:
                t = get_text_content(child)
                if not t:
                    continue
                p = cell1.paragraphs[0] if first_para else add_cell_paragraph(cell1)
                first_para = False
                p.paragraph_format.space_before = Pt(0)
                p.paragraph_format.space_after = Pt(1)
                r = p.add_run(t)
                set_run_font(r, size=Pt(9.5), color=hex_to_rgb("64748b"))
        # 内容列为空时兜底输出整体文本（防丢失）
        if first_para:
            p = cell1.paragraphs[0]
            r = p.add_run(get_text_content(item))
            set_run_font(r, size=Pt(10), color=hex_to_rgb("475569"))

        # 3) 难度列
        lvl_el = item.find(class_="task-level")
        lvl_text = get_text_content(lvl_el) if lvl_el else ""
        cell2 = cells[2]
        cell2.width = Cm(1.8)
        set_cell_margins(cell2, top=40, start=40, bottom=40, end=80)
        if lvl_text:
            p2 = cell2.paragraphs[0]
            p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r2 = p2.add_run(lvl_text)
            # 依据难度等级着色（easy=绿 mid=橙 hard=红；未知等级用 accent）
            lvl_key = ""
            if lvl_el is not None:
                lvl_cls = lvl_el.get("class") or []
                lvl_key = next((c for c in lvl_cls if c in level_colors), "")
            if lvl_key in level_colors:
                bg_hex, fg_hex = level_colors[lvl_key]
                set_run_font(r2, size=Pt(9), bold=True, color=hex_to_rgb(fg_hex))
                # 难度徽章底色：run 级字符底纹
                apply_shading_to_run(r2, bg_hex)
            else:
                set_run_font(r2, size=Pt(9), bold=True, color=hex_to_rgb(accent))

        # 行底淡边框（与卡片风格一致）
        for c in cells:
            set_cell_borders(c, top_color=border_color, color=border_color)

    # 任务卡片后留空一行（与后续内容分隔）
    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_before = Pt(2)
    spacer.paragraph_format.space_after = Pt(2)


def process_hero_banner(doc, section, palette):
    """Hero Banner → 标题段落 + 底线装饰（加背景色 shading）"""
    has_pending = flush_pending_page_break(doc)
    bg_color = extract_bg_with_gradient_fallback(section.get("style", ""))
    h1 = section.find("h1")
    p = section.find("p")
    para = doc.add_paragraph()
    if has_pending:
        inject_page_break_before(para)
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    para.paragraph_format.space_before = Pt(24)
    para.paragraph_format.space_after = Pt(8)
    if bg_color:
        apply_shading(para, bg_color)
    run = para.add_run(get_text_content(h1) if h1 else "")
    set_run_font(run, size=Pt(28), bold=True, color=hex_to_rgb(palette.get("primary", "1e293b")))
    if p:
        para2 = doc.add_paragraph()
        para2.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para2.paragraph_format.space_before = Pt(2)
        para2.paragraph_format.space_after = Pt(8)
        if bg_color:
            apply_shading(para2, bg_color)
        run2 = para2.add_run(get_text_content(p))
        set_run_font(run2, size=Pt(14), color=hex_to_rgb(palette.get("accent", "64748b")))
    para3 = doc.add_paragraph()
    para3.alignment = WD_ALIGN_PARAGRAPH.CENTER
    para3.paragraph_format.space_before = Pt(4)
    para3.paragraph_format.space_after = Pt(4)
    if bg_color:
        apply_shading(para3, bg_color)
    run3 = para3.add_run("─" * 8)
    set_run_font(run3, size=Pt(10), color=hex_to_rgb(palette.get("accent", "64748b")))

    # Hero 区产品图（base64）：插入 Word，避免图片丢失
    hero_img = section.find("img")
    if hero_img is not None:
        try:
            from html2docx_core import _extract_img_bytes, extract_img_width_px
            img_bytes = _extract_img_bytes(hero_img)
            if img_bytes:
                p_img = doc.add_paragraph()
                p_img.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p_img.paragraph_format.space_before = Pt(8)
                p_img.paragraph_format.space_after = Pt(4)
                if bg_color:
                    apply_shading(p_img, bg_color)
                run_img = p_img.add_run()
                run_img.add_picture(io.BytesIO(img_bytes), width=Inches(4.5))
        except Exception:
            pass


def process_chart_card(doc, section, palette, parsed_styles=None, soup=None):
    """图表卡（trend-card / sparkline-card / chart-row）→ Word 结构区块

    处理策略（2026-08 起）：图形优先截图，可文本化的走文本。
      - 判定原则：能全部文本显示的就不贴图，不能显示的（纯图形）才贴图。
      - 含 <table> 内嵌数据表 → 可完整文本化，不截图，走"标题+标签+指标+表格"路径
      - 含 SVG / .chart-row/.bar 等纯图形结构 → Playwright 截图（视觉保真）
      - 截图失败回退文本结构：
        - h3 标题 → 加粗段落
        - .chart-labels（W31~W38 / 图像/文本…）→ 数据标签行（分类，逗号分隔）
        - .stat-inline（34% 图像（最大类）…）→ 指标行（值+说明）
        - .note（文字说明）→ 说明段落
        - .bar（仅高度样式，无文本）→ 不输出（空条无信息量）
    保留内容完整性，避免 bar 被误判为 auto_table 产生空表格行。
    """
    if flush_pending_page_break(doc):
        pass  # 分页逻辑由外层 process_block 统一处理

    # ===== 判定：含内嵌数据表 → 可全部文本显示，不截图 =====
    # 各渠道 GMV 明细等"图表+表格"卡片：表格数据是核心信息，
    # 文本化输出完整（含表头+每行数据），不贴图避免重复。
    inner_table = section.find("table")
    if inner_table is None:
        # ===== 纯图形（SVG / chart-row / bar）→ Playwright 截图优先 =====
        # 截图包含容器内的 h3 标题 + 图表 + 标签 + 指标行，视觉完整；
        # 成功则插入图片并 return；失败回退到下方文本结构。
        try:
            png_bytes = _rasterize_element(section, soup)
            if png_bytes:
                import io as _io
                from docx.shared import Inches as _Inches
                flush_pending_page_break(doc)
                p_img = doc.add_paragraph()
                p_img.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p_img.paragraph_format.space_before = Pt(4)
                p_img.paragraph_format.space_after = Pt(4)
                run_img = p_img.add_run()
                run_img.add_picture(_io.BytesIO(png_bytes), width=_Inches(5.5))
                print("[INFO] mini_chart: 已通过 Playwright 截图插入 Word")
                return
        except Exception as e:
            print(f"[INFO] mini_chart: Playwright 截图不可用（{e}），回退文本结构")

    accent = palette.get("accent", "6366f1")
    text_color = palette.get("text", "1f2d3d")
    border_color = palette.get("border", "e2e8f0")

    # 标题：h3（图表卡）或 chart-row 的直接文本
    title_el = section.find("h3")
    title = get_text_content(title_el) if title_el else ""
    if not title:
        # 兜底：chart-row 单独出现时取自身 class 描述
        classes = section.get("class") or []
        if "chart-row" in classes:
            title = ""
    if title:
        para = doc.add_paragraph()
        para.paragraph_format.space_before = Pt(6)
        para.paragraph_format.space_after = Pt(4)
        run = para.add_run(title)
        set_run_font(run, size=Pt(12), bold=True, color=hex_to_rgb(palette.get("primary", "1e293b")))

    # 数据标签行：.chart-labels 或 .stat-inline
    # 优先 .chart-labels（分类标签），再 .stat-inline（指标行）
    labels_el = section.find(class_="chart-labels")
    stat_inline_el = section.find(class_="stat-inline")
    if labels_el:
        labels = [get_text_content(s) for s in labels_el.find_all("span", recursive=False)]
        labels = [l for l in labels if l]
        if labels:
            p_labels = doc.add_paragraph()
            p_labels.paragraph_format.space_before = Pt(2)
            p_labels.paragraph_format.space_after = Pt(2)
            run_l = p_labels.add_run(" · ".join(labels))
            set_run_font(run_l, size=Pt(10), color=hex_to_rgb(text_color))

    # 2. .stat-inline 指标行（值 + 标签）
    if stat_inline_el:
        items = []
        for item in stat_inline_el.find_all(class_="item", recursive=False):
            v = item.find(class_="v")
            l = item.find(class_="l")
            v_text = get_text_content(v) if v else ""
            l_text = get_text_content(l) if l else ""
            if v_text and l_text:
                items.append(f"{v_text} {l_text}")
            elif v_text:
                items.append(v_text)
        if items:
            p_stats = doc.add_paragraph()
            p_stats.paragraph_format.space_before = Pt(2)
            p_stats.paragraph_format.space_after = Pt(2)
            run_stats = p_stats.add_run(" | ".join(items))
            set_run_font(run_stats, size=Pt(10), color=hex_to_rgb(accent))

    # 3. .note 说明
    note = section.find(class_="note")

    # 3.5 漏斗图回退文本：截图失败时提取 funnel-stage 各级数据
    funnel_stages = section.find_all(class_="funnel-stage")
    if funnel_stages:
        for stage in funnel_stages:
            # 类名兼容：优先标准类名，兼容常见变体
            name_el = (stage.find(class_="stage-name") or stage.find(class_="fs-name")
                       or stage.find(class_="f-name"))
            count_el = (stage.find(class_="stage-count") or stage.find(class_="fs-data")
                        or stage.find(class_="f-value"))
            rate_el = (stage.find(class_="stage-rate") or stage.find(class_="fs-pct")
                       or stage.find(class_="f-pct"))
            name = get_text_content(name_el) if name_el else ""
            count = get_text_content(count_el) if count_el else ""
            rate = get_text_content(rate_el) if rate_el else ""
            line = "  |  ".join(x for x in (name, count, rate) if x)
            if not line:
                # 兜底：字段类名全部不匹配时回退整级文本，杜绝静默丢失
                line = get_text_content(stage)
            if line:
                p_funnel = doc.add_paragraph()
                p_funnel.paragraph_format.space_before = Pt(1)
                p_funnel.paragraph_format.space_after = Pt(1)
                run_f = p_funnel.add_run(line)
                set_run_font(run_f, size=Pt(10), color=hex_to_rgb(text_color))

    if note:
        note_text = get_text_content(note)
        if note_text:
            p_note = doc.add_paragraph()
            p_note.paragraph_format.space_before = Pt(2)
            p_note.paragraph_format.space_after = Pt(6)
            run_note = p_note.add_run(note_text)
            set_run_font(run_note, size=Pt(9), color=hex_to_rgb("64748b"))

    # 4. 内嵌 <table>（如各渠道 GMV 明细表）
    # trend-card 可能内嵌数据表格，process_chart_card 原逻辑不处理 table 导致丢失
    inner_table = section.find("table")
    if inner_table:
        try:
            process_table(doc, inner_table, palette, parsed_styles, soup)
        except Exception:
            pass


def process_chart_unknown(doc, section, palette, soup=None):
    """未知图表/图形容器 → 三层降级兜底处理

    用于 classify_element 无法识别具体图表类型时的兜底 IR。
    三层降级策略（按可用性依次尝试）：

    第 0 层：Playwright 光栅化截图 → PNG 插入 Word（视觉保真度最高）
    第 1 层：从 HTML/SVG 结构中递归提取全部文本和数据 → 重建数据表格/列表
    第 2 层：零文本零数据（纯装饰元素）→ 跳过（无信息可保，不输出无意义警告）
    """
    import io as _io
    from docx.shared import Inches as _Inches

    text_color = palette.get("text", "1f2d3d")
    accent = palette.get("accent", "6366f1")
    primary = palette.get("primary", "1e293b")

    # ===== 判定：含内嵌数据表 → 可全部文本显示，不截图 =====
    # 与 mini_chart 一致：表格数据可完整文本化，截图会导致图片+表格重复。
    inner_table = section.find("table")
    if inner_table is None:
        # ===== 第 0 层：Playwright 光栅化截图 =====
        # 对未知图表区域截图转 PNG 插入 Word，视觉保真度最高。
        # 失败则降级到第 1 层。
        try:
            png_bytes = _rasterize_element(section, soup)
            if png_bytes:
                flush_pending_page_break(doc)
                para = doc.add_paragraph()
                para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                para.paragraph_format.space_before = Pt(6)
                para.paragraph_format.space_after = Pt(4)
                run = para.add_run()
                run.add_picture(_io.BytesIO(png_bytes), width=_Inches(5.5))
                print("[INFO] chart_unknown: 已通过 Playwright 截图插入 Word")
                return
        except Exception as e:
            print(f"[INFO] chart_unknown: Playwright 截图不可用（{e}），降级到数据提取")

    # ===== 第 1 层：从结构中提取数据重建表格/列表 =====
    data_items = extract_chart_data(section)
    if data_items:
        flush_pending_page_break(doc)
        # 标题（如容器内有 h3/h4）
        title_el = section.find(["h3", "h4"])
        title = get_text_content(title_el) if title_el else ""
        if title:
            para_t = doc.add_paragraph()
            para_t.paragraph_format.space_before = Pt(6)
            para_t.paragraph_format.space_after = Pt(4)
            run_t = para_t.add_run(title)
            set_run_font(run_t, size=Pt(12), bold=True, color=hex_to_rgb(primary))

        # 两列以上 → 重建数据表格；否则 → 列表
        if len(data_items) > 1 and any(len(item) > 1 for item in data_items):
            # 重建数据表
            max_cols = max(len(item) for item in data_items)
            num_rows = len(data_items)
            table = doc.add_table(rows=num_rows, cols=max_cols)
            table.alignment = WD_TABLE_ALIGNMENT.CENTER
            set_table_borders(table, color=palette.get("border", "dbe4ef"))
            set_table_width_percent(table, 100)
            for ri, row_data in enumerate(data_items):
                for ci in range(max_cols):
                    cell_text = row_data[ci] if ci < len(row_data) else ""
                    cell = table.rows[ri].cells[ci]
                    p = cell.paragraphs[0]
                    run = p.add_run(str(cell_text))
                    set_run_font(run, size=Pt(10), color=hex_to_rgb(text_color))
                    if ri == 0:
                        run.bold = True
            print(f"[INFO] chart_unknown: 已提取 {num_rows} 行数据重建表格")
        else:
            # 单列数据 → 列表输出
            for item in data_items:
                line = "  ".join(str(x) for x in item if x)
                if line:
                    para = doc.add_paragraph()
                    para.paragraph_format.space_before = Pt(1)
                    para.paragraph_format.space_after = Pt(1)
                    run = para.add_run(line)
                    set_run_font(run, size=Pt(10), color=hex_to_rgb(text_color))
            print(f"[INFO] chart_unknown: 已提取 {len(data_items)} 项数据输出为列表")
        return

    # ===== 第 2 层：纯装饰元素 → 跳过 =====
    # 零文本零数据，无信息可保，直接跳过（不输出无意义的警告段落）
    print("[INFO] chart_unknown: 无可提取数据（纯装饰元素），已跳过")
    flush_pending_page_break(doc)


def _rasterize_element(section, soup=None):
    """使用 Playwright 对 HTML 中的图表元素区域截图，返回 PNG 字节。

    实现方式：将整个 soup（或 section 的父文档）渲染到 Playwright 页面，
    截取 section 对应 DOM 区域的截图。

    失败返回 None（由调用方降级处理）。
    """
    # Playwright 可能未安装或无 Chromium，用 try/except 保护
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    # 需要 HTML 文件路径才能渲染——从 soup 重建临时文件
    if soup is None:
        return None

    import tempfile
    import os

    # 从 section 提取一个可用于定位的标记
    # 如果 section 有 id 属性，用 #id 定位；否则用内容哈希生成临时 id
    target_id = section.get("id", "")
    if not target_id:
        import hashlib
        target_id = "chart-unknown-" + hashlib.md5(get_text_content(section).encode()).hexdigest()[:8]
        section["id"] = target_id

    # ===== 关联元素判定：确定截图边界 =====
    # 旧逻辑：向上回溯找父容器，要求图表组件占比 >=2/3，不识别 SVG → 截图范围不精确
    # 新逻辑：先判断 section 是不是图表元素（SVG/Canvas/chart-row 等），
    #   如果是，找父容器，标记"该截的"（图表+标签+图例+数据注释）和"不该截的"
    #   （正文段落、标题），通过 JS 临时隐藏不该截的元素后截父容器。
    _CHART_COMPONENT_CLS = (
        "chart-row", "chart-labels", "stat-inline",
        "legend-list", "legend-item",
        "funnel-stage", "funnel-connector",
    )
    _CHART_TAG_NAMES = ("svg", "canvas")

    # section 自身是否为图表元素（含 chart-row class 或是 svg/canvas 标签）
    _is_chart_element = (
        any(c in _CHART_COMPONENT_CLS for c in (section.get("class") or []))
        or section.name in _CHART_TAG_NAMES
    )

    # 该隐藏的兄弟元素 id 列表（截图前 JS 临时 display:none，截图后恢复）
    _hide_ids = []

    if _is_chart_element:
        parent = section.parent
        if parent is not None and parent.name not in ("body", "html"):
            # 确保父容器有 id（截图目标）
            if not parent.get("id"):
                import hashlib
                parent_id = "chart-parent-" + hashlib.md5(
                    get_text_content(parent).encode()
                ).hexdigest()[:8]
                parent["id"] = parent_id
            else:
                parent_id = parent.get("id")
            target_id = parent_id
            section = parent

            # 遍历父容器直接子元素，标记不该截的
            for child in parent.children:
                if not isinstance(child, Tag):
                    continue
                if child is parent:
                    continue
                # 该截的：图表组件（chart-row/chart-labels/stat-inline/legend-list/legend-item）
                #   + svg/canvas 标签 + 数据注释（紧跟图表的小字号 p）
                child_classes = child.get("class") or []
                child_name = child.name or ""
                _should_keep = (
                    any(c in _CHART_COMPONENT_CLS for c in child_classes)
                    or child_name in _CHART_TAG_NAMES
                )
                # 数据注释判断：含 font-size:12px 或 class 含 cite/source 的 p 标签
                if not _should_keep and child_name == "p":
                    child_style = child.get("style") or ""
                    _style_low = child_style.lower().replace(" ", "")
                    if "font-size:12px" in _style_low:
                        _should_keep = True
                    # class 含 source-list 的也保留（数据来源列表）
                    if "source-list" in child_classes:
                        _should_keep = True

                if not _should_keep:
                    # 不该截的：给临时 id，JS 隐藏
                    if not child.get("id"):
                        import hashlib as _hl
                        _hide_id = "chart-hide-" + _hl.md5(
                            get_text_content(child).encode()
                        ).hexdigest()[:8]
                        child["id"] = _hide_id
                    _hide_ids.append(child.get("id"))
        # 如果没有合适的父容器，target_id 保持 section 自身
    # 如果 section 不是图表元素（如直接是 doc-section 等），保持原样截 section

    # 重建完整 HTML（soup 可能已被修改，用原始字符串）
    html_str = str(soup)

    # 在 </head> 前注入 CSS：强制目标元素及其所有祖先可见
    # 解决 tab-panel display:none / collapse 折叠等导致截图不可见的问题
    visibility_css = f"""<style data-rasterize-fix>
#{target_id}, #{target_id} * {{
    visibility: visible !important;
    opacity: 1 !important;
}}
/* 强制目标元素的所有祖先容器可见（覆盖 display:none / visibility:hidden） */
</style>"""
    # 用 JS 在页面加载后动态设置祖先可见（比 CSS 更可靠，CSS 无法选择祖先链）
    # 同时临时隐藏不该截的兄弟元素，截图后再恢复
    _hide_ids_js = ", ".join(f"'{hid}'" for hid in _hide_ids)
    ancestor_js = """
<script data-rasterize-fix>
(function(){
    var el = document.getElementById('%s');
    if(!el) return;
    var node = el.parentElement;
    while(node && node !== document.body){
        var style = getComputedStyle(node);
        if(style.display === 'none' || style.visibility === 'hidden'){
            node.style.display = 'block';
            node.style.visibility = 'visible';
            node.style.opacity = '1';
        }
        node = node.parentElement;
    }
    // 临时隐藏不该截的兄弟元素
    var hideIds = [%s];
    var hidden = [];
    hideIds.forEach(function(hid){
        var h = document.getElementById(hid);
        if(h){
            hidden.push({el: h, display: h.style.display});
            h.style.display = 'none';
        }
    });
    // 恢复被隐藏的元素（用 setTimeout 确保截图已完成）
    setTimeout(function(){
        hidden.forEach(function(item){
            item.el.style.display = item.display;
        });
    }, 1000);
})();
</script>""" % (target_id, _hide_ids_js)

    # 注入到 HTML 中（</head> 前 / </body> 前）
    if "</head>" in html_str:
        html_str = html_str.replace("</head>", visibility_css + "\n</head>")
    if "</body>" in html_str:
        html_str = html_str.replace("</body>", ancestor_js + "\n</body>")

    # 写临时文件
    tmp_path = os.path.join(tempfile.gettempdir(), f"_chart_unknown_{target_id}.html")
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(html_str)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1200, "height": 900})
            # 路径分段 URL 编码，避免中文用户名/Temp 路径导致 Playwright 无法打开
            _path_parts = tmp_path.replace(os.sep, "/").split("/")
            _encoded_parts = []
            for _part in _path_parts:
                if _part:
                    _encoded_parts.append(quote_from_bytes(_part.encode("utf-8"), safe=""))
            _tmp_url = "file:///" + "/".join(_encoded_parts)
            page.goto(_tmp_url, wait_until="domcontentloaded")
            page.wait_for_timeout(500)  # 等待渲染
            # 确保元素可见后再截图（祖先链已由注入的 JS 强制可见）
            el = page.query_selector(f"#{target_id}")
            if el:
                # 使用 force 模式截图（绕过可见性检查）
                try:
                    png_bytes = el.screenshot(type="png")
                except Exception:
                    # 不可见时降级：用 page.screenshot 截整页后裁剪
                    png_bytes = None
                if png_bytes:
                    browser.close()
                    return png_bytes
            browser.close()
    except Exception as e:
        print(f"[INFO] chart_unknown 截图失败: {e}")
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass
    return None


def process_data_table(doc, section, palette, soup=None):
    """键值对数据组（.reason-data / .reason-data-item）→ 2 列数据表

    将 ".reason-data" 内 >=2 个 ".reason-data-item"（各含 .dv 值 + .dl 说明）
    归约为 2 列（值 / 说明）表格输出，避免被 flatten 拆成零散段落。

    结构兼容：
      - section 是 .reason-data 容器：遍历直接子 .reason-data-item
      - section 是 .reason-card（含 .reason-data）：自动下钻到 .reason-data
    """
    if flush_pending_page_break(doc):
        pass

    # 下钻：如果传入的是 reason-card 容器，先找其内 .reason-data
    data_el = section
    if "reason-data" not in (section.get("class") or []):
        data_el = section.find(class_="reason-data")
    if data_el is None:
        return

    items = [c for c in data_el.children
             if isinstance(c, Tag) and "reason-data-item" in (c.get("class") or [])]
    if len(items) < 2:
        return

    rows = []
    for item in items:
        dv = item.find(class_="dv")
        dl = item.find(class_="dl")
        v = get_text_content(dv) if dv else ""
        l = get_text_content(dl) if dl else ""
        if v or l:
            rows.append((v, l))

    if not rows:
        return

    border_color = palette.get("border", "dbe4ef")
    text_color = palette.get("text", "1f2d3d")
    accent = palette.get("accent", "3b82f6")

    table = doc.add_table(rows=len(rows) + 1, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_table_borders(table, color=border_color)
    set_table_width_percent(table, 100)

    # 表头
    for ci, header in enumerate(("指标", "说明")):
        cell = table.rows[0].cells[ci]
        cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = cell.paragraphs[0].add_run(header)
        set_run_font(run, size=Pt(10), bold=True, color=hex_to_rgb(accent))
        apply_shading_to_cell(cell, palette.get("primary_light", "dbe7f6"))

    # 数据行：值列加粗 + 主色，说明列常规
    for ri, (v, l) in enumerate(rows, start=1):
        c0, c1 = table.rows[ri].cells
        set_cell_margins(c0, top=40, start=80, bottom=40, end=80)
        set_cell_margins(c1, top=40, start=80, bottom=40, end=80)
        if v:
            run_v = c0.paragraphs[0].add_run(v)
            set_run_font(run_v, size=Pt(10), bold=True, color=hex_to_rgb(accent))
        if l:
            run_l = c1.paragraphs[0].add_run(l)
            set_run_font(run_l, size=Pt(10), color=hex_to_rgb(text_color))

    print(f"[INFO] data_table: 已输出 {len(rows)} 行键值对数据表")


def process_stat_table(doc, section, palette, soup=None):
    """.stat-inline 指标行 → 单行多列表格（值+标签成组）

    结构：<div class="stat-inline"><div class="item"><div class="v">值</div>
    <div class="l">标签</div></div>…</div>
    输出为无边框单行表格：每项占 2 列（值列 + 标签列），值加粗、标签浅色。
    避免此前 .v/.l 被拍平为逐行零散段落。
    """
    items = [c for c in section.children
             if isinstance(c, Tag) and "item" in (c.get("class") or [])]
    if len(items) < 2:
        return

    text_color = palette.get("text", "1f2d3d")
    label_color = palette.get("text_secondary", "6b7a90")

    # 值+标签成对输出：每项占 2 列（值 | 标签）
    cols = 2 * len(items)
    table = doc.add_table(rows=1, cols=cols)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_table_borders_nil(table)
    set_table_width_percent(table, 100)

    for ci, item in enumerate(items):
        v_el = item.find(class_="v")
        l_el = item.find(class_="l")
        v = get_text_content(v_el) if v_el else ""
        l = get_text_content(l_el) if l_el else ""
        # 值列（加粗 + 主色）
        c_v = table.rows[0].cells[ci * 2]
        p = c_v.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(2)
        p.paragraph_format.space_after = Pt(2)
        if v:
            run = p.add_run(v)
            set_run_font(run, size=Pt(12), bold=True, color=hex_to_rgb(text_color))
        # 标签列（小字号浅色）
        c_l = table.rows[0].cells[ci * 2 + 1]
        p = c_l.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(2)
        if l:
            run = p.add_run(l)
            set_run_font(run, size=Pt(9), color=hex_to_rgb(label_color))

    print(f"[INFO] stat_table: 已输出 {len(items)} 项指标（值+标签成对表格）")
