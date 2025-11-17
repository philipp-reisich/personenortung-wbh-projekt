# path: api/scripts/seed.py

from __future__ import annotations
import asyncio
import os
from pathlib import Path
from typing import Sequence
import asyncpg


async def ensure_schema(conn: asyncpg.Connection) -> None:
    exists = await conn.fetchval("SELECT to_regclass('public.users')")
    if not exists:
        schema_path = os.environ.get("SCHEMA_PATH", "/app/schema.sql")
        ddl = Path(schema_path).read_text(encoding="utf-8")
        await conn.execute(ddl)


async def seed() -> None:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL is not set")
    # async SQLAlchemy URLs -> asyncpg URL
    db_url_clean = db_url.replace("postgresql+asyncpg", "postgresql")
    conn = await asyncpg.connect(db_url_clean)

    try:
        await ensure_schema(conn)

        anchors: Sequence[tuple[str, str, float, float, float]] = [
            ("A-01", "Anchor 1", 5.0, 5.0, 2.5),
            ("A-02", "Anchor 2", 5.0, 28.0, 2.5),
        ]
        for aid, name, x, y, z in anchors:
            await conn.execute(
                """
                INSERT INTO anchors (id, name, x, y, z)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (id) DO NOTHING
                """,
                aid,
                name,
                x,
                y,
                z,
            )

        wearables: Sequence[tuple[str, str, str]] = [
            ("W-01", "alice", "builder 1"),
            ("W-02", "bob", "builder 2"),
        ]
        for uid, person, role in wearables:
            await conn.execute(
                """
                INSERT INTO wearables (uid, person_ref, role)
                VALUES ($1, $2, $3)
                ON CONFLICT (uid) DO NOTHING
                """,
                uid,
                person,
                role,
            )

        from api.auth import get_password_hash

        password_hash = get_password_hash("admin")
        await conn.execute(
            """
            INSERT INTO users (username, password_hash, role)
            VALUES ($1, $2, $3)
            ON CONFLICT (username) DO NOTHING
            """,
            "admin",
            password_hash,
            "admin",
        )

        print("✓ Schema geladen & Seed-Daten (Anchors, Wearables, Admin) erstellt")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(seed())
