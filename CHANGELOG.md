# Änderungen

## 0.3.0b1 — Zusätzliche FP2-Daten

- Zwei zusätzliche, ausschließlich lesende Ressourcenabfragen mit 81 Statusfeldern und sieben Einstellungen pro Gerät.
- Gerätemodus, gemeldete Personenzählung, Zonen und Statistiken sowie Schlaf-, Herz-, Atem- und Bewegungswerte bei gemeldetem Schlafmodus.
- Dynamische Entitäten nur für gelieferte Werte, optionale Zonen-/Einstellungsentitäten und deutscher/englischer Oberfläche.
- Hintergrundabruf mit gemeinsamem Kontolimit, Geräte- und Gruppenisolation, eigener Verfügbarkeit und bereinigtem Zusatzdatenstatus.
- Keine Modusänderung, keine Ersatznullen, keine Übernahme alter Werte nach Teilantworten und keine abgeleitete Position aus unbekannten Codes.
- Live-Anmeldung und bisheriger Trait-Abruf mit zwei eigenen FP2 bestätigt; weitere Live-Ergebnisse und Testzahlen im [Validierungsbericht](docs/VALIDIERUNG.md).

## 0.2.0b1 — Anmelde-Beta

- Vollständiger EU-Anmeldeweg auf Basis des SleepRadar-Loginvertrags mit Fortschrittsanzeige und serverseitiger Kontoprüfung.
- Konto und Passwort als lokale `secrets.yaml`-Einträge oder vorhandene Secret-Referenzen; private Sitzungsspeicherung außerhalb von Config Entries.
- Automatische Neuanmeldung nach bestätigtem Sitzungsablauf, gemeinsamer Kontolimiter und geprüfte Übernahme neuer Tokens; vorübergehende Verbindungsfehler erlauben spätere Versuche nach Backoff.
- Einrichtung, Reauth, Geräteauswahl, Neustart und Entfernen mit konsistenter Kontoidentität; Migration alter Einträge verlangt neue Anmeldung.
- Aussagekräftige bereinigte Ereignislogs und Diagnosen ohne Credentials oder rohe Serverantworten.
- Reale Kontoanmeldung und Langzeitprüfung bleiben ausstehend; die Beta startet nur nach ausdrücklicher Aktivierung des experimentellen Anmeldewegs.

- Proxyman-HAR mit redundanten JSON-Parametern importieren, ohne Bodybytes zu verändern.
- Erster echter lokaler G1-Signaturvergleich am 27.09.2026 bestanden; G2 und weitere Live-Nachweise bleiben offen.
- Bereinigte Diagnose um beobachteten HTTP-Status und begrenzte numerische Anwendungscodes erweitern; keine automatischen Wiederholungen oder Deutung unbekannter Codes.
- Vier autorisierte G2-Proben dokumentiert: Der private Endpunkt bestätigt die Ablehnung der Sitzung mit Code 108 und `Token has expired`; kein erfolgreicher Live-Abruf.

## 0.1.0b1 — 2026-09-26

Erste installierbare Labor-Beta für HACS-Custom-Repositories.

- Gemeinsamer strikter Parser mit typisierten Beobachtungen, Geräteisolation und Datenqualität.
- EU-Signaturkandidat, sicherer Import, lokaler Signaturvergleich und kontrollierte Leseprobe.
- Asynchroner Transport, Fehlerklassifikation, Rate-Limiter und AuthProvider.
- HA-Einrichtung, Offline-Vorschau, Coordinator, Diagnose, Sensor-/Button-Plattformen und Repairs.
- Deutsche und englische Oberfläche, Beispiel-Dashboard, Tests und GitHub-CI.
- Produktives Polling, automatische Anmeldung und Cloud-Präsenz bleiben bis zu Live-Nachweisen gesperrt.
