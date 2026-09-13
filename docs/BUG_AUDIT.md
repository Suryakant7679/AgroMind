# AI Tutor bug audit

Audit date: 2026-09-12. This is the set of findings verified during this review, not a guarantee that every possible defect has been discovered. Production infrastructure and live provider billing were not exercised.

## Fixed in this patch

| Severity | Bug and trigger | Fix / evidence |
| --- | --- | --- |
| Critical | A signed-in user could request filesystem, database, Redis, terminal, or other server tools through chat. Tool constructors and execution had no role check. | `app/main.py` passes a trusted admin capability to `explicit_mcp_answer`; all categories except public DuckDuckGo search require it. HTTP regression verifies denial before registry initialization. |
| Critical | `/api/orchestrate` could invoke unscoped memory/RAG and privileged specialist tools as an ordinary user. | The endpoint now requires an authenticated administrator before invocation. The specialist layer remains an administrative facility, not a tenant-isolated student API. |
| High | Chat accepted another user's attachment ID even though the upload listing/download endpoints enforced ownership. Remembered IDs also entered context without filtering. | Chat validates attachment ownership and existence before creating a conversation; context generation independently filters current and remembered attachments by user. |
| High | A user could set `active_file` / `open_files` in their session and cause ordinary chat context to read backend workspace files. | HTTP chat enables workspace snippets and Git status only for administrators. Workspace snippets also use the protected filesystem reader. |
| High | Implicit GitHub lookups used the backend's `GITHUB_TOKEN`, potentially exposing repositories accessible to its owner. | Ordinary chat's GitHub reader now uses public, unauthenticated access. Explicit administrative GitHub MCP retains its separate configured reader. Public GitHub rate limits therefore apply to ordinary chat. |
| High | Filesystem protection blocked only the exact `.env` name, allowing `.env.production`, case variants on Windows, and recursive search through file symlinks outside the root. | Reads, listings and searches share path validation; secret variants are blocked case-insensitively and recursive results are resolved before reading. Symlink regression is included but skipped on this Windows session because link creation is not permitted. |
| High | Successful generic, Python and GitHub MCP results were set to `None`, making their direct response branches unreachable and invoking the LLM unnecessarily. | Removed the resets. Tool results use the existing deterministic response/stream handlers. An HTTP regression fails if the LLM is invoked for an explicit search result. |
| Medium | DuckDuckGo appeared in the MCP catalog but had no executable entry in the generic registry. | `duckduckgo_search` now calls the existing `search_web` implementation. |
| Medium | An unsupported version such as `/api/v2/health` raised another version error inside error logging, dropping the connection instead of returning JSON. | Error logging records the raw URL path without re-running version validation. HTTP regression expects structured 404. |
| Medium | Provider errors left persistent chat recovery, and streaming Redis recovery, marked `running`. | LLM failures now mark the applicable recovery state `failed`; ordinary and streaming regression tests cover this. |
| Medium | MCP reader initialization could throw before the executor's error handling, dropping the request when a dependency or configuration was missing. | Initialization failures produce a deterministic tool error without exposing the underlying configuration string. |
| Medium | Tests imported application globals that loaded the developer's `.env`, data paths and configured cloud/provider services. | `tests/conftest.py` directs application stores to temporary files and overrides cloud/provider credentials. Gateway HTTP tests use their own in-memory rate limiter. Worker tests continue using their own temporary project roots. |

## Remaining confirmed defects and limitations

| Severity | Finding / evidence | Suggested resolution |
| --- | --- | --- |
| High | Conversation mutations use whole-store load/modify/save without a transaction spanning the operation. A controlled stale-snapshot reproduction overwrote a concurrent title change. PostgreSQL also loads all rows and upserts the snapshot (`app/store.py`, `app/postgres_store.py`). | Use row-specific transactional writes and concurrency control in PostgreSQL. Serialize JSON mutations and use atomic replacement for local storage. Include simultaneous-request tests. |
| High | JSON upload/vector indexes write directly to shared files and upload metadata updates use separate load/save operations (`receive_uploads`, `save_artifacts`, `JsonVectorStore`). Concurrent requests can lose updates or read partial JSON. | Atomic file replacement plus a lock spanning each complete mutation; durable transactional metadata for production. |
| High | Deleting a conversation removes its store entry but leaves its message vectors. Reproduction confirmed `semantic_search` still returned the deleted conversation text. | Delete vector records by conversation ID and clear associated stream/cache state, with a retryable cleanup strategy if Qdrant is unavailable. |
| High | Uploaded binaries and their index are local files even with PostgreSQL selected; per-user long-term memory is also written to a local JSON file by the PostgreSQL store. Ephemeral hosting can lose them after restart/redeploy. | Store uploads in object storage and metadata/memory in PostgreSQL; migrate existing records before switching. |
| Medium | Every Qdrant-backed retrieval scrolls all vectors and payloads into Python before filtering and ranking (`QdrantVectorStore.load`, `hybrid_retrieve`). | Query Qdrant using an indexed user filter and a bounded candidate set. |
| Medium | An automatic web-search exception returns empty context, allowing the normal answer path to proceed without fresh evidence (`web_research_context_text`). | Explicitly represent lookup failure and tell the user current facts could not be verified; retry an independently configured research provider. |
| Medium | The frontend saves `provider_mode`, but model selection reads server environment configuration instead of that user's preference (`web/app.js`, `EnvironmentModelRouter`). | Carry an approved provider preference into routing, or remove the nonfunctional selector. |
| Medium | Ordinary streaming skips the response validation used by nonstreaming and grounded responses; errors during iterator consumption can also be recorded as successful model calls (`generate_response_stream`). | Validate the completed stream appropriately and record completion/error status from iterator consumption. |
| Medium | Custom MCP tool timeout applies only to `call_tool`, not initialization or tool listing. The registry creates a fresh process per call, so a stateful browser cannot retain its session between calls. | Add lifecycle deadlines and session management before using stateful tools from backend chat. Keep Playwright in a persistent IDE MCP session for now. |
| Medium | `fetch_url` and several process tools collect entire HTTP bodies/stdout before truncating. The restricted Python runner limits elapsed time but not memory or accumulated output. | Apply streaming byte limits and OS/container memory/output limits before exposing these capabilities beyond administrators. |
| Low | No favicon is served: the browser smoke test observed `/favicon.ico` returning 404. | Add a favicon and declare it in the HTML. |

## Validation

- Existing baseline: 218 tests passed.
- Final automated suite: 231 passed, 1 skipped. The skipped test requires Windows symlink privileges.
- Five existing PyMuPDF/SWIG deprecation warnings remain.
- `node --check web/app.js` and `git diff --check` passed.
- npm installation audit: zero reported vulnerabilities at installation time.
- MCP protocol initialization: Context7 advertised 2 tools; Playwright advertised 24 tools. Required tool names were verified.
- Backend custom MCP bridge successfully listed Context7's tools.
- Actual headless Chrome test through Playwright MCP: local signup, authenticated streamed chat, no page-script exceptions, and no horizontal overflow at 390px viewport width. Used temporary data and a mocked LLM; this does not validate production providers or deployment.

Existing edits to `app/llm.py` and `tests/test_validation.py` were preserved. No production deployment or account credential changes were performed.
