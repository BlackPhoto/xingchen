#!/usr/bin/env python3
"""Content inventory and preservation checks for bilingual slide re-layouts."""
from __future__ import annotations

import hashlib
import json
import unicodedata
from pathlib import Path

from pptx.enum.shapes import MSO_SHAPE_TYPE

from geometry import iter_shape_geometries


def normalize_text(value: str) -> str:
    """Normalize run and line-break differences without rewriting words."""
    return " ".join(unicodedata.normalize("NFC", value or "").split())


def _sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _chart_payload(shape):
    payload = []
    try:
        for series in shape.chart.series:
            values = []
            try:
                values = list(series.values)
            except (AttributeError, TypeError, ValueError):
                pass
            payload.append({"name": normalize_text(str(series.name or "")), "values": values})
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    return payload


def classify_shape_role(shape, slide_box, slide_area, z_index=0):
    text = normalize_text(shape.text) if getattr(shape, "has_text_frame", False) else ""
    left, top, width, height = slide_box
    area = width * height
    coverage = area / max(1, slide_area)
    name = str(shape.name).lower()
    background_name = any(token in name for token in ("background", "backdrop", "背景", "底图"))
    near_full_slide = (
        coverage >= 0.90
        and left <= width * 0.03
        and top <= height * 0.03
    )
    if text:
        return "text"
    if getattr(shape, "has_table", False):
        return "table"
    if getattr(shape, "has_chart", False):
        return "chart"
    if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
        if background_name or (near_full_slide and z_index <= 2):
            return "background-picture"
        return "content-picture"
    if background_name or (coverage >= 0.90 and z_index <= 2):
        return "background-shape"
    if area > 0:
        return "container-or-decoration"
    return "decoration"


def _shape_record(shape, geometry, slide_area):
    text = normalize_text(shape.text) if getattr(shape, "has_text_frame", False) else ""
    role = classify_shape_role(shape, geometry.slide_box, slide_area, geometry.z_index)
    record = {
        "shape_id": int(shape.shape_id),
        "name": str(shape.name),
        "shape_type": str(shape.shape_type),
        "role": role,
    }
    protected = False
    if text:
        record["text"] = text
        protected = True
    if getattr(shape, "has_table", False):
        record["table"] = [
            [normalize_text(cell.text) for cell in row.cells]
            for row in shape.table.rows
        ]
        protected = True
    if getattr(shape, "has_chart", False):
        record["chart"] = _chart_payload(shape)
        protected = True
    if role in ("content-picture", "background-picture"):
        record["image_sha256"] = _sha256(shape.image.blob)
        protected = role == "content-picture"
    record["protected"] = protected
    return record


def snapshot_presentation(prs):
    slides = []
    slide_area = int(prs.slide_width) * int(prs.slide_height)
    for slide_number, slide in enumerate(prs.slides, 1):
        shapes = []
        backgrounds = []
        for geometry in iter_shape_geometries(slide.shapes):
            record = _shape_record(geometry.shape, geometry, slide_area)
            if record["protected"]:
                shapes.append(record)
            elif record["role"] in ("background-picture", "background-shape"):
                backgrounds.append(record)
        notes = ""
        try:
            notes = normalize_text(slide.notes_slide.notes_text_frame.text)
        except (AttributeError, KeyError, ValueError):
            pass
        slides.append({
            "slide": slide_number,
            "shapes": shapes,
            "backgrounds": backgrounds,
            "notes": notes,
        })
    return {"slide_count": len(slides), "slides": slides}


def write_snapshot(prs, path):
    data = snapshot_presentation(prs)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def protected_shape_ids(snapshot):
    return {
        (int(slide["slide"]), int(shape["shape_id"]))
        for slide in snapshot.get("slides", [])
        for shape in slide.get("shapes", [])
        if shape.get("protected")
    }


def compare_snapshot(source_snapshot, target_prs):
    """Return preservation errors; bilingual English may be appended to source text."""
    errors = []
    target = snapshot_presentation(target_prs)
    if target["slide_count"] != source_snapshot.get("slide_count"):
        errors.append(
            f"slide count changed: source {source_snapshot.get('slide_count')}, "
            f"target {target['slide_count']}"
        )
    target_slides = {int(slide["slide"]): slide for slide in target["slides"]}
    for source_slide in source_snapshot.get("slides", []):
        slide_number = int(source_slide["slide"])
        target_slide = target_slides.get(slide_number)
        if target_slide is None:
            errors.append(f"slide {slide_number}: missing")
            continue
        target_shapes = {int(shape["shape_id"]): shape for shape in target_slide.get("shapes", [])}
        for source_shape in source_slide.get("shapes", []):
            shape_id = int(source_shape["shape_id"])
            target_shape = target_shapes.get(shape_id)
            if target_shape is None:
                errors.append(f"slide {slide_number} shape {shape_id}: protected content missing")
                continue
            source_text = source_shape.get("text", "")
            if source_text and source_text not in target_shape.get("text", ""):
                errors.append(f"slide {slide_number} shape {shape_id}: source text changed")
            for key, label in (
                ("table", "table content"),
                ("chart", "chart data"),
                ("image_sha256", "image media"),
            ):
                if key in source_shape and source_shape.get(key) != target_shape.get(key):
                    errors.append(f"slide {slide_number} shape {shape_id}: {label} changed")
        source_notes = source_slide.get("notes", "")
        if source_notes and source_notes not in target_slide.get("notes", ""):
            errors.append(f"slide {slide_number}: speaker notes changed")
    return errors
