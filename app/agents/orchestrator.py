from __future__ import annotations

import re
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents.planner import PlannerAgent
from app.agents.specialists import SpecialistAgentRegistry


RouteName = Literal["clarification", "approval", "blocked", "tool_execution", "planned_execution", "direct_response"]


class OrchestratorState(TypedDict, total=False):
    objective: str
    context: dict[str, Any]
    plan: dict[str, Any]
    decision: dict[str, Any]
    route: RouteName
    status: str
    next_node: str
    missing_tools: list[str]
    execution_queue: list[list[str]]
    result: dict[str, Any]
    selected_agent: str
    agent_output: dict[str, Any]
    reflection: dict[str, Any]
    reflections: list[dict[str, Any]]
    review: dict[str, Any]
    agent_results: list[dict[str, Any]]
    final_result: dict[str, Any]
    retry_count: int
    max_retries: int
    retry_action: str
    trace: list[str]


class DecisionRouter:
    """Select the next orchestration path from plan, risk, and capability state."""

    AMBIGUOUS_PATTERN = re.compile(r"^(do it|do this|fix it|fix this|continue|handle that|make it work)[.! ]*$", re.I)

    def decide(self, plan: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        context = context or {}
        objective = str(plan.get("objective") or "").strip()
        requirements = plan.get("tool_requirements") or []
        missing = [str(item["server"]) for item in requirements if item.get("required") and item.get("available") is False]
        risk_flags = list(plan.get("complexity", {}).get("risk_flags") or [])
        has_context = any(value for key, value in context.items() if key != "available_mcp_servers")
        if self.AMBIGUOUS_PATTERN.fullmatch(objective) and not has_context:
            route: RouteName = "clarification"
            reason = "The objective refers to missing context"
        elif risk_flags and not bool(context.get("approved")):
            route = "approval"
            reason = "Risk-sensitive work requires explicit approval"
        elif missing:
            route = "blocked"
            reason = "One or more required MCP servers are unavailable"
        elif any(item.get("required") for item in requirements):
            route = "tool_execution"
            reason = "The plan requires MCP-backed capabilities"
        elif plan.get("classification", {}).get("category") in {"memory", "rag", "tool", "reflection"}:
            route = "planned_execution"
            reason = "The task requires a stateful specialist agent"
        elif plan.get("complexity", {}).get("level") in {"moderate", "complex"}:
            route = "planned_execution"
            reason = "The task requires coordinated multi-step execution"
        else:
            route = "direct_response"
            reason = "The task can be handled as a single direct response"
        return {"route": route, "reason": reason, "missing_tools": missing, "risk_flags": risk_flags}


class LangGraphOrchestrator:
    """Plan and route AIOS tasks through a compiled LangGraph state graph."""

    def __init__(self, planner: PlannerAgent | None = None, router: DecisionRouter | None = None, agents: SpecialistAgentRegistry | None = None) -> None:
        self.planner = planner or PlannerAgent()
        self.router = router or DecisionRouter()
        self.agents = agents or SpecialistAgentRegistry()
        self.graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(OrchestratorState)
        builder.add_node("plan_task", self._plan_task)
        builder.add_node("decision", self._decision)
        builder.add_node("request_clarification", self._request_clarification)
        builder.add_node("request_approval", self._request_approval)
        builder.add_node("blocked", self._blocked)
        builder.add_node("prepare_tools", self._prepare_tools)
        builder.add_node("prepare_execution", self._prepare_execution)
        builder.add_node("direct_response", self._direct_response)
        builder.add_node("agent_dispatch", self._agent_dispatch)
        builder.add_node("memory_agent", lambda state: self._run_agent(state, "memory"))
        builder.add_node("rag_agent", lambda state: self._run_agent(state, "rag"))
        builder.add_node("browser_agent", lambda state: self._run_agent(state, "browser"))
        builder.add_node("coding_agent", lambda state: self._run_agent(state, "coding"))
        builder.add_node("terminal_agent", lambda state: self._run_agent(state, "terminal"))
        builder.add_node("filesystem_agent", lambda state: self._run_agent(state, "filesystem"))
        builder.add_node("vision_agent", lambda state: self._run_agent(state, "vision"))
        builder.add_node("database_agent", lambda state: self._run_agent(state, "database"))
        builder.add_node("tool_agent", lambda state: self._run_agent(state, "tool"))
        builder.add_node("reflection_agent", lambda state: self._run_agent(state, "reflection", reflect=False))
        builder.add_node("post_reflection", self._post_reflection)
        builder.add_node("retry_decision", self._retry_decision)
        builder.add_node("retry_agent", self._retry_agent)
        builder.add_node("reviewer_agent", self._reviewer_agent)
        builder.add_node("merge_results", self._merge_results)
        builder.add_node("prepared", self._prepared)
        builder.add_edge(START, "plan_task")
        builder.add_edge("plan_task", "decision")
        builder.add_conditional_edges(
            "decision",
            self._select_route,
            {
                "clarification": "request_clarification",
                "approval": "request_approval",
                "blocked": "blocked",
                "tool_execution": "prepare_tools",
                "planned_execution": "prepare_execution",
                "direct_response": "direct_response",
            },
        )
        for node in ("request_clarification", "request_approval", "blocked", "direct_response"):
            builder.add_edge(node, END)
        builder.add_edge("prepare_tools", "agent_dispatch")
        builder.add_edge("prepare_execution", "agent_dispatch")
        builder.add_conditional_edges("agent_dispatch", self._select_agent, {
            "memory": "memory_agent", "rag": "rag_agent", "browser": "browser_agent",
            "coding": "coding_agent", "terminal": "terminal_agent", "filesystem": "filesystem_agent",
            "vision": "vision_agent", "database": "database_agent", "tool": "tool_agent", "reflection": "reflection_agent",
            "prepared": "prepared",
        })
        for node in ("memory_agent", "rag_agent", "browser_agent", "coding_agent", "terminal_agent", "filesystem_agent", "vision_agent", "database_agent", "tool_agent"):
            builder.add_edge(node, "post_reflection")
        builder.add_edge("post_reflection", "retry_decision")
        builder.add_conditional_edges("retry_decision", self._select_retry_action, {"retry": "retry_agent", "review": "reviewer_agent"})
        builder.add_conditional_edges("retry_agent", self._select_agent, {
            "memory": "memory_agent", "rag": "rag_agent", "browser": "browser_agent",
            "coding": "coding_agent", "terminal": "terminal_agent", "filesystem": "filesystem_agent",
            "vision": "vision_agent", "database": "database_agent", "tool": "tool_agent",
        })
        builder.add_edge("reviewer_agent", "merge_results")
        builder.add_edge("merge_results", END)
        builder.add_edge("reflection_agent", END)
        builder.add_edge("prepared", END)
        return builder.compile()

    def _plan_task(self, state: OrchestratorState) -> dict[str, Any]:
        plan = self.planner.plan_dict(state["objective"], state.get("context") or {})
        return {"plan": plan, "trace": [*(state.get("trace") or []), "plan_task"]}

    def _decision(self, state: OrchestratorState) -> dict[str, Any]:
        decision = self.router.decide(state["plan"], state.get("context"))
        return {"decision": decision, "route": decision["route"], "missing_tools": decision["missing_tools"], "trace": [*(state.get("trace") or []), "decision"]}

    @staticmethod
    def _select_route(state: OrchestratorState) -> RouteName:
        return state["route"]

    @staticmethod
    def _queue(state: OrchestratorState) -> list[list[str]]:
        return list(state["plan"].get("dependency_graph", {}).get("execution_batches") or [])

    def _request_clarification(self, state: OrchestratorState) -> dict[str, Any]:
        return {"status": "awaiting_input", "next_node": "user", "execution_queue": [], "result": {"message": "Please provide the task target and the context that 'it' or 'this' refers to."}, "trace": [*state["trace"], "request_clarification"]}

    def _request_approval(self, state: OrchestratorState) -> dict[str, Any]:
        return {"status": "awaiting_approval", "next_node": "user", "execution_queue": self._queue(state), "result": {"message": "Explicit approval is required before risk-sensitive execution.", "risk_flags": state["decision"]["risk_flags"]}, "trace": [*state["trace"], "request_approval"]}

    def _blocked(self, state: OrchestratorState) -> dict[str, Any]:
        return {"status": "blocked", "next_node": "capability_setup", "execution_queue": [], "result": {"message": "Required MCP capabilities are unavailable.", "missing_tools": state["missing_tools"]}, "trace": [*state["trace"], "blocked"]}

    def _prepare_tools(self, state: OrchestratorState) -> dict[str, Any]:
        servers = [item["server"] for item in state["plan"].get("tool_requirements", []) if item.get("required")]
        return {"status": "dispatching", "next_node": "agent_dispatch", "execution_queue": self._queue(state), "result": {"message": "Plan is ready for specialist-agent execution.", "required_servers": servers}, "trace": [*state["trace"], "prepare_tools"]}

    def _prepare_execution(self, state: OrchestratorState) -> dict[str, Any]:
        return {"status": "dispatching", "next_node": "agent_dispatch", "execution_queue": self._queue(state), "result": {"message": "Plan is ready for coordinated agent execution."}, "trace": [*state["trace"], "prepare_execution"]}

    def _agent_dispatch(self, state: OrchestratorState) -> dict[str, Any]:
        selected = self._agent_for(state)
        return {"selected_agent": selected, "next_node": f"{selected}_agent" if selected != "prepared" else "prepared", "trace": [*state["trace"], "agent_dispatch"]}

    @staticmethod
    def _select_agent(state: OrchestratorState) -> str:
        return state["selected_agent"]

    @staticmethod
    def _agent_for(state: OrchestratorState) -> str:
        context = state.get("context") or {}
        override = str(context.get("agent") or "").lower()
        supported = {"memory", "rag", "browser", "coding", "terminal", "filesystem", "vision", "database", "tool", "reflection"}
        if override in supported:
            return override
        category = str(state["plan"].get("classification", {}).get("category") or "")
        if category in {"memory", "rag", "coding", "filesystem", "vision", "tool", "reflection"}:
            return category
        if category == "data":
            return "database"
        servers = {item["server"] for item in state["plan"].get("tool_requirements", []) if item.get("required")}
        if "aios-browser" in servers:
            return "browser"
        if "aios-terminal" in servers:
            return "terminal"
        if "aios-filesystem" in servers:
            return "filesystem"
        if servers:
            return "tool"
        return "prepared"

    def _run_agent(self, state: OrchestratorState, name: str, reflect: bool = True) -> dict[str, Any]:
        context = state.get("context") or {}
        inputs = context.get("agent_inputs") if isinstance(context.get("agent_inputs"), dict) else {}
        raw_payload = inputs.get(name, context.get("agent_input"))
        if isinstance(raw_payload, list):
            attempt_index = min(state.get("retry_count", 0), max(0, len(raw_payload) - 1))
            payload = raw_payload[attempt_index] if raw_payload and isinstance(raw_payload[attempt_index], dict) else {}
        else:
            payload = raw_payload if isinstance(raw_payload, dict) else {}
        output = self.agents.execute(name, state["objective"], payload if isinstance(payload, dict) else {}, context)
        status = "completed" if output["status"] == "completed" else output["status"]
        next_node = "post_reflection" if reflect else "complete" if status == "completed" else "user"
        results = [*(state.get("agent_results") or []), {"attempt": state.get("retry_count", 0) + 1, **output}]
        return {"status": "reflecting" if reflect else status, "next_node": next_node, "agent_output": output, "agent_results": results, "result": output, "trace": [*state["trace"], f"{name}_agent"]}

    def _post_reflection(self, state: OrchestratorState) -> dict[str, Any]:
        reflection = self.agents.execute("reflection", state["objective"], {"agent_output": state["agent_output"], "plan": state["plan"]}, state.get("context") or {})
        agent_status = state["agent_output"].get("status", "failed")
        final_status = "completed" if agent_status == "completed" else agent_status
        reflections = [*(state.get("reflections") or []), {"attempt": state.get("retry_count", 0) + 1, **reflection}]
        return {"status": final_status, "reflection": reflection, "reflections": reflections, "result": {"agent_output": state["agent_output"], "reflection": reflection}, "trace": [*state["trace"], "post_reflection"]}

    def _retry_decision(self, state: OrchestratorState) -> dict[str, Any]:
        should_retry = state["agent_output"].get("status") == "failed" and state.get("retry_count", 0) < state.get("max_retries", 1)
        action = "retry" if should_retry else "review"
        return {"retry_action": action, "next_node": "retry_agent" if should_retry else "reviewer_agent", "trace": [*state["trace"], "retry_decision"]}

    @staticmethod
    def _select_retry_action(state: OrchestratorState) -> str:
        return state["retry_action"]

    def _retry_agent(self, state: OrchestratorState) -> dict[str, Any]:
        return {"retry_count": state.get("retry_count", 0) + 1, "status": "retrying", "next_node": f"{state['selected_agent']}_agent", "trace": [*state["trace"], "retry_agent"]}

    def _reviewer_agent(self, state: OrchestratorState) -> dict[str, Any]:
        review = self.agents.execute(
            "reviewer", state["objective"],
            {"agent_output": state["agent_output"], "reflection": state["reflection"], "plan": state["plan"]},
            state.get("context") or {},
        )
        return {"review": review, "status": "reviewing", "next_node": "merge_results", "trace": [*state["trace"], "reviewer_agent"]}

    def _merge_results(self, state: OrchestratorState) -> dict[str, Any]:
        review_output = state.get("review", {}).get("output") or {}
        verdict = review_output.get("verdict", "changes_required")
        status = "completed" if verdict == "approved" else "failed" if verdict == "rejected" else "needs_review"
        attempts = state.get("agent_results") or []
        final = {
            "objective": state["objective"], "plan_id": state["plan"].get("id"),
            "status": status, "selected_agent": state.get("selected_agent"),
            "attempt_count": len(attempts), "retry_count": state.get("retry_count", 0),
            "agent_results": attempts, "reflections": state.get("reflections") or [],
            "review": state.get("review"),
            "summary": f"{state.get('selected_agent', 'Agent')} execution {verdict} after {len(attempts)} attempt(s).",
        }
        return {"status": status, "next_node": "complete" if status == "completed" else "user", "final_result": final, "result": final, "trace": [*state["trace"], "merge_results"]}

    def _prepared(self, state: OrchestratorState) -> dict[str, Any]:
        return {"status": "ready", "next_node": "future_specialist_agent", "result": {"message": "Plan is ready, but its specialist agent is not implemented yet."}, "trace": [*state["trace"], "prepared"]}

    def _direct_response(self, state: OrchestratorState) -> dict[str, Any]:
        return {"status": "ready", "next_node": "general_agent", "execution_queue": self._queue(state), "result": {"message": "Task can proceed through the direct-response path."}, "trace": [*state["trace"], "direct_response"]}

    def invoke(self, objective: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        objective = objective.strip()
        if not objective:
            raise ValueError("Task objective is required")
        safe_context = dict(context or {})
        try:
            max_retries = max(0, min(int(safe_context.get("max_retries", 1)), 3))
        except (TypeError, ValueError) as exc:
            raise ValueError("max_retries must be an integer between 0 and 3") from exc
        prior_results = safe_context.get("agent_results") if isinstance(safe_context.get("agent_results"), list) else []
        return dict(self.graph.invoke({
            "objective": objective, "context": safe_context, "trace": [],
            "retry_count": 0, "max_retries": max_retries, "agent_results": list(prior_results), "reflections": [],
        }))
