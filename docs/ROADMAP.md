# Roadmap und Live-Gates

| Paket | Softwarestand dieser Beta | Ausstehende Abnahme |
|---|---|---|
| P0 | Vier Fixtures aus vollständiger Spezifikation rekonstruiert | Kein separates Starter-ZIP vorhanden |
| P1 | Datenmodell, Parser, Isolation, Datenqualität | Laufende Protokolländerungen beobachten |
| P2 | Sicherer lokaler Import; G1 am 27.09.2026 mit eigenen Originalbytes bestanden | Keine Aussage zur aktuellen Sitzungsgültigkeit |
| P3 | Async-Transport; vier autorisierte G2-Proben, Server bestätigt abgelehnte Sitzung | Anmeldung für aktuelle Sitzung; erfolgreicher G2-Abruf fehlt |
| P4 | G1 bestanden; explizit aktivierbarer experimenteller Anmeldeweg in 0.2.0b1 | Erfolgreiche G2-/G3-Prüfung am eigenen Konto |
| P5 | Login, privater Sitzungsspeicher, Secret-Referenzen und automatische Neuanmeldung implementiert | Reale Anmeldung und Sitzungserneuerung am Nutzerkonto |
| P6 | Vollständige Einrichtung, Reauth, Coordinator, Entitäten und Lebenszyklus | Erstinstallation und Betrieb im Nutzer-HA |
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

Ein Endpunkt-Erfolg ist keine Freigabe von G3–G6. Auf ausdrücklichen Nutzerauftrag
ermöglicht 0.2.0b1 die Anmeldung und den experimentellen Betrieb vor Abschluss
dieser Langzeitnachweise. Die Zustimmung erlaubt die jeweiligen Kontozugriffe;
sie verändert keinen Evidenzstatus. Eine Anmeldung wird erst beim bewussten
Start ausgeführt, nicht beim Installieren der Integration.
