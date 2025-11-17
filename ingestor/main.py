# path: ingestor/main.py
"""MQTT ingestion service for the RTLS prototype.

- Subscribes to:
    - rtls/anchor/+/scan    -> table scans  (now with temp_c, tx_power_dbm, adv_seq, flags, emergency)
    - rtls/anchor/+/status  -> table anchor_status
    - rtls/events           -> table events
- Validates JSON via Pydantic
- Converts timestamps (ms since epoch) to timestamptz; falls back to now()
- Batches inserts with size/time thresholds
- Skips rows with unknown anchor_id / uid (FK) without aborting whole batch
- Periodically refreshes known anchors/wearables from DB for pre-filtering
- Auto-reconnects to MQTT, graceful shutdown on SIGTERM/SIGINT
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import socket
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Tuple, Set

import asyncpg
import paho.mqtt.client as mqtt
from pydantic import BaseModel, ValidationError, Field

# --------------------------- Logging -----------------------------------------

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("ingestor")

# --------------------------- Config ------------------------------------------

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

DB_DSN = DATABASE_URL.replace("postgresql+asyncpg", "postgresql")

MQTT_HOST = os.getenv("MQTT_BROKER_HOST", "mqtt")
MQTT_PORT = int(os.getenv("MQTT_BROKER_PORT", "1883"))

SUB_TOPIC_SCAN = os.getenv("SUB_TOPIC_SCAN", "rtls/anchor/+/scan")
SUB_TOPIC_STATUS = os.getenv("SUB_TOPIC_STATUS", "rtls/anchor/+/status")
SUB_TOPIC_EVENTS = os.getenv("SUB_TOPIC_EVENTS", "rtls/events")

MQTT_QOS = int(os.getenv("MQTT_QOS", "1"))

BATCH_MAX_SIZE = int(os.getenv("BATCH_MAX_SIZE", "200"))
BATCH_MAX_AGE_S = float(os.getenv("BATCH_MAX_AGE_S", "1.0"))

IDS_REFRESH_S = int(os.getenv("IDS_REFRESH_S", "60"))
TS_MIN_EPOCH_MS = int(os.getenv("TS_MIN_EPOCH_MS", "1514764800000"))  # 2018-01-01
ALLOW_FALLBACK_NOW_TS = os.getenv("ALLOW_FALLBACK_NOW_TS", "true").lower() in (
    "1",
    "true",
    "yes",
)

MQTT_CLIENT_ID = os.getenv(
    "MQTT_CLIENT_ID", f"rtls-ingestor-{socket.gethostname()}-{uuid.uuid4().hex[:6]}"
)

# --------------------------- Models ------------------------------------------


class _TsMixin:
    ts: Optional[int]

    def coerce_ts_dt(self) -> datetime:
        now_ms = int(time.time() * 1000)
        if self.ts is None:
            if not ALLOW_FALLBACK_NOW_TS:
                raise ValueError("ts missing and fallback disabled")
            return datetime.fromtimestamp(now_ms / 1000.0, tz=timezone.utc)
        ts_ms = int(self.ts)
        if ts_ms < TS_MIN_EPOCH_MS or ts_ms > (now_ms + 365 * 24 * 3600 * 1000):
            ts_ms = now_ms
        return datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)


class ScanMessage(BaseModel, _TsMixin):
    ts: Optional[int] = None
    anchor_id: str = Field(min_length=1, max_length=64)
    uid: str = Field(min_length=1, max_length=64)
    rssi: float
    adv_seq: Optional[int] = None
    battery: Optional[float] = None  # Volt
    temp_c: Optional[float] = None
    tx_power_dbm: Optional[int] = None
    emergency: Optional[bool] = None


class AnchorStatus(BaseModel, _TsMixin):
    ts: Optional[int] = None
    anchor_id: str
    ip: Optional[str] = None
    fw: Optional[str] = None
    uptime_s: Optional[int] = None
    wifi_rssi: Optional[int] = None
    heap_free: Optional[int] = None
    heap_min: Optional[int] = None
    chip_temp_c: Optional[float] = None
    tx_power_dbm: Optional[int] = None
    ble_scan_active: Optional[bool] = None


class RtlsEvent(BaseModel, _TsMixin):
    ts: Optional[int] = None
    uid: str
    type: str
    severity: Optional[int] = None
    details: Optional[str] = None
    anchor_id: Optional[str] = None


# --------------------------- Known IDs cache ---------------------------------


@dataclass
class KnownIds:
    anchors: Set[str]
    wearables: Set[str]
    last_loaded_s: float = 0.0

    @classmethod
    async def load(cls, conn) -> "KnownIds":
        a_rows = await conn.fetch("SELECT id FROM anchors")
        w_rows = await conn.fetch("SELECT uid FROM wearables")
        anchors = {r["id"] for r in a_rows}
        wearables = {r["uid"] for r in w_rows}
        logger.info(
            "loaded known ids: %d anchors, %d wearables", len(anchors), len(wearables)
        )
        return cls(anchors=anchors, wearables=wearables, last_loaded_s=time.monotonic())

    async def ensure_fresh(self, conn):
        now = time.monotonic()
        if now - self.last_loaded_s >= IDS_REFRESH_S:
            refreshed = await KnownIds.load(conn)
            self.anchors = refreshed.anchors
            self.wearables = refreshed.wearables
            self.last_loaded_s = refreshed.last_loaded_s


# --------------------------- Batch flushers ----------------------------------


async def flush_scans(
    batch: List[ScanMessage], pool: asyncpg.Pool, kid: KnownIds
) -> None:
    if not batch:
        return
    async with pool.acquire() as conn:
        await kid.ensure_fresh(conn)
    valid = []
    skipped_unknown = 0
    for msg in batch:
        try:
            ts = msg.coerce_ts_dt()
        except Exception as e:
            logger.warning("Skipping scan with bad ts: %s (payload=%s)", e, msg.dict())
            continue
        if msg.anchor_id not in kid.anchors or msg.uid not in kid.wearables:
            skipped_unknown += 1
            if skipped_unknown <= 5:
                logger.warning(
                    "Skipping scan due to unknown FK (anchor_id=%s, uid=%s)",
                    msg.anchor_id,
                    msg.uid,
                )
            continue
        valid.append(
            (
                ts,
                msg.anchor_id,
                msg.uid,
                float(msg.rssi),
                msg.battery,
                msg.temp_c,
                msg.tx_power_dbm,
                msg.adv_seq,
                None,
                bool(msg.emergency) if msg.emergency is not None else None,
            )
        )
    if not valid:
        if skipped_unknown:
            logger.info(
                "Scan batch had only unknown FK rows (skipped=%d)", skipped_unknown
            )
        return
    async with pool.acquire() as conn:
        try:
            await conn.executemany(
                """
                INSERT INTO scans
                  (ts, anchor_id, uid, rssi, battery, temp_c, tx_power_dbm, adv_seq, flags, emergency)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                """,
                valid,
            )
            logger.info(
                "Inserted %d scans%s",
                len(valid),
                f" (skipped {skipped_unknown} unknown)" if skipped_unknown else "",
            )
        except asyncpg.exceptions.ForeignKeyViolationError:
            inserted = 0
            for rec in valid:
                try:
                    await conn.execute(
                        """
                        INSERT INTO scans
                          (ts, anchor_id, uid, rssi, battery, temp_c, tx_power_dbm, adv_seq, flags, emergency)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                        """,
                        *rec,
                    )
                    inserted += 1
                except asyncpg.exceptions.ForeignKeyViolationError:
                    pass
            logger.info(
                "FK violation during scan batch; inserted %d/%d", inserted, len(valid)
            )


async def flush_status(
    batch: List[AnchorStatus], pool: asyncpg.Pool, kid: KnownIds
) -> None:
    if not batch:
        return
    async with pool.acquire() as conn:
        await kid.ensure_fresh(conn)
    valid = []
    skipped = 0
    for msg in batch:
        try:
            ts = msg.coerce_ts_dt()
        except Exception as e:
            logger.warning(
                "Skipping status with bad ts: %s (payload=%s)", e, msg.dict()
            )
            continue
        if msg.anchor_id not in kid.anchors:
            skipped += 1
            continue
        valid.append(
            (
                ts,
                msg.anchor_id,
                msg.ip,
                msg.fw,
                msg.uptime_s,
                msg.wifi_rssi,
                msg.heap_free,
                msg.heap_min,
                msg.chip_temp_c,
                msg.tx_power_dbm,
                msg.ble_scan_active,
            )
        )
    if not valid:
        return
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO anchor_status
              (ts, anchor_id, ip, fw, uptime_s, wifi_rssi, heap_free, heap_min, chip_temp_c, tx_power_dbm, ble_scan_active)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
            """,
            valid,
        )
        logger.info(
            "Inserted %d anchor_status rows%s",
            len(valid),
            f" (skipped {skipped})" if skipped else "",
        )


