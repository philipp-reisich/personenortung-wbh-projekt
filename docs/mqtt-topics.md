# MQTT Topic Plan

Dieses Dokument beschreibt die MQTT‑Topics und Nutzlasten, die im RTLS‑Prototyp verwendet werden. Alle Topics verwenden das Präfix `rtls/` und verzichten auf retained Messages. Die Kommunikation erfolgt standardmäßig mit QoS 1, um zumindest einmalige Zustellung sicherzustellen.

## Topics

### rtls/anchor/{anchorId}/scan

- Publisher: Anchor
- Subscriber: Ingestor
- Beschreibung: Roh‑Scandaten der Wearables.

Beispiel‑Payload:
```json
{
  "ts": 1730200000123,        // Unix ms (UTC)
  "anchor_id": "A-01",
  "uid": "W-02",
  "rssi": -67,
  "adv_seq": 1234,            // optional, für Deduplikation
  "battery": 3.9              // optional, Volt
}
```

Felder:
- ts: int64
- anchor_id: string
- uid: string
- rssi: number (dBm)
- adv_seq: int (optional)
- battery: number (V, optional)

Hinweise:
- Deduplikation im Ingestor (adv_seq + Zeitfenster).
- Keine retained Messages.

### rtls/anchor/{anchorId}/status

- Publisher: Anchor (optional)
- Subscriber: Ingestor / API
- Beschreibung: Heartbeat/Status des Anchors.

Beispiel‑Payload:
```json
{
  "ts": 1730200000456,
  "anchor_id": "A-01",
  "ip": "192.168.1.20",
  "uptime_s": 864,
  "fw": "1.2.0"
}
```

Felder (optional je nach Firmware):
- ts: int64
- anchor_id: string
- ip: string
- uptime_s: int
- fw: string

### rtls/wearable/{uid}/event

- Publisher: Wearable (oder durch Anchor weitergeleitet; optional)
- Subscriber: Ingestor / API
- Beschreibung: Ereignisse wie Notfallknopf oder Low‑Battery.

Beispiel‑Payload:
```json
{
  "ts": 1730200000789,
  "uid": "W-02",
  "type": "emergency",        // z.B. emergency | low_battery
  "battery": 3.7,             // V (optional)
  "seq": 457                  // optional
}
```

## Qualitätssicherung

- QoS: 1 (mindestens einmal). Ingestor verarbeitet idempotent.
- Retain: aus (verhindert veraltete Daten).
- Authentifizierung/TLS: Broker kann TLS und Benutzer/Passwort nutzen; für Produktion zwingend empfohlen.

Weiterführend: siehe docs/architecture.md.