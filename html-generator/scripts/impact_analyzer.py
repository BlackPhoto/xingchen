#!/usr/bin/env python3
"""
impact_analyzer.py — 转换前影响分析模块（第二版 · 语义 class 版）

用法:
  python impact_analyzer.py <input.html> [--format docx|pdf|md] [--json]

功能：扫描 HTML 中使用的 IR 语义类型和 CSS 特性，生成影响清单。
- 只有存在会降级或丢失的块/特性时才输出提醒
- 全是基础语义 class（title/heading/paragraph/list/table/image）且无装饰性 CSS
  时输出"无需提醒"（need_remind=false）
- 影响清单按 IR 语义类型报告"什么会变成什么"

--json 模式：输出结构化 JSON，供 LLM 解析后向用户确认（Agent 场景使用）。
  示例输出: {"need_remind": true, "format": "docx", "items": ["...", "..."]}

Markdown 特别说明：Markdown 只做结构保真（标题/列表/表格/代码块），
视觉样式天然不保留不逐项提醒。但结构降级（卡片→列表、时间线→有序列表等）
仍需提醒，因此 md 格式做精简版影响分析（只报结构降级，不报视觉降级）。

依赖：sem_common（公共语义识别层）
"""

import sys
import os
import json
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
    print("[ERROR] 缺少 beautifulsoup4 依赖")
    sys.exit(1)

# 公共语义识别层（与 html2docx / html2md 共用同一份逻辑）
from sem_common import find_semantic_class, classify_element


# 基础语义（转换无损，无需提醒）
BASIC_CLASSES = {"title", "heading", "paragraph", "list", "table", "image"}

# Word 降级映射（IR 语义 → 说明）
# 注：code_block 在 Word 中保留（等宽字体），不算降级，故不在此列出
WORD_DEGRADATION = {
    "stat_block": "将降级为普通表格",
    "callout": "将降级为带底色段落",
    "timeline": "将降级为两列表格（时间样式丢失）",
    "hero_banner": "将降级为标题段落",
    "card_grid": "将降级为普通表格",
    "divider": "保留（字符饰线）",
    "quote": "将降级为缩进段落",
    "columns": "将降级为表格列",
    "compare_cards": "将降级为并排表格列",
    "comparison": "用表格实现",
    "faq": "将降级为加粗问题+段落",
    "badge_group": "将降级为逗号分隔文本（圆角丢失）",
    "gallery": "将降级为图片纵列",
    "pricing_table": "用表格实现",
    "icon_list": "将降级为普通列表（图标丢失）",
    "end_page": "保留",
    "task_list": "任务卡片将降级为一行式表格（编号 | 标题+描述 | 难度）",
    "demo_grid": "模拟界面网格将重建为表格（窗口装饰丢失，数据结构保留）",
    "auto_table": "规律性重复结构将重建为表格（网格布局保留，装饰丢失）",
    "mini_chart": "迷你图/柱状图将降级为数据标签文本（图形视觉丢失，数据保留）",
    "stat_table": "指标数据行将重建为无边框表格（值+说明成列）",
    "chart_unknown": "未知图表将降级为截图或数据重建表格/列表（图形视觉丢失，数据保留）",
    "collapse_group": "折叠内容将全部展开（内容保留）",
    # cite/source-list 是段落内联 / 列表容器，不产生独立 IR 块，不在此列出。
    # 其处理由段落/列表流程内联完成（cite → 上标文本，source-list → 有序列表），无降级。
}

# CSS 特性 Word 丢失/降级映射
WORD_CSS_DEGRADATION = {
    "gradient_background": "渐变背景将降级为纯色",
    "border_radius": "圆角效果将丢失",
    "box_shadow": "阴影效果将丢失",
    "flexbox_grid": "Flexbox/Grid 布局将重建为表格",
    "position_float": "定位/浮动将丢失",
    "transform_animation": "变换/动画将丢失",
    "svg_inline": "SVG 将降级为 PNG",
    "merged_cell": "合并单元格将在 Word 中重建（跨列/跨行合并保留）",
}

# Markdown 合并单元格降级说明（Markdown 不支持合并，展开填充属预期行为）
MD_MERGED_CELL_DEGRADATION = "表格含合并单元格，Markdown 将展开为平铺单元格（跨列/跨行合并不保留）"