async def flush_events(
    batch: List[RtlsEvent], pool: asyncpg.Pool, kid: KnownIds
) -> None:
    if not batch:
        return
    async with pool.acquire() as conn:
        await kid.ensure_fresh(conn)
    valid = []
    skipped = 0
    for msg in batch:
        try:
            ts = msg.coerce_ts_dt()
        except Exception as e:
            logger.warning("Skipping event with bad ts: %s (payload=%s)", e, msg.dict())
            continue
        if msg.uid not in kid.wearables:
            skipped += 1
            continue
        valid.append((ts, msg.uid, msg.type, msg.severity, msg.details))
    if not valid:
        return
    async with pool.acquire() as conn:
        await conn.executemany(
            "INSERT INTO events (ts, uid, type, severity, details) VALUES ($1,$2,$3,$4,$5)",
            valid,
        )
        logger.info(
            "Inserted %d events%s",
            len(valid),
            f" (skipped {skipped})" if skipped else "",
        )


# --------------------------- MQTT plumbing -----------------------------------


def build_mqtt_client(
    loop: asyncio.AbstractEventLoop,
    scan_q: asyncio.Queue[ScanMessage],
    status_q: asyncio.Queue[AnchorStatus],
    event_q: asyncio.Queue[RtlsEvent],
) -> mqtt.Client:
    client = mqtt.Client(client_id=MQTT_CLIENT_ID, clean_session=True)
    client.enable_logger()
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    client.will_set(
        "rtls/ingestor/status",
        payload=json.dumps({"status": "offline", "client_id": MQTT_CLIENT_ID}),
        qos=1,
        retain=True,
    )

    def on_connect(c, userdata, flags, rc):
        if rc == 0:
            logger.info("Connected to MQTT broker at %s:%d", MQTT_HOST, MQTT_PORT)
            c.publish(
                "rtls/ingestor/status",
                json.dumps({"status": "online", "client_id": MQTT_CLIENT_ID}),
                qos=1,
                retain=True,
            )
            c.subscribe(
                [
                    (SUB_TOPIC_SCAN, MQTT_QOS),
                    (SUB_TOPIC_STATUS, MQTT_QOS),
                    (SUB_TOPIC_EVENTS, MQTT_QOS),
                ]
            )
        else:
            logger.error("MQTT connect failed: rc=%s", rc)

    def on_disconnect(c, userdata, rc):
        if rc != 0:
            logger.warning(
                "MQTT unexpected disconnect (rc=%s) – will auto-reconnect", rc
            )

    def on_message(c, userdata, msg: mqtt.MQTTMessage):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            topic = msg.topic

            if topic.startswith("rtls/anchor/") and topic.endswith("/scan"):
                scan = ScanMessage(**payload)
                loop.call_soon_threadsafe(scan_q.put_nowait, scan)

            elif topic.startswith("rtls/anchor/") and topic.endswith("/status"):
                st = AnchorStatus(**payload)
                loop.call_soon_threadsafe(status_q.put_nowait, st)

            elif topic == "rtls/events":
                ev = RtlsEvent(**payload)
                loop.call_soon_threadsafe(event_q.put_nowait, ev)

            else:
                logger.debug("ignored topic %s", topic)

        except (json.JSONDecodeError, ValidationError) as e:
            logger.warning("Invalid payload on %s: %s", msg.topic, e)
        except Exception as e:
            logger.exception("on_message error: %s", e)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_start()
    return client


