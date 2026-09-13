# Local setup

For the complete AgroMind portal and AI Tutor, follow [the README](readme.md#getting-started).
Both use local PostgreSQL. Set `DATABASE_URL` and `AIOS_STORAGE_BACKEND=postgres`
in `.env`, install both dependency sets, and start `python run_integrated.py`.
AgroMind signup requires no hosted authentication service. Its tables are created
automatically in the `agromind` schema; AI Tutor retains its own tables and login.

The reference below covers additional AI Tutor settings.

## Run

Add your API keys to `.env` first:

```text
AIOS_PROVIDER=auto
AIOS_DEFAULT_MODEL=
OPENAI_API_KEY=your_key_here
ANTHROPIC_API_KEY=
GROQ_API_KEY=
DEEPSEEK_API_KEY=
GEMINI_API_KEY=
```

Leave providers blank if you are not using them yet.

`AIOS_PROVIDER=auto` chooses the first available key in this order: Groq, Gemini, OpenAI, DeepSeek. You can force one with `AIOS_PROVIDER=groq`, `gemini`, `openai`, or `deepseek`.

The app reloads `.env` on startup and lets the file override old terminal environment values. After changing an API key, restart the server.

Provider-specific model settings are supported:

```text
AIOS_GROQ_MODEL=llama-3.1-8b-instant
AIOS_GEMINI_MODEL=gemini-3.5-flash
AIOS_OPENAI_MODEL=gpt-4o-mini
AIOS_DEEPSEEK_MODEL=deepseek-chat
```

If one provider rejects a request, auto mode tries the next configured provider. For example, if Groq returns a provider/CDN `403`, the app can continue with Gemini when `GEMINI_API_KEY` is present. To skip Groq entirely, set:

```text
AIOS_PROVIDER=gemini
```

If you see `[WinError 10054] An existing connection was forcibly closed by the remote host`, the provider or network closed the connection before returning an API response. Keep `AIOS_PROVIDER=auto` so the app retries and then falls back to another configured provider.

If Gemini returns `models/gemini-1.5-flash is not found`, remove the old `AIOS_GEMINI_MODEL=gemini-1.5-flash` setting or change it to `AIOS_GEMINI_MODEL=gemini-3.5-flash`. The app also tries a few current Gemini fallback model names when Gemini is enabled.

```powershell
python app/main.py
```

Open:

```text
http://127.0.0.1:8000
```

Health check:

```text
http://127.0.0.1:8000/api/health
```

## API authentication and versioning

Version 1 routes use `/api/v1`; existing `/api` routes remain compatible aliases.
Local development leaves authentication optional. To protect all non-public API
routes, configure and restart:

```text
AIOS_AUTH_REQUIRED=true
AIOS_JWT_SECRET=replace_with_a_random_secret_of_at_least_32_bytes
AIOS_ADMIN_EMAILS=admin@example.com
```

Register through `POST /api/v1/auth/register` with `email`, `password`, and an
optional `display_name`, or sign in through `POST /api/v1/auth/login`. Send the
returned token on protected requests as `Authorization: Bearer <token>`. User
records, password hashes, the development signing secret, request analytics,
and login sessions persist across restarts. Configure `AIOS_API_RATE_LIMIT` and
`AIOS_API_RATE_WINDOW` to adjust gateway throttling.
PostgreSQL mode writes identities and events to the `users` and `analytics`
tables; JSON mode uses `AIOS_GATEWAY_DATA_FILE`.

## Current Features

- Simple chat UI.
- Local JSON conversation storage.
- Conversation list and reload.
- Dependency-free Python backend.
- Local `.env` loading for API keys.
- Real LLM calls through OpenAI-compatible providers or Gemini.

## Next Development Step

Add file upload and RAG now that the real model calls and streaming responses are in place.

## PostgreSQL schema

Create a PostgreSQL role and database, then put its connection URL in `.env`:

```text
DATABASE_URL=postgresql://aios:your_password@127.0.0.1:5432/aios
```

Install the database driver and apply all versioned migrations:

```powershell
python -m pip install -r requirements.txt
python -m app.migrate
```

The migrations create `users`, `sessions`, `chats`, `projects`, `files`,
`settings`, `api_keys`, `logs`, and `analytics`, their indexes and foreign keys, automatic
`updated_at` triggers, and a `schema_migrations` ledger. API keys must be
encrypted by the application before their ciphertext is stored in
`api_keys.encrypted_secret`; plaintext secrets must never be inserted.
The migration is safe to run again. When `DATABASE_URL` is configured and
`AIOS_STORAGE_BACKEND=auto` (the default), sessions and chats use PostgreSQL.
Use `AIOS_STORAGE_BACKEND=json` only when you explicitly want local JSON.

## Redis ephemeral state

Start Redis locally with Docker and configure the connection:

```powershell
docker run --name aios-redis -p 6379:6379 -d redis:7-alpine
```

```text
REDIS_URL=redis://127.0.0.1:6379/0
```

Install dependencies with `python -m pip install -r requirements.txt`, then
restart the app. Redis stores TTL-backed active sessions, cache entries,
stream recovery state, and queue job state. PostgreSQL remains authoritative;
the app degrades gracefully when Redis is unavailable.

Temporary conversation memory expires after `AIOS_REDIS_MEMORY_TTL` seconds.
Chat requests use an atomic fixed-window rate limit configured by
`AIOS_CHAT_RATE_LIMIT` requests per `AIOS_CHAT_RATE_WINDOW` seconds. When Redis
is unavailable, rate limiting fails open so local development remains usable.

## Background workers

Checkpoint 14 uses Redis queues. Start one worker process for all queue
consumers and a second process for scheduled job production:

```powershell
python -m app.workers --worker all
```

```powershell
python -m app.workers --worker scheduler
```

Use separate terminals and keep both processes running. Add `--once` to a
command for a non-blocking single pass. For production, individual consumers
can be scaled independently with `--worker pdf`, `ocr`, `embedding`, `memory`,
`summary`, `git`, `files`, `cache`, `analytics`, `health`, `email`, `backup`, or
`vector`. A reachable `REDIS_URL` is required.

The queues and payloads are:

- `pdf-processing`: `{"artifact_id": "..."}`; embedded text proceeds to embeddings and scanned PDFs proceed to OCR.
- `ocr`: `{"artifact_id": "..."}`; images and configured scanned-PDF OCR.
- `embedding-generation`: an `artifact_id`, a `conversation_id`, or `{"target": "memory", "user_id": "..."}`.
- `memory-compression`: `{"conversation_id": "...", "recent_limit": 6, "text_limit": 2000}`.
- `conversation-summary`: `{"conversation_id": "...", "keep_recent": 6}`.
- `git-monitoring` and `file-monitoring`: detect repository/workspace changes and queue code-vector refreshes.
- `cache-cleanup`: removes orphaned Redis queue references; Redis expires cache values by TTL.
- `analytics`: aggregates gateway events into `data/worker_state/analytics-summary.json`.
- `health-check`: records Redis, conversation-store, vector-store, and upload-storage health.
- `email-notifications`: sends explicit notification jobs through configured SMTP.
- `backup`: archives local `data` files under `data/backups` with retention cleanup; `.env` and existing backups are excluded.
- `vector-index-update`: rebuilds selected document, code, conversation, and memory sources.

The scheduler persists last-run timestamps under `data/worker_state` so restarts
do not duplicate interval jobs. Configure intervals with
`AIOS_SCHEDULE_<NAME>_SECONDS`; set an interval to `0` to disable it. Email is
opt-in: leave `AIOS_HEALTH_ALERT_EMAIL` and SMTP settings blank to run without
notifications. Configure PDF/OCR extraction with `AIOS_PDF_TEXT_COMMAND`,
`AIOS_OCR_COMMAND`, and `AIOS_PDF_OCR_COMMAND`.

## Observability

Checkpoint 15 combines gateway analytics, the LLM usage ledger, tool/worker
events, Redis queue depths, scheduled health snapshots, and live resource
sampling. Open the workspace tools panel and use **System health**, or request:

```text
GET /api/v1/observability
```

When authentication is required, this endpoint is restricted to users with the
`admin` role. The dashboard reports token totals, estimated provider cost, API
average/p95/max latency, model and tool success rates, recent errors, unique
users, CPU and RAM utilization, NVIDIA GPU utilization when `nvidia-smi` is
available, Redis queue depths, and worker health. Systems without an NVIDIA GPU
report GPU monitoring as unavailable rather than unhealthy.

Metrics events are retained in `AIOS_OBSERVABILITY_FILE` (default
`data/observability.json`) up to `AIOS_OBSERVABILITY_MAX_EVENTS` records.
Provider cost remains an estimate and requires the configured
`AIOS_<PROVIDER>_INPUT_COST_PER_MILLION` and
`AIOS_<PROVIDER>_OUTPUT_COST_PER_MILLION` rates. Run
`python -m pip install -r requirements.txt` after pulling changes so `psutil`
is available for CPU and memory metrics.

## ChromaDB vector storage

ChromaDB is the vector backend in the updated configuration templates. Install
`requirements.txt`, set `AIOS_VECTOR_BACKEND=chroma`, and use `AIOS_CHROMA_PATH`
for native persistent storage. A blank `CHROMA_HOST` selects an embedded client.
Use a shared Chroma server for multiple app/worker processes; Docker Compose
provides it with `CHROMA_HOST=chroma` and `CHROMA_PORT=8000`.

Existing private environment files and Qdrant data are preserved. Stop writers,
run `python -m app.import_vectors_to_chroma --source qdrant` (or `--source json`),
then select Chroma in your environment and restart. Keep the source available
until retrieval has been verified. See the README for migration details.
The legacy Qdrant adapter remains available for migration and compatibility.
Uploaded files and metadata remain in their existing locations.

## Local application

Python serves both the frontend and API on localhost. See [README](readme.md) for complete startup instructions.

## Local Docker stack

Docker Compose remains available for local development and recovery testing. It
starts PostgreSQL, Redis, Qdrant, migrations, API, workers, monitoring, and Nginx:

```powershell
$env:AIOS_ENV_FILE=".env.production"
docker compose --env-file .env.production up -d --build
```

Validate or stop the local stack with:

```powershell
docker compose --env-file .env.production config
docker compose --env-file .env.production ps
docker compose --env-file .env.production down
```

Use `scripts/backup.ps1` and `scripts/restore.ps1` for local PostgreSQL and
application-data recovery. Keep backups outside the application data volume.

## MCP router and local servers

Install dependencies, then run any server over standard MCP stdio:

```powershell
python -m pip install -r requirements.txt
python -m app.mcp.router_server
python -m app.mcp.filesystem_server
python -m app.mcp.python_server
python -m app.mcp.terminal_server
python -m app.mcp.browser_server
python -m app.mcp.duckduckgo_server
python -m app.mcp.git_server
python -m app.mcp.github_server
python -m app.mcp.docker_server
python -m app.mcp.kubernetes_server
python -m app.mcp.postgresql_server
python -m app.mcp.sqlite_server
python -m app.mcp.redis_server
python -m app.mcp.cloud_server
python -m app.mcp.productivity_server
python -m app.mcp.rest_server
python -m app.mcp.ocr_server
python -m app.mcp.image_server
python -m app.mcp.custom_server
```

MCP clients should launch these commands themselves rather than starting them
manually. Copy `mcp-servers.example.json` into your client's MCP configuration
and replace its `cwd` placeholders with this repository's absolute path.
Filesystem access is restricted to `AIOS_MCP_WORKSPACE_ROOT` (the repository by
default), and `.env`/`.git` are denied. Writes remain disabled unless
`AIOS_MCP_FILESYSTEM_WRITE=true`. Python execution is isolated, timed out, and
rejects imports, file access, private attributes, and dynamic evaluation.
Terminal execution is shell-free and limited to an allowlist. Browser requests
block private and local network addresses. Git, GitHub, and Docker servers are
read-only: they expose repository status/history, public or token-authenticated
GitHub metadata, and container/image/log inspection without mutation tools.
Kubernetes is limited to contexts, resource inspection, descriptions, and logs.
PostgreSQL connections force read-only transactions, SQLite opens in read-only
mode inside the workspace, and Redis access is confined to the `aios:` prefix.
Cloud inventory uses installed and authenticated `aws`, `az`, or `gcloud` CLIs
and only exposes identity, resource, and storage listing commands. Slack and
Notion use `SLACK_BOT_TOKEN` and `NOTION_TOKEN` for read-only queries. REST URLs
use the browser server's public-network checks; optionally restrict them further
with `AIOS_MCP_REST_HOSTS`, and opt into mutations with
`AIOS_MCP_REST_WRITE=true`. OCR uses Tesseract when available or command
templates in `AIOS_OCR_COMMAND`/`AIOS_PDF_OCR_COMMAND` (`{file}` and
`{language}` placeholders are supported). Image output is disabled unless
`AIOS_MCP_IMAGE_WRITE=true`.

Custom stdio servers are read from `AIOS_MCP_CUSTOM_CONFIG` (default
`mcp-servers.json`). Listing configured servers is safe by default; spawning or
calling them requires `AIOS_MCP_CUSTOM_ENABLED=true`, and the executable must be
listed by `AIOS_MCP_CUSTOM_COMMANDS`. Config files and server working directories
must remain inside the workspace.

## Planner and specialist agents

`POST /api/orchestrate` runs task planning, capability checks, dependency
ordering, decision routing, and specialist-agent dispatch. The implemented
specialists cover memory, local RAG, public web browsing, coding inspection and
changes, allowlisted terminal commands, workspace-confined filesystem
operations, vision/OCR, read-only databases, explicit registered-tool calls,
and post-execution reflection. Structured operation details can be supplied under
`context.agent_input`, or per agent under `context.agent_inputs`:

```json
{
  "objective": "Search the workspace for TODO comments",
  "context": {
    "agent": "filesystem",
    "agent_input": {"operation": "search", "query": "TODO", "path": "."}
  }
}
```

Filesystem and coding writes still require `AIOS_MCP_FILESYSTEM_WRITE=true`.
Terminal commands remain limited by `AIOS_MCP_TERMINAL_COMMANDS`, and browser
requests retain public-network validation. Database agents preserve the existing
read-only SQL and Redis namespace restrictions. Every executed specialist result
is passed through the reflection agent for a verdict and success-criteria review.
An independent reviewer then applies the final quality gate. Failed specialist
executions are retried once by default and can be configured per request with
`context.max_retries` from 0 to 3. Use a list under
`context.agent_inputs.<agent>` to provide different structured input for each
attempt. The final response merges every attempt, reflection, reviewer verdict,
plan ID, retry count, and status into `final_result`.

Import existing local sessions and conversations once before starting the app:

```powershell
python -m app.import_json_store
```
