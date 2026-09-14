# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.12.13 AS uv

FROM python:3.12-slim AS builder
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app
COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY alembic.ini ./
COPY migrations ./migrations
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim AS runtime
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VERA_API_HOST=0.0.0.0 \
    VERA_API_PORT=8000
RUN groupadd --system vera && useradd --system --gid vera --home-dir /app vera
WORKDIR /app
COPY --from=builder --chown=vera:vera /app/.venv /app/.venv
COPY --from=builder --chown=vera:vera /app/alembic.ini /app/alembic.ini
COPY --from=builder --chown=vera:vera /app/migrations /app/migrations
USER vera
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=2)"
CMD ["uvicorn", "vera.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
