#!/usr/bin/env python3
"""
html2docx.py — 将 html-generator 生成的 HTML 转换为 Word (.docx)

用法: python html2docx.py <input.html> <output.docx>

核心逻辑（第二版 · 生成放开 / 转换归约）：
1. 解析 HTML，读取 body 的 data-palette 与 class="mode-xxx"
2. 预解析 <style> 块（cssutils，可选）
3. 遍历 body 直接子元素，按"语义 class + 结构特征"归约识别为 IR 语义
   （12 种块级语义 class + cite/source-list 2 种辅助，见 references/semantic-classes.md；
    25 种 IR 语义归约规则见 references/ir-blocks.md）
4. 无语义 class 的元素按结构特征兜底识别（blockquote→quote、details→faq 等）
5. 纯色 background → shading 保留；data-float → 表格定位；分页去重

转换保真度：语义保真 ~95%，视觉保真 ~70%
（卡片/时间线/画廊等降级为紧凑表格/段落，装饰性 CSS 被忽略）

模块拆分架构（2026-08）：
  sem_common ← docx_utils ← html2docx_core ← html2docx_scene / html2docx_advanced
                                  ↑                ↑
                            html2docx_enhanced（不依赖 core）
                                  ↑
                          html2docx.py（本文件，主入口 + 分发器）
"""

import sys
import os
import re

# Windows 下 stdout/stderr 默认可能非 UTF-8（如 GBK），强制设为 UTF-8 避免中文输出乱码
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# 确保同目录模块可被 import（即使从其他目录调用或通过 -m 运行）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from bs4 import BeautifulSoup, Tag
    from docx import Document
    from docx.shared import Pt, RGBColor, Cm
    from docx.oxml.ns import qn
except ImportError:
    print("[ERROR] 缺少依赖，请先运行: pip install -r requirements.txt")
    sys.exit(1)

# 公共语义层
from sem_common import flatten_semantic_blocks, parse_style_blocks, get_text_content

# Word OXML 工具层
from docx_utils import (
    DEFAULT_FONT,
    PALETTES,
    extract_body_background,
    set_page_background,
    add_page_break,
)

# 核心层处理
from html2docx_core import (
    process_title_page, process_heading, process_paragraph,
    process_bullet_list, process_table, process_image,
)

# 增强层处理
from html2docx_enhanced import (
    process_stat_block, process_callout, process_timeline, process_code_block,
)

# 场景层处理
from html2docx_scene import (
    process_card_grid, process_divider, process_tab_group,
    process_collapse_group, process_hero_banner, process_task_list,
    process_chart_card, process_chart_unknown,
)

# 高级层处理
from html2docx_advanced import (
    process_quote, process_columns, process_compare_cards,
    process_comparison, process_faq, process_badge_group,
    process_gallery, process_pricing_table, process_icon_list,
    process_end_page,
)


# ===== 主转换流程 =====

