# path: rtls/locator/main.py
"""Positioning service for the RTLS prototype.

- Periodically reads anchors and recent scans from PostgreSQL
- Groups scans per uid in a sliding WINDOW_SECONDS time window
  (per-uid window inside a wider QUERY_WINDOW_FACTOR * WINDOW_SECONDS DB query)
- For each uid + anchor:
    - keeps best (strongest) RSSI and latest timestamp within the window
    - converts RSSI to distance via a log-distance model:
        d = 10 ** ((TX_POWER_DBM_AT_1M - rssi) / (10 * PATH_LOSS_EXPONENT))
- Position estimation:
    - uses up to TOP_K strongest anchors
    - inverse-distance-squared weighted centroid -> method="proximity"
    - falls back to nearest anchor if weights degenerate -> "fallback_nearest"
    - if only one anchor heard -> method="single_anchor" at that anchor's (x, y)
- Computes a quality score q_score in [0, 1] from:
    - number of anchors (up to TOP_K)
    - RSSI spread between strongest and weakest anchor
- Inserts rows into table positions with:
    ts=now(), uid, x, y, z=0.0, method, q_score, zone=None,
    nearest_anchor_id, dist_m, num_anchors, dists (JSON of per-anchor distances)
- Throttles writes per uid using WRITE_THROTTLE_S (monotonic clock)
- Runs as a long-lived asyncio loop using an asyncpg connection pool
"""

from __future__ import annotations
import asyncio, json, math, os, logging, time
from typing import Dict, Tuple, List
import asyncpg

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO),
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("locator")

DATABASE_URL = os.environ["DATABASE_URL"]

WINDOW_SECONDS       = int(os.getenv("WINDOW_SECONDS", "7"))
POLL_INTERVAL        = float(os.getenv("POLL_INTERVAL", "1.5"))
WRITE_THROTTLE_S     = float(os.getenv("WRITE_THROTTLE_S", "5.0"))
QUERY_WINDOW_FACTOR  = float(os.getenv("QUERY_WINDOW_FACTOR", "2.0"))
TX_POWER_DBM_AT_1M   = float(os.getenv("TX_POWER_DBM_AT_1M", "-59"))
PATH_LOSS_EXPONENT   = float(os.getenv("PATH_LOSS_EXPONENT", "2.2"))
WEIGHT_DIST_CLAMP_M  = float(os.getenv("WEIGHT_DIST_CLAMP_M", "0.5"))
TOP_K                = int(os.getenv("TOP_K", "3"))

_last_written_ts_monotonic: Dict[str, float] = {}

def rssi_to_distance(rssi: float, tx_power: float, n: float) -> float:
    return 10 ** ((tx_power - rssi) / (10.0 * n))

async def fetch_anchors(conn) -> Dict[str, Tuple[float, float, float]]:
    rows = await conn.fetch("SELECT id, x, y, z FROM anchors")
    return {r["id"]: (float(r["x"]), float(r["y"]), float(r["z"])) for r in rows}

async def fetch_recent_scans(conn, seconds: int) -> List[asyncpg.Record]:
    q = """
    SELECT ts, anchor_id, uid, rssi
      FROM scans
     WHERE ts > now() - make_interval(secs => $1)
    ORDER BY ts DESC
    """
    return await conn.fetch(q, seconds)

def should_throttle(uid: str) -> bool:
    now_m = time.monotonic()
    last = _last_written_ts_monotonic.get(uid, 0.0)
    if now_m - last < WRITE_THROTTLE_S:
        return True
    _last_written_ts_monotonic[uid] = now_m
    return False

