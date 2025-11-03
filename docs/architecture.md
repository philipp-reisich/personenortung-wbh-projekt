# BLE RTLS Prototype Architecture

## Überblick

Dieses Projekt implementiert einen Real‑Time‑Location‑System‑Prototyp (RTLS) für Baustellen im Bahnumfeld. Wearables senden BLE‑Advertising‑Frames, die von stationären Ankern (Scannern) empfangen werden. Die Scanner veröffentlichen die Roh‑Scans via MQTT an einen Server. Ein Ingestor‑Dienst validiert die Nachrichten und persistiert sie in einer TimescaleDB. Ein Locator‑Dienst wertet die RSSI‑Messungen aus, schätzt Positionen anhand eines einfachen Proximity‑Algorithmus und schreibt diese in die Datenbank. Die FastAPI‑Anwendung stellt REST‑ und WebSocket‑Schnittstellen sowie ein Web‑Dashboard bereit. Ein optionaler Event‑Engine‑Teil (nicht vollständig implementiert) generiert Alarme bei Notfallknopfdruck oder Geofence‑Ereignissen.

## Komponenten und Datenfluss

```mermaid
flowchart LR
    subgraph Geräte
        W[Wearable (Advertiser)]
        B[Notfall‑Button]
    end
    subgraph Infrastruktur
        A[Anchor (Scanner)]
        R[Router / MQTT Broker]
        I[Ingestor Service]
        L[Locator Service]
        DB[(TimescaleDB)]
        API[FastAPI & Dashboard]
    end
    W -- BLE Advertising --> A
    B -- Event Flag --> W
    A -- MQTT JSON Scan --> R
    R -- MQTT QoS1 --> I
    I -- Batch Inserts --> DB
    L -- Position Berechnung --> DB
    API -- REST/WebSocket --> Benutzer
    DB -- Query --> API
```

### MQTT Topics

Die Anker veröffentlichen Roh‑Scans auf dem Topic:
- rtls/anchor/{anchorId}/scan

Payload (JSON) der Scans:
```json
{
  "ts": 1730200000123,       // Unix ms
  "anchor_id": "A-01",
  "uid": "W-02",
  "rssi": -67,
  "adv_seq": 1234,
  "battery": 3.9
}
```

Optionale Topics (falls aktiviert):
- rtls/anchor/{anchorId}/status — Heartbeats/Status des Ankers
- rtls/wearable/{uid}/event — z.B. Notfallknopf, Low‑Battery

Eigenschaften:
- QoS 1 (mindestens einmal)
- keine retained Messages
- Validierung und Deduplikation erfolgen im Ingestor

Weitere Details in: [mqtt-topics.md](mqtt-topics.md)

### Datenbank

PostgreSQL mit TimescaleDB. Zentrale Tabellen:
- anchors, wearables
- scans (Hypertable): Roh‑Scans der Anker
- positions (Hypertable): berechnete Positionen
- events (Hypertable): z.B. Notfall‑/Geofence‑Ereignisse
- anchor_status (optional): Statusmeldungen der Anker
- users/roles (optional): AuthN/AuthZ

Retention (konfigurierbar via Env):
- scans: 7 Tage
- positions: 30 Tage
- events: 180 Tage

Schema: [../db/schema.sql](../db/schema.sql)

### Dienste im Backend

- Ingestor
  - Abonniert MQTT‑Topics, validiert Payloads (Pydantic) und schreibt gebatcht in scans/events/anchor_status.
  - Batch‑Größe und Flush‑Intervall sind konfigurierbar.
- Locator
  - Aggregiert aktuelle Scans in einem Zeitfenster (z. B. letzte 2–5 s) je Wearable.
  - Berechnet Positionen und persistiert sie in positions (inkl. Qualitätsmetrik).
- API & Dashboard
  - REST‑Endpoints (u. a.): /anchors, /wearables, /positions/latest, /scans/latest, /stats
  - WebSocket: /ws/positions für Live‑Updates ans Dashboard

