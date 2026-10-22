#!/usr/bin/env python3
"""Create one local-based merge copy in cwd/.temp and record three source digests."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from skill_utils import SkillError, copy_skill, tree_digest, validate_skill_identity


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--local", required=True, type=Path)
    parser.add_argument("--upstream", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    roles = ("baseline", "local", "upstream")
    inputs = [getattr(args, role).expanduser().resolve() for role in roles]
    temp_root = Path.cwd().resolve() / ".temp"
    session_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid.uuid4().hex[:8]
    )
    workspace = temp_root / f"skill-merger-{session_id}"
    created_workspace = False
    try:
        skill_name = validate_skill_identity(inputs)
        temp_root.mkdir(parents=True, exist_ok=True)
        workspace.mkdir()
        created_workspace = True

        reserved_names = {
            "session.json",
            "diff_inventory.json",
            "change_inventory.json",
            "decision_manifest.json",
            "validation_report.json",
            "merge_report.md",
        }
        merged_directory_name = inputs[1].name
        if merged_directory_name in reserved_names:
            merged_directory_name = f"merged-{merged_directory_name}"
        merged_path = workspace / merged_directory_name
        copy_skill(inputs[1], merged_path)

        session = {
            "schema_version": 1,
            "session_id": session_id,
            "skill_name": skill_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "working_directory": str(Path.cwd().resolve()),
            "temp_root": str(temp_root),
            "workspace": str(workspace),
            "inputs": {
                role: {
                    "source": str(source),
                    "source_directory_name": source.name,
                    "digest": tree_digest(source),
                }
                for role, source in zip(roles, inputs)
            },
            "merged": {
                "path": str(merged_path),
                "directory_name": merged_path.name,
                "initial_digest": tree_digest(merged_path),
            },
        }
        (workspace / "session.json").write_text(
            json.dumps(session, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(session, ensure_ascii=False, indent=2))
        return 0
    except (OSError, SkillError) as exc:
        if created_workspace:
            shutil.rmtree(workspace, ignore_errors=True)
        print(f"prepare_workspace: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
