#!/usr/bin/env python3
"""Register a Skill with the local server and enforce the new-Skill limit."""

import argparse
import json
import logging
import os
import re
import sys
import tempfile
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

MAX_ENABLED_SKILLS = 100
SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def emit_result(ok: bool, reason: str, **extra: object) -> None:
    """Emit a concise, machine-readable outcome for the calling Skill."""
    print(json.dumps({"ok": ok, "reason": reason, **extra}, ensure_ascii=False))


def resolve_basic_auth() -> tuple[str, str] | None:
    """Read desktop-provided Basic Auth credentials from env."""
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


def resolve_skill_storage_dir() -> Path:
    """Resolve skill storage root from TELEAGENT_CONFIG_DIR with legacy fallback."""
    config_dir = os.getenv("TELEAGENT_CONFIG_DIR")
    if config_dir and config_dir.strip():
        return Path(config_dir.strip()).expanduser() / "skills"
    return Path.home() / ".config" / "teleai-super-agent" / "skills"


def require_config_dir() -> Path:
    """Return TELEAGENT_CONFIG_DIR without permitting a fallback for new Skills."""
    value = (os.getenv("TELEAGENT_CONFIG_DIR") or "").strip()
    if not value:
        raise ValueError("Missing or empty TELEAGENT_CONFIG_DIR")
    return Path(value).expanduser()


def strip_jsonc(text: str) -> str:
    """Remove JSONC comments and trailing commas while respecting JSON strings."""
    out: list[str] = []
    index = 0
    in_string = False
    escaped = False
    while index < len(text):
        char = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            out.append(char)
            index += 1
            continue
        if char == "/" and following == "/":
            index += 2
            while index < len(text) and text[index] not in "\r\n":
                index += 1
            continue
        if char == "/" and following == "*":
            end = text.find("*/", index + 2)
            if end < 0:
                raise ValueError("unterminated JSONC block comment")
            index = end + 2
            continue
        out.append(char)
        index += 1
    return re.sub(r",\s*([}\]])", r"\1", "".join(out))


class ConfigLock:
    """Portable exclusive lock for the read-count-write critical section."""

    def __init__(self, config_file: Path) -> None:
        self.path = config_file.with_name(config_file.name + ".skill-limit.lock")
        self.fd: int | None = None

    def __enter__(self) -> "ConfigLock":
        deadline = time.monotonic() + 10
        while True:
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.write(self.fd, str(os.getpid()).encode("ascii"))
                return self
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"timed out waiting for config lock: {self.path}")
                time.sleep(0.05)

    def __exit__(self, *_: object) -> None:
        if self.fd is not None:
            os.close(self.fd)
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def load_config(config_file: Path) -> dict[str, object]:
    if not config_file.exists():
        return {}
    try:
        data = json.loads(strip_jsonc(config_file.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"cannot parse {config_file}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{config_file} must contain a JSON object")
    return data


def write_config_atomic(config_file: Path, config: dict[str, object]) -> None:
    config_file.parent.mkdir(parents=True, exist_ok=True)
    mode = config_file.stat().st_mode & 0o777 if config_file.exists() else 0o600
    fd, temp_name = tempfile.mkstemp(prefix=f".{config_file.name}.", dir=config_file.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(config, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, mode)
        os.replace(temp_name, config_file)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def write_skill_permission(skill_name: str) -> str:
    """Persist allow/deny and return the registration state."""
    if not SKILL_NAME_RE.fullmatch(skill_name) or ".." in skill_name:
        raise ValueError(f"invalid skill name: {skill_name!r}")
    config_file = require_config_dir() / "TeleAgent.jsonc"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    with ConfigLock(config_file):
        config = load_config(config_file)
        permission = config.setdefault("permission", {})
        if not isinstance(permission, dict):
            raise ValueError("permission in TeleAgent.jsonc must be an object")
        skills = permission.setdefault("skill", {})
        if not isinstance(skills, dict):
            raise ValueError("permission.skill in TeleAgent.jsonc must be an object")
        enabled_count = sum(value == "allow" for value in skills.values())
        if skills.get(skill_name) == "allow":
            return "already_enabled"
        if enabled_count >= MAX_ENABLED_SKILLS:
            skills[skill_name] = "deny"
            write_config_atomic(config_file, config)
            return "registered_denied"
        skills[skill_name] = "allow"
        write_config_atomic(config_file, config)
        return "enabled"


def main(argv: list[str] | None = None) -> int:
    """Parse args, resolve path, POST, return shell exit code."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(
        description="POST skill path to SUPER_AGENT_SERVER_URL/skill/add",
    )
    parser.add_argument("path", help="Relative or absolute path to SKILL.md")
    args = parser.parse_args(argv)

    raw = args.path.strip()
    if not raw:
        logger.error("path must be non-empty")
        emit_result(False, "invalid_path")
        return 1
    user_path = Path(raw).expanduser()
    skills_root = resolve_skill_storage_dir()
    candidate = user_path if user_path.is_absolute() else skills_root / user_path
    skill_path = str(candidate.resolve(strict=False))

    if not Path(skill_path).is_file():
        logger.error("SKILL.md not found: %s", skill_path)
        emit_result(False, "skill_file_not_found")
        return 1

    try:
        activation = write_skill_permission(Path(skill_path).parent.name)
    except (OSError, RuntimeError, ValueError) as exc:
        logger.error("Failed to update Skill permission: %s", exc)
        emit_result(False, "permission_update_failed")
        return 1

    base = os.getenv("SUPER_AGENT_SERVER_URL")
    if not base or not str(base).strip():
        logger.error("Missing or empty SUPER_AGENT_SERVER_URL")
        emit_result(False, "missing_server_url")
        return 1

    try:
        response = requests.post(
            f"{str(base).strip().rstrip('/')}/skill/add",
            json={"path": skill_path},
            auth=resolve_basic_auth(),
            timeout=60.0,
        )
    except requests.RequestException as exc:
        logger.error("Request failed: %s", exc)
        emit_result(False, "registration_request_failed")
        return 1

    if response.ok:
        logger.info("Register success")
        emit_result(True, activation)
        return 0

    logger.error("Error: HTTP %s: %s", response.status_code, response.text or response.reason)
    emit_result(False, "registration_failed", status=response.status_code)
    return 1


if __name__ == "__main__":
    sys.exit(main())
