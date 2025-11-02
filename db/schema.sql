-- db/schema.sql
-- Database schema for the BLE RTLS prototype

CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
CREATE EXTENSION IF NOT EXISTS postgis;

-- Anchors
CREATE TABLE IF NOT EXISTS anchors (
    id TEXT PRIMARY KEY,
    name TEXT,
    x DOUBLE PRECISION NOT NULL,
    y DOUBLE PRECISION NOT NULL,
    z DOUBLE PRECISION DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Wearables
CREATE TABLE IF NOT EXISTS wearables (
    uid TEXT PRIMARY KEY,
    person_ref TEXT,
    role TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Scans (hypertable)
DROP TABLE IF EXISTS scans CASCADE;
CREATE TABLE IF NOT EXISTS scans (
    id BIGSERIAL NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    anchor_id TEXT NOT NULL REFERENCES anchors(id) ON DELETE CASCADE,
    uid TEXT NOT NULL REFERENCES wearables(uid) ON DELETE CASCADE,
    rssi REAL,
    battery REAL,
    temp_c REAL,
    tx_power_dbm SMALLINT,
    adv_seq INTEGER,
    flags INTEGER,
    emergency BOOLEAN,
    PRIMARY KEY (id, ts)
);
SELECT create_hypertable('scans', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_scans_uid_ts ON scans (uid, ts DESC);
CREATE INDEX IF NOT EXISTS idx_scans_anchor_ts ON scans (anchor_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_scans_emergency_ts ON scans (emergency, ts DESC);

-- Positions (hypertable) – erweitert: nearest_anchor_id, dist_m, num_anchors, dists(JSONB)
DROP TABLE IF EXISTS positions CASCADE;
CREATE TABLE IF NOT EXISTS positions (
    id BIGSERIAL NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    uid TEXT NOT NULL REFERENCES wearables(uid) ON DELETE CASCADE,
    x DOUBLE PRECISION,
    y DOUBLE PRECISION,
    z DOUBLE PRECISION,
    method TEXT,                 -- 'single_anchor' | 'proximity' | ...
    q_score DOUBLE PRECISION,
    zone TEXT,
    nearest_anchor_id TEXT,      -- bei single_anchor (und auch sonst: nächster Anchor)
    dist_m DOUBLE PRECISION,     -- Radius (bei single_anchor) oder Distanz zum nächsten Anchor
    num_anchors INT,             -- wie viele Anchors sind in dists enthalten
    dists JSONB,                 -- {"A-01": 3.2, "A-02": 5.8, ...}
    PRIMARY KEY (id, ts)
);
SELECT create_hypertable('positions', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_positions_uid_ts ON positions (uid, ts DESC);
CREATE INDEX IF NOT EXISTS idx_positions_anchor_ts ON positions (nearest_anchor_id, ts DESC);

-- Events (hypertable)
DROP TABLE IF EXISTS events CASCADE;
CREATE TABLE IF NOT EXISTS events (
    id BIGSERIAL NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    uid TEXT NOT NULL REFERENCES wearables(uid) ON DELETE CASCADE,
    type TEXT,
    severity INT,
    details TEXT,
    handled_by TEXT,
    PRIMARY KEY (id, ts)
);
SELECT create_hypertable('events', 'ts', if_not_exists => TRUE);

-- Anchor Status (hypertable)
DROP TABLE IF EXISTS anchor_status CASCADE;
CREATE TABLE IF NOT EXISTS anchor_status (
    id BIGSERIAL NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    anchor_id TEXT NOT NULL REFERENCES anchors(id) ON DELETE CASCADE,
    ip INET,
    fw TEXT,
    uptime_s INTEGER,
    wifi_rssi INTEGER,
    heap_free INTEGER,
    heap_min INTEGER,
    chip_temp_c REAL,
    tx_power_dbm SMALLINT,
    ble_scan_active BOOLEAN,
    PRIMARY KEY (id, ts)
);
SELECT create_hypertable('anchor_status', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_anchor_status_anchor_ts ON anchor_status (anchor_id, ts DESC);

-- Views
CREATE OR REPLACE VIEW v_anchor_latest AS
SELECT DISTINCT ON (anchor_id)
  anchor_id, ts, ip, fw, uptime_s, wifi_rssi, heap_free, heap_min, chip_temp_c, tx_power_dbm, ble_scan_active
FROM anchor_status
ORDER BY anchor_id, ts DESC;

CREATE OR REPLACE VIEW v_wearable_latest AS
SELECT s.uid,
       (SELECT s2.battery FROM scans s2 WHERE s2.uid=s.uid AND s2.battery IS NOT NULL ORDER BY ts DESC LIMIT 1) AS last_battery_v,
       (SELECT s3.temp_c FROM scans s3 WHERE s3.uid=s.uid AND s3.temp_c IS NOT NULL ORDER BY ts DESC LIMIT 1) AS last_temp_c,
       max(s.ts) AS last_seen
FROM scans s
GROUP BY s.uid;

-- Users (Basis)
CREATE TABLE IF NOT EXISTS users (
    uid SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Geofences (optional, PostGIS)
CREATE TABLE IF NOT EXISTS geofences (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    polygon GEOMETRY(POLYGON, 4326),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- (Optional) Retention Policies, außerhalb des Init-Phase setzen:
-- SELECT add_retention_policy('scans', INTERVAL '7 days');
-- SELECT add_retention_policy('positions', INTERVAL '30 days');
-- SELECT add_retention_policy('events', INTERVAL '180 days');
-- SELECT add_retention_policy('anchor_status', INTERVAL '7 days');
