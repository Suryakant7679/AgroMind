from __future__ import annotations

import os
import re
import shutil
from typing import Any

from app.mcp.process_tools import run_process


DEFAULT_COMMANDS = {"rg", "node", "npm", "npm.cmd", "where", "where.exe", "whoami", "whoami.exe", "hostname", "hostname.exe"}


def run_terminal(command: str, args: list[str] | None = None, timeout: int = 15) -> dict[str, Any]:
    allowed = DEFAULT_COMMANDS | {item.strip() for item in os.getenv("AIOS_MCP_TERMINAL_COMMANDS", "").split(",") if item.strip()}
    if command not in allowed or not re.fullmatch(r"[A-Za-z0-9_.-]+", command):
        raise PermissionError(f"Command is not allowlisted: {command}")
    executable = shutil.which(command)
    if not executable:
        raise FileNotFoundError(f"Command is not installed: {command}")
    values = [str(value) for value in (args or [])]
    if any("\x00" in value or len(value) > 4000 for value in values):
        raise ValueError("Invalid command argument")
    return run_process([executable, *values], timeout=timeout)
