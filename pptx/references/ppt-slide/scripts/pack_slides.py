#!/usr/bin/env python3
"""
PPT HTML Slide Packer
======================
Reads slide_*.html files from output directory and generates:
  1. index.html         - Multi-file viewer (iframe src, for local preview)
  2. {title}{MMDD}.html - Single-file viewer (srcdoc iframes, for sharing & editing)

Both feature:
  - iframe isolation (no CSS conflicts between slides)
  - Dynamic viewport scaling (JavaScript, any screen size)
  - Professional dark-theme navigation
  - Top info bar with title + page-jump input
  - Side-positioned prev/next buttons
  - Bottom page-dot indicator
  - Keyboard shortcuts (arrows, Home/End)
  - Touch swipe support
  - Backdrop blur effects

Single-file format:
  - Slide HTML is embedded in <script type="text/html"> blocks (not base64)
  - Users can directly read and edit the HTML source of each slide
  - Navigation JS reads .textContent from the template blocks and sets iframe.srcdoc

Usage:
  python pack_slides.py [output_dir] [title] [theme_name]
  python pack_slides.py output/
  python pack_slides.py output/ "My Presentation"
  python pack_slides.py output/ "My Presentation" party-red-gold

theme_name (optional): key from color-themes.json. When provided,
the navigation bar accent (input focus, hover, active dot) follows the
theme's primary accent color instead of the hardcoded blue.
"""

import sys
import os
import re
import glob
import json
import html as html_mod
from datetime import date


# ============================================================
# Shared Navigation CSS (injected into both output files)
# ============================================================

NAV_CSS = """\
/* Navigation chrome. Theme accent is injected via __NAV_ACCENT__ /
   __NAV_ACCENT_RGB__ placeholders at render time; when no theme is given
   the placeholders fall back to the classic blue accent. */
* { margin: 0; padding: 0; box-sizing: border-box; }

body {
  background: #1a1a2e;
  font-family: "Microsoft YaHei", "PingFang SC", "Helvetica Neue", Arial, sans-serif;
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  user-select: none;
}

/* --- Top Bar --- */
.top-bar {
  height: 40px;
  flex-shrink: 0;
  background: rgba(0,0,0,0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  color: #cbd5e1;
  font-size: 14px;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border-bottom: 1px solid rgba(255,255,255,0.08);
}
.top-bar .title-text { color: #f1f5f9; font-weight: 600; letter-spacing: 1px; }
.top-bar .sep { color: rgba(255,255,255,0.2); }
.top-bar input {
  width: 52px;
  text-align: center;
  background: rgba(255,255,255,0.1);
  border: 1px solid rgba(255,255,255,0.2);
  color: #f1f5f9;
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 14px;
  outline: none;
}
.top-bar input:focus { border-color: __NAV_ACCENT__; background: rgba(__NAV_ACCENT_RGB__,0.15); }
.top-bar .hint { color: rgba(255,255,255,0.35); font-size: 12px; }

/* --- Viewer --- */
.viewer {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}
#slideFrame {
  border: none;
  width: 1280px;
  height: 768px;
  background: #fff;
  box-shadow: 0 8px 40px rgba(0,0,0,0.5);
  border-radius: 4px;
  transform-origin: center center;
}

/* --- Side Nav Buttons --- */
.nav-btn {
  position: fixed;
  top: 50%;
  transform: translateY(-50%);
  width: 52px;
  height: 80px;
  border: none;
  border-radius: 8px;
  background: rgba(255,255,255,0.08);
  color: #cbd5e1;
  font-size: 28px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.2s, color 0.2s;
  z-index: 100;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}
.nav-btn:hover { background: rgba(__NAV_ACCENT_RGB__,0.3); color: #fff; }
.nav-btn:active { background: rgba(__NAV_ACCENT_RGB__,0.5); }
.nav-btn.disabled { opacity: 0.15; pointer-events: none; }
.btn-prev { left: 12px; }
.btn-next { right: 12px; }

/* --- Bottom Dots --- */
.bottom-bar {
  height: 48px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}
.dots {
  display: flex;
  gap: 5px;
  padding: 6px 14px;
  background: rgba(0,0,0,0.5);
  border-radius: 20px;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  max-width: 80vw;
  overflow-x: auto;
  scrollbar-width: none;
}
.dots::-webkit-scrollbar { display: none; }
.dot {
  flex-shrink: 0;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: rgba(255,255,255,0.2);
  cursor: pointer;
  transition: background 0.2s, transform 0.2s;
}
.dot:hover { background: rgba(255,255,255,0.5); }
.dot.active {
  background: __NAV_ACCENT__;
  transform: scale(1.3);
  box-shadow: 0 0 6px rgba(__NAV_ACCENT_RGB__,0.5);
}
"""


