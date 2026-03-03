FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Install dependencies — this layer is cached until pyproject.toml changes.
# Run `uv lock` locally and commit uv.lock for reproducible builds.
COPY pyproject.toml ./
RUN uv sync --no-dev --no-install-project

ENV PATH="/app/.venv/bin:$PATH"

COPY src/ ./src/
COPY config/ ./config/

CMD ["python", "-m", "src.agent.agent"]
