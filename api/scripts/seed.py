"""Seed-Skript mit erweiterten Demo-Daten."""

from __future__ import annotations
import asyncio
import os
from pathlib import Path
from typing import Sequence
import asyncpg


async def ensure_schema(conn: asyncpg.Connection) -> None:
    """Schema sicherstellen."""
    exists = await conn.fetchval("SELECT to_regclass('public.users')")
    if not exists:
        schema_path = os.environ.get("SCHEMA_PATH", "/app/schema.sql")
        ddl = Path(schema_path).read_text(encoding="utf-8")
        await conn.execute(ddl)


async def seed() -> None:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL is not set")
    db_url_clean = db_url.replace("postgresql+asyncpg", "postgresql")
    conn = await asyncpg.connect(db_url_clean)

    await ensure_schema(conn)

    # Ankerpunkte mit realistischen Positionen (in Metern)
    anchors: Sequence[tuple[str, str, float, float, float]] = [
        ("A-01", "NW Ecke", 0.0, 0.0, 0.0),
        ("A-02", "NE Ecke", 30.0, 0.0, 0.0),
        ("A-03", "SW Ecke", 0.0, 25.0, 0.0),
        ("A-04", "SE Ecke", 30.0, 25.0, 0.0),
        ("A-05", "Mitte", 15.0, 12.5, 0.0),
    ]
    for aid, name, x, y, z in anchors:
        await conn.execute(
            "INSERT INTO anchors (id, name, x, y, z) VALUES ($1, $2, $3, $4, $5) ON CONFLICT (id) DO NOTHING",
            aid, name, x, y, z,
        )

    # Wearables mit Metadaten
    wearables: Sequence[tuple[str, str, str]] = [
        ("W-01", "Max Müller", "worker"),
        ("W-02", "Anna Schmidt", "worker"),
        ("W-03", "Tom Fischer", "supervisor"),
    ]
    for uid, person, role in wearables:
        await conn.execute(
            "INSERT INTO wearables (uid, person_ref, role) VALUES ($1, $2, $3) ON CONFLICT (uid) DO NOTHING",
            uid, person, role,
        )

    # Admin-Benutzer
    from api.auth import get_password_hash
    password_hash = get_password_hash("admin")
    await conn.execute(
        "INSERT INTO users (username, password_hash, role) VALUES ($1, $2, $3) ON CONFLICT (username) DO NOTHING",
        "admin", password_hash, "admin",
    )

    print("✓ Schema und Testdaten erstellt")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(seed())
