from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Callable

from app.mcp.browser_tools import extract_links, fetch_url
from app.mcp.filesystem_tools import WorkspaceFilesystem
from app.mcp.git_tools import GitInspector
from app.mcp.image_tools import ImageProcessor
from app.mcp.ocr_tools import OCRReader
from app.mcp.postgresql_tools import PostgreSQLReader
from app.mcp.python_tools import run_restricted_python
from app.mcp.redis_tools import RedisReader
from app.mcp.sqlite_tools import SQLiteReader
from app.mcp.terminal_tools import run_terminal
from app.observability import OBSERVABILITY


def agent_result(agent: str, status: str, output: Any = None, message: str = "") -> dict[str, Any]:
    return {"agent": agent, "status": status, "message": message, "output": output}


class MemoryAgent:
    def __init__(self, store: Any | None = None) -> None:
        self.store = store

    def execute(self, objective: str, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        operation = str(payload.get("operation") or "recall").lower()
        if operation == "recall":
            long_term = self.store.get_long_term_memory() if self.store else context.get("long_term_memory", {})
            short_term: dict[str, Any] = dict(context.get("short_term_memory") or {})
            conversation_id = str(payload.get("conversation_id") or context.get("conversation_id") or "")
            if self.store and conversation_id:
                short_term = dict(self.store.get_conversation(conversation_id).get("short_term_memory") or {})
            return agent_result("memory", "completed", {"short_term": short_term, "long_term": long_term}, "Memory context recalled")
        if operation == "remember":
            if not self.store:
                return agent_result("memory", "needs_input", None, "A persistent memory store is required")
            scope = str(payload.get("scope") or "long_term")
            if scope == "short_term":
                conversation_id = str(payload.get("conversation_id") or context.get("conversation_id") or "")
                if not conversation_id:
                    return agent_result("memory", "needs_input", None, "conversation_id is required for short-term memory")
                output = self.store.update_short_term_memory(
                    conversation_id,
                    artifact_ids=payload.get("artifact_ids"), task=payload.get("task"),
                    variables=payload.get("variables"), tool_outputs=payload.get("tool_outputs"),
                )
            else:
                output = self.store.update_long_term_memory(
                    user_preferences=payload.get("user_preferences"), coding_style=payload.get("coding_style"),
                    projects=payload.get("projects"), commands=payload.get("commands"),
                    learned_behavior=payload.get("learned_behavior"),
                )
            return agent_result("memory", "completed", output, "Memory updated")
        raise ValueError("Memory operation must be recall or remember")


class RAGAgent:
    def __init__(self, retriever: Callable[[str, int, list[str] | None], list[dict[str, Any]]] | None = None) -> None:
        self.retriever = retriever

    def execute(self, objective: str, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        query = str(payload.get("query") or objective).strip()
        top_k = max(1, min(int(payload.get("top_k", 5)), 20))
        source_types = payload.get("source_types")
        if source_types is not None and (not isinstance(source_types, list) or not all(isinstance(item, str) for item in source_types)):
            raise ValueError("source_types must be a list of strings")
        if self.retriever:
            results = self.retriever(query, top_k, source_types)
        else:
            records = context.get("vector_records")
            if not isinstance(records, list):
                return agent_result("rag", "needs_input", None, "A retriever or vector_records context is required")
            terms = set(re.findall(r"[A-Za-z0-9_]+", query.lower()))
            ranked = []
            for record in records:
                if source_types and str(record.get("source_type")) not in source_types:
                    continue
                text = str(record.get("text") or "")
                tokens = set(re.findall(r"[A-Za-z0-9_]+", text.lower()))
                score = len(terms & tokens) / max(1, len(terms))
                ranked.append({**record, "scores": {**(record.get("scores") or {}), "agent": round(score, 6)}})
            results = sorted(ranked, key=lambda item: item["scores"]["agent"], reverse=True)[:top_k]
        public_results = [{key: value for key, value in item.items() if key != "embedding"} for item in results]
        citations = [
            {
                "id": item.get("id"), "source_type": item.get("source_type", "document"),
                "filename": item.get("filename", ""), "snippet": str(item.get("text") or "")[:500],
                "score": (item.get("scores") or {}).get("rerank", (item.get("scores") or {}).get("agent", 0)),
            }
            for item in public_results
        ]
        return agent_result("rag", "completed", {"query": query, "results": public_results, "citations": citations}, f"Retrieved {len(public_results)} relevant records")


class BrowserAgent:
    def __init__(self, fetcher: Callable[[str, int], dict[str, Any]] = fetch_url, link_extractor: Callable[[str, int], list[dict[str, str]]] = extract_links) -> None:
        self.fetcher, self.link_extractor = fetcher, link_extractor

    def execute(self, objective: str, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        match = re.search(r"https?://[^\s<>]+", objective)
        url = str(payload.get("url") or (match.group(0).rstrip(".,)") if match else ""))
        if not url:
            return agent_result("browser", "needs_input", None, "A public HTTP(S) URL is required")
        operation = str(payload.get("operation") or "fetch")
        if operation not in {"fetch", "links"}:
            raise ValueError("Browser operation must be fetch or links")
        limit = max(1, min(int(payload.get("limit", 100)), 500))
        output = self.link_extractor(url, limit) if operation == "links" else self.fetcher(url, max(100, min(int(payload.get("max_chars", 50_000)), 200_000)))
        return agent_result("browser", "completed", output, f"Browser {operation} completed")


class FilesystemAgent:
    def __init__(self, filesystem: WorkspaceFilesystem | None = None) -> None:
        self.filesystem = filesystem or WorkspaceFilesystem()

    def execute(self, objective: str, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        operation = str(payload.get("operation") or "").lower()
        if not operation:
            return agent_result("filesystem", "needs_input", None, "A filesystem operation is required")
        if operation == "list":
            output = self.filesystem.list_files(str(payload.get("path") or "."), bool(payload.get("recursive")), int(payload.get("limit", 200)))
        elif operation == "read":
            output = self.filesystem.read_file(str(payload.get("path") or ""), int(payload.get("max_chars", 100_000)))
        elif operation == "search":
            output = self.filesystem.search_text(str(payload.get("query") or ""), str(payload.get("path") or "."), int(payload.get("limit", 100)))
        elif operation == "write":
            output = self.filesystem.write_file(str(payload.get("path") or ""), str(payload.get("content") or ""), bool(payload.get("overwrite")))
        else:
            raise ValueError("Filesystem operation must be list, read, search, or write")
        return agent_result("filesystem", "completed", output, f"Filesystem {operation} completed")


class TerminalAgent:
    def __init__(self, runner: Callable[[str, list[str] | None, int], dict[str, Any]] = run_terminal) -> None:
        self.runner = runner

    def execute(self, objective: str, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        command = str(payload.get("command") or "")
        if not command:
            return agent_result("terminal", "needs_input", None, "An allowlisted command is required")
        args = payload.get("args") or []
        if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
            raise ValueError("Terminal args must be a list of strings")
        output = self.runner(command, args, int(payload.get("timeout", 15)))
        return agent_result("terminal", "completed" if output.get("ok") else "failed", output, "Terminal command completed")


class CodingAgent:
    def __init__(self, filesystem: WorkspaceFilesystem | None = None, git: GitInspector | None = None, terminal: TerminalAgent | None = None) -> None:
        self.filesystem = filesystem or WorkspaceFilesystem()
        self.git = git or GitInspector(self.filesystem.root)
        self.terminal = terminal or TerminalAgent()

    def execute(self, objective: str, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        operation = str(payload.get("operation") or "inspect").lower()
        output: dict[str, Any] = {"git_status": self.git.status()}
        if operation == "inspect":
            paths = payload.get("paths") or context.get("open_files") or []
            if not isinstance(paths, list): raise ValueError("paths must be a list")
            output["files"] = [self.filesystem.read_file(str(path), int(payload.get("max_chars", 40_000))) for path in paths[:12]]
        elif operation == "search":
            output["matches"] = self.filesystem.search_text(str(payload.get("query") or ""), str(payload.get("path") or "."), int(payload.get("limit", 100)))
        elif operation == "apply_changes":
            changes = payload.get("changes")
            if not isinstance(changes, dict) or not changes:
                return agent_result("coding", "needs_input", None, "A non-empty changes mapping is required")
            output["changes"] = [self.filesystem.write_file(str(path), str(content), overwrite=True) for path, content in changes.items()]
            output["git_diff"] = self.git.diff()
        elif operation == "verify":
            terminal_payload = payload.get("terminal")
            if not isinstance(terminal_payload, dict):
                return agent_result("coding", "needs_input", None, "A terminal verification request is required")
            output["verification"] = self.terminal.execute(objective, terminal_payload, context)
        else:
            raise ValueError("Coding operation must be inspect, search, apply_changes, or verify")
        status = "failed" if operation == "verify" and output["verification"].get("status") == "failed" else "completed"
        return agent_result("coding", status, output, f"Coding {operation} completed")


class VisionAgent:
    def __init__(self, images: ImageProcessor | None = None, ocr: OCRReader | None = None) -> None:
        self.images = images or ImageProcessor()
        self.ocr = ocr or OCRReader(self.images.files.root)

    def execute(self, objective: str, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        operation = str(payload.get("operation") or "info").lower()
        path = str(payload.get("path") or context.get("active_file") or "")
        if not path:
            return agent_result("vision", "needs_input", None, "An image or scanned-document path is required")
        if operation == "info":
            output = self.images.info(path)
        elif operation == "ocr":
            output = self.ocr.extract(path, str(payload.get("language") or "eng"), int(payload.get("timeout", 30)))
        elif operation == "transform":
            output_path = str(payload.get("output_path") or "")
            if not output_path:
                return agent_result("vision", "needs_input", None, "output_path is required for image transforms")
            output = self.images.transform(
                path, output_path, payload.get("width"), payload.get("height"), payload.get("crop"),
                payload.get("image_format"), int(payload.get("quality", 85)), bool(payload.get("overwrite")),
            )
        else:
            raise ValueError("Vision operation must be info, ocr, or transform")
        status = "failed" if isinstance(output, dict) and output.get("ok") is False else "completed"
        return agent_result("vision", status, output, f"Vision {operation} completed")


class DatabaseAgent:
    def __init__(self, providers: dict[str, Callable[[], Any]] | None = None) -> None:
        self.providers = providers or {
            "postgresql": PostgreSQLReader,
            "sqlite": SQLiteReader,
            "redis": RedisReader,
        }

    def execute(self, objective: str, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        provider = str(payload.get("provider") or "").lower()
        if not provider:
            provider = "postgresql" if re.search(r"\b(postgres|postgresql)\b", objective, re.I) else "sqlite" if re.search(r"\bsqlite\b", objective, re.I) else "redis" if re.search(r"\bredis\b", objective, re.I) else ""
        if provider not in self.providers:
            return agent_result("database", "needs_input", None, "provider must be postgresql, sqlite, or redis")
        reader = self.providers[provider]()
        operation = str(payload.get("operation") or "tables").lower()
        if provider in {"postgresql", "sqlite"}:
            if operation == "tables":
                output = reader.tables()
            elif operation == "columns" and provider == "postgresql":
                output = reader.columns(str(payload.get("table") or ""), str(payload.get("schema") or "public"))
            elif operation == "query":
                output = reader.query(str(payload.get("sql") or ""), payload.get("parameters"), int(payload.get("limit", 200)))
            else:
                raise ValueError(f"Unsupported {provider} operation: {operation}")
        else:
            if operation == "keys":
                output = reader.keys(str(payload.get("pattern") or "*"), int(payload.get("limit", 200)))
            elif operation == "get":
                output = reader.get(str(payload.get("key") or ""), int(payload.get("max_chars", 50_000)))
            elif operation == "stats":
                output = reader.stats()
            else:
                raise ValueError(f"Unsupported redis operation: {operation}")
        return agent_result("database", "completed", {"provider": provider, "operation": operation, "result": output}, f"Read-only {provider} {operation} completed")


class ToolAgent:
    def __init__(self, tools: dict[str, Callable[..., Any]] | None = None, filesystem: WorkspaceFilesystem | None = None) -> None:
        files = filesystem or WorkspaceFilesystem()
        self.tools = tools or {
            "list_files": files.list_files,
            "read_file": files.read_file,
            "search_text": files.search_text,
            "write_file": files.write_file,
            "run_python": run_restricted_python,
            "run_command": run_terminal,
            "browse_url": fetch_url,
            "page_links": extract_links,
        }

    def execute(self, objective: str, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        tool = str(payload.get("tool") or "")
        arguments = payload.get("arguments") or {}
        if not tool:
            return agent_result("tool", "needs_input", {"available_tools": sorted(self.tools)}, "An explicit tool name is required")
        if tool not in self.tools:
            raise ValueError(f"Tool is not registered: {tool}")
        if not isinstance(arguments, dict) or len(arguments) > 30:
            raise ValueError("Tool arguments must be an object with at most 30 fields")
        output = self.tools[tool](**arguments)
        status = "failed" if isinstance(output, dict) and output.get("ok") is False else "completed"
        return agent_result("tool", status, {"tool": tool, "result": output}, f"Tool {tool} completed")


class ReflectionAgent:
    def execute(self, objective: str, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        output = payload.get("agent_output") or context.get("agent_output")
        plan = payload.get("plan") or context.get("plan") or {}
        if not isinstance(output, dict):
            return agent_result("reflection", "needs_input", None, "agent_output is required for reflection")
        issues: list[str] = []
        if output.get("status") != "completed":
            issues.append(f"Agent status is {output.get('status', 'unknown')}")
        if output.get("output") is None or output.get("output") == "" or output.get("output") == [] or output.get("output") == {}:
            issues.append("Agent returned no substantive output")
        nested = output.get("output")
        if isinstance(nested, dict):
            for key, value in nested.items():
                if isinstance(value, dict) and value.get("ok") is False:
                    issues.append(f"Nested operation failed: {key}")
        criteria = [
            {"subtask_id": item.get("id"), "criterion": item.get("success_criteria", ""), "evidence_status": "requires downstream validation"}
            for item in (plan.get("subtasks") or []) if item.get("success_criteria")
        ]
        verdict = "failed" if output.get("status") == "failed" else "needs_review" if issues else "passed"
        review = {"verdict": verdict, "issues": issues, "criteria": criteria, "reviewed_agent": output.get("agent"), "objective": objective}
        return agent_result("reflection", "completed", review, f"Reflection completed with verdict: {verdict}")


class ReviewerAgent:
    """Apply an independent deterministic quality gate after reflection."""

    def execute(self, objective: str, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        output = payload.get("agent_output") or context.get("agent_output")
        reflection = payload.get("reflection") or context.get("reflection")
        plan = payload.get("plan") or context.get("plan") or {}
        if not isinstance(output, dict) or not isinstance(reflection, dict):
            return agent_result("reviewer", "needs_input", None, "agent_output and reflection are required for review")
        reflection_output = reflection.get("output") if isinstance(reflection.get("output"), dict) else {}
        planned_criteria = [item.get("success_criteria") for item in plan.get("subtasks", []) if item.get("success_criteria")]
        reflected_criteria = reflection_output.get("criteria") if isinstance(reflection_output.get("criteria"), list) else []
        checks = [
            {"name": "agent_completed", "passed": output.get("status") == "completed"},
            {"name": "reflection_completed", "passed": reflection.get("status") == "completed"},
            {"name": "reflection_passed", "passed": reflection_output.get("verdict") == "passed"},
            {"name": "output_present", "passed": output.get("output") not in (None, "", [], {})},
            {"name": "success_criteria_accounted_for", "passed": len(reflected_criteria) == len(planned_criteria)},
        ]
        failed_checks = [item["name"] for item in checks if not item["passed"]]
        if output.get("status") == "failed" or reflection_output.get("verdict") == "failed":
            verdict = "rejected"
        elif failed_checks:
            verdict = "changes_required"
        else:
            verdict = "approved"
        review = {
            "verdict": verdict,
            "approved": verdict == "approved",
            "checks": checks,
            "failed_checks": failed_checks,
            "reviewed_agent": output.get("agent"),
            "objective": objective,
            "limitations": ["Success criteria are structurally accounted for; semantic verification depends on agent evidence."],
        }
        return agent_result("reviewer", "completed", review, f"Reviewer verdict: {verdict}")


class SpecialistAgentRegistry:
    def __init__(self, **agents: Any) -> None:
        defaults = {
            "memory": MemoryAgent(), "rag": RAGAgent(), "browser": BrowserAgent(),
            "coding": CodingAgent(), "terminal": TerminalAgent(), "filesystem": FilesystemAgent(),
            "vision": VisionAgent(), "database": DatabaseAgent(), "tool": ToolAgent(), "reflection": ReflectionAgent(), "reviewer": ReviewerAgent(),
        }
        defaults.update({key: value for key, value in agents.items() if value is not None})
        self.agents = defaults

    def execute(self, name: str, objective: str, payload: dict[str, Any] | None, context: dict[str, Any] | None) -> dict[str, Any]:
        agent = self.agents.get(name)
        if agent is None:
            raise KeyError(f"Unknown specialist agent: {name}")
        started = time.perf_counter()
        try:
            result = agent.execute(objective, dict(payload or {}), dict(context or {}))
        except (OSError, RuntimeError, ValueError, PermissionError, FileNotFoundError, KeyError) as exc:
            result = agent_result(name, "failed", None, str(exc))
        success = result.get("status") != "failed"
        OBSERVABILITY.record("tool", name, success=success, duration_ms=(time.perf_counter() - started) * 1000, error="" if success else str(result.get("summary") or "Agent execution failed"), properties={"objective_length": len(objective)})
        return result