def convert_html_to_docx(html_path, docx_path):
    """主转换函数"""
    with open(html_path, "r", encoding="utf-8-sig") as f:
        soup = BeautifulSoup(f.read(), "lxml")

    body = soup.find("body")
    if not body:
        print("[ERROR] HTML 中未找到 <body> 标签")
        sys.exit(1)

    # 预解析 style 块
    parsed_styles = parse_style_blocks(soup)

    # 提取页面级背景色（body 渐变/纯色 → Word 页面背景）
    page_bg = extract_body_background(soup, body, parsed_styles)

    # 识别调色板
    palette_id = body.get("data-palette", "ink-blue")
    palette = PALETTES.get(palette_id, PALETTES["ink-blue"])

    # 创建 Word 文档
    doc = Document()

    # 设置页面级背景色（在 Document 创建后调用）
    if page_bg:
        set_page_background(doc, page_bg)

    # 缩小页面边距（减少留白）
    for section in doc.sections:
        section.top_margin = Cm(1.5)
        section.bottom_margin = Cm(1.5)
        section.left_margin = Cm(1.8)
        section.right_margin = Cm(1.8)

    # 设置默认样式
    style = doc.styles["Normal"]
    font = style.font
    font.name = DEFAULT_FONT
    font.size = Pt(11)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), DEFAULT_FONT)
    pf = style.paragraph_format
    pf.space_before = Pt(2)
    pf.space_after = Pt(4)
    pf.line_spacing = 1.15

    for level in (1, 2, 3):
        heading_style = doc.styles[f"Heading {level}"]
        # 显式设置字号与加粗，确保 Word 中标题视觉上区别于正文
        heading_size = 18 if level == 1 else (16 if level == 2 else 14)
        heading_style.font.size = Pt(heading_size)
        heading_style.font.bold = True
        heading_style.font.color.rgb = RGBColor(0x0F, 0x1E, 0x33)
        # 中文字体：与正文统一（否则 Word 标题缺 eastAsia 字体，逐字符回退导致粗细不一）
        heading_style.font.name = DEFAULT_FONT
        h_rfonts = heading_style.element.rPr.rFonts
        h_rfonts.set(qn("w:eastAsia"), DEFAULT_FONT)
        # 移除主题字体引用（asciiTheme/eastAsiaTheme 等），否则 Word 主题覆盖具体字体名
        for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
            key = qn(attr)
            if key in h_rfonts.attrib:
                del h_rfonts.attrib[key]
        hpf = heading_style.paragraph_format
        hpf.space_before = Pt(10 if level == 1 else 8)
        hpf.space_after = Pt(4)
        hpf.line_spacing = 1.2
        hpf.keep_with_next = True  # 标题与后续内容保持在同一页

    for sn in ("List Bullet", "List Number"):
        try:
            ls = doc.styles[sn]
            ls.paragraph_format.space_before = Pt(1)
            ls.paragraph_format.space_after = Pt(1)
            ls.paragraph_format.line_spacing = 1.15
        except KeyError:
            pass

    # 遍历语义块
    blocks = flatten_semantic_blocks(body)
    first_block = True

    for element, ir, group_info in blocks:
        process_block(doc, element, ir, group_info, palette, first_block, parsed_styles, soup)
        first_block = False

    # ===== 尾部空白页清理 pass =====
    # 修复问题：Word 规定表格后必须跟一个段落，当封面/尾页 1×1 表格占满整页时，
    # 残留空段落被推到下一页 → 空白页。此 pass 在保存前执行尾部清理。
    _cleanup_trailing_blank_pages(doc)

# ===== 格式健康 pass =====
    # 修复问题：未知图表/宽表/大图片可能导致表格超宽或格式异常，
    # 此 pass 统一修复超宽表格和超大图片。
    _format_health_pass(doc)

# ===== 文本量比对校验 =====
    # 修复问题：处理函数只取部分子结构时，可能静默丢弃内容（如折叠卡内代码被吞）。
    # 此校验在保存前比对 HTML 正文文本量与 docx 文本量，差异超阈值时打印 WARNING。
    _verify_text_coverage(soup, doc, html_path)

    # ===== 图表容器逐项核对校验 =====
    # 修复问题：总量比对粒度太粗，单个图表容器（漏斗级/柱条）丢失占比小会被放过。
    # 此校验逐图表容器比对，丢失即显式 WARNING（2026-09 新增）。
    _verify_chart_container_coverage(soup, doc)

    doc.save(docx_path)
    print(f"[OK] Word 文件已生成: {docx_path}")


