#!/usr/bin/env python3
"""Collect three-way filesystem states and text diffs without semantic decisions."""

from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from skill_utils import (
    SkillError,
    hash_file,
    iter_entries,
    validate_skill_identity,
)


MISSING: Dict[str, Any] = {
    "state": "missing",
    "hash": None,
    "binary": False,
    "link_target": None,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--local", required=True, type=Path)
    parser.add_argument("--upstream", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-diff-lines", type=int, default=400)
    return parser.parse_args()


def is_binary(path: Path) -> bool:
    with path.open("rb") as handle:
        chunk = handle.read(8192)
    return b"\0" in chunk


def describe(path: Path) -> Dict[str, Any]:
    try:
        if path.is_symlink():
            target = os.readlink(str(path))
            return {
                "state": "symlink",
                "hash": None,
                "binary": False,
                "link_target": target,
            }
        if path.is_dir():
            return {
                "state": "dir",
                "hash": None,
                "binary": False,
                "link_target": None,
            }
        if path.is_file():
            binary = is_binary(path)
            return {
                "state": "file",
                "hash": hash_file(path),
                "binary": binary,
                "link_target": None,
            }
        return {
            "state": "other",
            "hash": None,
            "binary": False,
            "link_target": None,
        }
    except OSError as exc:
        return {
            "state": "unreadable",
            "hash": None,
            "binary": False,
            "link_target": None,
            "error": str(exc),
        }


def fingerprint(item: Dict[str, Any]) -> Tuple[Any, ...]:
    return (
        item.get("state"),
        item.get("hash"),
        item.get("binary"),
        item.get("link_target"),
    )


def classify(
    base: Dict[str, Any], local: Dict[str, Any], upstream: Dict[str, Any]
) -> Tuple[str, Optional[str], str]:
    states = {base["state"], local["state"], upstream["state"]} - {"missing"}
    special = (
        any(item["state"] in {"symlink", "other", "unreadable"} for item in (base, local, upstream))
        or any(item.get("binary") for item in (base, local, upstream))
        or len(states) > 1
    )
    if special:
        return "special_object", None, "需要保守处理的对象或类型变化"

    base_fp, local_fp, upstream_fp = map(fingerprint, (base, local, upstream))
    if local_fp == upstream_fp:
        reason = "三方结果一致" if base_fp == local_fp else "local 与 upstream 产生相同结果"
        return "unchanged_or_same_result", None, reason
    if base_fp == local_fp:
        return "unilateral_change", "upstream", "只有 upstream 相对 baseline 变化"
    if base_fp == upstream_fp:
        return "unilateral_change", "local", "只有 local 相对 baseline 变化"
    return "bilateral_change", None, "local 与 upstream 均产生不同变化"


def read_lines(root: Path, relative: str, item: Dict[str, Any]) -> Optional[List[str]]:
    if item["state"] == "missing":
        return []
    if item["state"] != "file" or item.get("binary"):
        return None
    try:
        return (root / relative).read_text(encoding="utf-8").splitlines(keepends=True)
    except (OSError, UnicodeError):
        return None


def make_diff(
    base_root: Path,
    side_root: Path,
    relative: str,
    base_item: Dict[str, Any],
    side_item: Dict[str, Any],
    side_name: str,
    max_lines: int,
) -> Tuple[str, bool]:
    before = read_lines(base_root, relative, base_item)
    after = read_lines(side_root, relative, side_item)
    if before is None or after is None:
        return "", False
    lines = list(
        difflib.unified_diff(
            before,
            after,
            fromfile=f"baseline/{relative}",
            tofile=f"{side_name}/{relative}",
            n=3,
        )
    )
    truncated = len(lines) > max_lines
    if truncated:
        lines = lines[:max_lines]
        lines.append(f"\n... diff truncated after {max_lines} lines ...\n")
    return "".join(lines), truncated


def collect_paths(roots: Iterable[Path]) -> List[str]:
    paths = set()
    for root in roots:
        paths.update(relative.as_posix() for relative, _ in iter_entries(root))
    return sorted(paths)


def main() -> int:
    args = parse_args()
    roots = {
        "baseline": args.baseline.resolve(),
        "local": args.local.resolve(),
        "upstream": args.upstream.resolve(),
    }
    try:
        skill_name = validate_skill_identity(list(roots.values()))
        entries: List[Dict[str, Any]] = []
        for relative in collect_paths(roots.values()):
            items = {
                role: describe(root / relative) if (root / relative).exists() or (root / relative).is_symlink() else dict(MISSING)
                for role, root in roots.items()
            }
            if all(item["state"] in {"missing", "dir"} for item in items.values()):
                # Ordinary directory creation/deletion is represented by its files.
                # Skipping it avoids duplicate functional evidence.
                continue
            category, changed_side, reason = classify(
                items["baseline"], items["local"], items["upstream"]
            )
            local_diff, local_truncated = make_diff(
                roots["baseline"],
                roots["local"],
                relative,
                items["baseline"],
                items["local"],
                "local",
                args.max_diff_lines,
            )
            upstream_diff, upstream_truncated = make_diff(
                roots["baseline"],
                roots["upstream"],
                relative,
                items["baseline"],
                items["upstream"],
                "upstream",
                args.max_diff_lines,
            )
            entry = {
                "path": relative,
                "category": category,
                "changed_side": changed_side,
                "reason": reason,
                "base_state": items["baseline"]["state"],
                "local_state": items["local"]["state"],
                "upstream_state": items["upstream"]["state"],
                "base_hash": items["baseline"].get("hash"),
                "local_hash": items["local"].get("hash"),
                "upstream_hash": items["upstream"].get("hash"),
                "base_to_local_diff": local_diff,
                "base_to_upstream_diff": upstream_diff,
                "diff_truncated": local_truncated or upstream_truncated,
            }
            for role in ("baseline", "local", "upstream"):
                if items[role].get("link_target") is not None:
                    entry[f"{role}_link_target"] = items[role]["link_target"]
                if items[role].get("error"):
                    entry[f"{role}_error"] = items[role]["error"]
            entries.append(entry)

        counts = Counter(entry["category"] for entry in entries)
        report = {
            "schema_version": 1,
            "skill_name": skill_name,
            "summary": dict(sorted(counts.items())),
            "entries": entries,
        }
        rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
        return 0
    except (OSError, SkillError) as exc:
        print(f"diff_engine: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
