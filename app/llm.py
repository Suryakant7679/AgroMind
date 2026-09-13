from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Iterator
from datetime import date
from threading import local
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.model_router import EnvironmentModelRouter, ModelRoute
from app.observability import OBSERVABILITY
from app.usage import UsageTracker
from app.validation import ValidationError, ValidationManager, validation_context


SYSTEM_PROMPT = (
    "You are AIOS, a helpful AI assistant inside a local chatbot app. "
    "Answer clearly, stay practical, and ask a short follow-up question when the user goal is unclear. "
    "When explaining mathematics, show the relevant equations and steps, define the symbols, and write "
    "mathematical notation as LaTeX using $...$ for inline formulas and $$...$$ for display formulas. "
    "When live DuckDuckGo or MCP evidence is supplied, it is authoritative and overrides model knowledge, "
    "conversation history, summaries, and memory. Answer current factual questions only from that evidence. "
    "When sources conflict, prefer official primary sources and evidence current as of today's supplied date. "
    "For factual and current claims, include clickable Markdown source links using the exact supplied URLs. "
    "Never cite a search query, never invent bare numeric citations, and never reuse an earlier answer that "
    "conflicts with live evidence. Tool execution is already complete when evidence is supplied: return only "
    "the final answer, never a plan or a statement that you will search. "
    "Do not repeat or append an earlier assistant response to the new answer."
)


class LLMError(RuntimeError):
    pass


ROUTER = EnvironmentModelRouter()
USAGE = UsageTracker()
VALIDATION = ValidationManager.from_env()
_ROUTE_STATE = local()


def has_live_tool_evidence(messages: list[dict[str, str]]) -> bool:
    return any(
        item.get("role") == "system"
        and ("AUTHORITATIVE LIVE WEB EVIDENCE" in item.get("content", "") or "Live GitHub MCP results" in item.get("content", ""))
        for item in messages
    )


def is_incomplete_tool_plan(text: str) -> bool:
    if re.search(r"\[[^\]]+\]\(https?://[^)]+\)", text):
        return False
    return bool(re.search(
        r"\b(?:i need to (?:find|search|look up)|i (?:will|'ll) (?:search|look up|check)|"
        r"perform (?:a )?(?:quick )?search|duckduckgo search\s*:|let me (?:search|check))\b",
        text,
        re.IGNORECASE,
    ))


def finalize_grounded_response(text: str, messages: list[dict[str, str]]) -> str:
    evidence = "\n".join(
        item.get("content", "") for item in messages
        if item.get("role") == "system" and "AUTHORITATIVE LIVE WEB EVIDENCE" in item.get("content", "")
    )
    sources = re.findall(r"\[\d+\]\s+([^\n]+)\nURL:\s*(https?://\S+)", evidence)
    if not sources:
        return text.strip()
    cleaned = re.sub(r"(?<!\])\s*\[\d+\]", "", text)
    cleaned = re.sub(r"(?m)^\s*https?://\S+\s*$", "", cleaned).strip()
    existing_urls = set(re.findall(r"\[[^\]]+\]\((https?://[^)]+)\)", cleaned))
    links = [f"[{title.strip()}]({url})" for title, url in sources[:3] if url not in existing_urls]
    if links:
        cleaned += "\n\nSources:\n\n" + "\n".join(f"- {link}" for link in links)
    return cleaned


def remove_echoed_assistant_responses(text: str, messages: list[dict[str, str]]) -> str:
    """Remove long prior assistant messages copied verbatim into a new response."""
    cleaned = text.strip()
    prior_responses = {
        item.get("content", "").strip()
        for item in messages
        if item.get("role") == "assistant" and len(item.get("content", "").strip()) >= 80
    }
    for prior in sorted(prior_responses, key=len, reverse=True):
        if prior not in cleaned:
            continue
        candidate = cleaned.replace(prior, "").strip()
        candidate = re.sub(r"(?:\r?\n\s*){3,}", "\n\n", candidate).strip()
        if candidate:
            cleaned = candidate
    return cleaned


