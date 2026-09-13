from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, replace
from hashlib import sha256
from typing import Any


@dataclass(frozen=True)
class TaskClassification:
    category: str
    intent: str
    confidence: float
    domains: list[str]
    requires_tools: bool
    rationale: str


@dataclass(frozen=True)
class ComplexityAnalysis:
    level: str
    score: int
    estimated_subtasks: int
    factors: list[str]
    risk_flags: list[str]


@dataclass(frozen=True)
class PlannedSubtask:
    id: str
    title: str
    description: str
    category: str
    dependencies: list[str] = field(default_factory=list)
    suggested_tools: list[str] = field(default_factory=list)
    success_criteria: str = ""


@dataclass(frozen=True)
class ToolRequirement:
    server: str
    tools: list[str]
    reason: str
    access: str
    required: bool
    available: bool | None
    configuration: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DependencyGraph:
    dependencies: dict[str, list[str]]
    execution_batches: list[list[str]]
    has_cycle: bool


@dataclass(frozen=True)
class TaskPlan:
    id: str
    objective: str
    classification: TaskClassification
    complexity: ComplexityAnalysis
    tool_requirements: list[ToolRequirement]
    subtasks: list[PlannedSubtask]
    dependency_graph: DependencyGraph
    context: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TaskClassifier:
    CATEGORY_PATTERNS = {
        "reflection": r"\b(reflect|reflection|self-critique|review (?:the )?(?:result|output|work))\b",
        "tool": r"\b(?:use|call|invoke|run) (?:an? )?(?:mcp )?tool\b",
        "memory": r"\b(remember|recall|memory|my preferences?|what do you know about me)\b",
        "rag": r"\b(rag|knowledge base|uploaded documents?|retriev(?:e|al)|search (?:my|the) documents?)\b",
        "vision": r"\b(image|photo|picture|screenshot|diagram|visual|ocr)\b",
        "devops": r"\b(docker|kubernetes|k8s|deploy|deployment|ci/?cd|cloud|aws|azure|gcp|server|infrastructure)\b",
        "data": r"\b(database|postgres(?:ql)?|sqlite|redis|sql|dataset|analytics|query|schema)\b",
        "research": r"\b(research|sources?|citations?|papers?|literature|latest|evidence|web search)\b",
        "communication": r"\b(slack|notion|email|message|announcement|report|documentation|document)\b",
        "coding": r"\b(code|bug|debug|function|class|api|python|javascript|typescript|frontend|backend|refactor|test suite|repository)\b",
        "math": r"\b(calculate|equation|algebra|geometry|calculus|probability|statistics|matrix)\b|\d\s*[+*/^=]\s*\d",
        "filesystem": r"\b(files?|folders?|director(?:y|ies)|workspace|rename|copy|move)\b",
        "reasoning": r"\b(analy[sz]e|reason|strategy|trade-?offs?|compare|evaluate|diagnose|investigate)\b",
    }
    INTENT_PATTERNS = {
        "debug": r"\b(fix|debug|diagnose|investigate|broken|failure|error|bug)\b",
        "create": r"\b(create|build|implement|add|generate|write|design|develop)\b",
        "modify": r"\b(change|update|edit|refactor|improve|optimi[sz]e|migrate|convert|resize|crop)\b",
        "research": r"\b(research|find sources?|look up|latest|investigate|survey)\b",
        "analyze": r"\b(analy[sz]e|compare|evaluate|review|inspect|explain|summari[sz]e)\b",
        "operate": r"\b(run|execute|deploy|start|stop|restart|query|fetch|send)\b",
    }
    TOOL_PATTERN = re.compile(
        r"https?://|\b(file|repository|database|terminal|command|browser|github|docker|kubernetes|slack|notion|ocr|image|api endpoint|deploy|run tests?)\b",
        re.I,
    )

    def classify(self, objective: str) -> TaskClassification:
        text = objective.strip().lower()
        if not text:
            raise ValueError("Task objective is required")
        matches = [category for category, pattern in self.CATEGORY_PATTERNS.items() if re.search(pattern, text)]
        category = matches[0] if matches else "general"
        intent = next((name for name, pattern in self.INTENT_PATTERNS.items() if re.search(pattern, text)), "answer")
        confidence = min(0.98, 0.62 + (0.14 if matches else 0) + (0.08 if len(matches) > 1 else 0) + (0.06 if intent != "answer" else 0))
        domains = matches or ["general"]
        reason = f"Matched {category} task signals with {intent} intent" if matches else "No specialist task signals; using general planning"
        actionable_categories = {"coding", "data", "devops", "filesystem", "vision", "communication", "research"}
        requires_tools = bool(self.TOOL_PATTERN.search(text)) or (category in actionable_categories and intent in {"debug", "create", "modify", "operate", "research"})
        return TaskClassification(category, intent, round(confidence, 2), domains, requires_tools, reason)


