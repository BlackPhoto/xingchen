#!/usr/bin/env python3
"""
docx_utils.py — Word OXML 工具层

从 html2docx.py 中提取的 Word 文档操作工具函数。
包含字体检测、调色板加载、颜色解析、OXML 操作等底层工具。

被以下模块 import：
- html2docx.py（主入口）
- html2docx_core.py / html2docx_enhanced.py / html2docx_scene.py / html2docx_advanced.py
"""

import os
import re
import json
import platform

from docx.shared import RGBColor
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

# 从 sem_common 导入 cssutils 可用性标志和 parse_style_blocks
from sem_common import HAS_CSSUTILS


# ===== 跨平台字体适配 =====

def _detect_default_font():
    """根据操作系统选择默认正文字体"""
    system = platform.system()
    if system == "Darwin":
        return "PingFang SC"
    elif system == "Linux":
        return "Noto Sans SC"
    else:  # Windows 及其他
        return "Microsoft YaHei"


def _detect_code_font():
    """根据操作系统选择默认代码字体"""
    system = platform.system()
    if system == "Darwin":
        return "SF Mono"
    elif system == "Linux":
        return "Source Code Pro"
    else:  # Windows
        return "Consolas"


DEFAULT_FONT = _detect_default_font()
CODE_FONT = _detect_code_font()


# ===== 调色板（与 references/palettes.json 对应，运行时可动态读取） =====
# 仅保留转换所需的关键色位（primary/accent/bg），完整 20 色位见 palettes.json
_PALETTE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "references")


def load_palettes():
    """读取 references/palettes.json；失败时回退内置默认色值"""
    default = {
        "ink-blue": {"primary": "0f1e33", "accent": "3b82f6", "bg": "f4f7fb",
                     "primary_light": "dbe7f6", "accent_light": "e8f0fe",
                     "text": "1f2d3d", "text_secondary": "5b6b80",
                     "border": "dbe4ef", "card": "ffffff"},
        "warm-gold": {"primary": "5d4a1e", "accent": "c9991f", "bg": "faf7ef",
                      "primary_light": "f2e6cd", "accent_light": "faf0d5",
                      "text": "3d3225", "text_secondary": "6b5e50",
                      "border": "e8dcbf", "card": "ffffff"},
        "teal": {"primary": "0e6b57", "accent": "14b8a6", "bg": "f1faf7",
                 "primary_light": "d6f0e8", "accent_light": "e0f7f3",
                 "text": "134e4a", "text_secondary": "5b8a85",
                 "border": "cdeee7", "card": "ffffff"},
        "rose": {"primary": "7f1d3d", "accent": "e05a76", "bg": "fbf3f6",
                 "primary_light": "f9dbe4", "accent_light": "fde8ed",
                 "text": "5f1d33", "text_secondary": "9c7280",
                 "border": "f3d7de", "card": "ffffff"},
        "navy-gold": {"primary": "1c2f4a", "accent": "b79a4a", "bg": "f6f5f0",
                      "primary_light": "dde6f0", "accent_light": "f6efd9",
                      "text": "1e2c3c", "text_secondary": "6b7a90",
                      "border": "d9dccb", "card": "ffffff"},
        "violet": {"primary": "4c2f86", "accent": "8b5cf6", "bg": "f7f4fc",
                   "primary_light": "e8dff7", "accent_light": "efe9fc",
                   "text": "3b2a55", "text_secondary": "7c6a93",
                   "border": "e3daf2", "card": "ffffff"},
        "orange": {"primary": "8c3a10", "accent": "f97316", "bg": "fdf5ee",
                   "primary_light": "f9e2cc", "accent_light": "fdeedb",
                   "text": "5c2d10", "text_secondary": "a8826e",
                   "border": "f4dcc4", "card": "ffffff"},
        "mono": {"primary": "22262b", "accent": "6b7280", "bg": "f7f7f5",
                 "primary_light": "ececea", "accent_light": "f0f0ee",
                 "text": "27272a", "text_secondary": "71717a",
                 "border": "e4e2dd", "card": "ffffff"},
    }
    try:
        with open(os.path.join(_PALETTE_DIR, "palettes.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
        result = {}
        for p in data.get("palettes", []):
            pid = p.get("id")
            result[pid] = {
                "primary": p.get("primary", "").lstrip("#"),
                "accent": p.get("accent", "").lstrip("#"),
                "bg": p.get("bg", "").lstrip("#"),
                "primary_light": p.get("primary_light", "").lstrip("#"),
                "accent_light": p.get("accent_light", "").lstrip("#"),
                "text": p.get("text", "").lstrip("#"),
                "text_secondary": p.get("text_secondary", "").lstrip("#"),
                "border": p.get("border", "").lstrip("#"),
                "card": p.get("card", "").lstrip("#"),
            }
        if result:
            return result
    except Exception:
        pass
    return default


PALETTES = load_palettes()

# callout 变体颜色（提示/警告/引用）
CALLOUT_COLORS = {
    "tip": {"bg": "E8F5E9", "border": "2E7D32"},
    "warning": {"bg": "FFF3E0", "border": "E65100"},
    "quote": {"bg": "f0fdfa", "border": "14b8a6"},
}


# ===== 颜色工具 =====

def hex_to_rgb(hex_str):
    """十六进制色值转 RGBColor"""
    hex_str = hex_str.lstrip("#")
    return RGBColor(int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16))


def _hex_brightness(hex_str):
    """计算 hex 色值的感知亮度（0-255，越大越亮），用于判断深/浅底"""
    if not hex_str:
        return 255
    hex_str = hex_str.lstrip("#")
    if len(hex_str) == 3:
        hex_str = "".join(c * 2 for c in hex_str)
    if len(hex_str) < 6:
        return 255
    r, g, b = int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16)
    return int(0.299 * r + 0.587 * g + 0.114 * b)


