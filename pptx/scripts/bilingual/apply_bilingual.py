#!/usr/bin/env python3
"""Apply only pre-planned bilingual and layout operations."""
from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE, MSO_SHAPE_TYPE
from pptx.enum.text import MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Emu, Pt

from content_guard import compare_snapshot
from geometry import EMU, geometry_for_shape, invert_box


def iter_shapes(items):
    for shape in items:
        yield shape
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from iter_shapes(shape.shapes)


def find_shape(slide, shape_id):
    matches = [s for s in iter_shapes(slide.shapes) if s.shape_id == int(shape_id)]
    if len(matches) != 1:
        raise SystemExit(f"shape_id {shape_id} matched {len(matches)} shapes")
    return matches[0]


def validate_bounds(op, slide_width, slide_height, op_name="operation"):
    left, top = int(op["left"]), int(op["top"])
    width, height = int(op["width"]), int(op["height"])
    tolerance = int(0.02 * EMU)
    if left < 0 or top < 0:
        raise SystemExit(f"{op_name}: negative position ({left}, {top})")
    if width <= 0 or height <= 0:
        raise SystemExit(f"{op_name}: non-positive dimensions ({width}x{height})")
    if left + width > int(slide_width) + tolerance:
        raise SystemExit(f"{op_name}: right edge exceeds slide width")
    if top + height > int(slide_height) + tolerance:
        raise SystemExit(f"{op_name}: bottom edge exceeds slide height")


def set_box_slide(slide, shape, op, slide_width, slide_height):
    """Write a slide-space target, converting it to group-local coordinates."""
    validate_bounds(op, slide_width, slide_height, f"shape {shape.shape_id}")
    try:
        geometry = geometry_for_shape(slide.shapes, shape.shape_id)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if not geometry.transform_supported:
        raise SystemExit(f"shape {shape.shape_id}: rotated/flipped group transforms are unsupported")
    local = invert_box(
        (int(op["left"]), int(op["top"]), int(op["width"]), int(op["height"])),
        geometry.to_slide,
    )
    shape.left, shape.top, shape.width, shape.height = map(Emu, local)


def set_marker(shape, marker):
    candidates = shape._element.xpath("./p:nvSpPr/p:cNvPr")
    if not candidates:
        candidates = shape._element.xpath("./p:nvGrpSpPr/p:cNvPr")
    if candidates:
        old = candidates[0].get("descr", "")
        candidates[0].set("descr", marker if not old else f"{marker}; {old}")


def parse_alignment(value, fallback=None):
    if value is None:
        return fallback
    values = {
        "left": PP_ALIGN.LEFT,
        "center": PP_ALIGN.CENTER,
        "right": PP_ALIGN.RIGHT,
        "justify": PP_ALIGN.JUSTIFY,
    }
    if str(value).lower() not in values:
        raise SystemExit(f"unsupported alignment: {value}")
    return values[str(value).lower()]


def clear_bullets(paragraph):
    p_pr = paragraph._p.get_or_add_pPr()
    for tag in ("a:buChar", "a:buAutoNum", "a:buBlip", "a:buNone"):
        for node in p_pr.findall(qn(tag)):
            p_pr.remove(node)
    p_pr.append(OxmlElement("a:buNone"))


def set_style(shape, op):
    fill_color = op.get("fill_color")
    if fill_color is not None:
        if str(fill_color).lower() == "none":
            shape.fill.background()
        else:
            shape.fill.solid()
            shape.fill.fore_color.rgb = RGBColor.from_string(str(fill_color))
    line_color = op.get("line_color")
    if line_color is not None:
        if str(line_color).lower() == "none":
            shape.line.fill.background()
        else:
            shape.line.color.rgb = RGBColor.from_string(str(line_color))
    if op.get("line_width_pt") is not None:
        shape.line.width = Pt(float(op["line_width_pt"]))
    if not getattr(shape, "has_text_frame", False):
        return
    frame = shape.text_frame
    for key, attribute in (
        ("margin_left_in", "margin_left"),
        ("margin_right_in", "margin_right"),
        ("margin_top_in", "margin_top"),
        ("margin_bottom_in", "margin_bottom"),
    ):
        if op.get(key) is not None:
            setattr(frame, attribute, Emu(int(float(op[key]) * EMU)))
    alignment = parse_alignment(op.get("alignment"))
    for paragraph in frame.paragraphs:
        if alignment is not None:
            paragraph.alignment = alignment
        for run in paragraph.runs:
            if op.get("font_name") is not None:
                run.font.name = str(op["font_name"])
            if op.get("font_size_pt") is not None:
                run.font.size = Pt(float(op["font_size_pt"]))
            if op.get("font_color") is not None:
                run.font.color.rgb = RGBColor.from_string(str(op["font_color"]))
            if op.get("bold") is not None:
                run.font.bold = bool(op["bold"])
            if op.get("italic") is not None:
                run.font.italic = bool(op["italic"])


def move_to_front(shape):
    parent = shape._element.getparent()
    parent.remove(shape._element)
    ext_lists = parent.findall(qn("p:extLst"))
    if ext_lists:
        parent.insert(parent.index(ext_lists[0]), shape._element)
    else:
        parent.append(shape._element)


