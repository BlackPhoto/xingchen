#!/usr/bin/env python3
"""
Fix chart/image xfrm (off/ext) in xlsx files for mobile preview compatibility.

XlsxWriter writes <a:off x="0" y="0"/><a:ext cx="0" cy="0"/> for chart objects
in the drawing XML. Desktop Excel locates objects via cell anchors and ignores
the 0x0 xfrm, but mobile preview engines (WeChat Work, WPS Mobile, Excel Mobile)
read xfrm values: ext=0 renders nothing, off=0 places the object over the
data area.

This script computes the real absolute position and size of every anchored
drawing object from its anchor cells (row heights / column widths defined in
the worksheet XML) and patches xfrm accordingly. Works for any sheet layout
(hidden rows/cols, custom sizes, charts anchored anywhere including far
beyond the data area — undimensioned rows/cols fall back to the file's
declared defaults, matching Excel's own behavior).

Usage:
    python fix_chart_xfrm.py <excel_file>          # fix in place
    python fix_chart_xfrm.py <excel_file> --check # report only, no changes

Returns JSON: {"status": "fixed"/"ok"/"error", "objects_fixed": N, "details": [...]}
"""

import zipfile
import re
import sys
import json
import shutil
import os
import tempfile

EMU_PER_PX = 9525
EMU_PER_PT = 12700


def col_width_to_px(width_chars):
    """Excel column width (chars, Calibri 11) -> pixels."""
    return int(round(width_chars * 7)) + 5


def parse_sheet_dimensions(sheet_xml):
    """Extract declared default sizes and per-row/per-col overrides."""
    m = re.search(r'<sheetFormatPr[^>]*defaultRowHeight="([\d.]+)"', sheet_xml)
    default_row_ht_pt = float(m.group(1)) if m else 15.0
    m = re.search(r'<sheetFormatPr[^>]*defaultColWidth="([\d.]+)"', sheet_xml)
    default_col_width = float(m.group(1)) if m else 8.43

    row_hts = {}
    row_hidden = set()
    for m in re.finditer(r'<row r="(\d+)"([^>]*)>', sheet_xml):
        rnum = int(m.group(1))
        attrs = m.group(2)
        ht = re.search(r'ht="([\d.]+)"', attrs)
        if ht:
            row_hts[rnum] = float(ht.group(1))
        if 'hidden="1"' in attrs:
            row_hidden.add(rnum)

    col_widths = {}
    col_hidden = set()
    for m in re.finditer(r'<col ([^>]*?)/>', sheet_xml):
        attrs = m.group(1)
        mn = re.search(r'min="(\d+)"', attrs)
        mx = re.search(r'max="(\d+)"', attrs)
        if not (mn and mx):
            continue
        w = re.search(r'width="([\d.]+)"', attrs)
        hidden = 'hidden="1"' in attrs
        for c in range(int(mn.group(1)), int(mx.group(1)) + 1):
            if w:
                col_widths[c] = float(w.group(1))
            if hidden:
                col_hidden.add(c)

    return {
        'default_row_ht_pt': default_row_ht_pt,
        'default_col_width': default_col_width,
        'row_hts': row_hts,
        'row_hidden': row_hidden,
        'col_widths': col_widths,
        'col_hidden': col_hidden,
    }


def row_height_emu(row_idx_0based, dims):
    r = row_idx_0based + 1
    if r in dims['row_hidden']:
        return 0
    pt = dims['row_hts'].get(r, dims['default_row_ht_pt'])
    return int(round(pt * EMU_PER_PT))


def col_width_emu(col_idx_0based, dims):
    c = col_idx_0based + 1
    if c in dims['col_hidden']:
        return 0
    w = dims['col_widths'].get(c, dims['default_col_width'])
    return int(round(col_width_to_px(w) * EMU_PER_PX))


def anchor_pos_emu(col, coloff, row, rowoff, dims):
    """Absolute EMU coordinates of an anchor marker."""
    x = sum(col_width_emu(i, dims) for i in range(col)) + int(coloff)
    y = sum(row_height_emu(i, dims) for i in range(row)) + int(rowoff)
    return x, y


ANCHOR_RE = re.compile(
    r'<xdr:from><xdr:col>(\d+)</xdr:col><xdr:colOff>(\d+)</xdr:colOff>'
    r'<xdr:row>(\d+)</xdr:row><xdr:rowOff>(\d+)</xdr:rowOff></xdr:from>'
    r'<xdr:to><xdr:col>(\d+)</xdr:col><xdr:colOff>(\d+)</xdr:colOff>'
    r'<xdr:row>(\d+)</xdr:row><xdr:rowOff>(\d+)</xdr:rowOff></xdr:to>'
)
XFRM_RE = re.compile(r'<xdr:xfrm><a:off x="(\d+)" y="(\d+)"/><a:ext cx="(\d+)" cy="(\d+)"/></xdr:xfrm>')