def is_dark_color(hex_str, threshold=160):
    """色值是否偏深（用于深底配白字判断）"""
    return _hex_brightness(hex_str) < threshold


def _gradient_mid_color(style_str):
    """提取渐变两端色值并计算其中间色（50% 位置插值），用于降级纯色。

    渐变格式如 linear-gradient(135deg, #1e3a5f 0%, #4f8ef7 100%)
    取第一个与最后一个色值做 RGB 通道平均，得到视觉中点色。
    仅一个色值时返回该色；取不到返回 None。
    """
    hex_colors = re.findall(r'#[0-9a-fA-F]{3,8}', style_str)
    rgb_match = re.findall(r'rgba?\((\d+),\s*(\d+),\s*(\d+)', style_str)
    all_colors = []
    for c in hex_colors:
        c6 = c.lstrip("#")
        if len(c6) == 3:
            c6 = "".join(ch * 2 for ch in c6)
        if len(c6) >= 6:
            all_colors.append(c6[:6])
    for r_str, g_str, b_str in rgb_match:
        all_colors.append(f"{int(r_str):02x}{int(g_str):02x}{int(b_str):02x}")
    if len(all_colors) < 2:
        return all_colors[0] if all_colors else None
    # 两端中间色：取第一个与最后一个色值，RGB 通道平均
    first, last = all_colors[0], all_colors[-1]
    mid_r = (int(first[0:2], 16) + int(last[0:2], 16)) // 2
    mid_g = (int(first[2:4], 16) + int(last[2:4], 16)) // 2
    mid_b = (int(first[4:6], 16) + int(last[4:6], 16)) // 2
    return f"{mid_r:02x}{mid_g:02x}{mid_b:02x}"


def extract_bg_with_gradient_fallback(style_str):
    """提取纯色背景；渐变则提取两端中间色作为降级纯色（shading 用）"""
    if not style_str:
        return None
    # 先尝试纯色
    m = re.search(r'background(?:-color)?:\s*(#[0-9a-fA-F]{3,8})', style_str)
    if m:
        return m.group(1).lstrip("#")
    m = re.search(r'background(?:-color)?:\s*rgb\((\d+),\s*(\d+),\s*(\d+)\)', style_str)
    if m:
        r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{r:02x}{g:02x}{b:02x}"
    # 渐变降级：取两端色值的中间色（视觉上更接近渐变中点）
    if "gradient" in style_str:
        mid = _gradient_mid_color(style_str)
        if mid:
            return mid
    return None


def _parse_color_value(value):
    """将 CSS 颜色值（hex / rgb / rgba）解析为 hex 字符串；rgba 透明度忽略（Word 无透明度概念）。

    失败返回 None。
    """
    if not value:
        return None
    value = value.strip()
    m = re.match(r'#([0-9a-fA-F]{3,8})', value)
    if m:
        c6 = m.group(1)
        if len(c6) == 3:
            c6 = "".join(ch * 2 for ch in c6)
        if len(c6) >= 6:
            return c6[:6].lower()
    m = re.match(r'rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)', value)
    if m:
        r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{r:02x}{g:02x}{b:02x}"
    return None


