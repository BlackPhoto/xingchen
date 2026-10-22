#!/usr/bin/env python3
"""
sem_common.py — 公共语义识别层

从 html2docx.py / html2md.py / impact_analyzer.py 中提取的公共代码。
三份转换脚本共用同一份语义识别逻辑，消除重复维护。

包含：
- 12 种语义 class 常量
- classify_element / flatten_semantic_blocks（完整版，含 Tab组/compare-grid/折叠组识别）
- parse_table_data / parse_style_blocks
- 基础工具函数（get_text_content / find_semantic_class / semantic_children 等）

被以下模块 import：
- html2docx.py（主入口）
- html2docx_core.py / html2docx_scene.py / html2docx_advanced.py（处理函数层）
- html2md.py（Markdown 转换）
- impact_analyzer.py（影响分析）
"""

import re
import logging

try:
    from bs4 import BeautifulSoup, Tag, NavigableString, Comment
except ImportError:
    print("[ERROR] 缺少 beautifulsoup4 依赖")
    raise

# cssutils 可选，有则预解析 style 块，无则跳过
try:
    import cssutils
    cssutils.log.setLevel(logging.CRITICAL)
    HAS_CSSUTILS = True
except Exception:
    HAS_CSSUTILS = False


# 12 种语义 class（与 references/semantic-classes.md 一致）
SEMANTIC_CLASSES = {
    "title", "heading", "paragraph", "card", "table",
    "timeline", "stat", "code", "callout", "image", "list",
    "end_page",
}

# 容器聚合：并列同类语义子元素时的 IR 类型
GROUPABLE = {"stat", "card"}

# 通用重复网格检测的列数候选（按出现频率优先）
GRID_COL_CANDIDATES = (4, 3, 5, 2, 6)

# 单元格内出现这些块级标签视为"复合卡片"（非简单单元格），排除出 auto_table
_CELL_BLOCK_TAGS = {
    "div", "p", "ul", "ol", "table", "h1", "h2", "h3", "h4", "h5", "h6",
    "blockquote", "pre", "section", "aside", "article", "figure",
}

# 已有专属处理分支的自定义 class：auto_table 兜底不劫持
_AUTO_TABLE_EXCLUDED_CLASSES = ("rootcause-direct", "rootcause-deep", "impact-grid")

# 图表组件 class：迷你图/条形图卡片的组成元素（.chart-row > .bar / .chart-labels > span / .stat-inline > .item）
# 这些容器有专属 mini_chart 处理分支，detect_repetitive_grid 不劫持
CHART_COMPONENT_CLASSES = (
    "chart-row", "bar", "chart-labels", "stat-inline",
    "trend-card", "sparkline-card",
    "funnel-stage", "funnel-connector",
)

# 图表卡容器 class（trend-card / sparkline-card / bar-chart-card / funnel-wrap）→ 整体识别为 mini_chart/chart_unknown
CHART_CARD_CLASSES = ("trend-card", "sparkline-card", "bar-chart-card", "bar-chart-container", "chart-card", "funnel-wrap")


def detect_repetitive_grid(element, min_items=4):
    """通用重复结构检测（兜底策略，用于未识别 class 的 div/容器）

    检测条件（多层保险防误判）：
      1. 直接子元素（Tag）数量 >= min_items（至少 2 行 x 2 列）
      2. 子元素标签名完全一致（全是 div 或全是 span）
      3. 子元素为简单单元格（不含块级复合结构，如 rcd-item 卡片）
      4. 能推断合理列数（2~6 列，总数能被整除且行数 >= 2）
      5. 切片后各行 class 模式一致（结构一致性验证）

    返回 (num_cols, rows_data)：
      rows_data: list[list[Tag]]，按行切片的子元素二维列表
    不满足条件返回 None（由调用方走原有拍平逻辑）
    """
    children = [c for c in element.children if isinstance(c, Tag)]
    if len(children) < min_items:
        return None
    # 标签名完全一致
    names = {c.name for c in children}
    if len(names) != 1:
        return None
    tag_name = next(iter(names))
    # 内联元素（span/button/a 等）排成多行必须有布局线索（flex/grid），
    # 否则视为单行（如一行按钮组），避免误判为表格
    if tag_name != "div":
        style = re.sub(r"\s+", "", (element.get("style") or "").lower())
        has_layout_hint = ("display:flex" in style or "display:grid" in style
                           or "grid-template-columns" in style or "flex-wrap" in style)
        if not has_layout_hint:
            return None
    # 已有专属处理分支的自定义 class（rootcause-*/impact-grid 等）不劫持
    el_classes = element.get("class") or []
    if any(c in _AUTO_TABLE_EXCLUDED_CLASSES for c in el_classes):
        return None
    # 图表组件容器（chart-row 等）不劫持：有专属 mini_chart 处理分支
    if any(c in CHART_COMPONENT_CLASSES for c in el_classes):
        return None
    # 单元格为简单元素：含块级复合结构（卡片）不作为单元格，排除
    for c in children:
        if any(blk in (c.get("class") or []) for blk in ("rcd-item",)):
            return None
        if any(b.name in _CELL_BLOCK_TAGS for b in c.find_all(recursive=False)
               if b.name in _CELL_BLOCK_TAGS):
            return None
    # 图表特征排除：所有单元格均无文本（仅高度/背景样式，如 .bar）→ 非数据表格
    # 数据表格的单元格必然有文本内容；全无文本的重复结构是图表条（height 百分比），
    # 转 Word/Markdown 会得到空表格行。此规则比 class 名单更通用，防"打地鼠"。
    if all(not get_text_content(c) for c in children):
        return None
    # 推断列数
    total = len(children)
    num_cols = None
    for n in GRID_COL_CANDIDATES:
        if total % n == 0 and total // n >= 2:
            num_cols = n
            break
    if not num_cols:
        return None
    rows = [children[i:i + num_cols] for i in range(0, total, num_cols)]
    if not _rows_structurally_consistent(rows, num_cols):
        return None
    return num_cols, rows


