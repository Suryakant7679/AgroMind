"""Keep unit/integration tests off developer data and configured cloud services."""
import atexit
import os
import tempfile
from pathlib import Path

_test_data = tempfile.TemporaryDirectory(prefix="ai-tutor-tests-")
atexit.register(_test_data.cleanup)
for key in ("AGROMIND_DATABASE_URL", "DATABASE_URL", "REDIS_URL", "QDRANT_URL", "QDRANT_API_KEY", "OPENAI_API_KEY",
            "GROQ_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "GITHUB_TOKEN",
            "AIOS_ADMIN_EMAILS", "AIOS_MCP_WORKSPACE_ROOT"):
    os.environ[key] = ""
os.environ.update(AIOS_STORAGE_BACKEND="json", AIOS_VECTOR_BACKEND="json", AIOS_AUTH_REQUIRED="false")
for key, name in {
    "AIOS_DATA_FILE": "conversations.json", "AIOS_MEMORY_FILE": "memory.json",
    "AIOS_GATEWAY_DATA_FILE": "gateway.json", "AIOS_VECTOR_INDEX": "vectors.json",
    "AIOS_UPLOAD_INDEX": "uploads.json", "AIOS_UPLOAD_DIR": "uploads",
    "AIOS_USAGE_FILE": "usage.json", "AIOS_OBSERVABILITY_FILE": "observability.json",
}.items():
    os.environ[key] = str(Path(_test_data.name) / name)

os.environ["AIOS_WORKER_STATE_DIR"] = "data/worker_state"
