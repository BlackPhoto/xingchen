#!/usr/bin/env python3
"""Shared deterministic helpers for skill-merger scripts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Dict, Iterator, List, Tuple


EXCLUDED_NAMES = {
    ".DS_Store",
    ".git",
    ".merge_report.md",
    "__pycache__",
    "decision_manifest.json",
    "diff_inventory.json",
    "merge_report.md",
    "validation_report.json",
}


class SkillError(RuntimeError):
    """Raised for an invalid or unsafe Skill operation."""


def _unquote_yaml_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        quote = value[0]
        if quote == "'":
            return value[1:-1].replace("''", "'")
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value[1:-1]
    return value


def parse_frontmatter(path: Path) -> Dict[str, str]:
    """Parse the top-level scalar fields needed by the merger."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SkillError(f"无法读取 {path}: {exc}") from exc

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillError(f"{path} 缺少 YAML frontmatter")

    try:
        closing = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration as exc:
        raise SkillError(f"{path} 的 YAML frontmatter 未闭合") from exc

    result: Dict[str, str] = {}
    index = 1
    key_pattern = re.compile(r"^([A-Za-z0-9_-]+):(?:\s*(.*))?$")
    while index < closing:
        line = lines[index]
        match = key_pattern.match(line)
        if not match:
            index += 1
            continue
        key, raw_value = match.group(1), (match.group(2) or "")
        if raw_value in {"|", ">"}:
            block: List[str] = []
            index += 1
            while index < closing and (
                not lines[index].strip() or lines[index].startswith((" ", "\t"))
            ):
                block.append(lines[index].lstrip())
                index += 1
            separator = "\n" if raw_value == "|" else " "
            result[key] = separator.join(block).strip()
            continue
        result[key] = _unquote_yaml_scalar(raw_value)
        index += 1
    return result


def validate_skill_identity(skill_dirs: List[Path]) -> str:
    names: List[str] = []
    for directory in skill_dirs:
        if not directory.is_dir():
            raise SkillError(f"Skill 目录不存在或不是目录: {directory}")
        skill_md = directory / "SKILL.md"
        if not skill_md.is_file():
            raise SkillError(f"Skill 目录缺少 SKILL.md: {directory}")
        name = parse_frontmatter(skill_md).get("name", "").strip()
        if not name:
            raise SkillError(f"SKILL.md 缺少 frontmatter name: {skill_md}")
        names.append(name)
    if len(set(names)) != 1:
        raise SkillError(f"三个 Skill 的 name 不一致: {names}")
    return names[0]


def should_exclude(relative_path: Path) -> bool:
    return any(part in EXCLUDED_NAMES for part in relative_path.parts)


def iter_entries(root: Path) -> Iterator[Tuple[Path, Path]]:
    """Yield (relative, absolute) entries without following symlinks."""
    for current, dirs, files in os.walk(str(root), topdown=True, followlinks=False):
        current_path = Path(current)
        relative_current = current_path.relative_to(root)

        kept_dirs: List[str] = []
        for name in sorted(dirs):
            relative = relative_current / name
            if should_exclude(relative):
                continue
            absolute = current_path / name
            yield relative, absolute
            if not absolute.is_symlink():
                kept_dirs.append(name)
        dirs[:] = kept_dirs

        for name in sorted(files):
            relative = relative_current / name
            if not should_exclude(relative):
                yield relative, current_path / name


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def tree_digest(root: Path) -> str:
    """Hash paths, object types, permissions, contents, and link targets."""
    if not root.is_dir():
        raise SkillError(f"无法计算目录摘要: {root}")
    digest = hashlib.sha256()
    for relative, absolute in sorted(iter_entries(root), key=lambda item: item[0].as_posix()):
        stat = absolute.lstat()
        if absolute.is_symlink():
            kind = "symlink"
            payload = os.readlink(str(absolute)).encode("utf-8", errors="surrogateescape")
        elif absolute.is_dir():
            kind = "dir"
            payload = b""
        elif absolute.is_file():
            kind = "file"
            payload = bytes.fromhex(hash_file(absolute).split(":", 1)[1])
        else:
            kind = "other"
            payload = b""
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(kind.encode("ascii"))
        digest.update(b"\0")
        digest.update(f"{stat.st_mode & 0o777:o}".encode("ascii"))
        digest.update(b"\0")
        digest.update(payload)
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def count_files(root: Path) -> int:
    return sum(1 for _, path in iter_entries(root) if path.is_file() and not path.is_symlink())


def copy_skill(source: Path, destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        raise SkillError(f"目标路径已存在: {destination}")

    def ignore(directory: str, names: List[str]) -> List[str]:
        base = Path(directory)
        ignored: List[str] = []
        for name in names:
            try:
                relative = (base / name).relative_to(source)
            except ValueError:
                continue
            if should_exclude(relative):
                ignored.append(name)
        return ignored

    shutil.copytree(source, destination, symlinks=True, ignore=ignore)


def ensure_safe_symlinks(root: Path) -> None:
    root_resolved = root.resolve()
    for relative, absolute in iter_entries(root):
        if not absolute.is_symlink():
            continue
        try:
            resolved = absolute.resolve(strict=False)
        except RuntimeError as exc:
            raise SkillError(f"symlink 循环或无法解析: {relative}") from exc
        try:
            common = Path(os.path.commonpath([str(root_resolved), str(resolved)]))
        except ValueError as exc:
            raise SkillError(f"symlink 无法安全解析: {relative}") from exc
        if common != root_resolved:
            raise SkillError(f"symlink 越出 Skill 根目录: {relative} -> {os.readlink(str(absolute))}")
        if not resolved.exists():
            raise SkillError(f"symlink 目标不存在: {relative} -> {os.readlink(str(absolute))}")


def safe_skill_name(name: str) -> str:
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", name)
        or ".." in name
    ):
        raise SkillError(f"不安全的 Skill name: {name!r}")
    return name
