FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Install dependencies — this layer is cached until pyproject.toml / uv.lock change.
# Copy workspace manifests needed to resolve newsletter-frontend.
COPY pyproject.toml uv.lock ./
COPY packages/core/pyproject.toml packages/core/pyproject.toml
COPY packages/knowledge/pyproject.toml packages/knowledge/pyproject.toml
COPY services/frontend/pyproject.toml services/frontend/pyproject.toml
RUN uv sync --frozen --no-dev --no-install-workspace --package newsletter-frontend

ENV PATH="/app/.venv/bin:$PATH"
# Bind to all interfaces inside a container; defaults to 127.0.0.1 locally.
ENV APP_HOST="0.0.0.0"

COPY packages/core/src/ packages/core/src/
COPY packages/knowledge/src/ packages/knowledge/src/
COPY services/frontend/src/ services/frontend/src/
COPY config/ ./config/

# Install workspace packages (editable) after source is copied
RUN uv sync --frozen --no-dev --package newsletter-frontend

EXPOSE 8080

ENTRYPOINT [".venv/bin/python", "-m"]
CMD ["frontend.app"]