def extract_bg_from_styles(parsed_styles, selectors, soup=None):
    """从 <style> 块中按 selector 提取背景色（支持渐变→中间色降级）。

    Args:
        parsed_styles: parse_style_blocks 返回的 {selector: {prop: value}}（cssutils，可能为空）
        selectors: 候选 selector 列表，按顺序匹配
        soup: 可选，BS4 对象；cssutils 不可用时用正则从原始 style 文本兜底提取
    Returns:
        降级后的 hex 色值（无 #），无则 None
    """
    # 1) cssutils 预解析路径
    if parsed_styles:
        for sel in selectors:
            props = parsed_styles.get(sel)
            if not props:
                continue
            bg_val = props.get("background") or props.get("background-color")
            if bg_val:
                bg = extract_bg_with_gradient_fallback(f"background:{bg_val}")
                if bg:
                    return bg
    # 2) 正则兜底：直接从原始 <style> 文本中提取（不依赖 cssutils）
    if soup is not None:
        for style_tag in soup.find_all("style"):
            style_text = style_tag.string or ""
            for sel in selectors:
                # 匹配 ".title { ... background: xxx ... }" 或 "section.title { ... }"
                # 注意：优先匹配【非 dark-mode 前缀】的规则。HTML 中 body.dark-mode .title 等
                # 暗黑规则常写在普通规则之前，若直接搜 ".title {" 会先命中暗黑规则
                # （渐变 #0f172a→#1e3a5f），导致封面取到暗黑中间色。转换目标默认是浅色模式。
                sel_esc = re.escape(sel)
                # 匹配"整段选择器含 sel 的规则"，前缀含 dark-mode 的整条跳过。
                # 注意：不能只用 (?<![\w.-]) + sel + [^{}]* 取前缀——dark-mode 在 sel 之前，
                # 前缀捕获不到，必须把整段选择器（含 sel 之前的 dark-mode 部分）一起匹配。
                for m in re.finditer(r'([^{}]*' + sel_esc + r'[^{}]*)\{([^}]*)\}', style_text, re.IGNORECASE | re.DOTALL):
                    sel_full = m.group(1)
                    body_part = m.group(2)
                    # 跳过暗黑模式专属规则（选择器含 .dark-mode）
                    if 'dark-mode' in sel_full:
                        continue
                    bg_m = re.search(r'background(?:-color)?\s*:\s*([^;}]+)', body_part)
                    if bg_m:
                        bg_val = bg_m.group(1).strip()
                        bg = extract_bg_with_gradient_fallback(f"background:{bg_val}")
                        if bg:
                            return bg
    return None


def extract_color_from_styles(parsed_styles, selectors, soup=None, inline_style=None, default=None):
    """从内联 style 与 <style> 块中按 selector 提取文字颜色。

    优先级：内联 style > cssutils 预解析 > 正则兜底。

    Args:
        parsed_styles: parse_style_blocks 返回的 {selector: {prop: value}}（cssutils，可能为空）
        selectors: 候选 selector 列表，按顺序匹配（如 [".end_page h1", "h1.end_page"]）
        soup: 可选，BS4 对象；cssutils 不可用时用正则从原始 style 文本兜底提取
        inline_style: 可选，元素内联 style 字符串（如 'color: #fff; font-size: 14px'）
        default: 全部未命中时的兜底值
    Returns:
        hex 色值字符串（无 #），无则 default
    """
    # 0) 内联 style 优先
    if inline_style:
        m = re.search(r'color\s*:\s*([^;]+)', inline_style)
        if m:
            c = _parse_color_value(m.group(1))
            if c:
                return c
    # 1) cssutils 预解析路径
    if parsed_styles:
        for sel in selectors:
            props = parsed_styles.get(sel)
            if not props:
                continue
            color_val = props.get("color")
            if color_val:
                c = _parse_color_value(color_val)
                if c:
                    return c
    # 2) 正则兜底：直接从原始 <style> 文本中提取（不依赖 cssutils）
    if soup is not None:
        for style_tag in soup.find_all("style"):
            style_text = style_tag.string or ""
            for sel in selectors:
                sel_esc = re.escape(sel)
                for m in re.finditer(r'([^{}]*' + sel_esc + r'[^{}]*)\{([^}]*)\}', style_text, re.IGNORECASE | re.DOTALL):
                    # 跳过暗黑模式专属规则（选择器含 .dark-mode）
                    if 'dark-mode' in m.group(1):
                        continue
                    cm = re.search(r'color\s*:\s*([^;}]+)', m.group(2))
                    if not cm:
                        continue
                    c = _parse_color_value(cm.group(1).strip())
                    if c:
                        return c
    return default


