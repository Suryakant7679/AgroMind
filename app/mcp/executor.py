from __future__ import annotations

import asyncio
import inspect
import json
import re
from typing import Any, Callable

from app.mcp.router import MCPRouter

_EXPLICIT_MCP = re.compile(r"\b(?:use|using|with|via)\s+(?:the\s+)?([a-z][a-z0-9_-]*)\s+mcp(?:\s+(?:server|tool))?\b", re.IGNORECASE)


def _registry(category: str) -> dict[str, Callable[..., Any]]:
    if category == "duckduckgo":
        from app.mcp.duckduckgo_tools import search_web
        return {"duckduckgo_search": search_web}
    if category == "python":
        from app.mcp.python_tools import python_package_info, run_restricted_python
        return {"run_python": run_restricted_python, "package_info": python_package_info}
    if category == "github":
        from app.mcp.github_tools import GitHubReader
        reader = GitHubReader()
        return {"github_repository": reader.repository, "github_contributors": reader.contributors, "github_issues": reader.issues, "github_pull_requests": reader.pull_requests}
    if category == "filesystem":
        from app.mcp.filesystem_tools import WorkspaceFilesystem
        reader = WorkspaceFilesystem()
        return {"list_files": reader.list_files, "read_file": reader.read_file, "search_text": reader.search_text, "write_file": reader.write_file}
    if category == "terminal":
        from app.mcp.terminal_tools import run_terminal
        return {"run_command": run_terminal}
    if category == "browser":
        from app.mcp.browser_tools import extract_links, fetch_url
        return {"browse_url": fetch_url, "page_links": extract_links}
    if category == "git":
        from app.mcp.git_tools import GitInspector
        reader = GitInspector()
        return {"git_status": reader.status, "git_diff": reader.diff, "git_log": reader.log, "git_show": reader.show, "git_branches": reader.branches}
    if category == "docker":
        from app.mcp.docker_tools import container_logs, inspect_container, list_containers, list_images
        return {"docker_containers": list_containers, "docker_inspect": inspect_container, "docker_logs": container_logs, "docker_images": list_images}
    if category == "kubernetes":
        from app.mcp.kubernetes_tools import KubernetesReader
        reader = KubernetesReader()
        return {"kubernetes_contexts": reader.contexts, "kubernetes_namespaces": reader.namespaces, "kubernetes_resources": reader.resources, "kubernetes_describe": reader.describe, "kubernetes_logs": reader.logs}
    if category == "postgresql":
        from app.mcp.postgresql_tools import PostgreSQLReader
        reader = PostgreSQLReader()
        return {"postgres_tables": reader.tables, "postgres_columns": reader.columns, "postgres_query": reader.query}
    if category == "sqlite":
        from app.mcp.sqlite_tools import SQLiteReader
        reader = SQLiteReader()
        return {"sqlite_tables": reader.tables, "sqlite_query": reader.query}
    if category == "redis":
        from app.mcp.redis_tools import RedisReader
        reader = RedisReader()
        return {"redis_keys": reader.keys, "redis_get": reader.get, "redis_stats": reader.stats}
    if category == "cloud":
        from app.mcp.cloud_tools import CloudReader
        reader = CloudReader()
        return {"cloud_providers": reader.providers, "cloud_inspect": reader.inspect}
    if category == "productivity":
        from app.mcp.productivity_tools import ProductivityReader
        reader = ProductivityReader()
        return {"slack_channels": reader.slack_channels, "slack_history": reader.slack_history, "notion_search": reader.notion_search, "notion_page": reader.notion_page}
    if category == "rest":
        from app.mcp.rest_tools import rest_request
        return {"request_api": rest_request}
    if category == "ocr":
        from app.mcp.ocr_tools import OCRReader
        reader = OCRReader()
        return {"extract_text": reader.extract}
    if category == "image":
        from app.mcp.image_tools import ImageProcessor
        reader = ImageProcessor()
        return {"image_info": reader.info, "transform_image": reader.transform}
    if category == "custom":
        from app.mcp.custom_tools import CustomMCPRegistry
        reader = CustomMCPRegistry()
        return {"custom_servers": reader.list_servers, "custom_tools": reader.list_tools, "custom_call": reader.call_tool}
    return {}


def _arguments(query: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    for index, char in enumerate(query):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(query[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return {}


def _tool_name(query: str, tools: dict[str, Callable[..., Any]]) -> str:
    lowered = query.lower().replace("-", "_")
    for name in tools:
        if name in lowered or name.replace("_", " ") in lowered:
            return name
    route = MCPRouter().classify(query)
    return route.suggested_tool if route.suggested_tool in tools else next(iter(tools), "")


def explicit_mcp_answer(query: str, *, allow_privileged: bool = True) -> tuple[str, str] | None:
    match = _EXPLICIT_MCP.search(query)
    if not match:
        return None
    category = match.group(1).lower().replace("-", "")
    aliases = {"file": "filesystem", "files": "filesystem", "postgres": "postgresql", "k8s": "kubernetes", "api": "rest"}
    category = aliases.get(category, category)
    catalog = MCPRouter.TOOL_CATALOG
    if category not in catalog:
        return (f"Unknown MCP server '{category}'. Available MCP categories: {', '.join(sorted(catalog))}.", "router")
    if not allow_privileged and category != "duckduckgo":
        return ("This MCP server requires an administrator account because it can access server resources.", category)
    lowered = query.lower().replace("-", "_")
    has_named_tool = any(name in lowered or name.replace("_", " ") in lowered for name in catalog[category])
    if category in {"python", "github"} and not has_named_tool:
        return None
    try:
        tools = _registry(category)
    except Exception as exc:
        return (f"{category.title()} MCP could not initialize: {type(exc).__name__}.", category)
    tool_name = _tool_name(query, tools)
    if not tool_name or tool_name not in tools:
        return (f"{category.title()} MCP tools: {', '.join(catalog[category])}.", category)
    tool = tools[tool_name]
    arguments = _arguments(query)
    signature = inspect.signature(tool)
    missing = [name for name, parameter in signature.parameters.items() if parameter.default is inspect.Parameter.empty and parameter.kind not in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD} and name not in arguments]
    if missing:
        example = {name: f"<{name}>" for name in missing}
        return (f"{category.title()} MCP selected {tool_name}, but required arguments are missing: {', '.join(missing)}. Retry with JSON arguments, for example: use {category} MCP {tool_name} with {json.dumps(example)}", category)
    unknown = sorted(set(arguments) - set(signature.parameters))
    if unknown:
        return (f"{category.title()} MCP {tool_name} does not accept: {', '.join(unknown)}.", category)
    try:
        result = tool(**arguments)
        if inspect.isawaitable(result):
            result = asyncio.run(result)
        rendered = json.dumps(result, ensure_ascii=False, indent=2, default=str)
        return (f"{category.title()} MCP result from {tool_name}:\n{rendered}", category)
    except Exception as exc:
        return (f"{category.title()} MCP {tool_name} failed with a real tool error: {type(exc).__name__}: {exc}. No LLM-generated fallback was used.", category)