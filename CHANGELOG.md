# Änderungen

## Unveröffentlicht

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
