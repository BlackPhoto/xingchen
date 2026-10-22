#!/usr/bin/env python3
"""Shared geometry helpers for bilingual planning and application.

Planning coordinates are always expressed in slide space.  PowerPoint stores
children of a group in the group's child coordinate space, so writes to an
existing grouped shape must be converted back to local coordinates.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator

from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.oxml.ns import qn

EMU = 914400
IDENTITY = (0.0, 0.0, 1.0, 1.0)


@dataclass(frozen=True)
class ShapeGeometry:
    shape: object
    parent_id: int | None
    group_path: tuple[int, ...]
    z_index: int
    local_box: tuple[int, int, int, int]
    slide_box: tuple[int, int, int, int]
    to_slide: tuple[float, float, float, float]
    transform_supported: bool


def _number(node, name: str, default: int = 0) -> int:
    return int(node.get(name, default)) if node is not None else default


def group_child_transform(group) -> tuple[tuple[float, float, float, float], bool]:
    """Return the child-space to parent-space transform for a group shape.

    The bilingual pipeline intentionally supports only axis-aligned group
    transforms. Rotated or flipped groups are reported as unsupported so the
    automatic planner can fall back instead of producing unsafe coordinates.
    """
    grp_pr = getattr(group._element, "grpSpPr", None)
    xfrm = grp_pr.find(qn("a:xfrm")) if grp_pr is not None else None
    if xfrm is None:
        return IDENTITY, True

    supported = not any(
        (
            int(xfrm.get("rot", "0")) != 0,
            xfrm.get("flipH") in ("1", "true", "True"),
            xfrm.get("flipV") in ("1", "true", "True"),
        )
    )
    off = xfrm.find(qn("a:off"))
    ext = xfrm.find(qn("a:ext"))
    child_off = xfrm.find(qn("a:chOff"))
    child_ext = xfrm.find(qn("a:chExt"))
    if off is None or ext is None:
        return IDENTITY, False

    off_x, off_y = _number(off, "x"), _number(off, "y")
    ext_x, ext_y = _number(ext, "cx"), _number(ext, "cy")
    if child_off is None or child_ext is None:
        return (float(off_x), float(off_y), 1.0, 1.0), supported

    child_x, child_y = _number(child_off, "x"), _number(child_off, "y")
    child_cx, child_cy = _number(child_ext, "cx"), _number(child_ext, "cy")
    if child_cx <= 0 or child_cy <= 0 or ext_x <= 0 or ext_y <= 0:
        return IDENTITY, False
    scale_x = ext_x / child_cx
    scale_y = ext_y / child_cy
    return (
        off_x - child_x * scale_x,
        off_y - child_y * scale_y,
        scale_x,
        scale_y,
    ), supported


def compose(
    parent: tuple[float, float, float, float],
    child: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    parent_x, parent_y, parent_sx, parent_sy = parent
    child_x, child_y, child_sx, child_sy = child
    return (
        parent_x + child_x * parent_sx,
        parent_y + child_y * parent_sy,
        parent_sx * child_sx,
        parent_sy * child_sy,
    )


def apply_box(
    box: tuple[int, int, int, int],
    transform: tuple[float, float, float, float],
) -> tuple[int, int, int, int]:
    left, top, width, height = box
    off_x, off_y, scale_x, scale_y = transform
    return (
        int(round(off_x + left * scale_x)),
        int(round(off_y + top * scale_y)),
        int(round(width * scale_x)),
        int(round(height * scale_y)),
    )


def invert_box(
    box: tuple[int, int, int, int],
    transform: tuple[float, float, float, float],
) -> tuple[int, int, int, int]:
    left, top, width, height = box
    off_x, off_y, scale_x, scale_y = transform
    if scale_x == 0 or scale_y == 0:
        raise ValueError("group transform has a zero scale")
    return (
        int(round((left - off_x) / scale_x)),
        int(round((top - off_y) / scale_y)),
        int(round(width / scale_x)),
        int(round(height / scale_y)),
    )


def iter_shape_geometries(
    items: Iterable,
    parent_id: int | None = None,
    group_path: tuple[int, ...] = (),
    to_slide: tuple[float, float, float, float] = IDENTITY,
    transform_supported: bool = True,
) -> Iterator[ShapeGeometry]:
    for z_index, shape in enumerate(items):
        local_box = (int(shape.left), int(shape.top), int(shape.width), int(shape.height))
        slide_box = apply_box(local_box, to_slide)
        shape_rotation = float(getattr(shape, "rotation", 0) or 0)
        own_supported = transform_supported and abs(shape_rotation) < 0.001
        yield ShapeGeometry(
            shape=shape,
            parent_id=parent_id,
            group_path=group_path,
            z_index=z_index,
            local_box=local_box,
            slide_box=slide_box,
            to_slide=to_slide,
            transform_supported=own_supported,
        )
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            child_transform, child_supported = group_child_transform(shape)
            yield from iter_shape_geometries(
                shape.shapes,
                parent_id=shape.shape_id,
                group_path=group_path + (shape.shape_id,),
                to_slide=compose(to_slide, child_transform),
                transform_supported=transform_supported and child_supported,
            )


def geometry_for_shape(items: Iterable, shape_id: int) -> ShapeGeometry:
    matches = [g for g in iter_shape_geometries(items) if g.shape.shape_id == int(shape_id)]
    if len(matches) != 1:
        raise ValueError(f"shape_id {shape_id} matched {len(matches)} shapes")
    return matches[0]
