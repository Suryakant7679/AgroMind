# Complete local Docker startup

The Dockerfile, Compose services, Nginx and backup utilities remain intact.
They support local/self-hosted use and are not tied to a hosting provider.

Start Docker Desktop with Linux containers. In PowerShell at the project root:

```powershell
if (-not (Test-Path .env.production)) { Copy-Item .env.production.example .env.production }
```

Review `.env.production`. Configure `DATABASE_URL` for `postgres:5432`,
`REDIS_URL` for `redis:6379/0`, and `QDRANT_URL` for `http://qdrant:6333`.
Database credentials must match `POSTGRES_USER`, `POSTGRES_PASSWORD` and
`POSTGRES_DB`. Clear `QDRANT_API_KEY` for the default local Qdrant service.
Keep authentication enabled, set a strong stable `AIOS_JWT_SECRET`, configure
`GROQ_API_KEY` and/or `GEMINI_API_KEY`, and replace applicable `CHANGE_ME` values.
The supplied example already uses local service names. Do not overwrite existing
credentials or data; moving a hosted database locally requires a separate import.

Start infrastructure and all background processes:

```powershell
docker compose --env-file .env.production up -d --build postgres redis qdrant migrate worker scheduler monitoring
```

Start the frontend and API together on a loopback-only port:

```powershell
docker compose --env-file .env.production run --rm --no-deps --publish 127.0.0.1:8000:8000 app
```

Open **http://localhost:8000**. The image includes Poppler and Tesseract.
This command uses the normal application and shared data volume, with no TLS
certificates or separate frontend process required. The optional Nginx entrypoint
remains available but is not needed for this localhost HTTP workflow.

The app retains its edge network for external model calls. Existing workers use
an internal backend network; jobs requiring external access (such as SMTP) need
appropriate networking or native workers. No subsystem has been simplified.

Stop the foreground app with Ctrl+C, then stop other services without deleting data:

```powershell
docker compose --env-file .env.production stop
```

Do not remove volumes to stop the application. Native Python startup is in the
[README](../readme.md). Model APIs, web search and CDN assets still use the internet.

## Verification

```powershell
Invoke-RestMethod http://localhost:8000/api/v1/health
node --check web/app.js
python -m pytest -q
```

Open the UI, sign up/log in, send a message, upload a document and reopen history.
Health alone does not verify model credentials or every database operation.
