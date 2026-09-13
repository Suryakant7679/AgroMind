from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any


def workspace_root() -> Path:
    return Path(os.getenv("AIOS_MCP_WORKSPACE_ROOT", Path(__file__).resolve().parents[2])).resolve()


def run_process(command: list[str], timeout: int = 15, cwd: Path | None = None, max_output: int = 50_000) -> dict[str, Any]:
    timeout = max(1, min(timeout, 60))
    completed = subprocess.run(command, cwd=cwd or workspace_root(), text=True, capture_output=True, timeout=timeout, shell=False, check=False)
    return {"ok": completed.returncode == 0, "return_code": completed.returncode, "stdout": completed.stdout[-max_output:], "stderr": completed.stderr[-max_output:]}
