#!/usr/bin/env python3
"""Validate renderer-safe bilingual paragraphs and independent English boxes."""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from content_guard import compare_snapshot, snapshot_presentation
from geometry import iter_shape_geometries

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
NS = {"a": A, "p": P}


def shape_box(shape):
    xfrm = shape.find("./p:spPr/a:xfrm", namespaces=NS)
    if xfrm is None:
        return None
    off = xfrm.find("./a:off", namespaces=NS)
    ext = xfrm.find("./a:ext", namespaces=NS)
    if off is None or ext is None:
        return None
    return tuple(int(v) for v in (off.get("x"), off.get("y"), ext.get("cx"), ext.get("cy")))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pptx")
    parser.add_argument("--min-font-pt", type=float, default=8.0)
    parser.add_argument("--plan", help="bilingual_ops.json used to verify expected writes")
    parser.add_argument("--source", help="source PPTX used to verify content preservation")
    args = parser.parse_args()
    errors = []
    inline = 0
    separate = 0
    found_inline = set()
    found_separate = set()

    with zipfile.ZipFile(args.pptx) as archive:
        presentation = etree.fromstring(archive.read("ppt/presentation.xml"))
        slide_size = presentation.find(".//p:sldSz", namespaces=NS)
        slide_w = int(slide_size.get("cx"))
        slide_h = int(slide_size.get("cy"))
        names = sorted(
            (n for n in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
            key=lambda n: int(re.search(r"\d+", n).group()),
        )
        for name in names:
            root = etree.fromstring(archive.read(name))
            for node in root.xpath("//a:t", namespaces=NS):
                text = node.text or ""
                if "\n" in text or "\r" in text:
                    errors.append(f"{name}: CR/LF inside <a:t>")
                if text and not text.strip():
                    errors.append(f"{name}: whitespace-only text run")

            slide_number = int(re.search(r"\d+", name).group())
            for shape in root.xpath("//p:sp", namespaces=NS):
                props = shape.find("./p:nvSpPr/p:cNvPr", namespaces=NS)
                if props is None:
                    continue
                shape_name = props.get("name", "")
                description = props.get("descr", "")
                is_separate = shape_name.startswith("BilingualEN_")
                is_inline = "BilingualInline_" in description
                if not is_separate and not is_inline:
                    continue

                box = shape_box(shape)
                grouped = bool(shape.xpath("ancestor::p:grpSp", namespaces=NS))
                if box and not grouped and (box[0] < 0 or box[1] < 0 or box[0] + box[2] > slide_w or box[1] + box[3] > slide_h):
                    errors.append(f"{name} {shape_name}: outside slide bounds")
                text = "".join(shape.xpath(".//a:t/text()", namespaces=NS)).strip()
                if not text:
                    errors.append(f"{name} {shape_name}: empty")

                if is_separate:
                    separate += 1
                    found_separate.add((slide_number, shape_name))
                    body = shape.find("./p:txBody/a:bodyPr", namespaces=NS)
                    if body is None or body.get("wrap") != "square":
                        errors.append(f"{name} {shape_name}: wrap disabled")
                if is_inline:
                    inline += 1
                    marker_ids = re.findall(r"BilingualInline_s(\d+)_id(\d+)", description)
                    for marker_slide, marker_shape in marker_ids:
                        found_inline.add((int(marker_slide), int(marker_shape)))
                    paragraphs = shape.findall("./p:txBody/a:p", namespaces=NS)
                    english_paragraphs = [p for p in paragraphs if p.xpath(".//a:rPr[@lang='en-US']", namespaces=NS)]
                    if len(paragraphs) < 2 or not english_paragraphs:
                        errors.append(f"{name} {shape_name}: missing marked English paragraph")

                for r_pr in shape.xpath(".//a:rPr[@lang='en-US']", namespaces=NS):
                    size = r_pr.get("sz")
                    if size and int(size) < int(args.min_font_pt * 100):
                        errors.append(f"{name} {shape_name}: English font below {args.min_font_pt:g}pt")

    # Recheck all marked shapes in normalized slide coordinates. XML child
    # coordinates inside groups cannot be compared directly with slide bounds.
    prs = Presentation(args.pptx)
    for slide_number, slide in enumerate(prs.slides, 1):
        for geometry in iter_shape_geometries(slide.shapes):
            shape = geometry.shape
            has_content = bool(
                (getattr(shape, "has_text_frame", False) and shape.text.strip())
                or getattr(shape, "has_table", False)
                or getattr(shape, "has_chart", False)
                or shape.shape_type == MSO_SHAPE_TYPE.PICTURE
            )
            if has_content:
                box = geometry.slide_box
                if not geometry.transform_supported:
                    errors.append(f"slide {slide_number} {shape.name}: unsupported content geometry")
                if box[0] < 0 or box[1] < 0 or box[0] + box[2] > prs.slide_width or box[1] + box[3] > prs.slide_height:
                    errors.append(f"slide {slide_number} {shape.name}: content outside slide bounds")
            props = shape._element.xpath("./p:nvSpPr/p:cNvPr")
            if not props:
                continue
            shape_name = props[0].get("name", "")
            description = props[0].get("descr", "")
            if not shape_name.startswith("BilingualEN_") and "BilingualInline_" not in description:
                continue
            box = geometry.slide_box
            if not geometry.transform_supported:
                errors.append(f"slide {slide_number} {shape_name}: unsupported rotated/flipped geometry")
            if box[0] < 0 or box[1] < 0 or box[0] + box[2] > prs.slide_width or box[1] + box[3] > prs.slide_height:
                errors.append(f"slide {slide_number} {shape_name}: outside slide bounds")

    plan = None
    if args.plan:
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        operations = plan.get("operations", [])
        expected_inline = {
            (int(op["slide"]), int(op["source_shape_id"]))
            for op in operations if op.get("op") == "add_inline_para"
        }
        expected_separate = {
            (int(op["slide"]), str(op["name"]))
            for op in operations if op.get("op") == "add_textbox"
        }
        for missing in sorted(expected_inline - found_inline):
            errors.append(f"slide {missing[0]} shape {missing[1]}: planned inline write is missing")
        for missing in sorted(expected_separate - found_separate):
            errors.append(f"slide {missing[0]} {missing[1]}: planned English box is missing")
        for op in operations:
            if op.get("op") != "set_slide_background":
                continue
            slide_number = int(op["slide"])
            try:
                actual = str(prs.slides[slide_number - 1].background.fill.fore_color.rgb)
            except (AttributeError, IndexError, TypeError, ValueError):
                actual = ""
            expected = str(op.get("fill_color", "FFFFFF")).upper()
            if actual.upper() != expected:
                errors.append(
                    f"slide {slide_number}: background color {actual or 'missing'} != planned {expected}"
                )

    source_snapshot = None
    if args.source:
        source_snapshot = snapshot_presentation(Presentation(args.source))
    elif plan:
        source_snapshot = plan.get("source_content")
    if source_snapshot:
        errors.extend(compare_snapshot(source_snapshot, prs))

    if inline + separate == 0:
        errors.append("no marked bilingual content found")
    if errors:
        print("BILINGUAL_VALIDATION_FAILED", file=sys.stderr)
        for error in errors:
            print("- " + error, file=sys.stderr)
        return 2
    print(f"bilingual validation passed: {inline} inline, {separate} separate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
