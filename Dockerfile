# backend production image - works on Render / Fly.io / Railway / Docker Compose
# parser runs in GitHub Actions separately, this image is backend-only
FROM python:3.12-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# uv - fast Python package manager
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /app

# deps first - Docker layer caching
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# app code
COPY src/ ./src/
COPY db/ ./db/

ENV PRODUCTION=1
ENV PYTHONUNBUFFERED=1
# Default port (overridden by $PORT on Render / Fly)
ENV PORT=8080

EXPOSE 8080

# Shell form so $PORT expands at runtime (Render sets it dynamically)
CMD uv run uvicorn src.api.main:app --host 0.0.0.0 --port ${PORT}
