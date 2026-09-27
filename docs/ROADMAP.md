# Roadmap und Live-Gates

| Paket | Softwarestand dieser Beta | Ausstehende Abnahme |
|---|---|---|
| P0 | Vier Fixtures aus vollständiger Spezifikation rekonstruiert | Kein separates Starter-ZIP vorhanden |
| P1 | Datenmodell, Parser, Isolation, Datenqualität | Laufende Protokolländerungen beobachten |
| P2 | Sicherer lokaler Import; G1 am 27.09.2026 mit eigenen Originalbytes bestanden | Keine Aussage zur aktuellen Sitzungsgültigkeit |
| P3 | Async-Transport; erste autorisierte G2-Probe mit Anwendungsfehler abgelehnt | Ursache klären; erfolgreicher G2-Abruf fehlt |
| P4 | Profilversion und Prüfstatus; G1 bestanden | G2–G3 fehlen; produktiver Pfad bleibt gesperrt |
| P5 | AuthProvider und Login-Kandidat | Identitätsnachweis, realer Login / Ablauf und Einwilligung |
| P6 | Config Flow, Coordinator, Entitäten | Geräteprüfung nach P4 |
| P7 | Bereinigte Diagnose, Repairs, Dashboard, Dokumentation | Lokales Feedback zur Oberfläche |
| P8 | Tests, HACS-Paket, CI und Beta-Release | Staging-HA, G5/G6 und 24-Stunden-Lauf |
| P9 | Präsenz ausdrücklich ungemappt | G4: drei vollständige Anwesenheitszyklen je Gerät |
| P10 | Keine erfundenen Zusatzfähigkeiten | Separate Captures für Schlaf / Position / Anzahl |

## Erforderliche Nachweise

1. **G0:** Offline-Datenvertrag mit pseudonymisierten Fixtures prüfen.
2. **G1:** Signatur zu originalen Body-Bytes lokal konstantzeitlich vergleichen.
3. **G2:** Eine bewusst gestartete, neu signierte Leseprobe am festen EU-Endpunkt.
4. **G3:** Probe mit geschlossener App, ohne Proxy und mit unabhängiger Wertänderung;
   `needSubscribe`-Verhalten und Kontoidentität klären.
5. **G4:** Präsenzsemantik pro Gerät/Modus mit drei vollständigen Zyklen belegen.
6. **G5:** Sitzungserneuerung, Neustart und Kontoabweichung am realen Konto prüfen.
7. **G6:** Mindestens 24 Stunden konservativer Beobachtung inklusive Ausfall und
   Neustart. Erst danach Produktionsfreigabe dokumentieren.

Ein Endpunkt-Erfolg ist keine Freigabe von G3–G6. Es gibt keine automatische
Freischaltung durch einen Laborbericht und keinen Schalter, der fehlende Evidenz ersetzt.
