import os
os.environ.setdefault("AIOS_VECTOR_BACKEND", "json")
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from app.llm import gemini_models_to_try, parse_chat_completion_stream_event, parse_gemini_stream_event
from app.model_router import EnvironmentModelRouter
from app.usage import UsageTracker
from app.migrate import migration_files
from app.postgres_store import PostgreSQLConversationStore
from app.storage import create_store
from app.redis_state import NullRedisState, RedisState, create_redis_state
from app.vector_store import JsonVectorStore, QdrantVectorStore
from app.mcp.filesystem_tools import WorkspaceFilesystem
from app.mcp.python_tools import python_package_info, run_restricted_python
from app.mcp.router import MCPRouter
from app.mcp.browser_tools import validate_public_url
from app.mcp.docker_tools import _safe_name
from app.mcp.git_tools import GitInspector
from app.mcp.github_tools import GitHubReader
from app.mcp.terminal_tools import run_terminal
from app.mcp.sql_tools import validate_read_only_sql
from app.mcp.sqlite_tools import SQLiteReader
from app.mcp.kubernetes_tools import _safe as safe_kubernetes_name
from app.mcp.cloud_tools import CloudReader
from app.mcp.custom_tools import CustomMCPRegistry
from app.mcp.image_tools import ImageProcessor
from app.mcp.ocr_tools import OCRReader
from app.mcp.productivity_tools import ProductivityReader
from app.mcp.rest_tools import validate_rest_request
from app.agents.planner import (
    ComplexityAnalyzer,
    DependencyEstimator,
    PlannedSubtask,
    PlannerAgent,
    TaskClassifier,
    ToolRequirementDetector,
)
from app.agents.orchestrator import DecisionRouter, LangGraphOrchestrator
from app.agents.specialists import (
    BrowserAgent,
    CodingAgent,
    DatabaseAgent,
    FilesystemAgent,
    MemoryAgent,
    RAGAgent,
    ReflectionAgent,
    ReviewerAgent,
    SpecialistAgentRegistry,
    TerminalAgent,
    ToolAgent,
    VisionAgent,
)
from app.main import (
    artifact_category,
    browser_results_context_text,
    build_context_messages,
    compact_conversations,
    compress_context_text,
    conversation_messages_for_llm,
    count_message_tokens,
    chunk_document_text,
    clean_extracted_text,
    add_citations_to_results,
    developer_instructions_context_text,
    document_metadata_for_upload,
    estimate_tokens,
    extract_pdf_text_basic,
    extract_pdf_text_pymupdf,
    fit_messages_to_token_window,
    generate_embedding,
    git_status_context_text,
    github_answer_text,
    github_context_text,
    github_repository_reference,
    hybrid_retrieve,
    iter_stream_chunks,
    load_artifacts,
    load_vector_records,
    long_term_memory_context_text,
    mcp_outputs_context_text,
    open_files_context_text,
    parse_json_body,
    parse_multipart_files,
    project_context_text,
    python_mcp_answer_text,
    rank_context_sections,
    remove_duplicate_context_sections,
    related_conversations,
    retrieved_context_text,
    rerank_results,
    running_task_state_context_text,
    safe_filename,
    select_top_k,
    short_term_memory_context_text,
    similar_documents,
    usable_extracted_text,
    save_artifacts,
    semantic_search,
    terminal_output_context_text,
    upsert_vector_records,
    uploaded_files_context_text,
    user_preferences_context_text,
    vector_record_for_message,
    vector_records_for_artifact,
    vector_records_for_long_term_memory,
)
from app.store import ConversationStore


class ParseJsonBodyTests(unittest.TestCase):
    def test_empty_body_defaults_to_empty_dict(self) -> None:
        self.assertEqual(parse_json_body(""), {})

    def test_valid_json_is_parsed(self) -> None:
        self.assertEqual(parse_json_body('{"message": "hello"}'), {"message": "hello"})

    def test_invalid_json_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            parse_json_body("{not valid json}")

    def test_form_encoded_body_is_parsed(self) -> None:
        self.assertEqual(parse_json_body("message=Hello&stream=true"), {"message": "Hello", "stream": "true"})


class StreamingParserTests(unittest.TestCase):
    def test_chat_completion_stream_event_extracts_delta_text(self) -> None:
        event = '{"choices":[{"delta":{"content":"hello"}}]}'
        self.assertEqual(parse_chat_completion_stream_event(event, "groq"), "hello")

    def test_chat_completion_stream_event_allows_empty_delta(self) -> None:
        event = '{"choices":[{"delta":{"role":"assistant"}}]}'
        self.assertEqual(parse_chat_completion_stream_event(event, "groq"), "")

    def test_gemini_stream_event_extracts_text_parts(self) -> None:
        event = '{"candidates":[{"content":{"parts":[{"text":"hello "},{"text":"there"}]}}]}'
        self.assertEqual(parse_gemini_stream_event(event, "gemini-2.0-flash"), "hello there")

    def test_gemini_stream_event_allows_empty_parts(self) -> None:
        event = '{"candidates":[{"content":{"parts":[]}}]}'
        self.assertEqual(parse_gemini_stream_event(event, "gemini-2.0-flash"), "")


class GeminiModelFallbackTests(unittest.TestCase):
    def test_default_gemini_model_is_current(self) -> None:
        old_value = os.environ.pop("AIOS_GEMINI_MODEL", None)
        old_default = os.environ.pop("AIOS_DEFAULT_MODEL", None)
        try:
            self.assertEqual(gemini_models_to_try()[0], "gemini-2.0-flash")
        finally:
            if old_value is not None:
                os.environ["AIOS_GEMINI_MODEL"] = old_value
            if old_default is not None:
                os.environ["AIOS_DEFAULT_MODEL"] = old_default


class ModelRouterTests(unittest.TestCase):
    def test_router_classifies_supported_task_types(self) -> None:
        router = EnvironmentModelRouter()
        examples = {
            "coding": "Debug this Python function",
            "reasoning": "Analyze the trade-offs in this strategy",
            "vision": "Describe this screenshot",
            "math": "Calculate 12 * 14",
            "research": "Research papers and provide citations",
            "general": "Hello, how are you?",
        }
        for expected, message in examples.items():
            with self.subTest(expected=expected):
                self.assertEqual(router.classify([{"role": "user", "content": message}]), expected)

    def test_task_provider_and_model_overrides_are_resolved(self) -> None:
        old_provider = os.environ.get("AIOS_CODING_PROVIDER")
        old_model = os.environ.get("AIOS_CODING_GROQ_MODEL")
        try:
            os.environ["AIOS_CODING_PROVIDER"] = "groq"
            os.environ["AIOS_CODING_GROQ_MODEL"] = "coding-model"
            routes = EnvironmentModelRouter().routes(
                [{"role": "user", "content": "Write Python code"}], ["groq", "gemini"]
            )
            self.assertEqual((routes[0].task, routes[0].provider, routes[0].model), ("coding", "groq", "coding-model"))
        finally:
            if old_provider is None:
                os.environ.pop("AIOS_CODING_PROVIDER", None)
            else:
                os.environ["AIOS_CODING_PROVIDER"] = old_provider
            if old_model is None:
                os.environ.pop("AIOS_CODING_GROQ_MODEL", None)
            else:
                os.environ["AIOS_CODING_GROQ_MODEL"] = old_model