class ComplexityAnalyzer:
    ACTION_PATTERN = re.compile(r"\b(add|analy[sz]e|build|change|compare|create|debug|deploy|design|fix|implement|integrate|migrate|refactor|research|run|tests?|testing|update|verify)\b", re.I)
    RISK_PATTERNS = {
        "destructive operation": r"\b(delete|drop|remove|overwrite|reset)\b",
        "production impact": r"\b(production|prod|live system|deploy)\b",
        "security-sensitive": r"\b(authentication|authorization|security|secret|credential|payment)\b",
        "data migration": r"\b(migration|migrate|schema change)\b",
    }

    def analyze(self, objective: str, classification: TaskClassification) -> ComplexityAnalysis:
        text = objective.strip()
        words = text.split()
        score = 1
        factors: list[str] = []
        actions = {match.group(0).lower() for match in self.ACTION_PATTERN.finditer(text)}
        if len(words) > 25:
            score += 1; factors.append("long task description")
        if len(words) > 70:
            score += 1; factors.append("high requirement density")
        if len(actions) > 1:
            added = min(2, len(actions) - 1); score += added; factors.append("multiple requested actions")
        connectors = len(re.findall(r"\b(and then|then|after|before|while|and|also)\b", text, re.I))
        if connectors:
            score += min(2, connectors); factors.append("multi-step wording")
        if len(classification.domains) > 1:
            score += min(2, len(classification.domains) - 1); factors.append("cross-domain work")
        if classification.requires_tools:
            score += 1; factors.append("external tools or workspace access")
        if re.search(r"\b(must|without|ensure|only|except|constraint|compatible|backward)\b", text, re.I):
            score += 1; factors.append("explicit constraints")
        risks = [name for name, pattern in self.RISK_PATTERNS.items() if re.search(pattern, text, re.I)]
        if risks:
            score += min(2, len(risks)); factors.append("risk-sensitive changes")
        score = max(1, min(score, 10))
        if score <= 3:
            level, estimated = "simple", 1
        elif score <= 6:
            level, estimated = "moderate", 3
        else:
            level, estimated = "complex", 5
        return ComplexityAnalysis(level, score, estimated, factors or ["single focused request"], risks)


