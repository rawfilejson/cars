"""
FastAPI მთავარი ფაილი — backend-ის entry point.

გაშვება ლოკალურად:
    uv run uvicorn src.api.main:app --reload --port 8765

ვებსაიტი:
    http://localhost:8765/docs    — Swagger UI (auto-generated API docs)
    http://localhost:8765/healthz — health check
    http://localhost:8765/stats   — total cars count
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

from src.api.schemas import HealthCheck
from src.api.search import router as search_router, car_router
from src.api.stats import router as stats_router
from src.common.config import r2_is_configured


# Production რეჟიმი — Render-ი PRODUCTION=1-ს აყენებს (იხ. render.yaml)
IS_PRODUCTION = bool(os.getenv("PRODUCTION"))

logging.basicConfig(
    level=logging.INFO if IS_PRODUCTION else logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("API starting up...")
    # Warm the pool on startup so the first user request doesn't pay the
    # connection setup cost (~2s on Supabase)
    from src.api.db_pool import get_pool, close_pool
    get_pool()
    yield
    log.info("API shutting down...")
    close_pool()


app = FastAPI(
    title="ქართული მანქანების ბაზა — backend API",
    description="ანონიმური, უფასო ძიება ვინ კოდით / ნომრით / ტექსტით",
    version="1.0.0",
    lifespan=lifespan,
    default_response_class=ORJSONResponse,
)


# CORS — production-ში მკაცრად შეცვალე
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        # production frontend
        "https://cars.demee-metreveli.workers.dev",
        # local dev
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:5500",
        "http://localhost:8080",
        "http://127.0.0.1:5500",
        "http://127.0.0.1:8080",
    ],
    allow_credentials=False,                    # auth აღარ გვაქვს
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


app.include_router(search_router)
app.include_router(car_router)
app.include_router(stats_router)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """ნებისმიერი unexpected exception → 500 + უარყოფა stack trace-ის."""
    log.exception("Unhandled exception on %s %s", request.method, request.url.path)

    if IS_PRODUCTION:
        return ORJSONResponse(
            status_code=500,
            content={"detail": {"code": "server_error"}},
        )
    return ORJSONResponse(
        status_code=500,
        content={"detail": f"{type(exc).__name__}: {exc}"},
    )


@app.get("/healthz", response_model=HealthCheck)
def health_check() -> HealthCheck:
    """Health check — DB და R2 ხელმისაწვდომია?"""
    from src.api.db_pool import connection

    db_ok = False
    try:
        with connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        db_ok = True
    except Exception:
        pass

    return HealthCheck(
        status="ok" if db_ok else "degraded",
        db=db_ok,
        r2=r2_is_configured(),
    )


@app.get("/")
def root() -> dict:
    return {
        "service": "ქართული მანქანების ბაზა",
        "docs": "/docs",
        "health": "/healthz",
        "stats": "/stats",
    }
