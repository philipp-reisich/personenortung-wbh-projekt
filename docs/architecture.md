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

Die Scanner veröffentlichen Roh‑Scans auf dem Topic `rtls/anchor/{anchorId}/scan` mit folgendem JSON‑Schema:

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

Der Ingestor verarbeitet diese Nachrichten, validiert sie mithilfe von Pydantic und schreibt sie in die Tabelle `scans`. Weitere Topics sind in der Datei [mqtt-topics.md](mqtt-topics.md) dokumentiert.

### Datenbank

Die Datenbank basiert auf PostgreSQL mit TimescaleDB‑Erweiterung. Sie enthält Tabellen für Anker, Wearables, Roh‑Scans, Positionen, Events, Benutzer und optionale Geofences. Die Tabellen `scans`, `positions` und `events` werden als Hypertables partitioniert, sodass große Datenmengen effizient verwaltet und retention policies umgesetzt werden können. Das Schema befindet sich in [db/schema.sql](../db/schema.sql).

## Positionierungsalgorithmus

Die Genauigkeit (< 5 m im Freifeld) wird primär durch eine Proximity‑Ortung basierend auf der log‑distance path loss‑Formel erreicht. Das Modell berechnet die Distanz *d* in Metern aus dem gemessenen RSSI (*R*) mit Hilfe der Referenzsendeleistung (*TxPower*) und des Pfadverlust‑Exponenten (*n*):

\[ d = 10^{\left(\frac{\mathit{TxPower} - R}{10\,n}\right)} \]

Diese Formel ist in der Fachliteratur etabliert; das Baeldung‑Artikel beschreibt den log‑distance path loss und typische Exponenten zwischen 2 und 4 abhängig von der Umgebung【685827273207562†L88-L104】. Für Baustellen wird ein n‑Wert von ca. 2,2 angenommen. Die Gewichtung pro Anker ergibt sich aus dem inversen Quadrat der geschätzten Distanz (*w_i = 1/d_i^2*). Die Koordinaten werden als gewichteter Mittelwert der Top‑k Anker (standardmäßig k=3) berechnet. Zusätzlich wird die Varianz der RSSI‑Messungen zur Qualitätsbewertung genutzt (je kleiner die Varianz, desto höher der Qualitätsfaktor).

Für die Verfeinerung kann optional ein Fingerprinting‑Ansatz implementiert werden. Dabei wird eine Radiomap aus mehreren Referenzpunkten aufgenommen und mittels k‑NN das Positionieren ermöglicht. Aufgrund des erhöhten Aufwands ist dies im Prototyp als Fallback vorgesehen.

## Hardwareparameter

### Advertising‑Intervall

Wearables senden BLE‑Advertising‑Frames im Intervall von 200 ms (konfigurierbar 100–300 ms). Kurze Intervalle verbessern die Detektionszeit, erhöhen jedoch den Stromverbrauch. Laut NovelBits liegt der Stromverbrauch beim Advertising typischerweise zwischen 3–10 mA und längere Intervalle erhöhen die Batterielaufzeit【98596641544427†L144-L177】. Kontakt.io empfiehlt ein Intervall von 200–350 ms, das eine gute Balance zwischen Genauigkeit und Batterielaufzeit (z.B. ~30 Monate bei 200 ms) bietet【411591169030834†L41-L81】.

### Scan‑Fenster und Scan‑Intervall

Die Anker scannen kontinuierlich im WLAN‑Segment. Beim BLE‑Scanning definiert das Scan‑Intervall den Zeitraum zwischen zwei Scans, während das Scan‑Fenster die tatsächliche Scandauer innerhalb dieses Intervalls beschreibt. Das Intervall kann gemäß Bluetooth‑Spezifikation zwischen 4 ms und 10,24 s liegen, das Fenster muss kleiner oder gleich dem Intervall sein【137338906953372†L74-L89】. Für eine kontinuierliche Erfassung wird das Scan‑Fenster gleich dem Intervall gesetzt (Duty‑Cycle 100 %), wie auch im Handbuch des TEKTELIC Asset Tracker beschrieben【765599799355057†L2216-L2225】.

## Marktrecherche / Technologievergleich

Für die Auswahl der Ortungstechnologie wurden BLE, UWB und RFID betrachtet. Eine Quelle fasst die Charakteristika zusammen: UWB liefert sehr hohe Genauigkeit (~30 cm) bei hohen Kosten und komplexer Infrastruktur; BLE bietet mittlere Genauigkeit (~1 m), geringe Kosten und Reichweiten bis zu 300 m; RFID ist günstig, aber Reichweite und Genauigkeit sind begrenzt【953518879992435†L250-L312】. Für das Bahnumfeld erscheint BLE aufgrund des Kosten‑Nutzen‑Verhältnisses und der Energieeffizienz am geeignetsten. UWB könnte in zukünftigen Ausbaustufen für höhere Präzision in kritischen Zonen integriert werden.

## Datenschutz‑ und Sicherheitskonzept

Positionsdaten gelten als personenbezogene Daten und unterliegen der DSGVO. Eine rechtmäßige Verarbeitung setzt eine eindeutige Rechtsgrundlage voraus (Einwilligung oder berechtigtes Interesse). Die 22Academy hebt hervor, dass Geolokalisierungsdaten als sensibel gelten und nur zweckgebunden gespeichert werden dürfen; Transparenz und Datenminimierung sind zwingend【200088409187489†L69-L140】. Die EDPB‑Richtlinien zu Pseudonymisierung erklären, dass pseudonymisierte Daten weiterhin personenbezogen sind und zusätzliche Schutzmaßnahmen notwendig bleiben【839086812867505†L11-L33】. Deshalb implementiert der Prototyp folgende Maßnahmen:

* **Pseudonymisierung:** Wearable‑UIDs werden in der UI nicht direkt Personen zugeordnet; Zuordnungen sind getrennt und rollenbasiert geschützt.
* **Zugriffskontrolle:** Rollen (admin, operator, viewer) mit minimalen Berechtigungen; Authentifizierung mittels JWT.
* **Transportverschlüsselung:** MQTT kann optional mit TLS betrieben werden, und das Backend nutzt HTTPS.
* **Retention Policies:** Roh‑Scans werden 7 Tage, Positionen 30 Tage und Events 180 Tage gespeichert; danach automatisches Löschen.
* **Audit‑Logs:** Jede Änderung an Benutzer‑ und Rolleninformationen wird protokolliert.

Weitere Details zu Datenschutz und Sicherheitsmaßnahmen finden sich in [privacy-security.md](privacy-security.md).

## Schnellstart

1. Kopiere `.env.example` nach `.env` und passe die Variablen an.
2. Starte alle Services mit `make up`. Dadurch werden MQTT‑Broker, Datenbank, API, Ingestor und Locator gestartet.
3. Führe `make seed` aus, um Demo‑Geräte und einen Admin‑Benutzer anzulegen.
4. Öffne das Dashboard unter [http://localhost:8000](http://localhost:8000) und melde dich mit Benutzername `admin`/Passwort `admin` an.
5. Die WebSocket‑URL für Live‑Positionen ist `/ws/positions`.

## Weitere Arbeitsschritte

Der vorliegende Prototyp bildet die Grundlage für Feldtests. Für die Abnahme sind folgende Punkte zu validieren (siehe [test-plan.md](test-plan.md)):

* Genauigkeit < 5 m im Freifeld.
* Alarm‑Latenz (Notfallknopf bis Anzeige) ≤ 30 s.
* Batterielaufzeit > 8 h bei konfigurierten Intervallen.
* Offline‑Pufferung und Synchronisation nach Wiederverbindung.
