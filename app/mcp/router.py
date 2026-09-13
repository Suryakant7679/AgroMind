from __future__ import annotations

import re
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ToolRoute:
    category: str
    server: str
    suggested_tool: str
    confidence: float
    reason: str


class MCPRouter:
    TOOL_CATALOG = {
        "duckduckgo": ["duckduckgo_search"],
        "filesystem": ["list_files", "read_file", "search_text", "write_file"],
        "python": ["run_python", "package_info"],
        "terminal": ["run_command"],
        "browser": ["browse_url", "page_links"],
        "git": ["git_status", "git_diff", "git_log", "git_show", "git_branches"],
        "github": ["github_repository", "github_contributors", "github_issues", "github_pull_requests"],
        "docker": ["docker_containers", "docker_inspect", "docker_logs", "docker_images"],
        "kubernetes": ["kubernetes_contexts", "kubernetes_namespaces", "kubernetes_resources", "kubernetes_describe", "kubernetes_logs"],
        "postgresql": ["postgres_tables", "postgres_columns", "postgres_query"],
        "sqlite": ["sqlite_tables", "sqlite_query"],
        "redis": ["redis_keys", "redis_get", "redis_stats"],
        "cloud": ["cloud_providers", "cloud_inspect"],
        "productivity": ["slack_channels", "slack_history", "notion_search", "notion_page"],
        "rest": ["request_api"],
        "ocr": ["extract_text"],
        "image": ["image_info", "transform_image"],
        "custom": ["custom_servers", "custom_tools", "custom_call"],
    }

    def classify(self, request: str) -> ToolRoute:
        text = request.strip().lower()
        if re.search(r"\b(web search|search (?:the )?web|research|sources?|citations?|references?|papers?|literature|latest)\b", text):
            return ToolRoute("duckduckgo", "aios-duckduckgo", "duckduckgo_search", 0.94, "Request requires current web sources and URLs")
        if re.search(r"\b(aws|amazon web services|azure|google cloud|gcp|cloud resources?|s3 buckets?)\b", text):
            return ToolRoute("cloud", "aios-cloud", "cloud_inspect", 0.95, "Request targets a cloud provider")
        if re.search(r"\b(slack|notion|productivity|channel history)\b", text):
            tool = "slack_history" if "history" in text else "notion_search" if "notion" in text else "slack_channels"
            return ToolRoute("productivity", "aios-productivity", tool, 0.94, "Request targets communication or productivity data")
        if re.search(r"\b(ocr|optical character recognition|extract text from (an? )?(image|scan)|scanned (image|pdf))\b", text):
            return ToolRoute("ocr", "aios-ocr", "extract_text", 0.95, "Request requires optical character recognition")
        if re.search(r"\b(resize|crop|convert|inspect)\b.*\b(image|photo|png|jpe?g|webp)\b", text):
            tool = "image_info" if "inspect" in text else "transform_image"
            return ToolRoute("image", "aios-image", tool, 0.93, "Request requires image processing")
        if re.search(r"\b(rest api|api endpoint|http (get|post|put|patch|delete)|call (an? )?api)\b", text):
            return ToolRoute("rest", "aios-rest", "request_api", 0.94, "Request targets a REST API")
        if re.search(r"\b(custom mcp|external mcp|third[- ]party mcp)\b", text):
            return ToolRoute("custom", "aios-custom", "custom_servers", 0.93, "Request targets a configured custom MCP server")
        if re.search(r"\b(kubernetes|kubectl|k8s|pod|namespace)\b", text):
            return ToolRoute("kubernetes", "aios-kubernetes", "kubernetes_logs" if "log" in text else "kubernetes_resources", 0.95, "Request targets Kubernetes")
        if re.search(r"\b(postgres|postgresql)\b", text):
            return ToolRoute("postgresql", "aios-postgresql", "postgres_query", 0.95, "Request targets PostgreSQL")
        if re.search(r"\bsqlite\b", text):
            return ToolRoute("sqlite", "aios-sqlite", "sqlite_query", 0.95, "Request targets SQLite")
        if re.search(r"\bredis\b", text):
            return ToolRoute("redis", "aios-redis", "redis_keys", 0.95, "Request targets Redis")
        if re.search(r"\b(github|pull request|github issue)\b", text):
            tool = "github_contributors" if "contributor" in text else "github_pull_requests" if "pull request" in text else "github_issues" if "issue" in text else "github_repository"
            return ToolRoute("github", "aios-github", tool, 0.94, "Request targets GitHub")
        if re.search(r"\b(docker|container|docker image)\b", text):
            tool = "docker_logs" if "log" in text else "docker_images" if "image" in text else "docker_containers"
            return ToolRoute("docker", "aios-docker", tool, 0.93, "Request targets Docker")
        if re.search(r"\b(git status|git diff|git log|commit history|branches)\b", text):
            tool = "git_diff" if "diff" in text else "git_log" if "log" in text or "history" in text else "git_branches" if "branch" in text else "git_status"
            return ToolRoute("git", "aios-git", tool, 0.93, "Request targets local Git")
        if re.search(r"https?://|\b(browse|web page|website|fetch url)\b", text):
            return ToolRoute("browser", "aios-browser", "browse_url", 0.9, "Request requires a public web resource")
        if re.search(r"\b(terminal|run command|execute command|rg |npm |node )\b", text):
            return ToolRoute("terminal", "aios-terminal", "run_command", 0.88, "Request requires an allowlisted terminal command")
        filesystem_patterns = {
            "write_file": r"\b(write|create|save|edit|update)\b.*\b(file|folder|directory|code)\b",
            "search_text": r"\b(search|find|grep|locate)\b.*\b(file|text|code|project)\b",
            "read_file": r"\b(read|open|show|inspect)\b.*\b(file|code|source|project)\b",
            "list_files": r"\b(list|tree|structure)\b.*\b(files?|folders?|directory|project)\b",
        }
        for tool, pattern in filesystem_patterns.items():
            if re.search(pattern, text):
                return ToolRoute("filesystem", "aios-filesystem", tool, 0.9, f"Matched filesystem operation: {tool}")
        if re.search(r"\b(python|calculate|compute|statistics|equation|simulate|data analysis)\b", text):
            tool = "package_info" if re.search(r"\b(package|library|framework|details? of|information (?:about|on))\b", text) else "run_python"
            return ToolRoute("python", "aios-python", tool, 0.88, "Request requires Python tooling")
        return ToolRoute("general", "", "", 0.35, "No filesystem or Python tool requirement detected")

    def classify_dict(self, request: str) -> dict:
        return asdict(self.classify(request))
