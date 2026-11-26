# syntax=docker/dockerfile:1
FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# uv: fast, reproducible installs from the lockfile
COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /usr/local/bin/uv

WORKDIR /app

# Dependency layer first so code edits don't bust the cache
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY src/ src/
COPY config.yaml ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

# Surfaced at /healthz so a deploy can be traced to a commit
ARG GIT_SHA=dev
ENV GIT_SHA=${GIT_SHA}

EXPOSE 8080
CMD ["uvicorn", "gerry.app.main:app", "--host", "0.0.0.0", "--port", "8080"]