def generate_response(messages: list[dict[str, str]]) -> tuple[str, str]:
    text, route = _generate_response_once(messages)
    active_route = [route]
    if has_live_tool_evidence(messages) and is_incomplete_tool_plan(text):
        text, corrected_route = _generate_response_once([
            *messages,
            {
                "role": "system",
                "content": (
                    "The tools have already finished and their results are in the authoritative evidence above. "
                    "Do not announce, request, or simulate another search. Return the completed answer now, using "
                    "the freshest official evidence and at least one clickable Markdown source link."
                ),
            },
        ])
        active_route[0] = corrected_route
        if is_incomplete_tool_plan(text):
            raise LLMError("The model returned a tool plan instead of a final grounded answer.")
    if has_live_tool_evidence(messages):
        text = finalize_grounded_response(text, messages)
    text = remove_echoed_assistant_responses(text, messages)

    def retry(feedback: str) -> str:
        retry_messages = [*messages, {"role": "system", "content": feedback}]
        corrected, retry_route = _generate_response_once(retry_messages)
        active_route[0] = retry_route
        return remove_echoed_assistant_responses(corrected, messages)

    try:
        validated = VALIDATION.process(text, validation_context(messages), retry=retry)
    except ValidationError as exc:
        raise LLMError(str(exc)) from exc
    return validated, active_route[0].provider


def generate_response_stream(messages: list[dict[str, str]]) -> tuple[Iterator[str], str]:
    # Tool-grounded answers are completed and validated before delivery so an
    # intermediate "I will search" plan can never leak into the chat UI.
    if has_live_tool_evidence(messages):
        text, provider = generate_response(messages)
        return iter((text,)), provider
    started = time.perf_counter()
    route: ModelRoute | None = None
    try:
        chunks, route = generate_with_router(messages, stream=True)
        assert not isinstance(chunks, str)
        def live_chunks() -> Iterator[str]:
            output: list[str] = []
            try:
                for chunk in chunks:
                    output.append(chunk)
                    yield chunk
            finally:
                text = "".join(output).strip()
                USAGE.record(route.provider, route.model, route.task, messages, text)
                OBSERVABILITY.record("model", f"{route.provider}/{route.model}", duration_ms=(time.perf_counter() - started) * 1000, properties={"task": route.task, "stream": True})

        return live_chunks(), route.provider
    except (ValidationError, LLMError) as exc:
        OBSERVABILITY.record("model", f"{route.provider}/{route.model}" if route else "unrouted", success=False, duration_ms=(time.perf_counter() - started) * 1000, error=str(exc), properties={"task": route.task if route else "unknown", "stream": True})
        raise LLMError(str(exc)) from exc


def _generate_response_once(messages: list[dict[str, str]]) -> tuple[str, ModelRoute]:
    text, route = generate_with_router(messages, stream=False)
    assert isinstance(text, str)
    USAGE.record(route.provider, route.model, route.task, messages, text)
    return text, route


def generate_with_router(
    messages: list[dict[str, str]], stream: bool
) -> tuple[str | Iterator[str], ModelRoute]:
    try:
        routes = ROUTER.routes(messages, configured_providers())
    except ValueError as exc:
        raise LLMError(str(exc)) from exc
    errors: list[str] = []
    for route in routes:
        _ROUTE_STATE.active = route
        started = time.perf_counter()
        try:
            if route.provider in {"openai", "groq", "deepseek"}:
                result = chat_completions_stream(route.provider, messages) if stream else chat_completions(route.provider, messages)
            else:
                result = gemini_stream(messages) if stream else gemini(messages)
            if not stream:
                OBSERVABILITY.record("model", f"{route.provider}/{route.model}", duration_ms=(time.perf_counter() - started) * 1000, properties={"task": route.task, "stream": False})
            return result, route
        except LLMError as exc:
            OBSERVABILITY.record("model", f"{route.provider}/{route.model}", success=False, duration_ms=(time.perf_counter() - started) * 1000, error=str(exc), properties={"task": route.task, "stream": stream})
            errors.append(f"{route.provider}: {exc}")
    if errors:
        raise LLMError("All configured providers failed. " + " | ".join(errors))
    raise LLMError("No LLM provider is configured. Add an API key to .env.")


