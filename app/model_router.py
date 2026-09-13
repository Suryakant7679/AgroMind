from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Protocol


TASK_TYPES = ("coding", "reasoning", "vision", "math", "research", "general")
PROVIDERS = ("groq", "gemini", "openai", "deepseek")


@dataclass(frozen=True)
class ModelRoute:
    task: str
    provider: str
    model: str


class ModelRouter(Protocol):
    """Contract for task classification and provider/model routing."""

    def classify(self, messages: list[dict[str, str]]) -> str: ...

    def routes(self, messages: list[dict[str, str]], available: list[str]) -> list[ModelRoute]: ...


class EnvironmentModelRouter:
    """Routes tasks using environment overrides with deterministic fallback."""

    DEFAULT_MODELS = {
        "groq": "llama-3.1-8b-instant",
        "gemini": "gemini-2.0-flash",
        "openai": "gpt-4o-mini",
        "deepseek": "deepseek-chat",
    }

    TASK_PATTERNS = {
        "vision": r"\b(image|photo|picture|screenshot|diagram|visual|ocr)\b",
        "coding": r"\b(code|coding|bug|debug|function|class|api|sql|python|javascript|typescript|program)\b",
        "math": r"\b(calculate|equation|algebra|geometry|calculus|probability|integral|derivative|matrix)\b|\d\s*[+*/^=]\s*\d",
        "research": r"\b(research|sources?|citations?|papers?|literature|compare evidence|latest)\b",
        "reasoning": r"\b(reason|reasoning|analy[sz]e|logic|deduce|strategy|trade-?offs?|step by step|why)\b",
    }

    def classify(self, messages: list[dict[str, str]]) -> str:
        text = " ".join(
            item.get("content", "") for item in messages if item.get("role") == "user"
        ).lower()
        for task, pattern in self.TASK_PATTERNS.items():
            if re.search(pattern, text):
                return task
        return "general"

    def routes(self, messages: list[dict[str, str]], available: list[str]) -> list[ModelRoute]:
        task = self.classify(messages)
        requested = os.getenv(f"AIOS_{task.upper()}_PROVIDER", "").strip().lower()
        global_provider = os.getenv("AIOS_PROVIDER", "auto").strip().lower()
        preferred = requested or global_provider
        if preferred != "auto" and preferred not in PROVIDERS:
            raise ValueError(f"Unknown provider configured for {task}: {preferred}")

        providers = list(available)
        if preferred != "auto":
            providers = [preferred]
        return [ModelRoute(task, provider, self.model_for(task, provider)) for provider in providers]

    def model_for(self, task: str, provider: str) -> str:
        keys = (
            f"AIOS_{task.upper()}_{provider.upper()}_MODEL",
            f"AIOS_{task.upper()}_MODEL",
            f"AIOS_{provider.upper()}_MODEL",
            "AIOS_DEFAULT_MODEL",
        )
        for key in keys:
            value = os.getenv(key, "").strip()
            if value:
                return value
        return self.DEFAULT_MODELS[provider]

