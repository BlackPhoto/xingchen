#!/usr/bin/env python3
"""Plan isolated bilingual edits in normalized slide coordinates."""
from __future__ import annotations

import argparse
import json
import math
import sys
import unicodedata
from pathlib import Path

from pptx import Presentation

from content_guard import protected_shape_ids, snapshot_presentation
from geometry import EMU, geometry_for_shape, iter_shape_geometries

ALLOWED_IGNORE_ROLES = {"background", "decoration", "watermark", "container-or-decoration"}


def font_size(shape):
    if not getattr(shape, "has_text_frame", False):
        return None
    for paragraph in shape.text_frame.paragraphs:
        for run in paragraph.runs:
            if run.font.size:
                return run.font.size.pt
    return None


def _text_units(text: str) -> float:
    units = 0.0
    for char in text:
        if char == "\t":
            units += 2.0
        elif char.isspace():
            units += 0.32
        elif unicodedata.east_asian_width(char) in ("W", "F"):
            units += 1.0
        elif char.isalnum():
            units += 0.56
        else:
            units += 0.42
    return units


def text_height(text: str, width: int, pt: float, margin_left: int = 0, margin_right: int = 0) -> int:
    usable_width_pt = max((width - margin_left - margin_right) / EMU * 72, pt)
    line_capacity = max(usable_width_pt / max(pt, 1), 0.5)
    lines = 0
    for logical_line in (text or " ").splitlines() or [" "]:
        lines += max(1, math.ceil(_text_units(logical_line) / line_capacity))
    return int(lines * pt * 1.25 / 72 * EMU)


def required_inline_height(shape, english: str, width: int, source_pt: float, english_pt: float, gap_pt: float) -> int:
    frame = shape.text_frame
    margin_left = int(frame.margin_left or 0)
    margin_right = int(frame.margin_right or 0)
    vertical_margins = int(frame.margin_top or 0) + int(frame.margin_bottom or 0)
    content = (
        text_height(shape.text, width, source_pt, margin_left, margin_right)
        + text_height(english, width, english_pt, margin_left, margin_right)
        + int(gap_pt / 72 * EMU)
    )
    return vertical_margins + int(content * 1.12)


def overlap(a, b):
    return not (
        a[0] + a[2] <= b[0]
        or b[0] + b[2] <= a[0]
        or a[1] + a[3] <= b[1]
        or b[1] + b[3] <= a[1]
    )