def move_to_back(shape):
    parent = shape._element.getparent()
    parent.remove(shape._element)
    parent.insert(2, shape._element)


def add_layout_shape(slide, op, slide_width, slide_height):
    kinds = {"rectangle": MSO_SHAPE.RECTANGLE, "rounded_rectangle": MSO_SHAPE.ROUNDED_RECTANGLE}
    kind = op.get("shape_kind", "rectangle")
    if kind not in kinds:
        raise SystemExit(f"unsupported shape_kind: {kind}")
    validate_bounds(op, slide_width, slide_height, "add_shape")
    shape = slide.shapes.add_shape(kinds[kind], Emu(int(op["left"])), Emu(int(op["top"])), Emu(int(op["width"])), Emu(int(op["height"])))
    shape.name = op["name"]
    set_style(shape, op)
    if op.get("z_order") == "back":
        move_to_back(shape)
    return shape


def set_slide_background(slide, op):
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = RGBColor.from_string(str(op.get("fill_color", "FFFFFF")))


def add_inline(slide, op, slide_width, slide_height):
    shape = find_shape(slide, op["source_shape_id"])
    if not getattr(shape, "has_text_frame", False):
        raise SystemExit(f"shape {op['source_shape_id']} has no text frame")
    set_box_slide(slide, shape, op, slide_width, slide_height)
    frame = shape.text_frame
    previous = frame.paragraphs[-1]
    paragraph = frame.add_paragraph()
    if previous._p.pPr is not None:
        paragraph._p.insert(0, deepcopy(previous._p.pPr))
    clear_bullets(paragraph)
    paragraph.alignment = parse_alignment(op.get("alignment"), previous.alignment)
    paragraph.space_before = Pt(float(op.get("gap_pt", 2)))
    paragraph.space_after = Pt(0)
    run = paragraph.add_run()
    run.text = op["text"]
    run.font.name = op.get("font_name", "Arial")
    run.font.size = Pt(float(op["font_size_pt"]))
    run.font.color.rgb = RGBColor.from_string(op.get("color", "888888"))
    run._r.get_or_add_rPr().set("lang", "en-US")
    set_marker(shape, f"BilingualInline_s{op['slide']}_id{op['source_shape_id']}")


def add_separate(slide, op, slide_width, slide_height):
    validate_bounds(op, slide_width, slide_height, "add_textbox")
    shape = slide.shapes.add_textbox(
        Emu(int(op["left"])), Emu(int(op["top"])),
        Emu(int(op["width"])), Emu(int(op["height"]))
    )
    shape.name = op["name"]
    frame = shape.text_frame
    frame.clear()
    frame.word_wrap = True
    frame.auto_size = MSO_AUTO_SIZE.NONE
    frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
    paragraph = frame.paragraphs[0]
    paragraph.alignment = parse_alignment(op.get("alignment"), paragraph.alignment)
    run = paragraph.add_run()
    run.text = op["text"]
    run.font.name = op.get("font_name", "Arial")
    run.font.size = Pt(float(op["font_size_pt"]))
    run.font.color.rgb = RGBColor.from_string(op.get("color", "888888"))
    run._r.get_or_add_rPr().set("lang", "en-US")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pptx")
    parser.add_argument("operations")
    parser.add_argument("output")
    args = parser.parse_args()
    if Path(args.pptx).resolve() == Path(args.output).resolve():
        raise SystemExit("output must be a new file; source PPTX cannot be overwritten")
    prs = Presentation(args.pptx)
    plan = json.loads(Path(args.operations).read_text(encoding="utf-8"))
    ops = plan.get("operations", [])

    for op in ops:
        kind = op.get("op")
        if kind == "resize_slide":
            prs.slide_width = Emu(int(op["width"]))
            prs.slide_height = Emu(int(op["height"]))
            continue
        slide = prs.slides[int(op["slide"]) - 1]
        if kind == "set_slide_background":
            set_slide_background(slide, op)
        elif kind == "add_shape":
            add_layout_shape(slide, op, prs.slide_width, prs.slide_height)
        elif kind == "set_shape_style":
            set_style(find_shape(slide, op["shape_id"]), op)
        elif kind == "move_resize_shape":
            set_box_slide(
                slide, find_shape(slide, op["shape_id"]), op,
                prs.slide_width, prs.slide_height,
            )
        elif kind == "delete_shape":
            shape = find_shape(slide, op["shape_id"])
            shape._element.getparent().remove(shape._element)
        elif kind == "bring_to_front":
            move_to_front(find_shape(slide, op["shape_id"]))
        elif kind == "send_to_back":
            move_to_back(find_shape(slide, op["shape_id"]))
        elif kind == "add_inline_para":
            add_inline(slide, op, prs.slide_width, prs.slide_height)
        elif kind == "add_textbox":
            add_separate(slide, op, prs.slide_width, prs.slide_height)
        else:
            raise SystemExit(f"unsupported operation: {kind}")

    source_content = plan.get("source_content")
    if source_content:
        preservation_errors = compare_snapshot(source_content, prs)
        if preservation_errors:
            raise SystemExit(
                "CONTENT_PRESERVATION_FAILED\n- " + "\n- ".join(preservation_errors)
            )
    prs.save(args.output)
    print(f"applied {len(ops)} operations")


if __name__ == "__main__":
    main()
