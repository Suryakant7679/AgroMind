# AI Tutor

AI Tutor is a locally hosted, multi-user chatbot for conversational learning, document Q&A, and mathematical explanations. It provides authenticated chat, streaming responses, PDF/text extraction, retrieval-backed context, and rendered LaTeX equations.

## Local architecture

Python serves `web/` and `/api/v1/*` together at **http://localhost:8000**.
No separate frontend server or frontend build is required.

```text
Browser -> localhost:8000 -> Python HTTP server
                            |-- static frontend and authenticated API
                            |-- PostgreSQL / Redis / Qdrant
                            |-- local uploads and memory
                            `-- external model provider
```

The application and data services can run locally. Model APIs, web search,
CDN-loaded KaTeX and optional external integrations still need internet access.
Their implementations have not been replaced.

## Current features

- User-scoped conversations and chat history
- Streaming assistant responses with cancellation and recovery
- PDF and text uploads with extracted document context
- Hidden attachment context: extracted PDF text is not displayed as the user's prompt
- Retrieval-backed document and conversation context through Qdrant
- Mathematical answers rendered with KaTeX/LaTeX
- Markdown, syntax-highlighted code, speech input, and text-to-speech
- Multiple AI providers with automatic fallback and task-aware routing
- Redis-backed sessions, caching, rate limits, and stream state
- PostgreSQL migrations and durable user/chat storage
- Health, usage, search, planning, orchestration, and observability APIs

## Start on localhost (PowerShell)

For the complete stack including local PostgreSQL, Redis, Qdrant, workers and
PDF/OCR executables, follow [Local Docker startup](docs/DEPLOYMENT.md).

For native Python startup, install Python 3.12+ and provide local PostgreSQL,
Redis and Qdrant services. From the project root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Edit `.env`, preserving credentials and existing data. Configure local endpoints:

```dotenv
AIOS_HOST=127.0.0.1
AIOS_PORT=8000
AIOS_AUTH_REQUIRED=true
AIOS_STORAGE_BACKEND=postgres
DATABASE_URL=postgresql://USER:PASSWORD@127.0.0.1:5432/aios
REDIS_URL=redis://127.0.0.1:6379/0
AIOS_VECTOR_BACKEND=qdrant
QDRANT_URL=http://127.0.0.1:6333
QDRANT_API_KEY=
AIOS_PROVIDER=auto
```

Substitute your local database credentials. Keep `GROQ_API_KEY` and/or
`GEMINI_API_KEY` configured, along with any existing model overrides. Configure
a stable random `AIOS_JWT_SECRET` of at least 32 bytes; preserve an existing
secret if existing tokens should remain valid. For native PDF/OCR support,
install Poppler and Tesseract so `pdftotext`, `pdftoppm` and `tesseract` are on
PATH, or use the existing extraction-command settings.

Start the frontend and backend together:

```powershell
.\.venv\Scripts\python.exe -m app.main
```

Open **http://localhost:8000** and sign up or log in. The health endpoint is
http://localhost:8000/api/v1/health. PostgreSQL migrations run at startup.
Do not open `web/index.html` directly because its API calls need the server.

In two additional terminals, run one background command in each:

```powershell
.\.venv\Scripts\python.exe -m app.workers --worker all
.\.venv\Scripts\python.exe -m app.workers --worker scheduler
```

The `all` worker includes health monitoring. Redis must be reachable. Stop each
foreground process with Ctrl+C. Existing JSON storage modes remain available
for lightweight local use; they do not provide the complete database stack.
Existing `.env` files are not changed automatically. Switching database URLs
does not migrate existing accounts or chats; preserve and migrate data separately.

## API overview

All routes use the `/api/v1` prefix.

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/health` | Service, provider, and Redis status |
| `GET/POST` | `/api/v1/conversations` | List or create conversations |
| `POST` | `/api/v1/chat` | Send a normal or streaming chat request |
| `GET/POST` | `/api/v1/uploads` | List or upload artifacts |
| `GET` | `/api/v1/conversations/search` | Search conversation history |
| `GET` | `/api/v1/observability` | Runtime health and metrics |
| `GET` | `/api/v1/usage` | Provider token and cost estimates |

## Testing

Run the complete suite:

```powershell
python -m pytest -q
```

Check frontend JavaScript syntax:

```powershell
node --check web/app.js
```

Local cleanup verification: **231 tests passed, 1 skipped**; JavaScript syntax and Compose configuration checks passed. A real Chrome localhost smoke test passed signup, authenticated text upload, streamed chat, persistence, retrieval and saved login using temporary JSON stores and a mocked model. Docker Desktop was not running, so the full container stack and real provider calls were not exercised. See [the bug audit](docs/BUG_AUDIT.md) for existing limitations.

## Project structure

```text
app/             Python backend, authentication, storage, LLM routing, RAG, and agents
web/             Static frontend served by Python
migrations/      PostgreSQL schema migrations
tests/           Automated backend and frontend regression tests
docs/            Deployment documentation
Dockerfile       Local/self-hosted application image
.env.example     Local configuration template
.env.production.example  Full local Docker stack template
```

## Local persistence

Preserve PostgreSQL, Redis and Qdrant volumes and the application data directory.
Uploads and some memory/metrics remain local files; back up those alongside the
database. External AI services retain their own quotas and rate limits.

## Security

- Never commit `.env`, database passwords, Redis credentials, JWT secrets, or provider API keys.
- Rotate any credential that has been posted publicly.
- Keep write-capable MCP and execution tools disabled on the public deployment unless they are explicitly secured.
- Use long, random production values for `AIOS_JWT_SECRET`.

## License

No license has been declared. All rights remain with the repository owner unless a license is added later.

## Audit and MCP tools

- [Verified bugs, fixes, and remaining work](docs/BUG_AUDIT.md)
- [Installed MCP servers and setup](docs/MCP_SETUP.md)
