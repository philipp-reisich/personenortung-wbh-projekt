# MQTT Topic Plan

Dieses Dokument beschreibt die MQTT‑Topics und Nutzlasten, die im RTLS‑Prototyp verwendet werden. Alle Topics verwenden das Präfix `rtls/` und verzichten auf retained Messages. Die Kommunikation erfolgt standardmäßig mit QoS 1, um zumindest einmalige Zustellung sicherzustellen.

## Topics

### `rtls/anchor/{anchorId}/scan`

\* **Publisher:** Anchor (Scanner)
\* **Subscriber:** Ingestor
\* **Beschreibung:** Enthält Roh‑Scandaten der Wearables.

Beispiel‑Payload:

```json
{
  "ts": 1730200000123,
  "anchor_id": "A-01",
  "uid": "W-02",
  "rssi": -67,
  "adv_seq": 1234,
  "battery": 3.9
}
```

Felder:

| Feld         | Typ    | Beschreibung                        |
|--------------|--------|-------------------------------------|
| `ts`         | int64  | Timestamp in Millisekunden UTC       |
| `anchor_id`  | string | ID des Anchors (z.B. `A-01`)         |
| `uid`        | string | UID des Wearables                    |
| `rssi`       | float  | Gemessener RSSI‑Wert (dBm)           |
| `adv_seq`    | int    | Sequence‑Zähler (optional)           |
| `battery`    | float  | Batteriespannung in Volt (optional)  |

### `rtls/wearable/{uid}/state`

\* **Publisher:** Wearable (optional)
\* **Subscriber:** Ingestor / API
\* **Beschreibung:** Senden von Telemetrie wie Batteriestand oder Statusmeldungen. Struktur analog zu `scan`, ergänzt um Statusflags.

### `rtls/system/heartbeat`

\* **Publisher:** Anchors und Services
\* **Subscriber:** Monitoring/Operations
\* **Beschreibung:** Regelmäßiger Lebenszeichen‑Ping, z.B. jede Minute, um Systemzustand zu überwachen. Nutzlast kann serviceabhängige Felder wie Uptime enthalten.

## Qualitätssicherung

\* **QoS:** Für kritische Daten (Scans) wird QoS 1 verwendet, sodass Nachrichten mindestens einmal zugestellt werden. Eine idempotente Verarbeitung im Ingestor stellt sicher, dass Duplikate keine Konsistenzprobleme verursachen.
\* **Retain:** Es werden keine retained Messages verwendet, um eine unbeabsichtigte Weitergabe veralteter Daten zu verhindern.
\* **Authentifizierung:** Der MQTT‑Broker kann optional TLS und Passwort‑Authentifizierung nutzen. In dieser Vorlage ist der Broker offen für einfache Tests; in der Produktion müssen Benutzerrechte konfiguriert werden.

Weitere Details zur Verarbeitung sind in [architecture.md](architecture.md) beschrieben.