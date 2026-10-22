#!/usr/bin/env python3
"""Register an installed Skill by POSTing its SKILL.md path to the desktop server."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, Tuple


def resolve_basic_auth() -> Optional[Tuple[str, str]]:
    """Read desktop-provided Basic Auth credentials from the environment."""
    username = (
        os.getenv("SUPER_AGENT_OPENCODE_USERNAME")
        or os.getenv("OPENCODE_SERVER_USERNAME")
        or ""
    ).strip()
    password = (
        os.getenv("SUPER_AGENT_OPENCODE_PASSWORD")
        or os.getenv("OPENCODE_SERVER_PASSWORD")
        or ""
    )
    if not username or not password:
        return None
    return username, password


def resolve_skill_md(path: Path) -> Path:
    candidate = path.expanduser().resolve(strict=False)
    if candidate.is_dir():
        candidate = candidate / "SKILL.md"
    if not candidate.is_file():
        raise ValueError(f"SKILL.md 不存在: {candidate}")
    return candidate


def register_skill(path: Path, timeout: float = 60.0) -> dict:
    skill_md = resolve_skill_md(path)
    base = (os.getenv("SUPER_AGENT_SERVER_URL") or "").strip()
    if not base:
        raise ValueError("缺少或未设置 SUPER_AGENT_SERVER_URL")

    request = urllib.request.Request(
        f"{base.rstrip('/')}/skill/add",
        data=json.dumps({"path": str(skill_md)}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    auth = resolve_basic_auth()
    if auth:
        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode("utf-8")).decode("ascii")
        request.add_header("Authorization", f"Basic {token}")

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            status = getattr(response, "status", 200)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Skill 加载失败: HTTP {exc.code}: {detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Skill 加载请求失败: {exc.reason}") from exc

    if not 200 <= status < 300:
        raise RuntimeError(f"Skill 加载失败: HTTP {status}: {body}")
    return {
        "status": "registered",
        "skill_md": str(skill_md),
        "endpoint": f"{base.rstrip('/')}/skill/add",
        "response": body,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="Installed Skill directory or SKILL.md path")
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                register_skill(args.path, args.timeout),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"register_skill: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
