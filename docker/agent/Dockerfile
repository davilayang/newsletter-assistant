FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# livekit-rtc requires libgobject-2.0 (glib) for its native FFI library
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
  && rm -rf /var/lib/apt/lists/*

# Install dependencies — this layer is cached until pyproject.toml changes.
# Run `uv lock` locally and commit uv.lock for reproducible builds.
COPY pyproject.toml ./
RUN uv sync --no-dev --no-install-project

ENV PATH="/app/.venv/bin:$PATH"

COPY src/ ./src/
COPY config/ ./config/

ENTRYPOINT [".venv/bin/python", "-m"]
CMD ["src.frontend.agent", "start"]