def current_route() -> ModelRoute | None:
    return getattr(_ROUTE_STATE, "active", None)


def generate_with_fallback(messages: list[dict[str, str]]) -> tuple[str, str]:
    errors: list[str] = []
    for provider in configured_providers():
        try:
            if provider in {"openai", "groq", "deepseek"}:
                return chat_completions(provider, messages), provider
            if provider == "gemini":
                return gemini(messages), provider
        except LLMError as exc:
            errors.append(f"{provider}: {exc}")

    if errors:
        raise LLMError(
            "All configured providers failed. Please verify your API keys and network connection. "
            + " | ".join(errors)
        )
    raise LLMError(
        "No LLM provider is configured. Add an API key to .env, for example GROQ_API_KEY or GEMINI_API_KEY."
    )


def generate_stream_with_fallback(messages: list[dict[str, str]]) -> tuple[Iterator[str], str]:
    errors: list[str] = []
    for provider in configured_providers():
        try:
            if provider in {"openai", "groq", "deepseek"}:
                return chat_completions_stream(provider, messages), provider
            if provider == "gemini":
                return gemini_stream(messages), provider
        except LLMError as exc:
            errors.append(f"{provider}: {exc}")

    if errors:
        raise LLMError(
            "All configured providers failed. Please verify your API keys and network connection. "
            + " | ".join(errors)
        )
    raise LLMError(
        "No LLM provider is configured. Add an API key to .env, for example GROQ_API_KEY or GEMINI_API_KEY."
    )


def configured_providers() -> list[str]:
    """Only Gemini and Groq may generate user-facing answers."""
    providers: list[str] = []
    if os.getenv("GROQ_API_KEY"):
        providers.append("groq")
    if os.getenv("GEMINI_API_KEY"):
        providers.append("gemini")
    return providers


def should_use_web_search(query: str) -> bool:
    """Ask the active Gemini/Groq model whether fresh web evidence is necessary."""
    query = " ".join(str(query).split())[:1000]
    if not query:
        return False
    temporal_pattern = rf"\b(?:current|currently|today|this\s+year|latest|recent|news|who\s+won|winner|champion|{date.today().year})\b"
    if re.search(temporal_pattern, query, re.IGNORECASE):
        return True
    decision_prompt = (
        "You are a tool-routing classifier. Decide whether answering the USER QUERY requires live web search. "
        "Return exactly WEB for current affairs, recent or changing facts, requested sources/citations/papers, "
        "shopping/travel recommendations, or facts you are not confident are stable. Return exactly DIRECT for "
        "greetings, writing help, calculations, coding from supplied context, and stable textbook/book knowledge.\n\n"
        f"USER QUERY: {query}"
    )
    try:
        decision, route = generate_with_router([{"role": "user", "content": decision_prompt}], stream=False)
        assert isinstance(decision, str)
        OBSERVABILITY.record("model", f"{route.provider}/{route.model}", properties={"task": "tool-routing"})
        return decision.strip().upper().startswith("WEB")
    except LLMError:
        return bool(re.search(r"\b(latest|today|current|news|recent|source|citation|reference|paper|research|look up|web search)\b", query, re.I))


