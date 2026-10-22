#!/usr/bin/env python3
"""
html2md.py — 将 html-generator 生成的 HTML 转换为 Markdown (.md)

用法: python html2md.py <input.html> <output.md>

核心逻辑（第二版 · 生成放开 / 转换归约）：
1. 遍历 body，按语义 class + 结构特征归约识别为 IR 语义
2. 按 Markdown 映射输出：
   - title_page → # 标题
   - heading → # / ## / ###
   - paragraph → 正文文本
   - bullet_list → - / 1. 列表
   - table → Markdown 表格
   - image → ![alt](data:...)
   - stat_block → 加粗数字文本
   - callout → > 引用
   - timeline → 有序列表
   - code_block → 围栏代码块
   - card_grid / columns / comparison → 分组标题 + 列表
   - faq → 加粗问题 + 正文
   - divider → ---
   - badge_group → 逗号分隔文本
   - quote → > 引用
   - end_page → 标题 + 致谢文本
3. 以 --- 分隔线切分章节

转换保真度：语义保真 ~90%，视觉样式天然不保留（无需逐项提醒）

依赖：sem_common（公共语义识别层）
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
except ImportError:
    print("[ERROR] 缺少依赖，请先运行: pip install -r requirements.txt")
    sys.exit(1)

# 公共语义识别层（与 html2docx / impact_analyzer 共用同一份逻辑）
from sem_common import (
    flatten_semantic_blocks,
    get_text_content,
    find_semantic_class,
    semantic_children,
    parse_table_data,
    detect_repetitive_grid,
    extract_chart_data,
    is_hidden_chart_label,
)


# ===== 各 IR 类型的 Markdown 渲染 =====

def md_escape(text):
    """转义 Markdown 特殊字符（保留中文/数字/常见符号）

    仅转义行首特殊符号与表格/标题语法字符，避免破坏 Markdown 结构：
    - 行首的 #、>、-、+、*、数字. 等需要转义，防止被解析为标题/列表/引用
    - 表格单元格内的 | 需要转义，防止列结构破坏
    - 普通文本中的 *、_、` 等保留（多数场景可读）
    """
    if not text:
        return text
    # 行首特殊符号转义：仅当后跟空白（或行尾）才可能被解析为标题/列表/引用
    # 数字. 后必须跟空白才是有序列表项（如 "1. 条目"），"1.1" 这类编号标题不转义
    text = re.sub(r"^([#>*+\-](?=\s|$)|\d+\.(?=\s|$))\s*", r"\\\1 ", text, count=1)
    # 表格单元格转义由 md_table 处理，这里只转义行首
    return text


def render_title_page(el, soup=None):
    h1 = el.find("h1")
    title = md_escape(get_text_content(h1) if h1 else get_text_content(el))
    ps = [md_escape(p.get_text(strip=True)) for p in el.find_all("p") if p.get_text(strip=True)]
    lines = []

    # 提取机密信息（page-header / confidential-watermark）→ 封面标题之前输出
    # 这些元素是 body 直接子元素，不在 section.title 内，需要通过 soup 全局查找
    if soup:
        wm = soup.find(class_="confidential-watermark")
        if wm:
            wm_text = md_escape(get_text_content(wm))
            if wm_text:
                lines.append(f"**{wm_text}**")
                lines.append("")
        hdr = soup.find(class_="page-header")
        if hdr:
            hdr_text = md_escape(get_text_content(hdr))
            if hdr_text:
                lines.append(hdr_text)
                lines.append("")

    lines.append(f"# {title}")
    lines.append("")
    for p in ps:
        lines.append(p)
        lines.append("")
    # 提取封面 meta 信息（.title-meta .meta-item）
    meta_items = el.select(".meta-item")
    if meta_items:
        meta_parts = []
        for mi in meta_items:
            value_el = mi.find(class_="value")
            label_el = mi.find(class_="label")
            value = md_escape(get_text_content(value_el)) if value_el else ""
            label = md_escape(get_text_content(label_el)) if label_el else ""
            if value and label:
                meta_parts.append(f"**{value}** {label}")
            elif value:
                meta_parts.append(f"**{value}**")
        if meta_parts:
            lines.append(" | ".join(meta_parts))
            lines.append("")
    return "\n".join(lines)


def render_heading(el):
    is_heading_tag = el.name in ("h1", "h2", "h3")
    tag = el if is_heading_tag else el.find(["h1", "h2", "h3"])
    level = int(el.get("data-level", 1))
    if not el.get("data-level"):
        tag_map = {"h1": 1, "h2": 2, "h3": 3}
        if tag and tag.name in tag_map:
            level = tag_map[tag.name]
    text = md_escape(get_text_content(tag) if tag else get_text_content(el))
    return f"{'#' * level} {text}"


def render_paragraph(el):
    text = md_escape(el.get_text(strip=True))
    return text if text else ""


def _extract_li_text(li):
    """提取 li 的完整文本，保留子元素（如 status-pill）与直接文本节点之间的空格

    避免 get_text(strip=True) 把 span 标签文本和后续正文拼接在一起失去分隔。
    例如：<li><span class="status-pill">已完成</span> 园区 A 区施工</li>
    get_text(strip=True) → "已完成园区 A 区施工"（粘连）
    本函数 → "已完成 园区 A 区施工"（保留空格）
    """
    parts = []
    for child in li.children:
        if isinstance(child, Tag):
            t = child.get_text(strip=True)
            if t:
                parts.append(t)
        elif isinstance(child, str):
            t = child.strip()
            if t:
                parts.append(t)
    # 如果按子节点拼接结果为空，兜底用 get_text
    if not parts:
        return get_text_content(li)
    return " ".join(parts)


def render_bullet_list(el):
    is_list_tag = el.name in ("ul", "ol")
    ul = el if is_list_tag else (el.find("ul") or el.find("ol"))
    if ul is None:
        ul = el
    if ul.name not in ("ul", "ol"):
        ul = None
    lis = ul.find_all("li", recursive=False) if ul else el.find_all("li", recursive=False)
    lines = []
    is_ordered = ul.name == "ol" if ul else False
    for i, li in enumerate(lis, 1):
        text = md_escape(_extract_li_text(li))
        if not text:
            continue
        if is_ordered:
            lines.append(f"{i}. {text}")
        else:
            lines.append(f"- {text}")
    return "\n".join(lines)


def md_table(rows):
    """渲染 Markdown 表格"""
    if not rows:
        return ""
    num_cols = max(len(r) for r in rows)
    # 补齐每行到 num_cols，并转义单元格内的竖线（防止破坏表格结构）
    padded = []
    for r in rows:
        row = list(r) + [""] * (num_cols - len(r))
        row = [c.replace("|", "\\|").replace("\n", "<br>") if c else "" for c in row]
        padded.append(row)
    header = padded[0]
    lines = ["| " + " | ".join(header) + " |"]
    lines.append("| " + " | ".join(["---"] * num_cols) + " |")
    for row in padded[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def render_table(el):
    table_elem = el.find("table") if el.name != "table" else el
    if not table_elem:
        return ""
    rows, _, detail_map = parse_table_data(table_elem)
    caption = el.get("data-caption", "")
    out = []
    if caption:
        out.append(f"**{caption}**")
        out.append("")

    # detail_map: [(after_row_idx, detail_text), ...]
    # after_row_idx 是 rows 中的索引（0 = 表头行或第一行）
    # 在 HTML 中 row-detail 紧跟在对应数据行后面
    # Markdown 表格不支持行间插入文本，所以：
    # 1) 先输出完整表格
    # 2) 再按顺序输出每条 detail，用对应行的第一列值标注
    detail_by_row = {}
    for after_row, text in detail_map:
        detail_by_row.setdefault(after_row, []).append(text)

    out.append(md_table(rows))

    # 输出 row-detail 内容，标注对应行
    if detail_by_row:
        out.append("")
        for after_row, texts in sorted(detail_by_row.items()):
            # 取对应行的第一列值作为标注
            label = rows[after_row][0] if after_row < len(rows) and rows[after_row] else ""
            for detail_text in texts:
                if detail_text:
                    if label:
                        out.append(f"> **{label}** → {detail_text}")
                    else:
                        out.append(f"> {detail_text}")
    return "\n".join(out)


def render_image(el):
    img = el.find("img") if el.name != "img" else el
    if not img:
        return ""
    src = img.get("src", "")
    alt = img.get("alt", "")
    caption = el.get("data-caption", "")
    figcaption = el.find("figcaption")
    if not caption and figcaption:
        caption = get_text_content(figcaption)
    # base64 图片直接引用（data URI）
    out = f"![{alt}]({src})"
    if caption:
        out += f"\n\n*{caption}*"
    return out


def render_stat_block(el, group_info=None):
    cards = []
    if group_info and group_info[0] == "stat":
        for stat_el in group_info[1]:
            divs = stat_el.find_all("div")
            texts = [d.get_text(strip=True) for d in divs if d.get_text(strip=True)]
            value = texts[0] if texts else stat_el.get_text(strip=True)
            label = texts[-1] if len(texts) >= 2 else ""
            cards.append((value, label))
    elif find_semantic_class(el) == "stat":
        divs = el.find_all("div")
        texts = [d.get_text(strip=True) for d in divs if d.get_text(strip=True)]
        value = texts[0] if texts else el.get_text(strip=True)
        label = texts[-1] if len(texts) >= 2 else ""
        cards.append((value, label))
    else:
        for stat_el in semantic_children(el, "stat"):
            divs = stat_el.find_all("div")
            texts = [d.get_text(strip=True) for d in divs if d.get_text(strip=True)]
            value = texts[0] if texts else stat_el.get_text(strip=True)
            label = texts[-1] if len(texts) >= 2 else ""
            cards.append((value, label))
    lines = []
    for value, label in cards:
        lines.append(f"**{md_escape(value)}** {md_escape(label)}")
    return "\n".join(lines)


def render_callout(el):
    text = md_escape(get_text_content(el))
    if not text:
        return ""
    return "> " + text.replace("\n", "\n> ")


def render_chart_card(el):
    """图表卡（trend-card / sparkline-card / chart-row）→ Markdown 结构区块

    迷你图/柱状图在 Markdown 中无法还原，输出为结构化文本：
      - h3 标题 → **加粗**
      - .chart-labels → 标签列表（用 · 分隔）
      - .stat-inline → 指标行（值+说明，用 | 分隔）
      - .note → 说明
    """
    lines = []

    # 标题（h3）
    title_el = el.find("h3")
    title = get_text_content(title_el) if title_el else ""
    if title:
        lines.append(f"**{md_escape(title)}**")
        lines.append("")

    # 图表标签行（.chart-labels）
    labels_el = el.find(class_="chart-labels")
    if labels_el:
        # 隐藏的图表数据标签（aria-hidden / display:none）：浏览器中不可见，
        # 是降级兜底标签，图表截图已覆盖信息，跳过避免重复输出
        if is_hidden_chart_label(labels_el):
            labels_el = None
    if labels_el:
        labels = [get_text_content(s) for s in labels_el.find_all("span", recursive=False)]
        labels = [l for l in labels if l]
        if labels:
            lines.append("· " + " · ".join(md_escape(l) for l in labels))
            lines.append("")

    # 指标行（.stat-inline）
    stat_inline_el = el.find(class_="stat-inline")
    if stat_inline_el:
        items = []
        for item in stat_inline_el.find_all(class_="item", recursive=False):
            v = item.find(class_="v")
            l = item.find(class_="l")
            v_text = get_text_content(v) if v else ""
            l_text = get_text_content(l) if l else ""
            if v_text and l_text:
                items.append(f"{md_escape(v_text)} {md_escape(l_text)}")
            elif v_text:
                items.append(md_escape(v_text))
        if items:
            lines.append(" | ".join(items))
            lines.append("")

    # 说明（.note）
    note = el.find(class_="note")
    if note:
        note_text = get_text_content(note)
        if note_text:
            lines.append(md_escape(note_text))
            lines.append("")

    # 内嵌 <table>（如各渠道 GMV 明细表）
    inner_table = el.find("table")
    if inner_table:
        table_md = render_table(inner_table)
        if table_md:
            lines.append(table_md)
            lines.append("")

    return "\n".join(lines).strip()


def render_chart_unknown(el):
    """未知图表/图形容器 → Markdown 结构化输出

    复用 sem_common.extract_chart_data 提取数据（SVG text/rect 属性 → data-value/data-label
    → CSS height% → 递归文本），按数据维度输出：
    - 多列数据 → Markdown 表格
    - 单列数据 → Markdown 列表
    - 零文本零数据 → 返回空（跳过纯装饰元素）

    避免此前命中 chart_unknown 后走 render_paragraph 拍平导致文本粘连或整块丢失。
    """
    # 提取标题（如容器内有 h3/h4）
    lines = []
    title_el = el.find(["h3", "h4"])
    title = get_text_content(title_el) if title_el else ""
    if title:
        lines.append(f"**{md_escape(title)}**")
        lines.append("")

    # 提取数据
    data_items = extract_chart_data(el)

    if not data_items:
        # 零文本零数据 → 纯装饰元素，跳过
        return ""

    # 多列数据 → Markdown 表格；单列 → 列表
    if len(data_items) > 1 and any(len(item) > 1 for item in data_items):
        rows = []
        for item in data_items:
            rows.append([md_escape(str(cell)) for cell in item])
        lines.append(md_table(rows))
    else:
        for item in data_items:
            line = "  ".join(md_escape(str(x)) for x in item if x)
            if line:
                lines.append(f"- {line}")

    return "\n".join(lines).strip()


def render_timeline(el):
    lis = el.find_all("li")
    lines = []
    for i, li in enumerate(lis, 1):
        # 时间元素查找（优先级与 Word 端一致）：strong → .tl-year → .time → .date
        time_el = li.find("strong")
        if not time_el or not get_text_content(time_el):
            time_el = li.find(class_="tl-year")
        if not time_el or not get_text_content(time_el):
            time_el = li.find(class_="time")
        if not time_el or not get_text_content(time_el):
            time_el = li.find(class_="date")
        time_text = get_text_content(time_el) if time_el else ""
        desc = li.get_text(strip=True)
        # 只删除开头的 strong 时间文本，避免误删正文中的相同子串
        if time_text and desc.startswith(time_text):
            desc = desc[len(time_text):].strip()
        # 去除装饰性箭头符号（折叠按钮 ▶ 等）
        desc = re.sub(r"[▶▸►›]", "", desc).strip()
        desc = md_escape(desc)
        if time_text:
            lines.append(f"{i}. **{md_escape(time_text)}** {desc}")
        else:
            lines.append(f"{i}. {desc}")
    if not lines:
        return ""
    return "\n".join(lines)


def render_code_block(el):
    code = el.find("code") or el.find("pre")
    if not code:
        return ""
    text = code.get_text()
    lang = el.get("data-lang", "")
    return f"```{lang}\n{text.rstrip()}\n```"


def _extract_card_info(card_el):
    """从单个卡片元素提取标题、正文、列表项（与 Word 端 _collect_cards 对齐）"""
    h3 = card_el.find("h3") or card_el.find("h4") or card_el.find("strong")
    title = get_text_content(h3) if h3 else ""
    p = card_el.find("p")
    content = get_text_content(p) if p else ""
    if not content and h3 and not card_el.find(["ul", "ol"]):
        # 无 p 段落且无列表时，才取整体文本做兜底；有列表时 content 留空，列表项由 content_list 输出
        content = card_el.get_text(strip=True).replace(title, "").strip()
    # 收集 ul/ol 列表项（完整保留，避免丢失）
    content_list = []
    for ul in card_el.find_all(["ul", "ol"]):
        for li in ul.find_all("li", recursive=False):
            t = get_text_content(li)
            if t:
                content_list.append(t)
    return title, content, content_list


def render_card_grid(el, group_info=None):
    cards = []
    if group_info and group_info[0] == "card":
        for card_el in group_info[1]:
            cards.append(_extract_card_info(card_el))
    elif find_semantic_class(el) == "card":
        cards.append(_extract_card_info(el))
    else:
        for card_el in semantic_children(el, "card"):
            cards.append(_extract_card_info(card_el))
    lines = []
    for title, content, content_list in cards:
        if title:
            lines.append(f"**{md_escape(title)}**")
        if content:
            lines.append(md_escape(content))
        # 卡片内列表项：逐行输出为 Markdown 列表项（完整保留，避免内容丢失）
        for item in content_list:
            lines.append(f"- {md_escape(item)}")
        lines.append("")
    return "\n".join(lines).strip()


def render_task_list(el, group_info=None):
    """任务卡片列表（.task-item）→ 加粗标题 + 描述 + 难度标注

    Markdown 无卡片概念，输出为紧凑文本行：
      **1. Word：制作个人简历**（入门）
      用 Word 制作一份一页纸的个人简历……
    """
    # 收集任务卡片：
    #   - group_info 提供完整列表（连续同级 .task-item 合并场景）
    #   - el 自身是 .task-item → 单个
    #   - 否则取其直接子元素中的 .task-item，再递归兜底
    items = []
    if group_info and group_info[0] == "task":
        items = list(group_info[1])
    elif "task-item" in (el.get("class") or []):
        items = [el]
    else:
        items = [c for c in el.children if isinstance(c, Tag)
                 and "task-item" in (c.get("class") or [])]
        if not items:
            items = el.find_all(class_="task-item")
    lines = []
    for item in items:
        num = get_text_content(item.find(class_="task-num")) if item.find(class_="task-num") else ""
        title = get_text_content(item.find(class_="task-title")) if item.find(class_="task-title") else ""
        desc = get_text_content(item.find(class_="task-desc")) if item.find(class_="task-desc") else ""
        lvl = get_text_content(item.find(class_="task-level")) if item.find(class_="task-level") else ""
        head = f"**{num}. {title}**" if num else f"**{title}**"
        if lvl:
            head += f"（{lvl}）"
        lines.append(head)
        if desc:
            lines.append(md_escape(desc))
        lines.append("")
    return "\n".join(lines).strip()


def render_quote(el):
    ps = el.find_all("p")
    if ps:
        body = md_escape(get_text_content(ps[0]))
        lines = ["> " + body.replace("\n", "\n> ")]
        if len(ps) >= 2 and get_text_content(ps[1]):
            lines.append("")
            lines.append(f"> — {md_escape(get_text_content(ps[1]))}")
        return "\n".join(lines)
    body = md_escape(get_text_content(el))
    return "> " + body.replace("\n", "\n> ") if body else ""


def render_divider(el):
    return "---"


def render_columns(el):
    cols = [c for c in el.children if isinstance(c, Tag) and c.get_text(strip=True)]
    lines = []
    for i, col in enumerate(cols, 1):
        lines.append(f"**栏 {i}**")
        lines.append(md_escape(col.get_text(strip=True)))
        lines.append("")
    return "\n".join(lines).strip()


def render_comparison(el):
    sides = [c for c in el.children if isinstance(c, Tag) and c.get_text(strip=True)]
    lines = []
    if len(sides) >= 2:
        lines.append("**对比**")
        lines.append("")
        for i, side in enumerate(sides[:2], 1):
            lines.append(f"**方案 {i}**")
            lines.append(md_escape(side.get_text(strip=True)))
            lines.append("")
        return "\n".join(lines).strip()
    table_elem = el.find("table")
    if table_elem:
        rows, _, _detail = parse_table_data(table_elem)
        return md_table(rows)
    return ""


def render_faq(el):
    lines = []
    details = el.find("details")
    if details:
        summary = details.find("summary")
        if summary:
            lines.append(f"**{md_escape(get_text_content(summary))}**")
        body = details.get_text(strip=True).replace(get_text_content(summary) if summary else "", "").strip()
        if body:
            lines.append(md_escape(body))
        return "\n".join(lines)
    ps = el.find_all("p")
    for p in ps:
        text = md_escape(get_text_content(p))
        if not text:
            continue
        if text.startswith("Q:") or text.startswith("问"):
            lines.append(f"**{text}**")
        else:
            lines.append(text)
    return "\n".join(lines)


def render_badge_group(el):
    spans = el.find_all("span")
    texts = [md_escape(get_text_content(s)) for s in spans if get_text_content(s)]
    if not texts:
        texts = [t for t in get_text_content(el).split("、") if t.strip()]
    return "、".join(texts)


def render_gallery(el):
    lines = []
    for img in el.find_all("img"):
        src = img.get("src", "")
        alt = img.get("alt", "")
        lines.append(f"![{alt}]({src})")
        fig = img.find_parent("figure")
        if fig:
            cap = fig.find("figcaption")
            if cap and get_text_content(cap):
                lines.append(f"*{get_text_content(cap)}*")
    return "\n\n".join(lines)


def render_icon_list(el):
    lis = el.find_all("li")
    lines = []
    if lis:
        for li in lis:
            text = md_escape(get_text_content(li))
            if text:
                lines.append(f"- {text}")
    else:
        for p in el.find_all("p"):
            text = md_escape(get_text_content(p))
            if text:
                lines.append(f"- {text}")
    return "\n".join(lines)


def render_hero_banner(el):
    """Hero 横幅 → # 标题（与 title_page 相同的 Markdown 输出）"""
    h1 = el.find("h1")
    title = md_escape(get_text_content(h1) if h1 else get_text_content(el))
    ps = [md_escape(p.get_text(strip=True)) for p in el.find_all("p") if p.get_text(strip=True)]
    lines = [f"# {title}", ""]
    for p in ps:
        lines.append(p)
        lines.append("")
    # 提取封面 meta 信息（.title-meta .meta-item）
    meta_items = el.select(".meta-item")
    if meta_items:
        meta_parts = []
        for mi in meta_items:
            value_el = mi.find(class_="value")
            label_el = mi.find(class_="label")
            value = md_escape(get_text_content(value_el)) if value_el else ""
            label = md_escape(get_text_content(label_el)) if label_el else ""
            if value and label:
                meta_parts.append(f"**{value}** {label}")
            elif value:
                meta_parts.append(f"**{value}**")
        if meta_parts:
            lines.append(" | ".join(meta_parts))
            lines.append("")
    return "\n".join(lines)


def _render_panel_content(panel):
    """渲染 Tab 面板内容：按子元素类型分发到对应的 Markdown 渲染函数

    面板内常见子元素：h3 标题、p 段落、ul/ol 列表、table 表格、div 卡片等。
    不再退化为纯文本，保留 Markdown 结构（列表/表格/代码块等）。
    跳过交互辅助元素（搜索框/无结果提示/复制按钮等），仅输出实际内容。
    """
    SKIP_CLASSES = ("table-search-input", "table-no-result", "code-copy-btn", "back-to-top")

    def _skip(child):
        if is_hidden_chart_label(child):
            return True
        cls = child.get("class") or []
        return any(c in cls for c in SKIP_CLASSES)

    lines = []
    for child in panel.children:
        if not isinstance(child, Tag):
            continue
        if _skip(child):
            continue
        name = child.name or ""
        # h1-h4 标题
        if name in ("h1", "h2", "h3", "h4"):
            text = md_escape(get_text_content(child))
            if text:
                level = {"h1": 1, "h2": 2, "h3": 3, "h4": 4}[name]
                lines.append(f"{'#' * level} {text}")
                lines.append("")
        # 段落
        elif name == "p":
            text = md_escape(get_text_content(child))
            if text:
                lines.append(text)
                lines.append("")
        # 列表
        elif name in ("ul", "ol"):
            rendered = render_bullet_list(child)
            if rendered:
                lines.append(rendered)
                lines.append("")
        # 表格
        elif name == "table":
            rendered = render_table(child)
            if rendered:
                lines.append(rendered)
                lines.append("")
        # 代码块
        elif name == "pre" or child.find("code"):
            rendered = render_code_block(child)
            if rendered:
                lines.append(rendered)
                lines.append("")
        # 提示/警告块（callout）
        elif name == "aside" or "callout" in (child.get("class") or []):
            rendered = render_callout(child)
            if rendered:
                lines.append(rendered)
                lines.append("")
        # div 容器（如 .table-wrap / .card 等）→ 递归查找内部表格/列表/段落
        elif name == "div":
            inner_table = child.find("table")
            if inner_table:
                rendered = render_table(inner_table)
                if rendered:
                    lines.append(rendered)
                    lines.append("")
            else:
                # 递归遍历 div 内部子元素
                sub_lines = []
                for sub in child.children:
                    if not isinstance(sub, Tag):
                        continue
                    if is_hidden_chart_label(sub):
                        continue
                    sub_name = sub.name or ""
                    if sub_name in ("h1", "h2", "h3", "h4"):
                        text = md_escape(get_text_content(sub))
                        if text:
                            level = {"h1": 1, "h2": 2, "h3": 3, "h4": 4}[sub_name]
                            sub_lines.append(f"{'#' * level} {text}")
                            sub_lines.append("")
                    elif sub_name == "p":
                        text = md_escape(get_text_content(sub))
                        if text:
                            sub_lines.append(text)
                            sub_lines.append("")
                    elif sub_name in ("ul", "ol"):
                        rendered = render_bullet_list(sub)
                        if rendered:
                            sub_lines.append(rendered)
                            sub_lines.append("")
                    elif sub_name == "table":
                        rendered = render_table(sub)
                        if rendered:
                            sub_lines.append(rendered)
                            sub_lines.append("")
                    elif sub_name == "pre" or (sub.find("code") and sub_name == "pre"):
                        rendered = render_code_block(sub)
                        if rendered:
                            sub_lines.append(rendered)
                            sub_lines.append("")
                    elif sub_name == "aside" or "callout" in (sub.get("class") or []):
                        rendered = render_callout(sub)
                        if rendered:
                            sub_lines.append(rendered)
                            sub_lines.append("")
                    elif sub_name == "div":
                        # 深层嵌套 div → 取文本兜底
                        text = md_escape(get_text_content(sub))
                        if text:
                            sub_lines.append(text)
                            sub_lines.append("")
                if sub_lines:
                    lines.extend(sub_lines)
    return "\n".join(lines).strip()


def render_tab_group(el):
    """Tab 切换组 → 各 Tab 标题 + 内容展开（Markdown 无 Tab 交互）"""
    tab_nav = el if "tab-nav" in (el.get("class") or []) else el.find(class_="tab-nav")
    if tab_nav is None:
        tab_nav = el
    btns = tab_nav.find_all("button", class_="tab-btn") if tab_nav else []
    # 面板：取 tab-nav 之后连续的兄弟 .tab-panel
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
        panels = el.find_all(class_="tab-panel")
    lines = []
    if not btns:
        for panel in panels:
            panel_md = _render_panel_content(panel)
            if panel_md:
                lines.append(panel_md)
                lines.append("")
    else:
        for i, btn in enumerate(btns):
            btn_text = md_escape(get_text_content(btn))
            lines.append(f"**{btn_text}**")
            lines.append("")
            if i < len(panels):
                panel_md = _render_panel_content(panels[i])
                if panel_md:
                    lines.append(panel_md)
                    lines.append("")
            lines.append("")
    return "\n".join(lines).strip()


def render_auto_table(el):
    """通用重复网格（auto_table）→ Markdown 表格

    复用 _render_demo_grid_md 的构建逻辑：detect_repetitive_grid 已验证
    行结构一致性，直接按其列数切片为 Markdown 表格。
    """
    result = detect_repetitive_grid(el)
    if not result:
        return ""
    num_cols, rows_data = result
    rows = []
    for row in rows_data:
        rows.append([get_text_content(c) if c else "" for c in row])
    return md_table(rows)


def render_stat_table(el):
    """stat-inline 指标行（stat_table）→ Markdown 表格

    结构：<div class="stat-inline"><div class="item"><div class="v">值</div>
    <div class="l">标签</div></div>…</div>
    输出 2 列（值+说明）表格，避免 .v/.l 被拍平成零散段落。
    """
    items = [c for c in el.children if isinstance(c, Tag) and "item" in (c.get("class") or [])]
    rows = []
    for item in items:
        v_el = item.find(class_="v")
        l_el = item.find(class_="l")
        v = get_text_content(v_el) if v_el else ""
        l = get_text_content(l_el) if l_el else ""
        rows.append([v, l])
    if not rows:
        return ""
    return md_table(rows)


def _render_collapse_body_md(body):
    """结构化展开折叠体正文为 Markdown（段落/列表/表格/demo-grid/flex表格）

    穿透无语义包装层（.collapse-body-inner / .demo-mockup / .demo-content 等），
    遇到 demo-grid → Markdown 表格，遇到 flex 表格容器 → Markdown 表格。
    """
    lines = []
    for child in body.children:
        if not isinstance(child, Tag):
            continue
        child_classes = child.get("class") or []

        # demo-grid → Markdown 表格
        if "demo-grid" in child_classes:
            md = _render_demo_grid_md(child)
            if md:
                lines.append(md)
                lines.append("")
            continue

        # 通用重复网格检测（兜底）：未识别 div 含规律性重复行列 → auto_table
        if child.name == "div" and find_semantic_class(child) is None \
           and detect_repetitive_grid(child) is not None:
            md = render_auto_table(child)
            if md:
                lines.append(md)
                lines.append("")
            continue

        # 穿透无语义包装层（.collapse-body-inner / .demo-mockup / .demo-content / 裸 div[style]）
        if child.name == "div" and find_semantic_class(child) is None \
           and "impact-grid" not in child_classes \
           and "rootcause-direct" not in child_classes \
           and "rootcause-deep" not in child_classes \
           and "demo-grid" not in child_classes:
            # flex 表格容器识别
            if _is_flex_table_container_md(child):
                md = _render_flex_table_md(child)
                if md:
                    lines.append(md)
                    lines.append("")
            else:
                inner = _render_collapse_body_md(child)
                if inner:
                    lines.append(inner)
                    lines.append("")
            continue

        if child.name == "p":
            text = get_text_content(child)
            if text:
                lines.append(md_escape(text))
                lines.append("")
        elif child.name in ("ul", "ol"):
            for li in child.find_all("li", recursive=False):
                text = get_text_content(li)
                if text:
                    lines.append(f"- {md_escape(text)}")
            lines.append("")
        elif child.name == "table":
            rows, _, _detail = parse_table_data(child)
            if rows:
                lines.append(md_table(rows))
                lines.append("")
        elif child.name in ("h3", "h4"):
            text = get_text_content(child)
            if text:
                lines.append(f"**{md_escape(text)}**")
                lines.append("")
        else:
            text = get_text_content(child)
            if text:
                lines.append(md_escape(text))
                lines.append("")
    return "\n".join(lines).strip()


def _render_demo_grid_md(element):
    """demo-grid → Markdown 表格"""
    cells = [c for c in element.children if isinstance(c, Tag) and "demo-cell" in (c.get("class") or [])]
    if not cells:
        cells = element.find_all(class_="demo-cell", recursive=False)
    if not cells:
        return ""
    # 解析列数
    num_cols = None
    style = element.get("style", "")
    for part in style.split(";"):
        part = part.strip()
        if part.startswith("grid-template-columns"):
            val = part.split(":", 1)[1].strip()
            num_cols = len(val.split())
            break
    if not num_cols or num_cols < 2:
        total = len(cells)
        for n in [4, 3, 5, 2, 6]:
            if total % n == 0:
                num_cols = n
                break
        if not num_cols:
            num_cols = 4
    rows = []
    for i in range(0, len(cells), num_cols):
        row = [get_text_content(cells[i + j]) if i + j < len(cells) else "" for j in range(num_cols)]
        rows.append(row)
    return md_table(rows)


def _is_flex_table_container_md(element):
    """判断裸 div 是否为 flex 表格容器（Markdown 端，与 Word 端逻辑一致）"""
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


def _render_flex_table_md(container):
    """flex 表格容器 → Markdown 表格"""
    rows = []
    for row_div in container.children:
        if not isinstance(row_div, Tag) or row_div.name != "div":
            continue
        spans = [s for s in row_div.children if isinstance(s, Tag) and s.name == "span"]
        texts = [get_text_content(s) for s in spans]
        if texts:
            rows.append(texts)
    return md_table(rows) if rows else ""


def render_collapse_group(el):
    """折叠展开 → 标题 + 正文结构化展开（Markdown 无折叠交互）

    支持折叠体内嵌套的 demo-grid / flex 表格 → Markdown 表格输出；
    段落/列表/原生 table 也结构化输出，避免整体拍平。
    """
    items = el.find_all(class_="collapse-item")
    lines = []
    for item in items:
        trigger = item.find(class_="collapse-trigger")
        body = item.find(class_="collapse-body")
        title = get_text_content(trigger) if trigger else ""
        title = re.sub(r"[▶▸►›>]", "", title).strip()
        if title:
            lines.append(f"**{md_escape(title)}**")
            lines.append("")
        if body:
            # 穿透 .collapse-body-inner 包装层
            inner = body.find(class_="collapse-body-inner")
            target = inner if inner else body
            body_md = _render_collapse_body_md(target)
            if body_md:
                lines.append(body_md)
                lines.append("")
    return "\n".join(lines).strip()


def render_compare_cards(el):
    """并排对比卡片 → 各卡片标题 + 内容分行"""
    cards = [c for c in el.children if isinstance(c, Tag)
             and "compare-card" in (c.get("class") or [])]
    lines = []
    for i, card in enumerate(cards, 1):
        tagline = card.find(class_="tagline")
        h3 = card.find("h3")
        ps = card.find_all("p")
        if tagline:
            lines.append(f"**{md_escape(get_text_content(tagline))}**")
        if h3:
            lines.append(f"### {md_escape(get_text_content(h3))}")
            lines.append("")
        for p in ps:
            text = md_escape(get_text_content(p))
            if text:
                lines.append(text)
        lines.append("")
    return "\n".join(lines).strip()


def render_pricing_table(el):
    """定价/方案对比表 → Markdown 表格"""
    table_elem = el.find("table") if el.name != "table" else el
    if not table_elem:
        return ""
    rows, _, _detail = parse_table_data(table_elem)
    caption = el.get("data-caption", "")
    out = []
    if caption:
        out.append(f"**{caption}**")
        out.append("")
    out.append(md_table(rows))
    return "\n".join(out)


def render_end_page(el):
    h1 = el.find("h1")
    lines = []
    if h1:
        lines.append(f"# {md_escape(get_text_content(h1))}")
        lines.append("")
    for p in el.find_all("p"):
        text = md_escape(get_text_content(p))
        if text:
            lines.append(text)
            lines.append("")
    # 尾页 meta 信息（.title-meta .meta-item，如复盘人/日期/报告编号），复用封面格式
    meta_items = el.select(".meta-item")
    if meta_items:
        meta_parts = []
        for mi in meta_items:
            value_el = mi.find(class_="value")
            label_el = mi.find(class_="label")
            value = md_escape(get_text_content(value_el)) if value_el else ""
            label = md_escape(get_text_content(label_el)) if label_el else ""
            if value and label:
                meta_parts.append(f"**{value}** {label}")
            elif value:
                meta_parts.append(f"**{value}**")
        if meta_parts:
            lines.append(" | ".join(meta_parts))
            lines.append("")
    return "\n".join(lines).strip()


def render_block(el, ir, group_info=None, soup=None):
    """按 IR 类型渲染 Markdown

    Args:
        soup: BeautifulSoup 文档对象（仅 title_page 需要，用于全局查找 page-header/watermark）
    """
    handlers = {
        "title_page": render_title_page,
        "heading": render_heading,
        "paragraph": render_paragraph,
        "bullet_list": render_bullet_list,
        "table": render_table,
        "image": render_image,
        "stat_block": render_stat_block,
        "callout": render_callout,
        "timeline": render_timeline,
        "code_block": render_code_block,
        "hero_banner": render_hero_banner,
        "card_grid": render_card_grid,
        "divider": render_divider,
        "tab_group": render_tab_group,
        "collapse_group": render_collapse_group,
        "task_list": render_task_list,
        "mini_chart": render_chart_card,
        "auto_table": render_auto_table,
        "stat_table": render_stat_table,
        "compare_cards": render_compare_cards,
        "quote": render_quote,
        "columns": render_columns,
        "comparison": render_comparison,
        "faq": render_faq,
        "badge_group": render_badge_group,
        "gallery": render_gallery,
        "pricing_table": render_pricing_table,
        "icon_list": render_icon_list,
        "end_page": render_end_page,
        "chart_unknown": render_chart_unknown,
    }
    handler = handlers.get(ir)
    if not handler:
        return render_paragraph(el)
    if ir == "title_page":
        return handler(el, soup=soup)
    return handler(el, group_info) if ir in ("stat_block", "card_grid", "task_list") else handler(el)


def convert_html_to_md(html_path, md_path):
    with open(html_path, "r", encoding="utf-8-sig") as f:
        soup = BeautifulSoup(f.read(), "lxml")

    body = soup.find("body")
    if not body:
        print("[ERROR] HTML 中未找到 <body> 标签")
        sys.exit(1)

    blocks = flatten_semantic_blocks(body)
    lines = []
    prev_ir = None
    for el, ir, group_info in blocks:
        rendered = render_traced(el, ir, group_info, soup=soup)
        if not rendered.strip():
            continue
        # Markdown 分页规则：以 --- 分隔线切分章节
        # title_page 后、连续 heading 后不重复插入分隔线
        if ir == "heading":
            level = int(el.get("data-level", 1))
            if level == 1 and prev_ir not in ("title_page", "heading"):
                lines.append("---")
                lines.append("")
        lines.append(rendered)
        lines.append("")
        prev_ir = ir

    # 去除首尾多余空行
    md_text = "\n".join(lines).strip() + "\n"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_text)
    print(f"[OK] Markdown 文件已生成: {md_path}")

    # ===== 文本完整度自检（只警告不阻断，不修改输出）=====
    # 对比 HTML 全文词数与 MD 全文词数，差异超 30% 时警告
    _check_text_integrity(soup, md_text)


def _check_text_integrity(soup, md_text):
    """文本完整度自检：HTML 全文词数 vs MD 全文词数，差异超阈值时警告

    只警告不阻断，不修改已生成的 MD 文件。
    阈值 30%：Markdown 天然丢弃视觉元素（SVG path 坐标、CSS 装饰文本等），
    少量差异属正常行为；超过 30% 可能意味着有语义内容被遗漏。
    """
    # 提取 HTML body 纯文本（排除 style/script 标签）
    body = soup.find("body")
    if not body:
        return
    for tag in body.find_all(["style", "script"]):
        tag.extract()
    html_text = body.get_text(separator=" ", strip=True)
    # 提取 MD 纯文本（去掉 Markdown 语法符号）
    md_plain = re.sub(r'[#|>\-`*_\[\]()]', " ", md_text)
    md_plain = re.sub(r"\s+", " ", md_plain).strip()

    # 按中文字符 + 英文单词计数
    html_words = re.findall(r'[\u4e00-\u9fff]|[a-zA-Z]+|\d+', html_text)
    md_words = re.findall(r'[\u4e00-\u9fff]|[a-zA-Z]+|\d+', md_plain)

    if not html_words:
        return

    html_count = len(html_words)
    md_count = len(md_words)
    loss_ratio = 1.0 - (md_count / html_count) if html_count > 0 else 0.0

    if loss_ratio > 0.30:
        print(f"[WARN] 文本完整度自检：HTML {html_count} 词 → MD {md_count} 词，"
              f"丢失率 {loss_ratio:.0%}（超 30% 阈值），可能存在内容遗漏，请检查")


def render_traced(el, ir, group_info, soup=None):
    """带类型追踪的渲染分发（便于处理 heading level=1 分页）"""
    return render_block(el, ir, group_info, soup=soup)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("用法: python html2md.py <input.html> <output.md>")
        sys.exit(1)
    input_path = sys.argv[1]
    output_path = sys.argv[2]
    if not os.path.exists(input_path):
        print(f"[ERROR] 输入文件不存在: {input_path}")
        sys.exit(1)
    convert_html_to_md(input_path, output_path)
