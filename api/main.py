"""Entry point for the FastAPI server - Fixed validators."""

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
    app = FastAPI(title="BLE RTLS Prototype", version="0.2.0")

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

    broadcast_queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=1000)
    ws_clients = set()
    poll_connection = None

    @app.on_event("startup")
    async def startup_event() -> None:
        nonlocal poll_connection
        try:
            await get_db_instance().connect()
            print("✓ Database pool connected")
        except Exception as e:
            print(f"❌ Database pool connection failed: {e}")
            raise

        try:
            db_url = str(settings.database_url)
            db_url_clean = db_url.replace("postgresql+asyncpg", "postgresql")
            poll_connection = await asyncpg.connect(db_url_clean)
            print("✓ Poll connection established")
        except Exception as e:
            print(f"❌ Poll connection failed: {e}")
            poll_connection = None

        async def poll_positions() -> None:
            nonlocal poll_connection
            while True:
                try:
                    if poll_connection is None or poll_connection.is_closed():
                        try:
                            db_url = str(settings.database_url)
                            db_url_clean = db_url.replace("postgresql+asyncpg", "postgresql")
                            poll_connection = await asyncpg.connect(db_url_clean)
                            print("✓ Poll connection re-established")
                        except Exception as e:
                            print(f"⚠ Poll connection failed: {e}")
                            await asyncio.sleep(5)
                            continue

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
                        print(f"📊 Found {len(rows)} positions in last 10 seconds")
                        for row in rows:
                            # Convert JSONB dists properly
                            dists_val = row["dists"]
                            if isinstance(dists_val, str):
                                try:
                                    dists_val = json.loads(dists_val)
                                except:
                                    dists_val = {}

                            data = {
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
                                broadcast_queue.put_nowait(data)
                                if data["x"] and data["y"]:
                                    print(f"📍 Queued: {data['uid']} at ({data['x']:.1f}, {data['y']:.1f})")
                                elif data["nearest_anchor_id"]:
                                    print(f"📍 Queued: {data['uid']} (single anchor: {data['nearest_anchor_id']}, {data['dist_m']:.1f}m)")
                            except asyncio.QueueFull:
                                print("⚠ Queue full")
                    else:
                        print(f"⏳ No new positions in last 10 seconds")

                except Exception as e:
                    print(f"❌ Poll error: {e}")
                    poll_connection = None

                await asyncio.sleep(2)

        asyncio.create_task(poll_positions())
        print("✓ Position poller started")

    @app.on_event("shutdown")
    async def shutdown_event() -> None:
        nonlocal poll_connection
        if poll_connection and not poll_connection.is_closed():
            await poll_connection.close()
            print("✓ Poll connection closed")
        await get_db_instance().disconnect()
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
            print(f"📌 GET /anchors: {len(result)} anchors")
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
            print(f"📱 GET /wearables: {len(result)} wearables")
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

    @app.get("/positions/latest", response_model=list[PositionOut])
    async def latest_positions(limit: int = 100, conn: asyncpg.Connection = Depends(get_db_connection)):
        try:
            query = """
            SELECT DISTINCT ON (uid)
                id, ts, uid, x, y, z, method, q_score, zone,
                nearest_anchor_id, dist_m, num_anchors, dists
            FROM positions
            ORDER BY uid, ts DESC
            LIMIT $1
            """
            rows = await conn.fetch(query, limit)

            result = []
            for row in rows:
                row_dict = dict(row)
                # Convert JSONB dists if needed
                if isinstance(row_dict.get("dists"), str):
                    try:
                        row_dict["dists"] = json.loads(row_dict["dists"])
                    except:
                        row_dict["dists"] = {}
                result.append(PositionOut(**row_dict))

            print(f"📊 GET /positions/latest: {len(result)} devices")
            return result
        except Exception as e:
            print(f"❌ /positions/latest error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/scans/latest", response_model=list[ScanOut])
    async def latest_scans(conn: asyncpg.Connection = Depends(get_db_connection)):
        try:
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
            result = [ScanOut(**dict(row)) for row in rows]
            print(f"📡 GET /scans/latest: {len(result)} wearables")
            return result
        except Exception as e:
            print(f"❌ /scans/latest error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/anchor_status/latest", response_model=list[AnchorStatusOut])
    async def latest_anchor_status(conn: asyncpg.Connection = Depends(get_db_connection)):
        try:
            query = """
            SELECT DISTINCT ON (anchor_id)
                anchor_id, ts, ip, fw, uptime_s, wifi_rssi, heap_free, heap_min,
                chip_temp_c, tx_power_dbm, ble_scan_active
            FROM anchor_status
            ORDER BY anchor_id, ts DESC
            """
            rows = await conn.fetch(query)

            result = []
            for row in rows:
                row_dict = dict(row)
                # Convert INET to string
                if row_dict.get("ip"):
                    row_dict["ip"] = str(row_dict["ip"])
                result.append(AnchorStatusOut(**row_dict))

            print(f"📡 GET /anchor_status/latest: {len(result)} anchors")
            return result
        except Exception as e:
            print(f"❌ /anchor_status/latest error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/stats")
    async def get_stats(conn: asyncpg.Connection = Depends(get_db_connection)):
        try:
            active_devices = await conn.fetchval(
                "SELECT COUNT(DISTINCT uid) FROM positions WHERE ts > NOW() - INTERVAL '5 minutes'"
            )
            anchors_count = await conn.fetchval("SELECT COUNT(*) FROM anchors")
            wearables_count = await conn.fetchval("SELECT COUNT(*) FROM wearables")
            total_positions = await conn.fetchval("SELECT COUNT(*) FROM positions WHERE ts > NOW() - INTERVAL '1 day'")
            emergency_count = await conn.fetchval(
                "SELECT COUNT(*) FROM events WHERE type = 'emergency' AND ts > NOW() - INTERVAL '1 hour'"
            )

            print(f"📈 Stats: {active_devices} active devices")
            return {
                "active_devices": active_devices or 0,
                "total_anchors": anchors_count or 0,
                "total_wearables": wearables_count or 0,
                "total_positions": total_positions or 0,
                "emergency_count": emergency_count or 0,
            }
        except Exception as e:
            print(f"❌ /stats error: {e}")
            return {
                "active_devices": 0,
                "total_anchors": 0,
                "total_wearables": 0,
                "total_positions": 0,
                "emergency_count": 0,
            }

    @app.websocket("/ws/positions")
    async def ws_positions(websocket: WebSocket):
        await websocket.accept()
        ws_clients.add(websocket)
        print(f"✓ WebSocket client connected (total: {len(ws_clients)})")

        try:
            while True:
                try:
                    data = await asyncio.wait_for(broadcast_queue.get(), timeout=10.0)
                    await websocket.send_json(data)
                except asyncio.TimeoutError:
                    await websocket.send_json({"type": "ping"})
        except WebSocketDisconnect:
            print("⚠ WebSocket client disconnected")
        except Exception as e:
            print(f"❌ WebSocket error: {e}")
        finally:
            ws_clients.discard(websocket)

    @app.get("/health")
    async def health_check():
        return {
            "status": "ok",
            "ws_clients": len(ws_clients),
            "queue_size": broadcast_queue.qsize(),
        }

    app.state.broadcast_queue = broadcast_queue
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting RTLS API on 0.0.0.0:8000")
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)
