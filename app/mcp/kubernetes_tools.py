from __future__ import annotations

import re
from typing import Any

from app.mcp.process_tools import run_process


def _safe(value: str, label: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,200}", value) or value.startswith("-"): raise ValueError(f"Invalid {label}")
    return value


class KubernetesReader:
    def contexts(self) -> dict[str, Any]: return run_process(["kubectl", "config", "get-contexts", "-o", "name"], 20)
    def namespaces(self) -> dict[str, Any]: return run_process(["kubectl", "get", "namespaces", "-o", "json"], 20)
    def resources(self, resource: str = "pods", namespace: str = "default", limit: int = 200) -> dict[str, Any]:
        result = run_process(["kubectl", "get", _safe(resource, "resource"), "--namespace", _safe(namespace, "namespace"), "-o", "json"], 30, max_output=200_000)
        return result
    def describe(self, resource: str, name: str, namespace: str = "default") -> dict[str, Any]:
        return run_process(["kubectl", "describe", _safe(resource, "resource"), _safe(name, "name"), "--namespace", _safe(namespace, "namespace")], 30, max_output=100_000)
    def logs(self, pod: str, namespace: str = "default", container: str = "", tail: int = 200) -> dict[str, Any]:
        command = ["kubectl", "logs", _safe(pod, "pod"), "--namespace", _safe(namespace, "namespace"), "--tail", str(max(1, min(tail, 2000)))]
        if container: command += ["--container", _safe(container, "container")]
        return run_process(command, 30, max_output=100_000)