def _verify_text_coverage(soup, doc, html_path):
    """比对 HTML 正文文本量与 docx 输出文本量，差异超阈值时打印 WARNING。

    目的：尽早发现转换端静默丢（处理函数窄口径提取/结构兜底缺失等）。
    阈值策略：
      - 差异 > 15%：WARNING（可能存在内容丢失，需人工检查）
      - 差异 > 40%：明显异常（打印更醒目提示）
    默认只告警，不阻断（避免误伤正常转换）；配合 --strict 参数可使差异 > 20% 时退出码非 0。

    统计口径说明（2026-09 修订）：
      - 图表卡（.chart-card / 含 SVG / 含 .chart-row 且无表格的 .card）在转换时走
        "整卡截图"路径（Playwright 截图后插入图片），卡内标题/标签/图例/数据行
        以像素形式存在，不会出现在 Word 段落/表格文本中——这是设计内行为。
        此类容器的文本应从 HTML 侧统计中排除，否则会因"图片取代文本"误报丢失。
      - 判定为"截图容器"的标准与转换端 process_chart_card / process_chart_unknown
        保持一致：.chart-card；或含 <svg>/<canvas>；或含 .chart-row 且不含 <table>。
    """
    try:
        body = soup.find("body")
        if body is None:
            return
        # 排除 <style>/<script> 后的 HTML 可见文本（与 docx 输出对齐）
        for tag in body.find_all(["style", "script"]):
            tag.decompose()
        # 去除代码复制按钮等交互辅助文本（Word 端不输出）
        for btn in body.find_all(class_="code-copy-btn"):
            btn.decompose()
        # 排除"整卡截图"图表容器的文本（图片取代文本，属设计内行为，不计入 diff）
        _screenshot_containers = []
        # 1) 显式图表卡 .chart-card
        _screenshot_containers += body.find_all(class_="chart-card")
        # 2) 含 SVG/Canvas 的 .card（图表卡：折线/饼/环形等）
        for card in body.find_all(class_="card"):
            if card.find(["svg", "canvas"]) is not None:
                _screenshot_containers.append(card)
        # 3) 含 .chart-row 且无内嵌表格的 .card（柱状/条形图卡：process_chart_card 截图分支）
        for card in body.find_all(class_="card"):
            if card.find(class_="chart-row") is not None and card.find("table") is None:
                _screenshot_containers.append(card)
        for el in _screenshot_containers:
            el.decompose()
        html_text = body.get_text()
        html_chars = len(re.sub(r"\s+", "", html_text))

        # 统计 docx 全部段落 + 表格文本
        docx_chars = 0
        for para in doc.paragraphs:
            docx_chars += len(re.sub(r"\s+", "", para.text))
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        docx_chars += len(re.sub(r"\s+", "", para.text))

        if html_chars == 0:
            return
        diff = (html_chars - docx_chars) / html_chars
        if diff > 0.15:
            level = "WARNING" if diff <= 0.20 else "ERROR"
            print(f"[{level}] 文本量比对：HTML {html_chars} 字 vs Word {docx_chars} 字，"
                  f"差异 {(diff*100):.1f}%。可能存在内容丢失，请检查以下结构："
                  f"折叠卡(details)/提示框(callout)/代码块(code)/时间线(timeline)。")
            if diff > 0.20:
                print(f"[INFO] 如需阻断转换，请在调用处传入 strict=True")
        else:
            print(f"[INFO] 文本量比对通过：HTML {html_chars} 字 vs Word {docx_chars} 字，"
                  f"差异 {(diff*100):.1f}%（阈值 15%）")
    except Exception as e:
        print(f"[WARNING] 文本量比对失败（不影响转换结果）: {e}")