class ToolRequirementDetector:
    """Map task signals to concrete MCP servers, tools, access, and setup needs."""

    RULES = (
        ("aios-github", r"\bgithub|pull requests?|github issues?\b", ["github_repository", "github_issues", "github_pull_requests"], "read", ["GITHUB_TOKEN for private repositories"]),
        ("aios-git", r"\b(git|commit|branch|diff|repository history)\b", ["git_status", "git_diff", "git_log"], "read", []),
        ("aios-docker", r"\b(docker|containers?|docker images?)\b", ["docker_containers", "docker_inspect", "docker_logs"], "read", ["Docker CLI and daemon"]),
        ("aios-kubernetes", r"\b(kubernetes|k8s|kubectl|pods?|namespaces?)\b", ["kubernetes_resources", "kubernetes_describe", "kubernetes_logs"], "read", ["kubectl and an authenticated context"]),
        ("aios-cloud", r"\b(aws|azure|gcp|google cloud|cloud resources?|s3 buckets?)\b", ["cloud_providers", "cloud_inspect"], "read", ["Authenticated provider CLI"]),
        ("aios-postgresql", r"\b(postgres|postgresql)\b", ["postgres_tables", "postgres_columns", "postgres_query"], "read", ["DATABASE_URL"]),
        ("aios-sqlite", r"\bsqlite\b", ["sqlite_tables", "sqlite_query"], "read", ["AIOS_SQLITE_PATH"]),
        ("aios-redis", r"\bredis\b", ["redis_keys", "redis_get", "redis_stats"], "read", ["REDIS_URL"]),
        ("aios-productivity", r"\b(slack|notion|channel history)\b", ["slack_channels", "slack_history", "notion_search", "notion_page"], "read", ["SLACK_BOT_TOKEN or NOTION_TOKEN"]),
        ("aios-ocr", r"\b(ocr|scanned (?:image|pdf)|extract text from (?:an? )?(?:image|scan))\b", ["extract_text"], "read", ["Tesseract or AIOS_OCR_COMMAND"]),
        ("aios-image", r"\b(resize|crop|convert|inspect)\b.*\b(image|photo|png|jpe?g|webp)\b", ["image_info", "transform_image"], "write", ["AIOS_MCP_IMAGE_WRITE=true for output"]),
        ("aios-rest", r"\b(rest api|api endpoint|http (?:get|post|put|patch|delete)|call (?:an? )?api)\b", ["request_api"], "network", ["AIOS_MCP_REST_HOSTS when host restriction is desired"]),
        ("aios-browser", r"https?://|\b(browse|web page|website|web search|latest|online sources?)\b", ["browse_url", "page_links"], "network", []),
        ("aios-custom", r"\b(custom mcp|external mcp|third[- ]party mcp)\b", ["custom_servers", "custom_tools", "custom_call"], "execute", ["AIOS_MCP_CUSTOM_ENABLED=true"]),
        ("aios-python", r"\b(calculate|equation|statistics|data analysis|simulate|matrix)\b|\d\s*[+*/^=]\s*\d", ["run_python"], "execute", []),
        ("aios-terminal", r"\b(run|execute)\b.*\b(command|tests?|test suite|build|lint|formatter)\b|\b(pytest|npm test|unittest)\b", ["run_command"], "execute", ["Command must be allowlisted"]),
        ("aios-filesystem", r"\b(files?|folders?|director(?:y|ies)|workspace|source code|codebase|repository|implement|refactor|bug)\b", ["list_files", "read_file", "search_text", "write_file"], "write", ["AIOS_MCP_FILESYSTEM_WRITE=true for changes"]),
    )

    CATEGORY_DEFAULTS = {
        "coding": ("aios-filesystem", ["list_files", "read_file", "search_text", "write_file"], "write", ["AIOS_MCP_FILESYSTEM_WRITE=true for changes"]),
        "filesystem": ("aios-filesystem", ["list_files", "read_file", "search_text", "write_file"], "write", ["AIOS_MCP_FILESYSTEM_WRITE=true for changes"]),
        "research": ("aios-browser", ["browse_url", "page_links"], "network", []),
        "data": ("aios-postgresql", ["postgres_tables", "postgres_columns", "postgres_query"], "read", ["DATABASE_URL"]),
        "devops": ("aios-terminal", ["run_command"], "execute", ["Command must be allowlisted"]),
        "communication": ("aios-productivity", ["slack_channels", "notion_search"], "read", ["SLACK_BOT_TOKEN or NOTION_TOKEN"]),
        "math": ("aios-python", ["run_python"], "execute", []),
        "vision": ("aios-image", ["image_info"], "read", []),
    }

    def detect(self, objective: str, classification: TaskClassification, context: dict[str, Any] | None = None) -> list[ToolRequirement]:
        context = context or {}
        available_value = context.get("available_mcp_servers")
        available = set(available_value) if isinstance(available_value, list) else None
        found: dict[str, ToolRequirement] = {}
        for server, pattern, tools, access, configuration in self.RULES:
            if re.search(pattern, objective, re.I):
                found[server] = ToolRequirement(server, tools, f"Task explicitly references capabilities provided by {server}", access, True, None if available is None else server in available, configuration)
        if classification.requires_tools and classification.category in self.CATEGORY_DEFAULTS:
            server, tools, access, configuration = self.CATEGORY_DEFAULTS[classification.category]
            if not found or classification.category in {"coding", "filesystem"}:
                found.setdefault(server, ToolRequirement(server, tools, f"{classification.category} tasks require this workspace capability", access, True, None if available is None else server in available, configuration))
        return list(found.values())