### Positionierungsalgorithmus

Der Locator nutzt ein RSSI‑basiertes Proximity‑Modell mit log‑distance path loss:

- Distanzschätzung: d = 10^((TxPower − RSSI) / (10 · n))
- Parameter (per Env konfigurierbar):
  - TX_POWER_DBM_AT_1M (z. B. −59)
  - PATH_LOSS_EXPONENT n (z. B. 2.2)
  - TOP_K (Anzahl stärkster Anker, z. B. 3)
- Gewichtung: inverse Quadrate, w_i = 1 / d_i^2
- Position: gewichtetes Mittel der Top‑k Ankerkoordinaten
- Qualität: q_score aus u. a. RSSI‑Streuung, Ankeranzahl und Geometrie
- Robustheit:
  - Filterung offensichtlicher Ausreißer (RSSI/Distanz‑Schranken)
  - Mindestanzahl Anker; bei Unterschreitung kein Fix
  - Optionales zeitliches Glätten (z. B. über gleitendes Fenster)

### Firmware‑Parameter (aktuelle Implementierung)

Wearable (Advertiser):
- Enthält u. a. uid, adv_seq, battery, optional: button/emergency‑Flag, Temperatur/TxPower.
- Advertising‑Intervall und Sendeleistung sind in der Firmware konfigurierbar; bei gesetztem Notfall‑Flag kann das Intervall reduziert werden.

Anchor (Scanner/Publisher):
- Kontinuierliches aktives Scannen (hoher Duty‑Cycle), Dedupe via adv_seq.
- Publiziert strukturierte JSON‑Scans auf rtls/anchor/{anchorId}/scan.

Hinweise zu konkreten Standardwerten siehe Firmware‑Quellen im Repository.

### Betrieb und Konfiguration

Wichtige Umgebungsvariablen (Beispiele):
- DATABASE_URL
- MQTT_BROKER_URL, MQTT_USERNAME, MQTT_PASSWORD
- INGEST_BATCH_SIZE, INGEST_FLUSH_MS
- LOCATOR_WINDOW_S, TOP_K
- TX_POWER_DBM_AT_1M, PATH_LOSS_EXPONENT
- RETENTION_DAYS_SCANS, RETENTION_DAYS_POSITIONS, RETENTION_DAYS_EVENTS

Start/Deployment:
- .env aus .env.example erstellen und anpassen
- docker‑compose/Makefile nutzen, z. B.:
  - make up — startet Broker, DB, API, Ingestor, Locator
  - make seed — legt Demo‑Geräte/Beispieldaten an

### Sicherheit und Datenschutz (implementierte Maßnahmen)

- Pseudonymisierung: UI zeigt Wearables ohne direkte Personenbezüge; Zuordnungen sind geschützt.
- Authentifizierung/Autorisierung: rollenbasiert (z. B. admin/operator/viewer); Token‑basierter Zugriff.
- Transport: MQTT/HTTP können mit TLS betrieben werden.
- Datenminimierung/Retention: automatische Löschung gemäß Retention‑Policies.
- Audit/Monitoring: zentrale Logs für Betriebsereignisse; Health‑Checks der Services.

Details und Empfehlungen: [privacy-security.md](privacy-security.md)

### Schnellstart

1. .env aus .env.example anlegen und konfigurieren.
2. make up starten.
3. Optional: make seed für Beispielgeräte und Testdaten.
4. Dashboard unter http://localhost:8000 öffnen.
5. Live‑Positionen über WebSocket /ws/positions.

### Weitere Arbeitsschritte

- Genauigkeit im Zielbereich (< 5 m Freifeld) validieren.
- Alarm‑Latenz (Notfall bis Anzeige) ≤ 30 s testen.
- Batterielaufzeit unter realen Intervallen > 8 h nachweisen.
- Offline‑Pufferung der Anker und Resync nach Verbindungsaufbau prüfen.