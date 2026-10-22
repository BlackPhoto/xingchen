# -*- coding: utf-8 -*-
"""
h2p_config.py — html2pptx 转换引擎的唯一配置来源。

管三类东西（都在这里，别处不再有）：
  1. 调参常数（Profile 各节）：历史上是对着"中文商务幻灯片 × LibreOffice"
     手工调出来的值，集中化后可测试、可审计、可按档位覆盖。
  2. 实测标定数据（font_metrics.json）：由 TestCase/measure.py 生成——同一段
     文本在浏览器和 LibreOffice 各量一次宽度，比值即为"渲染器宽度因子"。
     这些不是拍脑袋的数，是量出来的，因此放在配置层而非引擎逻辑层。
  3. 档位覆盖（load_profile / --profile）：换渲染器（WPS/PowerPoint）或换
     deck 风格时，用一个 JSON 覆盖若干字段，不动引擎代码。

改这里的行为须知：
  - 默认值 = 2026-08 手调基线，改动任何一项都应先跑
    TestCase/bench.py 对比分数（防视觉回归）。
  - 行距/宽度类常数与"px→pt = ×0.75"的换算耦合，改一处要检查另一处
    （见 html2pptx._fill_frame）。

用法：
  引擎侧：  from h2p_config import CFG, load_profile, load_font_metrics, font_width_factor
  命令行：  python html2pptx.py in.html -o out.pptx --profile my.json
  重新标定： python TestCase/measure.py --twice   （结果写入 TestCase/font_metrics.json）
"""
import json
import os
from dataclasses import dataclass, field

_HERE = os.path.dirname(os.path.abspath(__file__))

# =====================================================================
# 一、调参常数
# =====================================================================

@dataclass
class Typography:
    """文本样式兜底与判定——浏览器 computed style 缺失/为 normal 时使用。"""
    default_font: str = 'Microsoft YaHei'   # CSS 字体栈全部未命中时的兜底字体
    default_fs: float = 19.0                # box 缺失 font-size 时的兜底字号(px)
    default_color: str = '1A1A2E'           # 文本缺色兜底（深蓝黑，商务 deck 惯用）
    lh_default: float = 1.22                # line-height:normal 的近似倍率（雅黑实测）
    lh_min: float = 0.9                     # line-height 下限，防 0/负值
    bold_threshold: int = 550               # 数字 font-weight ≥ 此值判为粗体（CSS 语义 500/600 边界）
    # flow 模式（--text-mode flow）的逐字符宽度系数（字号倍数）——估算换行用。
    # 仅 flow 回退路径使用；行模式（默认）由 font_metrics.json 实测因子替代。
    char_w: dict = field(default_factory=lambda: {
        'cjk': 1.0,          # CJK 全角 = 1em（雅黑/等线实测）
        'space': 0.30,       # 空格
        'digit_upper': 0.56, # 数字与大写字母
        'lower': 0.50,       # 小写字母
        'other': 0.45,       # 标点等
    })


@dataclass
class Autofit:
    """flow 模式的缩字/换行策略参数；行模式（默认）不做 autofit，仅少数字段被表格引用。"""
    cap_reserve_chars: float = 1.0    # 换行宽度预留（字符数）——渲染器度量比浏览器略宽
    cap_floor_px: float = 10.0        # 换行宽度下限(px)，窄盒防除零
    line_round_eps: float = 0.02      # 行数取整容差（ceil 前 减去，防 1.0000001 → 2 行）
    para_gap: float = 0.12            # 段间距（字号倍数），累加进总高估算
    label_lines: float = 1.75         # 盒高 < 此倍行高 → 视为单行标签（禁换行微缩）
    metric_slack: float = 1.06        # 单行标签微缩安全余量（渲染器偏宽 6%）
    scale_floor: float = 0.6          # normAutofit 缩放系数下限
    step: float = 20.0                # 缩放步进 1/step（PowerPoint 惯例 5% 步进）


@dataclass
class Geometry:
    """形状判定阈值——'多粗算边框'、'多圆算圆角' 这类视觉分界。"""
    border_px: float = 0.4            # 可见边框的最小宽度(px)，低于此视为无边框
    corner_min: float = 0.5           # 圆角最小半径(px)，低于此按直角
    corner_square_eps: float = 4.0    # 旋转 90/270° 圆角要求近正方形的容差(px)
    oval_pct: float = 0.49            # 四角 ≥49% 圆角 → 判椭圆（而非封顶 roundRect）
    oval_aspect: float = 1.02         # 椭圆判定的长宽比下限
    svg_rad_min: float = 0.6          # SVG rect 圆角最小半径(px)
    svg_min_size: float = 0.3         # SVG 形状最小尺寸(px)，小于此跳过
    img_radius_min: float = 1.5       # 图片圆角最小半径(px)
    adj_cap: float = 0.5              # roundRect adjustment 上限（OOXML 语义 0-0.5）
    # CSS 三角形启发式：小盒 + 单边粗边框 → 判为三角（箭头装饰常用手法）
    tri_sw_min: float = 3.0           # 边框最小粗细(px)
    tri_w_factor: float = 1.6         # 盒宽 ≤ 边粗 × 此系数
    tri_h_factor: float = 2.4         # 盒高 ≤ 边粗 × 此系数


