#!/usr/bin/env python3
"""
html2pdf.py — 将 html-generator 生成的 HTML 转换为 PDF (.pdf)

用法: python html2pdf.py <input.html> <output.pdf>

核心逻辑（第二版 · 生成放开 / 转换归约）：
1. 使用 Playwright（无头 Chromium）打开 HTML 文件
2. 渲染前 DOM 修复 pass（封面/尾页居中 + 内容恢复 + 图表修复 + 尾部清理）
3. 调用 page.pdf() 生成 PDF
4. 渲染后空白页检测（可选 PyMuPDF，缺失自动降级）
5. PDF 保真度 ~95%（近乎 1:1 还原 HTML 渲染效果；仅动画/过渡不可静态呈现）

依赖：playwright（自动下载 Chromium 内核，首次约 100MB）
      pymupdf（可选，用于渲染后空白页检测；未安装自动降级为警告）
"""

import sys
import os
import asyncio
from urllib.parse import quote_from_bytes

# Windows 下 stdout/stderr 默认可能非 UTF-8（如 GBK），强制设为 UTF-8 避免中文输出乱码
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("[ERROR] 缺少 playwright 依赖，请先运行: pip install playwright && playwright install chromium")
    sys.exit(1)


# ===== PDF 尾页空白页检测（可选依赖 pymupdf）=====
def _detect_and_remove_trailing_blank_pages(pdf_path):
    """渲染后检测：读取 PDF，若最后一页无文本且无图像 → 删除该页另存

    修复问题：封面/尾页 min-height + 内容高度恰好凑出一页空白时，
    Chromium 分页会多生成一个空白尾页。此函数在 PDF 生成后检测并清理。

    依赖：pymupdf（fitz），缺失时降级为警告提示（不影响转换结果）。
    只读检测：绝不改动有内容的页面，仅删除"无文本且无图像"的末尾页。
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        print("[WARN] 未安装 pymupdf，跳过 PDF 尾页空白页检测（不影响转换结果）")
        return
    try:
        doc = fitz.open(pdf_path)
        if doc.page_count <= 1:
            doc.close()
            return
        removed = 0
        # 从末尾往回检查连续空白页
        while doc.page_count > 1:
            page = doc[doc.page_count - 1]
            text = page.get_text().strip()
            images = page.get_images()
            if not text and not images:
                doc.delete_page(doc.page_count - 1)
                removed += 1
            else:
                break
        if removed > 0:
            tmp_path = pdf_path + ".tmp"
            doc.save(tmp_path)
            doc.close()
            os.replace(tmp_path, pdf_path)
            print(f"[INFO] 尾页空白页检测: 删除 {removed} 个末尾空白页")
        else:
            doc.close()
    except Exception as e:
        print(f"[WARN] PDF 尾页空白页检测失败: {e}（不影响转换结果）")


async def convert_html_to_pdf(html_path, pdf_path):
    """主转换函数：使用 Playwright 无头 Chromium 生成 PDF"""
    html_path = os.path.abspath(html_path)
    if not os.path.exists(html_path):
        print(f"[ERROR] 输入文件不存在: {html_path}")
        sys.exit(1)

    # 将路径分段 URL 编码，避免空格/中文/特殊字符导致 Playwright 无法打开
    path_parts = html_path.replace(os.sep, "/").split("/")
    encoded_parts = []
    for part in path_parts:
        if part:
            encoded_parts.append(quote_from_bytes(part.encode("utf-8"), safe=""))
    html_url = "file:///" + "/".join(encoded_parts)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # 打开 HTML 文件
        await page.goto(html_url, wait_until="load")

        # ---- PDF 打印优化（三步法，确保覆盖内联样式）----
        # 步骤 1：切换到 print 媒体模式，激活 @media print 规则
        await page.emulate_media(media="print")

        # 步骤 2：直接操作 DOM，移除 body 的内联 padding/margin
        await page.evaluate("""() => {
            const body = document.body;
            if (body) {
                body.style.padding = '0';
                body.style.margin = '0';
                body.style.setProperty('-webkit-print-color-adjust', 'exact', 'important');
                body.style.setProperty('print-color-adjust', 'exact', 'important');
            }
        }""")

        # 步骤 3：注入打印优化 CSS
        #   - 背景色覆盖整个页面
        #   - 减小 title/end_page padding
        #   - 分页控制（title / end_page / heading level=1 新起一页）
        #   - margin:0 抵消 HTML 中 .title{margin-bottom}/.end_page{margin-top}，
        #     否则封面 273mm + margin 超出单页可用高度，Chromium 分页时会把
        #     封面后的首个标题（如"一、项目概述及必要性"）挤到封面页底部。
        #   - 交互组件静态化：Tab 全部面板展开、折叠全部展开、
        #     搜索框/复制按钮/返回顶部按钮隐藏（交互丢失，内容不丢）
        await page.add_style_tag(content="""
            @media print {
                body {
                    padding: 0 !important;
                    margin: 0 !important;
                    -webkit-print-color-adjust: exact !important;
                    print-color-adjust: exact !important;
                }
                .title, .end_page {
                    display: flex !important;
                    flex-direction: column !important;
                    justify-content: center !important;
                    align-items: center !important;
                    min-height: calc(297mm - 26mm) !important;
                    box-sizing: border-box !important;
                    margin: 0 !important;
                    -webkit-print-color-adjust: exact !important;
                    print-color-adjust: exact !important;
                }
                /* 封面/尾页子元素强制水平居中（防多行标题/副标题内部左对齐） */
                .title > *, .end_page > * {
                    text-align: center !important;
                }
                /* 图表 SVG 响应式：有 viewBox 的 SVG 自动适配父容器宽度，防 PDF 裁切 */
                svg[viewBox] {
                    max-width: 100% !important;
                    height: auto !important;
                }
                /* ===== 分页策略：仅封面/尾页强制分页，其余 section 自然流动 =====
                   mode-deck 等模式骨架在 @media print 中对 .slide 设了
                   page-break-after: always，导致内容短的 section 底部留出大片空白。
                   此处统一覆盖：所有 .slide 的 page-break-after 置为 auto，
                   仅 .title / .end_page 保留强制分页。
                   覆盖所有文档，不限于某个 HTML。 */
                .slide {
                    page-break-after: auto !important;
                    break-after: auto !important;
                }
                .title, .end_page {
                    page-break-after: always !important;
                    break-after: page !important;
                }
                section, div, table, figure {
                    break-inside: auto !important;
                }
                .title, .end_page, .stat {
                    break-inside: avoid !important;
                }
                .card {
                    break-inside: auto !important;
                }
                /* 含柱状图的卡片不允许跨页拆分，防止 chart-row 被截断 */
                .card:has(.chart-row) {
                    break-inside: avoid !important;
                }
                .chart-row {
                    break-inside: avoid !important;
                }
                /* ===== 关闭跨页表格的表头重复 =====
                   Chromium 打印引擎对 <thead> 的默认行为是跨页时在新页顶部自动重复表头
                   （table-header-group），视觉上与正文重复、且对 8-10 行的小表显得多余。
                   将 thead 改为 table-row-group 后：
                   - 表头仍在表格首部正常显示（表格布局不受影响，列宽/对齐不变）
                   - 表格跨页时新页顶部直接接续数据行，不再重复表头
                   实测确认：仅 display 值变化，不破坏 table 布局；
                   副作用是跨页长表在后续页顶部不再有表头提示（阅读长表时需回看首行），
                   这是关闭表头重复的必然代价，与 Word 端"跨页保留表头"行为不同属预期差异。 */
                thead {
                    display: table-row-group !important;
                }
                /* ===== 页脚回到文档流末尾（position:fixed 会在每页重复，盖住正文） ===== */
                .page-footer {
                    position: relative !important;
                    bottom: auto !important;
                    width: 100% !important;
                    max-width: 100% !important;
                }
                /* ===== 交互组件静态化（interactive-pack 降级） =====
                   Tab 面板全部展开；Tab 按钮容器整体隐藏（按钮文字由
                   下方 Tab 篇章标题 pass 提取后插入各面板开头作为标题） */
                .tab-panel {
                    display: block !important;
                }
                .tab-nav {
                    display: none !important;
                }
                /* Tab 篇章标题：由 pass 提取按钮文字插入面板开头 */
                .tab-section-title {
                    font-size: 22px !important;
                    font-weight: 700 !important;
                    margin: 28px 0 12px 0 !important;
                    padding-left: 16px !important;
                    border-left: 4px solid #3b82f6 !important;
                    color: #0f1e33 !important;
                    -webkit-print-color-adjust: exact !important;
                    print-color-adjust: exact !important;
                }
                .collapse-body {
                    max-height: none !important;
                    overflow: visible !important;
                }
                .collapse-arrow {
                    display: none !important;
                }
                /* 自定义折叠箭头（如 .bid-arrow）—— 非 interactive-pack 标准类，
                   但 LLM 生成 HTML 时常自定义箭头元素，转 PDF 时一律隐藏 */
                [class*="-arrow"]:not(.collapse-arrow) {
                    display: none !important;
                }
                /* 自定义折叠体（如 .bid-card-body）—— 与 .collapse-body 同理展开 */
                [class*="-body"][style*="max-height"] {
                    max-height: none !important;
                    overflow: visible !important;
                }
                .table-search-wrap,
                .table-no-result,
                .code-copy-btn,
                .back-to-top {
                    display: none !important;
                }
            }
        """)

        # ---- Tab 篇章标题提取 pass ----
        # 问题：Tab 按钮文字（如"基础篇""进阶篇"）在打印 CSS 中随 .tab-nav 整体隐藏，
        #   导致 PDF 中各面板内容连续铺开，缺少篇章分隔标题。
        # 方案：遍历每组 .tab-nav + .tab-panel，读取按钮文字，在对应面板开头插入
        #   一个 h2 标题元素（带 tab-section-title 类），使篇章标签进入正文流。
        #   与 Word 端 html2docx_scene.py 的处理方式保持一致（提取按钮文字作为面板标题）。
        tab_title_result = await page.evaluate("""() => {
            const stats = { titles_inserted: 0 };
            document.querySelectorAll('.tab-nav').forEach(nav => {
                const btns = nav.querySelectorAll('.tab-btn');
                if (!btns.length) return;
                // 取 tab-nav 之后连续的兄弟 .tab-panel
                const panels = [];
                let sib = nav.nextElementSibling;
                while (sib) {
                    if (sib.classList.contains('tab-panel')) {
                        panels.push(sib);
                        sib = sib.nextElementSibling;
                    } else {
                        break;
                    }
                }
                btns.forEach((btn, i) => {
                    const text = (btn.textContent || '').trim();
                    if (!text || i >= panels.length) return;
                    // 面板开头已存在 .tab-section-title 则跳过（防重复）
                    const existing = panels[i].querySelector(':scope > .tab-section-title');
                    if (existing) return;
                    const h2 = document.createElement('h2');
                    h2.className = 'tab-section-title';
                    h2.textContent = text;
                    panels[i].insertBefore(h2, panels[i].firstChild);
                    stats.titles_inserted++;
                });
            });
            return stats;
        }""")
        if tab_title_result and tab_title_result['titles_inserted']:
            print(f"[INFO] Tab 篇章标题 pass: 提取 {tab_title_result['titles_inserted']} 个按钮文字为面板标题")

        # ---- 问题2：内容恢复 pass ----
        # 折叠卡片、Tab、<details>、自定义折叠体等在打印时可能保持隐藏状态，
        # 导致内容丢失。此 pass 在渲染前强制展开所有含内容的隐藏元素。
        # 注意：仅恢复"有内容价值的隐藏元素"，排除交互控件（按钮/搜索框/返回顶部等）。
        recovery_result = await page.evaluate("""() => {
            const stats = { details_opened: 0, display_restored: 0, maxheight_expanded: 0, visibility_restored: 0 };
            const SKIP_TAGS = new Set(['SCRIPT','STYLE','LINK','META','HEAD','NOSCRIPT','TEMPLATE']);
            const INTERACTIVE = new Set(['tab-btn','tab-nav','collapse-arrow','code-copy-btn','back-to-top',
                'table-search-wrap','table-search-input','table-no-result',
                'toc-sidebar','toc-toggle']);
            function isInteractive(el) {
                const cls = el.classList || [];
                for (const c of cls) { if (INTERACTIVE.has(c) || c.includes('-arrow')) return true; }
                const tag = el.tagName;
                if (tag === 'BUTTON' && !el.querySelector('img,svg,p,div,table')) return true;
                if (tag === 'INPUT' || tag === 'SELECT') return true;
                return false;
            }
            function hasContent(el) {
                if (SKIP_TAGS.has(el.tagName)) return false;
                if (el.querySelector('img,svg,canvas,video,table')) return true;
                return (el.textContent || '').trim().length > 0;
            }

            // 1) <details> 全部展开（语义化折叠内容必须全量呈现）
            document.querySelectorAll('details').forEach(d => {
                if (!d.open) { d.open = true; stats.details_opened++; }
            });

            // 2) display:none 但含内容的元素 → 恢复显示（排除交互控件）
            document.querySelectorAll('*').forEach(el => {
                if (el === document.body || SKIP_TAGS.has(el.tagName)) return;
                const style = getComputedStyle(el);
                if (style.display === 'none' && hasContent(el) && !isInteractive(el)) {
                    let restoreDisplay = 'block';
                    // JS 运行时以内联样式隐藏的元素（如倒计时结束 set display:none）：
                    // 临时移除内联样式，读回样式表中的原始布局值（flex/grid/block 等），
                    // 避免一律恢复为 block 导致 flex/grid 容器子元素纵向堆叠（倒计时竖排问题）。
                    // 仅当移除后仍为 none（元素本身在样式表中即隐藏，如 Tab 面板）时回退 block。
                    if (el.style && el.style.display === 'none') {
                        el.style.removeProperty('display');
                        const original = getComputedStyle(el).display;
                        if (original && original !== 'none') restoreDisplay = original;
                    }
                    // <tr> 恢复为 table-row，避免脱离表格布局导致内容竖排
                    if (el.tagName === 'TR') restoreDisplay = 'table-row';
                    el.style.setProperty('display', restoreDisplay, 'important');
                    stats.display_restored++;
                }
            });

            // 3) max-height 折叠体 → 全部展开（不限于 -body 结尾类名）
            document.querySelectorAll('*').forEach(el => {
                if (el === document.body || SKIP_TAGS.has(el.tagName)) return;
                const style = getComputedStyle(el);
                const mh = style.maxHeight;
                if (mh && mh !== 'none') {
                    const mhNum = parseFloat(mh);
                    if (!isNaN(mhNum) && mhNum < el.scrollHeight && hasContent(el)) {
                        el.style.setProperty('max-height', 'none', 'important');
                        el.style.setProperty('overflow', 'visible', 'important');
                        stats.maxheight_expanded++;
                    }
                }
            });

            // 4) visibility:hidden / opacity:0 含内容元素恢复
            document.querySelectorAll('*').forEach(el => {
                if (el === document.body || SKIP_TAGS.has(el.tagName)) return;
                const style = getComputedStyle(el);
                if ((style.visibility === 'hidden' || parseFloat(style.opacity) === 0) &&
                    hasContent(el) && !isInteractive(el)) {
                    el.style.setProperty('visibility', 'visible', 'important');
                    el.style.setProperty('opacity', '1', 'important');
                    stats.visibility_restored++;
                }
            });
            return stats;
        }""")
        if recovery_result and (recovery_result['details_opened'] or recovery_result['display_restored'] or
                recovery_result['maxheight_expanded'] or recovery_result['visibility_restored']):
            parts = []
            if recovery_result['details_opened']: parts.append(f"展开 {recovery_result['details_opened']} 个 <details>")
            if recovery_result['display_restored']: parts.append(f"恢复 {recovery_result['display_restored']} 个 display:none 元素")
            if recovery_result['maxheight_expanded']: parts.append(f"展开 {recovery_result['maxheight_expanded']} 个 max-height 折叠体")
            if recovery_result['visibility_restored']: parts.append(f"恢复 {recovery_result['visibility_restored']} 个 visibility/opacity 隐藏元素")
            print(f"[INFO] 内容恢复 pass: {'，'.join(parts)}")

        # ---- 问题4：图表 DOM 修复 pass ----
        # 未知图表（SVG / CSS 条形图 / 绝对定位图表等）在打印时可能：
        #   宽度溢出裁切（SVG 宽度已由 CSS svg[viewBox] 规则处理）、
        #   position:absolute 偏移出页、overflow:hidden 裁掉图例/标签。
        # 此 pass 按结构特征修复，不依赖 class 名。
        chart_fix_result = await page.evaluate("""() => {
            const stats = { scrollable_chart_fixed: 0, abs_position_fixed: 0, overflow_hidden_fixed: 0 };

            // 1) 可滚动图表容器缩放（扩展表格缩放逻辑到所有可滚动 div）
            const usablePx = (210 - 24) * 96 / 25.4;
            document.querySelectorAll('div').forEach(div => {
                if (!div.querySelector('svg,canvas,.chart-row,.bar,.legend')) return;
                const style = getComputedStyle(div);
                const isScrollable = style.overflowX === 'auto' || style.overflowX === 'scroll' ||
                    style.overflow === 'auto' || style.overflow === 'scroll';
                if (isScrollable && div.scrollWidth > div.clientWidth) {
                    div.style.overflow = 'visible';
                    let fontSize = parseFloat(style.fontSize);
                    let iters = 0;
                    while (div.scrollWidth > usablePx && fontSize > 4 && iters < 15) {
                        fontSize *= 0.9;
                        div.style.fontSize = fontSize.toFixed(1) + 'px';
                        void div.scrollWidth;
                        iters++;
                    }
                    stats.scrollable_chart_fixed++;
                }
            });

            // 2) position:absolute 修复：图表容器的祖先无定位上下文 → 加 position:relative
            document.querySelectorAll('svg,canvas,.chart-row,.bar').forEach(el => {
                let parent = el.parentElement;
                while (parent && parent !== document.body) {
                    const pStyle = getComputedStyle(parent);
                    if (pStyle.position === 'absolute' || pStyle.position === 'fixed') {
                        let ancestor = parent.parentElement;
                        let hasContext = false;
                        while (ancestor && ancestor !== document.body) {
                            const aStyle = getComputedStyle(ancestor);
                            if (['relative','absolute','fixed','sticky'].includes(aStyle.position)) {
                                hasContext = true; break;
                            }
                            ancestor = ancestor.parentElement;
                        }
                        if (!hasContext && parent.parentElement) {
                            parent.parentElement.style.setProperty('position', 'relative', 'important');
                            stats.abs_position_fixed++;
                        }
                        break;
                    }
                    parent = parent.parentElement;
                }
            });

            // 3) overflow:hidden 含图表内容 → overflow:visible（防图例/标签被裁）
            document.querySelectorAll('div').forEach(div => {
                const style = getComputedStyle(div);
                if ((style.overflow === 'hidden' || style.overflowX === 'hidden') &&
                    div.querySelector('svg,canvas,.chart-labels,.legend')) {
                    if (div.scrollHeight > div.clientHeight || div.scrollWidth > div.clientWidth) {
                        div.style.setProperty('overflow', 'visible', 'important');
                        stats.overflow_hidden_fixed++;
                    }
                }
            });
            return stats;
        }""")
        if chart_fix_result and (chart_fix_result['scrollable_chart_fixed'] or chart_fix_result['abs_position_fixed'] or
                chart_fix_result['overflow_hidden_fixed']):
            parts = []
            if chart_fix_result['scrollable_chart_fixed']: parts.append(f"缩放 {chart_fix_result['scrollable_chart_fixed']} 个可滚动图表容器")
            if chart_fix_result['abs_position_fixed']: parts.append(f"修复 {chart_fix_result['abs_position_fixed']} 个绝对定位偏移")
            if chart_fix_result['overflow_hidden_fixed']: parts.append(f"展开 {chart_fix_result['overflow_hidden_fixed']} 个 overflow:hidden 容器")
            print(f"[INFO] 图表 DOM 修复 pass: {'，'.join(parts)}")

        # ---- 问题3（渲染前）：尾部空容器清理 ----
        # 移除 body 末尾连续的空容器（无文本、无图片、无显式高度），防止 Chromium 产生多余空白页。
        trailing_cleanup_count = await page.evaluate("""() => {
            const SKIP_TAGS = new Set(['SCRIPT','STYLE','LINK','META','HEAD','NOSCRIPT','TEMPLATE']);
            let removed = 0;
            const body = document.body;
            const children = Array.from(body.children);
            for (let i = children.length - 1; i >= 0; i--) {
                const el = children[i];
                if (SKIP_TAGS.has(el.tagName)) continue;
                // 跳过 .title / .end_page（封面/尾页即使内容少也不能删）
                if (el.classList.contains('title') || el.classList.contains('end_page')) break;
                const hasText = (el.textContent || '').trim().length > 0;
                const hasMedia = el.querySelector('img,svg,canvas,video,table');
                // 只删除真正空的容器（无内容且高度极小）
                if (!hasText && !hasMedia && el.offsetHeight < 5) {
                    body.removeChild(el);
                    removed++;
                } else {
                    break;
                }
            }
            return removed;
        }""")
        if trailing_cleanup_count:
            print(f"[INFO] 尾部清理: 移除 {trailing_cleanup_count} 个空容器（防多余空白页）")

        # ---- 可滚动超宽表格自动缩放（如 .gantt-wrap{overflow-x:auto}） ----
        # 仅处理 HTML 中"可横向滑动"的表格（父容器有 overflow-x: auto/scroll）。
        # 这类表格在浏览器中靠滚动条查看完整内容，但转 PDF 时滚动区会被裁切，
        # 因此需缩小 font-size 使其自然排布到页宽内。普通表格不处理。
        # A4 纵向可用宽度 = 210mm - 左右 12mm×2 = 186mm ≈ 703px (96dpi)。
        # 注意：跳过 .gantt-chart（甘特图）。甘特图已设 width:100% 自适应页宽，
        # 不超宽；若强行走缩放，white-space:nowrap + font-size 缩小会改变其
        # 单元格排版，进而影响整页分页（实测会导致封面后首个 h1 被挤到封面页）。
        # 甘特图列多时可自行收缩内容或减少列数，不应依赖此缩放逻辑。
        adjust_count = await page.evaluate("""() => {
            const tables = document.querySelectorAll('table');
            const usablePx = (210 - 24) * 96 / 25.4;
            let n = 0;
            tables.forEach((t) => {
                // 0) 跳过甘特图：gantt-chart 已 width:100% 自适应，不走缩放
                if (t.classList.contains('gantt-chart')) return;
                // 1) 仅处理"可横向滚动"的表格：直接父容器有 overflow-x: auto/scroll
                const parent = t.parentElement;
                if (!parent) return;
                const pStyle = getComputedStyle(parent);
                const isScrollable =
                    pStyle.overflowX === 'auto' || pStyle.overflowX === 'scroll' ||
                    pStyle.overflow === 'auto' || pStyle.overflow === 'scroll';
                if (!isScrollable) return;  // 普通表格跳过

                // 2) 只清除直接父容器的 overflow（解除滚动裁切），保留所有祖先容器 padding
                //    表格仍待在卡片容器内，左右有自然留白，与文档其他内容对齐
                parent.style.overflow = 'visible';

                // 3) 清除单元格 min-width（Chromium 中 min-width 阻止缩放收缩）
                t.querySelectorAll('th, td').forEach((c) => {
                    c.style.minWidth = '0';
                    c.style.whiteSpace = 'nowrap';
                });
                // 4) 用父容器实际内容宽度作为缩放目标（精确值，不用估算）
                //    parent.clientWidth 已包含自身 padding，减去左右 padding 即为表格可用宽度
                const pPadL = parseFloat(pStyle.paddingLeft);
                const pPadR = parseFloat(pStyle.paddingRight);
                const targetWidth = parent.clientWidth - pPadL - pPadR;
                // 5) 先设 width:auto 让表格按内容自然撑开（否则 width:100% 会让 offsetWidth
                //    恒等于容器宽度，缩放循环不触发，但打印时 nowrap 内容仍会溢出）
                const origWidth = t.style.width;
                t.style.width = 'auto';
                // 6) 递归缩小 font-size + padding，直到宽度 <= targetWidth
                let fontSize = parseFloat(getComputedStyle(t).fontSize);
                let iterations = 0;
                while (t.offsetWidth > targetWidth && fontSize > 4 && iterations < 20) {
                    fontSize *= 0.9;
                    t.style.fontSize = fontSize.toFixed(1) + 'px';
                    t.querySelectorAll('th, td').forEach((c) => {
                        c.style.padding = Math.max(1, fontSize * 0.3).toFixed(0) + 'px ' + Math.max(1, fontSize * 0.2).toFixed(0) + 'px';
                    });
                    void t.offsetWidth;
                    iterations++;
                }
                // 7) 缩放完成后设 width:100% 确保表格填满容器，左右边距对称
                t.style.width = '100%';
                if (iterations > 0) n += 1;
            });
            return n;
        }""")
        if adjust_count:
            print(f"[INFO] 已自动缩放 {adjust_count} 个可滚动超宽表格至页面宽度内（内容等比缩小，不裁切）")

        await page.pdf(
            path=pdf_path,
            format="A4",
            margin={
                "top": "12mm",
                "bottom": "12mm",
                "left": "12mm",
                "right": "12mm",
            },
            print_background=True,  # 保留背景色/渐变
            display_header_footer=False,
            prefer_css_page_size=False,
        )

        await browser.close()

    # ---- 问题3（渲染后）：PDF 尾页空白页检测 ----
    _detect_and_remove_trailing_blank_pages(pdf_path)

    print(f"[OK] PDF 文件已生成: {pdf_path}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("用法: python html2pdf.py <input.html> <output.pdf>")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2]

    if not os.path.exists(input_path):
        print(f"[ERROR] 输入文件不存在: {input_path}")
        sys.exit(1)

    asyncio.run(convert_html_to_pdf(input_path, output_path))