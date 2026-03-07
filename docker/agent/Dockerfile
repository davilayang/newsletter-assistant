FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# livekit-rtc requires libgobject-2.0 (glib) for its native FFI library
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
  && rm -rf /var/lib/apt/lists/*

# Install dependencies — this layer is cached until pyproject.toml / uv.lock change.
# Copy workspace manifests needed to resolve newsletter-agent.
COPY pyproject.toml uv.lock ./
COPY packages/core/pyproject.toml packages/core/pyproject.toml
COPY packages/knowledge/pyproject.toml packages/knowledge/pyproject.toml
COPY services/agent/pyproject.toml services/agent/pyproject.toml
RUN uv sync --frozen --no-dev --no-install-workspace --package newsletter-agent

ENV PATH="/app/.venv/bin:$PATH"

COPY packages/core/src/ packages/core/src/
COPY packages/knowledge/src/ packages/knowledge/src/
COPY services/agent/src/ services/agent/src/
COPY config/ ./config/

# Install workspace packages (editable) after source is copied
RUN uv sync --frozen --no-dev --package newsletter-agent

ENTRYPOINT [".venv/bin/python", "-m"]
CMD ["agent.agent", "start"]
