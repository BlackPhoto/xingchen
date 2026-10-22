#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
chart_validator.py — SVG 图表校验脚本（只读，不修改任何文件）

用法：
    python chart_validator.py <html_file>
    python chart_validator.py <html_file> --json

校验项：
  1. 饼图/环形图：path 坐标连续性（前一段终点 = 后一段起点）
  2. 饼图/环形图：角度总和是否等于 360°
  3. 饼图/环形图：large-arc-flag 与 sweep 角度是否匹配
  4. 饼图/环形图：path fill 与 legend swatch 颜色一致性
  5. 柱状图：条形数 = 标签数 = 数据项数
  6. 折线图：数据点数 = 标签数、坐标在 viewBox 范围内、多线数据点数一致
  7. 面积图：path 闭合性、坐标在 viewBox 范围内、数据点与标签对应
  8. 雷达图：顶点数 = 维度数、多边形闭合、轴角度均匀分布
  9. 散点图：散点数 = 数据项数、坐标在 viewBox 范围内、半径可见
  10. 通用 SVG：检测未覆盖的图表类型并提示

退出码：0 = 通过，1 = 发现问题，2 = 用法错误
"""

import sys
import re
import math
import json
import argparse

# Windows 下 stdout/stderr 默认可能非 UTF-8（如 GBK），强制设为 UTF-8 避免中文输出乱码
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("[FATAL] 需要 beautifulsoup4: pip install beautifulsoup4")
    sys.exit(2)


# ============================================================
#  常量
# ============================================================

TOLERANCE = 1.5  # 坐标容差（像素），浮点比较用


# ============================================================
#  工具函数
# ============================================================

def parse_path_d(d):
    """解析 SVG path d 属性中的 M/L/A 命令，返回命令列表。

    返回格式：[{'cmd':'M', 'args':[x,y]}, {'cmd':'L', 'args':[x,y]},
              {'cmd':'A', 'args':[rx,ry,xrot,large_arc,sweep,ex,ey]}, ...]
    """
    commands = []
    # 匹配 M, L, A, Z 命令及其参数（Z 无参数）
    pattern = re.compile(r'([MLAZ])\s*([-\d.,\s]*)', re.IGNORECASE)
    for m in pattern.finditer(d):
        cmd = m.group(1).upper()
        raw = m.group(2).strip()
        nums = [float(x) for x in re.split(r'[\s,]+', raw) if x] if raw else []
        commands.append({'cmd': cmd, 'args': nums})
    return commands


def extract_pie_paths(svg):
    """从 SVG 中提取饼图/环形图的扇形 path 列表。

    识别条件：path 的 d 属性含 M...L...A...Z 模式（从圆心出发，画弧，回到圆心）。
    返回：[{'d': str, 'fill': str, 'commands': [...]}, ...]
    """
    paths = []
    for path in svg.find_all('path'):
        d = path.get('d', '')
        if not d:
            continue
        commands = parse_path_d(d)
        # 饼图 path 模式：M cx,cy L sx,sy A rx,ry ... ex,ey Z
        has_m = any(c['cmd'] == 'M' for c in commands)
        has_l = any(c['cmd'] == 'L' for c in commands)
        has_a = any(c['cmd'] == 'A' for c in commands)
        has_z = any(c['cmd'] == 'Z' for c in commands)
        if has_m and has_l and has_a and has_z:
            paths.append({
                'd': d,
                'fill': path.get('fill', ''),
                'commands': commands,
            })
    return paths


def get_arc_endpoint(commands):
    """获取 A 命令的终点坐标 (ex, ey)。"""
    for c in commands:
        if c['cmd'] == 'A' and len(c['args']) >= 7:
            return (c['args'][5], c['args'][6])
    return None


def get_arc_startpoint(commands):
    """获取 L 命令后的起点坐标（弧的起始点）。"""
    for c in commands:
        if c['cmd'] == 'L' and len(c['args']) >= 2:
            return (c['args'][0], c['args'][1])
    return None


def get_arc_params(commands):
    """获取 A 命令的参数：rx, ry, x-rotation, large-arc-flag, sweep-flag。"""
    for c in commands:
        if c['cmd'] == 'A' and len(c['args']) >= 7:
            return {
                'rx': c['args'][0],
                'ry': c['args'][1],
                'xrot': c['args'][2],
                'large_arc': int(c['args'][3]),
                'sweep_flag': int(c['args'][4]),
            }
    return None


def get_center(commands):
    """获取 M 命令的坐标（圆心）。"""
    for c in commands:
        if c['cmd'] == 'M' and len(c['args']) >= 2:
            return (c['args'][0], c['args'][1])
    return None


def coords_match(p1, p2, tol=TOLERANCE):
    """比较两个坐标点是否在容差范围内相等。"""
    if p1 is None or p2 is None:
        return False
    return abs(p1[0] - p2[0]) < tol and abs(p1[1] - p2[1]) < tol


def calc_expected_endpoint(cx, cy, r, start_angle_deg, sweep_deg):
    """根据圆心、半径、起始角和扫过角度计算期望的弧终点坐标。"""
    end_angle = start_angle_deg + sweep_deg
    ex = cx + r * math.sin(math.radians(end_angle))
    ey = cy - r * math.cos(math.radians(end_angle))
    return (ex, ey)


def reverse_calc_angle(cx, cy, px, py):
    """根据圆心和圆周上的点反推角度（度，从12点钟顺时针）。"""
    dx = px - cx
    dy = py - cy
    # angle = atan2(dx, -dy) → 从12点钟顺时针为正
    angle = math.degrees(math.atan2(dx, -dy))
    if angle < 0:
        angle += 360
    return angle


def extract_legend_colors(svg):
    """从 SVG 的兄弟元素中提取 legend swatch 颜色列表。

    legend 结构：<div class="legend-list"> <div class="legend-item">
                <span class="swatch" style="background:#xxx;"></span> 标签 ... </div>
    """
    # 找 SVG 的父容器
    parent = svg.parent
    if not parent:
        return []

    colors = []
    legend = parent.find(class_='legend-list')
    if not legend:
        return colors

    for item in legend.find_all(class_='legend-item'):
        swatch = item.find(class_='swatch')
        if swatch:
            style = swatch.get('style', '')
            m = re.search(r'background\s*:\s*(#?[0-9a-fA-F]{3,8})', style)
            if m:
                colors.append(m.group(1).lower())
    return colors


def extract_path_fills(paths):
    """提取 path 的 fill 颜色列表。"""
    result = []
    for p in paths:
        fill = p['fill'].strip().lower()
        if fill:
            result.append(fill)
    return result


def get_viewbox(svg):
    """解析 SVG viewBox 属性，返回 (min_x, min_y, width, height) 或 None。

    BeautifulSoup 的 html.parser 会将属性名转为小写（viewBox → viewbox），
    因此同时检查两种大小写。
    """
    # html.parser 把 viewBox 转为 viewbox，lxml 保留原样
    vb = svg.get('viewBox', '') or svg.get('viewbox', '')
    if not vb:
        # 尝试从 width/height 属性推断
        w = svg.get('width', '')
        h = svg.get('height', '')
        try:
            return (0, 0, float(w), float(h))
        except (ValueError, TypeError):
            return None
    nums = re.split(r'[\s,]+', vb.strip())
    if len(nums) >= 4:
        try:
            return (float(nums[0]), float(nums[1]), float(nums[2]), float(nums[3]))
        except ValueError:
            pass
    return None


def parse_points_str(points_str):
    """解析 SVG points 属性字符串，返回 [(x, y), ...] 坐标列表。"""
    if not points_str:
        return []
    nums = [float(x) for x in re.split(r'[\s,]+', points_str.strip()) if x]
    if len(nums) % 2 != 0:
        return []
    return [(nums[i], nums[i + 1]) for i in range(0, len(nums), 2)]


def extract_polyline_points(svg):
    """从 <polyline> 元素提取坐标点列表。

    返回：[{'points': [(x,y),...], 'fill': str, 'stroke': str}, ...]
    """
    results = []
    for pl in svg.find_all('polyline'):
        points = parse_points_str(pl.get('points', ''))
        if not points:
            continue
        results.append({
            'points': points,
            'fill': pl.get('fill', 'none'),
            'stroke': pl.get('stroke', ''),
        })
    return results


def extract_linechart_paths(svg):
    """提取折线图 <path>（M+L 命令，无 A 无 Z，fill=none）。

    返回：[{'points': [(x,y),...], 'fill': str, 'stroke': str}, ...]
    """
    results = []
    for path in svg.find_all('path'):
        d = path.get('d', '')
        if not d:
            continue
        commands = parse_path_d(d)
        has_m = any(c['cmd'] == 'M' for c in commands)
        has_a = any(c['cmd'] == 'A' for c in commands)
        has_z = any(c['cmd'] == 'Z' for c in commands)
        fill = path.get('fill', 'none')
        # 折线 path：M+L，无 A，无 Z，无填充
        if has_m and not has_a and not has_z and (not fill or fill == 'none'):
            points = []
            for c in commands:
                if c['cmd'] in ('M', 'L') and len(c['args']) >= 2:
                    points.append((c['args'][0], c['args'][1]))
            if points:
                results.append({
                    'points': points,
                    'fill': fill,
                    'stroke': path.get('stroke', ''),
                })
    return results


def extract_area_paths(svg):
    """提取面积图 <path>（M+L+Z 命令，无 A，有 fill）。

    返回：[{'points': [(x,y),...], 'fill': str, 'commands': [...], 'stroke': str}, ...]
    """
    results = []
    for path in svg.find_all('path'):
        d = path.get('d', '')
        if not d:
            continue
        commands = parse_path_d(d)
        has_m = any(c['cmd'] == 'M' for c in commands)
        has_l = any(c['cmd'] == 'L' for c in commands)
        has_a = any(c['cmd'] == 'A' for c in commands)
        has_z = any(c['cmd'] == 'Z' for c in commands)
        fill = path.get('fill', 'none')
        # 面积 path：M+L+Z，无 A，有填充
        if has_m and has_l and has_z and not has_a and fill and fill != 'none':
            points = []
            for c in commands:
                if c['cmd'] in ('M', 'L') and len(c['args']) >= 2:
                    points.append((c['args'][0], c['args'][1]))
            if points:
                results.append({
                    'points': points,
                    'fill': fill,
                    'stroke': path.get('stroke', ''),
                    'commands': commands,
                })
    return results


def extract_polygons(svg):
    """提取 <polygon> 元素的顶点坐标。

    返回：[{'points': [(x,y),...], 'fill': str, 'stroke': str}, ...]
    """
    results = []
    for pg in svg.find_all('polygon'):
        points = parse_points_str(pg.get('points', ''))
        if not points:
            continue
        results.append({
            'points': points,
            'fill': pg.get('fill', 'none'),
            'stroke': pg.get('stroke', ''),
        })
    return results


def extract_scatter_circles(svg):
    """提取散点图的 <circle> 数据点。

    排除大圆（背景/环形图中心孔）、无填充/白色填充圆（网格/装饰）。
    若 SVG 已被识别为饼图/环形图或折线图/面积图，跳过（圆为装饰/数据点标记）。
    """
    # 饼图/环形图的圆是装饰，跳过
    if extract_pie_paths(svg):
        return []
    # 折线图/面积图中的小圆点是数据标记，不是散点
    if extract_polyline_points(svg) or extract_linechart_paths(svg) or extract_area_paths(svg):
        return []

    results = []
    for circle in svg.find_all('circle'):
        try:
            cx = float(circle.get('cx', ''))
            cy = float(circle.get('cy', ''))
            r = float(circle.get('r', ''))
        except (ValueError, TypeError):
            continue

        fill = circle.get('fill', 'none')
        # 排除大圆（r > 30，可能是背景/网格/环形孔）
        if r > 30:
            continue
        # 排除无填充或白色填充（网格/装饰）
        if not fill or fill in ('none', 'white', '#ffffff', '#fff'):
            continue

        results.append({'cx': cx, 'cy': cy, 'r': r, 'fill': fill})
    return results


def extract_chart_labels(svg, skip_legend=False):
    """从图表容器中提取标签列表（用于数据点/维度数量比对）。

    查找顺序：.chart-labels > span → .legend-item 文本 → SVG <text> 元素。
    skip_legend=True 时跳过 legend（雷达图的 legend 是数据系列名，不是维度标签）。
    """
    parent = svg.parent
    if not parent:
        return []

    labels = []

    # 1. .chart-labels > span（柱状图/折线图 x 轴标签）
    label_container = parent.find(class_='chart-labels')
    if label_container:
        for span in label_container.find_all('span'):
            text = span.get_text(strip=True)
            if text:
                labels.append(text)
    if labels:
        return labels

    # 2. .legend-item 标签文本（散点图图例）
    if not skip_legend:
        legend = parent.find(class_='legend-list')
        if legend:
            for item in legend.find_all(class_='legend-item'):
                text = item.get_text(strip=True)
                # 提取标签名（排除百分比/数值后缀）
                m = re.match(r'^[^\d¥$%]+', text)
                if m and m.group().strip():
                    labels.append(m.group().strip())
    if labels:
        return labels

    # 3. SVG <text> 元素（雷达图轴标签等）
    for t in svg.find_all('text'):
        text = t.get_text(strip=True)
        if text and len(text) <= 20:
            labels.append(text)

    return labels


# ============================================================
#  校验函数
# ============================================================

def validate_pie(svg, svg_index):
    """校验饼图/环形图。返回 issues 列表。"""
    issues = []
    paths = extract_pie_paths(svg)

    if not paths:
        return issues  # 没有饼图 path，不校验

    # ---- 1. 坐标连续性 ----
    for i in range(len(paths) - 1):
        end_pt = get_arc_endpoint(paths[i]['commands'])
        next_start = get_arc_startpoint(paths[i + 1]['commands'])
        if not coords_match(end_pt, next_start):
            issues.append(
                f"[svg#{svg_index}] 扇形#{i} 终点 ({end_pt}) 与扇形#{i+1} 起点 ({next_start}) 不匹配，"
                f"坐标不连续（期望误差<{TOLERANCE}px）"
            )

    # 最后一段终点应与第一段起点闭合
    if len(paths) > 1:
        last_end = get_arc_endpoint(paths[-1]['commands'])
        first_start = get_arc_startpoint(paths[0]['commands'])
        if not coords_match(last_end, first_start):
            issues.append(
                f"[svg#{svg_index}] 最后扇形终点 ({last_end}) 与首扇形起点 ({first_start}) 不闭合，"
                f"饼图未形成完整圆形"
            )

    # ---- 2. 角度总和与 large-arc-flag 校验 ----
    # 从 path 反推每段的角度
    cx, cy = (None, None)
    center = get_center(paths[0]['commands'])
    if center:
        cx, cy = center

    arc_params = get_arc_params(paths[0]['commands'])
    r = arc_params['rx'] if arc_params else 90

    total_sweep = 0
    for i, p in enumerate(paths):
        cmds = p['commands']
        start_pt = get_arc_startpoint(cmds)
        end_pt = get_arc_endpoint(cmds)
        params = get_arc_params(cmds)

        if start_pt is None or end_pt is None or params is None or cx is None:
            continue

        # 反推角度
        start_angle = reverse_calc_angle(cx, cy, start_pt[0], start_pt[1])
        end_angle = reverse_calc_angle(cx, cy, end_pt[0], end_pt[1])
        sweep = end_angle - start_angle
        if sweep < 0:
            sweep += 360
        total_sweep += sweep

        # large-arc-flag 校验
        expected_large_arc = 1 if sweep > 180 else 0
        if params['large_arc'] != expected_large_arc:
            issues.append(
                f"[svg#{svg_index}] 扇形#{i}: large-arc-flag={params['large_arc']} "
                f"但 sweep={sweep:.1f}°（{'>' if sweep > 180 else '<='}180°），"
                f"应为 {expected_large_arc}"
            )

    if len(paths) > 1 and abs(total_sweep - 360) > 2.0:
        issues.append(
            f"[svg#{svg_index}] 扇形角度总和={total_sweep:.1f}°，期望 360°（误差>2°）"
        )

    # ---- 3. 颜色一致性 ----
    path_fills = extract_path_fills(paths)
    legend_colors = extract_legend_colors(svg)

    if legend_colors and len(path_fills) == len(legend_colors):
        for i, (pf, lc) in enumerate(zip(path_fills, legend_colors)):
            if pf != lc:
                issues.append(
                    f"[svg#{svg_index}] 颜色不一致: path#{i} fill={pf} vs legend#{i} swatch={lc}"
                )
    elif legend_colors and len(path_fills) != len(legend_colors):
        issues.append(
            f"[svg#{svg_index}] path 数量({len(path_fills)}) 与 legend 项数({len(legend_colors)}) 不匹配，无法校验颜色一致性"
        )

    return issues


def validate_barchart(soup):
    """校验柱状图：条形数 = 标签数 = 数据项数。返回 issues 列表。"""
    issues = []

    chart_rows = soup.find_all(class_='chart-row')
    for i, row in enumerate(chart_rows):
        bars = row.find_all(class_='bar')
        # 找同级的 chart-labels
        parent = row.parent
        if not parent:
            continue
        labels = parent.find_all(class_='chart-labels')
        if labels:
            label_spans = labels[0].find_all('span')
            if len(bars) != len(label_spans):
                issues.append(
                    f"[bar#{i}] 条形数({len(bars)}) != 标签数({len(label_spans)})，"
                    f"两者必须一一对应"
                )

        # 检查 stat-inline
        stat_inline = parent.find_all(class_='stat-inline')
        if stat_inline:
            items = stat_inline[0].find_all(class_='item')
            if len(bars) != len(items):
                issues.append(
                    f"[bar#{i}] 条形数({len(bars)}) != 数据项数({len(items)})，"
                    f"三者必须一一对应"
                )

    return issues


def validate_linechart(svg, svg_index):
    """校验折线图：数据点数、viewBox 范围、多线一致性。返回 issues 列表。"""
    issues = []

    # 收集所有折线数据：来自 <polyline fill=none> 和 <path M...L... fill=none>
    lines = []
    for pl in extract_polyline_points(svg):
        if not pl['fill'] or pl['fill'] == 'none':
            lines.append(pl)
    lines.extend(extract_linechart_paths(svg))

    if not lines:
        return issues

    # 1. 坐标在 viewBox 范围内
    vb = get_viewbox(svg)
    if vb:
        vb_x, vb_y, vb_w, vb_h = vb
        x_min, x_max = vb_x, vb_x + vb_w
        y_min, y_max = vb_y, vb_y + vb_h
        for i, line in enumerate(lines):
            for j, (px, py) in enumerate(line['points']):
                if px < x_min - TOLERANCE or px > x_max + TOLERANCE or \
                   py < y_min - TOLERANCE or py > y_max + TOLERANCE:
                    issues.append(
                        f"[svg#{svg_index}] 折线#{i} 第{j+1}个点 ({px:.1f},{py:.1f}) "
                        f"超出 viewBox 范围 ({vb_x},{vb_y},{vb_w},{vb_h})"
                    )

    # 2. 多条折线数据点数一致
    if len(lines) > 1:
        counts = [len(l['points']) for l in lines]
        if len(set(counts)) > 1:
            issues.append(
                f"[svg#{svg_index}] 多条折线数据点数不一致: {counts}，各线应有相同数量的数据点"
            )

    # 3. 数据点数 = 标签数
    labels = extract_chart_labels(svg)
    if labels:
        first_count = len(lines[0]['points']) if lines else 0
        if first_count != len(labels):
            issues.append(
                f"[svg#{svg_index}] 折线数据点数({first_count}) != 标签数({len(labels)})，"
                f"两者必须一一对应"
            )

    # 4. 每条线至少 2 个点
    for i, line in enumerate(lines):
        if len(line['points']) < 2:
            issues.append(
                f"[svg#{svg_index}] 折线#{i} 仅有 {len(line['points'])} 个点，"
                f"折线至少需要 2 个数据点"
            )

    return issues


def validate_areachart(svg, svg_index):
    """校验面积图：path 闭合性、viewBox 范围、数据点对应。返回 issues 列表。"""
    issues = []
    areas = extract_area_paths(svg)

    if not areas:
        return issues

    # 1. 坐标在 viewBox 范围内
    vb = get_viewbox(svg)
    if vb:
        vb_x, vb_y, vb_w, vb_h = vb
        x_min, x_max = vb_x, vb_x + vb_w
        y_min, y_max = vb_y, vb_y + vb_h
        for i, area in enumerate(areas):
            for j, (px, py) in enumerate(area['points']):
                if px < x_min - TOLERANCE or px > x_max + TOLERANCE or \
                   py < y_min - TOLERANCE or py > y_max + TOLERANCE:
                    issues.append(
                        f"[svg#{svg_index}] 面积#{i} 第{j+1}个点 ({px:.1f},{py:.1f}) "
                        f"超出 viewBox 范围 ({vb_x},{vb_y},{vb_w},{vb_h})"
                    )

    # 2. path 已闭合（有 Z 命令）— extract_area_paths 已确保有 Z，双重确认
    for i, area in enumerate(areas):
        has_z = any(c['cmd'] == 'Z' for c in area['commands'])
        if not has_z:
            issues.append(
                f"[svg#{svg_index}] 面积#{i} path 未闭合（缺少 Z 命令），面积图 path 必须闭合"
            )

    # 3. 数据点与标签对应（面积图 path 含闭合基线点，数据点 = 总点数 - 2 或 -1）
    labels = extract_chart_labels(svg)
    if labels:
        total = len(areas[0]['points'])
        # 常见模式：M 基线 L 数据... L 基线 Z → 数据点 = total - 2
        #          M 数据 L 数据... Z        → 数据点 = total
        matched = any(total - offset == len(labels) for offset in (0, 1, 2))
        if not matched and total > 2:
            issues.append(
                f"[svg#{svg_index}] 面积图数据点数({total}, 含闭合点) "
                f"与标签数({len(labels)}) 不匹配，请检查数据点与标签是否对应"
            )

    # 4. 多个面积图数据点数一致
    if len(areas) > 1:
        counts = [len(a['points']) for a in areas]
        if len(set(counts)) > 1:
            issues.append(
                f"[svg#{svg_index}] 多个面积图数据点数不一致: {counts}"
            )

    return issues


def validate_radar(svg, svg_index):
    """校验雷达图：顶点数、闭合性、轴角度均匀。返回 issues 列表。"""
    issues = []

    # 雷达图用 <polygon> 或闭合 <polyline fill!=none>（首尾点重合）
    shapes = list(extract_polygons(svg))
    for pl in extract_polyline_points(svg):
        if pl['fill'] and pl['fill'] != 'none' and len(pl['points']) >= 3:
            if coords_match(pl['points'][0], pl['points'][-1]):
                shapes.append(pl)

    if not shapes:
        return issues

    # 计算有效顶点数（闭合多边形首尾重合时减 1）
    def vertex_count(shape):
        pts = shape['points']
        return len(pts) - 1 if coords_match(pts[0], pts[-1]) else len(pts)

    # 1. 顶点数 = 维度/标签数（雷达图的 legend 是数据系列名，不是维度，跳过）
    labels = extract_chart_labels(svg, skip_legend=True)
    if labels:
        first_v = vertex_count(shapes[0])
        if first_v != len(labels):
            issues.append(
                f"[svg#{svg_index}] 雷达图顶点数({first_v}) != 维度/标签数({len(labels)})，"
                f"两者必须一一对应"
            )

    # 2. 至少 3 个顶点
    for i, shape in enumerate(shapes):
        v = vertex_count(shape)
        if v < 3:
            issues.append(
                f"[svg#{svg_index}] 雷达图#{i} 仅有 {v} 个顶点，"
                f"至少需要 3 个顶点形成多边形"
            )

    # 3. 轴角度均匀分布（360°/N）
    first = shapes[0]
    pts = first['points']
    v_pts = pts[:-1] if coords_match(pts[0], pts[-1]) else pts
    n = len(v_pts)
    if n >= 3:
        cx = sum(p[0] for p in v_pts) / n
        cy = sum(p[1] for p in v_pts) / n
        angles = []
        for px, py in v_pts:
            a = math.degrees(math.atan2(py - cy, px - cx))
            if a < 0:
                a += 360
            angles.append(a)
        expected_step = 360.0 / n
        for j in range(n):
            expected = (angles[0] + j * expected_step) % 360
            diff = abs(angles[j] - expected)
            if diff > 180:
                diff = 360 - diff
            if diff > 5.0:
                issues.append(
                    f"[svg#{svg_index}] 雷达图轴角度不均匀: 第{j+1}个轴角度={angles[j]:.1f}°，"
                    f"期望={expected:.1f}°（间隔应为 {expected_step:.1f}°）"
                )
                break

    # 4. 多个数据形状顶点数一致
    if len(shapes) > 1:
        counts = [vertex_count(s) for s in shapes]
        if len(set(counts)) > 1:
            issues.append(
                f"[svg#{svg_index}] 多个雷达图形状顶点数不一致: {counts}"
            )

    return issues


def validate_scatter(svg, svg_index):
    """校验散点图：散点数、viewBox 范围、半径可见性。返回 issues 列表。"""
    issues = []
    circles = extract_scatter_circles(svg)

    if not circles:
        return issues

    # 1. 坐标在 viewBox 范围内
    vb = get_viewbox(svg)
    if vb:
        vb_x, vb_y, vb_w, vb_h = vb
        x_min, x_max = vb_x, vb_x + vb_w
        y_min, y_max = vb_y, vb_y + vb_h
        for i, c in enumerate(circles):
            if c['cx'] < x_min - TOLERANCE or c['cx'] > x_max + TOLERANCE or \
               c['cy'] < y_min - TOLERANCE or c['cy'] > y_max + TOLERANCE:
                issues.append(
                    f"[svg#{svg_index}] 散点#{i} ({c['cx']:.1f},{c['cy']:.1f}) "
                    f"超出 viewBox 范围 ({vb_x},{vb_y},{vb_w},{vb_h})"
                )

    # 2. 散点数 = 标签/数据项数
    labels = extract_chart_labels(svg)
    if labels and len(circles) != len(labels):
        issues.append(
            f"[svg#{svg_index}] 散点数({len(circles)}) != 标签数({len(labels)})，"
            f"两者必须一一对应"
        )

    # 3. 半径可见（r >= 1）
    for i, c in enumerate(circles):
        if c['r'] < 1.0:
            issues.append(
                f"[svg#{svg_index}] 散点#{i} 半径={c['r']:.1f} 过小，可能不可见"
            )

    return issues


def validate_svg_generic(svg, svg_index):
    """通用 SVG 校验：检测未覆盖的图表类型并提示。返回 issues 列表。"""
    # 已覆盖的图表类型检测
    has_pie = bool(extract_pie_paths(svg))
    has_line = bool(extract_polyline_points(svg)) or bool(extract_linechart_paths(svg))
    has_area = bool(extract_area_paths(svg))
    has_radar = bool(extract_polygons(svg))
    has_scatter = bool(extract_scatter_circles(svg))

    # 若已识别为已知图表类型，不再报告"未覆盖"
    if has_pie or has_line or has_area or has_radar or has_scatter:
        return []

    issues = []
    all_paths = svg.find_all('path')
    has_polyline = svg.find('polyline') or svg.find('polygon')
    has_text = svg.find('text')

    if len(all_paths) > 0 and (has_polyline or has_text):
        issues.append(
            f"[svg#{svg_index}] 检测到未识别的 SVG 图表类型，"
            f"该类型尚未实现数学校验，请依赖截图+视觉模型检查"
        )

    return issues


# ============================================================
#  主流程
# ============================================================

def validate(html_path):
    """校验 HTML 文件中的所有 SVG 图表。返回 (passed, issues)。"""
    with open(html_path, 'r', encoding='utf-8-sig') as f:
        content = f.read()

    soup = BeautifulSoup(content, 'html.parser')
    issues = []

    # 1. 校验所有 SVG
    svgs = soup.find_all('svg')
    for i, svg in enumerate(svgs):
        # 饼图/环形图校验
        issues.extend(validate_pie(svg, i))
        # 折线图校验
        issues.extend(validate_linechart(svg, i))
        # 面积图校验
        issues.extend(validate_areachart(svg, i))
        # 雷达图校验
        issues.extend(validate_radar(svg, i))
        # 散点图校验
        issues.extend(validate_scatter(svg, i))
        # 通用 SVG 校验（兜底）
        issues.extend(validate_svg_generic(svg, i))

    # 2. 校验柱状图
    issues.extend(validate_barchart(soup))

    passed = len(issues) == 0
    return passed, issues


def main():
    parser = argparse.ArgumentParser(description='SVG 图表校验脚本')
    parser.add_argument('html_file', help='待校验的 HTML 文件路径')
    parser.add_argument('--json', action='store_true', help='JSON 输出')
    args = parser.parse_args()

    try:
        passed, issues = validate(args.html_file)
    except FileNotFoundError:
        msg = f"文件不存在: {args.html_file}"
        if args.json:
            print(json.dumps({"passed": False, "error": msg}, ensure_ascii=False))
        else:
            print(f"[ERROR] {msg}")
        sys.exit(2)

    if args.json:
        result = {"passed": passed, "issues_count": len(issues), "issues": issues}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if passed:
            print("[PASS] 图表校验通过，未发现问题。")
        else:
            print(f"[FAIL] 发现 {len(issues)} 个问题：")
            for issue in issues:
                print(f"  - {issue}")

    sys.exit(0 if passed else 1)


if __name__ == '__main__':
    main()