# PDF 已知问题映射
PDF_KNOWN_ISSUES = {
    "transform_animation": "动画/过渡效果将不可静态呈现",
    "position_float": "浮动定位在 PDF 分页处可能位置偏移",
}

# 交互组件特征（检测 HTML 中的交互增强包组件，见 references/interactive-pack.md）
# 每项: (class 特征, 降级描述)
INTERACTIVE_FEATURES = [
    ("tab-nav", "Tab 切换交互 → Word/PDF 全部面板展开（内容不丢）"),
    ("table-search-input", "表格搜索 → Word/PDF 保留完整表格（无搜索功能）"),
    ("collapse-trigger", "折叠展开交互 → Word/PDF 全部展开为段落（内容不丢，含 demo-grid 网格重建为表格）"),
    ("code-copy-btn", "代码复制按钮 → Word/PDF/Markdown 按钮丢失，代码保留"),
    ("back-to-top", "返回顶部按钮 → Word/PDF/Markdown 按钮丢失（无影响）"),
]

# Markdown 交互组件降级描述
INTERACTIVE_FEATURES_MD = [
    ("tab-nav", "Tab 切换交互 → 全部面板展开（内容保留）"),
    ("table-search-input", "表格搜索 → 保留完整表格（无搜索功能）"),
    ("collapse-trigger", "折叠展开交互 → 全部展开为段落（内容保留，含 demo-grid 网格重建为表格）"),
    ("code-copy-btn", "代码复制按钮 → 按钮丢失，代码保留"),
    ("back-to-top", "返回顶部按钮 → 按钮丢失（无影响）"),
]

# Markdown 结构降级映射（IR 语义 → 说明）
# 只报结构重塑（卡片→列表、时间线→有序列表等），不报视觉降级（颜色/渐变/阴影等天然不保留属预期行为）
MARKDOWN_DEGRADATION = {
    "stat_block": "数字指标卡将变为加粗数字文本（卡片布局丢失）",
    "callout": "提示/警告块将变为引用块（变体类型丢失）",
    "timeline": "时间线将变为有序列表（时间线样式丢失）",
    "hero_banner": "横幅将变为标题（装饰布局丢失）",
    "card_grid": "卡片网格将变为分组标题+列表（卡片布局丢失）",
    "columns": "多栏布局将变为分组标题+列表（多栏结构丢失）",
    "compare_cards": "对比卡片将变为两组标题+列表（并排布局丢失）",
    "comparison": "左右对比将变为两组标题+列表（对比布局丢失）",
    "faq": "问答将变为加粗问题+正文",
    "badge_group": "标签组将变为逗号分隔文本（标签样式丢失）",
    "gallery": "图片画廊将变为图片逐个输出（网格布局丢失）",
    "icon_list": "图标列表将变为普通列表（图标丢失）",
    "tab_group": "Tab 面板将全部展开（内容保留）",
    "collapse_group": "折叠内容将全部展开（内容保留）",
    "task_list": "任务卡片将变为加粗标题+描述（卡片布局丢失）",
    "demo_grid": "模拟界面网格将重建为表格（窗口装饰丢失，数据结构保留）",
    "auto_table": "规律性重复结构将重建为表格（网格布局保留，装饰丢失）",
    "mini_chart": "迷你图/柱状图将变为数据标签文本（图形视觉丢失，数据保留）",
    "stat_table": "指标数据将重建为 Markdown 表格（值+说明成列）",
    "chart_unknown": "未知图表将提取数据重建为表格/列表（图形视觉丢失，数据保留）",
}

# cite / source-list 处理说明（供分析函数注释引用）
# - cite：段落内联标签，Word 转上标文本 + 内部书签链接；Markdown 输出 [N] 纯文本。无结构降级。
# - source-list：普通有序列表容器，内部 class="list" 的 <ol> 按列表语义处理；无结构降级。


def scan_interactive_features(body, target_format="docx"):
    """扫描交互增强组件（interactive-pack），返回命中的降级描述列表"""
    features = INTERACTIVE_FEATURES_MD if target_format == "md" else INTERACTIVE_FEATURES
    items = []
    for cls, desc in features:
        if body.find(class_=cls) is not None:
            items.append(desc)
    return items