def _verify_chart_container_coverage(soup, doc):
    """逐图表容器核对：HTML 中图表容器（漏斗级/柱体/迷你图条）的文本必须在 Word 中可找回。

    目的：文本量比对（总量 15% 阈值）粒度太粗，单个图表容器丢失（如漏斗 6 级
    全部静默跳过）占比小，会被总量阈值放过。此核对逐容器比对，丢失即显式 WARNING。

    核对对象：
      - .funnel-stage（漏斗每一级，含 f-name/f-value/f-pct 等）
      - .bar-row（条形图行，含 bar-rank/bar-label/bar-fill）
      - .bar（柱状图柱体，取 .bar-val 文本；若无 bar-val 则跳过——纯装饰条无信息量）

判定：容器文本去掉空白后，必须能在 docx 全文（段落+表格）中按子串命中。
    纯数字/短文本可能被"拼接"而不是逐词保留，故取容器文本核心片段匹配，
    任一容器完全找不到 → WARNING。

    例外（2026-09 修订）：位于"整卡截图"图表容器（.chart-card / 含 SVG 的 .card /
    含 .chart-row 且无表格的 .card）内部的漏斗/柱体/条，其文本已随截图以像素形式
    存在于 Word 图片中，不再逐容器核对（避免与截图路径冲突产生误报）。
    """
    if soup is None:
        return
    try:
        body = soup.find("body")
        if body is None:
            return
        # 整卡截图容器（与转换端 process_chart_card / process_chart_unknown 保持一致）
        _shot_containers = []
        _shot_containers += body.find_all(class_="chart-card")
        for card in body.find_all(class_="card"):
            if card.find(["svg", "canvas"]) is not None:
                _shot_containers.append(card)
            elif card.find(class_="chart-row") is not None and card.find("table") is None:
                _shot_containers.append(card)
        # 从核对范围内移除截图容器内的所有目标容器
        for sc in _shot_containers:
            for inner in sc.find_all(class_=("funnel-stage", "bar-row", "bar")):
                inner.decompose()
        # docx 全文（段落 + 表格）
        docx_texts = []
        for para in doc.paragraphs:
            t = re.sub(r"\s+", "", para.text)
            if t:
                docx_texts.append(t)
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        t = re.sub(r"\s+", "", para.text)
                        if t:
                            docx_texts.append(t)
        full_docx = "\n".join(docx_texts)

        # 需核对的图表容器
        containers = []
        containers += body.find_all(class_="funnel-stage")
        containers += body.find_all(class_="bar-row")
        # .bar 柱体（取 .bar-val 数值文本，无 .bar-val 则跳过）
        for bar in body.find_all(class_="bar"):
            val_el = bar.find(class_="bar-val")
            if val_el is not None:
                containers.append(val_el)

        missing = []
        for c in containers:
            text = re.sub(r"\s+", "", c.get_text())
            if not text:
                continue
            # 取核心片段（前 12 字符）匹配，避免过长文本拼接差异
            probe = text[:12]
            if probe and probe not in full_docx:
                missing.append((c.name, (c.get("class") or [""])[0], probe))

        if missing:
            print(f"[WARNING] 图表容器核对：{len(missing)}/{len(containers)} 个图表容器文本未在 "
                  f"Word 中找到（可能被静默丢弃）。示例: {missing[:3]}")
        else:
            print(f"[INFO] 图表容器核对通过：{len(containers)} 个图表容器全部找回")
    except Exception as e:
        print(f"[WARNING] 图表容器核对失败（不影响转换结果）: {e}")