def overlap_area(a, b):
    width = max(0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    height = max(0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    return width * height


def contains(outer, inner, tolerance=int(0.03 * EMU)):
    return (
        outer[0] <= inner[0] + tolerance
        and outer[1] <= inner[1] + tolerance
        and outer[0] + outer[2] >= inner[0] + inner[2] - tolerance
        and outer[1] + outer[3] >= inner[1] + inner[3] - tolerance
    )


def box_from_inches(data, fallback):
    if not data:
        return fallback
    return (
        int(float(data.get("left_in", fallback[0] / EMU)) * EMU),
        int(float(data.get("top_in", fallback[1] / EMU)) * EMU),
        int(float(data.get("width_in", fallback[2] / EMU)) * EMU),
        int(float(data.get("height_in", fallback[3] / EMU)) * EMU),
    )


def box_is_valid(box, page_w, page_h):
    return (
        box[0] >= 0
        and box[1] >= 0
        and box[2] > 0
        and box[3] > 0
        and box[0] + box[2] <= page_w
        and box[1] + box[3] <= page_h
    )


def is_container(other, other_box, src_box, target_box, explicit_container_id=None):
    if explicit_container_id is not None and other.shape_id == int(explicit_container_id):
        return True
    if getattr(other, "has_text_frame", False) and other.text_frame.text.strip():
        return False
    return (
        other_box[2] * other_box[3] > src_box[2] * src_box[3] * 1.2
        and contains(other_box, src_box)
        and contains(other_box, target_box)
    )


def load_manifest_roles(path):
    if not path:
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    roles = {}
    for slide in data.get("slides", []):
        slide_number = int(slide["slide"])
        for shape in slide.get("shapes", []):
            roles[(slide_number, int(shape["shape_id"]))] = str(shape.get("role_hint", "unknown"))
    return roles


def infer_role(shape, box, page_area):
    text = shape.text.strip() if getattr(shape, "has_text_frame", False) else ""
    if text:
        lowered_name = str(shape.name).lower()
        if "watermark" in lowered_name or "水印" in lowered_name:
            return "watermark"
        if text.replace("/", "").replace(" ", "").isdigit():
            return "page-number-or-index"
        return "text"
    if box[2] * box[3] >= page_area * 0.8:
        return "background"
    return "container-or-decoration"


def ignored_ids(entry, slide_number, geometries, roles, page_area, errors):
    raw = {int(value) for value in entry.get("ignore_shape_ids", [])}
    if not raw:
        return set(), True
    reasons = entry.get("ignore_reason")
    ignored = set()
    valid = True
    by_id = {geometry.shape.shape_id: geometry for geometry in geometries}
    for shape_id in raw:
        geometry = by_id.get(shape_id)
        if geometry is None:
            errors.append(f"slide {slide_number}: ignored shape_id {shape_id} does not exist")
            valid = False
            continue
        if isinstance(reasons, dict):
            reason = str(reasons.get(str(shape_id), reasons.get(shape_id, ""))).strip()
        else:
            reason = str(reasons or "").strip()
        if not reason:
            errors.append(f"slide {slide_number} shape {shape_id}: ignore_reason is required")
            valid = False
            continue
        role = roles.get(
            (slide_number, shape_id),
            infer_role(geometry.shape, geometry.slide_box, page_area),
        )
        has_text = bool(
            getattr(geometry.shape, "has_text_frame", False)
            and geometry.shape.text_frame.text.strip()
        )
        if role not in ALLOWED_IGNORE_ROLES or (has_text and role != "watermark"):
            errors.append(f"slide {slide_number} shape {shape_id}: role {role!r} cannot be ignored")
            valid = False
            continue
        ignored.add(shape_id)
    return ignored, valid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pptx")
    parser.add_argument("translations")
    parser.add_argument("output")
    parser.add_argument("--manifest", help="layout manifest used to verify ignore roles")
    args = parser.parse_args()

    prs = Presentation(args.pptx)
    config = json.loads(Path(args.translations).read_text(encoding="utf-8"))
    roles = load_manifest_roles(args.manifest)
    operations, errors = [], []
    planned_boxes, deleted, added_obstacles = {}, set(), {}
    source_content = config.get("source_content") or snapshot_presentation(prs)
    protected = protected_shape_ids(source_content)
    mutable_backgrounds = {
        (int(slide["slide"]), int(shape["shape_id"])): shape.get("role")
        for slide in source_content.get("slides", [])
        for shape in slide.get("backgrounds", [])
    }
    raw_strategies = config.get("slide_strategies", {})
    if isinstance(raw_strategies, list):
        strategies = {int(item["slide"]): item["strategy"] for item in raw_strategies}
    else:
        strategies = {int(key): value for key, value in raw_strategies.items()}
    for slide_number, strategy in strategies.items():
        if slide_number < 1 or slide_number > len(prs.slides):
            errors.append(f"slide_strategies: invalid slide {slide_number}")
        if strategy not in ("preserve", "reflow", "rebuild"):
            errors.append(f"slide {slide_number}: unsupported layout strategy {strategy}")

    slide_size = config.get("slide_size")
    if slide_size:
        page_w = int(float(slide_size["width_in"]) * EMU)
        page_h = int(float(slide_size["height_in"]) * EMU)
        if page_w <= 0 or page_h <= 0:
            errors.append("slide_size must be positive")
        else:
            operations.append({"op": "resize_slide", "width": page_w, "height": page_h})
    else:
        page_w, page_h = int(prs.slide_width), int(prs.slide_height)

    geometry_by_slide = {
        number: list(iter_shape_geometries(slide.shapes))
        for number, slide in enumerate(prs.slides, 1)
    }

    for index, edit in enumerate(config.get("background_edits", [])):
        try:
            slide_number = int(edit["slide"])
            action = str(edit.get("action", "keep"))
            if slide_number < 1 or slide_number > len(prs.slides):
                raise ValueError("invalid slide")
            if action not in ("keep", "simplify", "restyle", "replace"):
                raise ValueError(f"unsupported background action {action}")
            if action == "keep":
                continue
            requested_ids = edit.get("shape_ids")
            if requested_ids is None:
                background_ids = sorted(
                    shape_id for (item_slide, shape_id) in mutable_backgrounds
                    if item_slide == slide_number
                )
            else:
                background_ids = [int(shape_id) for shape_id in requested_ids]
                invalid = [
                    shape_id for shape_id in background_ids
                    if (slide_number, shape_id) not in mutable_backgrounds
                ]
                if invalid:
                    raise ValueError(
                        "shape(s) are not classified as mutable background: "
                        + ", ".join(map(str, invalid))
                    )
            fill_color = str(edit.get("fill_color", "FFFFFF"))
            if len(fill_color) != 6 or any(char not in "0123456789abcdefABCDEF" for char in fill_color):
                raise ValueError("fill_color must be a six-digit RGB value")
            for shape_id in background_ids:
                role = mutable_backgrounds[(slide_number, shape_id)]
                if action == "restyle" and role == "background-shape":
                    operations.append({
                        "op": "set_shape_style", "slide": slide_number,
                        "shape_id": shape_id, "fill_color": fill_color,
                        "line_color": "none", "line_width_pt": 0,
                    })
                else:
                    deleted.add((slide_number, shape_id))
                    operations.append({
                        "op": "delete_shape", "slide": slide_number, "shape_id": shape_id,
                    })
            operations.append({
                "op": "set_slide_background", "slide": slide_number,
                "fill_color": fill_color,
            })
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"background_edit {index}: {exc}")

    for index, edit in enumerate(config.get("layout_edits", [])):
        try:
            slide_number = int(edit["slide"])
            action = edit.get("action", "move_resize")
            if slide_number < 1 or slide_number > len(prs.slides):
                raise ValueError("invalid slide")
            if action == "add_shape":
                target = box_from_inches(edit.get("target"), (0, 0, 0, 0))
                if not box_is_valid(target, page_w, page_h):
                    raise ValueError("add_shape target must be positive and inside the slide")
                z_order = edit.get("z_order")
                operation = {
                    "op": "add_shape", "slide": slide_number,
                    "name": edit.get("name", f"BilingualLayout_s{slide_number}_{index}"),
                    "shape_kind": edit.get("shape_kind", "rectangle"),
                    "left": target[0], "top": target[1], "width": target[2], "height": target[3],
                    "fill_color": edit.get("fill_color"), "line_color": edit.get("line_color"),
                    "line_width_pt": edit.get("line_width_pt", 0), "z_order": z_order,
                    "coordinate_space": "slide",
                }
                operations.append(operation)
                if z_order != "back":
                    added_obstacles.setdefault(slide_number, []).append((operation["name"], target))
                continue

            shape_id = int(edit["shape_id"])
            geometry = geometry_for_shape(prs.slides[slide_number - 1].shapes, shape_id)
            if action == "delete":
                if (slide_number, shape_id) in protected:
                    raise ValueError("cannot delete a content-locked shape")
                deleted.add((slide_number, shape_id))
                operations.append({"op": "delete_shape", "slide": slide_number, "shape_id": shape_id})
                continue
            if action == "set_style":
                operations.append({
                    "op": "set_shape_style", "slide": slide_number, "shape_id": shape_id,
                    "fill_color": edit.get("fill_color"), "line_color": edit.get("line_color"),
                    "line_width_pt": edit.get("line_width_pt"),
                    "font_name": edit.get("font_name"), "font_size_pt": edit.get("font_size_pt"),
                    "font_color": edit.get("font_color"), "bold": edit.get("bold"),
                    "italic": edit.get("italic"), "alignment": edit.get("alignment"),
                    "margin_left_in": edit.get("margin_left_in"),
                    "margin_right_in": edit.get("margin_right_in"),
                    "margin_top_in": edit.get("margin_top_in"),
                    "margin_bottom_in": edit.get("margin_bottom_in"),
                })
                continue
            if action not in ("move_resize", "bring_to_front", "send_to_back"):
                raise ValueError(f"unsupported action {action}")
            if action in ("bring_to_front", "send_to_back"):
                operations.append({
                    "op": "bring_to_front" if action == "bring_to_front" else "send_to_back",
                    "slide": slide_number, "shape_id": shape_id,
                })
                continue
            if not geometry.transform_supported:
                raise ValueError(f"shape_id {shape_id} uses a rotated or flipped transform")
            target = box_from_inches(edit.get("target"), planned_boxes.get((slide_number, shape_id), geometry.slide_box))
            if not box_is_valid(target, page_w, page_h):
                raise ValueError("move_resize target must be positive and inside the slide")
            planned_boxes[(slide_number, shape_id)] = target
            operations.append({
                "op": "move_resize_shape", "slide": slide_number, "shape_id": shape_id,
                "left": target[0], "top": target[1], "width": target[2], "height": target[3],
                "coordinate_space": "slide",
            })
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"layout_edit {index}: {exc}")

    for index, entry in enumerate(config.get("entries", [])):
        try:
            slide_number = int(entry["slide"])
            shape_id = int(entry["shape_id"])
            english = str(entry["english"]).strip()
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"entry {index}: {exc}")
            continue
        if not english or slide_number < 1 or slide_number > len(prs.slides):
            errors.append(f"entry {index}: invalid slide or empty English")
            continue
        if (slide_number, shape_id) in deleted:
            errors.append(f"slide {slide_number} shape {shape_id}: source is deleted by layout_edits")
            continue

        geometries = geometry_by_slide[slide_number]
        matches = [g for g in geometries if g.shape.shape_id == shape_id]
        if len(matches) != 1:
            errors.append(f"slide {slide_number}: shape_id {shape_id} matched {len(matches)} shapes")
            continue
        source_geometry = matches[0]
        source = source_geometry.shape
        if not source_geometry.transform_supported:
            errors.append(f"slide {slide_number} shape {shape_id}: unsupported rotated/flipped geometry")
            continue
        if not getattr(source, "has_text_frame", False):
            errors.append(f"slide {slide_number} shape {shape_id}: source has no text frame")
            continue

        mode = entry.get("mode", "inline")
        if mode not in ("inline", "separate"):
            errors.append(f"entry {index}: unsupported mode {mode}")
            continue
        english_pt = float(entry.get("font_size_pt") or max((font_size(source) or 12) * 0.8, 8))
        if english_pt < 8:
            errors.append(f"slide {slide_number} shape {shape_id}: English font below 8pt")
            continue
        planned_source = planned_boxes.get((slide_number, shape_id), source_geometry.slide_box)
        source_target = box_from_inches(entry.get("target"), planned_source)
        page_area = page_w * page_h
        ignored, ignore_valid = ignored_ids(entry, slide_number, geometries, roles, page_area, errors)
        if not ignore_valid:
            continue

        if mode == "inline":
            required = required_inline_height(
                source, english, source_target[2], font_size(source) or 12, english_pt,
                float(entry.get("gap_pt", 2)),
            )
            if source_target[3] < required:
                errors.append(
                    f"slide {slide_number} shape {shape_id}: inline target height "
                    f"{source_target[3] / EMU:.3f}in < required {required / EMU:.3f}in"
                )
                continue
            if not box_is_valid(source_target, page_w, page_h):
                errors.append(f"slide {slide_number} shape {shape_id}: inline target exceeds slide")
                continue
            old_source = source_geometry.slide_box
            blockers, tolerance = [], (0.03 * EMU) ** 2
            explicit_container = entry.get("container_shape_id")
            for other_geometry in geometries:
                other = other_geometry.shape
                if other is source or other.shape_id in ignored or (slide_number, other.shape_id) in deleted:
                    continue
                old_other = other_geometry.slide_box
                other_box = planned_boxes.get((slide_number, other.shape_id), old_other)
                if is_container(other, other_box, planned_source, source_target, explicit_container):
                    continue
                if overlap_area(source_target, other_box) > overlap_area(old_source, old_other) + tolerance:
                    blockers.append(f"{other.shape_id}:{other.name}")
            blockers.extend(
                f"new:{name}" for name, box in added_obstacles.get(slide_number, []) if overlap(source_target, box)
            )
            if blockers:
                errors.append(
                    f"slide {slide_number} shape {shape_id}: inline resize creates collision with "
                    + ", ".join(blockers)
                )
                continue
            operations.append({
                "op": "add_inline_para", "slide": slide_number, "source_shape_id": shape_id,
                "left": source_target[0], "top": source_target[1],
                "width": source_target[2], "height": source_target[3], "text": english,
                "font_size_pt": english_pt, "font_name": entry.get("font_name", "Arial"),
                "color": entry.get("color", "888888"), "gap_pt": float(entry.get("gap_pt", 2)),
                "alignment": entry.get("alignment"), "coordinate_space": "slide",
            })
            continue

        gap = int(float(entry.get("gap_in", 0.06)) * EMU)
        box = box_from_inches(
            entry.get("target"),
            (planned_source[0], planned_source[1] + planned_source[3] + gap,
             planned_source[2], text_height(english, planned_source[2], english_pt)),
        )
        if not box_is_valid(box, page_w, page_h):
            errors.append(f"slide {slide_number} shape {shape_id}: English box exceeds slide")
            continue
        blockers, explicit_container = [], entry.get("container_shape_id")
        for other_geometry in geometries:
            other = other_geometry.shape
            if other is source or other.shape_id in ignored or (slide_number, other.shape_id) in deleted:
                continue
            other_box = planned_boxes.get((slide_number, other.shape_id), other_geometry.slide_box)
            if other_box[2] * other_box[3] > page_area * 0.8 or is_container(
                other, other_box, planned_source, box, explicit_container
            ):
                continue
            if overlap(box, other_box):
                blockers.append(f"{other.shape_id}:{other.name}")
        blockers.extend(
            f"new:{name}" for name, added_box in added_obstacles.get(slide_number, []) if overlap(box, added_box)
        )
        if blockers:
            errors.append(f"slide {slide_number} shape {shape_id}: collision with " + ", ".join(blockers))
            continue
        operations.append({
            "op": "add_textbox", "slide": slide_number, "source_shape_id": shape_id,
            "name": f"BilingualEN_s{slide_number}_id{shape_id}",
            "left": box[0], "top": box[1], "width": box[2], "height": box[3], "text": english,
            "font_size_pt": english_pt, "font_name": entry.get("font_name", "Arial"),
            "color": entry.get("color", "888888"), "alignment": entry.get("alignment"),
            "coordinate_space": "slide",
        })

    edited_ids = {
        (int(edit["slide"]), int(edit["shape_id"]))
        for edit in config.get("layout_edits", [])
        if "shape_id" in edit and edit.get("action") != "delete"
    }
    translated_ids = {
        (int(entry["slide"]), int(entry["shape_id"]))
        for entry in config.get("entries", [])
        if "slide" in entry and "shape_id" in entry
    }
    for slide_number, strategy in strategies.items():
        if strategy != "rebuild":
            continue
        missing = sorted(
            shape_id for locked_slide, shape_id in protected
            if locked_slide == slide_number
            and (slide_number, shape_id) not in edited_ids
            and (slide_number, shape_id) not in translated_ids
        )
        if missing:
            errors.append(
                f"slide {slide_number}: rebuild plan does not place protected shape(s) "
                + ", ".join(map(str, missing))
            )

    collision_pattern = "collision"
    out_of_bounds_pattern = "exceeds slide"
    per_slide_collision_counts = {}
    for error in errors:
        slide_match = None
        for prefix in (f"slide ",):
            if error.startswith(prefix):
                rest = error[len(prefix):]
                end = rest.find(":")
                if end > 0:
                    try:
                        slide_match = int(rest[:end])
                    except ValueError:
                        pass
                break
        if slide_match is None:
            continue
        if collision_pattern in error or out_of_bounds_pattern in error:
            per_slide_collision_counts[slide_match] = per_slide_collision_counts.get(slide_match, 0) + 1

    STRATEGY_UPGRADE_THRESHOLD = 3
    upgrade_warnings = []
    for slide_number, count in sorted(per_slide_collision_counts.items()):
        if count >= STRATEGY_UPGRADE_THRESHOLD:
            current = strategies.get(slide_number, "preserve")
            if current != "rebuild":
                upgrade_warnings.append(
                    f"slide {slide_number}: {count} collision/out-of-bounds errors detected; "
                    f"current strategy is {current!r}. Consider upgrading to rebuild and "
                    f"regenerating full layout_edits for all protected shapes on this slide "
                    f"instead of adjusting individual coordinates."
                )

    if errors:
        print("BILINGUAL_PLAN_FAILED", file=sys.stderr)
        for warning in upgrade_warnings:
            print("STRATEGY_UPGRADE: " + warning, file=sys.stderr)
        for error in errors:
            print("- " + error, file=sys.stderr)
        return 2
    Path(args.output).write_text(
        json.dumps({
            "slide_strategies": strategies,
            "source_content": source_content,
            "operations": operations,
        }, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"planned {len(operations)} operations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
