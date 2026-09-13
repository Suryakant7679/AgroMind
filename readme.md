# AgroMind with AI Tutor

AgroMind brings together AI-assisted tools for agriculture, healthcare, and education.
Its chatbot page opens AI Tutor, a learning assistant that can answer questions,
work with uploaded documents, and display mathematical explanations.

Both applications run locally. AgroMind provides the FastAPI portal, while AI Tutor
runs as a separate Python service. They currently have separate accounts and logins.

## What you can do

- Explore AgroMind's domain tools and save generated outputs.
- Chat with AI Tutor and return to previous conversations.
- Upload PDFs or text files and ask questions about their contents.
- Read streamed answers with Markdown, code formatting, and LaTeX equations.
- Use image OCR and browser voice features where supported.

The repository also includes a separate LangGraph workflow for administrative
specialist tasks, background workers, and local Docker configuration.

## How it fits together

```text
Browser
  |
  +-- AgroMind portal       http://127.0.0.1:8000
  |     FastAPI + templates
  |     /chatbot embeds AI Tutor
  |
  +-- AI Tutor             http://127.0.0.1:8010
        Python HTTP server + JavaScript frontend
        |-- PostgreSQL: accounts and conversations
        |-- Redis: temporary state and background queues
        |-- ChromaDB: retrieval records
        `-- External LLM APIs: answer generation
```

AgroMind uses Supabase for its own authentication and data. AI Tutor supports local
JSON storage as well as PostgreSQL. Its retrieval combines hash-based vectors,
keyword matching, and reranking; it does not use a trained embedding model.

## Getting started

The commands below use PowerShell and Python 3.12. Run them from the project root.

### 1. Install dependencies

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

To run AgroMind alongside AI Tutor, also install the dependencies declared in
`pyproject.toml`:

```powershell
.\.venv\Scripts\python.exe -c "import subprocess, sys, tomllib; from pathlib import Path; deps = tomllib.loads(Path('pyproject.toml').read_text())['project']['dependencies']; subprocess.check_call([sys.executable, '-m', 'pip', 'install', *deps])"
```

Node.js is only needed for optional frontend checks and development tools.

### 2. Configure your environment

Create `.env` if it does not already exist:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Edit the file with your own settings. Keep existing credentials if you already
have a working setup.

| Setting | Purpose |
| --- | --- |
| `GROQ_API_KEY` or `GEMINI_API_KEY` | Model access for AI Tutor's automatic provider selection |
| `AIOS_PROVIDER` | Use `auto`, or your intended provider |
| `AIOS_AUTH_REQUIRED` | Set to `true` to protect AI Tutor API requests |
| `AIOS_JWT_SECRET` | Stable, random signing secret of at least 32 bytes |
| `AIOS_STORAGE_BACKEND` | `postgres` for PostgreSQL or `json` for local file storage |
| `DATABASE_URL` | AI Tutor's PostgreSQL connection, when selected |
| `REDIS_URL` | Shared state and workers; required for background jobs |
| `AIOS_VECTOR_BACKEND` | Set to `chroma` to use ChromaDB |
| `AIOS_CHROMA_PATH` | Local Chroma data directory, such as `data/chroma` |
| `CHROMA_HOST` / `CHROMA_PORT` | Shared Chroma server; leave the host blank for single-process embedded storage |
| `SUPABASE_URL` / `SUPABASE_ANON_KEY` | AgroMind authentication and database access |
| `SESSION_SECRET` | AgroMind's session signing secret |

AgroMind also accepts the existing `NEXT_PUBLIC_SUPABASE_*` aliases. Some
administrative operations require `SUPABASE_SERVICE_ROLE_KEY`. Its database
schema is in `supabase/schema.sql`; the launcher does not provision Supabase.

For native PDF extraction and OCR, install Poppler and Tesseract so `pdftotext`,
`pdftoppm`, and `tesseract` are available on PATH. The Docker image includes them.

### 3. Start the application

**AgroMind with AI Tutor:**

```powershell
.\.venv\Scripts\python.exe run_integrated.py
```

Open **http://127.0.0.1:8000**. After signing in to AgroMind, open **Chatbot**.
AI Tutor is also available directly at **http://127.0.0.1:8010** and has its own login.
The launcher waits for AI Tutor to start and stops the child process when you exit.

**AI Tutor on its own:**

```powershell
.\.venv\Scripts\python.exe -m app.main
```

With `AIOS_HOST=127.0.0.1` and `AIOS_PORT=8000`, open **http://127.0.0.1:8000**.
The same process serves the frontend and API; no frontend build is needed.

Choose one startup option at a time to avoid port conflicts. Use **Ctrl+C** to stop.
Model APIs, web search, CDN assets, and hosted Supabase still need internet access.

## Background workers and Docker

For scheduled jobs, start a worker and scheduler in separate terminals:

```powershell
.\.venv\Scripts\python.exe -m app.workers --worker all
.\.venv\Scripts\python.exe -m app.workers --worker scheduler
```

Workers require Redis. Use a shared Chroma server when running multiple processes.

See [Local Docker setup](docs/DEPLOYMENT.md) for AI Tutor, PostgreSQL, Redis,
ChromaDB, and worker startup. The current Docker workflow runs AI Tutor; it does
not launch the combined AgroMind portal automatically.

## Keeping your data

Back up database volumes and the application `data/` directory. Uploaded files,
some memory, and metrics are stored locally. Changing a database URL does not
move existing accounts or conversations.

To copy existing vectors into ChromaDB, stop writers and run the appropriate command:

```powershell
.\.venv\Scripts\python.exe -m app.import_vectors_to_chroma --source json
# Or, with your existing QDRANT_* connection settings:
.\.venv\Scripts\python.exe -m app.import_vectors_to_chroma --source qdrant
```

The migration preserves the source and verifies the copied records. Select
`AIOS_VECTOR_BACKEND=chroma`, restart, and check retrieval before retiring the old store.

Keep `.env` files, API keys, user uploads, and database credentials out of Git.

## Project structure

```text
agromind/          FastAPI portal, domain tools, templates, and Supabase access
app/               AI Tutor backend, authentication, document processing, and retrieval
  agents/          LangGraph planning and specialist workflows
  mcp/             Search and other tool integrations
web/               AI Tutor HTML, CSS, and JavaScript
migrations/        AI Tutor PostgreSQL migrations
supabase/          AgroMind database schema
tests/             Application and regression tests
docs/              Setup, audit, and development notes
scripts/           Backup, restore, and development utilities
run_integrated.py  Starts AgroMind and AI Tutor together
run.py             Starts only AgroMind
Dockerfile         AI Tutor container image
docker-compose.yml Local AI Tutor infrastructure and workers
```

## Tests and further reading

Install pytest in your environment, then run:

```powershell
.\.venv\Scripts\python.exe -m pip install pytest
.\.venv\Scripts\python.exe -m pytest -q
node --check web/app.js
```

Tests cover application behavior, authentication, retrieval, streaming, and tools.
They do not establish live provider availability or production-scale performance.

- [Detailed setup](SETUP.md)
- [Local Docker setup](docs/DEPLOYMENT.md)
- [Known issues and audit](docs/BUG_AUDIT.md)
- [MCP development tools](docs/MCP_SETUP.md)

## License

No license has been declared for this repository.
