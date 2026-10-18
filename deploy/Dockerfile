# Team 12 tester image. Build from the repo root:
#   docker build -f deploy/Dockerfile -t team12-tester .
# Runs one uvicorn worker (one process per SQLite file); the database lives on the /data volume.

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.2 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first, so code changes do not reinstall them.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY tester ./tester
RUN uv sync --locked --no-dev

RUN useradd --system --uid 10001 --no-create-home tester \
    && mkdir /data && chown tester /data
USER tester

ENV PATH="/app/.venv/bin:$PATH" \
    APP_ENV=production \
    TESTER_DB_PATH=/data/tester.db \
    ROOT_PATH=/tester \
    PORT=8001

VOLUME /data
EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/openapi.json', timeout=4)"

# ROOT_PATH must match the prefix the reverse proxy strips (empty when served at the host root).
CMD ["sh", "-c", "exec uvicorn tester.main:create_app --factory --host 0.0.0.0 --port \"$PORT\" --workers 1 --root-path \"$ROOT_PATH\""]
