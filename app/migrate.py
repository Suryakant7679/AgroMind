from __future__ import annotations

import hashlib
import os
from pathlib import Path

try:
    from app.config import load_env
except ModuleNotFoundError:
    from config import load_env


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"


def database_url() -> str:
    value = os.getenv("DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError(
            "DATABASE_URL is missing. Add it to .env, for example "
            "postgresql://aios:password@localhost:5432/aios"
        )
    return value


def migration_files() -> list[Path]:
    return sorted(MIGRATIONS.glob("*.sql"))


def run_migrations() -> int:
    load_env()
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "PostgreSQL driver is missing. Install it with: pip install \"psycopg[binary]\""
        ) from exc

    applied = 0
    with psycopg.connect(database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    checksum TEXT NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute("SELECT version, checksum FROM schema_migrations")
            existing = dict(cursor.fetchall())

        for path in migration_files():
            sql = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
            if path.name in existing:
                if existing[path.name] != checksum:
                    raise RuntimeError(f"Applied migration was modified: {path.name}")
                continue
            with connection.cursor() as cursor:
                cursor.execute(sql)
                cursor.execute(
                    "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
                    (path.name, checksum),
                )
            connection.commit()
            applied += 1
            print(f"Applied {path.name}")
    return applied


def main() -> None:
    count = run_migrations()
    print(f"Database is up to date ({count} migration(s) applied).")


if __name__ == "__main__":
    main()
