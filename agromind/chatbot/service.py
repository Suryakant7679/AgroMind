import os
from dataclasses import dataclass

from pydantic import BaseModel, Field

from agromind.ai import AIProviderError
from agromind.data import get_domain, get_tool
from agromind.models import default_groq_model


CHATBOT_AGENT = "workspace_chatbot"


class WorkspaceChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: str | None = None


class WorkspaceChatResponse(BaseModel):
    session_id: str
    answer: str
    provider: str
    context_items: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class ChatMemoryMessage:
    role: str
    content: str


class WorkspaceChatbot:
    def _tool_label(self, output: dict) -> str:
        domain_id = output.get("domain") or "unknown"
        tool_id = output.get("tool") or "unknown"
        domain = get_domain(domain_id)
        tool = get_tool(domain_id, tool_id)
        domain_name = domain["name"] if domain else str(domain_id).replace("-", " ").title()
        tool_name = tool["title"] if tool else str(tool_id).replace("-", " ").title()
        return f"{domain_name} / {tool_name}"

    def _summarize_outputs(self, outputs: list[dict]) -> tuple[str, list[str]]:
        lines = []
        labels = []
        for output in outputs[:8]:
            label = self._tool_label(output)
            labels.append(label)
            prompt = output.get("prompt") or {}
            prompt_text = ", ".join(f"{key}: {value}" for key, value in prompt.items() if value)
            result = (output.get("output_markdown") or "").strip().replace("\n", " ")
            if len(result) > 500:
                result = result[:500].rstrip() + "..."
            lines.append(
                f"- {label}\n"
                f"  Prompt: {prompt_text or 'No prompt fields saved'}\n"
                f"  Result preview: {result or 'No saved output text'}"
            )
        return "\n".join(lines), labels

    def _summarize_usage(self, usage: dict) -> str:
        domain_rows = usage.get("domain_rows") or {}
        provider_rows = usage.get("provider_rows") or {}
        domain_text = ", ".join(
            f"{domain}: {values.get('requests', 0)} requests"
            for domain, values in sorted(domain_rows.items())
        )
        provider_text = ", ".join(
            f"{provider}: {values.get('requests', 0)} requests"
            for provider, values in sorted(provider_rows.items())
        )
        return (
            f"Requests today: {usage.get('requests_today', 0)}\n"
            f"Requests this month: {usage.get('requests_this_month', 0)}\n"
            f"Tokens this month: {usage.get('tokens_this_month', 0)}\n"
            f"Credits this month: {usage.get('credits_this_month', 0)}\n"
            f"Domains used: {domain_text or 'No domain usage yet'}\n"
            f"Providers used: {provider_text or 'No provider usage yet'}"
        )

    def fallback_answer(self, message: str, labels: list[str]) -> str:
        used = "\n".join(f"- {label}" for label in labels[:6])
        used_text = f"\n\nRecent tools I can see:\n{used}" if used else "\n\nI do not see saved tool usage yet."
        return (
            "## Workspace Chatbot\n\n"
            "I can help you understand your AgroMind workspace, but the live AI provider is not reachable right now.\n\n"
            f"Your message: {message.strip()}"
            f"{used_text}\n\n"
            "Ask me things like what tools you used, what output to continue from, or what next step fits your workflow."
        )

    def build_messages(
        self,
        message: str,
        memory: list[ChatMemoryMessage],
        output_context: str,
        usage_context: str,
    ) -> list[dict]:
        system_prompt = (
            "You are AgroMind's Workspace Chatbot. You are separate from the domain agent chat. "
            "Your job is to understand the user's current workspace context, recent tools they used, "
            "saved AI outputs, usage patterns, and ongoing chat memory. Do not execute external actions. "
            "If the user asks to send, save, publish, or modify external systems, explain that AgroMind uses "
            "draft-and-approve workflows. Be concise, practical, and refer to recent tools only when useful.\n\n"
            f"Recent saved tool outputs:\n{output_context or 'No saved outputs yet.'}\n\n"
            f"Usage summary:\n{usage_context}"
        )
        messages = [{"role": "system", "content": system_prompt}]
        for item in memory[-12:]:
            if item.role in {"user", "assistant"} and item.content:
                messages.append({"role": item.role, "content": item.content})
        messages.append({"role": "user", "content": message})
        return messages

    async def reply(
        self,
        request: WorkspaceChatRequest,
        user_id: str | None,
        access_token: str | None = None,
    ) -> WorkspaceChatResponse:
        from agromind.supabase_store import (
            fetch_agent_memory,
            fetch_recent_outputs,
            save_agent_memory,
            usage_summary,
        )

        session_id = request.session_id or user_id or "anonymous"
        memory_rows = fetch_agent_memory(user_id, CHATBOT_AGENT, session_id, access_token=access_token)
        memory = [ChatMemoryMessage(role=row.get("role", ""), content=row.get("content", "")) for row in memory_rows]
        outputs = fetch_recent_outputs(user_id, limit=8, access_token=access_token)
        output_context, labels = self._summarize_outputs(outputs)
        usage_context = self._summarize_usage(usage_summary(user_id, access_token))
        messages = self.build_messages(request.message, memory, output_context, usage_context)

        provider = "local"
        try:
            if os.getenv("GROQ_API_KEY"):
                from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

                model = default_groq_model("reasoning")
                client = OpenAI(
                    api_key=os.getenv("GROQ_API_KEY"),
                    base_url="https://api.groq.com/openai/v1",
                    timeout=45,
                )
                completion = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.25,
                )
                answer = completion.choices[0].message.content or ""
                provider = f"groq:{model}"
            else:
                answer = self.fallback_answer(request.message, labels)
        except (APIConnectionError, APITimeoutError) as exc:
            answer = self.fallback_answer(request.message, labels)
            provider = "local:fallback"
            print(f"Workspace chatbot provider connection failed: {exc}")
        except APIStatusError as exc:
            answer = self.fallback_answer(request.message, labels)
            provider = "local:fallback"
            print(f"Workspace chatbot provider status error: {getattr(exc, 'status_code', 'unknown')}")
        except AIProviderError as exc:
            answer = exc.user_message
            provider = "local:fallback"
        except Exception as exc:
            answer = self.fallback_answer(request.message, labels)
            provider = "local:fallback"
            print(f"Workspace chatbot provider failed: {exc}")

        save_agent_memory(user_id, CHATBOT_AGENT, session_id, "user", request.message, access_token=access_token)
        save_agent_memory(user_id, CHATBOT_AGENT, session_id, "assistant", answer, access_token=access_token)

        return WorkspaceChatResponse(
            session_id=session_id,
            answer=answer,
            provider=provider,
            context_items=labels,
        )