def chat_completions(provider: str, messages: list[dict[str, str]]) -> str:
    configs = {
        "openai": {
            "key": "OPENAI_API_KEY",
            "url": "https://api.openai.com/v1/chat/completions",
            "model": "gpt-4o-mini",
        },
        "groq": {
            "key": "GROQ_API_KEY",
            "url": "https://api.groq.com/openai/v1/chat/completions",
            "model": "llama-3.1-8b-instant",
        },
        "deepseek": {
            "key": "DEEPSEEK_API_KEY",
            "url": "https://api.deepseek.com/chat/completions",
            "model": "deepseek-chat",
        },
    }
    config = configs[provider]
    api_key = require_env(config["key"])
    model = provider_model(provider, config["model"])
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, *messages],
        "temperature": float(os.getenv("AIOS_TEMPERATURE", "0.7")),
    }
    data = post_json(
        config["url"],
        payload,
        {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "AIOS-Starter/0.1",
        },
    )
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"Unexpected {provider} response shape.") from exc


def chat_completions_stream(provider: str, messages: list[dict[str, str]]) -> Iterator[str]:
    configs = {
        "openai": {
            "key": "OPENAI_API_KEY",
            "url": "https://api.openai.com/v1/chat/completions",
            "model": "gpt-4o-mini",
        },
        "groq": {
            "key": "GROQ_API_KEY",
            "url": "https://api.groq.com/openai/v1/chat/completions",
            "model": "llama-3.1-8b-instant",
        },
        "deepseek": {
            "key": "DEEPSEEK_API_KEY",
            "url": "https://api.deepseek.com/chat/completions",
            "model": "deepseek-chat",
        },
    }
    config = configs[provider]
    api_key = require_env(config["key"])
    model = provider_model(provider, config["model"])
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, *messages],
        "temperature": float(os.getenv("AIOS_TEMPERATURE", "0.7")),
        "stream": True,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "User-Agent": "AIOS-Starter/0.1",
    }
    return stream_chat_completions(config["url"], payload, headers, provider)


def gemini(messages: list[dict[str, str]]) -> str:
    api_key = require_env("GEMINI_API_KEY")
    prompt = "\n\n".join(f"{item['role']}: {item['content']}" for item in messages)
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": float(os.getenv("AIOS_TEMPERATURE", "0.7"))},
    }
    errors: list[str] = []
    for model in gemini_models_to_try():
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={api_key}"
        )
        try:
            data = post_json(
                url,
                payload,
                {
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": "AIOS-Starter/0.1",
                },
            )
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(part.get("text", "") for part in parts).strip()
        except LLMError as exc:
            errors.append(f"{model}: {exc}")
            continue
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("Unexpected gemini response shape.") from exc

    raise LLMError("All Gemini models failed. " + " | ".join(errors))


def gemini_stream(messages: list[dict[str, str]]) -> Iterator[str]:
    api_key = require_env("GEMINI_API_KEY")
    prompt = "\n\n".join(f"{item['role']}: {item['content']}" for item in messages)
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": float(os.getenv("AIOS_TEMPERATURE", "0.7"))},
    }
    errors: list[str] = []
    for model in gemini_models_to_try():
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:streamGenerateContent?alt=sse&key={api_key}"
        )
        try:
            return stream_gemini(url, payload, model)
        except LLMError as exc:
            errors.append(f"{model}: {exc}")
            continue

    raise LLMError("All Gemini streaming models failed. " + " | ".join(errors))


def post_json(url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    attempts = int(os.getenv("AIOS_LLM_RETRIES", "2")) + 1
    last_error: Exception | None = None

    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=int(os.getenv("AIOS_LLM_TIMEOUT", "60"))) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise LLMError(f"LLM request failed with HTTP {exc.code}: {detail}") from exc
        except TimeoutError as exc:
            last_error = exc
            if attempt == attempts - 1:
                raise LLMError("The LLM provider request timed out.") from exc
        except (ConnectionResetError, ConnectionAbortedError) as exc:
            last_error = exc
            if attempt == attempts - 1:
                raise LLMError(connection_error_message(exc)) from exc
        except URLError as exc:
            last_error = exc
            reason = exc.reason
            if attempt == attempts - 1:
                raise LLMError(connection_error_message(reason)) from exc

        time.sleep(0.7 * (attempt + 1))

    raise LLMError(connection_error_message(last_error))


