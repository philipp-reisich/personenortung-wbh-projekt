Dieses Projekt nutzt **Docker** zur Containerisierung des gesamten Systems – bestehend aus Backend, Datenbank, MQTT-Broker und Dashboard.  
Bitte stelle sicher, dass **Docker** und **Docker Compose** auf deinem System installiert sind.

### 🧩 Voraussetzungen
- [Docker Desktop](https://www.docker.com/get-started/) (oder Docker Engine)
- `make` (unter macOS und Linux vorinstalliert, unter Windows via WSL verfügbar)

---

### ▶️ Projekt starten

1. **Repository klonen und ins Projektverzeichnis wechseln:**
   ```
   git clone <repo-url>
   cd rtls
   ```

2. **Container erstellen und starten:**
   ```
   make up
   ```

3. **Backend und Dashboard starten:**
   ```
   make start
   ```

4. **Anschließend ist das Dashboard erreichbar unter:**  
   👉 http://localhost:8000

---

### 🛑 Projekt stoppen

Um alle laufenden Container zu beenden und Ressourcen freizugeben:
```
make down
```

---

### 📦 Enthaltene Services

| Service                            | Beschreibung                                                                                      |
|----------------------------------|-------------------------------------------------------------------------------------------------|
| Backend (Python/FastAPI)          | Stellt die REST- und WebSocket-Schnittstellen bereit und kommuniziert mit der Datenbank.        |
| TimescaleDB (PostgreSQL-basierte Datenbank) | Speichert Positionsdaten, Scans und Gerätestatus.                                    |
| MQTT-Broker (z. B. Eclipse Mosquitto)         | Vermittelt Nachrichten zwischen Anchors, Wearables und Backend.                     |
| Dashboard (HTML/JS – Leaflet-basiert)         | Visualisiert alle Geräte, Positionen und Systemzustände in Echtzeit.                 |

---

### 📘 Hinweis:
Die Datei `.env` enthält alle Konfigurationsparameter (z. B. Zugangsdaten, Ports).  
```