def collect_ir_types(body):
    """扫描 body，收集所有 IR 语义类型 + 语义 class 出现次数"""
    ir_types = set()
    class_counts = {}

    def visit(container):
        for child in container.children:
            if not isinstance(child, Tag):
                continue
            if child.name == "style":
                continue
            scls = find_semantic_class(child)
            if scls:
                class_counts[scls] = class_counts.get(scls, 0) + 1
                ir = classify_element(child)
                if ir:
                    ir_types.add(ir)
                continue
            child_classes = child.get("class") or []
            # task-item（无语义 class 的任务卡片）→ task_list
            if "task-item" in child_classes:
                ir_types.add("task_list")
                continue
            # demo-grid（模拟界面网格）→ demo_grid
            if "demo-grid" in child_classes:
                ir_types.add("demo_grid")
                continue
            # compare-grid（无语义 class 的对比卡片组）
            if child.name == "div" and "compare-grid" in child_classes:
                compare_cards = [c for c in child.children if isinstance(c, Tag)
                                and "compare-card" in (c.get("class") or [])]
                if len(compare_cards) >= 2:
                    ir_types.add("compare_cards")
                    continue
            # 聚合组
            grouped = False
            for gcls in ("stat", "card"):
                members = [c for c in child.children if isinstance(c, Tag) and find_semantic_class(c) == gcls]
                if len(members) >= 2:
                    ir = "stat_block" if gcls == "stat" else "card_grid"
                    ir_types.add(ir)
                    # 聚合组内的成员由容器统一处理，不计入独立 class 统计
                    grouped = True
                    break
            if grouped:
                continue
            ir = classify_element(child)
            if ir:
                ir_types.add(ir)
            elif child.get_text(strip=True):
                tag_children = [c for c in child.children if isinstance(c, Tag)]
                if tag_children:
                    visit(child)

    visit(body)
    return ir_types, class_counts


def scan_css_features(body):
    """扫描 CSS 特性"""
    css_features = set()
    all_styles = ""
    for elem in body.find_all(True):
        style = elem.get("style", "")
        if style:
            all_styles += style + "; "
        if elem.get("data-layout") or elem.get("data-cols"):
            css_features.add("flexbox_grid")
        if elem.get("data-float") and elem["data-float"] in ("left", "right", "wrap"):
            css_features.add("position_float")
        # colspan/rowspan 检测：Word 中重建合并，Markdown 展开填充
        if elem.name in ("td", "th") and (elem.get("colspan") or elem.get("rowspan")):
            try:
                cs = int(elem.get("colspan", 1))
            except (TypeError, ValueError):
                cs = 1
            try:
                rs = int(elem.get("rowspan", 1))
            except (TypeError, ValueError):
                rs = 1
            if cs > 1 or rs > 1:
                css_features.add("merged_cell")

    # <style> 块
    for style_tag in body.find_all("style"):
        style_text = style_tag.string or ""
        all_styles += style_text + "; "

    if "gradient" in all_styles or "linear-gradient" in all_styles:
        css_features.add("gradient_background")
    if "border-radius" in all_styles:
        css_features.add("border_radius")
    if "box-shadow" in all_styles:
        css_features.add("box_shadow")
    if re.search(r'position\s*:\s*(absolute|relative|fixed|sticky)\b', all_styles):
        css_features.add("position_float")
    if "transform" in all_styles or "animation" in all_styles or "transition" in all_styles:
        css_features.add("transform_animation")

    if body.find("svg"):
        css_features.add("svg_inline")

    return css_features