def extract_font_size_from_styles(parsed_styles, selectors, soup=None, inline_style=None, default=None):
    """从内联 style 与 <style> 块中按 selector 提取 font-size（返回 pt 数值）。

    优先级：内联 style > cssutils 预解析 > 正则兜底。
    px 按 1px=0.75pt 换算。

    Args:
        parsed_styles: parse_style_blocks 返回的 {selector: {prop: value}}（cssutils，可能为空）
        selectors: 候选 selector 列表，按顺序匹配
        soup: 可选，BS4 对象；cssutils 不可用时用正则从原始 style 文本兜底提取
        inline_style: 可选，元素内联 style 字符串
        default: 全部未命中时的兜底值
    Returns:
        pt 数值（float），无则 default
    """
    # 0) 内联 style 优先
    if inline_style:
        m = re.search(r'font-size\s*:\s*([0-9.]+)\s*(px|pt)', inline_style)
        if m:
            val = float(m.group(1))
            return val if m.group(2) == "pt" else round(val * 0.75, 2)
    # 1) cssutils 预解析路径
    if parsed_styles:
        for sel in selectors:
            props = parsed_styles.get(sel)
            if not props:
                continue
            fs_val = props.get("font-size")
            if fs_val:
                m = re.match(r'([0-9.]+)\s*(px|pt)', fs_val.strip())
                if m:
                    val = float(m.group(1))
                    return val if m.group(2) == "pt" else round(val * 0.75, 2)
    # 2) 正则兜底：直接从原始 <style> 文本中提取
    if soup is not None:
        for style_tag in soup.find_all("style"):
            style_text = style_tag.string or ""
            for sel in selectors:
                sel_esc = re.escape(sel)
                for m in re.finditer(r'([^{}]*' + sel_esc + r'[^{}]*)\{([^}]*)\}', style_text, re.IGNORECASE | re.DOTALL):
                    # 跳过暗黑模式专属规则（选择器含 .dark-mode）
                    if 'dark-mode' in m.group(1):
                        continue
                    fm = re.search(r'font-size\s*:\s*([0-9.]+)\s*(px|pt)', m.group(2))
                    if fm:
                        val = float(fm.group(1))
                        return val if fm.group(2) == "pt" else round(val * 0.75, 2)
    return default


def extract_text_align_from_styles(parsed_styles, selectors, soup=None, inline_style=None, default=None):
    """从内联 style 与 <style> 块中按 selector 提取 text-align。

    优先级：内联 style > cssutils 预解析 > 正则兜底。

    Args:
        parsed_styles: parse_style_blocks 返回的 {selector: {prop: value}}（cssutils，可能为空）
        selectors: 候选 selector 列表，按顺序匹配
        soup: 可选，BS4 对象；cssutils 不可用时用正则从原始 style 文本兜底提取
        inline_style: 可选，元素内联 style 字符串
        default: 全部未命中时的兜底值
    Returns:
        text-align 字符串（如 "left"/"center"/"right"），无则 default
    """
    # 0) 内联 style 优先
    if inline_style:
        m = re.search(r'text-align\s*:\s*(left|center|right|justify)', inline_style, re.IGNORECASE)
        if m:
            return m.group(1).lower()
    # 1) cssutils 预解析路径
    if parsed_styles:
        for sel in selectors:
            props = parsed_styles.get(sel)
            if not props:
                continue
            align_val = props.get("text-align")
            if align_val:
                return align_val.strip().lower()
    # 2) 正则兜底：直接从原始 <style> 文本中提取
    if soup is not None:
        for style_tag in soup.find_all("style"):
            style_text = style_tag.string or ""
            for sel in selectors:
                sel_esc = re.escape(sel)
                for m in re.finditer(r'([^{}]*' + sel_esc + r'[^{}]*)\{([^}]*)\}', style_text, re.IGNORECASE | re.DOTALL):
                    # 跳过暗黑模式专属规则（选择器含 .dark-mode）
                    if 'dark-mode' in m.group(1):
                        continue
                    am = re.search(r'text-align\s*:\s*(left|center|right|justify)', m.group(2))
                    if am:
                        return am.group(1).lower()
    return default


def extract_body_background(soup, body, parsed_styles):
    """从 <style> 块和 body 内联样式中提取页面级背景色。

    优先级：body 内联 style > <style> 块中 body 选择器 > body::before 光斑(忽略)
    渐变降级为纯色（取渐变两端中间色，与 extract_bg_with_gradient_fallback 一致）。

    Returns:
        hex 色值字符串（如 "f8fafc"），无则 None
    """
    # 1) 尝试 body 内联 style
    bg = extract_bg_with_gradient_fallback(body.get("style", ""))
    if bg:
        return bg

    # 2) 尝试 <style> 块中 body 选择器（cssutils 预解析）
    if parsed_styles:
        for selector, props in parsed_styles.items():
            # 匹配 "body" 选择器（不匹配 body::before、body.xxx 等）
            if selector.strip() == "body":
                bg_val = props.get("background") or props.get("background-color")
                if bg_val:
                    # cssutils 返回的值可能是 "linear-gradient(...)" 或 "#xxx" 或 "rgb(...)"
                    bg = extract_bg_with_gradient_fallback(f"background:{bg_val}")
                    if bg:
                        return bg

    # 3) 正则兜底：直接从原始 <style> 文本中提取 body { background: ... }
    for style_tag in soup.find_all("style"):
        style_text = style_tag.string or ""
        # 匹配 body { ... background: xxx ... }
        m = re.search(r'body\s*\{[^}]*?background(?:-color)?\s*:\s*([^;}]+)', style_text, re.IGNORECASE | re.DOTALL)
        if m:
            bg_val = m.group(1).strip()
            bg = extract_bg_with_gradient_fallback(f"background:{bg_val}")
            if bg:
                return bg

    return None