class UsageTrackerTests(unittest.TestCase):
    def test_usage_is_persisted_and_summarized(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tracker = UsageTracker(os.path.join(temp_dir, "usage.json"))
            entry = tracker.record(
                "groq", "test-model", "coding", [{"role": "user", "content": "hello"}], "world"
            )
            summary = tracker.summary()
            self.assertEqual(summary["requests"], 1)
            self.assertEqual(summary["by_provider"]["groq"]["requests"], 1)
            self.assertEqual(summary["total_tokens"], entry["total_tokens"])


class PostgreSQLMigrationTests(unittest.TestCase):
    def test_initial_migration_defines_required_tables_and_relationships(self) -> None:
        files = migration_files()
        self.assertTrue(files)
        sql = files[0].read_text(encoding="utf-8").lower()
        for table in ("users", "sessions", "chats"):
            self.assertIn(f"create table if not exists {table}", sql)
        self.assertIn("user_id uuid references users(id)", sql)
        self.assertIn("session_id uuid references sessions(id)", sql)
        self.assertIn("create unique index if not exists users_email_lower_unique", sql)

    def test_second_migration_defines_project_file_setting_and_api_key_tables(self) -> None:
        files = migration_files()
        self.assertGreaterEqual(len(files), 2)
        sql = files[1].read_text(encoding="utf-8").lower()
        for table in ("projects", "files", "settings", "api_keys"):
            self.assertIn(f"create table if not exists {table}", sql)
        self.assertIn("project_id uuid references projects(id)", sql)
        self.assertIn("chat_id uuid references chats(id)", sql)
        self.assertIn("encrypted_secret bytea not null", sql)
        self.assertNotIn("api_key text", sql)

    def test_third_migration_defines_structured_logs_and_analytics(self) -> None:
        files = migration_files()
        self.assertGreaterEqual(len(files), 3)
        sql = files[2].read_text(encoding="utf-8").lower()
        for table in ("logs", "analytics"):
            self.assertIn(f"create table if not exists {table}", sql)
        self.assertIn("context jsonb not null", sql)
        self.assertIn("properties jsonb not null", sql)
        self.assertIn("estimated_cost_usd numeric", sql)
        self.assertIn("logs_created_at_idx", sql)
        self.assertIn("analytics_event_time_idx", sql)


class StorageBackendTests(unittest.TestCase):
    def test_postgres_store_serializes_uuid_and_timestamp_rows(self) -> None:
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        row = {"id": __import__("uuid").uuid4(), "session_id": None, "created_at": now}
        converted = PostgreSQLConversationStore._chat_from_row(row)
        self.assertIsInstance(converted["id"], str)
        self.assertEqual(converted["created_at"], now.isoformat())

    def test_json_backend_can_be_forced(self) -> None:
        old_backend = os.environ.get("AIOS_STORAGE_BACKEND")
        try:
            os.environ["AIOS_STORAGE_BACKEND"] = "json"
            self.assertIs(type(create_store()), ConversationStore)
        finally:
            if old_backend is None:
                os.environ.pop("AIOS_STORAGE_BACKEND", None)
            else:
                os.environ["AIOS_STORAGE_BACKEND"] = old_backend


class _FakeRedis:
    def __init__(self) -> None:
        self.values = {}
        self.expirations = {}
        self.counters = {}

    def ping(self): return True
    def setex(self, key, ttl, value):
        self.values[key], self.expirations[key] = value, ttl
        return True
    def get(self, key): return self.values.get(key)
    def expire(self, key, ttl):
        self.expirations[key] = ttl
        return key in self.values
    def delete(self, *keys):
        count = sum(key in self.values for key in keys)
        for key in keys: self.values.pop(key, None)
        return count
    def eval(self, script, key_count, key, window):
        self.counters[key] = self.counters.get(key, 0) + 1
        return [self.counters[key], int(window)]


class RedisStateTests(unittest.TestCase):
    def test_invalid_managed_redis_url_falls_back_without_crashing(self) -> None:
        with mock.patch.dict(os.environ, {"REDIS_URL": "https://example.upstash.io"}, clear=False):
            state = create_redis_state()
        self.assertIsInstance(state, NullRedisState)

    def test_active_sessions_use_namespaced_json_and_ttl(self) -> None:
        client = _FakeRedis()
        state = RedisState(client, "test")
        self.assertTrue(state.set_active_session("session-1", {"id": "session-1"}))
        self.assertEqual(state.get_active_session("session-1"), {"id": "session-1"})
        self.assertEqual(client.expirations["test:session:session-1"], state.session_ttl)

    def test_cache_round_trip_and_delete(self) -> None:
        client = _FakeRedis()
        state = RedisState(client, "test")
        state.cache_set("answer", {"value": 42})
        self.assertEqual(state.cache_get("answer"), {"value": 42})
        self.assertTrue(state.cache_delete("answer"))
        self.assertIsNone(state.cache_get("answer"))

    def test_stream_state_round_trip(self) -> None:
        state = RedisState(_FakeRedis(), "test")
        state.set_stream_state("chat-1", {"status": "running"})
        self.assertEqual(state.get_stream_state("chat-1")["status"], "running")

    def test_temporary_memory_round_trip_renews_ttl(self) -> None:
        client = _FakeRedis()
        state = RedisState(client, "test")
        state.set_temporary_memory("chat-1", {"task": "debug"})
        memory = state.get_temporary_memory("chat-1")
        self.assertEqual(memory["task"], "debug")
        self.assertIn("cached_at", memory)
        self.assertEqual(client.expirations["test:memory:chat-1"], state.memory_ttl)

    def test_rate_limit_blocks_after_limit_and_hashes_identity(self) -> None:
        client = _FakeRedis()
        state = RedisState(client, "test")
        self.assertTrue(state.rate_limit("private-user-id", 2, 60)["allowed"])
        self.assertTrue(state.rate_limit("private-user-id", 2, 60)["allowed"])
        limited = state.rate_limit("private-user-id", 2, 60)
        self.assertFalse(limited["allowed"])
        self.assertEqual(limited["remaining"], 0)
        self.assertTrue(all("private-user-id" not in key for key in client.counters))


class VectorStoreTests(unittest.TestCase):
    def test_json_vector_store_upserts_and_replaces_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JsonVectorStore(Path(temp_dir) / "vectors.json", "test", 8)
            store.upsert([{"id": "d1", "source_type": "document", "embedding": [0.0] * 8}])
            store.upsert([{"id": "m1", "source_type": "memory", "embedding": [1.0] * 8}])
            store.replace_source("memory", [{"id": "m2", "source_type": "memory", "embedding": [0.5] * 8}])
            self.assertEqual({item["id"] for item in store.load()}, {"d1", "m2"})


    def test_qdrant_collection_creation_tolerates_concurrent_creator(self) -> None:
        class RacingClient:
            def __init__(self):
                self.exists_checks = 0

            def collection_exists(self, collection):
                self.exists_checks += 1
                return self.exists_checks > 1

            def create_collection(self, **kwargs):
                raise RuntimeError("collection already exists")

            def create_payload_index(self, *args, **kwargs):
                return None

        store = QdrantVectorStore.__new__(QdrantVectorStore)
        store.client = RacingClient()
        store.collection = "test"
        store.dimensions = 8
        store._ensure_collection()
        self.assertEqual(store.client.exists_checks, 2)

class PlannerAgentTests(unittest.TestCase):
    def test_classifier_identifies_category_intent_and_tool_requirement(self) -> None:
        result = TaskClassifier().classify("Fix the PostgreSQL query bug and run tests")
        self.assertEqual(result.category, "data")
        self.assertEqual(result.intent, "debug")
        self.assertTrue(result.requires_tools)
        self.assertIn("coding", result.domains)

    def test_complexity_analysis_distinguishes_focused_and_cross_domain_work(self) -> None:
        classifier = TaskClassifier()
        analyzer = ComplexityAnalyzer()
        simple = classifier.classify("Explain recursion")
        self.assertEqual(analyzer.analyze("Explain recursion", simple).level, "simple")
        objective = "Migrate the production PostgreSQL authentication schema, update the API, add tests, and deploy it without downtime"
        complex_classification = classifier.classify(objective)
        result = analyzer.analyze(objective, complex_classification)
        self.assertEqual(result.level, "complex")
        self.assertIn("production impact", result.risk_flags)
        self.assertIn("security-sensitive", result.risk_flags)

    def test_planner_generates_dependency_aware_verifiable_subtasks(self) -> None:
        plan = PlannerAgent().plan("Fix the API bug and run the test suite")
        self.assertEqual(plan.classification.intent, "debug")
        self.assertEqual(len(plan.subtasks), 3)
        self.assertEqual(plan.subtasks[1].dependencies, ["step-1"])
        self.assertEqual(plan.subtasks[2].dependencies, ["step-2"])
        self.assertIn("aios-filesystem", plan.subtasks[0].suggested_tools)
        self.assertTrue(all(item.success_criteria for item in plan.subtasks))

    def test_planner_is_deterministic_and_preserves_context(self) -> None:
        planner = PlannerAgent()
        context = {"project": "AIOS", "active_file": "app/main.py"}
        first = planner.plan("Implement a Python function", context)
        second = planner.plan("Implement a Python function", context)
        self.assertEqual(first.id, second.id)
        self.assertEqual(first.context, context)
        self.assertEqual(first.to_dict()["classification"]["category"], "coding")

    def test_planner_rejects_empty_or_oversized_objectives(self) -> None:
        planner = PlannerAgent()
        with self.assertRaises(ValueError): planner.plan("  ")
        with self.assertRaises(ValueError): planner.plan("x" * 8001)

    def test_tool_detector_returns_specific_capabilities_and_availability(self) -> None:
        objective = "Inspect Kubernetes pod logs and post a summary to Slack"
        classification = TaskClassifier().classify(objective)
        requirements = ToolRequirementDetector().detect(
            objective,
            classification,
            {"available_mcp_servers": ["aios-kubernetes"]},
        )
        by_server = {item.server: item for item in requirements}
        self.assertIn("kubernetes_logs", by_server["aios-kubernetes"].tools)
        self.assertTrue(by_server["aios-kubernetes"].available)
        self.assertFalse(by_server["aios-productivity"].available)
        self.assertEqual(by_server["aios-productivity"].access, "read")

    def test_dependency_estimator_builds_batches_and_detects_cycles(self) -> None:
        independent = [
            PlannedSubtask("a", "A", "A", "general"),
            PlannedSubtask("b", "B", "B", "general"),
            PlannedSubtask("c", "C", "C", "general", ["a", "b"]),
        ]
        _, graph = DependencyEstimator().estimate(independent)
        self.assertEqual(graph.execution_batches, [["a", "b"], ["c"]])
        self.assertFalse(graph.has_cycle)
        cyclic = [
            PlannedSubtask("a", "A", "A", "general", ["b"]),
            PlannedSubtask("b", "B", "B", "general", ["a"]),
        ]
        _, cyclic_graph = DependencyEstimator().estimate(cyclic)
        self.assertTrue(cyclic_graph.has_cycle)


class LangGraphOrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.orchestrator = LangGraphOrchestrator()

    def test_langgraph_contains_planning_decision_and_route_nodes(self) -> None:
        nodes = set(self.orchestrator.graph.get_graph().nodes)
        self.assertTrue({"plan_task", "decision", "prepare_tools", "direct_response", "blocked"} <= nodes)
        self.assertTrue({"memory_agent", "rag_agent", "browser_agent", "coding_agent", "terminal_agent", "filesystem_agent"} <= nodes)
        self.assertTrue({"retry_decision", "retry_agent", "reviewer_agent", "merge_results"} <= nodes)

    def test_routes_tool_tasks_and_returns_dependency_queue(self) -> None:
        result = self.orchestrator.invoke("Fix the API bug and run tests")
        self.assertEqual(result["route"], "tool_execution")
        self.assertEqual(result["next_node"], "complete")
        self.assertEqual(result["selected_agent"], "coding")
        self.assertEqual(result["agent_output"]["agent"], "coding")
        self.assertEqual(result["trace"], ["plan_task", "decision", "prepare_tools", "agent_dispatch", "coding_agent", "post_reflection", "retry_decision", "reviewer_agent", "merge_results"])
        self.assertEqual(result["reflection"]["output"]["verdict"], "passed")
        self.assertEqual(result["review"]["output"]["verdict"], "approved")
        self.assertEqual(result["final_result"]["attempt_count"], 1)
        self.assertEqual(result["execution_queue"][0], ["step-1"])

    def test_routes_ambiguous_risky_blocked_and_direct_tasks(self) -> None:
        clarification = self.orchestrator.invoke("fix it")
        self.assertEqual(clarification["status"], "awaiting_input")
        approval = self.orchestrator.invoke("Deploy Kubernetes to production")
        self.assertEqual(approval["status"], "awaiting_approval")
        blocked = self.orchestrator.invoke(
            "Browse the website https://example.com",
            {"available_mcp_servers": ["aios-filesystem"]},
        )
        self.assertEqual(blocked["status"], "blocked")
        self.assertIn("aios-browser", blocked["missing_tools"])
        direct = self.orchestrator.invoke("Hello there")
        self.assertEqual(direct["route"], "direct_response")
        self.assertEqual(direct["next_node"], "general_agent")

    def test_router_allows_explicitly_approved_risk(self) -> None:
        plan = PlannerAgent().plan_dict("Deploy Kubernetes to production", {"approved": True})
        decision = DecisionRouter().decide(plan, {"approved": True})
        self.assertEqual(decision["route"], "tool_execution")

    def test_dispatches_memory_and_rag_agents(self) -> None:
        memory = self.orchestrator.invoke("Recall my preferences", {"long_term_memory": {"theme": "dark"}})
        self.assertEqual(memory["selected_agent"], "memory")
        self.assertEqual(memory["agent_output"]["output"]["long_term"]["theme"], "dark")
        rag = self.orchestrator.invoke(
            "Search my uploaded documents for apples",
            {"vector_records": [{"id": "one", "source_type": "document", "filename": "fruit.txt", "text": "apples and pears"}]},
        )
        self.assertEqual(rag["selected_agent"], "rag")
        self.assertEqual(rag["agent_output"]["output"]["citations"][0]["id"], "one")


class SpecialistAgentTests(unittest.TestCase):
    def test_memory_agent_recalls_and_updates_persistent_memory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConversationStore(Path(temp_dir) / "conversations.json")
            conversation = store.create_conversation()
            agent = MemoryAgent(store)
            remembered = agent.execute("remember", {"operation": "remember", "learned_behavior": ["prefers concise replies"]}, {})
            self.assertEqual(remembered["status"], "completed")
            recalled = agent.execute("recall", {"conversation_id": conversation["id"]}, {})
            self.assertIn("prefers concise replies", recalled["output"]["long_term"]["learned_behavior"])

    def test_rag_agent_ranks_records_and_returns_citations(self) -> None:
        records = [
            {"id": "a", "source_type": "document", "filename": "a.txt", "text": "oranges only"},
            {"id": "b", "source_type": "document", "filename": "b.txt", "text": "apples are red fruit"},
        ]
        result = RAGAgent().execute("find apples", {"query": "apples", "top_k": 1}, {"vector_records": records})
        self.assertEqual(result["output"]["results"][0]["id"], "b")
        self.assertEqual(result["output"]["citations"][0]["filename"], "b.txt")

    def test_browser_and_terminal_agents_use_injected_safe_primitives(self) -> None:
        browser = BrowserAgent(fetcher=lambda url, limit: {"url": url, "content": "ok", "limit": limit})
        browsed = browser.execute("browse https://example.com", {}, {})
        self.assertEqual(browsed["output"]["content"], "ok")
        terminal = TerminalAgent(runner=lambda command, args, timeout: {"ok": True, "command": command, "args": args, "timeout": timeout})
        executed = terminal.execute("run", {"command": "rg", "args": ["TODO"], "timeout": 5}, {})
        self.assertTrue(executed["output"]["ok"])

    def test_filesystem_and_coding_agents_execute_scoped_operations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "app.py").write_text("value = 1\n", encoding="utf-8")
            filesystem = WorkspaceFilesystem(root, allow_write=True)
            fs_agent = FilesystemAgent(filesystem)
            found = fs_agent.execute("search", {"operation": "search", "query": "value"}, {})
            self.assertEqual(found["output"][0]["path"], "app.py")
            coding = CodingAgent(filesystem, GitInspector(root), TerminalAgent(runner=lambda command, args, timeout: {"ok": True}))
            changed = coding.execute("update code", {"operation": "apply_changes", "changes": {"app.py": "value = 2\n"}}, {})
            self.assertEqual(changed["status"], "completed")
            self.assertEqual((root / "app.py").read_text(encoding="utf-8"), "value = 2\n")

    def test_registry_converts_agent_errors_to_structured_failures(self) -> None:
        registry = SpecialistAgentRegistry(filesystem=FilesystemAgent(WorkspaceFilesystem(Path.cwd(), allow_write=False)))
        result = registry.execute("filesystem", "write", {"operation": "write", "path": "blocked.txt", "content": "x"}, {})
        self.assertEqual(result["status"], "failed")
        self.assertIn("disabled", result["message"])

    def test_vision_agent_inspects_and_transforms_images(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            Image.new("RGB", (20, 10), "blue").save(root / "source.png")
            processor = ImageProcessor(root, allow_write=True)
            agent = VisionAgent(processor, OCRReader(root))
            info = agent.execute("inspect image", {"operation": "info", "path": "source.png"}, {})
            self.assertEqual(info["output"]["width"], 20)
            transformed = agent.execute("resize image", {"operation": "transform", "path": "source.png", "output_path": "small.png", "width": 10}, {})
            self.assertEqual((transformed["output"]["width"], transformed["output"]["height"]), (10, 5))

    def test_database_agent_uses_read_only_provider_interface(self) -> None:
        class FakeDatabase:
            def tables(self): return [{"name": "notes"}]
            def query(self, sql, parameters, limit): return {"rows": [{"sql": sql}], "row_count": 1}

        agent = DatabaseAgent({"sqlite": FakeDatabase})
        tables = agent.execute("inspect SQLite", {"provider": "sqlite", "operation": "tables"}, {})
        self.assertEqual(tables["output"]["result"][0]["name"], "notes")
        queried = agent.execute("query SQLite", {"provider": "sqlite", "operation": "query", "sql": "SELECT 1"}, {})
        self.assertEqual(queried["output"]["result"]["row_count"], 1)

    def test_tool_agent_invokes_only_registered_tools(self) -> None:
        agent = ToolAgent({"double": lambda value: value * 2})
        result = agent.execute("use tool", {"tool": "double", "arguments": {"value": 4}}, {})
        self.assertEqual(result["output"]["result"], 8)
        registry = SpecialistAgentRegistry(tool=agent)
        blocked = registry.execute("tool", "use tool", {"tool": "unknown"}, {})
        self.assertEqual(blocked["status"], "failed")

    def test_reflection_agent_reviews_failures_and_success_criteria(self) -> None:
        plan = {"subtasks": [{"id": "step-1", "success_criteria": "Tests pass"}]}
        passed = ReflectionAgent().execute("verify", {"agent_output": {"agent": "coding", "status": "completed", "output": {"ok": True}}, "plan": plan}, {})
        self.assertEqual(passed["output"]["verdict"], "passed")
        failed = ReflectionAgent().execute("verify", {"agent_output": {"agent": "terminal", "status": "failed", "output": None}, "plan": plan}, {})
        self.assertEqual(failed["output"]["verdict"], "failed")

    def test_reviewer_agent_approves_success_and_rejects_failure(self) -> None:
        plan = {"subtasks": [{"id": "step-1", "success_criteria": "Tests pass"}]}
        output = {"agent": "coding", "status": "completed", "output": {"tests": "passed"}}
        reflection = ReflectionAgent().execute("verify", {"agent_output": output, "plan": plan}, {})
        approved = ReviewerAgent().execute("verify", {"agent_output": output, "reflection": reflection, "plan": plan}, {})
        self.assertEqual(approved["output"]["verdict"], "approved")
        failed_output = {"agent": "coding", "status": "failed", "output": None}
        failed_reflection = ReflectionAgent().execute("verify", {"agent_output": failed_output, "plan": plan}, {})
        rejected = ReviewerAgent().execute("verify", {"agent_output": failed_output, "reflection": failed_reflection, "plan": plan}, {})
        self.assertEqual(rejected["output"]["verdict"], "rejected")


class NewSpecialistRoutingTests(unittest.TestCase):
    def test_orchestrator_dispatches_vision_database_tool_and_reflection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            Image.new("RGB", (8, 6), "green").save(root / "image.png")

            class FakeDatabase:
                def tables(self): return [{"name": "items"}]

            registry = SpecialistAgentRegistry(
                vision=VisionAgent(ImageProcessor(root, allow_write=False), OCRReader(root)),
                database=DatabaseAgent({"sqlite": FakeDatabase}),
                tool=ToolAgent({"echo": lambda value: value}),
            )
            orchestrator = LangGraphOrchestrator(agents=registry)
            vision = orchestrator.invoke("Inspect this image", {"agent_input": {"operation": "info", "path": "image.png"}})
            self.assertEqual(vision["selected_agent"], "vision")
            database = orchestrator.invoke("Inspect SQLite tables", {"agent_input": {"provider": "sqlite", "operation": "tables"}})
            self.assertEqual(database["selected_agent"], "database")
            tool = orchestrator.invoke("Use a tool", {"agent_input": {"tool": "echo", "arguments": {"value": "ok"}}})
            self.assertEqual(tool["selected_agent"], "tool")
            reflected = orchestrator.invoke("Review the result", {"agent_output": {"agent": "tool", "status": "completed", "output": "ok"}})
            self.assertEqual(reflected["selected_agent"], "reflection")


class RetryAndMergeTests(unittest.TestCase):
    def test_failed_agent_is_retried_and_then_approved(self) -> None:
        class FlakyCodingAgent:
            def __init__(self): self.calls = 0
            def execute(self, objective, payload, context):
                self.calls += 1
                return {"agent": "coding", "status": "failed", "message": "temporary", "output": None} if self.calls == 1 else {"agent": "coding", "status": "completed", "message": "recovered", "output": {"ok": True}}

        flaky = FlakyCodingAgent()
        orchestrator = LangGraphOrchestrator(agents=SpecialistAgentRegistry(coding=flaky))
        result = orchestrator.invoke("Fix the API bug", {"max_retries": 2})
        self.assertEqual(flaky.calls, 2)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["retry_count"], 1)
        self.assertEqual(result["final_result"]["attempt_count"], 2)
        self.assertIn("retry_agent", result["trace"])

    def test_retry_exhaustion_is_rejected(self) -> None:
        class FailingCodingAgent:
            def __init__(self): self.calls = 0
            def execute(self, objective, payload, context):
                self.calls += 1
                return {"agent": "coding", "status": "failed", "message": "still failing", "output": None}

        failing = FailingCodingAgent()
        orchestrator = LangGraphOrchestrator(agents=SpecialistAgentRegistry(coding=failing))
        result = orchestrator.invoke("Fix the API bug", {"max_retries": 2})
        self.assertEqual(failing.calls, 3)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["review"]["output"]["verdict"], "rejected")
        self.assertEqual(result["final_result"]["retry_count"], 2)

    def test_merge_includes_prior_agent_results(self) -> None:
        prior = {"attempt": 0, "agent": "memory", "status": "completed", "message": "context", "output": {"remembered": True}}
        result = LangGraphOrchestrator().invoke("Recall my preferences", {"long_term_memory": {"theme": "dark"}, "agent_results": [prior]})
        self.assertEqual(result["final_result"]["attempt_count"], 2)
        self.assertEqual(result["final_result"]["agent_results"][0]["agent"], "memory")

    def test_invalid_retry_limit_is_rejected(self) -> None:
        with self.assertRaises(ValueError): LangGraphOrchestrator().invoke("Recall memory", {"max_retries": "many"})


