from __future__ import annotations

import os
import shlex
import shutil
from pathlib import Path
from typing import Any

from app.mcp.filesystem_tools import WorkspaceFilesystem
from app.mcp.process_tools import run_process


class OCRReader:
    SUPPORTED = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".pdf"}

    def __init__(self, root: str | Path | None = None) -> None:
        self.files = WorkspaceFilesystem(root, allow_write=False)

    def _command(self, path: Path, language: str) -> list[str]:
        template = os.getenv("AIOS_PDF_OCR_COMMAND" if path.suffix.lower() == ".pdf" else "AIOS_OCR_COMMAND", "").strip()
        if template:
            parts = shlex.split(template)
            replacement = str(path)
            command = [part.replace("{file}", replacement).replace("{language}", language) for part in parts]
            if not any("{file}" in part for part in parts):
                command.append(replacement)
            return command
        executable = shutil.which("tesseract")
        if not executable:
            raise RuntimeError("Tesseract is not installed; install it or configure AIOS_OCR_COMMAND")
        if path.suffix.lower() == ".pdf":
            raise RuntimeError("PDF OCR requires AIOS_PDF_OCR_COMMAND")
        return [executable, str(path), "stdout", "-l", language]

    def extract(self, path: str, language: str = "eng", timeout: int = 30) -> dict[str, Any]:
        resolved = self.files.resolve(path)
        if resolved.suffix.lower() not in self.SUPPORTED:
            raise ValueError(f"Unsupported OCR file type: {resolved.suffix}")
        if not language.replace("+", "").replace("_", "").isalnum() or len(language) > 50:
            raise ValueError("Invalid OCR language")
        result = run_process(self._command(resolved, language), timeout=timeout, cwd=self.files.root, max_output=500_000)
        return {"path": str(resolved.relative_to(self.files.root)), "language": language, "text": result.pop("stdout"), **result}
