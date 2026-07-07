import os
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from agromind.ai import AIProviderError
from agromind.models import default_groq_model


AGENT_KNOWLEDGE_DIR = Path(__file__).resolve().parent / "knowledge"


class AgentChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    agent: str = "auto"
    session_id: str | None = None


class AgentChatResponse(BaseModel):
    agent: str
    session_id: str
    answer: str
    provider: str
    sources: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class AgentProfile:
    id: str
    name: str
    domain: str
    temperature: float
    system_prompt: str


@dataclass(frozen=True)
class AgentMemoryMessage:
    role: str
    content: str


@dataclass(frozen=True)
class RetrievedContext:
    source: str
    text: str
    score: int


AGENTS = {
    "farmer": AgentProfile(
        id="farmer",
        name="Farmer Agent",
        domain="agriculture",
        temperature=0.25,
        system_prompt=(
            "You are AgroMind's Farmer Agent. Help with crops, soil, irrigation, pests, "
            "disease symptoms, weather-aware planning, input decisions, farm operations, "
            "and market-aware practical steps. Ask for crop, location, season, stage, "
            "soil, water, and symptom details when missing."
        ),
    ),
    "doctor": AgentProfile(
        id="doctor",
        name="Doctor Agent",
        domain="healthcare",
        temperature=0.15,
        system_prompt=(
            "You are AgroMind's Doctor Agent. Provide careful educational health guidance, "
            "triage support, follow-up questions, wellness steps, and red-flag escalation. "
            "Do not claim to diagnose with certainty and do not replace a licensed clinician."
        ),
    ),
    "tutor": AgentProfile(
        id="tutor",
        name="Tutor Agent",
        domain="education",
        temperature=0.35,
        system_prompt=(
            "You are AgroMind's Tutor Agent. Teach step by step, adapt to the learner's "
            "level, remember what the learner is studying, give hints before final answers "
            "when useful, and create practice material."
        ),
    ),
}


ROUTING_KEYWORDS = {
    "farmer": {
        "crop", "farm", "soil", "seed", "irrigation", "fertilizer", "pest", "leaf",
        "plant", "harvest", "mandi", "yield", "rain", "tomato", "wheat", "rice",
    },
    "doctor": {
        "health", "fever", "pain", "symptom", "medicine", "skin", "rash", "blood",
        "report", "doctor", "sleep", "stress", "diet", "infection", "allergy",
    },
    "tutor": {
        "study", "learn", "teach", "explain", "homework", "exam", "notes", "quiz",
        "mcq", "worksheet", "essay", "math", "science", "class", "chapter",
        "plot", "graph", "chart", "visualize", "visualise", "equation",
    },
}


class AgentOrchestrator:
    def __init__(self, knowledge_dir: Path = AGENT_KNOWLEDGE_DIR) -> None:
        self.knowledge_dir = knowledge_dir

    def resolve_agent(self, requested_agent: str, message: str) -> AgentProfile:
        requested = (requested_agent or "auto").strip().lower()
        if requested in AGENTS:
            return AGENTS[requested]

        text = message.lower()
        scores = {
            agent_id: sum(1 for keyword in keywords if keyword in text)
            for agent_id, keywords in ROUTING_KEYWORDS.items()
        }
        best_agent = max(scores, key=scores.get)
        if scores[best_agent] > 0:
            return AGENTS[best_agent]
        return AGENTS["farmer"]

    def search_knowledge(self, agent_id: str, query: str, limit: int = 3) -> list[RetrievedContext]:
        agent_dir = self.knowledge_dir / agent_id
        if not agent_dir.exists():
            return []

        terms = {term.lower().strip(".,?!:;()[]{}") for term in query.split() if len(term) > 2}
        matches: list[RetrievedContext] = []
        for path in agent_dir.glob("*.md"):
            try:
                text = path.read_text(encoding="utf-8")
            except Exception:
                continue
            score = sum(text.lower().count(term) for term in terms)
            if score:
                matches.append(
                    RetrievedContext(
                        source=str(path.relative_to(self.knowledge_dir)).replace("\\", "/"),
                        text=text[:2000],
                        score=score,
                    )
                )
        return sorted(matches, key=lambda item: item.score, reverse=True)[:limit]

    def fallback_answer(self, agent: AgentProfile, message: str) -> str:
        return (
            f"## {agent.name}\n\n"
            "I can help with this as an AgroMind agent, but the live AI provider is not reachable right now. "
            "Here is the safe next step:\n\n"
            f"- I understood your request: {message.strip()}\n"
            "- Share any missing details such as location, age/class level, crop/stage, symptoms, or goal.\n"
            "- I will keep context across this agent chat when Supabase memory is configured.\n\n"
            "Try again once the provider connection is available."
        )

    def build_messages(
        self,
        agent: AgentProfile,
        message: str,
        memory: list[AgentMemoryMessage],
        context: list[RetrievedContext],
    ) -> list[dict]:
        context_text = "\n\n".join(f"Source: {item.source}\n{item.text}" for item in context)
        system_prompt = (
            f"{agent.system_prompt}\n\n"
            "You are operating inside AgroMind as an agent, not a one-shot form filler. "
            "Use memory for continuity, ask focused follow-up questions when the task is under-specified, "
            "and suggest safe next actions. Keep answers practical and structured."
        )
        if context_text:
            system_prompt += f"\n\nRetrieved local knowledge:\n{context_text}"

        messages = [{"role": "system", "content": system_prompt}]
        for item in memory[-12:]:
            if item.role in {"user", "assistant"} and item.content:
                messages.append({"role": item.role, "content": item.content})
        messages.append({"role": "user", "content": message})
        return messages

    async def reply(
        self,
        request: AgentChatRequest,
        user_id: str | None,
        access_token: str | None = None,
    ) -> AgentChatResponse:
        from agromind.supabase_store import fetch_agent_memory, save_agent_memory

        agent = self.resolve_agent(request.agent, request.message)
        session_id = request.session_id or user_id or "anonymous"
        memory_rows = fetch_agent_memory(user_id, agent.id, session_id, access_token=access_token)
        memory = [AgentMemoryMessage(role=row.get("role", ""), content=row.get("content", "")) for row in memory_rows]
        context = self.search_knowledge(agent.id, request.message)
        messages = self.build_messages(agent, request.message, memory, context)

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
                    temperature=agent.temperature,
                )
                answer = completion.choices[0].message.content or ""
                provider = f"groq:{model}"
            else:
                answer = self.fallback_answer(agent, request.message)
        except (APIConnectionError, APITimeoutError) as exc:
            answer = self.fallback_answer(agent, request.message)
            provider = "local:fallback"
            print(f"Agent provider connection failed: {exc}")
        except APIStatusError as exc:
            answer = self.fallback_answer(agent, request.message)
            provider = "local:fallback"
            print(f"Agent provider status error: {getattr(exc, 'status_code', 'unknown')}")
        except AIProviderError as exc:
            answer = exc.user_message
            provider = "local:fallback"
        except Exception as exc:
            answer = self.fallback_answer(agent, request.message)
            provider = "local:fallback"
            print(f"Agent provider failed: {exc}")

        save_agent_memory(user_id, agent.id, session_id, "user", request.message, access_token=access_token)
        save_agent_memory(user_id, agent.id, session_id, "assistant", answer, access_token=access_token)

        return AgentChatResponse(
            agent=agent.id,
            session_id=session_id,
            answer=answer,
            provider=provider,
            sources=[item.source for item in context],
        )
