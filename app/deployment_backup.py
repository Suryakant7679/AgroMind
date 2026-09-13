from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_archive(data_dir: Path, output: Path) -> dict[str, object]:
    data_dir = data_dir.resolve()
    output = output.resolve()
    if not data_dir.is_dir():
        raise FileNotFoundError(f"Data directory does not exist: {data_dir}")
    output.parent.mkdir(parents=True, exist_ok=True)
    included: list[str] = []
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in data_dir.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(data_dir)
            if relative.parts and relative.parts[0] == "backups":
                continue
            if path.resolve() == output:
                continue
            archive.write(path, f"data/{relative.as_posix()}")
            included.append(relative.as_posix())
        archive.writestr("backup-manifest.json", json.dumps({"created_at": utc_now(), "file_count": len(included), "files": included}, indent=2))
    return {"archive": str(output), "file_count": len(included), "size": output.stat().st_size}


def _validated_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members: list[zipfile.ZipInfo] = []
    for member in archive.infolist():
        path = Path(member.filename)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"Unsafe backup member: {member.filename}")
        if member.filename == "backup-manifest.json":
            continue
        if not path.parts or path.parts[0] != "data":
            raise ValueError(f"Unexpected backup member: {member.filename}")
        members.append(member)
    return members


def restore_archive(archive_path: Path, data_dir: Path, force: bool = False) -> dict[str, object]:
    archive_path = archive_path.resolve()
    data_dir = data_dir.resolve()
    if not archive_path.is_file():
        raise FileNotFoundError(f"Backup archive does not exist: {archive_path}")
    if data_dir.exists() and any(data_dir.iterdir()) and not force:
        raise RuntimeError("Target data directory is not empty; pass --force to restore it")
    data_dir.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="aios-restore-", dir=data_dir.parent))
    rollback = data_dir.parent / f".aios-rollback-{uuid4().hex}"
    restored = 0
    try:
        with zipfile.ZipFile(archive_path) as archive:
            members = _validated_members(archive)
            for member in members:
                relative = Path(*Path(member.filename).parts[1:])
                destination = (stage / relative).resolve()
                if stage != destination and stage not in destination.parents:
                    raise ValueError(f"Unsafe backup destination: {member.filename}")
                if member.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target)
                restored += 1
        data_dir.mkdir(parents=True, exist_ok=True)
        rollback.mkdir(parents=True, exist_ok=False)
        existing = list(data_dir.iterdir())
        for item in existing:
            shutil.move(str(item), rollback / item.name)
        try:
            for item in list(stage.iterdir()):
                shutil.move(str(item), data_dir / item.name)
        except Exception:
            for item in list(data_dir.iterdir()):
                if item.is_dir(): shutil.rmtree(item)
                else: item.unlink()
            for item in list(rollback.iterdir()):
                shutil.move(str(item), data_dir / item.name)
            raise
        shutil.rmtree(rollback)
        return {"archive": str(archive_path), "data_dir": str(data_dir), "restored_files": restored}
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        if rollback.exists():
            shutil.rmtree(rollback, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or restore AIOS local-data archives")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--data-dir", default=os.getenv("AIOS_DATA_ROOT", "/app/data"))
    create.add_argument("--output", required=True)
    restore = subparsers.add_parser("restore")
    restore.add_argument("archive")
    restore.add_argument("--data-dir", default=os.getenv("AIOS_DATA_ROOT", "/app/data"))
    restore.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.command == "create":
        result = create_archive(Path(args.data_dir), Path(args.output))
    else:
        result = restore_archive(Path(args.archive), Path(args.data_dir), force=args.force)
    print(json.dumps(result))


if __name__ == "__main__":
    main()