def analyze_html(html_path, target_format="docx"):
    """分析 HTML 文件，返回影响清单

    Returns:
        dict: {"need_remind": bool, "items": [str, ...], "format": str}
    """
    with open(html_path, "r", encoding="utf-8-sig") as f:
        soup = BeautifulSoup(f.read(), "lxml")

    body = soup.find("body")
    if not body:
        return {"need_remind": False, "items": [], "format": target_format}

    ir_types, class_counts = collect_ir_types(body)
    css_features = scan_css_features(body)
    interactive_items = scan_interactive_features(body, target_format)

    # Markdown：精简版影响分析——只报结构降级，不报视觉降级
    if target_format == "md":
        items = list(interactive_items)
        for ir in sorted(ir_types):
            if ir in MARKDOWN_DEGRADATION:
                items.append(MARKDOWN_DEGRADATION[ir])
        if "merged_cell" in css_features:
            items.append(MD_MERGED_CELL_DEGRADATION)
        return {"need_remind": len(items) > 0, "items": items, "format": target_format}

    # PDF：视觉保真度高，仅少量已知限制 + 交互组件降级
    if target_format == "pdf":
        items = []
        for feature in sorted(css_features):
            if feature in PDF_KNOWN_ISSUES:
                items.append(PDF_KNOWN_ISSUES[feature])
        items.extend(interactive_items)
        return {"need_remind": len(items) > 0, "items": items, "format": target_format}

    # Word：生成影响清单
    items = list(interactive_items)

    # 非基础语义 class 的降级提醒
    for cls in sorted(class_counts):
        if cls in BASIC_CLASSES:
            continue
        # 将语义 class 映射到 IR 类型做降级描述
        ir_map = {
            "stat": "stat_block", "callout": "callout", "timeline": "timeline",
            "code": "code_block", "card": "card_grid", "table": "table",
            "image": "image", "list": "bullet_list", "title": "title_page",
            "heading": "heading", "paragraph": "paragraph",
        }
        ir = ir_map.get(cls)
        if ir in WORD_DEGRADATION and ir not in BASIC_CLASSES:
            count = class_counts[cls]
            items.append(f"有 {count} 个 {cls} {WORD_DEGRADATION[ir]}")

    # 聚合组产生的 stat_block/card_grid（无语义 class 容器，且非重复统计）
    # 聚合组内的 stat/card 元素本身已计入 class_counts，
    # 但容器的聚合效果（多列并排 → 表格）需要额外提醒
    if "stat_block" in ir_types and "stat" in class_counts:
        items.append("并列 stat 指标卡将合并为表格行")
    elif "stat_block" in ir_types:
        items.append("有 stat 指标卡将降级为普通表格")
    if "card_grid" in ir_types and "card" in class_counts:
        items.append("并列 card 卡片将合并为表格行")
    elif "card_grid" in ir_types:
        items.append("有 card 卡片将降级为普通表格")

    # task_list 提醒（.task-item 任务卡片）
    if "task_list" in ir_types:
        items.append(WORD_DEGRADATION["task_list"])

    # mini_chart 提醒（迷你图/柱状图卡）
    if "mini_chart" in ir_types:
        items.append(WORD_DEGRADATION["mini_chart"])

    # stat_table 提醒（stat-inline 指标行）
    if "stat_table" in ir_types:
        items.append(WORD_DEGRADATION["stat_table"])

    # chart_unknown 提醒（未知图表/图形容器）
    if "chart_unknown" in ir_types:
        items.append(WORD_DEGRADATION["chart_unknown"])

    # CSS 特性降级提醒
    for feature in sorted(css_features):
        if feature in WORD_CSS_DEGRADATION:
            items.append(WORD_CSS_DEGRADATION[feature])

    need_remind = len(items) > 0
    return {"need_remind": need_remind, "items": items, "format": target_format}


def format_output(result):
    """格式化输出影响清单（人类可读模式）"""
    fmt_map = {"docx": "Word", "pdf": "PDF", "md": "Markdown"}
    fmt_label = fmt_map.get(result.get("format"), result.get("format", ""))

    if not result["need_remind"]:
        print(f"[OK] 全部为基础内容，转换无降级，无需提醒")
        return

    print(f"[提醒] 以下内容在 {fmt_label} 转换中将发生降级或限制：")
    for item in result["items"]:
        print(f"  - {item}")
    print("是否继续转换？（由入口脚本或 LLM 处理确认逻辑）")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python impact_analyzer.py <input.html> [--format docx|pdf|md] [--json]")
        sys.exit(1)

    html_path = sys.argv[1]
    fmt = "docx"
    use_json = False

    args = sys.argv[2:]
    i = 0
    while i < len(args):
        if args[i] == "--format" and i + 1 < len(args):
            fmt = args[i + 1]
            i += 2
        elif args[i] == "--json":
            use_json = True
            i += 1
        else:
            i += 1

    if not os.path.exists(html_path):
        print(f"[ERROR] 输入文件不存在: {html_path}")
        sys.exit(1)

    result = analyze_html(html_path, fmt)

    if use_json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        format_output(result)

    sys.exit(1 if result["need_remind"] else 0)
