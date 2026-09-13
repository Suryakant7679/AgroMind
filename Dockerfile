FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    AIOS_HOST=0.0.0.0 \
    AIOS_PORT=8000 \
    AIOS_STORAGE_BACKEND=postgres \
    AIOS_VECTOR_BACKEND=chroma

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates poppler-utils tesseract-ocr \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system aios \
    && useradd --system --gid aios --create-home --home-dir /home/aios aios

WORKDIR /app
COPY requirements.txt pyproject.toml ./
RUN python -m pip install --upgrade pip \
    && python -c "import subprocess, sys, tomllib; deps = tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']; subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt', *deps])"

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY --chown=aios:aios . .
RUN mkdir -p /app/data/uploads /app/data/backups /app/data/worker_state /app/agromind/static/uploads \
    && chown -R aios:aios /app/data /app/agromind/static/uploads

USER aios
EXPOSE 8000
VOLUME ["/app/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).read()" || exit 1

CMD ["python", "-m", "app.main"]