@dataclass
class Table:
    """表格逐格缩放参数（单元格文字宽度拟合，行距单位修复后取值趋保守）。"""
    slack: float = 1.25               # 单行单元格宽度余量倍数
    uniform_floor: float = 0.65       # 全表统一缩放下限（防缩到不可读）
    single_line_factor: float = 1.6   # 单元格高 ≤ 此倍行高 → 视为单行设计（禁换行）
    default_row_h: float = 30.0       # 行高缺失/过小时的兜底行高(px)
    min_dim: float = 8.0              # 列宽/行高最小有效值(px)，低于此取平均/默认


# =====================================================================
# 二、字体别名与映射
# =====================================================================

# CSS 字体名 → 引擎可安全使用的字体名。显式别名（跨平台商用字体替换），
# 不认识的字体会走"已安装字体直通"（html2pptx.resolve_font，实测；macOS 使用 system_profiler，
# Linux 使用 fc-list）。FONT_MAP_DEFAULT 以 Windows 目标 PPTX 为基准：
# resolve_font 按浏览器语义逐名回退——映射命中的别名只有当目标字体确实已安装时才生效
# （PingFang SC 在 macOS 已装则直通原名；Windows 未装则跳过，落到字体栈下一个名字），
# 未映射的名字只有已安装才直通，否则跳过；全栈落空才用 default_font。
FONT_MAP_DEFAULT = {
    'DengXian': 'DengXian', '等线': 'DengXian',
    'Microsoft YaHei': 'Microsoft YaHei', '微软雅黑': 'Microsoft YaHei',
    'PingFang SC': 'PingFang SC',             # macOS 原生字体；仅当本机已装时才生效，否则回退栈内下一名字
    'Noto Sans SC': 'Noto Sans SC',
    'SimSun': 'SimSun', '宋体': 'SimSun',
    'SimHei': 'SimHei', '黑体': 'SimHei',
    'KaiTi': 'KaiTi', '楷体': 'KaiTi',
}


# =====================================================================
# 三、配置根对象与档位覆盖
# =====================================================================

@dataclass
class Profile:
    typography: Typography = field(default_factory=Typography)
    autofit: Autofit = field(default_factory=Autofit)
    geometry: Geometry = field(default_factory=Geometry)
    table: Table = field(default_factory=Table)
    font_map: dict = field(default_factory=lambda: dict(FONT_MAP_DEFAULT))


# 引擎全局持有的配置实例（进程级单例）
CFG = Profile()


def load_profile(path):
    """JSON 档位覆盖：{"typography": {...}, "geometry": {...}, "font_map": {...},
    "font_metrics_path": "..."}。只覆盖已知字段，未知键忽略。"""
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    fm = data.pop('font_map', None)
    if fm:
        CFG.font_map.update(fm)
    fmp = data.pop('font_metrics_path', None)
    if fmp:
        CFG.font_metrics_path = fmp
        load_font_metrics()
    for sect, vals in data.items():
        obj = getattr(CFG, sect, None)
        if obj is None or not isinstance(vals, dict):
            continue
        for k, v in vals.items():
            if hasattr(obj, k):
                setattr(obj, k, v)


# =====================================================================
# 四、实测标定：渲染器宽度因子（数据来自 TestCase/measure.py）
# =====================================================================

# font_metrics.json 的默认查找路径（项目根相对 TestCase/；可被 profile 覆盖）
CFG.font_metrics_path = os.path.join(_HERE, 'TestCase', 'font_metrics.json')

# {font: {class: ratio}}，class ∈ cjk/lower/upper/digits；ratio = LO墨迹宽/浏览器宽
FONT_METRICS = {}


def load_font_metrics(path=None):
    """载入宽度标定数据。文件缺失/损坏时静默置空——所有因子回退 1.0，
    行为退化为'不做宽度微缩'，不阻塞转换。"""
    global FONT_METRICS
    p = path or getattr(CFG, 'font_metrics_path', '')
    try:
        with open(p, encoding='utf-8') as f:
            FONT_METRICS = json.load(f).get('fonts', {}) or {}
    except Exception:
        FONT_METRICS = {}
    return FONT_METRICS


def font_width_factor(font, text):
    """给定字体渲染一段文本时，LibreOffice 相对浏览器的平均宽度倍率。

    >1 表示渲染器排得更宽（有溢出风险），调用方据此按比例微缩字号。
    逐字符归类（cjk/upper/lower/digits）取实测均值；未标定的字体/字符
    回退 1.0（不缩放）。标定方法见 TestCase/measure.py。"""
    m = FONT_METRICS.get(font)
    if not m or not text:
        return 1.0
    rs = []
    for ch in text:
        o = ord(ch)
        if o > 0x2E80:
            k = 'cjk'
        elif ch.isdigit():
            k = 'digits'
        elif ch.isupper():
            k = 'upper'
        elif ch.islower():
            k = 'lower'
        else:
            k = None
        if k:
            v = m.get(k)
            if v is not None:
                rs.append(v)
    return sum(rs) / len(rs) if rs else 1.0