def _rows_structurally_consistent(rows, num_cols):
    """校验切片后的行结构一致性：每行的 class 模式一致才认为符合表格规律。

    防误判核心：并排卡片组（各卡片 class 相同）会被自然排除——
    卡片组每行只有 1 个元素，列数为 1 不满足 num_cols >= 2 前置条件；
    而真正的网格/表格行（每行多个同类单元格）各行 class 模式一致。
    """
    if num_cols < 2:
        return False
    first_pattern = None
    for row in rows:
        pattern = tuple(sorted((c.get("class") or [])[0] if c.get("class") else "") for c in row)
        if first_pattern is None:
            first_pattern = pattern
        elif pattern != first_pattern:
            return False
    return True


def is_chart_card(el):
    """判断元素是否为图表容器（trend-card / sparkline-card / bar-chart-card / chart-row / chart-card）

    特征：
      - class 含 trend-card / sparkline-card → 图表卡容器（标题 + 数据条 + 标签 + 说明）
      - class 含 bar-chart-card / bar-chart-container → CSS 条形图容器（含 bar-group/bar-item 子结构），
        需整体识别为图表，避免内部 bar-group（flex + height%）被逐个拆成独立图表碎片
      - class 含 chart-row → 柱状图数据条组（bar 无文本，仅 height 样式），需专属处理
      - class 含 chart-card → 柱状图卡片容器（h3 标题 + chart-row + chart-labels），
        整体识别为 mini_chart 走截图路径，避免被拆散为纯数字文本（2026-09 新增）
    用于 classify_element 识别 mini_chart，让转换器整体处理图表卡，
    而非把 bar/标签拍平散落或误判为 auto_table。
    chart-labels / stat-inline 有文本内容，走普通段落即可，不识别为 mini_chart。

    保险丝（2026-09）：.chart-card 类名较通用，可能被用户用于含正文内容的容器。
    若容器内含正文语义元素（h1-h6 / paragraph / list / table / callout / stat / image / code），
    不整体识别为 mini_chart（否则正文会被 process_chart_card 的文本回退分支吞掉），
    返回 None 由上层递归分别处理。

    保险丝扩展（2026-09）：.chart-card 内含折叠组件（直接子元素 .collapse-item，
    或平铺的 .collapse-trigger + .collapse-body）时同样不识别为 mini_chart——
    折叠组应走 process_collapse_group 展开全部标题+正文，整体截图会吞掉折叠文字。
    判断标准与 classify_element 的 collapse_group 识别保持一致（仅直接结构）。
    """
    if not isinstance(el, Tag):
        return False
    classes = el.get("class") or []
    if any(c in CHART_CARD_CLASSES for c in classes):
        # 保险丝：.chart-card 含正文语义子元素时不做图表卡整体识别
        # 图表卡标题（h3）不算正文——标题 + chart-row/funnel-stage 是图表卡标准结构，
        # 若 h3 触发保险丝会把整卡拆散为文本（2026-09 修复：chart-card 含 h3 标题误判正文）。
        if "chart-card" in classes and _has_prose_content(el, ignore_headings=True):
            return False
        # 保险丝：.chart-card 含折叠组件直接结构时不做图表卡整体识别
        if "chart-card" in classes and _has_collapse_structure(el):
            return False
        return True
    if "chart-row" in classes:
        return True
    return False


# ===== 基础工具函数 =====

def get_text_content(element):
    """获取元素的纯文本内容"""
    return element.get_text(strip=True) if element else ""


def find_semantic_class(el):
    """返回元素上第一个语义 class 名；无则返回 None

    特殊规则：title 与 end_page 同时出现（如 class="title end_page"）时，
    按尾页处理（end_page 是更精确的语义）。
    """
    classes = el.get("class", [])
    if "end_page" in classes:
        return "end_page"
    for cls in classes:
        if cls in SEMANTIC_CLASSES:
            return cls
    return None


def semantic_children(el, scls):
    """返回 el 的直接子元素中带有指定语义 class 的元素列表"""
    return [c for c in el.children if isinstance(c, Tag) and find_semantic_class(c) == scls]


def get_data_cols(el):
    """读取 data-cols 属性；无则返回 None"""
    val = el.get("data-cols")
    if val and val.isdigit():
        return int(val)
    return None


def is_visible_text(el):
    """元素是否含可见文本"""
    text = el.get_text(strip=True)
    return bool(text) and len(text) > 0


def _has_media_child(el):
    """元素是否含媒体子元素（img/svg/figure/canvas/video）——即使无文本也不应跳过

    用于 flatten_semantic_blocks 中防止纯图片/SVG/图表容器因"无可见文本"被跳过。
    """
    if not isinstance(el, Tag):
        return False
    for tag_name in ("img", "svg", "figure", "canvas", "video"):
        if el.find(tag_name):
            return True
    return False


