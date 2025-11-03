# Datenschutz‑ und Sicherheitskonzept

Dieser Abschnitt erläutert, wie der RTLS‑Prototyp die Anforderungen an Datenschutz und Sicherheit im Rahmen der DSGVO erfüllt.

## Rechtliche Grundlagen

Geolokalisierungsdaten sind personenbezogene Daten. Sie können sensible Informationen über Arbeitszeiten, Bewegungsprofile oder Gesundheitszustand offenlegen und unterliegen daher strengen Vorgaben. Die 22Academy betont, dass eine Verarbeitung nur mit gültiger Rechtsgrundlage (z.B. Einwilligung oder berechtigtes Interesse) zulässig ist und dass Datenminimierung sowie Transparenz gewährleistet werden müssen. Die EDPB führt aus, dass Pseudonymisierung das Risiko reduziert, aber pseudonymisierte Daten weiterhin personenbezogen bleiben und zusätzliche Schutzmaßnahmen erforderlich sind.

## Maßnahmen im Prototyp

### Pseudonymisierung und Trennung der Zuordnung

Wearables senden nur eine UID; die Zuordnung zu einer Person (Name, Kontaktdaten) wird in einer separaten Tabelle gespeichert, die nur Administratoren einsehen können. Im Dashboard erscheinen lediglich anonyme Marker. Damit wird das Risiko bei einem Datenabfluss reduziert.

### Rollenbasierte Zugriffskontrolle

Das Backend implementiert Rollen (admin, operator, viewer) mittels JWT. Nur Administratoren können Benutzer anlegen oder die Zuordnung zwischen UID und Person einsehen. Operatoren dürfen Geräte verwalten, Viewer können lediglich Positionsdaten einsehen. Diese Trennung stellt sicher, dass nur berechtigte Personen auf personenbezogene Informationen zugreifen.

### Verschlüsselung und Integrität

* **Transport:** Der MQTT‑Broker kann TLS verwenden. Für den Testbetrieb ist der Broker offen, in der Produktion muss TLS konfiguriert werden. Die FastAPI‑Schnittstelle sollte hinter einem Reverse Proxy (z.B. Nginx) mit HTTPS betrieben werden.
* **Speicherung:** Passwörter werden mit Argon2 gehasht. Datenbanken können auf Verschlüsselung auf Dateisystemebene (LUKS) betrieben werden.

### Retention und Löschung

Die Datenbank ist so konfiguriert, dass Roh‑Scans nach 7 Tagen, Positionsdaten nach 30 Tagen und Events nach 180 Tagen gelöscht werden. Diese Werte sind konfigurierbar via Umgebungsvariablen. Damit wird das Prinzip der Speicherbegrenzung umgesetzt.

### Audit und Transparenz

Alle sicherheitsrelevanten Aktionen (z.B. Benutzeranlage, Rollenänderungen, Alarmbearbeitungen) werden in der Tabelle `events` mit dem ausführenden Benutzer protokolliert. Ein Audit‑Log ermöglicht die Nachvollziehbarkeit und unterstützt bei Datenschutzanfragen.

### Einwilligung und Information

Vor dem Einsatz des Systems muss eine Datenschutz‑Folgenabschätzung durchgeführt werden. Mitarbeiter sind transparent über Zweck, Umfang und Dauer der Ortung zu informieren und müssen ggf. ihre Einwilligung erteilen oder der Verarbeitung widersprechen können. Die Datenverarbeitung ist regelmässig zu überprüfen und anzupassen.