def fix_drawing_xml(drawing_xml, sheet_xml):
    """Patch every zero-size xfrm inside twoCellAnchor objects. Returns (new_xml, fixes)."""
    dims = parse_sheet_dimensions(sheet_xml)
    fixes = []

    def repl_anchor(m):
        block = m.group(0)
        # only patch blocks whose xfrm is zero-sized
        xf = XFRM_RE.search(block)
        if not xf or not (xf.group(1) == '0' and xf.group(2) == '0'
                          and xf.group(3) == '0' and xf.group(4) == '0'):
            return block
        am = ANCHOR_RE.search(block)
        if not am:
            return block
        fc, fco, fr, fro, tc, tco, tr, tro = am.groups()
        x1, y1 = anchor_pos_emu(int(fc), int(fco), int(fr), int(fro), dims)
        x2, y2 = anchor_pos_emu(int(tc), int(tco), int(tr), int(tro), dims)
        new_xfrm = f'<xdr:xfrm><a:off x="{x1}" y="{y1}"/><a:ext cx="{x2 - x1}" cy="{y2 - y1}"/></xdr:xfrm>'
        block = XFRM_RE.sub(new_xfrm, block)
        fixes.append({'off': [x1, y1], 'ext': [x2 - x1, y2 - y1]})
        return block

    # Match each twoCellAnchor block individually
    new_xml, n = re.subn(
        r'<xdr:twoCellAnchor>.*?</xdr:twoCellAnchor>',
        lambda m: repl_anchor(m),
        drawing_xml,
        flags=re.DOTALL,
    )
    return new_xml, fixes


def main():
    args = sys.argv[1:]
    if not args:
        print("Usage: python fix_chart_xfrm.py <excel_file> [--check]")
        sys.exit(1)
    path = args[0]
    check_only = '--check' in args

    if not os.path.exists(path):
        print(json.dumps({'status': 'error', 'error': f'File not found: {path}'}))
        sys.exit(1)

    with zipfile.ZipFile(path, 'r') as z:
        names = z.namelist()

        # Map each worksheet -> its drawing (via sheet rels)
        sheet_to_drawing = {}
        drawing_xmls = {}
        sheet_xmls = {}
        for name in names:
            m = re.match(r'xl/worksheets/_rels/(sheet\d+)\.xml\.rels', name)
            if m:
                rels = z.read(name).decode('utf-8')
                dm = re.search(r'Target="[^"]*/(drawing\d+\.xml)"', rels)
                if dm:
                    sheet_to_drawing[m.group(1)] = dm.group(1)
            if re.match(r'xl/worksheets/sheet\d+\.xml$', name):
                sheet_xmls[re.sub(r'\.xml$', '', name.split('/')[-1])] = z.read(name).decode('utf-8')
            if re.match(r'xl/drawings/drawing\d+\.xml$', name):
                drawing_xmls[name.split('/')[-1]] = z.read(name).decode('utf-8')

        if not drawing_xmls:
            print(json.dumps({'status': 'ok', 'objects_fixed': 0, 'details': 'no drawings'}))
            return

        # Compute fixes per drawing
        patched = {}
        all_fixes = []
        for sheet_name, drawing_name in sheet_to_drawing.items():
            if drawing_name not in drawing_xmls:
                continue
            sheet_xml = sheet_xmls.get(sheet_name)
            if sheet_xml is None:
                continue
            new_xml, fixes = fix_drawing_xml(drawing_xmls[drawing_name], sheet_xml)
            if fixes:
                patched[f'xl/drawings/{drawing_name}'] = new_xml
                all_fixes.extend(fixes)

        if check_only or not patched:
            print(json.dumps({
                'status': 'ok' if not patched else 'needs_fix',
                'objects_fixed': 0 if check_only else 0,
                'objects_needing_fix': len(all_fixes),
                'details': all_fixes,
            }))
            return

        # Rewrite the zip with patched drawings
        fd, tmp = tempfile.mkstemp(suffix='.xlsx')
        os.close(fd)
        with zipfile.ZipFile(path, 'r') as zin:
            with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zout:
                for item in zin.namelist():
                    if item in patched:
                        zout.writestr(item, patched[item])
                    else:
                        zout.writestr(item, zin.read(item))
        shutil.move(tmp, path)

        print(json.dumps({
            'status': 'fixed',
            'objects_fixed': len(all_fixes),
            'details': all_fixes,
        }))


if __name__ == '__main__':
    main()
