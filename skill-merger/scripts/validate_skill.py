#!/usr/bin/env python3
"""Statically validate a merged Skill without executing its code."""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import unquote, urlsplit

from skill_utils import SkillError, iter_entries, parse_frontmatter


LINK_PATTERN = re.compile(r"!?\[[^\]]*]\(([^)]+)\)")
CONFLICT_PATTERNS = (
    re.compile(r"^<<<<<<<(?:\s|$)", re.MULTILINE),
    re.compile(r"^=======$", re.MULTILINE),
    re.compile(r"^>>>>>>>(?:\s|$)", re.MULTILINE),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def inside(root: Path, candidate: Path) -> bool:
    try:
        return Path(os.path.commonpath([str(root), str(candidate)])) == root
    except ValueError:
        return False


def validate_markdown_links(path: Path, root: Path, errors: List[Dict[str, str]]) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return
    for raw in LINK_PATTERN.findall(text):
        target = raw.strip().strip("<>")
        if " " in target and not target.startswith(("http://", "https://")):
            target = target.split(" ", 1)[0]
        parsed = urlsplit(target)
        if parsed.scheme or target.startswith(("#", "/")) or not parsed.path:
            continue
        relative_target = Path(unquote(parsed.path))
        resolved = (path.parent / relative_target).resolve(strict=False)
        if not inside(root, resolved):
            errors.append(
                {
                    "code": "link_outside_root",
                    "path": str(path.relative_to(root)),
                    "message": f"Markdown 引用越出 Skill 根目录: {target}",
                }
            )
        elif not resolved.exists():
            errors.append(
                {
                    "code": "broken_link",
                    "path": str(path.relative_to(root)),
                    "message": f"Markdown 引用不存在: {target}",
                }
            )


def main() -> int:
    args = parse_args()
    root = args.skill.resolve()
    errors: List[Dict[str, str]] = []
    warnings: List[Dict[str, str]] = []

    try:
        if not root.is_dir():
            raise SkillError(f"Skill 目录不存在: {root}")
        skill_md = root / "SKILL.md"
        if not skill_md.is_file():
            errors.append(
                {"code": "missing_skill_md", "path": "SKILL.md", "message": "缺少 SKILL.md"}
            )
        else:
            try:
                frontmatter = parse_frontmatter(skill_md)
                for field in ("name", "description"):
                    if not frontmatter.get(field, "").strip():
                        errors.append(
                            {
                                "code": "missing_frontmatter_field",
                                "path": "SKILL.md",
                                "message": f"frontmatter 缺少 {field}",
                            }
                        )
            except SkillError as exc:
                errors.append(
                    {"code": "invalid_frontmatter", "path": "SKILL.md", "message": str(exc)}
                )

        for relative, absolute in iter_entries(root):
            relative_text = relative.as_posix()
            if absolute.is_symlink():
                try:
                    resolved = absolute.resolve(strict=False)
                except RuntimeError:
                    errors.append(
                        {
                            "code": "unsafe_symlink",
                            "path": relative_text,
                            "message": "symlink 循环或无法解析",
                        }
                    )
                    continue
                if not inside(root, resolved):
                    errors.append(
                        {
                            "code": "unsafe_symlink",
                            "path": relative_text,
                            "message": f"symlink 越出 Skill 根目录: {os.readlink(str(absolute))}",
                        }
                    )
                elif not resolved.exists():
                    errors.append(
                        {
                            "code": "broken_symlink",
                            "path": relative_text,
                            "message": f"symlink 目标不存在: {os.readlink(str(absolute))}",
                        }
                    )
                continue
            if not absolute.is_file():
                continue

            try:
                raw = absolute.read_bytes()
            except OSError as exc:
                errors.append(
                    {"code": "unreadable_file", "path": relative_text, "message": str(exc)}
                )
                continue
            if b"\0" in raw[:8192]:
                warnings.append(
                    {
                        "code": "binary_file",
                        "path": relative_text,
                        "message": "二进制文件未做内容级静态校验",
                    }
                )
                continue
            try:
                text = raw.decode("utf-8")
            except UnicodeError:
                warnings.append(
                    {
                        "code": "non_utf8_file",
                        "path": relative_text,
                        "message": "非 UTF-8 文件未做内容级静态校验",
                    }
                )
                continue

            if all(pattern.search(text) for pattern in CONFLICT_PATTERNS):
                errors.append(
                    {
                        "code": "conflict_markers",
                        "path": relative_text,
                        "message": "存在未解决的合并冲突标记",
                    }
                )

            if absolute.suffix == ".py":
                try:
                    ast.parse(text, filename=relative_text)
                except SyntaxError as exc:
                    errors.append(
                        {
                            "code": "python_syntax",
                            "path": relative_text,
                            "message": f"{exc.msg} (line {exc.lineno})",
                        }
                    )
            elif absolute.suffix == ".json":
                try:
                    json.loads(text)
                except json.JSONDecodeError as exc:
                    errors.append(
                        {
                            "code": "json_syntax",
                            "path": relative_text,
                            "message": f"{exc.msg} (line {exc.lineno})",
                        }
                    )
            if absolute.suffix.lower() in {".md", ".markdown"}:
                validate_markdown_links(absolute, root, errors)

        report: Dict[str, Any] = {
            "schema_version": 1,
            "skill": str(root),
            "valid": not errors,
            "errors": errors,
            "warnings": warnings,
        }
        rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
        return 0 if not errors else 1
    except (OSError, SkillError) as exc:
        print(f"validate_skill: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
