from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


class ConversationStore:
    def __init__(self, path: str = "data/conversations.json") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def list_conversations(self) -> list[dict[str, Any]]:
        return self._load()["conversations"]

    def list_conversations_for_session(self, session_id: str) -> list[dict[str, Any]]:
        return [
            conversation
            for conversation in self._load()["conversations"]
            if conversation.get("session_id") == session_id
        ]

    def list_conversations_for_user(self, user_id: str) -> list[dict[str, Any]]:
        return [item for item in self._load()["conversations"] if item.get("user_id") == user_id]

    def get_long_term_memory(self, user_id: str | None = None) -> dict[str, Any]:
        payload = self._load()
        if user_id:
            return normalize_long_term_memory(payload.get("user_long_term_memories", {}).get(user_id))
        return normalize_long_term_memory(payload.get("long_term_memory"))

    def update_long_term_memory(
        self,
        user_preferences: dict[str, Any] | None = None,
        coding_style: list[str] | None = None,
        projects: list[dict[str, Any] | str] | None = None,
        commands: list[str] | None = None,
        learned_behavior: list[str] | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        payload = self._load()
        source = payload.get("user_long_term_memories", {}).get(user_id) if user_id else payload.get("long_term_memory")
        memory = merge_long_term_memory(
            source, user_preferences, coding_style,
            projects, commands, learned_behavior,
        )
        if user_id:
            payload.setdefault("user_long_term_memories", {})[user_id] = memory
        else:
            payload["long_term_memory"] = memory
        self._save(payload)
        return memory

    def get_or_create_session(self, session_id: str | None = None, user_id: str | None = None) -> dict[str, Any]:
        payload = self._load()
        if session_id:
            for session in payload["sessions"]:
                if session["id"] == session_id:
                    if user_id and session.get("user_id") not in {None, user_id}:
                        raise PermissionError("Session belongs to another user")
                    if user_id and not session.get("user_id"):
                        session["user_id"] = user_id
                    session["updated_at"] = utc_now()
                    self._save(payload)
                    return session

        session = {
            "id": str(uuid4()),
            "user_id": user_id,
            "active_project": "",
            "current_workspace": {"name": "", "focus": ""},
            "running_task": "",
            "active_file": "",
            "open_files": [],
            "active_tool": "",
            "terminal_output": "",
            "browser_results": "",
            "mcp_outputs": "",
            "developer_instructions": "",
            "user_preferences": default_user_preferences(),
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        payload["sessions"].insert(0, session)
        self._save(payload)
        return session

    def update_session_context(
        self,
        session_id: str,
        active_project: str | None = None,
        current_workspace: dict[str, Any] | None = None,
        running_task: str | None = None,
        active_file: str | None = None,
        open_files: list[str] | None = None,
        active_tool: str | None = None,
        terminal_output: str | None = None,
        browser_results: str | None = None,
        mcp_outputs: str | None = None,
        developer_instructions: str | None = None,
        user_preferences: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = self._load()
        session = self._find_session(payload, session_id)
        if active_project is not None:
            session["active_project"] = active_project
        if current_workspace is not None:
            session["current_workspace"] = {
                "name": str(current_workspace.get("name", "")).strip(),
                "focus": str(current_workspace.get("focus", "")).strip(),
            }
        if running_task is not None:
            session["running_task"] = running_task
        if active_file is not None:
            session["active_file"] = active_file
        if open_files is not None:
            session["open_files"] = [
                str(item).strip()
                for item in open_files
                if str(item).strip()
            ][:12]
        if active_tool is not None:
            session["active_tool"] = active_tool
        if terminal_output is not None:
            session["terminal_output"] = terminal_output[-8000:]
        if browser_results is not None:
            session["browser_results"] = browser_results[-8000:]
        if mcp_outputs is not None:
            session["mcp_outputs"] = mcp_outputs[-8000:]
        if developer_instructions is not None:
            session["developer_instructions"] = developer_instructions[-8000:]
        if user_preferences is not None:
            session["user_preferences"] = normalized_user_preferences(
                {**session.get("user_preferences", {}), **user_preferences}
            )
        project_name = str(session.get("active_project") or session.get("current_workspace", {}).get("name") or "").strip()
        project_focus = str(session.get("current_workspace", {}).get("focus") or "").strip()
        learned_projects = [{"name": project_name, "focus": project_focus}] if project_name else None
        style_notes = [line.strip() for line in str(developer_instructions or "").splitlines() if line.strip()]
        user_id = str(session.get("user_id") or "") or None
        source_memory = payload.get("user_long_term_memories", {}).get(user_id) if user_id else payload.get("long_term_memory")
        updated_memory = merge_long_term_memory(
            source_memory,
            user_preferences=user_preferences,
            coding_style=style_notes or None,
            projects=learned_projects,
            commands=extract_commands(terminal_output or ""),
        )
        if user_id:
            payload.setdefault("user_long_term_memories", {})[user_id] = updated_memory
        else:
            payload["long_term_memory"] = updated_memory
        session["updated_at"] = utc_now()
        self._save(payload)
        return session

    def create_conversation(
        self, title: str = "New chat", session_id: str | None = None, user_id: str | None = None
    ) -> dict[str, Any]:
        payload = self._load()
        conversation = {
            "id": str(uuid4()),
            "user_id": user_id,
            "session_id": session_id,
            "active_thread_id": "main",
            "threads": [
                {
                    "id": "main",
                    "title": "Main",
                    "created_at": utc_now(),
                    "updated_at": utc_now(),
                }
            ],
            "title": title,
            "summary": "",
            "compressed_message_count": 0,
            "recovery_state": {},
            "short_term_memory": default_short_term_memory(),
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "messages": [],
        }
        payload["conversations"].insert(0, conversation)
        self._save(payload)
        return conversation

    def create_thread(self, conversation_id: str, title: str = "New thread") -> dict[str, Any]:
        payload = self._load()
        conversation = self._find(payload, conversation_id)
        thread = {
            "id": str(uuid4()),
            "title": title.strip() or "New thread",
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
        conversation["threads"].insert(0, thread)
        conversation["active_thread_id"] = thread["id"]
        conversation["updated_at"] = utc_now()
        self._save(payload)
        return thread

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        thread_id: str | None = None,
        parent_message_id: str | None = None,
    ) -> dict[str, Any]:
        payload = self._load()
        conversation = self._find(payload, conversation_id)
        thread_id = thread_id or conversation.get("active_thread_id") or "main"
        self._ensure_thread(conversation, thread_id)
        message = {
            "id": str(uuid4()),
            "thread_id": thread_id,
            "parent_message_id": parent_message_id,
            "role": role,
            "content": content,
            "created_at": utc_now(),
        }
        conversation["messages"].append(message)
        conversation["active_thread_id"] = thread_id
        conversation["updated_at"] = utc_now()
        self._touch_thread(conversation, thread_id)
        if conversation["title"] == "New chat" and role == "user":
            conversation["title"] = content[:48] or "New chat"
        self._refresh_summary_and_compression(conversation)
        self._save(payload)
        return message

    def update_short_term_memory(
        self,
        conversation_id: str,
        artifact_ids: list[str] | None = None,
        task: str | None = None,
        variables: dict[str, Any] | None = None,
        tool_outputs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = self._load()
        conversation = self._find(payload, conversation_id)
        memory = normalize_short_term_memory(conversation.get("short_term_memory"))
        if artifact_ids:
            incoming = [str(item) for item in artifact_ids if str(item)]
            memory["artifact_ids"] = list(dict.fromkeys([*memory["artifact_ids"], *incoming]))[-12:]
        if task is not None:
            memory["task"] = str(task).strip()[:2000]
        if variables:
            additions = {str(key)[:120]: value for key, value in variables.items()}
            memory["variables"] = dict(list({**memory["variables"], **additions}.items())[-40:])
        if tool_outputs:
            additions = {
                str(key)[:120]: str(value)[-8000:]
                for key, value in tool_outputs.items()
                if str(value).strip()
            }
            memory["tool_outputs"] = dict(list({**memory["tool_outputs"], **additions}.items())[-12:])
        memory["recent_messages"] = [
            {"role": item["role"], "content": str(item.get("content", ""))[-4000:]}
            for item in conversation.get("messages", [])
            if item.get("role") in {"user", "assistant"}
        ][-12:]
        memory["updated_at"] = utc_now()
        conversation["short_term_memory"] = memory
        conversation["updated_at"] = utc_now()
        self._save(payload)
        return memory

    def get_conversation(self, conversation_id: str) -> dict[str, Any]:
        payload = self._load()
        return self._find(payload, conversation_id)

    def rename_conversation(self, conversation_id: str, title: str) -> dict[str, Any]:
        normalized = str(title).strip()
        if not normalized:
            raise ValueError("Conversation title is required")
        if len(normalized) > 120:
            raise ValueError("Conversation title must be 120 characters or fewer")
        payload = self._load()
        conversation = self._find(payload, conversation_id)
        conversation["title"] = normalized
        conversation["updated_at"] = utc_now()
        self._save(payload)
        return conversation

    def delete_conversation(self, conversation_id: str) -> dict[str, Any]:
        payload = self._load()
        conversation = self._find(payload, conversation_id)
        payload["conversations"] = [
            item for item in payload["conversations"] if item["id"] != conversation_id
        ]
        self._save(payload)
        return conversation

    def set_recovery_state(self, conversation_id: str, recovery_state: dict[str, Any]) -> dict[str, Any]:
        payload = self._load()
        conversation = self._find(payload, conversation_id)
        conversation["recovery_state"] = recovery_state
        conversation["updated_at"] = utc_now()
        self._save(payload)
        return conversation

    def compress_short_term_memory(
        self,
        conversation_id: str,
        recent_limit: int = 6,
        text_limit: int = 2000,
    ) -> dict[str, Any]:
        """Bound ephemeral conversation memory without deleting chat history."""
        payload = self._load()
        conversation = self._find(payload, conversation_id)
        memory = normalize_short_term_memory(conversation.get("short_term_memory"))
        recent_limit = max(1, min(int(recent_limit), 12))
        text_limit = max(200, min(int(text_limit), 8000))
        memory["recent_messages"] = [
            {"role": str(item.get("role", "")), "content": str(item.get("content", ""))[-text_limit:]}
            for item in memory["recent_messages"][-recent_limit:]
            if str(item.get("content", "")).strip()
        ]
        memory["variables"] = dict(list(memory["variables"].items())[-20:])
        memory["tool_outputs"] = {
            str(key)[:120]: str(value)[-text_limit:]
            for key, value in list(memory["tool_outputs"].items())[-6:]
            if str(value).strip()
        }
        memory["compressed_at"] = utc_now()
        memory["updated_at"] = memory["compressed_at"]
        conversation["short_term_memory"] = memory
        conversation["updated_at"] = utc_now()
        self._save(payload)
        return memory

    def refresh_conversation_summary(
        self,
        conversation_id: str,
        keep_recent: int = 6,
        summary_limit: int = 1600,
    ) -> dict[str, Any]:
        """Regenerate the deterministic summary used for older chat context."""
        payload = self._load()
        conversation = self._find(payload, conversation_id)
        messages = [
            item for item in conversation.get("messages", [])
            if item.get("role") in {"user", "assistant"} and str(item.get("content", "")).strip()
        ]
        keep_recent = max(1, int(keep_recent))
        older = messages[:-keep_recent] if len(messages) > keep_recent else []
        summary = " | ".join(
            f"{item['role']}: {str(item.get('content', '')).strip()[:120]}"
            for item in older[-8:]
        )[:max(200, int(summary_limit))]
        conversation["summary"] = summary
        conversation["compressed_message_count"] = len(older)
        conversation["updated_at"] = utc_now()
        self._save(payload)
        return {"conversation_id": conversation_id, "summary": summary, "compressed_message_count": len(older)}

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"sessions": [], "conversations": [], "long_term_memory": default_long_term_memory(), "user_long_term_memories": {}}
        with self.path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        payload.setdefault("sessions", [])
        payload.setdefault("conversations", [])
        payload.setdefault("user_long_term_memories", {})
        payload["long_term_memory"] = normalize_long_term_memory(payload.get("long_term_memory"))
        for conversation in payload["conversations"]:
            conversation.setdefault("user_id", None)
            conversation.setdefault("session_id", None)
            conversation.setdefault("active_thread_id", "main")
            conversation.setdefault("threads", [{"id": "main", "title": "Main", "created_at": conversation.get("created_at", utc_now()), "updated_at": conversation.get("updated_at", utc_now())}])
            conversation.setdefault("summary", "")
            conversation.setdefault("compressed_message_count", 0)
            conversation.setdefault("recovery_state", {})
            conversation["short_term_memory"] = normalize_short_term_memory(conversation.get("short_term_memory"))
            for message in conversation.get("messages", []):
                message.setdefault("thread_id", conversation["active_thread_id"] or "main")
                message.setdefault("parent_message_id", None)
        for session in payload["sessions"]:
            session.setdefault("user_id", None)
            session.setdefault("active_project", "")
            session.setdefault("current_workspace", {"name": "", "focus": ""})
            session.setdefault("running_task", "")
            session.setdefault("active_file", "")
            session.setdefault("open_files", [])
            session.setdefault("active_tool", "")
            session.setdefault("terminal_output", "")
            session.setdefault("browser_results", "")
            session.setdefault("mcp_outputs", "")
            session.setdefault("developer_instructions", "")
            session["user_preferences"] = normalized_user_preferences(
                session.get("user_preferences", {})
            )
        return payload

    def _save(self, payload: dict[str, Any]) -> None:
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)

    @staticmethod
    def _find(payload: dict[str, Any], conversation_id: str) -> dict[str, Any]:
        for conversation in payload["conversations"]:
            conversation.setdefault("user_id", None)
            if conversation["id"] == conversation_id:
                return conversation
        raise KeyError(f"Conversation not found: {conversation_id}")

    @staticmethod
    def _find_session(payload: dict[str, Any], session_id: str) -> dict[str, Any]:
        for session in payload["sessions"]:
            if session["id"] == session_id:
                return session
        raise KeyError(f"Session not found: {session_id}")

    @staticmethod
    def _ensure_thread(conversation: dict[str, Any], thread_id: str) -> None:
        if any(thread["id"] == thread_id for thread in conversation["threads"]):
            return
        conversation["threads"].append(
            {
                "id": thread_id,
                "title": "Main" if thread_id == "main" else "Recovered thread",
                "created_at": utc_now(),
                "updated_at": utc_now(),
            }
        )

    @staticmethod
    def _touch_thread(conversation: dict[str, Any], thread_id: str) -> None:
        for thread in conversation["threads"]:
            if thread["id"] == thread_id:
                thread["updated_at"] = utc_now()
                return

    @staticmethod
    def _refresh_summary_and_compression(conversation: dict[str, Any]) -> None:
        messages = [
            item
            for item in conversation.get("messages", [])
            if item.get("role") in {"user", "assistant"}
        ]
        if len(messages) < 8:
            return
        older = messages[:-6]
        conversation["compressed_message_count"] = len(older)
        summary_items = older[-8:]
        summary = " | ".join(
            f"{item['role']}: {str(item.get('content', '')).strip()[:120]}"
            for item in summary_items
            if str(item.get("content", "")).strip()
        )
        conversation["summary"] = summary[:1600]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_short_term_memory() -> dict[str, Any]:
    return {
        "recent_messages": [], "artifact_ids": [], "task": "", "variables": {},
        "tool_outputs": {}, "updated_at": "", "compressed_at": "",
    }


def normalize_short_term_memory(memory: Any) -> dict[str, Any]:
    source = memory if isinstance(memory, dict) else {}
    normalized = default_short_term_memory()
    normalized["recent_messages"] = source.get("recent_messages", [])[-12:]
    normalized["artifact_ids"] = [str(item) for item in source.get("artifact_ids", []) if str(item)][-12:]
    normalized["task"] = str(source.get("task", ""))[:2000]
    normalized["variables"] = source.get("variables", {}) if isinstance(source.get("variables"), dict) else {}
    normalized["tool_outputs"] = source.get("tool_outputs", {}) if isinstance(source.get("tool_outputs"), dict) else {}
    normalized["updated_at"] = str(source.get("updated_at", ""))
    normalized["compressed_at"] = str(source.get("compressed_at", ""))
    return normalized


def default_long_term_memory() -> dict[str, Any]:
    return {
        "user_preferences": default_user_preferences(),
        "coding_style": [], "projects": [], "commands": [], "learned_behavior": [],
        "updated_at": "",
    }


def normalize_long_term_memory(memory: Any) -> dict[str, Any]:
    source = memory if isinstance(memory, dict) else {}
    normalized = default_long_term_memory()
    normalized["user_preferences"] = normalized_user_preferences(source.get("user_preferences", {}))
    normalized["coding_style"] = unique_text_items(source.get("coding_style", []), 30)
    normalized["commands"] = unique_text_items(source.get("commands", []), 50)
    normalized["learned_behavior"] = unique_text_items(source.get("learned_behavior", []), 50)
    normalized["projects"] = normalize_projects(source.get("projects", []))
    normalized["updated_at"] = str(source.get("updated_at", ""))
    return normalized


def merge_long_term_memory(
    current: Any,
    user_preferences: dict[str, Any] | None = None,
    coding_style: list[str] | None = None,
    projects: list[dict[str, Any] | str] | None = None,
    commands: list[str] | None = None,
    learned_behavior: list[str] | None = None,
) -> dict[str, Any]:
    memory = normalize_long_term_memory(current)
    if user_preferences:
        memory["user_preferences"] = normalized_user_preferences({**memory["user_preferences"], **user_preferences})
    if coding_style:
        memory["coding_style"] = unique_text_items([*memory["coding_style"], *coding_style], 30)
    if commands:
        memory["commands"] = unique_text_items([*memory["commands"], *commands], 50)
    if learned_behavior:
        memory["learned_behavior"] = unique_text_items([*memory["learned_behavior"], *learned_behavior], 50)
    if projects:
        memory["projects"] = normalize_projects([*memory["projects"], *projects])
    memory["updated_at"] = utc_now()
    return memory


def unique_text_items(items: Any, limit: int) -> list[str]:
    values = [str(item).strip()[:1000] for item in items if str(item).strip()] if isinstance(items, list) else []
    return list(dict.fromkeys(values))[-limit:]


def normalize_projects(projects: Any) -> list[dict[str, str]]:
    by_name: dict[str, dict[str, str]] = {}
    for item in projects if isinstance(projects, list) else []:
        if isinstance(item, dict):
            name = str(item.get("name", "")).strip()
            focus = str(item.get("focus", "")).strip()
        else:
            name, focus = str(item).strip(), ""
        if name:
            by_name[name.lower()] = {"name": name[:200], "focus": focus[:1000]}
    return list(by_name.values())[-30:]


def extract_commands(terminal_output: str) -> list[str]:
    commands: list[str] = []
    for line in terminal_output.splitlines():
        value = line.strip()
        for prefix in ("PS> ", "> ", "$ "):
            if value.startswith(prefix) and len(value) > len(prefix):
                commands.append(value[len(prefix):])
                break
    return unique_text_items(commands, 50)


def default_user_preferences() -> dict[str, Any]:
    return {
        "provider_mode": "auto",
        "compact_mode": False,
        "context_window_tokens": 4000,
    }


def normalized_user_preferences(preferences: dict[str, Any]) -> dict[str, Any]:
    normalized = default_user_preferences()
    provider_mode = str(preferences.get("provider_mode", normalized["provider_mode"])).strip()
    if provider_mode in {"auto", "groq", "gemini", "openai", "deepseek"}:
        normalized["provider_mode"] = provider_mode
    normalized["compact_mode"] = bool(preferences.get("compact_mode", normalized["compact_mode"]))
    try:
        context_window_tokens = int(preferences.get("context_window_tokens", normalized["context_window_tokens"]))
    except (TypeError, ValueError):
        context_window_tokens = normalized["context_window_tokens"]
    normalized["context_window_tokens"] = max(500, min(context_window_tokens, 128000))
    return normalized