def extract_img_width_px(img):
    """从 img 标签的 width/style 中提取宽度百分比或像素值；无则返回 None"""
    if not img:
        return None
    # 1) width="50%" 或 width="300"
    width_attr = img.get("width")
    if width_attr:
        m = re.search(r'(\d+(?:\.\d+)?)\s*%', width_attr)
        if m:
            return float(m.group(1)) / 100.0
        m = re.search(r'(\d+)', width_attr)
        if m:
            return float(m.group(1))
    # 2) style="width: 50%" / "width: 300px" / "max-width: 100%"
    style = img.get("style", "")
    if style:
        m = re.search(r'width\s*:\s*(\d+(?:\.\d+)?)\s*(%|px)', style)
        if m:
            val = float(m.group(1))
            if m.group(2) == "%":
                return val / 100.0
            return val
    return None


# ===== OXML 操作 =====

def set_run_font(run, font_name=None, size=None, bold=None, color=None):
    """统一设置 run 字体（ascii/hAnsi/eastAsia 三属性显式指定）

    python-docx 的 run.font.name 只写 ascii/hAnsi，中文字体必须补 eastAsia；
    同时移除 rFonts 上的 Theme 引用属性（asciiTheme/eastAsiaTheme 等），否则
    Word 主题会覆盖具体字体名，导致逐字符回退、粗细不一。
    """
    name = font_name or DEFAULT_FONT
    if size is not None:
        run.font.size = size
    if bold is not None:
        run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color
    run.font.name = name
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    rfonts.set(qn("w:ascii"), name)
    rfonts.set(qn("w:hAnsi"), name)
    rfonts.set(qn("w:eastAsia"), name)
    for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
        key = qn(attr)
        if key in rfonts.attrib:
            del rfonts.attrib[key]


def add_page_break(doc):
    """标记待分页：由下一个创建的段落承载（避免空段落留白）"""
    doc._pending_page_break = True


def add_cell_paragraph(cell):
    """在单元格末尾直接创建 <w:p> 并返回 Paragraph 对象

    绕过 python-docx 1.1.2 的 cell.add_paragraph() bug（在多单元格表格中
    可能向错误的 XML 节点写入段落）。直接操作 cell._tc XML 确保段落
    附加到当前单元格。所有多单元格表格写入场景统一使用本函数。
    """
    from docx.text.paragraph import Paragraph
    from docx.oxml import OxmlElement as _OxmlElement
    p_elem = _OxmlElement("w:p")
    cell._tc.append(p_elem)
    return Paragraph(p_elem, cell._tc)


def add_hyperlink(paragraph, url, text=None, size=None, color="0563c1"):
    """在段落中插入可点击超链接（Word 标准 w:hyperlink + 关系表注册）

    Word 超链接结构：
      - 文档关系表（document.xml.rels）注册 url → 关系 ID
      - 段落内 <w:hyperlink r:id="..."> 包裹 <w:r><w:t> 文本

    样式采用 Word 默认超链接（蓝色 0563C1 + 下划线），与 Word 手动
    插入超链接一致。url 为空时降级为纯文本，保证内容不丢失。
    """
    from docx.oxml import OxmlElement as _OxmlElement
    from docx.oxml.ns import qn as _qn

    url = (url or "").strip()
    text = (text or url).strip() or url
    if not url:
        # 无 href：按普通文本输出
        run = paragraph.add_run(text)
        if size is not None:
            run.font.size = size
        return run

    # 1. 注册 url 到文档关系表（part.relate_to 自动去重）
    r_id = paragraph.part.relate_to(
        url, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
        is_external=True,
    )

    # 2. 构造 <w:hyperlink r:id="...">
    hyperlink = _OxmlElement("w:hyperlink")
    hyperlink.set(_qn("r:id"), r_id)

    # 3. 构造内部 run，设置标准超链接样式（蓝色 + 下划线）
    run_elem = _OxmlElement("w:r")
    rpr = _OxmlElement("w:rPr")
    # 超链接样式（Word 内置 Hyperlink 字符样式）
    style_elem = _OxmlElement("w:rStyle")
    style_elem.set(_qn("w:val"), "Hyperlink")
    rpr.append(style_elem)
    # 颜色（默认 0563C1）
    color_elem = _OxmlElement("w:color")
    color_elem.set(_qn("w:val"), color.lstrip("#"))
    rpr.append(color_elem)
    # 下划线
    u_elem = _OxmlElement("w:u")
    u_elem.set(_qn("w:val"), "single")
    rpr.append(u_elem)
    # 字体
    if size is not None:
        sz_elem = _OxmlElement("w:sz")
        sz_elem.set(_qn("w:val"), str(int(size.pt * 2)))
        rpr.append(sz_elem)
        szcs_elem = _OxmlElement("w:szCs")
        szcs_elem.set(_qn("w:val"), str(int(size.pt * 2)))
        rpr.append(szcs_elem)
    run_elem.append(rpr)
    t_elem = _OxmlElement("w:t")
    t_elem.set(_qn("xml:space"), "preserve")
    t_elem.text = text
    run_elem.append(t_elem)

    hyperlink.append(run_elem)
    paragraph._p.append(hyperlink)
    return hyperlink


