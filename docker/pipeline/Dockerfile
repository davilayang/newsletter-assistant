FROM python:3.13-slim

# Firefox shared libraries required by camoufox (headless browser).
# On Debian Bookworm, libasound2 is a transitional package for libasound2t64.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libx11-6 \
    libxcb1 \
    libxext6 \
    libasound2 \
    ca-certificates \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Install dependencies — this layer is cached until pyproject.toml / uv.lock change.
# Copy workspace manifests needed to resolve newsletter-pipeline.
COPY pyproject.toml uv.lock ./
COPY packages/core/pyproject.toml packages/core/pyproject.toml
COPY packages/knowledge/pyproject.toml packages/knowledge/pyproject.toml
COPY services/pipeline/pyproject.toml services/pipeline/pyproject.toml
RUN uv sync --frozen --no-dev --no-install-workspace --package newsletter-pipeline

ENV PATH="/app/.venv/bin:$PATH"

# Pre-download the camoufox Firefox binary (~300 MB) so containers start
# without fetching it at runtime. Re-run `docker build` to refresh.
RUN camoufox fetch

COPY packages/core/src/ packages/core/src/
COPY packages/knowledge/src/ packages/knowledge/src/
COPY services/pipeline/src/ services/pipeline/src/
COPY config/ ./config/

# Install workspace packages (editable) after source is copied
RUN uv sync --frozen --no-dev --package newsletter-pipeline

CMD ["python", "-m", "knowledge.pipeline"]
