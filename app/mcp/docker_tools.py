from __future__ import annotations

import json
import re
from typing import Any

from app.mcp.process_tools import run_process


def _safe_name(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", name): raise ValueError("Invalid Docker object name")
    return name


def list_containers(all_containers: bool = True) -> list[dict[str, Any]]:
    command = ["docker", "ps"] + (["--all"] if all_containers else []) + ["--format", "{{json .}}"]
    result = run_process(command, timeout=20)
    if not result["ok"]: return [result]
    return [json.loads(line) for line in result["stdout"].splitlines() if line.strip()]


def inspect_container(name: str) -> dict[str, Any]:
    result = run_process(["docker", "inspect", _safe_name(name)], timeout=20)
    if result["ok"]:
        result["data"] = json.loads(result.pop("stdout"))[0]
    return result


def container_logs(name: str, tail: int = 100) -> dict[str, Any]:
    return run_process(["docker", "logs", "--tail", str(max(1, min(tail, 1000))), _safe_name(name)], timeout=20)


def list_images() -> list[dict[str, Any]]:
    result = run_process(["docker", "images", "--format", "{{json .}}"], timeout=20)
    if not result["ok"]: return [result]
    return [json.loads(line) for line in result["stdout"].splitlines() if line.strip()]