class DependencyEstimator:
    """Validate subtask dependencies and calculate topological execution batches."""

    def estimate(self, subtasks: list[PlannedSubtask]) -> tuple[list[PlannedSubtask], DependencyGraph]:
        identifiers = [item.id for item in subtasks]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Subtask IDs must be unique")
        known = set(identifiers)
        updated: list[PlannedSubtask] = []
        dependencies: dict[str, list[str]] = {}
        for index, item in enumerate(subtasks):
            inferred = list(dict.fromkeys(item.dependencies))
            if item.id in inferred or any(dependency not in known for dependency in inferred):
                raise ValueError(f"Invalid dependencies for {item.id}")
            dependencies[item.id] = inferred
            updated.append(replace(item, dependencies=inferred))
        remaining = set(identifiers)
        resolved: set[str] = set()
        batches: list[list[str]] = []
        while remaining:
            ready = [identifier for identifier in identifiers if identifier in remaining and set(dependencies[identifier]) <= resolved]
            if not ready:
                return updated, DependencyGraph(dependencies, batches, True)
            batches.append(ready)
            resolved.update(ready)
            remaining.difference_update(ready)
        return updated, DependencyGraph(dependencies, batches, False)


class SubtaskGenerator:
    TOOLS = {
        "coding": ["aios-filesystem", "aios-git", "aios-terminal"],
        "filesystem": ["aios-filesystem"],
        "research": ["aios-browser"],
        "data": ["aios-postgresql", "aios-sqlite", "aios-redis"],
        "devops": ["aios-docker", "aios-kubernetes", "aios-cloud"],
        "vision": ["aios-image", "aios-ocr"],
        "communication": ["aios-productivity"],
        "math": ["aios-python"],
        "reasoning": [],
        "general": [],
    }

    TEMPLATES = {
        "debug": [
            ("Reproduce and inspect", "Reproduce the reported behavior and collect the relevant evidence.", "The failure is reproducible or its triggering conditions are documented."),
            ("Identify the root cause", "Trace the behavior to the smallest supported root cause.", "The explanation accounts for the observed symptoms."),
            ("Implement the correction", "Apply the smallest complete correction while preserving existing behavior.", "The root cause is addressed by the implementation."),
            ("Verify the correction", "Run focused checks and relevant regression tests.", "The original failure and related regressions pass."),
            ("Review the result", "Review the final changes, risks, and user-facing impact.", "No unresolved required work or unexpected changes remain."),
        ],
        "research": [
            ("Define the research scope", "Identify the exact question, decision criteria, and freshness requirements.", "The research question and comparison criteria are explicit."),
            ("Gather authoritative evidence", "Collect relevant evidence from primary or authoritative sources.", "Every material claim has suitable evidence."),
            ("Compare and synthesize", "Evaluate the evidence against the decision criteria.", "Trade-offs and disagreements are represented accurately."),
            ("Produce the answer", "Present a concise conclusion with citations and limitations.", "The response answers the objective and supports its claims."),
            ("Check completeness", "Check source quality, recency, and missing information.", "No important evidence gap is left unstated."),
        ],
        "default": [
            ("Inspect requirements and context", "Confirm the objective, relevant context, constraints, and existing state.", "The implementation scope and constraints are understood."),
            ("Design the solution", "Choose a concrete approach and identify affected components.", "The approach covers the objective without unnecessary scope."),
            ("Implement the task", "Carry out the requested work using the relevant tools and context.", "The requested behavior is implemented completely."),
            ("Verify the result", "Run proportional checks against requirements and regressions.", "Relevant checks pass and requirements are demonstrably met."),
            ("Review and hand off", "Review for completeness, risks, and clear handoff information.", "The result is ready for use with remaining limitations stated."),
        ],
    }

    def generate(self, objective: str, classification: TaskClassification, complexity: ComplexityAnalysis, tool_requirements: list[ToolRequirement] | None = None) -> list[PlannedSubtask]:
        detected_tools = [requirement.server for requirement in (tool_requirements or []) if requirement.required]
        if complexity.level == "simple":
            return [PlannedSubtask(
                "step-1", "Complete the focused task", objective.strip(), classification.category, [],
                detected_tools,
                "The objective is answered or completed and the result is checked.",
            )]
        template_key = "research" if classification.category == "research" or classification.intent == "research" else "debug" if classification.intent == "debug" else "default"
        template = self.TEMPLATES[template_key]
        count = complexity.estimated_subtasks
        if count == 3:
            if template_key == "debug":
                template = [
                    template[0],
                    ("Identify and correct the root cause", f"{template[1][1]} {template[2][1]}", template[2][2]),
                    template[3],
                ]
            elif template_key == "research":
                template = [
                    template[0],
                    ("Gather and synthesize evidence", f"{template[1][1]} {template[2][1]}", template[2][2]),
                    template[3],
                ]
            else:
                template = [template[0], template[2], template[3]]
        tools = detected_tools
        subtasks: list[PlannedSubtask] = []
        for index, (title, description, success) in enumerate(template[:count], 1):
            identifier = f"step-{index}"
            dependencies = [f"step-{index - 1}"] if index > 1 else []
            subtasks.append(PlannedSubtask(identifier, title, description, classification.category, dependencies, tools, success))
        return subtasks


