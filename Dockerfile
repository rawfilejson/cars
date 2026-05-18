# Backend production image
# გამოიყენე: Fly.io / Render / Railway / Docker Compose
FROM python:3.12-slim AS base

# OS deps for Playwright (only needed if parser runs in same image — for now backend only)
# პარსერი ცალკე GitHub Actions-ში მუშაობს, აქ მხოლოდ backend.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# uv ინსტალაცია (სწრაფი Python package manager)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /app

# Dependencies ჯერ — caching-ისთვის
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# კოდი
COPY src/ ./src/
COPY db/ ./db/

# Production რეჟიმის flag
ENV PRODUCTION=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

# Fly.io-ის სტანდარტი — port 8080
CMD ["uv", "run", "uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