def _is_chart_like_container(el):
    """通用图表特征检测（结构特征，不依赖 class 名）——用于 chart_unknown 兜底识别

    检测条件（满足任一即返回 True）：
      1. 元素含 <svg> 子元素（SVG 图表/图形）
      2. 元素含 <canvas> 子元素（Canvas 图表）
      3. flex/grid 布局 + 多数直接子元素带 height 百分比/像素样式（CSS 条形图等，
         子元素可有文本标签——带文本的条形图也是图表，不是普通网格）
      4. 无 flex/grid 线索，但多数子元素带 height 百分比（CSS 类定义布局时的兜底）

    与 detect_repetitive_grid 的区别：普通网格/表格单元格不用百分比高度，
    图表条形则用 height:X% 表示数据大小。用"height 百分比"区分图表与普通网格。

    排除条件：已有专属 IR（mini_chart/card_grid/image 等）不在此识别，由上层 classify_element 先行分流。
    """
    if not isinstance(el, Tag):
        return False
    # 条件 1/2：含 SVG/Canvas
    if el.find("svg") or el.find("canvas"):
        return True
    # 条件 3/4：检查子元素的 height 特征
    children = [c for c in el.children if isinstance(c, Tag)]
    if len(children) < 2:
        return False
    style = re.sub(r"\s+", "", (el.get("style") or "").lower())
    has_layout = ("display:flex" in style or "display:grid" in style
                  or "grid-template-columns" in style or "flex-wrap" in style)
    # 统计带 height 样式的子元素
    height_pct_count = 0
    height_any_count = 0
    for c in children:
        c_style = re.sub(r"\s+", "", (c.get("style") or "").lower())
        if "height" in c_style:
            height_any_count += 1
            if "%" in c_style:
                height_pct_count += 1
    # 条件 3：flex/grid 布局 + 多数子元素带 height（px 或 %）→ CSS 条形图
    # 子元素可有文本标签（如 "Q1 35%"），不要求全空
    if has_layout and height_any_count >= max(2, len(children) // 2):
        return True
    # 条件 4：无 flex/grid 线索，但多数子元素带 height 百分比（纯百分比高度是图表条的典型特征）
    if height_pct_count >= max(2, len(children) // 2):
        return True
    return False


def _has_collapse_structure(el):
    """检测容器是否含折叠组件直接结构（.collapse-item，或平铺的 .collapse-trigger + .collapse-body）。

    与 classify_element 的 collapse_group 识别标准一致（仅直接子元素），
    避免深层嵌套的折叠（如时间线 li 内的折叠）劫持图表卡识别。
    """
    if not isinstance(el, Tag):
        return False
    direct_children = [c for c in el.children if isinstance(c, Tag)]
    if any("collapse-item" in (c.get("class") or []) for c in direct_children):
        return True
    if any("collapse-trigger" in (c.get("class") or []) for c in direct_children):
        return any("collapse-body" in (c.get("class") or []) for c in direct_children)
    return False


def is_hidden_chart_label(el):
    """判断元素是否为「被隐藏的图表数据标签」（.chart-labels 兜底标签）。

    场景：HTML 生成器在 SVG/CSS 图表下方常放一层 .chart-labels 纯文本标签，
    作为降级环境（无浏览器/截图失败）的数据兜底。为不干扰图表显示，
    这层标签常被标记为 aria-hidden="true" 或内联 display:none。
    浏览器中它本来就不可见，转换到 Word/Markdown 时若再输出，
    会与图表截图中的轴标签/图例重复（如"25Q3 25Q4 26Q1 26Q2"出现两份）。

    判断规则（仅命中"被隐藏的图表标签"，不影响其他元素）：
      1. class 含 chart-labels（图表数据标签容器）
      2. 且满足任一隐藏标记：
         - aria-hidden="true" 属性
         - 内联 style 含 display:none
    折叠内容（.collapse-body）用 max-height/overflow 隐藏而非 display:none 内联，
    且不带 aria-hidden，不受此规则影响。
    """
    if not isinstance(el, Tag):
        return False
    classes = el.get("class") or []
    if "chart-labels" not in classes:
        return False
    if str(el.get("aria-hidden", "")).strip().lower() == "true":
        return True
    style = el.get("style") or ""
    if "display" in style and "none" in style:
        return True
    return False


def _has_prose_content(el, ignore_headings=False):
    """检测容器是否含正文内容（语义 class 的段落/标题/列表/表格/时间线等）。

    用于 _is_chart_like_container 的例外判断：当容器同时含图表（SVG/Canvas/CSS 条形图）
    和正文段落时，不能整体识别为 chart_unknown（会导致正文被截图逻辑吞掉），
    应返回 None 让上层递归进入子元素分别处理。

    判断标准：直接子元素中存在带语义 class 的元素（paragraph/heading/list/table/
    timeline/callout/card/stat 等），或存在 h1-h6 标题标签。

    ignore_headings=True 时忽略 h1-h6 标题（用于图表卡容器：标题是图表标题而非正文，
    如 <div class="chart-card"><h3>标题</h3><div class="chart-row">…</div></div>，
    否则 h3 会触发正文保险丝导致整卡不识别为图表）。
    """
    if not isinstance(el, Tag):
        return False
    PROSE_SEMANTIC = {
        "paragraph", "heading", "list", "table", "timeline",
        "callout", "card", "stat", "image", "code", "end_page",
    }
    for child in el.children:
        if not isinstance(child, Tag):
            continue
        child_classes = child.get("class") or []
        # 含语义 class 的子元素 → 正文内容
        if any(c in PROSE_SEMANTIC for c in child_classes):
            return True
        # h1-h6 标题标签 → 正文内容（图表卡场景可忽略）
        if child.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            if ignore_headings:
                continue
            return True
        # 含 cite 引用的 p 标签 → 正文内容（学术引用）
        if child.name == "p" and child.find(class_="cite"):
            return True
    return False


# ===== 语义识别（归约到 IR 语义） =====

def classify_element(el):
    """识别单个元素的 IR 语义类型（不含聚合判断）

    返回字符串 IR 类型，或 None（无法识别 → 兜底 paragraph）
    """
    scls = find_semantic_class(el)
    if scls == "title":
        # title + hero → 仍走 title_page（封面级排版，深色渐变底+居中+垂直占满）。
        # hero_banner 仅用于纯 hero（无 title 语义）的长页头部横幅。
        # 此前 title+hero 被误判为 hero_banner，导致封面背景色/胶囊/垂直居中全部丢失。
        return "title_page"
    if scls == "heading":
        return "heading"
    if scls == "paragraph":
        return "paragraph"
    if scls == "table":
        # pricing 表（含 pricing 类名或 data-variant=pricing）→ 对比表格（高亮列）
        classes = el.get("class", [])
        if "pricing" in classes or el.get("data-variant") == "pricing":
            return "pricing_table"
        return "table"
    if scls == "timeline":
        return "timeline"
    if scls == "stat":
        return "stat_block"
    if scls == "code":
        return "code_block"
    if scls == "callout":
        return "callout"
    if scls == "image":
        return "image"
    if scls == "list":
        return "bullet_list"
    if scls == "card":
        # 卡片内含折叠组件（.collapse-trigger）→ 折叠组（展开全部内容）
        # 仅当折叠组件是卡片的直接结构（直接子元素 .collapse-item，
        # 或平铺的直接 .collapse-trigger/.collapse-body）时才视为折叠组；
        # 深度嵌套的折叠（如时间线 li 内的折叠）不劫持卡片本身。
        direct_items = [c for c in el.children if isinstance(c, Tag)
                        and "collapse-item" in (c.get("class") or [])]
        direct_triggers = [c for c in el.children if isinstance(c, Tag)
                           and "collapse-trigger" in (c.get("class") or [])]
        if direct_items or direct_triggers:
            return "collapse_group"
        return "card_grid"  # 单卡由处理函数按内容拆分
    if scls == "end_page":
        return "end_page"
    # 图表卡（trend-card / sparkline-card，含 .chart-row 或 .stat-inline）→ mini_chart
    if is_chart_card(el):
        return "mini_chart"
    # 无语义 class 的兜底识别（结构特征）
    name = el.name or ""
    # 任务卡片（.task-item：task-num + task-body + task-level 三件套）→ task_list
    if "task-item" in (el.get("class") or []):
        return "task_list"
    # 折叠组识别（仅直接结构）：容器直接子元素含 .collapse-item，
    # 或平铺的直接 .collapse-trigger + .collapse-body 组合。
    # 不使用深度 find：深层嵌套的折叠（时间线 li 内的折叠等）不应劫持
    # 整个容器（否则容器内标题/副标题会被吞掉）。
    direct_children = [c for c in el.children if isinstance(c, Tag)]
    if direct_children and any(
        "collapse-item" in (c.get("class") or []) for c in direct_children
    ):
        return "collapse_group"
    if direct_children and any(
        "collapse-trigger" in (c.get("class") or []) for c in direct_children
    ):
        # 平铺结构：需同时存在 trigger 与 body 才构成折叠组
        if any("collapse-body" in (c.get("class") or []) for c in direct_children):
            return "collapse_group"
    if name == "blockquote":
        return "quote"
    if name in ("table",):
        # 表格兜底识别为普通 table
        return "table"
    if name == "details":
        return "faq"
    # 含 badge/tag 类名的元素
    for cls in el.get("class", []):
        if cls in ("badge", "tag", "badge-group", "tag-group"):
            return "badge_group"
    # Tab 结构（.tab-nav 容器）
    if "tab-nav" in (el.get("class") or []):
        return "tab_group"
    # divider 特征：3 个圆点 span（旧样式，兼容保留）
    if name == "div":
        spans = el.find_all("span", recursive=False)
        if len(spans) == 3 and all(not s.get_text(strip=True) for s in spans):
            return "divider"
        # divider 特征：短线 + 菱形 + 短线（新样式）
        if len(spans) == 3 and all(
            (s.get("class") or [])[0] in ("line", "diamond") if s.get("class") else False
            for s in spans
        ):
            return "divider"
        # 含多个 img 网格 → gallery
        imgs = el.find_all("img", recursive=True)
        if len(imgs) >= 2:
            return "gallery"
        # 含 icon + 文字行 → icon_list（icon 特征：i 标签或含 emoji 前缀的行）
        icons = el.find_all("i", recursive=False) or el.find_all("span", class_="icon", recursive=False)
        if icons:
            return "icon_list"
        # 通用图表特征兜底（优先）：含 SVG/Canvas 或 CSS 条形图结构 → chart_unknown
        # 必须在 detect_repetitive_grid 之前检查，否则带文本标签的 CSS 条形图
        # 会被误判为 auto_table 输出错位空表格行
        # 例外：容器同时含正文段落（语义 class 的 p/h2 等）时不能整体截为 chart_unknown，
        # 否则正文段落会被截图逻辑吞掉。此时返回 None 让上层递归进入子元素分别处理。
        if _is_chart_like_container(el):
            if _has_prose_content(el):
                return None  # 混合容器（图表+正文）：递归处理，图表和正文各走各的路
            return "chart_unknown"
        # 交互式数据看板（.map-section：区域卡片矩阵 + 详情面板 + 图例）→ chart_unknown
        # 整块 Playwright 截图保留视觉（默认选中区域高亮 + 详情面板），避免 30+ 段落碎片化；
        # 截图失败时降级为提取文本重建表格（数据不丢）。
        # 结构特征：class 含 map-section/map-area/map-info-panel，或含 >=2 个带 onclick 的区域卡片
        el_classes = el.get("class") or []
        if ("map-section" in el_classes or "map-area" in el_classes or "map-info-panel" in el_classes) \
                or _has_map_region_cards(el):
            return "chart_unknown"
        # 键值对数据组（.reason-data：>=2 个 .reason-data-item，各含 dv+dl）→ data_table
        # 转 2 列（值+说明）表格输出，避免 dv/dl 被拆成零散段落
        if _is_reason_data_group(el):
            return "data_table"
        # 无 class 图表外层容器（含 .chart-row/.chart-labels/.stat-inline 组合 ≥2 且占比 ≥2/3）
        # → mini_chart 整体处理，让 _rasterize_element 截整个容器（含月份/指标），
        # 避免此前只截 .chart-row 柱条导致月份/指标被拍平。
        if is_bare_chart_wrapper(el):
            return "mini_chart"
        # .stat-inline 指标行（>=2 个 .item 含 .v+.l）→ stat_table
        # 放在 is_bare_chart_wrapper 之后：单独出现的 stat-inline 识别为指标表格；
        # 位于图表容器内的 stat-inline 由 is_bare_chart_wrapper 整体接管。
        if _is_stat_inline_group(el):
            return "stat_table"
        # 通用重复结构检测（兜底）：未识别的 div 含规律性重复行列 → auto_table
        if detect_repetitive_grid(el) is not None:
            return "auto_table"
    # 无语义 class 的列表标签 → bullet_list（如 .task-list 等自定义列表）
    if name in ("ul", "ol"):
        return "bullet_list"
    # SVG/Canvas 标签本身 → chart_unknown（截图保留视觉）
    if name in ("svg", "canvas"):
        return "chart_unknown"
    # 无 class 的普通段落 / 标题 / 容器
    if name in ("p", "h1", "h2", "h3", "h4", "h5", "h6", "div", "section", "pre"):
        return None  # 由上层决定：递归子元素或兜底
    return None


def _has_map_region_cards(el):
    """检测交互式区域卡片矩阵（如 .map-section 内的 .map-region 卡片）。

    结构特征：直接子元素中 >=2 个带 onclick/data-region 且含份额文本的卡片。
    """
    if not isinstance(el, Tag):
        return False
    regions = [
        c for c in el.children
        if isinstance(c, Tag)
        and (c.get("onclick") or c.get("data-region"))
    ]
    return len(regions) >= 2


def _is_reason_data_group(el):
    """检测键值对数据组（.reason-data 或含 >=2 个 .reason-data-item 的容器）。

    每个 item 须含一个值元素（.dv）与一个说明元素（.dl），适合输出 2 列表格。
    """
    if not isinstance(el, Tag):
        return False
    el_classes = el.get("class") or []
    if "reason-data" in el_classes:
        return True
    items = [
        c for c in el.children
        if isinstance(c, Tag) and "reason-data-item" in (c.get("class") or [])
    ]
    if len(items) < 2:
        return False
    return all(
        c.find(class_="dv") is not None and c.find(class_="dl") is not None
        for c in items
    )


def _is_stat_inline_group(el):
    """检测 .stat-inline 指标行（>=2 个 .item，各含 .v 值 + .l 标签）。

    结构特征：class 含 stat-inline，直接子元素 >=2 个 .item，
    每个 .item 同时含 .v（值）与 .l（标签）→ 适合输出为 2 列（值+说明）表格。
    避免 .v/.l 被 flatten 拍平为零散段落。
    """
    if not isinstance(el, Tag):
        return False
    el_classes = el.get("class") or []
    if "stat-inline" not in el_classes:
        return False
    items = [
        c for c in el.children
        if isinstance(c, Tag) and "item" in (c.get("class") or [])
    ]
    if len(items) < 2:
        return False
    return all(
        c.find(class_="v") is not None and c.find(class_="l") is not None
        for c in items
    )


def is_bare_chart_wrapper(el):
    """无 class 图表外层容器检测（含 .chart-row/.chart-labels/.stat-inline 组合）。

    背景：生成端（LLM）常写出"无 class 的图表卡外层容器"（如
    <div style="background:..."><div class="chart-row">…</div>
    <div class="chart-labels">…</div><div class="stat-inline">…</div></div>），
    此前只有 .chart-row 被识别为 mini_chart，导致截图只截柱条、月份/指标被拍平。

    结构特征（防误判）：
      - 元素是 div，且不含任何语义 class（title/heading/paragraph/card/table 等）
      - 内部不含 <table>（含 table 走文本化路径，不截图）
      - 直接子元素中图表组件（.chart-row/.chart-labels/.stat-inline）>= 2 个
      - 图表组件占直接子元素比例 >= 2/3（防止"正文大容器 + 零散图表组件"被整体截图吞掉正文）
    """
    if not isinstance(el, Tag):
        return False
    el_classes = el.get("class") or []
    if any(c in SEMANTIC_CLASSES for c in el_classes):
        return False
    if el.find("table"):
        return False
    children = [c for c in el.children if isinstance(c, Tag)]
    if len(children) < 2:
        return False
    chart_children = [
        c for c in children
        if any(cls in (c.get("class") or []) for cls in
               ("chart-row", "chart-labels", "stat-inline"))
    ]
    if len(chart_children) < 2:
        return False
    if len(chart_children) / len(children) < 2 / 3:
        return False
    return True


def flatten_semantic_blocks(body):
    """遍历 body，产出语义块列表。

    每个块: (element, ir_type, group_info)
      group_info: None 表示单块；("stat", [elements]) / ("card", [elements]) 表示聚合组
    规则：
      - 元素带语义 class → 单块
      - 无语义 class 的容器含 ≥2 个同类可聚合子元素（stat/card）→ 聚合组
      - 无语义 class 且可兜底识别（blockquote/details/divider/gallery 等）→ 单块
      - 其余容器递归进入其子元素；文本元素兜底为 paragraph
    """
    blocks = []
    skip_panels = set()  # 已被 tab_group 处理的面板，遍历时跳过（避免重复输出）
    skip_task_items = set()  # 已被 task_list 合并处理的连续 .task-item 兄弟，遍历时跳过
    skip_chart_siblings = set()  # 已被 chart_unknown 截图包含的同级图表组件（chart-labels/stat-inline/legend-list）
    # 交互辅助元素：无内容价值，三端输出时一律跳过（复制按钮/搜索框/无结果提示/返回顶部/暗黑模式切换）
    SKIP_INTERACTIVE_CLASSES = ("code-copy-btn", "table-search-input", "table-no-result", "back-to-top", "dark-toggle-btn")
    # 表格标题已通过 data-caption 属性输出，跳过 .table-caption div 避免重复
    SKIP_DECORATIVE_CLASSES = ("table-caption",)
    # 页眉/页脚/机密水印：非语义 class，Word 端由 process_title_page 提取注入封面，
    # Markdown 端由 render_title_page 提取输出，PDF 端由 Playwright 直接渲染。
    # 三端转换器均不应将其当普通段落输出（避免封面前多出文字行）。
    SKIP_NON_SEMANTIC_CLASSES = ("page-header", "page-footer", "confidential-watermark")
    # 导航/目录侧边栏：交互导航控件，目录条目由 JS 动态生成（静态 HTML 中为空壳），
    # 三端转换时一律跳过（PDF 端由 @media print 隐藏，Word/MD 端不应输出空标题+空列表）
    SKIP_NAV_CLASSES = ("toc-sidebar", "toc-toggle")

    def visit(container):
        for child in container.children:
            if not isinstance(child, Tag):
                continue
            if isinstance(child, Comment):
                continue
            if child.name in ("style", "script"):
                continue
            child_classes = child.get("class") or []
            if any(c in SKIP_INTERACTIVE_CLASSES for c in child_classes):
                continue
            if any(c in SKIP_DECORATIVE_CLASSES for c in child_classes):
                continue
            if any(c in SKIP_NON_SEMANTIC_CLASSES for c in child_classes):
                continue
            if any(c in SKIP_NAV_CLASSES for c in child_classes):
                continue
            if child.name == "button" and "back-to-top" in child_classes:
                continue
            # 隐藏的图表数据标签（.chart-labels 带 aria-hidden / display:none）：
            # 浏览器中不可见，是降级兜底标签，图表截图已覆盖信息，跳过避免重复输出
            if is_hidden_chart_label(child):
                continue
            if child in skip_panels:
                continue
            if child in skip_chart_siblings:
                continue
            scls = find_semantic_class(child)
            if scls:
                ir = classify_element(child)
                blocks.append((child, ir, None))
                continue
            # 无语义 class：识别 Tab 结构（.tab-nav + .tab-panel 组合）
            child_classes = child.get("class") or []
            if child.name == "div" and "tab-nav" in child_classes:
                # 只取 tab-nav 之后连续的兄弟 .tab-panel（同一组，防止跨组串扰）
                parent = child.parent
                panels = []
                if parent is not None:
                    siblings = [c for c in parent.children if isinstance(c, Tag)]
                    try:
                        idx = siblings.index(child)
                    except ValueError:
                        idx = -1
                    for sib in siblings[idx + 1:] if idx >= 0 else []:
                        if "tab-panel" in (sib.get("class") or []):
                            panels.append(sib)
                        else:
                            break
                if panels:
                    skip_panels.update(panels)
                    blocks.append((child, "tab_group", None))
                    continue
            # 无语义 class：先做 task-item 特征识别（任务卡片：task-num + task-body + task-level 三件套）
            # 练习任务列表由 1 个或多个 .task-item 组成：
            #   - 容器内含 ≥1 个 .task-item → 容器整体作为 task_list 块
            #   - 连续的同级 .task-item 兄弟 → 合并为一个 task_list 块（同一张表）
            if "task-item" in child_classes:
                if child in skip_task_items:
                    continue
                siblings = [c for c in container.children if isinstance(c, Tag)]
                try:
                    idx = siblings.index(child)
                except ValueError:
                    idx = -1
                run_items = [child]
                if idx >= 0:
                    for sib in siblings[idx + 1:]:
                        if "task-item" in (sib.get("class") or []):
                            run_items.append(sib)
                        else:
                            break
                skip_task_items.update(run_items[1:])
                # 块元素取首个 .task-item，完整列表经 group_info=("task", run_items) 传递
                blocks.append((child, "task_list", ("task", run_items)))
                continue
            if child.name == "div" and child.find(class_="task-item") is not None:
                task_items = [c for c in child.children if isinstance(c, Tag)
                              and "task-item" in (c.get("class") or [])]
                if task_items:
                    # 容器整体作为 task_list 块（由处理函数遍历所有 .task-item）
                    blocks.append((child, "task_list", ("task", task_items)))
                    continue
            # 无语义 class：先做 compare-grid（对比卡片组，含 ≥2 张 compare-card）
            if child.name == "div" and "compare-grid" in (child.get("class") or []):
                cards = [c for c in child.children if isinstance(c, Tag)
                         and "compare-card" in (c.get("class") or [])]
                if len(cards) >= 2:
                    blocks.append((child, "compare_cards", None))
                    continue
            # 无语义 class：检查聚合组
            for gcls in GROUPABLE:
                members = semantic_children(child, gcls)
                if len(members) >= 2:
                    # 混合结构保护：容器除聚合成员外，若直接子元素中还含
                    # 独立语义元素（标题/段落/图片/列表等），说明是"标题+卡片组"
                    # 等混合容器，整体聚合会把标题/图片吞进表格，必须递归进入，
                    # 让每个子元素独立输出。
                    # 例：mode-deck 的 <section class="slide"> 内 h2 + flex容器(4×card)，
                    # 若整体聚合 card_grid，h2 与图片会全部丢失。
                    other_semantic = [
                        c for c in child.children
                        if isinstance(c, Tag)
                        and c not in members
                        and (
                            find_semantic_class(c) in ("heading", "paragraph",
                                                       "title", "image", "list",
                                                       "callout", "code", "table",
                                                       "timeline", "end_page")
                            or c.name in ("img", "svg", "figure", "canvas", "video")
                        )
                    ]
                    if other_semantic:
                        visit(child)
                        break
                    ir = "stat_block" if gcls == "stat" else "card_grid"
                    blocks.append((child, ir, (gcls, members)))
                    break
            else:
                # 结构特征兜底
                ir = classify_element(child)
                if ir:
                    blocks.append((child, ir, None))
                    # chart_unknown/mini_chart 截图时已包含同级图表组件（chart-labels/stat-inline/legend-list），
                    # 标记同级图表组件为跳过，避免它们的文本被重复输出
                    if ir in ("chart_unknown", "mini_chart"):
                        _parent = child.parent
                        if _parent is not None:
                            _CHART_SIBLING_CLS = ("chart-labels", "stat-inline", "legend-list")
                            for sib in _parent.children:
                                if not isinstance(sib, Tag) or sib is child:
                                    continue
                                if any(c in _CHART_SIBLING_CLS for c in (sib.get("class") or [])):
                                    skip_chart_siblings.add(sib)
                elif is_visible_text(child) or _has_media_child(child):
                    # 普通容器：判断子元素构成
                    tag_children = [c for c in child.children if isinstance(c, Tag)]
                    # 注意：Comment 注释节点是 NavigableString 子类，必须排除，
                    # 否则含 <!-- --> 注释的容器会被误判为"混合内容"→ 整体输出段落，
                    # 导致 tab-panel/折叠组等内容全部丢失
                    text_children = [c for c in child.children
                                     if isinstance(c, NavigableString)
                                     and not isinstance(c, Comment)
                                     and re.sub(r"\s+", " ", str(c)).strip()]
                    if tag_children and text_children:
                        # 混合内容（Tag + bare text）：整体输出为一个 paragraph，
                        # 让 _add_rich_text_runs 的 walk 函数处理混合内容（Tag+文本同一段落）
                        blocks.append((child, "paragraph", None))
                    elif tag_children:
                        # 纯 Tag 子元素：递归进入
                        visit(child)
                    else:
                        # 无 Tag 子元素（纯文本）：整体兜底为 paragraph
                        blocks.append((child, "paragraph", None))
                # 无可见内容且无媒体子元素 → 跳过

    visit(body)
    return blocks


# ===== 数据解析工具 =====

def parse_table_data(table_elem):
    """解析 HTML table 为二维列表（展开 colspan/rowspan）

    返回 (rows, merges, detail_map)：
      rows: list[list[str]]，每行按展开后的列数补齐文本（colspan 重复填充文本，
            rowspan 在后续行对应位置填充空串占位）
      merges: list[dict]，每个 dict 描述一个合并区域：
        {"r": 起始行, "c": 起始列, "rs": 行跨度, "cs": 列跨度}
        （rs==1 且 cs==1 的普通单元格不记录）
      detail_map: list[(after_row, detail_text)]，row-detail 行的文本及其应插入
            位置（after_row = 该 detail 行上方最近数据行在 rows 中的索引）。
            调用方可在对应行正下方插入 detail 内容（表格内合并行 / 表格后段落）。

    说明：Markdown 不支持合并单元格，用展开后的 rows 即可；
    Word 端可用 merges 重建真实合并（cell.merge）。
    row-detail 行（class 含 "row-detail"）跳过 colspan 展开，收集到 detail_map。
    """
    rows = []
    merges = []
    detail_map = []   # [(after_row_idx, detail_text)]
    # rowspan 占位表：col -> 后续仍需跳过的行数（不含当前行）
    # 仅记录"上一行遗留"的占用；本行新设置的 rowspan 在行尾并入下一行
    pending_occ = {}
    new_occ = {}

    for tr in table_elem.find_all("tr"):
        # row-detail 行：CSS display:none 的展开详情，跳过 colspan 展开
        # 收集原始文本到 detail_map，记录其上方最近数据行索引
        tr_classes = tr.get("class") or []
        if "row-detail" in tr_classes:
            detail_text = tr.get_text(separator=" ", strip=True)
            if detail_text:
                # after_row: 上方最近数据行在 rows 中的索引（-1 = 在表头前）
                after_row = len(rows) - 1
                detail_map.append((after_row, detail_text))
            continue

        cells = []
        col = 0
        for td in tr.find_all(["td", "th"]):
            # 跳过被上方 rowspan 占用的列（遗留占用，本行直接留空）
            while pending_occ.get(col, 0) > 0:
                cells.append("")
                col += 1
            # 读取跨度（非法值回退为 1）
            try:
                cs = max(1, int(td.get("colspan", 1)))
            except (TypeError, ValueError):
                cs = 1
            try:
                rs = max(1, int(td.get("rowspan", 1)))
            except (TypeError, ValueError):
                rs = 1
            text = td.get_text(strip=True)
            # 当前行填充 colspan 个文本
            for _ in range(cs):
                cells.append(text)
            # 记录 rowspan 占用：后续行需跳过 rs-1 行（本行已占 1 行）
            if rs > 1:
                for k in range(col, col + cs):
                    new_occ[k] = max(new_occ.get(k, 0), rs - 1)
            # 记录合并区域（rs>1 或 cs>1）
            if rs > 1 or cs > 1:
                merges.append({"r": len(rows), "c": col, "rs": rs, "cs": cs})
            col += cs
        # 行尾补齐剩余 pending 占用列
        while col < max(pending_occ.keys(), default=-1) + 1:
            if pending_occ.get(col, 0) > 0:
                cells.append("")
            col += 1
        # 本行已过去：遗留占用减 1（减到 0 释放），并入本行新设置
        pending_occ = {k: v - 1 for k, v in pending_occ.items() if v > 1}
        for k, v in new_occ.items():
            pending_occ[k] = max(pending_occ.get(k, 0), v)
        new_occ = {}
        rows.append(cells)

    # 统一列数（补齐到最大列宽，rowspan 尾部占位可能造成列数不一致）
    max_cols = max((len(r) for r in rows), default=0)
    for r in rows:
        if len(r) < max_cols:
            r.extend([""] * (max_cols - len(r)))
    return rows, merges, detail_map


def parse_style_blocks(soup):
    """预解析 <style> 块，返回 {selector: {prop: value}} 字典"""
    styles = {}
    if not HAS_CSSUTILS:
        return styles
    for style_tag in soup.find_all("style"):
        try:
            sheet = cssutils.parseString(style_tag.string or "")
            for rule in sheet:
                if hasattr(rule, 'selectorText') and hasattr(rule, 'style'):
                    selector = rule.selectorText
                    props = {}
                    for prop in rule.style:
                        props[prop.name] = prop.value
                    if props:
                        styles[selector] = props
        except Exception:
            pass
    return styles


# ===== 未知图表数据提取（公共函数） =====

def extract_chart_data(section):
    """从未知图表容器中递归提取全部数据（文本+数值属性），返回二维列表。

    被 html2docx_scene.py（Word 端 process_chart_unknown）和 html2md.py
    （Markdown 端 render_chart_unknown）共用，消除重复维护。

    提取策略（按优先级）：
    1. SVG <text> 元素 → 提取文本（轴标签/图例/数据标签）
    2. SVG <rect>/<circle>/<path> 的 data-* 属性 → 提取数值
    3. HTML 子元素的 style="height:X%" / data-value="X" → 提取数值
    4. 递归遍历所有子元素的 get_text() → 提取文本（兜底）

    返回: list[list[str]]，每行是一个数据项（1~N 列）
    如果完全无数据，返回空列表 []。
    """
    data_items = []

    # 1. SVG <text> 元素提取
    svg_texts = []
    for svg in section.find_all("svg"):
        for t in svg.find_all("text"):
            text = get_text_content(t)
            if text:
                svg_texts.append(text.strip())
        # 提取 rect 的 height 属性（CSS 条形图数据）
        for rect in svg.find_all("rect"):
            h = rect.get("height", "")
            if h:
                svg_texts.append(h)
            # data-label 属性
            dl = rect.get("data-label", "") or rect.get("data-value", "")
            if dl:
                svg_texts.append(dl)

    if svg_texts:
        # 尝试配对（标签+值），否则逐个输出
        if len(svg_texts) >= 2:
            # 两两配对
            for i in range(0, len(svg_texts), 2):
                if i + 1 < len(svg_texts):
                    data_items.append([svg_texts[i], svg_texts[i + 1]])
                else:
                    data_items.append([svg_texts[i]])
        else:
            for t in svg_texts:
                data_items.append([t])

    # 2. HTML 子元素的 data-value / data-label 属性
    for child in section.find_all(True):  # 所有后代标签
        dv = child.get("data-value", "")
        dl = child.get("data-label", "")
        if dv and dl:
            data_items.append([dl, dv])
        elif dv:
            data_items.append([dv])
        elif dl:
            data_items.append([dl])

    # 3. CSS 条形图：子元素 style="height:X%" 提取数值
    for child in section.find_all(True):
        style = (child.get("style") or "").lower()
        m = re.search(r'height\s*:\s*(\d+(?:\.\d+)?)\s*%', style)
        if m:
            # 尝试配对标签文字
            label = get_text_content(child)
            if label:
                data_items.append([label, m.group(1) + "%"])
            else:
                data_items.append([m.group(1) + "%"])

    # 4. 递归提取所有文本（兜底）
    if not data_items:
        all_text = get_text_content(section)
        if all_text:
            # 按换行/逗号/竖线分割
            lines = re.split(r'[\n,，|]', all_text)
            for line in lines:
                line = line.strip()
                if line:
                    data_items.append([line])

    # 去重（保持顺序）
    seen = set()
    unique_items = []
    for item in data_items:
        key = tuple(str(x) for x in item)
        if key not in seen:
            seen.add(key)
            unique_items.append(item)

    return unique_items