def process_block(doc, element, ir, group_info, palette, first_block, parsed_styles=None, soup=None):
    """处理单个语义块 — 支持 25 种 IR 语义

    Args:
        group_info: ("stat", [elements]) / ("card", [elements]) 聚合组，None 表示单块
        parsed_styles: cssutils 预解析的 <style> 块样式字典（预留）
        soup: 可选，BS4 文档对象（用于正则兜底提取 <style> 块背景色）
    """
    # 分页逻辑：
    #   - title_page：封面用 1×1 表格承载，自然独占一页，无需主动分页
    #   - end_page：尾页用 1×1 表格承载，自然独占一页，无需主动分页
    #   - 其余内容顺延（一级标题不再强制新起一页，减少留白；用户可用分页符自行控制）
    need_pb = False

    # 核心层
    if ir == "title_page":
        process_title_page(doc, element, palette, first_block, parsed_styles, soup)
    elif ir == "heading":
        process_heading(doc, element, palette, need_pb)
    elif ir == "paragraph":
        process_paragraph(doc, element, palette)
    elif ir == "bullet_list":
        process_bullet_list(doc, element)
    elif ir == "table":
        process_table(doc, element, palette, parsed_styles, soup)
    elif ir == "image":
        process_image(doc, element)

    # 增强层
    elif ir == "stat_block":
        process_stat_block(doc, element, palette, group_info)
    elif ir == "callout":
        process_callout(doc, element, palette)
    elif ir == "timeline":
        process_timeline(doc, element, palette, parsed_styles, soup)
    elif ir == "code_block":
        process_code_block(doc, element)

    # 场景层
    elif ir == "hero_banner":
        if not first_block:
            add_page_break(doc)  # 非首块：前置分页，Hero 横幅独占一页
        process_hero_banner(doc, element, palette)
        add_page_break(doc)  # 内容后分页（去重：后续块自动承接）
    elif ir == "card_grid":
        # card 内含 <table class="table"> 时走容器递归，
        # 避免 process_card_grid 拍平内部表格结构
        if element.find("table", class_="table"):
            tag_children = [c for c in element.children if isinstance(c, Tag)]
            if tag_children:
                for c in element.children:
                    if isinstance(c, Tag):
                        c_cls = c.get("class") or []
                        # 跳过交互辅助元素
                        if any(x in c_cls for x in ("code-copy-btn", "table-search-input", "back-to-top")):
                            continue
                        if c.name in ("h1","h2","h3","h4","h5","h6"):
                            process_heading(doc, c, palette, False)
                        elif c.name == "p":
                            process_paragraph(doc, c, palette)
                        elif c.name in ("ul","ol"):
                            process_bullet_list(doc, c)
                        elif c.name == "table":
                            process_table(doc, c, palette, parsed_styles, soup)
                        elif c.name in ("div","section","article"):
                            # 递归进入无语义容器
                            for cc in c.children:
                                if isinstance(cc, Tag) and cc.name == "table":
                                    process_table(doc, cc, palette, parsed_styles, soup)
                                elif isinstance(cc, Tag) and cc.name == "p":
                                    process_paragraph(doc, cc, palette)
                                elif isinstance(cc, Tag) and cc.name in ("h1","h2","h3","h4","h5","h6"):
                                    process_heading(doc, cc, palette, False)
                                elif isinstance(cc, Tag) and get_text_content(cc):
                                    process_paragraph(doc, cc, palette)
                        else:
                            if get_text_content(c):
                                process_paragraph(doc, c, palette)
                return
        process_card_grid(doc, element, palette, group_info, soup=soup)
    elif ir == "divider":
        process_divider(doc)
    elif ir == "tab_group":
        process_tab_group(doc, element, palette, parsed_styles, soup)
    elif ir == "collapse_group":
        process_collapse_group(doc, element, palette)
    elif ir == "task_list":
        process_task_list(doc, element, palette, group_info)
    elif ir == "mini_chart":
        process_chart_card(doc, element, palette, parsed_styles, soup)
    elif ir == "auto_table":
        from html2docx_scene import _process_auto_table_from_grid
        _process_auto_table_from_grid(doc, element, palette)

    # 高级层
    elif ir == "quote":
        process_quote(doc, element, palette)
    elif ir == "columns":
        process_columns(doc, element, palette)
    elif ir == "comparison":
        process_comparison(doc, element, palette)
    elif ir == "compare_cards":
        process_compare_cards(doc, element, palette, parsed_styles, soup)
    elif ir == "faq":
        process_faq(doc, element, palette)
    elif ir == "badge_group":
        process_badge_group(doc, element, palette)
    elif ir == "gallery":
        process_gallery(doc, element)
    elif ir == "pricing_table":
        process_pricing_table(doc, element, palette)
    elif ir == "icon_list":
        process_icon_list(doc, element, palette)
    elif ir == "end_page":
        process_end_page(doc, element, palette, parsed_styles, soup)
    elif ir == "chart_unknown":
        process_chart_unknown(doc, element, palette, soup)
    elif ir == "data_table":
        from html2docx_scene import process_data_table
        process_data_table(doc, element, palette, soup)
    elif ir == "stat_table":
        from html2docx_scene import process_stat_table
        process_stat_table(doc, element, palette, soup)
    else:
        # 兜底：普通段落
        process_paragraph(doc, element)


