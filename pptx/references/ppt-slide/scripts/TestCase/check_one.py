# -*- coding: utf-8 -*-
"""check_one.py <slides_dir> <n> [n...] — convert one HTML slide, render, save PNG."""
import subprocess, sys, os

HERE = os.path.dirname(os.path.abspath(__file__))   # TestCase/
ROOT = os.path.dirname(HERE)                        # project root
os.chdir(HERE)

if len(sys.argv) < 3:
    sys.exit('usage: python TestCase/check_one.py <slides_dir> <n> [n...]')

SLIDES = sys.argv[1]
if not os.path.isabs(SLIDES): SLIDES = os.path.join(ROOT, SLIDES)

for arg in sys.argv[2:]:
    n = int(arg)
    src = os.path.join(SLIDES, f'slide_{n:02d}.html')
    pptx = f'check_{n:02d}.pptx'
    r = subprocess.run([sys.executable, os.path.join(ROOT, 'html2pptx.py'), src, '-o', pptx],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f'slide {n}: CONVERT FAILED\n{r.stderr[-600:]}')
        continue
    subprocess.run(['taskkill', '/F', '/IM', 'soffice.bin', '/T'], capture_output=True)
    subprocess.run(['taskkill', '/F', '/IM', 'soffice.exe', '/T'], capture_output=True)
    subprocess.run([r'C:\Program Files\LibreOffice\program\soffice.exe',
                    '-env:UserInstallation=file:///' + os.path.join(HERE, 'lo_profile').replace(os.sep, '/'),
                    '--headless', '--convert-to', 'pdf', '--outdir', 'qa64', pptx],
                   capture_output=True)
    import fitz
    doc = fitz.open(f'qa64/check_{n:02d}.pdf')
    doc[0].get_pixmap(matrix=fitz.Matrix(96/72, 96/72)).save(f'qa64/check_{n:02d}.png')
    print(f'slide {n}: rendered -> qa64/check_{n:02d}.png')
