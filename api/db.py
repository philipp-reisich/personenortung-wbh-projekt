# path: personenortung-wbh-projekt/api/db.py
"""Database connection helper functions using asyncpg.

The API uses an async connection pool. A dependency is provided to
FastAPI endpoints to acquire and release a database connection.
"""

import asyncpg
from fastapi import Depends
from typing import AsyncGenerator

from .config import get_settings


class Database:
    """Manages a connection pool to PostgreSQL using asyncpg."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        """Create the connection pool if it doesn't already exist."""
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                str(self.dsn), min_size=1, max_size=10
            )

    async def disconnect(self) -> None:
        """Close the pool and release all connections."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def get_connection(self) -> AsyncGenerator[asyncpg.Connection, None]:
        """Yield a connection from the pool.

        This helper is designed to be used as a FastAPI dependency. It
        transparently acquires and releases a connection from the pool.
        """
        if self._pool is None:
            await self.connect()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            yield conn


_db_instance: Database | None = None


def get_db_instance() -> Database:
    """Return a global Database instance, creating it if necessary."""
    global _db_instance
    if _db_instance is None:
        settings = get_settings()
        _db_instance = Database(settings.database_url)
    return _db_instance


async def get_db_connection() -> AsyncGenerator[asyncpg.Connection, None]:
    """FastAPI dependency that yields a database connection."""
    db = get_db_instance()
    async for conn in db.get_connection():
        yield conn
