# -*- coding: utf-8 -*-
"""
calibrate_all.py — 标定工作流统一入口。

按顺序执行三项标定，产出/更新引擎实际读取的数据与常数，并给出人工判定建议：

  1. 宽度标定  measure.py      → TestCase/font_metrics.json（引擎行模式微缩字号用）
                 标本: 10 字体 × cjk/大写/小写/数字 × 16/24/32px
  2. 垂直标定  vcalib.py       → 报告徽章/bullet 的垂直偏差(px)
                 若 |bullet delta| > 0.5px → 调整 extract.js 的 marker 补偿系数
                 (当前 0.06em；修改后必须跑 bench list 回归)
  3. 阴影标定  shadow_calib.py → LO/browser 阴影浓度比（诊断性，当前结论:
                 add_shadow 参数忠实；比例若 >1.3 需要在 add_shadow 里校正）

用法:
  python calibrate_all.py            # 全部三项
  python calibrate_all.py measure    # 只跑宽度标定
  python calibrate_all.py vcalib shadow
"""
import subprocess, sys, os

HERE = os.path.dirname(os.path.abspath(__file__))
STEPS = ['measure', 'vcalib', 'shadow']


def run(step):
    print('\n' + '=' * 62)
    print('== 标定步骤:', step)
    print('=' * 62)
    script = {'measure': 'measure.py', 'vcalib': 'vcalib.py', 'shadow': 'shadow_calib.py'}[step]
    r = subprocess.run([sys.executable, os.path.join(HERE, script)])
    return r.returncode


def main():
    steps = sys.argv[1:] or STEPS
    unknown = [s for s in steps if s not in STEPS]
    if unknown:
        sys.exit('unknown steps: %s (available: %s)' % (unknown, STEPS))
    fails = []
    for s in steps:
        if run(s) != 0:
            fails.append(s)
    print('\n' + '=' * 62)
    print('标定完成。人工判定清单：')
    print('  1. measure: 上表 ratio 与上次比有无漂移？确定性与否(--twice)？')
    print('  2. vcalib:  bullet delta 是否 |·|>0.5px？是 → 调 extract.js 0.06em 系数')
    print('  3. shadow:  LO/browser 比例是否仍在 0.8-1.1？偏离 → 检查 LO 版本/字体')
    print('  任何修改后: python bench.py（合成回归）+ 相关真实页 diffmap')
    if fails:
        print('FAILED steps:', fails)
        sys.exit(1)


if __name__ == '__main__':
    main()
