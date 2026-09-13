from __future__ import annotations

import shutil
from typing import Any

from app.mcp.process_tools import run_process


class CloudReader:
    """Read-only inventory helpers for AWS, Azure, and Google Cloud CLIs."""

    COMMANDS = {
        "aws": {
            "identity": ["aws", "sts", "get-caller-identity", "--output", "json"],
            "resources": ["aws", "resourcegroupstaggingapi", "get-resources", "--output", "json"],
            "storage": ["aws", "s3api", "list-buckets", "--output", "json"],
        },
        "azure": {
            "identity": ["az", "account", "show", "--output", "json"],
            "resources": ["az", "resource", "list", "--output", "json"],
            "storage": ["az", "storage", "account", "list", "--output", "json"],
        },
        "gcp": {
            "identity": ["gcloud", "auth", "list", "--filter=status:ACTIVE", "--format=json"],
            "resources": ["gcloud", "projects", "list", "--format=json"],
            "storage": ["gcloud", "storage", "buckets", "list", "--format=json"],
        },
    }

    def providers(self) -> list[dict[str, Any]]:
        return [
            {"provider": provider, "installed": shutil.which(commands["identity"][0]) is not None}
            for provider, commands in self.COMMANDS.items()
        ]

    def inspect(self, provider: str, resource: str = "resources", timeout: int = 30) -> dict[str, Any]:
        provider = provider.strip().lower()
        resource = resource.strip().lower()
        if provider not in self.COMMANDS:
            raise ValueError("Provider must be one of: aws, azure, gcp")
        if resource not in self.COMMANDS[provider]:
            raise ValueError("Resource must be one of: identity, resources, storage")
        command = self.COMMANDS[provider][resource]
        if shutil.which(command[0]) is None:
            raise RuntimeError(f"{command[0]} CLI is not installed or is not on PATH")
        return {"provider": provider, "resource": resource, **run_process(command, timeout=timeout)}