def add_internal_hyperlink(paragraph, anchor, text, size=None, color=None,
                          superscript=False, font_name=None):
    """在段落中插入内部超链接（锚点跳转，指向同文档内的书签）。

    与 add_hyperlink 不同，这里不注册外部 URL 关系，
    而是用 w:anchor 属性指向文档内已存在的书签名。

    Args:
        paragraph: python-docx Paragraph 对象
        anchor: 书签名（如 "source_1"），需与 add_bookmark 中一致
        text: 显示文本（如 "[1]"）
        size: 字号（Pt 对象），可选
        color: hex 色值字符串（如 "0563c1"），可选
        superscript: 是否上标显示
        font_name: 字体名，可选
    """
    from docx.oxml import OxmlElement as _OxmlElement
    from docx.oxml.ns import qn as _qn

    hyperlink = _OxmlElement("w:hyperlink")
    hyperlink.set(_qn("w:anchor"), anchor)

    run_elem = _OxmlElement("w:r")
    rpr = _OxmlElement("w:rPr")

    # 颜色
    if color:
        color_elem = _OxmlElement("w:color")
        color_elem.set(_qn("w:val"), color.lstrip("#"))
        rpr.append(color_elem)

    # 上标
    if superscript:
        va_elem = _OxmlElement("w:vertAlign")
        va_elem.set(_qn("w:val"), "superscript")
        rpr.append(va_elem)

    # 字体
    name = font_name or DEFAULT_FONT
    rfonts = _OxmlElement("w:rFonts")
    rfonts.set(_qn("w:ascii"), name)
    rfonts.set(_qn("w:hAnsi"), name)
    rfonts.set(_qn("w:eastAsia"), name)
    rpr.append(rfonts)

    # 字号
    if size is not None:
        sz_elem = _OxmlElement("w:sz")
        sz_elem.set(_qn("w:val"), str(int(size.pt * 2)))
        rpr.append(sz_elem)
        szcs_elem = _OxmlElement("w:szCs")
        szcs_elem.set(_qn("w:val"), str(int(size.pt * 2)))
        rpr.append(szcs_elem)

    run_elem.append(rpr)

    t_elem = _OxmlElement("w:t")
    t_elem.set(_qn("xml:space"), "preserve")
    t_elem.text = text
    run_elem.append(t_elem)

    hyperlink.append(run_elem)
    paragraph._p.append(hyperlink)
    return hyperlink


def add_bookmark(paragraph, bookmark_name):
    """在段落起始位置插入 Word 书签（bookmarkStart + bookmarkEnd）。

    用于配合 add_internal_hyperlink 实现文档内锚点跳转。
    书签包裹段落本身，使跳转目标定位到该段落。

    Args:
        paragraph: python-docx Paragraph 对象
        bookmark_name: 书签名（如 "source_1"），需与 anchor 一致
    """
    from docx.oxml import OxmlElement as _OxmlElement
    from docx.oxml.ns import qn as _qn

    # 使用 hash(bookmark_name) 生成确定性 ID（正整数且尽量唯一）
    bm_id = str(abs(hash(bookmark_name)) % 1000000)

    p = paragraph._p
    pPr = p.find(_qn("w:pPr"))
    if pPr is None:
        pPr = _OxmlElement("w:pPr")
        p.insert(0, pPr)

    bm_start = _OxmlElement("w:bookmarkStart")
    bm_start.set(_qn("w:id"), bm_id)
    bm_start.set(_qn("w:name"), bookmark_name)

    bm_end = _OxmlElement("w:bookmarkEnd")
    bm_end.set(_qn("w:id"), bm_id)

    # 书签放在 pPr 之后（段落属性之后、内容之前）
    pPr.addnext(bm_start)
    # bookmarkEnd 放到段落末尾
    p.append(bm_end)


# ===== CSS 内联样式解析（HTML → Word 保真） =====

CSS_PATTERNS = {
    "font-size": re.compile(r"font-size\s*:\s*([0-9.]+)\s*(px|pt)"),
    "color": re.compile(r"(?<!background-)color\s*:\s*(#[0-9a-fA-F]{3,8}|rgba?\([^)]*\))"),
    "background": re.compile(r"background(?:-color)?\s*:\s*(#[0-9a-fA-F]{3,8}|rgba?\([^)]*\))"),
    "bold": re.compile(r"font-weight\s*:\s*(bold|700|[1-9]00)"),
    "text-align": re.compile(r"text-align\s*:\s*(left|center|right|justify)", re.IGNORECASE),
}


