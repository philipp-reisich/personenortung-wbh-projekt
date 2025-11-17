Dieses Projekt nutzt **Docker** zur Containerisierung des gesamten Systems – bestehend aus Backend, Datenbank, MQTT-Broker und Dashboard.  
Bitte stelle sicher, dass **Docker** und **Docker Compose** auf deinem System installiert sind.

### 🧩 Voraussetzungen
- [Docker Desktop](https://www.docker.com/get-started/) (oder Docker Engine)
- [Docker Compose](https://docs.docker.com/compose/install/)
- `make` (unter macOS und Linux vorinstalliert, unter Windows via WSL verfügbar)

---

### ▶️ Projekt starten

1. **Repository klonen und ins Projektverzeichnis wechseln:**
   ```bash
   git clone <repo-url>
   cd personenortung-wbh-projekt
   ```

2. **Umgebungsvariablen konfigurieren:**
   ```bash
   cp .env.example .env
   # Bearbeite .env und passe die Werte an (z.B. Passwörter, Ports)
   ```

3. **Container erstellen und starten:**
   ```bash
   make up
   ```

4. **Optional: Beispieldaten laden (Anchors, Wearables, Admin-User):**
   ```bash
   make seed
   ```

5. **Dashboard öffnen:**
   👉 http://localhost:8000

   **Standard-Login:**
   - Benutzername: `admin`
   - Passwort: `admin` (siehe [api/scripts/seed.py](api/scripts/seed.py))

---

### 🛑 Projekt stoppen

Um alle laufenden Container zu beenden:
```bash
make down
```

---

### 📦 Enthaltene Services

| Service | Port | Beschreibung |
|---------|------|--------------|
| **API (FastAPI)** | 8000 | REST- und WebSocket-Schnittstellen, Dashboard |
| **TimescaleDB** | 5432 | PostgreSQL-basierte Zeitreihendatenbank |
| **MQTT Broker (Mosquitto)** | 1883 | Nachrichtenvermittlung zwischen Anchors/Wearables |
| **Ingestor** | - | Validiert und persistiert MQTT-Nachrichten |
| **Locator** | - | Berechnet Positionen aus RSSI-Daten |

---

### 🔧 Nützliche Befehle

```bash
make logs          # Live-Logs aller Services anzeigen
make seed          # Beispieldaten in DB laden
make test          # Tests ausführen
make restart       # Services neu starten
```

---

### 📘 Weitere Dokumentation

- [Architektur](docs/architecture.md) - Systemübersicht und Datenfluss
- [MQTT Topics](docs/mqtt-topics.md) - Nachrichtenformate und Topics
- [Privacy & Security](docs/privacy-security.md) - Datenschutzkonzept
- [Database Schema](db/schema.sql) - Datenbankstruktur

---

### 🔐 Sicherheitshinweis

⚠️ **Wichtig:** Die `.env`-Datei enthält sensible Zugangsdaten. Bitte:
- Ändere alle Standard-Passwörter vor dem Produktiveinsatz
- Füge `.env` niemals zu Git hinzu (bereits in [.gitignore](.gitignore) enthalten)
- Verwende starke, zufällige Passwörter für `SECRET_KEY`, `POSTGRES_PASSWORD`, etc.