#!/usr/bin/env python3
"""Generate a conservative native-PowerPoint card-grid bilingual layout candidate.

The planner is optional. It emits a complete translations.json only when every
requested entry belongs to a high-confidence, axis-aligned card layout that
fits on the slide. Unsupported pages must use the manual/model planning path.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

from geometry import EMU
from plan_bilingual import text_height


def box(shape):
    return tuple(int(float(shape[key]) * EMU) for key in ("left_in", "top_in", "width_in", "height_in"))


def contains(outer, inner, tolerance=int(0.03 * EMU)):
    return (
        outer[0] <= inner[0] + tolerance
        and outer[1] <= inner[1] + tolerance
        and outer[0] + outer[2] >= inner[0] + inner[2] - tolerance
        and outer[1] + outer[3] >= inner[1] + inner[3] - tolerance
    )


def to_inches(value):
    return round(value / EMU, 4)


def target(box_value):
    return {
        "left_in": to_inches(box_value[0]),
        "top_in": to_inches(box_value[1]),
        "width_in": to_inches(box_value[2]),
        "height_in": to_inches(box_value[3]),
    }


def group_rows(cards):
    rows = []
    for card in sorted(cards, key=lambda item: (item["box"][1], item["box"][0])):
        center = card["box"][1] + card["box"][3] / 2
        match = None
        for row in rows:
            tolerance = max(0.18 * EMU, statistics.median(c["box"][3] for c in row) * 0.35)
            row_center = statistics.mean(c["box"][1] + c["box"][3] / 2 for c in row)
            if abs(center - row_center) <= tolerance:
                match = row
                break
        if match is None:
            rows.append([card])
        else:
            match.append(card)
    for row in rows:
        row.sort(key=lambda item: item["box"][0])
    return rows


def estimate_shape_height(shape, entry=None):
    current = box(shape)
    source_pt = float(shape.get("first_font", {}).get("font_size_pt") or 12)
    if not entry:
        return current[3]
    english_pt = float(entry.get("font_size_pt") or max(source_pt * 0.8, 8))
    if english_pt < 8:
        raise ValueError(f"shape {shape['shape_id']}: English font below 8pt")
    source_height = text_height(shape.get("text", ""), current[2], source_pt)
    english_height = text_height(str(entry["english"]), current[2], english_pt)
    gap = int(float(entry.get("gap_pt", 2)) / 72 * EMU)
    return max(current[3], int((source_height + english_height + gap) * 1.12) + int(0.08 * EMU))


def fail(reason):
    print(f"BILINGUAL_LAYOUT_PLANNER_FAILED: {reason}", file=sys.stderr)
    return 2


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest")
    parser.add_argument("content", help="JSON with entries including slide, shape_id and english")
    parser.add_argument("output")
    parser.add_argument("--min-confidence", type=float, default=0.75)
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    content = json.loads(Path(args.content).read_text(encoding="utf-8"))
    entries = content.get("entries", [])
    if not entries:
        return fail("content has no entries")

    slide_w = int(float(manifest["slide_size"]["width_in"]) * EMU)
    slide_h = int(float(manifest["slide_size"]["height_in"]) * EMU)
    page_area = slide_w * slide_h
    slides = {int(slide["slide"]): slide for slide in manifest.get("slides", [])}
    entries_by_slide = defaultdict(list)
    for entry in entries:
        if not str(entry.get("english", "")).strip():
            return fail(f"slide {entry.get('slide')} shape {entry.get('shape_id')}: empty English")
        entries_by_slide[int(entry["slide"])].append(dict(entry))

    layout_edits = list(content.get("layout_edits", []))
    background_edits = list(content.get("background_edits", []))
    planned_entries = []
    slide_confidences = []
    slide_strategies = {}

    for slide_number, slide_entries in sorted(entries_by_slide.items()):
        if slide_number not in slides:
            return fail(f"slide {slide_number} missing from manifest")
        recommended = slides[slide_number].get("layout_health", {}).get("recommended_strategy", "preserve")
        requested_map = content.get("slide_strategies", {})
        requested = str(requested_map.get(str(slide_number), requested_map.get(slide_number, recommended)))
        if requested == "rebuild" or recommended == "rebuild":
            return fail(
                f"slide {slide_number}: full native rebuild requires a complete model-planned "
                "layout_edits map; the automatic card planner is intentionally conservative"
            )
        slide_strategies[slide_number] = "reflow"
        shapes = slides[slide_number].get("shapes", [])
        by_id = {int(shape["shape_id"]): shape for shape in shapes}
        for entry in slide_entries:
            source = by_id.get(int(entry["shape_id"]))
            if source is None:
                return fail(f"slide {slide_number} shape {entry['shape_id']} missing from manifest")
            if not source.get("transform_supported", True):
                return fail(f"slide {slide_number} shape {entry['shape_id']} uses unsupported transform")

        candidates = []
        for shape in shapes:
            shape_box = box(shape)
            area = shape_box[2] * shape_box[3]
            if (
                shape.get("role_hint") == "container-or-decoration"
                and not shape.get("text", "").strip()
                and page_area * 0.015 <= area <= page_area * 0.45
                and shape.get("transform_supported", True)
            ):
                candidates.append({"shape": shape, "box": shape_box})

        assignment = {}
        for entry in slide_entries:
            source_box = box(by_id[int(entry["shape_id"])])
            enclosing = [card for card in candidates if contains(card["box"], source_box)]
            if not enclosing:
                return fail(f"slide {slide_number} shape {entry['shape_id']} is not inside a card")
            card = min(enclosing, key=lambda item: item["box"][2] * item["box"][3])
            assignment[int(entry["shape_id"])] = card

        cards = {int(card["shape"]["shape_id"]): card for card in assignment.values()}
        if len(cards) < 2:
            return fail(f"slide {slide_number}: fewer than two translated cards")

        entry_map = {int(entry["shape_id"]): entry for entry in slide_entries}
        for card in cards.values():
            card["content"] = [
                shape for shape in shapes
                if shape.get("text", "").strip() and contains(card["box"], box(shape))
            ]
            card["content"].sort(key=lambda shape: (box(shape)[1], box(shape)[0]))
            if not card["content"]:
                return fail(f"slide {slide_number} card {card['shape']['shape_id']} has no text")
            pictures = [
                shape for shape in shapes
                if "PICTURE" in str(shape.get("shape_type", "")) and contains(card["box"], box(shape))
            ]
            if pictures:
                return fail(f"slide {slide_number} card {card['shape']['shape_id']} contains a picture")

            first_box, last_box = box(card["content"][0]), box(card["content"][-1])
            card["pad_top"] = max(int(0.08 * EMU), first_box[1] - card["box"][1])
            card["pad_bottom"] = max(
                int(0.08 * EMU), card["box"][1] + card["box"][3] - last_box[1] - last_box[3]
            )
            gaps = []
            for previous, current in zip(card["content"], card["content"][1:]):
                previous_box, current_box = box(previous), box(current)
                gaps.append(max(0, current_box[1] - previous_box[1] - previous_box[3]))
            card["gap"] = min(max(int(statistics.median(gaps)) if gaps else int(0.06 * EMU), int(0.04 * EMU)), int(0.16 * EMU))
            heights = [estimate_shape_height(shape, entry_map.get(int(shape["shape_id"]))) for shape in card["content"]]
            card["heights"] = heights
            card["required_height"] = (
                card["pad_top"] + card["pad_bottom"] + sum(heights)
                + card["gap"] * max(0, len(heights) - 1)
            )

        rows = group_rows(list(cards.values()))
        row_counts = [len(row) for row in rows]
        regularity = min(row_counts) / max(row_counts) if row_counts else 0
        coverage = len(assignment) / len(slide_entries)
        confidence = round(0.65 * coverage + 0.25 * regularity + 0.10, 3)
        if confidence < args.min_confidence:
            return fail(f"slide {slide_number}: confidence {confidence:.3f} below {args.min_confidence:.3f}")

        row_gap_values = []
        for previous, current in zip(rows, rows[1:]):
            previous_bottom = max(card["box"][1] + card["box"][3] for card in previous)
            current_top = min(card["box"][1] for card in current)
            row_gap_values.append(max(0, current_top - previous_bottom))
        row_gap = min(max(int(statistics.median(row_gap_values)) if row_gap_values else int(0.10 * EMU), int(0.06 * EMU)), int(0.20 * EMU))
        row_heights = [max(card["required_height"] for card in row) for row in rows]
        start_top = min(card["box"][1] for card in cards.values())
        available_bottom = slide_h - int(0.18 * EMU)
        needed_bottom = start_top + sum(row_heights) + row_gap * max(0, len(rows) - 1)
        if needed_bottom > available_bottom:
            row_gap = int(0.06 * EMU)
            needed_bottom = start_top + sum(row_heights) + row_gap * max(0, len(rows) - 1)
        if needed_bottom > available_bottom:
            return fail(
                f"slide {slide_number}: card layout needs {needed_bottom / EMU:.3f}in, "
                f"available bottom is {available_bottom / EMU:.3f}in"
            )

        row_top = start_top
        for row, row_height in zip(rows, row_heights):
            for card in row:
                card_id = int(card["shape"]["shape_id"])
                card_target = (card["box"][0], row_top, card["box"][2], row_height)
                layout_edits.append({
                    "slide": slide_number, "shape_id": card_id, "action": "move_resize",
                    "target": target(card_target),
                })
                cursor = row_top + card["pad_top"]
                for shape, shape_height in zip(card["content"], card["heights"]):
                    shape_id = int(shape["shape_id"])
                    old_box = box(shape)
                    shape_target = (old_box[0], cursor, old_box[2], shape_height)
                    if shape_id in entry_map:
                        planned = dict(entry_map[shape_id])
                        planned["mode"] = planned.get("mode", "inline")
                        planned["container_shape_id"] = card_id
                        planned["target"] = target(shape_target)
                        planned_entries.append(planned)
                    else:
                        layout_edits.append({
                            "slide": slide_number, "shape_id": shape_id, "action": "move_resize",
                            "target": target(shape_target),
                        })
                    cursor += shape_height + card["gap"]
            row_top += row_height + row_gap
        slide_confidences.append(confidence)

    result = {
        "slide_size": manifest["slide_size"],
        "layout_type": "card-grid",
        "confidence": min(slide_confidences),
        "failure_reason": None,
        "slide_strategies": slide_strategies,
        "source_content": manifest.get("content_inventory"),
        "background_edits": background_edits,
        "layout_edits": layout_edits,
        "entries": planned_entries,
    }
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"planned card-grid layout for {len(entries_by_slide)} slide(s), "
        f"confidence {result['confidence']:.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
