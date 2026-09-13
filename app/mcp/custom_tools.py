from __future__ import annotations

import os
import re
from datetime import timedelta
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.mcp.process_tools import workspace_root


class CustomMCPRegistry:
    """Load and invoke explicitly opted-in stdio MCP servers from a workspace config."""

    def __init__(self, config_path: str | Path | None = None, enabled: bool | None = None) -> None:
        self.root = workspace_root()
        configured = config_path or os.getenv("AIOS_MCP_CUSTOM_CONFIG", "mcp-servers.json")
        self.config_path = (self.root / configured).resolve() if not Path(configured).is_absolute() else Path(configured).resolve()
        if self.config_path != self.root and self.root not in self.config_path.parents:
            raise ValueError("Custom MCP config must be inside the workspace")
        self.enabled = os.getenv("AIOS_MCP_CUSTOM_ENABLED", "false").lower() == "true" if enabled is None else enabled

    def load(self) -> dict[str, dict[str, Any]]:
        if not self.config_path.exists():
            return {}
        import json
        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        servers = payload.get("mcpServers")
        if not isinstance(servers, dict):
            raise ValueError("Custom MCP config must contain an mcpServers object")
        validated: dict[str, dict[str, Any]] = {}
        for name, entry in servers.items():
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", str(name)) or not isinstance(entry, dict):
                raise ValueError("Invalid custom MCP server entry")
            command, args, env = entry.get("command"), entry.get("args", []), entry.get("env", {})
            if not isinstance(command, str) or not command.strip() or not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
                raise ValueError(f"Invalid command or args for MCP server {name}")
            if not isinstance(env, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in env.items()):
                raise ValueError(f"Invalid environment for MCP server {name}")
            cwd = Path(entry.get("cwd", self.root)).resolve()
            if cwd != self.root and self.root not in cwd.parents:
                raise ValueError(f"MCP server {name} cwd escapes the workspace")
            validated[name] = {"command": command, "args": args, "env": env, "cwd": str(cwd)}
        return validated

    def list_servers(self) -> list[dict[str, Any]]:
        return [{"name": name, "command": entry["command"], "args": entry["args"], "cwd": entry["cwd"]} for name, entry in self.load().items()]

    def _parameters(self, server: str) -> StdioServerParameters:
        if not self.enabled:
            raise PermissionError("Custom MCP execution is disabled; set AIOS_MCP_CUSTOM_ENABLED=true to enable")
        entry = self.load().get(server)
        if entry is None:
            raise KeyError(f"Unknown custom MCP server: {server}")
        allowed = {item.strip().lower() for item in os.getenv("AIOS_MCP_CUSTOM_COMMANDS", "python,node,npx,uvx").split(",") if item.strip()}
        executable = Path(entry["command"]).name.lower()
        if executable.endswith(".exe") or executable.endswith(".cmd"):
            executable = executable.rsplit(".", 1)[0]
        if executable not in allowed:
            raise PermissionError(f"Custom MCP executable is not allowlisted: {executable}")
        return StdioServerParameters(command=entry["command"], args=entry["args"], env={**os.environ, **entry["env"]}, cwd=entry["cwd"])

    async def list_tools(self, server: str) -> dict[str, Any]:
        async with stdio_client(self._parameters(server)) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return result.model_dump(mode="json", exclude_none=True)

    async def call_tool(self, server: str, tool: str, arguments: dict[str, Any] | None = None, timeout: int = 30) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,200}", tool):
            raise ValueError("Invalid tool name")
        async with stdio_client(self._parameters(server)) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool, arguments or {}, read_timeout_seconds=timedelta(seconds=max(1, min(timeout, 60))))
                return result.model_dump(mode="json", exclude_none=True)
