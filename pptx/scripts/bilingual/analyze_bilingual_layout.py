#!/usr/bin/env python3
"""Inventory slide geometry and text roles for an explicitly bilingual PPT edit.

The output is planning input only.  This script never mutates the presentation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pptx import Presentation
from content_guard import classify_shape_role, snapshot_presentation
from geometry import EMU, iter_shape_geometries


def _box(shape):
    return tuple(int(float(shape[key]) * EMU) for key in ("left_in", "top_in", "width_in", "height_in"))


def _overlap_area(a, b):
    width = max(0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    height = max(0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    return width * height


def _contains(outer, inner, tolerance=int(0.03 * EMU)):
    return (
        outer[0] <= inner[0] + tolerance
        and outer[1] <= inner[1] + tolerance
        and outer[0] + outer[2] >= inner[0] + inner[2] - tolerance
        and outer[1] + outer[3] >= inner[1] + inner[3] - tolerance
    )

def predict_bilingual_collisions(shapes, slide_w, slide_h):
    """Predict content collisions after adding bilingual text to every text shape.

    Simulates inline mode (source height expands ~2.1x) and separate mode (new
    English box placed below source), then counts predicted overlaps with other
    content shapes and out-of-bounds cases.  Returns (risk, inline_count,
    separate_count, details) where risk = max(inline, separate).
    """
    content_roles = {"text", "content-picture", "table", "chart"}
    text_shapes = [s for s in shapes if s["role_hint"] == "text"]
    content = [s for s in shapes if s["role_hint"] in content_roles]

    gap_emu = int(0.06 * EMU)
    inline_count = 0
    separate_count = 0
    details = []

    for text_shape in text_shapes:
        tbox = _box(text_shape)
        inline_box = (tbox[0], tbox[1], tbox[2], int(tbox[3] * 2.1))
        phantom_h = max(int(tbox[3] * 0.8), int(0.3 * EMU))
        phantom_box = (tbox[0], tbox[1] + tbox[3] + gap_emu, tbox[2], phantom_h)

        if inline_box[1] + inline_box[3] > slide_h:
            inline_count += 1
            details.append({"mode": "inline", "shape_ids": [text_shape["shape_id"]], "kind": "predicted_out_of_bounds"})
        if phantom_box[1] + phantom_box[3] > slide_h:
            separate_count += 1
            details.append({"mode": "separate", "shape_ids": [text_shape["shape_id"]], "kind": "predicted_out_of_bounds"})

        for other in content:
            if other is text_shape:
                continue
            obox = _box(other)
            area = _overlap_area(inline_box, obox)
            if area > 0:
                smaller = max(1, min(inline_box[2] * inline_box[3], obox[2] * obox[3]))
                if area / smaller >= 0.05:
                    inline_count += 1
                    details.append({"mode": "inline", "shape_ids": [text_shape["shape_id"], other["shape_id"]], "kind": "predicted_overlap"})
            area = _overlap_area(phantom_box, obox)
            if area > 0:
                smaller = max(1, min(phantom_box[2] * phantom_box[3], obox[2] * obox[3]))
                if area / smaller >= 0.05:
                    separate_count += 1
                    details.append({"mode": "separate", "shape_ids": [text_shape["shape_id"], other["shape_id"]], "kind": "predicted_overlap"})

    return max(inline_count, separate_count), inline_count, separate_count, details

def first_font(shape):
    if not getattr(shape, "has_text_frame", False):
        return {}
    for paragraph in shape.text_frame.paragraphs:
        for run in paragraph.runs:
            font = run.font
            result = {
                "font_name": font.name,
                "font_size_pt": font.size.pt if font.size else None,
                "bold": font.bold,
                "italic": font.italic,
            }
            if font.color and font.color.type is not None:
                try:
                    result["color"] = str(font.color.rgb)
                except (AttributeError, ValueError):
                    pass
            return result
    return {}


def shape_role(shape, slide_area, slide_box, z_index):
    text = shape.text.strip() if getattr(shape, "has_text_frame", False) else ""
    if text:
        lowered_name = str(shape.name).lower()
        if "watermark" in lowered_name or "水印" in lowered_name:
            return "watermark"
        if text.replace("/", "").replace(" ", "").isdigit():
            return "page-number-or-index"
        return "text"
    return classify_shape_role(shape, slide_box, slide_area, z_index)


def slide_type(shapes):
    roles = [shape["role_hint"] for shape in shapes]
    text_count = roles.count("text")
    if "chart" in roles or "table" in roles:
        return "data"
    if "content-picture" in roles and text_count:
        return "image-text"
    if text_count <= 2:
        return "title-or-section"
    if text_count >= 4:
        return "multi-block"
    return "text"


def layout_health(shapes, slide_w, slide_h):
    issues = []
    score = 100
    content_roles = {"text", "content-picture", "table", "chart"}
    content = [shape for shape in shapes if shape["role_hint"] in content_roles]
    for shape in content:
        left, top, width, height = _box(shape)
        if left < 0 or top < 0 or left + width > slide_w or top + height > slide_h:
            issues.append({"kind": "out_of_bounds", "shape_ids": [shape["shape_id"]]})
            score -= 35
        size = shape.get("first_font", {}).get("font_size_pt")
        if size is not None and float(size) < 8:
            issues.append({"kind": "small_text", "shape_ids": [shape["shape_id"]]})
            score -= 12
    collision_count = 0
    for index, first in enumerate(content):
        first_box = _box(first)
        for second in content[index + 1:]:
            second_box = _box(second)
            if _contains(first_box, second_box) or _contains(second_box, first_box):
                continue
            area = _overlap_area(first_box, second_box)
            if area <= 0:
                continue
            smaller = max(1, min(first_box[2] * first_box[3], second_box[2] * second_box[3]))
            if area / smaller >= 0.05:
                collision_count += 1
                issues.append({
                    "kind": "content_overlap",
                    "shape_ids": [first["shape_id"], second["shape_id"]],
                })
    score -= min(45, collision_count * 18)
    occupied = sum(_box(shape)[2] * _box(shape)[3] for shape in content)
    density = occupied / max(1, slide_w * slide_h)
    if density > 0.72:
        issues.append({"kind": "high_density", "value": round(density, 3)})
        score -= 15
    score = max(0, score)

    bilingual_risk, bilingual_inline, bilingual_separate, bilingual_details = \
        predict_bilingual_collisions(shapes, slide_w, slide_h)
    if bilingual_details:
        issues.append({"kind": "bilingual_collision_risk", "count": bilingual_risk})

    if score < 60 or collision_count >= 2 or any(i["kind"] == "out_of_bounds" for i in issues):
        strategy = "rebuild"
    elif bilingual_risk >= 3:
        strategy = "rebuild"
    elif score < 85 or density > 0.62 or bilingual_risk >= 1:
        strategy = "reflow"
    else:
        strategy = "preserve"
    return {
        "score": score,
        "issues": issues,
        "density": round(density, 3),
        "recommended_strategy": strategy,
        "bilingual_collision_risk": bilingual_risk,
        "bilingual_collision_preview": {
            "inline": bilingual_inline,
            "separate": bilingual_separate,
            "details": bilingual_details,
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pptx")
    parser.add_argument("output")
    args = parser.parse_args()

    prs = Presentation(args.pptx)
    slide_area = int(prs.slide_width) * int(prs.slide_height)
    result = {
        "slide_size": {
            "width_in": round(prs.slide_width / EMU, 4),
            "height_in": round(prs.slide_height / EMU, 4),
        },
        "slides": [],
        "content_inventory": snapshot_presentation(prs),
    }

    for slide_number, slide in enumerate(prs.slides, 1):
        shapes = []
        for geometry in iter_shape_geometries(slide.shapes):
            shape = geometry.shape
            left, top, width, height = geometry.slide_box
            local_left, local_top, local_width, local_height = geometry.local_box
            text = shape.text.strip() if getattr(shape, "has_text_frame", False) else ""
            paragraphs = []
            if getattr(shape, "has_text_frame", False):
                paragraphs = [p.text for p in shape.text_frame.paragraphs if p.text.strip()]
            shapes.append(
                {
                    "shape_id": shape.shape_id,
                    "name": shape.name,
                    "parent_group_id": geometry.parent_id,
                    "group_path": list(geometry.group_path),
                    "coordinate_space": "slide",
                    "original_coordinate_space": "group-local" if geometry.parent_id is not None else "slide",
                    "transform_supported": geometry.transform_supported,
                    "z_index": geometry.z_index,
                    "shape_type": str(shape.shape_type),
                    "role_hint": shape_role(shape, slide_area, geometry.slide_box, geometry.z_index),
                    "left_in": round(left / EMU, 4),
                    "top_in": round(top / EMU, 4),
                    "width_in": round(width / EMU, 4),
                    "height_in": round(height / EMU, 4),
                    "local_box_in": {
                        "left": round(local_left / EMU, 4),
                        "top": round(local_top / EMU, 4),
                        "width": round(local_width / EMU, 4),
                        "height": round(local_height / EMU, 4),
                    },
                    "text": text,
                    "paragraphs": paragraphs,
                    "first_font": first_font(shape),
                }
            )
        result["slides"].append({
            "slide": slide_number,
            "slide_type": slide_type(shapes),
            "layout_health": layout_health(shapes, int(prs.slide_width), int(prs.slide_height)),
            "shapes": shapes,
        })

    Path(args.output).write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"analyzed {len(prs.slides)} slides")


if __name__ == "__main__":
    main()
