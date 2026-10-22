#!/usr/bin/env python3
"""Move a merged Skill into place, keep a parent-level backup copy, and register it."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from register_skill import register_skill
from skill_utils import (
    SkillError,
    copy_skill,
    ensure_safe_symlinks,
    parse_frontmatter,
    safe_skill_name,
    tree_digest,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    deploy = subparsers.add_parser(
        "deploy",
        help="Verify the session inputs, move the merged Skill into place, and register it",
    )
    deploy.add_argument("--session", required=True, type=Path)
    deploy.add_argument("--register-timeout", type=float, default=60.0)
    deploy.add_argument(
        "--use-upstream",
        action="store_true",
        help="Deploy an exact copy of the recorded marketplace version instead of a semantic merge",
    )

    list_parser = subparsers.add_parser("list", help="Show the parent-level .backup-merge-skill entry")
    list_parser.add_argument("--target", required=True, type=Path)

    restore = subparsers.add_parser(
        "restore",
        help="Restore the .backup-merge-skill version and remove the current updated Skill",
    )
    restore.add_argument("--target", required=True, type=Path)
    restore.add_argument("--backup-id", required=True)
    restore.add_argument("--register-timeout", type=float, default=60.0)
    restore.add_argument("--confirm-overwrite", action="store_true")
    return parser.parse_args()


def load_skill_name(skill: Path) -> str:
    if not skill.is_dir():
        raise SkillError(f"Skill 目录不存在: {skill}")
    skill_md = skill / "SKILL.md"
    if not skill_md.is_file():
        raise SkillError(f"Skill 目录缺少 SKILL.md: {skill}")
    name = parse_frontmatter(skill_md).get("name", "").strip()
    return safe_skill_name(name)


def backup_root(target: Path) -> Path:
    return target.parent / ".." / ".backup-merge-skill"


def backup_path(target: Path) -> Path:
    return backup_root(target) / target.name


def backup_id(target: Path) -> str:
    digest = hashlib.sha256(str(target.resolve()).encode("utf-8")).hexdigest()
    return f"merge-backup-{digest[:12]}"


def load_session(path: Path) -> dict:
    session_path = path.expanduser().resolve()
    try:
        data = json.loads(session_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SkillError(f"无法读取合并会话 {session_path}: {exc}") from exc
    if not isinstance(data.get("inputs"), dict) or not isinstance(data.get("merged"), dict):
        raise SkillError(f"合并会话缺少 inputs 或 merged: {session_path}")
    for role in ("baseline", "local", "upstream"):
        entry = data["inputs"].get(role)
        if not isinstance(entry, dict) or not entry.get("source") or not entry.get("digest"):
            raise SkillError(f"合并会话缺少 {role} 源路径或摘要: {session_path}")
    if not data["merged"].get("path"):
        raise SkillError(f"合并会话缺少 merged.path: {session_path}")
    data["_session_path"] = str(session_path)
    return data


def ensure_temp_source(source: Path) -> None:
    temp_root = Path.cwd().resolve() / ".temp"
    try:
        source.relative_to(temp_root)
    except ValueError as exc:
        raise SkillError(f"合并产物必须位于当前工作目录的 .temp 下: {source}") from exc


@contextmanager
def target_lock(target: Path) -> Iterator[None]:
    backup_directory = backup_root(target)
    backup_directory.mkdir(parents=True, exist_ok=True)
    lock_path = backup_directory / f".{target.name}.merge.lock"
    try:
        descriptor = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise SkillError(f"Skill 已有更新或回滚任务进行中: {lock_path}") from exc
    try:
        os.close(descriptor)
        yield
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def validate_source(source: Path) -> None:
    ensure_temp_source(source)
    ensure_safe_symlinks(source)
    validator = Path(__file__).with_name("validate_skill.py")
    result = subprocess.run(
        [sys.executable, str(validator), "--skill", str(source)],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stdout.strip() or result.stderr.strip()
        raise SkillError(f"合并产物静态校验失败: {detail}")


def move_directory(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))


def verify_session_inputs(session: dict) -> None:
    for role in ("baseline", "local", "upstream"):
        entry = session["inputs"][role]
        source = Path(entry["source"]).expanduser().resolve()
        if not source.is_dir():
            raise SkillError(f"{role} 角色的原始 Skill 不存在: {source}")
        current_digest = tree_digest(source)
        if current_digest != entry["digest"]:
            raise SkillError(f"{role} 角色的原始 Skill 在分析后发生变化；请重新分析")


def materialize_upstream(session: dict, destination: Path) -> None:
    ensure_temp_source(destination)
    upstream = Path(session["inputs"]["upstream"]["source"]).expanduser().resolve()
    ensure_safe_symlinks(upstream)
    if destination.exists():
        shutil.rmtree(destination)
    copy_skill(upstream, destination)
    if tree_digest(destination) != session["inputs"]["upstream"]["digest"]:
        raise SkillError("技能广场最新版本复制后的摘要不一致")


def deploy(session_path: Path, timeout: float, use_upstream: bool = False) -> dict:
    session = load_session(session_path)
    verify_session_inputs(session)
    source = Path(session["merged"]["path"]).expanduser().resolve()
    target = Path(session["inputs"]["local"]["source"]).expanduser().resolve()
    backup = backup_path(target)
    if use_upstream:
        materialize_upstream(session, source)
    validate_source(source)

    source_name = load_skill_name(source)
    target_name = load_skill_name(target)
    if source_name != target_name:
        raise SkillError(
            f"合并产物和当前 Skill name 不一致: {source_name!r} != {target_name!r}"
        )

    with target_lock(target):
        if backup.exists():
            raise SkillError(f"备份目录已存在，拒绝覆盖: {backup}")
        source_digest = tree_digest(source)
        move_directory(target, backup)
        try:
            move_directory(source, target)
            if tree_digest(target) != source_digest:
                raise SkillError("移动后的 Skill 摘要与合并产物不一致")
            registration = register_skill(target, timeout)
        except Exception as exc:
            recovery_errors = []
            try:
                if target.exists() and not source.exists():
                    move_directory(target, source)
            except Exception as recovery_exc:
                recovery_errors.append(f"无法把合并产物移回临时目录: {recovery_exc}")
            try:
                if backup.exists() and not target.exists():
                    move_directory(backup, target)
            except Exception as recovery_exc:
                recovery_errors.append(f"无法恢复原 Skill: {recovery_exc}")
            detail = f"; {'; '.join(recovery_errors)}" if recovery_errors else ""
            raise SkillError(f"部署或加载失败，已尝试恢复原 Skill: {exc}{detail}") from exc

    return {
        "status": "deployed_and_registered",
        "effective_result": "upstream_exact" if use_upstream else "custom_merge",
        "skill_name": source_name,
        "target_digest": tree_digest(target),
        "backup_available": backup.is_dir(),
        "backup_id": backup_id(target),
        "registration_status": registration["status"],
    }


def restore(target: Path, expected_backup_id: str, timeout: float) -> dict:
    target = target.expanduser().resolve()
    backup = backup_path(target)
    actual_backup_id = backup_id(target)
    if expected_backup_id != actual_backup_id:
        raise SkillError("备份 ID 与当前 Skill 不匹配")
    if not target.is_dir():
        raise SkillError(f"当前 Skill 不存在: {target}")
    if not backup.is_dir():
        raise SkillError(f"备份不存在: {backup}")

    current_name = load_skill_name(target)
    backup_name = load_skill_name(backup)
    if current_name != backup_name:
        raise SkillError(f"当前 Skill 与备份 name 不一致: {current_name!r} != {backup_name!r}")

    temp_root = Path.cwd().resolve() / ".temp"
    temp_root.mkdir(parents=True, exist_ok=True)
    swap = temp_root / f".rollback-{target.name}"
    if swap.exists():
        raise SkillError(f"回滚临时目录已存在: {swap}")

    with target_lock(target):
        move_directory(target, swap)
        try:
            move_directory(backup, target)
            register_skill(target, timeout)
        except Exception as exc:
            if target.exists() and not backup.exists():
                move_directory(target, backup)
            if swap.exists() and not target.exists():
                move_directory(swap, target)
            raise SkillError(f"回滚或重新加载失败，已尝试恢复原状态: {exc}") from exc
        try:
            shutil.rmtree(swap)
        except OSError as exc:
            raise SkillError(
                f"历史版本已恢复并加载，但无法完全移除智能更新版本: {exc}"
            ) from exc

    return {
        "status": "restored_and_registered",
        "restored_backup_id": actual_backup_id,
        "skill_name": backup_name,
        "target_digest": tree_digest(target),
        "backup_available": False,
        "updated_version_removed": True,
        "registration_status": "registered",
    }


def main() -> int:
    args = parse_args()
    try:
        if args.command == "deploy":
            result = deploy(args.session, args.register_timeout, args.use_upstream)
        elif args.command == "list":
            target = args.target.expanduser().resolve()
            backup = backup_path(target)
            result = {
                "backup_exists": backup.is_dir(),
                "backup_id": backup_id(target) if backup.is_dir() else None,
            }
        elif args.command == "restore":
            if not args.confirm_overwrite:
                raise SkillError("回滚需要明确确认；确认后添加 --confirm-overwrite")
            result = restore(args.target, args.backup_id, args.register_timeout)
        else:
            raise SkillError(f"未知命令: {args.command}")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, SkillError, ValueError, RuntimeError) as exc:
        print(f"cache_manager: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
