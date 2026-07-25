"""Run AgroMind and the independent AI Tutor project together.

This launcher does not copy or modify AI Tutor. It starts that project from its
own directory, then exposes its live UI inside AgroMind's /chatbot page.
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
    configured = os.getenv("AI_TUTOR_ROOT", "../AI tutor").strip()
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
    tutor_env = os.environ.copy()
    tutor_env["AIOS_HOST"] = "127.0.0.1"
    tutor_env["AIOS_PORT"] = tutor_env.get("AI_TUTOR_PORT", "8010")
    tutor_env.setdefault("AIOS_STORAGE_BACKEND", "postgres")
    # Keep PostgreSQL chat persistence while allowing the app to start without
    # the optional local Qdrant service. AI Tutor remains the source of truth.
    tutor_env.setdefault("AIOS_VECTOR_BACKEND", "json")
    os.environ.setdefault("AI_TUTOR_URL", f"http://127.0.0.1:{tutor_env['AIOS_PORT']}")
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