def stream_chat_completions(
    url: str, payload: dict[str, Any], headers: dict[str, str], provider: str
) -> Iterator[str]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        response = urlopen(request, timeout=int(os.getenv("AIOS_LLM_TIMEOUT", "60")))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise LLMError(f"LLM streaming request failed with HTTP {exc.code}: {detail}") from exc
    except TimeoutError as exc:
        raise LLMError("The LLM provider streaming request timed out.") from exc
    except (ConnectionResetError, ConnectionAbortedError) as exc:
        raise LLMError(connection_error_message(exc)) from exc
    except URLError as exc:
        raise LLMError(connection_error_message(exc.reason)) from exc

    def events() -> Iterator[str]:
        try:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                event = line.removeprefix("data:").strip()
                if event == "[DONE]":
                    return
                chunk = parse_chat_completion_stream_event(event, provider)
                if chunk:
                    yield chunk
        finally:
            response.close()

    return events()


def stream_gemini(url: str, payload: dict[str, Any], model: str) -> Iterator[str]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "User-Agent": "AIOS-Starter/0.1",
        },
        method="POST",
    )
    try:
        response = urlopen(request, timeout=int(os.getenv("AIOS_LLM_TIMEOUT", "60")))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise LLMError(f"Gemini streaming request failed with HTTP {exc.code}: {detail}") from exc
    except TimeoutError as exc:
        raise LLMError("The Gemini streaming request timed out.") from exc
    except (ConnectionResetError, ConnectionAbortedError) as exc:
        raise LLMError(connection_error_message(exc)) from exc
    except URLError as exc:
        raise LLMError(connection_error_message(exc.reason)) from exc

    def events() -> Iterator[str]:
        try:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                event = line.removeprefix("data:").strip()
                chunk = parse_gemini_stream_event(event, model)
                if chunk:
                    yield chunk
        finally:
            response.close()

    return events()


def parse_chat_completion_stream_event(event: str, provider: str) -> str:
    try:
        data = json.loads(event)
        choice = data.get("choices", [{}])[0]
        delta = choice.get("delta", {})
        content = delta.get("content", "")
        if isinstance(content, str):
            return content
        return ""
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"Unexpected {provider} streaming response shape.") from exc


def parse_gemini_stream_event(event: str, model: str) -> str:
    try:
        data = json.loads(event)
        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        return "".join(part.get("text", "") for part in parts if isinstance(part.get("text", ""), str))
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"Unexpected Gemini streaming response shape for {model}.") from exc


def require_env(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        raise LLMError(f"{name} is missing. Add it to .env and restart the app.")
    return value


def provider_model(provider: str, default: str) -> str:
    active_route = current_route()
    if active_route and active_route.provider == provider:
        return active_route.model
    specific_names = {
        "openai": "AIOS_OPENAI_MODEL",
        "groq": "AIOS_GROQ_MODEL",
        "deepseek": "AIOS_DEEPSEEK_MODEL",
        "gemini": "AIOS_GEMINI_MODEL",
    }
    specific = os.getenv(specific_names[provider], "").strip()
    fallback = os.getenv("AIOS_DEFAULT_MODEL", "").strip()
    return specific or fallback or default


def gemini_models_to_try() -> list[str]:
    configured = provider_model("gemini", "gemini-2.0-flash")
    candidates = [
        configured,
        "gemini-2.0-flash",
        "gemini-1.5-flash",
        "gemini-2.5-flash",
    ]
    unique: list[str] = []
    for model in candidates:
        if model and model not in unique:
            unique.append(model)
    return unique


def connection_error_message(error: object) -> str:
    return (
        f"Could not reach the LLM provider: {error}. "
        "This is usually a provider/network reset, not a prompt problem. "
        "Use AIOS_PROVIDER=auto to fall back to another configured provider."
    )