async def compute_and_store_positions(pool) -> None:
    async with pool.acquire() as conn:
        anchors = await fetch_anchors(conn)

    logger.info("starting locator (window=%ss, poll=%.2fs, min_anchors=1, throttle=%.1fs)",
                WINDOW_SECONDS, POLL_INTERVAL, WRITE_THROTTLE_S)

    query_seconds = max(WINDOW_SECONDS, int(WINDOW_SECONDS * QUERY_WINDOW_FACTOR))

    while True:
        try:
            async with pool.acquire() as conn:
                scans = await fetch_recent_scans(conn, query_seconds)
                if not scans:
                    await asyncio.sleep(POLL_INTERVAL); continue

                by_uid: Dict[str, List[asyncpg.Record]] = {}
                for r in scans:
                    by_uid.setdefault(r["uid"], []).append(r)

                inserted_total = 0

                for uid, records in by_uid.items():
                    if should_throttle(uid):
                        continue

                    uid_latest_ts = max(r["ts"] for r in records)
                    uid_window_start = uid_latest_ts - await conn.fetchval("SELECT make_interval(secs => $1)", WINDOW_SECONDS)

                    filtered = [r for r in records if r["ts"] >= uid_window_start]

                    per_anchor = {}
                    for rec in filtered:
                        aid = rec["anchor_id"]
                        if aid not in anchors:
                            continue
                        rssi = float(rec["rssi"]); ts = rec["ts"]
                        s = per_anchor.get(aid)
                        if s is None:
                            per_anchor[aid] = {"best_rssi": rssi, "latest_ts": ts}
                        else:
                            if rssi > s["best_rssi"]:
                                s["best_rssi"] = rssi
                            if ts > s["latest_ts"]:
                                s["latest_ts"] = ts

                    if not per_anchor:
                        continue

                    now_db = await conn.fetchval("SELECT now()")
                    dists = {}
                    ages_s = {}
                    for aid, s in per_anchor.items():
                        d = rssi_to_distance(s["best_rssi"], TX_POWER_DBM_AT_1M, PATH_LOSS_EXPONENT)
                        dists[aid] = float(d)
                        ages_s[aid] = (now_db - s["latest_ts"]).total_seconds()

                    num_anchors = len(per_anchor)
                    nearest_anchor_id = max(per_anchor.items(), key=lambda kv: kv[1]["best_rssi"])[0]
                    nearest_dist = dists[nearest_anchor_id]

                    if num_anchors >= 2:
                        top = sorted(per_anchor.items(), key=lambda kv: kv[1]["best_rssi"], reverse=True)[:TOP_K]
                        wsumx = wsumy = wtot = 0.0
                        for aid, s in top:
                            ax, ay, _ = anchors[aid]
                            d = max(dists[aid], WEIGHT_DIST_CLAMP_M)
                            w = 1.0/(d*d)
                            wsumx += w*ax; wsumy += w*ay; wtot += w
                        if wtot > 0:
                            x, y = wsumx/wtot, wsumy/wtot
                            method = "proximity"
                        else:
                            ax, ay, _ = anchors[nearest_anchor_id]
                            x, y = ax, ay
                            method = "fallback_nearest"
                        logger.debug("uid=%s proximity: anchors=%s ages=%s", uid, list(per_anchor.keys()), {k: round(v,2) for k,v in ages_s.items()})
                    else:
                        ax, ay, _ = anchors[nearest_anchor_id]
                        x, y = ax, ay
                        method = "single_anchor"
                        logger.debug("uid=%s single_anchor: only %d anchor in last %ss (aligned to uid_latest=%s, nearest=%s, dist=%.2fm, ages=%s)",
                                     uid, num_anchors, WINDOW_SECONDS, uid_latest_ts, nearest_anchor_id, nearest_dist,
                                     {k: round(v,2) for k,v in ages_s.items()})

                    rssi_vals = [s["best_rssi"] for s in per_anchor.values()]
                    spread = max(rssi_vals) - min(rssi_vals) if len(rssi_vals) > 1 else 0.0
                    anchor_factor = min(1.0, (num_anchors - 1) / max(1, TOP_K - 1)) if num_anchors > 1 else 0.0
                    q_score = max(0.0, min(1.0, (0.6*anchor_factor + 0.4*(1.0 - min(1.0, abs(spread)/40.0)))))

                    await conn.execute(
                        """
                        INSERT INTO positions
                          (ts, uid, x, y, z, method, q_score, zone,
                           nearest_anchor_id, dist_m, num_anchors, dists)
                        VALUES (now(), $1, $2, $3, $4, $5, $6, $7,
                                $8, $9, $10, $11)
                        """,
                        uid, x, y, 0.0, method, q_score, None,
                        nearest_anchor_id, float(nearest_dist), int(num_anchors), json.dumps(dists)
                    )
                    inserted_total += 1

                if inserted_total:
                    logger.info("inserted %d positions", inserted_total)

            await asyncio.sleep(POLL_INTERVAL)

        except Exception as e:
            logger.exception("locator loop error: %s", e)
            await asyncio.sleep(1.0)

async def main() -> None:
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    try:
        await compute_and_store_positions(pool)
    finally:
        await pool.close()

if __name__ == "__main__":
    asyncio.run(main())
