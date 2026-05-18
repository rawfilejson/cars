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

import psycopg
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.schemas import HealthCheck
from src.api.search import router as search_router
from src.api.stats import router as stats_router
from src.common.config import DATABASE_URL, r2_is_configured


# Production რეჟიმის ცნობა — Fly.io ან Render
IS_PRODUCTION = bool(os.getenv("FLY_APP_NAME") or os.getenv("PRODUCTION"))

logging.basicConfig(
    level=logging.INFO if IS_PRODUCTION else logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("API starting up...")
    yield
    log.info("API shutting down...")


app = FastAPI(
    title="ქართული მანქანების ბაზა — backend API",
    description="ანონიმური, უფასო ძიება ვინ კოდით / ნომრით / ტექსტით",
    version="1.0.0",
    lifespan=lifespan,
)


# CORS — production-ში მკაცრად შეცვალე
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        # production frontend URL აქ
    ],
    allow_credentials=False,                    # auth აღარ გვაქვს
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


app.include_router(search_router)
app.include_router(stats_router)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """ნებისმიერი unexpected exception → 500 + უარყოფა stack trace-ის."""
    log.exception("Unhandled exception on %s %s", request.method, request.url.path)

    if IS_PRODUCTION:
        return JSONResponse(
            status_code=500,
            content={"detail": "შიდა შეცდომა — ცადე ცოტა ხანში"},
        )
    return JSONResponse(
        status_code=500,
        content={"detail": f"{type(exc).__name__}: {exc}"},
    )


@app.get("/healthz", response_model=HealthCheck)
def health_check() -> HealthCheck:
    """Health check — DB და R2 ხელმისაწვდომია?"""
    db_ok = False
    try:
        with psycopg.connect(DATABASE_URL, connect_timeout=3) as conn:
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