def get_inline_style_prop(style_str, prop, default=None):
    """从内联 style 字符串提取单个 CSS 属性值

    支持 font-size（返回 pt 数值，px 按 1px=0.75pt 换算）、
    color / background（返回 hex 字符串，无 #）、bold（返回 True）。
    """
    if not style_str:
        return default
    if prop == "font-size":
        m = CSS_PATTERNS["font-size"].search(style_str)
        if m:
            val = float(m.group(1))
            return val if m.group(2) == "pt" else round(val * 0.75, 2)
    elif prop in ("color", "background"):
        m = CSS_PATTERNS[prop].search(style_str)
        if m:
            c = _parse_color_value(m.group(1))
            if c:
                return c
    elif prop == "bold":
        if CSS_PATTERNS["bold"].search(style_str):
            return True
    elif prop == "text-align":
        m = CSS_PATTERNS["text-align"].search(style_str)
        if m:
            return m.group(1).lower()
    return default


def inject_page_break_before(para):
    """在段落 pPr 中注入 page_break_before"""
    pPr = para.paragraph_format.element.get_or_add_pPr()
    for existing in pPr.findall(qn("w:pageBreakBefore")):
        pPr.remove(existing)
    pb = OxmlElement("w:pageBreakBefore")
    pPr.append(pb)


def flush_pending_page_break(doc):
    """检查并清除待分页标记，返回 True 表示需要分页

    契约（读取即清除）：
    - 本函数只"查询并复位" `doc._pending_page_break` 标记，不注入任何分页符
    - 调用方必须在 flush 返回 True 后**自行真正注入分页符**
      （如 add_page_break / inject_page_break_before / 1x1 表格独占页），
      否则标记丢失、分页不生效
    """
    if getattr(doc, "_pending_page_break", False):
        doc._pending_page_break = False
        return True
    return False


def set_cell_margins(cell, top=40, start=80, bottom=40, end=80):
    """设置单元格内边距（单位：twips）"""
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    tcMar = OxmlElement("w:tcMar")
    for side, val in [("top", top), ("start", start), ("bottom", bottom), ("end", end)]:
        elem = OxmlElement(f"w:{side}")
        elem.set(qn("w:w"), str(val))
        elem.set(qn("w:type"), "dxa")
        tcMar.append(elem)
    existing = tcPr.find(qn("w:tcMar"))
    if existing is not None:
        tcPr.remove(existing)
    tcPr.append(tcMar)


def set_table_borders_nil(table):
    """去掉整个表格的所有边框"""
    tbl = table._tbl
    tblPr = tbl.tblPr
    if tblPr is None:
        tblPr = OxmlElement("w:tblPr")
        tbl.insert(0, tblPr)
    existing = tblPr.find(qn("w:tblBorders"))
    if existing is not None:
        tblPr.remove(existing)
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        elem = OxmlElement(f"w:{edge}")
        elem.set(qn("w:val"), "nil")
        borders.append(elem)
    tblPr.append(borders)


def set_table_borders(table, color="dbe4ef", sz="4"):
    """为整个表格设置统一细边框（w:tblBorders）"""
    tbl = table._tbl
    tblPr = tbl.tblPr
    if tblPr is None:
        tblPr = OxmlElement("w:tblPr")
        tbl.insert(0, tblPr)
    existing = tblPr.find(qn("w:tblBorders"))
    if existing is not None:
        tblPr.remove(existing)
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        elem = OxmlElement(f"w:{edge}")
        elem.set(qn("w:val"), "single")
        elem.set(qn("w:sz"), sz)
        elem.set(qn("w:space"), "0")
        elem.set(qn("w:color"), color)
        borders.append(elem)
    tblPr.append(borders)


def set_cell_borders(cell, top_color=None, color="e2e8f0", sz="4"):
    """为单元格设置边框；top_color 指定时顶部用 accent 粗线（模拟卡片顶部色条）"""
    tcPr = cell._tc.get_or_add_tcPr()
    existing = tcPr.find(qn("w:tcBorders"))
    if existing is not None:
        tcPr.remove(existing)
    tcBorders = OxmlElement("w:tcBorders")
    for edge in ("top", "left", "bottom", "right"):
        elem = OxmlElement(f"w:{edge}")
        if edge == "top" and top_color:
            elem.set(qn("w:val"), "single")
            elem.set(qn("w:sz"), "12")  # 3pt 粗线
            elem.set(qn("w:space"), "0")
            elem.set(qn("w:color"), top_color.lstrip("#"))
        else:
            elem.set(qn("w:val"), "single")
            elem.set(qn("w:sz"), sz)
            elem.set(qn("w:space"), "0")
            elem.set(qn("w:color"), color.lstrip("#"))
        tcBorders.append(elem)
    tcPr.append(tcBorders)


