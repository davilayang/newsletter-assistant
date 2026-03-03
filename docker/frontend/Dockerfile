FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Install dependencies — this layer is cached until pyproject.toml changes.
# Run `uv lock` locally and commit uv.lock for reproducible builds.
COPY pyproject.toml ./
RUN uv sync --no-dev --no-install-project

ENV PATH="/app/.venv/bin:$PATH"
# Bind to all interfaces inside a container; defaults to 127.0.0.1 locally.
ENV APP_HOST="0.0.0.0"

COPY src/ ./src/
COPY config/ ./config/

EXPOSE 8080

CMD ["python", "-m", "src.frontend.app"]
