# Run the complete application with Docker

Use Docker Desktop with Linux containers. One image, `agromind:local`, contains
both Python applications, their frontend files, PostgreSQL drivers, the ChromaDB
client/server, Git, Poppler, and Tesseract. Containers run as a non-root user.

## First-time setup

From the project root in PowerShell:

```powershell
if (-not (Test-Path .env.docker)) { Copy-Item .env.docker.example .env.docker }
```

Edit `.env.docker`. Replace each `CHANGE_ME` secret with a different random value:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Use a URL-safe database password, such as the generated hex value. Add your model
API key to `GROQ_API_KEY` or `GEMINI_API_KEY`. Keep this file private.
Compose supplies the container database, Redis, and Chroma addresses automatically.
Native `.env` settings and data are not included in the image.

## Build and start

```powershell
docker compose --env-file .env.docker build
docker compose --env-file .env.docker up -d
```

Open:

- AgroMind: **http://127.0.0.1:18080**
- AI Tutor: **http://127.0.0.1:18010**

The Docker ports differ from native Python ports so both setups can coexist.
To change them, edit `AGROMIND_DOCKER_PORT` and `AI_TUTOR_DOCKER_PORT` in
`.env.docker`, then run `up -d` again. AgroMind's chatbot iframe uses the Tutor port.
Each app has its own signup and login. PostgreSQL tables are initialized automatically.

Compose starts PostgreSQL, Redis, ChromaDB, the migration job, AI Tutor (`app`),
AgroMind (`portal`), and the worker, scheduler, and monitoring processes. Workers
can access external APIs. Database and vector ports are not published to the host.
The optional existing Nginx TLS service runs only with `--profile tls` and needs
certificates; it is not required for the localhost setup.

## Verify and manage

```powershell
docker compose --env-file .env.docker ps
Invoke-RestMethod http://127.0.0.1:18080/api/health
Invoke-RestMethod http://127.0.0.1:18010/api/v1/health
docker compose --env-file .env.docker logs --tail 50 app portal chroma
```

To rebuild after a code change:

```powershell
docker compose --env-file .env.docker up -d --build
```

Stop the application while keeping data:

```powershell
docker compose --env-file .env.docker stop
```

Named volumes preserve PostgreSQL records, Chroma vectors, Redis state, AI Tutor
files, and AgroMind uploads. Existing native records and older Docker volumes are
not imported automatically. Avoid `down -v` unless you intend to delete this
stack's saved data.

The default image has no Qdrant service or client dependency. For a one-time import
from an old Qdrant instance, install `requirements-qdrant-migration.txt` in a native
Python environment and use `python -m app.import_vectors_to_chroma --source qdrant`.
No existing Qdrant containers or data are removed by this setup.

## Run the container tests

```powershell
docker compose --env-file .env.docker exec -T portal python scripts/test_container.py
```

This creates a disposable test checkout. PostgreSQL test records are rolled back,
and the Chroma integration check deletes its own temporary collection.