# --------------------------- Main --------------------------------------------


async def run() -> None:
    logger.info(
        "Starting ingestor (batch size=%d, max_age=%.2fs, qos=%d)",
        BATCH_MAX_SIZE,
        BATCH_MAX_AGE_S,
        MQTT_QOS,
    )

    pool = await asyncpg.create_pool(DB_DSN, min_size=1, max_size=10)

    # Load initial known ids
    async with pool.acquire() as conn:
        known = await KnownIds.load(conn)

    scan_q: asyncio.Queue[ScanMessage] = asyncio.Queue(maxsize=10000)
    status_q: asyncio.Queue[AnchorStatus] = asyncio.Queue(maxsize=2000)
    event_q: asyncio.Queue[RtlsEvent] = asyncio.Queue(maxsize=2000)

    loop = asyncio.get_event_loop()
    mqtt_client = build_mqtt_client(loop, scan_q, status_q, event_q)

    stop = asyncio.Event()

    def _handle_signal(sig, frame=None):
        logger.info("Received %s – shutting down ...", sig)
        stop.set()

    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(s, _handle_signal)
        except Exception:
            pass

    scans_buf: List[ScanMessage] = []
    status_buf: List[AnchorStatus] = []
    events_buf: List[RtlsEvent] = []

    last_flush = time.monotonic()

    try:
        while not stop.is_set():
            timeout = max(0.0, BATCH_MAX_AGE_S - (time.monotonic() - last_flush))
            did_any = False
            try:
                msg = await asyncio.wait_for(scan_q.get(), timeout=timeout)
                scans_buf.append(msg)
                did_any = True
            except asyncio.TimeoutError:
                pass

            # Drain some more from queues (bounded)
            for _ in range(min(100, scan_q.qsize())):
                try:
                    scans_buf.append(scan_q.get_nowait())
                except asyncio.QueueEmpty:
                    break
            for _ in range(min(50, status_q.qsize())):
                try:
                    status_buf.append(status_q.get_nowait())
                except asyncio.QueueEmpty:
                    break
            for _ in range(min(50, event_q.qsize())):
                try:
                    events_buf.append(event_q.get_nowait())
                except asyncio.QueueEmpty:
                    break

            do_flush = (
                (time.monotonic() - last_flush) >= BATCH_MAX_AGE_S
                or len(scans_buf) >= BATCH_MAX_SIZE
                or len(status_buf) >= BATCH_MAX_SIZE // 2
                or len(events_buf) >= BATCH_MAX_SIZE // 2
            )

            if do_flush and (scans_buf or status_buf or events_buf):
                if scans_buf:
                    await flush_scans(scans_buf, pool, known)
                    scans_buf.clear()
                if status_buf:
                    await flush_status(status_buf, pool, known)
                    status_buf.clear()
                if events_buf:
                    await flush_events(events_buf, pool, known)
                    events_buf.clear()
                last_flush = time.monotonic()
            elif (
                did_any is False and (time.monotonic() - last_flush) >= BATCH_MAX_AGE_S
            ):
                # periodic flush even if no new data (no-op)
                last_flush = time.monotonic()

        # final flush
        if scans_buf:
            await flush_scans(scans_buf, pool, known)
        if status_buf:
            await flush_status(status_buf, pool, known)
        if events_buf:
            await flush_events(events_buf, pool, known)

    finally:
        try:
            mqtt_client.loop_stop()
            mqtt_client.disconnect()
        except Exception:
            pass
        await pool.close()
        logger.info("Ingestor shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Ingestor terminated by user")