# ============================================================
# HTML Generators
# ============================================================

def _load_theme_accent(theme_name=None):
    """
    Resolve the navigation accent color from color-themes.json.

    - theme_name: key under themes{} (e.g. 'party-red-gold'). None → fallback.
    - Returns (accent_hex, accent_rgb) where accent_hex is a #RRGGBB string and
      accent_rgb is a comma-separated 'r,g,b' usable inside rgba()/box-shadow.
    - Lookup order: primary.accent → primary.main → classic blue #2b7de9.
      Unknown theme or missing file falls back to the classic blue.
    """
    fallback_hex = '#2b7de9'
    fallback_rgb = '43,125,233'

    if not theme_name:
        return fallback_hex, fallback_rgb

    # Locate color-themes.json relative to this script
    themes_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               '..', 'color-themes.json')
    try:
        with open(themes_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return fallback_hex, fallback_rgb

    theme = (data.get('themes') or {}).get(theme_name) or {}
    primary = theme.get('primary') or {}
    accent_hex = primary.get('accent') or primary.get('main') or fallback_hex

    # Convert #RRGGBB to 'R,G,B' (also accept #RGB shorthand)
    hex_str = accent_hex.lstrip('#').strip()
    if len(hex_str) == 3:
        hex_str = ''.join(ch * 2 for ch in hex_str)
    try:
        rgb = tuple(int(hex_str[i:i + 2], 16) for i in (0, 2, 4))
        return accent_hex, '%d,%d,%d' % rgb
    except ValueError:
        return fallback_hex, fallback_rgb


def render_nav_css(theme_name=None):
    """Render NAV_CSS with theme accent injected (fallback to classic blue)."""
    accent_hex, accent_rgb = _load_theme_accent(theme_name)
    return (NAV_CSS
            .replace('__NAV_ACCENT__', accent_hex)
            .replace('__NAV_ACCENT_RGB__', accent_rgb))


def _esc(s):
    """HTML-escape a string for safe embedding."""
    return html_mod.escape(str(s), quote=True)


def gen_index_html(title, total, theme_name=None):
    """
    Generate multi-file index.html.
    Uses <iframe src='slide_XX.html'> — CSS naturally isolated per iframe.
    All slide_*.html files must exist in the same directory.
    """
    t = _esc(title)
    return (
        '<!DOCTYPE html>\n'
        '<html lang="zh-CN">\n'
        '<head>\n'
        '<meta charset="UTF-8">\n'
        f'<title>{t}</title>\n'
        f'<style>\n{render_nav_css(theme_name)}\n</style>\n'
        '</head>\n'
        '<body>\n'
        '<div class="top-bar">\n'
        f'  <span class="title-text">{t}</span>\n'
        '  <span class="sep">|</span>\n'
        f'  <span>第 <input type="text" id="pageInput" value="1"> / {total} 页</span>\n'
        '  <span class="sep">|</span>\n'
        '  <span class="hint">&larr; &rarr; &uarr; &darr; 翻页</span>\n'
        '</div>\n'
        '<button class="nav-btn btn-prev disabled" id="btnPrev">&#9664;</button>\n'
        '<button class="nav-btn btn-next" id="btnNext">&#9654;</button>\n'
        '<div class="viewer">\n'
        '  <iframe id="slideFrame"></iframe>\n'
        '</div>\n'
        '<div class="bottom-bar">\n'
        '  <div class="dots" id="dots"></div>\n'
        '</div>\n'
        '<script>\n'
        f'var TOTAL = {total};\n'
        'var current = 1;\n'
        'var frame = document.getElementById("slideFrame");\n'
        'var pageInput = document.getElementById("pageInput");\n'
        'var btnPrev = document.getElementById("btnPrev");\n'
        'var btnNext = document.getElementById("btnNext");\n'
        'var dotsCt = document.getElementById("dots");\n'
        '\n'
        'for (var i = 1; i <= TOTAL; i++) {\n'
        '  var d = document.createElement("div");\n'
        '  d.className = "dot" + (i === 1 ? " active" : "");\n'
        '  d.dataset.page = i;\n'
        '  d.onclick = function() { goTo(parseInt(this.dataset.page)); };\n'
        '  dotsCt.appendChild(d);\n'
        '}\n'
        '\n'
        'function loadSlide(n) {\n'
        '  frame.src = "slide_" + String(n).padStart(2, "0") + ".html";\n'
        '}\n'
        '\n'
        'function goTo(n) {\n'
        '  if (n < 1 || n > TOTAL) return;\n'
        '  current = n;\n'
        '  loadSlide(n);\n'
        '  pageInput.value = n;\n'
        '  btnPrev.classList.toggle("disabled", n === 1);\n'
        '  btnNext.classList.toggle("disabled", n === TOTAL);\n'
        '  var dots = dotsCt.children;\n'
        '  for (var i = 0; i < dots.length; i++) dots[i].classList.toggle("active", i === n - 1);\n'
        '  var ad = dots[n - 1];\n'
        '  if (ad) dotsCt.scrollLeft = ad.offsetLeft - dotsCt.offsetWidth / 2 + ad.offsetWidth / 2;\n'
        '}\n'
        '\n'
        'function go(dir) { goTo(current + dir); }\n'
        'btnPrev.onclick = function() { go(-1); };\n'
        'btnNext.onclick = function() { go(1); };\n'
        '\n'
        'document.addEventListener("keydown", function(e) {\n'
        '  if (document.activeElement === pageInput) {\n'
        '    if (e.key === "Enter") {\n'
        '      var v = parseInt(pageInput.value, 10);\n'
        '      if (!isNaN(v) && v >= 1 && v <= TOTAL) goTo(v);\n'
        '      pageInput.blur();\n'
        '    }\n'
        '    return;\n'
        '  }\n'
        '  switch (e.key) {\n'
        '    case "ArrowRight": case "ArrowDown": e.preventDefault(); go(1); break;\n'
        '    case "ArrowLeft":  case "ArrowUp":   e.preventDefault(); go(-1); break;\n'
        '    case "Home": e.preventDefault(); goTo(1); break;\n'
        '    case "End":  e.preventDefault(); goTo(TOTAL); break;\n'
        '  }\n'
        '});\n'
        '\n'
        'var tx = 0, ty = 0;\n'
        'document.addEventListener("touchstart", function(e) { tx = e.touches[0].clientX; ty = e.touches[0].clientY; });\n'
        'document.addEventListener("touchend", function(e) {\n'
        '  var dx = e.changedTouches[0].clientX - tx, dy = e.changedTouches[0].clientY - ty;\n'
        '  if (Math.abs(dx) > Math.abs(dy) && Math.abs(dx) > 50) { dx > 0 ? go(-1) : go(1); }\n'
        '});\n'
        '\n'
        'function updateScale() {\n'
        '  var v = document.querySelector(".viewer");\n'
        '  var s = Math.min(v.clientWidth / 1280, v.clientHeight / 768, 1);\n'
        '  frame.style.transform = "scale(" + s + ")";\n'
        '}\n'
        'window.addEventListener("resize", updateScale);\n'
        '\n'
        'loadSlide(1);\n'
        'updateScale();\n'
        '</script>\n'
        '</body>\n'
        '</html>'
    )


def gen_packed_html(title, total, slide_html_list, theme_name=None):
    """
    Generate single-file {title}{MMDD}.html.
    Uses <script type="text/html"> blocks + iframe.srcdoc — CSS fully isolated,
    zero external dependencies, HTML source is human-readable and editable.
    Each slide HTML is embedded verbatim in a <script type="text/html"> block.
    """
    t = _esc(title)

    # Build <script type="text/html"> blocks for each slide
    slide_blocks = []
    for i, html_content in enumerate(slide_html_list):
        slide_blocks.append(
            f'<script type="text/html" id="slide-{i + 1}">\n'
            + html_content
            + '\n</script>'
        )
    slides_section = '\n'.join(slide_blocks)

    return (
        '<!DOCTYPE html>\n'
        '<html lang="zh-CN">\n'
        '<head>\n'
        '<meta charset="UTF-8">\n'
        f'<title>{t}</title>\n'
        f'<style>\n{render_nav_css(theme_name)}\n</style>\n'
        '</head>\n'
        '<body>\n'
        '\n'
        '<!-- ============================================ -->\n'
        '<!-- Slide HTML Templates (directly editable)    -->\n'
        '<!-- Find slide-N and edit the HTML inside       -->\n'
        '<!-- ============================================ -->\n'
        f'{slides_section}\n'
        '\n'
        '<!-- ============================================ -->\n'
        '<!-- Navigation UI & Logic                       -->\n'
        '<!-- ============================================ -->\n'
        '<div class="top-bar">\n'
        f'  <span class="title-text">{t}</span>\n'
        '  <span class="sep">|</span>\n'
        f'  <span>第 <input type="text" id="pageInput" value="1"> / {total} 页</span>\n'
        '  <span class="sep">|</span>\n'
        '  <span class="hint">&larr; &rarr; &uarr; &darr; 翻页</span>\n'
        '</div>\n'
        '<button class="nav-btn btn-prev disabled" id="btnPrev">&#9664;</button>\n'
        '<button class="nav-btn btn-next" id="btnNext">&#9654;</button>\n'
        '<div class="viewer">\n'
        '  <iframe id="slideFrame"></iframe>\n'
        '</div>\n'
        '<div class="bottom-bar">\n'
        '  <div class="dots" id="dots"></div>\n'
        '</div>\n'
        '<script>\n'
        f'var TOTAL = {total};\n'
        'var current = 1;\n'
        'var frame = document.getElementById("slideFrame");\n'
        'var pageInput = document.getElementById("pageInput");\n'
        'var btnPrev = document.getElementById("btnPrev");\n'
        'var btnNext = document.getElementById("btnNext");\n'
        'var dotsCt = document.getElementById("dots");\n'
        '\n'
        'for (var i = 1; i <= TOTAL; i++) {\n'
        '  var d = document.createElement("div");\n'
        '  d.className = "dot" + (i === 1 ? " active" : "");\n'
        '  d.dataset.page = i;\n'
        '  d.onclick = function() { goTo(parseInt(this.dataset.page)); };\n'
        '  dotsCt.appendChild(d);\n'
        '}\n'
        '\n'
        'function loadSlide(n) {\n'
        '  var template = document.getElementById("slide-" + n);\n'
        '  if (template) frame.srcdoc = template.textContent;\n'
        '}\n'
        '\n'
        'function goTo(n) {\n'
        '  if (n < 1 || n > TOTAL) return;\n'
        '  current = n;\n'
        '  loadSlide(n);\n'
        '  pageInput.value = n;\n'
        '  btnPrev.classList.toggle("disabled", n === 1);\n'
        '  btnNext.classList.toggle("disabled", n === TOTAL);\n'
        '  var dots = dotsCt.children;\n'
        '  for (var i = 0; i < dots.length; i++) dots[i].classList.toggle("active", i === n - 1);\n'
        '  var ad = dots[n - 1];\n'
        '  if (ad) dotsCt.scrollLeft = ad.offsetLeft - dotsCt.offsetWidth / 2 + ad.offsetWidth / 2;\n'
        '}\n'
        '\n'
        'function go(dir) { goTo(current + dir); }\n'
        'btnPrev.onclick = function() { go(-1); };\n'
        'btnNext.onclick = function() { go(1); };\n'
        '\n'
        'document.addEventListener("keydown", function(e) {\n'
        '  if (document.activeElement === pageInput) {\n'
        '    if (e.key === "Enter") {\n'
        '      var v = parseInt(pageInput.value, 10);\n'
        '      if (!isNaN(v) && v >= 1 && v <= TOTAL) goTo(v);\n'
        '      pageInput.blur();\n'
        '    }\n'
        '    return;\n'
        '  }\n'
        '  switch (e.key) {\n'
        '    case "ArrowRight": case "ArrowDown": e.preventDefault(); go(1); break;\n'
        '    case "ArrowLeft":  case "ArrowUp":   e.preventDefault(); go(-1); break;\n'
        '    case "Home": e.preventDefault(); goTo(1); break;\n'
        '    case "End":  e.preventDefault(); goTo(TOTAL); break;\n'
        '  }\n'
        '});\n'
        '\n'
        'var tx = 0, ty = 0;\n'
        'document.addEventListener("touchstart", function(e) { tx = e.touches[0].clientX; ty = e.touches[0].clientY; });\n'
        'document.addEventListener("touchend", function(e) {\n'
        '  var dx = e.changedTouches[0].clientX - tx, dy = e.changedTouches[0].clientY - ty;\n'
        '  if (Math.abs(dx) > Math.abs(dy) && Math.abs(dx) > 50) { dx > 0 ? go(-1) : go(1); }\n'
        '});\n'
        '\n'
        'function updateScale() {\n'
        '  var v = document.querySelector(".viewer");\n'
        '  var s = Math.min(v.clientWidth / 1280, v.clientHeight / 768, 1);\n'
        '  frame.style.transform = "scale(" + s + ")";\n'
        '}\n'
        'window.addEventListener("resize", updateScale);\n'
        '\n'
        'loadSlide(1);\n'
        'updateScale();\n'
        '</script>\n'
        '</body>\n'
        '</html>'
    )


# ============================================================
# Main
# ============================================================

def _sanitize_filename(name):
    """Remove characters invalid in filenames across platforms (Windows + macOS + Linux)."""
    return re.sub(r'[\\/:*?"<>|]', '', name).strip()


def main():
    output_dir = sys.argv[1] if len(sys.argv) > 1 else 'output'
    custom_title = sys.argv[2] if len(sys.argv) > 2 else None
    theme_name = sys.argv[3] if len(sys.argv) > 3 else None

    # Find and sort slide files
    slide_files = sorted(glob.glob(os.path.join(output_dir, 'slide_*.html')))
    if not slide_files:
        print(f"ERROR: No slide_*.html files found in {output_dir}")
        sys.exit(1)

    total = len(slide_files)
    title = custom_title

    # Read slides and detect title
    slide_html_list = []
    for i, sf in enumerate(slide_files):
        with open(sf, 'r', encoding='utf-8') as f:
            content = f.read()
        slide_html_list.append(content)
        # Auto-detect title from first slide's <title> tag
        if i == 0 and not title:
            m = re.search(r'<title>(.*?)</title>', content)
            if m:
                title = m.group(1)
    if not title:
        title = "演示文稿"

    # Generate MMDD suffix from today's date
    mmdd = date.today().strftime('%m%d')

    # --- Generate 1: Multi-file index.html (iframe src, for local preview) ---
    index_path = os.path.join(output_dir, 'index.html')
    with open(index_path, 'w', encoding='utf-8') as f:
        f.write(gen_index_html(title, total, theme_name))

    # --- Generate 2: Single-file {title}{MMDD}.html (srcdoc, for sharing & editing) ---
    sanitized = _sanitize_filename(title)
    packed_name = f"{sanitized}{mmdd}.html"
    packed_path = os.path.join(output_dir, packed_name)
    with open(packed_path, 'w', encoding='utf-8') as f:
        f.write(gen_packed_html(title, total, slide_html_list, theme_name))
    packed_size = os.path.getsize(packed_path)

    print(f"[OK] {title}  ({total} slides)")
    print(f"  [1/2] {index_path}")
    print(f"  [2/2] {packed_path}  ({packed_size / 1024:.1f} KB, single-file, srcdoc)")
    if theme_name:
        print(f"  [theme] {theme_name} → 导航栏强调色跟随主题")


if __name__ == '__main__':
    main()