def set_table_width_percent(table, percent=100):
    """设置表格总宽度为页面可用宽度的百分比（pct 单位：50=0.5%）"""
    tbl = table._tbl
    tblPr = tbl.tblPr
    if tblPr is None:
        tblPr = OxmlElement("w:tblPr")
        tbl.insert(0, tblPr)
    existing = tblPr.find(qn("w:tblW"))
    if existing is not None:
        tblPr.remove(existing)
    tblW = OxmlElement("w:tblW")
    tblW.set(qn("w:w"), str(int(percent * 50)))
    tblW.set(qn("w:type"), "pct")
    tblPr.append(tblW)


def apply_shading(paragraph, bg_color_hex):
    """为段落应用纯色底色（shading）"""
    shading = OxmlElement("w:shd")
    shading.set(qn("w:fill"), bg_color_hex.lstrip("#"))
    shading.set(qn("w:val"), "clear")
    paragraph.paragraph_format.element.get_or_add_pPr().append(shading)


def apply_shading_to_run(run, bg_color_hex):
    """为 run 应用字符级底纹（w:shd 注入 rPr），用于胶囊/徽章式文字底色。

    与段落 shading 不同，字符级底纹只作用于 run 覆盖的文字范围，
    近似 HTML 中 inline-block 徽章（胶囊）的底色效果。
    """
    if not bg_color_hex:
        return
    rpr = run._element.get_or_add_rPr()
    # 移除已有 shd 避免重复
    existing = rpr.find(qn("w:shd"))
    if existing is not None:
        rpr.remove(existing)
    shading = OxmlElement("w:shd")
    shading.set(qn("w:val"), "clear")
    shading.set(qn("w:color"), "auto")
    shading.set(qn("w:fill"), bg_color_hex.lstrip("#"))
    rpr.append(shading)


def blend_rgba_with_bg(rgba_str, bg_hex):
    """将 rgba() 半透明色与背景色做 alpha 混合，返回混合后的 hex 色值。

    Word 无透明度概念，rgba 背景（如 rgba(255,255,255,0.2) 半透明白）
    需要先与所在背景混合成不透明色。bg_hex 可为 None（无背景时按白色混合）。

    Args:
        rgba_str: 形如 "rgba(r, g, b, a)" 的字符串
        bg_hex: 背景 hex 色值（无 # 或有 # 均可），None 时按白色混合
    Returns:
        混合后 hex 色值（无 #），解析失败返回 None
    """
    m = re.match(r'rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([0-9.]+)\s*\)', rgba_str, re.IGNORECASE)
    if not m:
        return None
    fr, fg, fb = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        alpha = float(m.group(4))
    except ValueError:
        alpha = 1.0
    alpha = max(0.0, min(1.0, alpha))
    if bg_hex:
        bg_hex = bg_hex.lstrip("#")
        br = int(bg_hex[0:2], 16)
        bg_g = int(bg_hex[2:4], 16)
        bb = int(bg_hex[4:6], 16)
    else:
        br = bg_g = bb = 255
    r = int(fr * alpha + br * (1 - alpha))
    g = int(fg * alpha + bg_g * (1 - alpha))
    b = int(fb * alpha + bb * (1 - alpha))
    return f"{r:02x}{g:02x}{b:02x}"


def apply_shading_to_cell(cell, bg_color_hex):
    """为表格单元格应用纯色底色（shading）"""
    shading = OxmlElement("w:shd")
    shading.set(qn("w:fill"), bg_color_hex.lstrip("#"))
    shading.set(qn("w:val"), "clear")
    cell._tc.get_or_add_tcPr().append(shading)


def set_page_background(doc, bg_color_hex):
    """设置 Word 页面级背景色。

    通过两步实现：
    1) 在 settings.xml 中注入 <w:background w:color="xxx"/> 元素
    2) 在 settings.xml 中注入 <w:displayBackgroundShape/> 元素（让 Word 实际渲染背景）

    注意：python-docx 不直接暴露此 API，需操作底层 oxml。
    """
    if not bg_color_hex:
        return

    bg_color_hex = bg_color_hex.lstrip("#")

    # 获取 settings 元素（settings.xml 的根元素）
    settings = doc.settings.element

    # 注入 displayBackgroundShape（让 Word 显示背景色）
    # 先检查是否已存在
    existing_display = settings.find(qn("w:displayBackgroundShape"))
    if existing_display is None:
        display_elem = OxmlElement("w:displayBackgroundShape")
        settings.append(display_elem)

    # 注入 background 元素
    # 先移除已有的 background
    for existing_bg in settings.findall(qn("w:background")):
        settings.remove(existing_bg)
    background_elem = OxmlElement("w:background")
    background_elem.set(qn("w:color"), bg_color_hex)
    # background 元素必须位于 displayBackgroundShape 之前（schema 顺序）
    # 插入到 settings 的最前面
    settings.insert(0, background_elem)
