# Test‑Plan und Abnahmekriterien

Dieser Testplan beschreibt die notwendigen Schritte zur Validierung des RTLS‑Prototyps im Labor und im Feld. Er erfüllt die Muss‑ und Soll‑Anforderungen aus dem Pflichtenheft.

## Unit‑ und Integrationstests

Die Codebasis enthält Pytest‑basierte Tests für kritische Komponenten:

\* **Locator:** Tests in `tests/test_locator.py` prüfen die Proximity‑Berechnung, insbesondere die korrekte Gewichtung der RSSI‑Werte und die Abwesenheit von Division‑by‑zero‑Fehlern bei fehlenden Scans. Es werden Randfälle wie weniger als 3 verfügbare Anker simuliert.
\* **API:** Tests in `tests/test_api.py` überprüfen Authentifizierung, Rollen‑Kontrolle und die REST‑Endpunkte für Anchors und Wearables. Die Tests nutzen FastAPIs TestClient, um HTTP‑Requests gegen die Anwendung auszuführen.

Die Unit‑Tests können via `make test` ausgeführt werden. Sie sollten in CI/CD‑Pipelines integriert werden.

## Last‑ und Latenztests

Um die geforderte Alarm‑Latenz von ≤ 30 Sekunden zu überprüfen, sind Lasttests mit simulierten Wearables erforderlich. Folgendes Vorgehen wird empfohlen:

1. **Simulator:** Entwickle ein einfaches Python‑Skript, das mehrere Wearables emuliert, die per MQTT im Intervall von 200 ms Scans erzeugen. Für Notfalltests löst das Skript den Button‑Event aus (z.B. durch Setzen des `adv_seq`‑Bits oder eines zusätzlichen Flags).
2. **Messung:** Messe die Zeit vom Publizieren des Notfall‑Events bis zum Empfang einer Alarmmeldung im Dashboard (per WebSocket). Tools wie Locust oder Apache JMeter können zur Lastgenerierung verwendet werden.
3. **Kriterien:** Die 95. Perzentile der Latenz muss unter 30 Sekunden liegen. Zudem darf bei 10 Wearables mit je 10 Hz keine Daten verloren gehen.

## Labortest

Der Labortest fokussiert sich auf Reichweite und Genauigkeit unter idealen Bedingungen:

1. **Aufbau:** Positioniere drei Anker auf bekannten Koordinaten in einem Freifeld (z.B. Parkplatz) und messe die physische Distanz zwischen den Ankern. Platziere das Wearable an verschiedenen Referenzpunkten (0 m, 5 m, 10 m etc.).
2. **Messung:** Pro Standort werden mindestens 100 Scans aufgenommen. Berechne die geschätzte Position durch den Locator und ermittle den Fehler (euklidische Distanz zum Referenzpunkt).
3. **Ziel:** Der Median‑Fehler muss < 5 m liegen. Bei größerer Entfernung kann der Fehler steigen; dies ist zu dokumentieren.

## Feldtest

Der Feldtest prüft das System unter realen Bedingungen (Baustelle, Tunnel, mehrgeschossige Bahnsteige):

1. **Umgebung:** Installiere Anker im Testareal entsprechend der geplanten Deployment‑Strategie. Kennzeichne Geofences (z.B. Gefahrenzonen).
2. **Tests:** Simuliere typische Arbeitsabläufe (Bewegungen von Arbeitern, Betreten/Verlassen von Zonen, Triggern des Notfall‑Buttons). Überwache die Positionsschätzungen, Zonen‑Events und Alarme.
3. **Abschattung/Mehrwege:** Dokumentiere Szenarien mit Sichtverdeckung, metallischen Strukturen oder Fahrzeugen, um die Robustheit zu beurteilen.
4. **Kriterien:** Alarm‑Latenz ≤ 30 s, durchschnittliche Positionsfehler < 5 m im Freien und akzeptable Fehler (< 10 m) in schwierigen Umgebungen. Datenpufferung bei Offline‑Unterbrechung muss ohne Verlust funktionieren.

## Akzeptanzkriterien‑Matrix

| Kriterium                | Muss/Soll | Prüfmethode                 | Zielwert                |
|--------------------------|-----------|-----------------------------|-------------------------|
| Positionsgenauigkeit     | Muss      | Labor‑ & Feldtest           | Median < 5 m Freifeld   |
| Alarm‑Latenz             | Muss      | Last-/Latenztest            | ≤ 30 s                  |
| Betriebsdauer            | Muss      | Langzeittest (Akkus)        | > 8 h                   |
| Offline‑Pufferung        | Muss      | Netzunterbrechung simulieren| Kein Datenverlust       |
| Rollen/RBAC              | Muss      | API‑Test                    | Zugriff konform Rollen  |
| Geofences/Zonenwarnung   | Soll      | Feldtest                    | Events korrekt erzeugt  |
| Integrationen (Grafana)  | Soll      | Monitoring‑Einbindung       | Dashboards abrufbar     |

Diese Matrix dient als Grundlage für die Abnahmeprotokolle.