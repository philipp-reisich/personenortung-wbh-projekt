# api/main.py
# Main FastAPI application for BLE RTLS Prototype

from __future__ import annotations

import asyncio
from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
from starlette.requests import Request
from datetime import datetime, timedelta
import asyncpg
import json

from .config import get_settings
from .auth import authenticate_user, create_access_token, get_current_user, get_password_hash
from .db import get_db_connection, get_db_instance
from .schemas import (
    AnchorCreate,
    AnchorOut,
    AnchorStatusOut,
    WearableCreate,
    WearableOut,
    PositionOut,
    ScanOut,
    Token,
    UserCreate,
    UserOut,
)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="BLE RTLS Prototype", version="0.3.2")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    here = Path(__file__).parent
    templates = Jinja2Templates(directory=str(here / "templates"))
    static_path = here / "static"
    if static_path.exists():
        app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

    positions_queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=1000)
    stats_queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=100)
    scans_queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=100)
    anchor_status_queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=100)

    ws_clients = set()
    poll_connection = None
    db_instance = None

    @app.on_event("startup")
    async def startup_event() -> None:
        nonlocal poll_connection, db_instance

        # Initialize main database
        try:
            db_instance = get_db_instance()
            await db_instance.connect()
            print("✓ Database pool connected")
        except Exception as e:
            print(f"❌ Database pool connection failed: {e}")
            raise

        # Poll connection für separate asyncpg
        try:
            db_url = str(settings.database_url)
            db_url_clean = db_url.replace("postgresql+asyncpg", "postgresql")
            poll_connection = await asyncpg.connect(db_url_clean)
            print("✓ Poll connection established")
        except Exception as e:
            print(f"❌ Poll connection failed: {e}")
            poll_connection = None

        # Task 1: Poll Positions
        async def poll_positions() -> None:
            nonlocal poll_connection
            while True:
                try:
                    if poll_connection is None or poll_connection.is_closed():
                        db_url = str(settings.database_url)
                        db_url_clean = db_url.replace("postgresql+asyncpg", "postgresql")
                        poll_connection = await asyncpg.connect(db_url_clean)
                        print("✓ Poll connection re-established")

                    now = datetime.utcnow()
                    time_ago = now - timedelta(seconds=10)
                    query = """
                        SELECT DISTINCT ON (uid)
                            id, ts, uid, x, y, z, method, q_score, zone,
                            nearest_anchor_id, dist_m, num_anchors, dists
                        FROM positions
                        WHERE ts > $1
                        ORDER BY uid, ts DESC
                    """
                    rows = await poll_connection.fetch(query, time_ago)

                    if rows:
                        for row in rows:
                            dists_val = row["dists"]
                            if isinstance(dists_val, str):
                                try:
                                    dists_val = json.loads(dists_val)
                                except:
                                    dists_val = {}

                            data = {
                                "type": "position",
                                "id": row["id"],
                                "ts": row["ts"].isoformat(),
                                "uid": row["uid"],
                                "x": float(row["x"]) if row["x"] is not None else None,
                                "y": float(row["y"]) if row["y"] is not None else None,
                                "z": float(row["z"]) if row["z"] is not None else None,
                                "method": row["method"],
                                "q_score": float(row["q_score"]) if row["q_score"] is not None else None,
                                "zone": row["zone"],
                                "nearest_anchor_id": row["nearest_anchor_id"],
                                "dist_m": float(row["dist_m"]) if row["dist_m"] is not None else None,
                                "num_anchors": row["num_anchors"],
                                "dists": dists_val,
                            }
                            try:
                                positions_queue.put_nowait(data)
                            except asyncio.QueueFull:
                                pass

                except Exception as e:
                    print(f"❌ Poll positions error: {e}")
                    poll_connection = None

                await asyncio.sleep(2)

        # Task 2: Poll Stats
        async def poll_stats() -> None:
            while True:
                try:
                    if db_instance and db_instance._pool:
                        async with db_instance._pool.acquire() as conn:
                            active_devices = await conn.fetchval(
                                "SELECT COUNT(DISTINCT uid) FROM positions WHERE ts > NOW() - INTERVAL '5 minutes'"
                            )
                            anchors_count = await conn.fetchval("SELECT COUNT(*) FROM anchors")
                            wearables_count = await conn.fetchval("SELECT COUNT(*) FROM wearables")
                            total_positions = await conn.fetchval(
                                "SELECT COUNT(*) FROM positions WHERE ts > NOW() - INTERVAL '1 day'"
                            )
                            emergency_count = await conn.fetchval(
                                "SELECT COUNT(*) FROM events WHERE type = 'emergency' AND ts > NOW() - INTERVAL '1 hour'"
                            )

                            data = {
                                "type": "stats",
                                "active_devices": active_devices or 0,
                                "total_anchors": anchors_count or 0,
                                "total_wearables": wearables_count or 0,
                                "total_positions": total_positions or 0,
                                "emergency_count": emergency_count or 0,
                                "ts": datetime.utcnow().isoformat()
                            }
                            try:
                                stats_queue.put_nowait(data)
                            except asyncio.QueueFull:
                                pass

                except Exception as e:
                    print(f"❌ Poll stats error: {e}")

                await asyncio.sleep(10)

        # Task 3: Poll Scans
        async def poll_scans() -> None:
            while True:
                try:
                    if db_instance and db_instance._pool:
                        async with db_instance._pool.acquire() as conn:
                            query = """
                            SELECT
                                uid,
                                (SELECT rssi FROM scans s2 WHERE s2.uid=s.uid AND s2.rssi IS NOT NULL ORDER BY ts DESC LIMIT 1) AS last_rssi,
                                (SELECT battery FROM scans s3 WHERE s3.uid=s.uid AND s3.battery IS NOT NULL ORDER BY ts DESC LIMIT 1) AS last_battery,
                                (SELECT temp_c FROM scans s4 WHERE s4.uid=s.uid AND s4.temp_c IS NOT NULL ORDER BY ts DESC LIMIT 1) AS last_temp_c,
                                (SELECT tx_power_dbm FROM scans s5 WHERE s5.uid=s.uid AND s5.tx_power_dbm IS NOT NULL ORDER BY ts DESC LIMIT 1) AS last_tx_power,
                                (SELECT emergency FROM scans s6 WHERE s6.uid=s.uid AND s6.emergency IS NOT NULL ORDER BY ts DESC LIMIT 1) AS last_emergency,
                                MAX(s.ts) AS last_seen
                            FROM scans s
                            GROUP BY s.uid
                            """
                            rows = await conn.fetch(query)

                            for row in rows:
                                data = {
                                    "type": "scan",
                                    "uid": row["uid"],
                                    "last_rssi": float(row["last_rssi"]) if row["last_rssi"] is not None else None,
                                    "last_battery": float(row["last_battery"]) if row["last_battery"] is not None else None,
                                    "last_temp_c": float(row["last_temp_c"]) if row["last_temp_c"] is not None else None,
                                    "last_tx_power": row["last_tx_power"],
                                    "last_emergency": row["last_emergency"],
                                    "last_seen": row["last_seen"].isoformat() if row["last_seen"] else None,
                                    "ts": datetime.utcnow().isoformat()
                                }
                                try:
                                    scans_queue.put_nowait(data)
                                except asyncio.QueueFull:
                                    pass

                except Exception as e:
                    print(f"❌ Poll scans error: {e}")

                await asyncio.sleep(15)

        # Task 4: Poll Anchor Status
        async def poll_anchor_status() -> None:
            while True:
                try:
                    if db_instance and db_instance._pool:
                        async with db_instance._pool.acquire() as conn:
                            query = """
                            SELECT DISTINCT ON (anchor_id)
                                anchor_id, ts, ip, fw, uptime_s, wifi_rssi, heap_free, heap_min,
                                chip_temp_c, tx_power_dbm, ble_scan_active
                            FROM anchor_status
                            ORDER BY anchor_id, ts DESC
                            """
                            rows = await conn.fetch(query)

                            for row in rows:
                                data = {
                                    "type": "anchor_status",
                                    "anchor_id": row["anchor_id"],
                                    "ts": row["ts"].isoformat() if row["ts"] else None,
                                    "ip": str(row["ip"]) if row["ip"] else None,
                                    "fw": row["fw"],
                                    "uptime_s": row["uptime_s"],
                                    "wifi_rssi": row["wifi_rssi"],
                                    "heap_free": row["heap_free"],
                                    "heap_min": row["heap_min"],
                                    "chip_temp_c": float(row["chip_temp_c"]) if row["chip_temp_c"] is not None else None,
                                    "tx_power_dbm": row["tx_power_dbm"],
                                    "ble_scan_active": row["ble_scan_active"],
                                    "update_ts": datetime.utcnow().isoformat()
                                }
                                try:
                                    anchor_status_queue.put_nowait(data)
                                except asyncio.QueueFull:
                                    pass

                except Exception as e:
                    print(f"❌ Poll anchor status error: {e}")

                await asyncio.sleep(15)

        asyncio.create_task(poll_positions())
        asyncio.create_task(poll_stats())
        asyncio.create_task(poll_scans())
        asyncio.create_task(poll_anchor_status())
        print("✓ All poll tasks started")

    @app.on_event("shutdown")
    async def shutdown_event() -> None:
        nonlocal poll_connection
        if poll_connection and not poll_connection.is_closed():
            await poll_connection.close()
            print("✓ Poll connection closed")
        if db_instance:
            await db_instance.disconnect()
            print("✓ Database pool disconnected")

    # ==================== ROUTES ====================

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return templates.TemplateResponse("index.html", {"request": request})

    @app.get("/anchors", response_model=list[AnchorOut])
    async def list_anchors(conn: asyncpg.Connection = Depends(get_db_connection)):
        try:
            rows = await conn.fetch("SELECT id, name, x, y, z, created_at FROM anchors ORDER BY id")
            result = [AnchorOut(**dict(row)) for row in rows]
            return result
        except Exception as e:
            print(f"❌ /anchors error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/anchors", response_model=AnchorOut)
    async def create_anchor(
        anchor: AnchorCreate,
        conn: asyncpg.Connection = Depends(get_db_connection),
        current=Depends(get_current_user),
    ):
        uid, role = current
        if role not in {"admin", "operator"}:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
        row = await conn.fetchrow(
            "INSERT INTO anchors (id, name, x, y, z) VALUES ($1, $2, $3, $4, $5) RETURNING id, name, x, y, z, created_at",
            anchor.id,
            anchor.name,
            anchor.x,
            anchor.y,
            anchor.z,
        )
        print(f"✓ Anchor created: {anchor.id}")
        return AnchorOut(**dict(row))

    @app.get("/wearables", response_model=list[WearableOut])
    async def list_wearables(conn: asyncpg.Connection = Depends(get_db_connection)):
        try:
            rows = await conn.fetch("SELECT uid, person_ref, role, created_at FROM wearables ORDER BY uid")
            result = [WearableOut(**dict(row)) for row in rows]
            return result
        except Exception as e:
            print(f"❌ /wearables error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/wearables", response_model=WearableOut)
    async def create_wearable(
        w: WearableCreate,
        conn: asyncpg.Connection = Depends(get_db_connection),
        current=Depends(get_current_user),
    ):
        uid, role = current
        if role not in {"admin", "operator"}:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
        row = await conn.fetchrow(
            "INSERT INTO wearables (uid, person_ref, role) VALUES ($1, $2, $3) RETURNING uid, person_ref, role, created_at",
            w.uid,
            w.person_ref,
            w.role,
        )
        print(f"✓ Wearable created: {w.uid}")
        return WearableOut(**dict(row))

    @app.get("/health")
    async def health_check():
        return {
            "status": "ok",
            "ws_clients": len(ws_clients),
            "queues": {
                "positions": positions_queue.qsize(),
                "stats": stats_queue.qsize(),
                "scans": scans_queue.qsize(),
                "anchor_status": anchor_status_queue.qsize(),
            }
        }

    # ==================== WEBSOCKET ====================

    @app.websocket("/ws/data")
    async def ws_data(websocket: WebSocket):
        """WebSocket for all data updates - OPTIMIZED"""
        await websocket.accept()
        ws_clients.add(websocket)
        print(f"✓ WebSocket client connected (total: {len(ws_clients)})")

        try:
            # Send initial data
            if db_instance and db_instance._pool:
                async with db_instance._pool.acquire() as conn:
                    # Initial anchors
                    rows = await conn.fetch("SELECT id, name, x, y, z, created_at FROM anchors ORDER BY id")
                    for row in rows:
                        await websocket.send_json({
                            "type": "anchor",
                            "id": row["id"],
                            "name": row["name"],
                            "x": float(row["x"]),
                            "y": float(row["y"]),
                            "z": float(row["z"]),
                            "created_at": row["created_at"].isoformat()
                        })

                    # Initial wearables
                    rows = await conn.fetch("SELECT uid, person_ref, role, created_at FROM wearables ORDER BY uid")
                    for row in rows:
                        await websocket.send_json({
                            "type": "wearable",
                            "uid": row["uid"],
                            "person_ref": row["person_ref"],
                            "role": row["role"],
                            "created_at": row["created_at"].isoformat()
                        })

            print("✓ Initial data sent")

            # Continuous updates - wait on ANY queue with timeout
            while True:
                # Create tasks for all queues - but with a timeout fallback
                get_tasks = [
                    asyncio.create_task(positions_queue.get()),
                    asyncio.create_task(stats_queue.get()),
                    asyncio.create_task(scans_queue.get()),
                    asyncio.create_task(anchor_status_queue.get()),
                ]

                # Wait for first result with 5s timeout
                done, pending = await asyncio.wait(
                    get_tasks,
                    timeout=5.0,
                    return_when=asyncio.FIRST_COMPLETED
                )

                # Cancel all pending tasks
                for task in pending:
                    task.cancel()

                # Send all completed data
                for task in done:
                    try:
                        data = await task
                        await websocket.send_json(data)
                    except asyncio.CancelledError:
                        pass
                    except Exception as e:
                        print(f"❌ Task error: {e}")

        except WebSocketDisconnect:
            print("⚠ WebSocket client disconnected")
        except Exception as e:
            print(f"❌ WebSocket error: {e}")
        finally:
            ws_clients.discard(websocket)
            print(f"✓ WebSocket client removed (total: {len(ws_clients)})")

    app.state.queues = {
        "positions": positions_queue,
        "stats": stats_queue,
        "scans": scans_queue,
        "anchor_status": anchor_status_queue,
    }
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting RTLS API on 0.0.0.0:8000")
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)