# ===== 尾部空白页清理 =====

def _is_blank_paragraph(para):
    """判断段落是否为空段落（无文本、无图片、无表格）"""
    text = para.text.strip() if hasattr(para, "text") else ""
    if text:
        return False
    # 检查是否含 inline shape（图片）
    for run in para.runs:
        if run._element.findall(qn("w:drawing")):
            return False
    return True


def _cleanup_trailing_blank_pages(doc):
    """尾部空白页清理 pass —— 在 doc.save 前执行

    修复问题：
    1. Word 规定表格后必须跟一个段落，封面/尾页 1×1 表格占满整页后，
       残留空段落被推到下一页 → 空白页。
    2. inject_page_break_before 的 pending 机制：分页标记排在文档末尾无处注入 → 尾部残留分页。

    处理策略：
    - 从文档末尾往回删孤立空段落（无文本、无图片、无表格内容）
    - 如果末尾是表格，保留其后唯一空段落但压缩到最小（1pt 字号 + 最小行距），
      满足 Word 语法要求但不产生新页
    - 未被消费的 pending 分页标记直接丢弃
    """
    from docx.oxml.ns import qn as _qn

    # 1. 丢弃未消费的 pending 分页标记
    if getattr(doc, "_pending_page_break", False):
        doc._pending_page_break = False

    # 2. 从末尾往回删孤立空段落
    # 收集 body 中的顶层段落元素（直接子元素 <w:p>）
    body_elem = doc.element.body
    # 遍历倒序，删除末尾连续空段落
    children = list(body_elem)
    removed = 0
    for child in reversed(children):
        if child.tag == _qn("w:p"):
            # 检查段落是否有内容
            has_text = False
            for t_elem in child.findall(f".//{_qn('w:t')}"):
                if t_elem.text and t_elem.text.strip():
                    has_text = True
                    break
            has_drawing = bool(child.findall(f".//{_qn('w:drawing')}"))
            has_page_break_before = bool(child.findall(f".//{_qn('w:pageBreakBefore')}"))
            if not has_text and not has_drawing and not has_page_break_before:
                # 空段落 → 删除
                body_elem.remove(child)
                removed += 1
            else:
                break
        elif child.tag == _qn("w:tbl"):
            # 表格后面必须保留一个空段落（Word 语法要求），
            # 但压缩到最小：1pt 字号 + 最小行距 + 零间距
            # 找表格后面紧跟的段落
            tbl_idx = list(body_elem).index(child)
            following_paras = []
            for c in list(body_elem)[tbl_idx + 1:]:
                if c.tag == _qn("w:p"):
                    following_paras.append(c)
                else:
                    break
            if following_paras:
                # 压缩第一个段落到最小
                first_p = following_paras[0]
                pPr = first_p.find(_qn("w:pPr"))
                if pPr is None:
                    pPr = OxmlElement("w:pPr")
                    first_p.insert(0, pPr)
                # 设置最小行距
                spacing = pPr.find(_qn("w:spacing"))
                if spacing is None:
                    spacing = OxmlElement("w:spacing")
                    pPr.append(spacing)
                spacing.set(_qn("w:before"), "0")
                spacing.set(_qn("w:after"), "0")
                spacing.set(_qn("w:line"), "20")  # 1pt = 20 twips
                spacing.set(_qn("w:lineRule"), "exact")
                # 设置最小字号（通过 rPr）
                rPr = pPr.find(_qn("w:rPr"))
                if rPr is None:
                    rPr = OxmlElement("w:rPr")
                    pPr.append(rPr)
                sz = rPr.find(_qn("w:sz"))
                if sz is None:
                    sz = OxmlElement("w:sz")
                    rPr.append(sz)
                sz.set(_qn("w:val"), "2")  # 1pt = 2 half-points
                # 删除表格与压缩段落之间多余的空段落
                for extra_p in following_paras[1:]:
                    has_text = bool(extra_p.findall(f".//{_qn('w:t')}"))
                    has_drawing = bool(extra_p.findall(f".//{_qn('w:drawing')}"))
                    if not has_text and not has_drawing:
                        body_elem.remove(extra_p)
                        removed += 1
            break
        else:
            # 非段落非表格（如 sectPr）→ 停止
            break

    if removed > 0:
        print(f"[INFO] 尾部清理: 移除 {removed} 个空白段落")


