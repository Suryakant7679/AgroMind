"""Run the suite in a disposable writable checkout inside the application image."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    source = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["AGROMIND_TEST_DATABASE_URL"] = environment.get("DATABASE_URL", "")
    environment["CHROMA_TEST_HOST"] = environment.get("CHROMA_HOST", "")
    environment["CHROMA_TEST_PORT"] = environment.get("CHROMA_PORT", "8000")
    with tempfile.TemporaryDirectory(prefix="agromind-container-tests-") as temporary:
        checkout = Path(temporary) / "checkout"
        shutil.copytree(source, checkout, ignore=shutil.ignore_patterns(
            "data", "uploads", ".git", "__pycache__", ".pytest_cache", ".env", ".env.docker", ".env.production", ".env.local"))
        subprocess.run(["git", "init", "-q", str(checkout)], check=True)
        return subprocess.call([sys.executable, "-m", "pytest", "-q", *sys.argv[1:]], cwd=checkout, env=environment)


if __name__ == "__main__":
    raise SystemExit(main())
