"""Run AgroMind and the independent AI Tutor project together.

This launcher does not copy or modify AI Tutor. It starts that project from its
configured directory (this repository by default), then exposes its live UI inside AgroMind's /chatbot page.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent

def ai_tutor_root() -> Path:
    configured = os.getenv("AI_TUTOR_ROOT", ".").strip()
    candidate = Path(configured)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    return candidate.resolve()

def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env.local")
    load_dotenv(PROJECT_ROOT / ".env")
    tutor_root = ai_tutor_root()
    tutor_entrypoint = tutor_root / "app" / "main.py"
    if not tutor_entrypoint.is_file():
        raise RuntimeError(
            f"AI Tutor was not found at {tutor_root}. "
            "Set AI_TUTOR_ROOT to the independent project directory."
        )
    import socket
    tutor_port = int(os.getenv("AI_TUTOR_PORT", "8010"))
    if not 1 <= tutor_port <= 65535 or tutor_port == 8000:
        raise ValueError("AI_TUTOR_PORT must be valid and different from AgroMind port 8000.")
    for port in (8000, tutor_port):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))
    tutor_env = os.environ.copy()
    tutor_env["AIOS_HOST"] = "127.0.0.1"
    tutor_env["AIOS_PORT"] = str(tutor_port)
    os.environ["AI_TUTOR_URL"] = f"http://127.0.0.1:{tutor_env['AIOS_PORT']}"
    tutor_bootstrap = (
        "import app.config as config; "
        "original_load_env = config.load_env; "
        "config.load_env = lambda path=config.ROOT / '.env', override=True: "
        "original_load_env(path, override=False); "
        "import app.main as main; main.main()"
    )
    tutor_process = subprocess.Popen(
        [sys.executable, "-c", tutor_bootstrap],
        cwd=tutor_root,
        env=tutor_env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        import json
        import time
        from urllib.request import urlopen
        deadline = time.monotonic() + 60
        while True:
            if tutor_process.poll() is not None:
                raise RuntimeError("AI Tutor failed to start; check its configuration.")
            try:
                with urlopen(os.environ["AI_TUTOR_URL"] + "/api/v1/health", timeout=1) as response:
                    if json.load(response).get("service") == "aios-starter":
                        break
            except (OSError, ValueError):
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError("AI Tutor startup timed out; check its database connections.")
            time.sleep(0.2)
        uvicorn.run("agromind.main:app", host="127.0.0.1", port=8000)
    finally:
        tutor_process.terminate()
        try:
            tutor_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            tutor_process.kill()
            tutor_process.wait()

if __name__ == "__main__":
    main()