class MCPRouterTests(unittest.TestCase):
    def test_classifies_filesystem_and_python_requests(self) -> None:
        router = MCPRouter()
        self.assertEqual(router.classify("read the project file").server, "aios-filesystem")
        self.assertEqual(router.classify("calculate statistics with Python").server, "aios-python")
        self.assertEqual(router.classify("hello there").category, "general")

    def test_filesystem_is_confined_and_protects_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "safe.txt").write_text("hello world", encoding="utf-8")
            filesystem = WorkspaceFilesystem(root)
            self.assertEqual(filesystem.read_file("safe.txt")["content"], "hello world")
            with self.assertRaises(ValueError): filesystem.resolve("../outside.txt", must_exist=False)
            with self.assertRaises(ValueError): filesystem.resolve(".env", must_exist=False)

    def test_filesystem_writes_are_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(PermissionError): WorkspaceFilesystem(temp_dir, allow_write=False).write_file("new.txt", "data")
            result = WorkspaceFilesystem(temp_dir, allow_write=True).write_file("new.txt", "data")
            self.assertEqual(result["bytes_written"], 4)

    def test_python_package_info_is_read_only_and_reports_related_packages(self) -> None:
        result = python_package_info("langchain")
        self.assertEqual(result["source"], "Python importlib.metadata")
        self.assertIn("related_installed_packages", result)
        with self.assertRaises(ValueError):
            python_package_info("../unsafe")

    def test_explicit_python_mcp_package_request_bypasses_llm(self) -> None:
        answer = python_mcp_answer_text("use python mcp tool to give details of langchain")
        self.assertIn("Python MCP package inspection", answer)
        self.assertIn("Top-level package installed: no", answer)
        self.assertIn("langchain-core", answer)

    def test_python_router_selects_package_info(self) -> None:
        route = MCPRouter().classify("use python mcp tool to give details of langchain")
        self.assertEqual(route.category, "python")
        self.assertEqual(route.suggested_tool, "package_info")
    def test_restricted_python_returns_results_and_blocks_imports(self) -> None:
        result = run_restricted_python("values = [1, 2, 3]\nresult = sum(values)")
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"], 6)
        blocked = run_restricted_python("import os\nresult = os.getcwd()")
        self.assertFalse(blocked["ok"])
        self.assertIn("Disallowed syntax", blocked["stderr"])

    def test_router_classifies_new_mcp_categories(self) -> None:
        router = MCPRouter()
        cases = {
            "show docker containers": "docker", "show git status": "git",
            "list GitHub pull requests": "github", "browse https://example.com": "browser",
            "run command rg": "terminal",
        }
        for request, category in cases.items():
            with self.subTest(request=request): self.assertEqual(router.classify(request).category, category)

    def test_browser_blocks_private_networks(self) -> None:
        for url in ("http://localhost/admin", "http://127.0.0.1/", "http://[::1]/"):
            with self.subTest(url=url), self.assertRaises(ValueError): validate_public_url(url)

    def test_terminal_rejects_unlisted_commands(self) -> None:
        with self.assertRaises(PermissionError): run_terminal("powershell", ["-Command", "Get-ChildItem"])

    def test_git_inspector_is_read_only_and_operational(self) -> None:
        result = GitInspector(Path(__file__).resolve().parents[1]).status()
        self.assertTrue(result["ok"])
        self.assertIn("##", result["stdout"])

    def test_github_router_selects_contributors(self) -> None:
        route = MCPRouter().classify("show GitHub contributors")
        self.assertEqual(route.category, "github")
        self.assertEqual(route.suggested_tool, "github_contributors")

    def test_github_reader_returns_contributors_and_recent_pull_request_details(self) -> None:
        reader = GitHubReader()
        reader._get = mock.Mock(
            side_effect=[
                [{"login": "alice", "contributions": 7, "html_url": "https://github.com/alice"}],
                [
                    {
                        "number": 4,
                        "title": "Improve docs",
                        "state": "closed",
                        "html_url": "https://github.com/o/r/pull/4",
                        "draft": False,
                        "user": {"login": "alice"},
                        "created_at": "2026-01-01T00:00:00Z",
                        "updated_at": "2026-01-02T00:00:00Z",
                        "closed_at": "2026-01-02T00:00:00Z",
                        "merged_at": "2026-01-02T00:00:00Z",
                    }
                ],
            ]
        )

        self.assertEqual(reader.contributors("o", "r")[0]["contributions"], 7)
        pull = reader.pull_requests("o", "r", state="all")[0]
        self.assertEqual(pull["author"], "alice")
        self.assertEqual(pull["merged_at"], "2026-01-02T00:00:00Z")
        self.assertEqual(reader._get.call_args_list[1].args[3]["state"], "all")
        self.assertEqual(reader._get.call_args_list[1].args[3]["sort"], "updated")

    def test_github_answer_never_falls_back_to_model_memory_on_api_failure(self) -> None:
        from app import main as main_module

        github = mock.Mock()
        github.repository.side_effect = RuntimeError("temporary GitHub failure")
        with mock.patch.object(main_module, "GITHUB", github):
            answer = github_answer_text(
                "Refer https://github.com/Rohit-24gb/Sustainability-connect and list contributors"
            )

        self.assertIn("could not retrieve live data", answer)
        self.assertIn("will not answer from cached conversation memory", answer)
    def test_github_answer_is_deterministic_and_reports_empty_pull_requests(self) -> None:
        from app import main as main_module

        github = mock.Mock()
        github.repository.return_value = {
            "full_name": "Rohit-24gb/Sustainability-connect",
            "html_url": "https://github.com/Rohit-24gb/Sustainability-connect",
        }
        github.contributors.return_value = [
            {"login": "Rohit-24gb", "contributions": 62, "url": "https://github.com/Rohit-24gb"},
            {"login": "Suryakant7679", "contributions": 9, "url": "https://github.com/Suryakant7679"},
        ]
        github.pull_requests.return_value = []

        with mock.patch.object(main_module, "GITHUB", github):
            answer = github_answer_text(
                "Refer https://github.com/Rohit-24gb/Sustainability-connect and list contributors and pull requests"
            )

        self.assertIn("Rohit-24gb", answer)
        self.assertIn("62 contributions", answer)
        self.assertIn("Suryakant7679", answer)
        self.assertIn("No open, closed, or merged pull requests were found.", answer)
        self.assertNotIn("Abhishek-24gb", answer)
    def test_live_github_context_uses_requested_repository_data(self) -> None:
        from app import main as main_module

        github = mock.Mock()
        github.repository.return_value = {
            "full_name": "Rohit-24gb/Sustainability-connect",
            "html_url": "https://github.com/Rohit-24gb/Sustainability-connect",
        }
        github.contributors.return_value = [
            {"login": "Rohit-24gb", "contributions": 62, "url": "https://github.com/Rohit-24gb"}
        ]
        github.pull_requests.return_value = []

        with mock.patch.object(main_module, "GITHUB", github):
            context = github_context_text(
                "Refer https://github.com/Rohit-24gb/Sustainability-connect and list contributors and recent pull requests"
            )

        self.assertIn("Live GitHub MCP results", context)
        self.assertIn("Rohit-24gb", context)
        self.assertIn('"pull_requests": []', context)
        github.pull_requests.assert_called_once_with(
            "Rohit-24gb", "Sustainability-connect", state="all", sort="updated", direction="desc"
        )
        self.assertEqual(
            github_repository_reference("https://github.com/Rohit-24gb/Sustainability-connect"),
            ("Rohit-24gb", "Sustainability-connect"),
        )
    def test_github_and_docker_names_are_validated(self) -> None:
        with self.assertRaises(ValueError): GitHubReader().repository("bad/name", "repo")
        with self.assertRaises(ValueError): _safe_name("--dangerous-option")

    def test_router_classifies_database_and_kubernetes_requests(self) -> None:
        router = MCPRouter()
        cases = {"show Kubernetes pods": "kubernetes", "query PostgreSQL": "postgresql", "inspect SQLite": "sqlite", "list Redis keys": "redis"}
        for request, category in cases.items():
            with self.subTest(request=request): self.assertEqual(router.classify(request).category, category)

    def test_router_classifies_checkpoint_ten_integrations(self) -> None:
        router = MCPRouter()
        cases = {
            "list AWS cloud resources": "cloud",
            "search Notion workspace": "productivity",
            "call REST API endpoint": "rest",
            "OCR this scanned PDF": "ocr",
            "resize this image": "image",
            "use a custom MCP server": "custom",
        }
        for request, category in cases.items():
            with self.subTest(request=request): self.assertEqual(router.classify(request).category, category)

    def test_cloud_and_productivity_inputs_are_validated(self) -> None:
        with self.assertRaises(ValueError): CloudReader().inspect("unknown")
        reader = ProductivityReader(slack_token="token", notion_token="token")
        with self.assertRaises(ValueError): reader.slack_history("bad channel!")
        with self.assertRaises(ValueError): reader.notion_page("not-a-page-id")

    def test_rest_mcp_blocks_mutations_and_private_networks(self) -> None:
        with mock.patch.dict(os.environ, {"AIOS_MCP_REST_WRITE": "false"}):
            with self.assertRaises(PermissionError): validate_rest_request("POST", "https://example.com")
        with self.assertRaises(ValueError): validate_rest_request("GET", "http://127.0.0.1/private")

    def test_image_processing_is_workspace_confined_and_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            Image.new("RGB", (20, 10), "red").save(root / "source.png")
            self.assertEqual(ImageProcessor(root).info("source.png")["width"], 20)
            with self.assertRaises(PermissionError): ImageProcessor(root, allow_write=False).transform("source.png", "out.png", width=10)
            result = ImageProcessor(root, allow_write=True).transform("source.png", "out.webp", width=10)
            self.assertEqual((result["width"], result["height"]), (10, 5))
            with self.assertRaises(ValueError): ImageProcessor(root).info("../outside.png")

    def test_ocr_validates_workspace_paths_and_types(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "notes.txt").write_text("not an image", encoding="utf-8")
            reader = OCRReader(root)
            with self.assertRaises(ValueError): reader.extract("notes.txt")
            with self.assertRaises(ValueError): reader.extract("../outside.png")

    def test_custom_mcp_config_is_validated_and_execution_is_opt_in(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            config = Path(temp_dir) / "servers.json"
            config.write_text('{"mcpServers":{"demo":{"command":"python","args":["-m","demo"],"cwd":"' + str(Path(temp_dir)).replace('\\', '\\\\') + '"}}}', encoding="utf-8")
            registry = CustomMCPRegistry(config, enabled=False)
            self.assertEqual(registry.list_servers()[0]["name"], "demo")
            with self.assertRaises(PermissionError): registry._parameters("demo")

    def test_sql_validator_blocks_mutations_and_multiple_statements(self) -> None:
        self.assertEqual(validate_read_only_sql("SELECT 1;"), "SELECT 1")
        for query in ("DELETE FROM users", "SELECT 1; DROP TABLE users"):
            with self.subTest(query=query), self.assertRaises((PermissionError, ValueError)): validate_read_only_sql(query)

    def test_sqlite_reader_opens_database_read_only(self) -> None:
        import sqlite3
        from contextlib import closing
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            path = Path(temp_dir) / "test.db"
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("CREATE TABLE notes (id INTEGER, text TEXT)")
                connection.execute("INSERT INTO notes VALUES (1, 'hello')")
                connection.commit()
            reader = SQLiteReader(path)
            self.assertEqual(reader.query("SELECT * FROM notes")["rows"][0]["text"], "hello")
            with self.assertRaises(PermissionError): reader.query("UPDATE notes SET text = 'bad'")

    def test_kubernetes_identifiers_reject_options(self) -> None:
        self.assertEqual(safe_kubernetes_name("default", "namespace"), "default")
        with self.assertRaises(ValueError): safe_kubernetes_name("--all-namespaces", "namespace")


class StreamingChunkingTests(unittest.TestCase):
    def test_large_stream_chunks_are_split_for_incremental_updates(self) -> None:
        self.assertEqual(list(iter_stream_chunks(["hello world"], chunk_size=5)), ["hello", " worl", "d"])


class SessionStoreTests(unittest.TestCase):
    def test_conversation_can_be_renamed_and_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConversationStore(os.path.join(temp_dir, "conversations.json"))
            conversation = store.create_conversation()
            renamed = store.rename_conversation(conversation["id"], "Study notes")
            self.assertEqual(renamed["title"], "Study notes")
            deleted = store.delete_conversation(conversation["id"])
            self.assertEqual(deleted["id"], conversation["id"])
            self.assertEqual(store.list_conversations(), [])

    def test_session_is_created_and_reused(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConversationStore(os.path.join(temp_dir, "conversations.json"))
            session = store.get_or_create_session()
            self.assertEqual(store.get_or_create_session(session["id"])["id"], session["id"])

    def test_conversations_can_be_scoped_to_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConversationStore(os.path.join(temp_dir, "conversations.json"))
            first = store.get_or_create_session()
            second = store.get_or_create_session()
            first_conversation = store.create_conversation(session_id=first["id"])
            store.create_conversation(session_id=second["id"])

            scoped = store.list_conversations_for_session(first["id"])
            self.assertEqual([item["id"] for item in scoped], [first_conversation["id"]])

    def test_compact_conversations_includes_session_id(self) -> None:
        conversation = {
            "id": "conversation-1",
            "session_id": "session-1",
            "title": "New chat",
            "created_at": "now",
            "updated_at": "now",
            "messages": [],
        }
        self.assertEqual(compact_conversations([conversation])[0]["session_id"], "session-1")

    def test_session_tracks_active_project_and_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConversationStore(os.path.join(temp_dir, "conversations.json"))
            session = store.get_or_create_session()

            updated = store.update_session_context(
                session["id"],
                active_project="AI Tutor",
                current_workspace={"name": "AI Tutor", "focus": "Checkpoint 6"},
                running_task="Add tracking",
                active_file="app/store.py",
                active_tool="editor",
                terminal_output="pytest ok",
                browser_results="Result: docs page",
                mcp_outputs="filesystem result",
                developer_instructions="Prefer small patches",
            )

            self.assertEqual(updated["active_project"], "AI Tutor")
            self.assertEqual(updated["current_workspace"]["name"], "AI Tutor")
            self.assertEqual(updated["current_workspace"]["focus"], "Checkpoint 6")
            self.assertEqual(updated["running_task"], "Add tracking")
            self.assertEqual(updated["active_file"], "app/store.py")
            self.assertEqual(updated["active_tool"], "editor")
            self.assertEqual(updated["terminal_output"], "pytest ok")
            self.assertEqual(updated["browser_results"], "Result: docs page")
            self.assertEqual(updated["mcp_outputs"], "filesystem result")
            self.assertEqual(updated["developer_instructions"], "Prefer small patches")

    def test_session_tracks_user_preferences(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConversationStore(os.path.join(temp_dir, "conversations.json"))
            session = store.get_or_create_session()

            updated = store.update_session_context(
                session["id"],
                user_preferences={
                    "provider_mode": "gemini",
                    "compact_mode": True,
                    "context_window_tokens": 12000,
                },
            )

            self.assertEqual(updated["user_preferences"]["provider_mode"], "gemini")
            self.assertTrue(updated["user_preferences"]["compact_mode"])
            self.assertEqual(updated["user_preferences"]["context_window_tokens"], 12000)

    def test_long_term_memory_survives_across_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConversationStore(os.path.join(temp_dir, "conversations.json"))
            first = store.get_or_create_session()
            store.update_session_context(
                first["id"],
                active_project="AI Tutor",
                current_workspace={"name": "AI Tutor", "focus": "Memory"},
                terminal_output="PS> python -m unittest",
                developer_instructions="Prefer small functions",
                user_preferences={"compact_mode": True},
            )
            store.get_or_create_session()

            memory = store.get_long_term_memory()
            self.assertTrue(memory["user_preferences"]["compact_mode"])
            self.assertEqual(memory["projects"][0]["name"], "AI Tutor")
            self.assertIn("python -m unittest", memory["commands"])
            self.assertIn("Prefer small functions", memory["coding_style"])

    def test_explicit_learned_behavior_is_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConversationStore(os.path.join(temp_dir, "conversations.json"))
            store.update_long_term_memory(learned_behavior=["Explain changes concisely"])
            self.assertIn("Explain changes concisely", store.get_long_term_memory()["learned_behavior"])

    def test_long_term_memory_is_rendered_for_model_context(self) -> None:
        context = long_term_memory_context_text({
            "user_preferences": {"compact_mode": True},
            "coding_style": ["Use type hints"],
            "projects": [{"name": "AI Tutor", "focus": "Memory"}],
            "commands": ["python -m unittest"],
            "learned_behavior": ["Prefer concise answers"],
        })
        self.assertIn("Use type hints", context)
        self.assertIn("AI Tutor", context)
        self.assertIn("python -m unittest", context)
        self.assertIn("Prefer concise answers", context)

    def test_conversation_threads_scope_messages(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConversationStore(os.path.join(temp_dir, "conversations.json"))
            conversation = store.create_conversation()
            thread = store.create_thread(conversation["id"], "Branch")
            store.add_message(conversation["id"], "user", "main message", thread_id="main")
            store.add_message(conversation["id"], "user", "branch message", thread_id=thread["id"])

            saved = store.get_conversation(conversation["id"])
            branch_messages = [
                item["content"]
                for item in saved["messages"]
                if item["thread_id"] == thread["id"]
            ]
            self.assertEqual(branch_messages, ["branch message"])

    def test_conversation_summary_and_compression_are_refreshed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConversationStore(os.path.join(temp_dir, "conversations.json"))
            conversation = store.create_conversation()
            for index in range(8):
                store.add_message(conversation["id"], "user", f"message {index}")

            saved = store.get_conversation(conversation["id"])
            self.assertGreater(saved["compressed_message_count"], 0)
            self.assertIn("message", saved["summary"])

    def test_short_term_memory_tracks_conversation_files_task_variables_and_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ConversationStore(os.path.join(temp_dir, "conversations.json"))
            conversation = store.create_conversation()
            store.add_message(conversation["id"], "user", "Summarize the attached paper")

            memory = store.update_short_term_memory(
                conversation["id"],
                artifact_ids=["paper-1"],
                task="Summarize research",
                variables={"audience": "beginner"},
                tool_outputs={"terminal": "extraction complete"},
            )

            self.assertEqual(memory["artifact_ids"], ["paper-1"])
            self.assertEqual(memory["task"], "Summarize research")
            self.assertEqual(memory["variables"]["audience"], "beginner")
            self.assertEqual(memory["tool_outputs"]["terminal"], "extraction complete")
            self.assertEqual(memory["recent_messages"][-1]["content"], "Summarize the attached paper")

            remembered = store.update_short_term_memory(conversation["id"])
            self.assertEqual(remembered["artifact_ids"], ["paper-1"])

    def test_short_term_memory_is_added_to_prompt_context(self) -> None:
        memory = {
            "task": "Debug upload",
            "variables": {"file": "paper.pdf"},
            "tool_outputs": {"terminal": "HTTP 201"},
        }
        context = short_term_memory_context_text(memory)
        self.assertIn("Debug upload", context)
        self.assertIn("paper.pdf", context)
        self.assertIn("HTTP 201", context)


class ContextWindowTests(unittest.TestCase):
    def test_estimate_tokens_counts_words_and_punctuation(self) -> None:
        self.assertGreaterEqual(estimate_tokens("hello, world!"), 3)

    def test_context_messages_are_pruned_to_token_budget(self) -> None:
        messages = [
            {"role": "user", "content": "older " * 100},
            {"role": "assistant", "content": "middle response"},
            {"role": "user", "content": "latest question"},
        ]
        selected = conversation_messages_for_llm(messages, max_tokens=30)

        self.assertEqual(selected[-1]["content"], "latest question")
        self.assertLessEqual(count_message_tokens(selected), 30)

    def test_context_can_be_filtered_by_thread_and_include_summary(self) -> None:
        messages = [
            {"role": "user", "thread_id": "main", "content": "main message"},
            {"role": "user", "thread_id": "branch", "content": "branch message"},
        ]
        selected = conversation_messages_for_llm(
            messages,
            max_tokens=200,
            thread_id="branch",
            summary="Older useful facts.",
        )

        self.assertEqual(selected[0]["role"], "system")
        self.assertEqual(selected[-1]["content"], "branch message")
        self.assertNotIn("main message", [item["content"] for item in selected])

    def test_project_context_is_rendered_from_session(self) -> None:
        session = {
            "active_project": "AI Tutor",
            "current_workspace": {"name": "AI Tutor", "focus": "Checkpoint 8"},
            "running_task": "Build context",
            "active_tool": "chat",
        }

        context = project_context_text(session)

        self.assertIn("Active project: AI Tutor", context)
        self.assertIn("Running task: Build context", context)

    def test_open_files_context_reads_workspace_file(self) -> None:
        context = open_files_context_text({"active_file": "readme.md", "open_files": []})

        self.assertIn("readme.md", context)
        self.assertIn("AI Tutor", context)

    def test_context_builder_prepends_structured_context(self) -> None:
        session = {
            "active_project": "AI Tutor",
            "current_workspace": {"name": "AI Tutor", "focus": "Checkpoint 8"},
            "running_task": "",
            "active_tool": "",
            "active_file": "",
            "open_files": [],
            "terminal_output": "tests passed",
            "browser_results": "official docs result",
            "mcp_outputs": "tool output",
            "developer_instructions": "keep changes small",
            "user_preferences": {"provider_mode": "auto", "compact_mode": False, "context_window_tokens": 4000},
        }
        messages = [{"role": "user", "content": "hello"}]

        built = build_context_messages(session, messages, max_tokens=4000)

        self.assertEqual(built[0]["role"], "system")
        self.assertIn("Current project context", built[0]["content"])
        self.assertIn("Recent terminal output", built[0]["content"])
        self.assertIn("Browser results", built[0]["content"])
        self.assertIn("MCP outputs", built[0]["content"])
        self.assertIn("Developer instructions", built[0]["content"])
        self.assertIn("User preferences", built[0]["content"])

    def test_terminal_output_context_is_rendered(self) -> None:
        context = terminal_output_context_text({"terminal_output": "python -m unittest\nOK"})

        self.assertIn("Recent terminal output", context)
        self.assertIn("OK", context)

    def test_browser_results_context_is_rendered(self) -> None:
        context = browser_results_context_text({"browser_results": "Search result summary"})

        self.assertIn("Browser results", context)
        self.assertIn("Search result summary", context)

    def test_git_status_context_is_available(self) -> None:
        context = git_status_context_text()

        self.assertIn("Git status", context)

    def test_mcp_outputs_context_is_rendered(self) -> None:
        context = mcp_outputs_context_text({"mcp_outputs": "tool result"})

        self.assertIn("MCP outputs", context)
        self.assertIn("tool result", context)

    def test_running_task_state_context_is_rendered(self) -> None:
        context = running_task_state_context_text(
            {"running_task": "Build context", "active_file": "app/main.py", "active_tool": "editor"}
        )

        self.assertIn("Running task state", context)
        self.assertIn("Build context", context)

    def test_developer_instructions_context_is_rendered(self) -> None:
        context = developer_instructions_context_text({"developer_instructions": "Prefer tests"})

        self.assertIn("Developer instructions", context)
        self.assertIn("Prefer tests", context)

    def test_user_preferences_context_is_rendered(self) -> None:
        context = user_preferences_context_text(
            {"user_preferences": {"provider_mode": "gemini", "compact_mode": True, "context_window_tokens": 12000}}
        )

        self.assertIn("User preferences", context)
        self.assertIn("gemini", context)

    def test_context_sections_are_ranked_by_priority(self) -> None:
        ranked = rank_context_sections(
            [
                {"name": "low", "priority": 1, "text": "low"},
                {"name": "high", "priority": 10, "text": "high"},
            ]
        )

        self.assertEqual([item["name"] for item in ranked], ["high", "low"])

    def test_duplicate_context_sections_are_removed(self) -> None:
        unique = remove_duplicate_context_sections(
            [
                {"name": "one", "priority": 2, "text": "Same text"},
                {"name": "two", "priority": 1, "text": " same   text "},
            ]
        )

        self.assertEqual(len(unique), 1)

    def test_context_text_is_compressed(self) -> None:
        compressed = compress_context_text("word " * 500, max_tokens=40)

        self.assertIn("Context compressed", compressed)
        self.assertLess(estimate_tokens(compressed), 120)

    def test_context_builder_fits_target_window(self) -> None:
        session = {
            "developer_instructions": "important " * 300,
            "active_project": "AI Tutor",
            "current_workspace": {"name": "AI Tutor", "focus": "Checkpoint 8"},
            "running_task": "Fit context",
            "active_file": "",
            "open_files": [],
            "terminal_output": "terminal " * 300,
            "browser_results": "browser " * 300,
            "mcp_outputs": "mcp " * 300,
            "user_preferences": {"provider_mode": "auto", "compact_mode": False, "context_window_tokens": 500},
        }
        messages = [{"role": "user", "content": "latest question"}]

        built = build_context_messages(session, messages, max_tokens=500)

        self.assertLessEqual(count_message_tokens(built), 500)
        self.assertEqual(built[-1]["content"], "latest question")

    def test_message_fitting_preserves_system_and_latest_message(self) -> None:
        fitted = fit_messages_to_token_window(
            [
                {"role": "system", "content": "system context"},
                {"role": "user", "content": "old " * 200},
                {"role": "user", "content": "latest"},
            ],
            max_tokens=80,
        )

        self.assertEqual(fitted[0]["role"], "system")
        self.assertEqual(fitted[-1]["content"], "latest")


class UploadParsingTests(unittest.TestCase):
    def test_multipart_upload_extracts_file(self) -> None:
        boundary = "----aios-test"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="files"; filename="notes.txt"\r\n'
            "Content-Type: text/plain\r\n\r\n"
            "hello upload\r\n"
            f"--{boundary}--\r\n"
        ).encode("utf-8")
        files = parse_multipart_files(f"multipart/form-data; boundary={boundary}", body)
        self.assertEqual(files[0]["filename"], "notes.txt")
        self.assertEqual(files[0]["content"], b"hello upload")

    def test_safe_filename_removes_unsafe_characters(self) -> None:
        self.assertEqual(safe_filename("../bad<>name.txt"), "bad-name.txt")

    def test_artifact_category_detects_media(self) -> None:
        self.assertEqual(artifact_category("photo.png", "image/png"), "image")
        self.assertEqual(artifact_category("voice.mp3", "audio/mpeg"), "audio")
        self.assertEqual(artifact_category("paper.pdf", "application/pdf"), "pdf")

    def test_artifact_category_detects_documents(self) -> None:
        self.assertEqual(artifact_category("report.docx", "application/octet-stream"), "document")

    def test_document_upload_extracts_text_preview(self) -> None:
        metadata = document_metadata_for_upload(
            "notes.txt",
            "text/plain",
            b"hello   document-\nupload\n\n\nsecond line",
            Path("notes.txt"),
        )

        self.assertEqual(metadata["ocr_status"], "not_required")
        self.assertEqual(metadata["extracted_text"], "hello documentupload\n\nsecond line")
        self.assertEqual(metadata["preview"], "hello documentupload\n\nsecond line")
        self.assertEqual(metadata["metadata"]["word_count"], 4)
        self.assertEqual(metadata["metadata"]["chunk_count"], 1)
        self.assertEqual(metadata["chunks"][0]["index"], 0)

    def test_text_cleaning_accepts_missing_subprocess_output(self) -> None:
        self.assertEqual(clean_extracted_text(None), "")

    def test_text_cleaning_normalizes_ocr_noise(self) -> None:
        cleaned = clean_extracted_text("Alpha   beta-\ngamma \n\n\n delta , ok")

        self.assertEqual(cleaned, "Alpha betagamma\n\ndelta, ok")

    def test_document_text_is_chunked_with_metadata(self) -> None:
        chunks = chunk_document_text("Sentence one. " * 80, chunk_size=220, overlap=30)

        self.assertGreater(len(chunks), 1)
        self.assertEqual(chunks[0]["id"], "chunk-0001")
        self.assertGreater(chunks[0]["word_count"], 0)

    def test_embedding_generation_is_deterministic_and_normalized(self) -> None:
        first = generate_embedding("alpha beta beta", dimensions=16)
        second = generate_embedding("alpha beta beta", dimensions=16)
        magnitude = sum(value * value for value in first) ** 0.5

        self.assertEqual(first, second)
        self.assertEqual(len(first), 16)
        self.assertAlmostEqual(magnitude, 1.0, places=5)

    def test_vector_records_are_created_for_document_chunks(self) -> None:
        artifact = {
            "id": "artifact-1",
            "filename": "notes.txt",
            "category": "file",
            "content_type": "text/plain",
            "document_type": "text",
            "path": "data/uploads/artifact-1-notes.txt",
            "chunks": chunk_document_text("alpha beta gamma"),
        }

        records = vector_records_for_artifact(artifact)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["artifact_id"], "artifact-1")
        self.assertEqual(len(records[0]["embedding"]), 64)

    def test_conversation_messages_and_long_term_memories_are_embedded(self) -> None:
        message_record = vector_record_for_message(
            "conversation-1",
            {"id": "message-1", "role": "user", "content": "Remember rotary embeddings", "thread_id": "main"},
        )
        memory_records = vector_records_for_long_term_memory({
            "coding_style": ["Prefer type hints"],
            "projects": [{"name": "AI Tutor", "focus": "semantic memory"}],
            "commands": [], "learned_behavior": [], "user_preferences": {},
        })

        self.assertEqual(message_record["source_type"], "conversation")
        self.assertEqual(len(message_record["embedding"]), 64)
        self.assertTrue(all(record["source_type"] == "memory" for record in memory_records))
        self.assertGreaterEqual(len(memory_records), 2)

    def test_semantic_search_spans_documents_and_conversations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from app import main as main_module
            old_index = main_module.VECTOR_INDEX
            main_module.VECTOR_INDEX = main_module.Path(temp_dir) / "vectors.json"
            try:
                main_module.save_vector_records([
                    {
                        "id": "doc:1", "source_type": "document", "artifact_id": "doc",
                        "filename": "vectors.pdf", "document_type": "pdf",
                        "text": "Global word vectors encode semantic relationships.",
                        "embedding": generate_embedding("Global word vectors encode semantic relationships."),
                        "metadata": {},
                    },
                    {
                        "id": "conversation:1", "source_type": "conversation", "source_id": "chat",
                        "filename": "conversation-chat", "document_type": "conversation",
                        "text": "We discussed railway ticket reservations.",
                        "embedding": generate_embedding("We discussed railway ticket reservations."),
                        "metadata": {},
                    },
                ])
                all_results = semantic_search("semantic word vectors", top_k=2)
                conversation_results = semantic_search("railway reservations", top_k=2, source_types=["conversation"])
            finally:
                main_module.VECTOR_INDEX = old_index

        self.assertEqual(all_results[0]["source_type"], "document")
        self.assertEqual([item["source_type"] for item in conversation_results], ["conversation"])

    def test_related_conversations_are_grouped_and_exclude_current_chat(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from app import main as main_module
            old_index = main_module.VECTOR_INDEX
            main_module.VECTOR_INDEX = main_module.Path(temp_dir) / "vectors.json"
            conversations = [
                {"id": "current", "title": "Current", "messages": [], "updated_at": "now"},
                {"id": "related", "title": "Embedding discussion", "messages": [], "updated_at": "now"},
                {"id": "other", "title": "Travel", "messages": [], "updated_at": "now"},
            ]
            try:
                main_module.save_vector_records([
                    vector_record_for_message("current", {"id": "m1", "role": "user", "content": "semantic embeddings"}),
                    vector_record_for_message("related", {"id": "m2", "role": "user", "content": "semantic vector embeddings for memory"}),
                    vector_record_for_message("other", {"id": "m3", "role": "user", "content": "railway ticket travel"}),
                ])
                results = related_conversations("semantic vector embeddings", conversations, exclude_id="current")
            finally:
                main_module.VECTOR_INDEX = old_index

        self.assertEqual(results[0]["conversation_id"], "related")
        self.assertNotIn("current", [item["conversation_id"] for item in results])

    def test_related_conversation_search_passes_user_scope_to_retrieval(self) -> None:
        from app import main as main_module
        with mock.patch.object(main_module, "semantic_search", return_value=[]) as search:
            results = related_conversations("database design", [], user_id="user-1")

        self.assertEqual(results, [])
        search.assert_called_once_with(
            "database design",
            top_k=40,
            source_types=["conversation"],
            user_id="user-1",
        )
    def test_similar_documents_rank_related_chunk_embeddings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from app import main as main_module
            old_index = main_module.VECTOR_INDEX
            main_module.VECTOR_INDEX = main_module.Path(temp_dir) / "vectors.json"
            try:
                def record(artifact_id, chunk_id, filename, text):
                    return {
                        "id": f"{artifact_id}:{chunk_id}", "source_type": "document",
                        "artifact_id": artifact_id, "chunk_id": chunk_id, "filename": filename,
                        "document_type": "pdf", "text": text, "embedding": generate_embedding(text),
                        "metadata": {},
                    }
                main_module.save_vector_records([
                    record("source", "c1", "source.pdf", "neural word embeddings semantic vectors"),
                    record("similar", "c1", "similar.pdf", "semantic word vectors and neural embeddings"),
                    record("different", "c1", "different.pdf", "railway reservation passenger ticket"),
                ])
                results = similar_documents("source", top_k=2)
            finally:
                main_module.VECTOR_INDEX = old_index

        self.assertEqual(results[0]["artifact_id"], "similar")
        self.assertGreater(results[0]["score"], results[1]["score"])
        self.assertTrue(results[0]["matching_chunks"])

    def test_vector_records_are_upserted_to_json_store(self) -> None:
        old_vector_index = os.environ.get("AIOS_VECTOR_INDEX")
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["AIOS_VECTOR_INDEX"] = os.path.join(temp_dir, "vectors.json")
            try:
                from app import main as main_module

                old_index = main_module.VECTOR_INDEX
                main_module.VECTOR_INDEX = main_module.Path(os.environ["AIOS_VECTOR_INDEX"])
                upsert_vector_records(
                    [
                        {
                            "id": "artifact-1:chunk-0001",
                            "artifact_id": "artifact-1",
                            "chunk_id": "chunk-0001",
                            "embedding": [1.0, 0.0],
                        }
                    ]
                )

                records = load_vector_records()
            finally:
                main_module.VECTOR_INDEX = old_index
                if old_vector_index is None:
                    os.environ.pop("AIOS_VECTOR_INDEX", None)
                else:
                    os.environ["AIOS_VECTOR_INDEX"] = old_vector_index

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["id"], "artifact-1:chunk-0001")

    def test_hybrid_retrieval_combines_vectors_and_keywords(self) -> None:
        old_vector_index = os.environ.get("AIOS_VECTOR_INDEX")
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["AIOS_VECTOR_INDEX"] = os.path.join(temp_dir, "vectors.json")
            try:
                from app import main as main_module

                old_index = main_module.VECTOR_INDEX
                main_module.VECTOR_INDEX = main_module.Path(os.environ["AIOS_VECTOR_INDEX"])
                records = [
                    {
                        "id": "a:chunk-0001",
                        "artifact_id": "a",
                        "chunk_id": "chunk-0001",
                        "filename": "algebra-notes.txt",
                        "document_type": "text",
                        "text": "Linear equations use variables and constants.",
                        "embedding": generate_embedding("Linear equations use variables and constants."),
                        "metadata": {"category": "file", "content_type": "text/plain"},
                    },
                    {
                        "id": "b:chunk-0001",
                        "artifact_id": "b",
                        "chunk_id": "chunk-0001",
                        "filename": "history.txt",
                        "document_type": "text",
                        "text": "Ancient trade routes crossed mountains.",
                        "embedding": generate_embedding("Ancient trade routes crossed mountains."),
                        "metadata": {"category": "file", "content_type": "text/plain"},
                    },
                ]
                main_module.save_vector_records(records)

                results = hybrid_retrieve("linear equation variables", top_k=2)
            finally:
                main_module.VECTOR_INDEX = old_index
                if old_vector_index is None:
                    os.environ.pop("AIOS_VECTOR_INDEX", None)
                else:
                    os.environ["AIOS_VECTOR_INDEX"] = old_vector_index

        self.assertEqual(results[0]["id"], "a:chunk-0001")
        self.assertGreater(results[0]["scores"]["hybrid"], results[1]["scores"]["hybrid"])
        self.assertIn("rerank", results[0]["scores"])

    def test_rerank_boosts_exact_phrase_match(self) -> None:
        results = [
            {"id": "low", "filename": "notes.txt", "document_type": "text", "text": "alpha beta", "scores": {"hybrid": 0.5}},
            {"id": "high", "filename": "notes.txt", "document_type": "text", "text": "find exact phrase here", "scores": {"hybrid": 0.4}},
        ]

        reranked = rerank_results("exact phrase", results)

        self.assertEqual(reranked[0]["id"], "high")

    def test_top_k_selection_limits_reranked_results(self) -> None:
        results = [
            {"id": "a", "scores": {"rerank": 0.2}},
            {"id": "b", "scores": {"rerank": 0.9}},
            {"id": "c", "scores": {"rerank": 0.4}},
        ]

        selected = select_top_k(results, top_k=2)

        self.assertEqual([item["id"] for item in selected], ["b", "c"])

    def test_citation_generation_labels_retrieved_chunks(self) -> None:
        cited = add_citations_to_results(
            [
                {
                    "filename": "notes.txt",
                    "chunk_id": "chunk-0002",
                    "metadata": {"start_char": 10, "end_char": 80},
                }
            ]
        )

        self.assertEqual(cited[0]["citation"], "[1] notes.txt, chunk-0002, chars 10-80")

    def test_retrieved_context_is_injected_into_chat_context(self) -> None:
        old_vector_index = os.environ.get("AIOS_VECTOR_INDEX")
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["AIOS_VECTOR_INDEX"] = os.path.join(temp_dir, "vectors.json")
            try:
                from app import main as main_module

                old_index = main_module.VECTOR_INDEX
                main_module.VECTOR_INDEX = main_module.Path(os.environ["AIOS_VECTOR_INDEX"])
                main_module.save_vector_records(
                    [
                        {
                            "id": "a:chunk-0001",
                            "artifact_id": "a",
                            "chunk_id": "chunk-0001",
                            "filename": "algebra-notes.txt",
                            "document_type": "text",
                            "text": "Linear equations use variables and constants.",
                            "embedding": generate_embedding("Linear equations use variables and constants."),
                            "metadata": {"category": "file", "content_type": "text/plain", "start_char": 0, "end_char": 45},
                        }
                    ]
                )
                session = {
                    "active_project": "",
                    "current_workspace": {},
                    "running_task": "",
                    "active_tool": "",
                    "active_file": "",
                    "open_files": [],
                    "terminal_output": "",
                    "browser_results": "",
                    "mcp_outputs": "",
                    "developer_instructions": "",
                    "user_preferences": {"provider_mode": "auto", "compact_mode": False, "context_window_tokens": 4000},
                }

                context = retrieved_context_text("linear equations", top_k=1)
                built = build_context_messages(session, [{"role": "user", "content": "linear equations"}], max_tokens=4000)
            finally:
                main_module.VECTOR_INDEX = old_index
                if old_vector_index is None:
                    os.environ.pop("AIOS_VECTOR_INDEX", None)
                else:
                    os.environ["AIOS_VECTOR_INDEX"] = old_vector_index

        self.assertIn("Retrieved document context", context)
        self.assertIn("[1] algebra-notes.txt, chunk-0001", context)
        self.assertIn("Retrieved document context", built[0]["content"])

    def test_scanned_pdf_without_text_is_marked_for_ocr(self) -> None:
        old_pdf_command = os.environ.pop("AIOS_PDF_OCR_COMMAND", None)
        old_ocr_command = os.environ.pop("AIOS_OCR_COMMAND", None)
        try:
            metadata = document_metadata_for_upload(
                "scan.pdf",
                "application/pdf",
                b"%PDF-1.4\n%%EOF",
                Path("scan.pdf"),
            )
        finally:
            if old_pdf_command is not None:
                os.environ["AIOS_PDF_OCR_COMMAND"] = old_pdf_command
            if old_ocr_command is not None:
                os.environ["AIOS_OCR_COMMAND"] = old_ocr_command

        self.assertEqual(metadata["ocr_status"], "unavailable")
        self.assertTrue(metadata["metadata"]["scanned_candidate"])

    def test_scanned_pdf_uses_builtin_poppler_tesseract_pipeline(self) -> None:
        from app import main as main_module

        def fake_run(command, **kwargs):
            if command[0] == "pdftoppm":
                Path(f"{command[-1]}-1.png").write_bytes(b"image")
                return mock.Mock(returncode=0, stdout="", stderr="")
            return mock.Mock(returncode=0, stdout="Text recovered from scanned PDF", stderr="")

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "scan.pdf"
            path.write_bytes(b"%PDF scan")
            with mock.patch.object(main_module.shutil, "which", side_effect=lambda name: name), mock.patch.object(
                main_module.subprocess, "run", side_effect=fake_run
            ):
                text, status, error = main_module.ocr_pdf_file(path)

        self.assertEqual(status, "completed")
        self.assertEqual(error, "")
        self.assertIn("Text recovered from scanned PDF", text)

    def test_basic_pdf_text_can_be_extracted(self) -> None:
        text = extract_pdf_text_basic(b"%PDF-1.4\nBT (Hello from PDF text) Tj ET\n%%EOF")

        self.assertIn("Hello from PDF text", text)

    def test_binary_pdf_noise_is_not_accepted_as_text(self) -> None:
        self.assertEqual(usable_extracted_text("\x87Íd\x8e \x8bôß\x80óþüôõÕ\x11À9"), "")

    def test_pymupdf_extractor_returns_empty_for_non_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "not-a-pdf.pdf"
            path.write_text("not a pdf", encoding="utf-8")

            self.assertEqual(extract_pdf_text_pymupdf(path), "")

    def test_old_pdf_artifact_is_upgraded_with_extracted_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from app import main as main_module

            old_root = main_module.ROOT
            old_upload_index = main_module.UPLOAD_INDEX
            old_vector_index = main_module.VECTOR_INDEX
            try:
                main_module.ROOT = Path(temp_dir)
                main_module.UPLOAD_INDEX = Path(temp_dir) / "data" / "uploads.json"
                main_module.VECTOR_INDEX = Path(temp_dir) / "data" / "vectors.json"
                upload_path = Path(temp_dir) / "data" / "uploads" / "paper.pdf"
                upload_path.parent.mkdir(parents=True, exist_ok=True)
                upload_path.write_bytes(b"%PDF-1.4\nBT (Rotary position embeddings improve transformer attention.) Tj ET\n%%EOF")
                save_artifacts(
                    [
                        {
                            "id": "artifact-1",
                            "filename": "ROFORMER ENHANCED TRANSFORMER WITH ROTARY.pdf",
                            "content_type": "application/pdf",
                            "size": upload_path.stat().st_size,
                            "category": "pdf",
                            "path": "data/uploads/paper.pdf",
                            "preview": "",
                        }
                    ]
                )

                artifacts = load_artifacts()
            finally:
                main_module.ROOT = old_root
                main_module.UPLOAD_INDEX = old_upload_index
                main_module.VECTOR_INDEX = old_vector_index

        self.assertIn("Rotary position embeddings", artifacts[0]["cleaned_text"])
        self.assertGreater(artifacts[0]["metadata"]["chunk_count"], 0)

    def test_uploaded_files_context_uses_extracted_text(self) -> None:
        old_upload_index = os.environ.get("AIOS_UPLOAD_INDEX")
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["AIOS_UPLOAD_INDEX"] = os.path.join(temp_dir, "uploads.json")
            try:
                from app import main as main_module

                old_index = main_module.UPLOAD_INDEX
                main_module.UPLOAD_INDEX = main_module.Path(os.environ["AIOS_UPLOAD_INDEX"])
                main_module.save_artifacts(
                    [
                        {
                            "id": "artifact-1",
                            "filename": "notes.txt",
                            "category": "file",
                            "size": 12,
                            "extracted_text": "important extracted text",
                            "ocr_status": "not_required",
                        }
                    ]
                )

                context = uploaded_files_context_text(["artifact-1"])
            finally:
                main_module.UPLOAD_INDEX = old_index
                if old_upload_index is None:
                    os.environ.pop("AIOS_UPLOAD_INDEX", None)
                else:
                    os.environ["AIOS_UPLOAD_INDEX"] = old_upload_index

        self.assertIn("Extracted text", context)
        self.assertIn("important extracted text", context)

    def test_uploaded_image_without_ocr_still_has_context_note(self) -> None:
        old_upload_index = os.environ.get("AIOS_UPLOAD_INDEX")
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["AIOS_UPLOAD_INDEX"] = os.path.join(temp_dir, "uploads.json")
            try:
                from app import main as main_module

                old_index = main_module.UPLOAD_INDEX
                main_module.UPLOAD_INDEX = main_module.Path(os.environ["AIOS_UPLOAD_INDEX"])
                main_module.save_artifacts(
                    [
                        {
                            "id": "artifact-1",
                            "filename": "cross_dataset_alignmnet.png",
                            "category": "image",
                            "size": 36556,
                            "cleaned_text": "",
                            "ocr_status": "unavailable",
                            "ocr_error": "Install Tesseract or set AIOS_OCR_COMMAND to enable OCR.",
                            "metadata": {"chunk_count": 0},
                        }
                    ]
                )

                context = uploaded_files_context_text(["artifact-1"])
            finally:
                main_module.UPLOAD_INDEX = old_index
                if old_upload_index is None:
                    os.environ.pop("AIOS_UPLOAD_INDEX", None)
                else:
                    os.environ["AIOS_UPLOAD_INDEX"] = old_upload_index

        self.assertIn("cross_dataset_alignmnet.png", context)
        self.assertIn("No text was extracted", context)
        self.assertIn("OCR or vision support is required", context)


if __name__ == "__main__":
    unittest.main()
