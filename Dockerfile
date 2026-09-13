FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    AIOS_HOST=0.0.0.0 \
    AIOS_PORT=8000

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates poppler-utils tesseract-ocr \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system aios \
    && useradd --system --gid aios --create-home --home-dir /home/aios aios

WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

COPY --chown=aios:aios . .
RUN mkdir -p /app/data/uploads /app/data/backups /app/data/worker_state \
    && chown -R aios:aios /app/data

USER aios
EXPOSE 8000
VOLUME ["/app/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).read()" || exit 1

CMD ["python", "-m", "app.main"]