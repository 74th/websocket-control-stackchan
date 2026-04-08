# syntax=docker/dockerfile:1.6
FROM node:25-bookworm-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends git ca-certificates && \
    rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
ENV UV_PYTHON_INSTALL_DIR=/var/uv/python
ENV UV_CACHE_DIR=/var/uv/cache

WORKDIR /app

COPY uv.lock \
    pyproject.toml \
    .

RUN --mount=type=cache,target=/var/uv/cache,uid=0,gid=0,mode=0777 \
    uv sync --frozen --no-install-project

COPY app.py .

USER node

ENV HOME=/home/node
ENV STACKCHAN_WORKSPACE_DIR=/app/workspace

ENTRYPOINT [".venv/bin/uvicorn", "app:app.fastapi", "--host=0.0.0.0", "--port=8000"]
