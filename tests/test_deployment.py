from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from app.deployment_backup import create_archive, restore_archive


ROOT = Path(__file__).resolve().parents[1]


class DeploymentBackupTests(unittest.TestCase):
    def test_data_archive_round_trip_and_backup_exclusion(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            (source / "uploads").mkdir(parents=True)
            (source / "uploads" / "note.txt").write_text("important", encoding="utf-8")
            (source / "gateway.json").write_text('{"secret":"value"}', encoding="utf-8")
            (source / "backups").mkdir()
            (source / "backups" / "old.zip").write_bytes(b"old")
            archive = root / "backup.zip"
            created = create_archive(source, archive)
            self.assertEqual(created["file_count"], 2)
            with zipfile.ZipFile(archive) as zipped:
                self.assertIn("data/uploads/note.txt", zipped.namelist())
                self.assertNotIn("data/backups/old.zip", zipped.namelist())
            target = root / "target"
            restored = restore_archive(archive, target)
            self.assertEqual(restored["restored_files"], 2)
            self.assertEqual((target / "uploads" / "note.txt").read_text(encoding="utf-8"), "important")

    def test_restore_requires_force_for_nonempty_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source, target = root / "source", root / "target"
            source.mkdir()
            (source / "new.txt").write_text("new", encoding="utf-8")
            target.mkdir()
            (target / "old.txt").write_text("old", encoding="utf-8")
            archive = root / "backup.zip"
            create_archive(source, archive)
            with self.assertRaises(RuntimeError):
                restore_archive(archive, target)
            restore_archive(archive, target, force=True)
            self.assertFalse((target / "old.txt").exists())
            self.assertEqual((target / "new.txt").read_text(encoding="utf-8"), "new")

    def test_restore_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "malicious.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("data/../../outside.txt", "bad")
            with self.assertRaises(ValueError):
                restore_archive(archive, root / "target")
            self.assertFalse((root / "outside.txt").exists())


class DeploymentConfigurationTests(unittest.TestCase):
    def test_container_runs_as_non_root_and_has_healthcheck(self) -> None:
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("USER aios", dockerfile)
        self.assertIn("HEALTHCHECK", dockerfile)
        self.assertIn('CMD ["python", "-m", "app.main"]', dockerfile)

    def test_compose_contains_complete_checkpoint_stack(self) -> None:
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        for service in ("postgres", "redis", "qdrant", "migrate", "app", "worker", "scheduler", "monitoring", "nginx"):
            self.assertIn(f"  {service}:", compose)
        self.assertIn("service_completed_successfully", compose)
        self.assertIn("internal: true", compose)
        self.assertNotIn("cloudflared", compose)
        self.assertNotIn("quick-tunnel", compose)

    def test_nginx_enforces_https_and_proxies_api_streams(self) -> None:
        nginx = (ROOT / "deploy" / "nginx.conf").read_text(encoding="utf-8")
        self.assertIn("return 301 https://$host$request_uri", nginx)
        self.assertIn("ssl_protocols TLSv1.2 TLSv1.3", nginx)
        self.assertIn("proxy_buffering off", nginx)
        self.assertIn("Strict-Transport-Security", nginx)

    def test_production_template_and_restore_confirmation_are_safe(self) -> None:
        template = (ROOT / ".env.production.example").read_text(encoding="utf-8")
        self.assertIn("AIOS_AUTH_REQUIRED=true", template)
        self.assertIn("AIOS_STORAGE_BACKEND=postgres", template)
        self.assertIn("AIOS_VECTOR_BACKEND=qdrant", template)
        self.assertIn("CHANGE_ME_AT_LEAST_32_RANDOM_BYTES", template)
        restore = (ROOT / "scripts" / "restore.ps1").read_text(encoding="utf-8")
        self.assertIn("[switch]$Force", restore)
        self.assertIn("Re-run with -Force", restore)


if __name__ == "__main__":
    unittest.main()