class PlannerAgent:
    """Create deterministic structured plans for downstream AIOS agents."""

    def __init__(self, classifier: TaskClassifier | None = None, analyzer: ComplexityAnalyzer | None = None, generator: SubtaskGenerator | None = None, tool_detector: ToolRequirementDetector | None = None, dependency_estimator: DependencyEstimator | None = None) -> None:
        self.classifier = classifier or TaskClassifier()
        self.analyzer = analyzer or ComplexityAnalyzer()
        self.generator = generator or SubtaskGenerator()
        self.tool_detector = tool_detector or ToolRequirementDetector()
        self.dependency_estimator = dependency_estimator or DependencyEstimator()

    def plan(self, objective: str, context: dict[str, Any] | None = None) -> TaskPlan:
        objective = objective.strip()
        if not objective:
            raise ValueError("Task objective is required")
        if len(objective) > 8_000:
            raise ValueError("Task objective must not exceed 8000 characters")
        safe_context = dict(context or {})
        classification = self.classifier.classify(objective)
        complexity = self.analyzer.analyze(objective, classification)
        tool_requirements = self.tool_detector.detect(objective, classification, safe_context)
        subtasks = self.generator.generate(objective, classification, complexity, tool_requirements)
        subtasks, dependency_graph = self.dependency_estimator.estimate(subtasks)
        canonical_context = json.dumps(safe_context, sort_keys=True, separators=(",", ":"), default=str)
        fingerprint = sha256((objective + canonical_context).encode("utf-8")).hexdigest()[:16]
        return TaskPlan(f"plan-{fingerprint}", objective, classification, complexity, tool_requirements, subtasks, dependency_graph, safe_context)

    def plan_dict(self, objective: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.plan(objective, context).to_dict()
