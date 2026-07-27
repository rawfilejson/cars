# Shared psycopg connection pool for the API
# Each search before this opened a fresh TLS connection to Supabase (~2s connect time on top of ~150ms of real query work)
# With a pool that keeps connections warm, that 2s overhead is gone
# The pool is created lazily so module import doesn't block, and closed cleanly via FastAPI lifespan

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from src.common.config import DATABASE_URL


_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            DATABASE_URL,
            min_size=2,
            max_size=6,
            kwargs={"row_factory": dict_row},
            open=True,
            timeout=10.0,
        )
    return _pool


@contextmanager
def connection() -> Iterator[psycopg.Connection]:
    # Yield a pooled connection
    # Auto-returns to pool
    with get_pool().connection() as conn:
        yield conn


def close_pool() -> None:
    # Close the pool - called on FastAPI shutdown.
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