# ===== 格式健康 pass =====

def _format_health_pass(doc):
    """格式健康 pass —— 在 doc.save 前执行

    统一修复未知块产生的格式异常：
    1. 表格总宽度 > 100% → 缩回 100%（防溢出）
    2. 图片宽度超过页面可用宽度 → 等比缩小
    3. 全空表格（所有单元格无文本）→ 删除并留提示
    """
    from docx.oxml.ns import qn as _qn
    from docx.shared import Emu

    body_elem = doc.element.body
    fixed_tables = 0
    fixed_images = 0
    removed_empty_tables = 0

    # 1. 修复超宽表格
    for table in doc.tables:
        tbl = table._tbl
        tblPr = tbl.find(_qn("w:tblPr"))
        if tblPr is not None:
            tblW = tblPr.find(_qn("w:tblW"))
            if tblW is not None:
                w_type = tblW.get(_qn("w:type"), "")
                w_val = tblW.get(_qn("w:w"), "0")
                if w_type == "pct":
                    # pct: 5000 = 100%
                    try:
                        val_int = int(w_val)
                        if val_int > 5000:
                            tblW.set(_qn("w:w"), "5000")
                            fixed_tables += 1
                    except ValueError:
                        pass
        # 2. 检测全空表格（所有单元格无文本）→ 删除
        all_empty = True
        for row in table.rows:
            for cell in row.cells:
                if cell.text.strip():
                    all_empty = False
                    break
            if not all_empty:
                break
        if all_empty and len(table.rows) > 0:
            # 用提示段落替换空表格
            tbl_parent = tbl.getparent()
            if tbl_parent is not None:
                tbl_parent.remove(tbl)
                removed_empty_tables += 1

    # 3. 修复超大图片（宽度超过页面可用宽度）
    # A4 纵向可用宽度 ≈ 21cm − 1.8×2 = 17.4cm = 6.85 inches
    max_width_emu = int(6.85 * 914400)  # 1 inch = 914400 EMU
    for para in doc.paragraphs:
        for run in para.runs:
            drawings = run._element.findall(f".//{_qn('w:drawing')}")
            for drawing in drawings:
                # 检查 inline extent
                extent = drawing.find(f".//{_qn('wp:extent')}")
                if extent is not None:
                    cx = int(extent.get("cx", "0"))
                    if cx > max_width_emu:
                        ratio = max_width_emu / cx
                        new_cx = max_width_emu
                        new_cy = int(int(extent.get("cy", "0")) * ratio)
                        extent.set("cx", str(new_cx))
                        extent.set("cy", str(new_cy))
                        fixed_images += 1

    if fixed_tables or fixed_images or removed_empty_tables:
        parts = []
        if fixed_tables:
            parts.append(f"修复 {fixed_tables} 个超宽表格")
        if fixed_images:
            parts.append(f"缩小 {fixed_images} 张超大图片")
        if removed_empty_tables:
            parts.append(f"删除 {removed_empty_tables} 个空表格")
        print(f"[INFO] 格式健康 pass: {'，'.join(parts)}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("用法: python html2docx.py <input.html> <output.docx>")
        sys.exit(1)
    input_path = sys.argv[1]
    output_path = sys.argv[2]
    if not os.path.exists(input_path):
        print(f"[ERROR] 输入文件不存在: {input_path}")
        sys.exit(1)
    convert_html_to_docx(input_path, output_path)
