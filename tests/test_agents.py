from fastapi.testclient import TestClient

import agromind.main as main
from agromind.agents.service import AgentChatRequest, AgentChatResponse, AgentOrchestrator
import agromind.supabase_store as store


def test_agent_router_selects_domain_agents():
    orchestrator = AgentOrchestrator()

    assert orchestrator.resolve_agent("auto", "My tomato crop leaves are curling").id == "farmer"
    assert orchestrator.resolve_agent("auto", "I have fever and skin rash").id == "doctor"
    assert orchestrator.resolve_agent("auto", "Explain quadratic equations for my exam").id == "tutor"
    assert orchestrator.resolve_agent("doctor", "general question").id == "doctor"


def test_agent_chat_requires_login():
    with TestClient(main.app) as test_client:
        response = test_client.post("/api/agents/chat", json={"message": "Help my crop"})

    assert response.status_code == 401


def test_agents_page_requires_login():
    with TestClient(main.app) as test_client:
        response = test_client.get("/agents", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


def test_agents_page_renders_for_authenticated_user(monkeypatch):
    monkeypatch.setattr(main, "user_from_session", lambda request: {"id": "user-1", "email": "u@example.com"})

    with TestClient(main.app) as test_client:
        response = test_client.get("/agents")

    assert response.status_code == 200
    assert "AgroMind Agents" in response.text
    assert "Farmer Agent" in response.text


def test_agent_chat_uses_authenticated_agent_orchestrator(monkeypatch):
    class FakeOrchestrator:
        async def reply(self, request, user_id, access_token=None):
            assert request.message == "Help my crop"
            assert request.agent == "auto"
            assert user_id == "user-1"
            assert access_token == "token"
            return AgentChatResponse(
                agent="farmer",
                session_id="user-1",
                answer="Agent response",
                provider="local",
                sources=[],
            )

    monkeypatch.setattr(main, "user_from_session", lambda request: {"id": "user-1", "email": "u@example.com", "access_token": "token"})
    monkeypatch.setattr(main, "agent_orchestrator", FakeOrchestrator())

    with TestClient(main.app) as test_client:
        response = test_client.post("/api/agents/chat", json={"message": "Help my crop"})

    assert response.status_code == 200
    assert response.json()["agent"] == "farmer"
    assert response.json()["answer"] == "Agent response"


def test_agent_orchestrator_falls_back_without_provider(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(store, "fetch_agent_memory", lambda *args, **kwargs: [])
    saved_messages = []
    monkeypatch.setattr(store, "save_agent_memory", lambda *args, **kwargs: saved_messages.append(args))

    orchestrator = AgentOrchestrator()
    response = __import__("asyncio").run(
        orchestrator.reply(
            AgentChatRequest(message="My tomato leaves are yellow", agent="auto", session_id="s1"),
            user_id="user-1",
        )
    )

    assert response.agent == "farmer"
    assert response.provider == "local"
    assert "Farmer Agent" in response.answer
    assert len(saved_messages) == 2
