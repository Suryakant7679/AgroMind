from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from PIL import Image

from app.mcp.filesystem_tools import WorkspaceFilesystem


class ImageProcessor:
    FORMATS = {"PNG", "JPEG", "WEBP", "BMP", "TIFF"}

    def __init__(self, root: str | Path | None = None, allow_write: bool | None = None) -> None:
        if allow_write is None:
            allow_write = os.getenv("AIOS_MCP_IMAGE_WRITE", "false").lower() == "true"
        self.files = WorkspaceFilesystem(root, allow_write=allow_write)

    def info(self, path: str) -> dict[str, Any]:
        source = self.files.resolve(path)
        with Image.open(source) as image:
            image.verify()
        with Image.open(source) as image:
            return {
                "path": source.relative_to(self.files.root).as_posix(), "format": image.format,
                "width": image.width, "height": image.height, "mode": image.mode,
                "frames": getattr(image, "n_frames", 1),
            }

    def transform(
        self,
        source_path: str,
        output_path: str,
        width: int | None = None,
        height: int | None = None,
        crop: list[int] | None = None,
        image_format: str | None = None,
        quality: int = 85,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        if not self.files.allow_write:
            raise PermissionError("Image writes are disabled; set AIOS_MCP_IMAGE_WRITE=true to enable")
        source = self.files.resolve(source_path)
        output = self.files.resolve(output_path, must_exist=False)
        if output.exists() and not overwrite:
            raise FileExistsError("Output file exists; pass overwrite=true to replace it")
        if width is not None and not 1 <= width <= 10_000:
            raise ValueError("width must be between 1 and 10000")
        if height is not None and not 1 <= height <= 10_000:
            raise ValueError("height must be between 1 and 10000")
        quality = max(1, min(quality, 100))
        target_format = (image_format or output.suffix.lstrip(".") or "PNG").upper()
        if target_format == "JPG": target_format = "JPEG"
        if target_format not in self.FORMATS:
            raise ValueError(f"Unsupported output format: {target_format}")
        with Image.open(source) as opened:
            image = opened.copy()
        if crop is not None:
            if len(crop) != 4 or any(not isinstance(value, int) for value in crop):
                raise ValueError("crop must be [left, top, right, bottom]")
            left, top, right, bottom = crop
            if left < 0 or top < 0 or right <= left or bottom <= top or right > image.width or bottom > image.height:
                raise ValueError("crop rectangle is outside the image")
            image = image.crop((left, top, right, bottom))
        if width is not None or height is not None:
            target_width = width or max(1, round(image.width * (height / image.height)))
            target_height = height or max(1, round(image.height * (width / image.width)))
            image = image.resize((target_width, target_height), Image.Resampling.LANCZOS)
        if target_format == "JPEG" and image.mode not in {"RGB", "L"}:
            image = image.convert("RGB")
        output.parent.mkdir(parents=True, exist_ok=True)
        save_args = {"quality": quality} if target_format in {"JPEG", "WEBP"} else {}
        image.save(output, format=target_format, **save_args)
        return {"source": source.relative_to(self.files.root).as_posix(), "output": output.relative_to(self.files.root).as_posix(), "format": target_format, "width": image.width, "height": image.height, "bytes_written": output.stat().st_size}
