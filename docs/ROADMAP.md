# Roadmap und Live-Gates

| Paket | Softwarestand dieser Beta | Ausstehende Abnahme |
|---|---|---|
| P0 | Vier Fixtures aus vollständiger Spezifikation rekonstruiert | Kein separates Starter-ZIP vorhanden |
| P1 | Datenmodell, Parser, Isolation, Datenqualität | Laufende Protokolländerungen beobachten |
| P2 | Sicherer lokaler Import; G1 am 27.09.2026 mit eigenen Originalbytes bestanden | Keine Aussage zur aktuellen Sitzungsgültigkeit |
| P3 | Async-Transport; regulärer Trait-Abruf mit zwei Geräten erfolgreich | Unabhängige physische Wertänderung prüfen |
| P4 | G1 und regulärer G2-Abruf bestanden; experimenteller Betrieb | G3-Prüfung am eigenen Konto |
| P5 | Reale Anmeldung, privater Sitzungsspeicher und Secret-Referenzen funktionieren | Echte Sitzungserneuerung am Nutzerkonto |
| P6 | Einrichtung und Geräteabruf im Nutzer-HA bestätigt | Verhalten über längeren Betrieb beobachten |
| P7 | Bereinigte Diagnose, Repairs, Dashboard, Dokumentation | Lokales Feedback zur Oberfläche |
| P8 | Tests, HACS-Paket, CI und Beta-Release | Staging-HA, G5/G6 und 24-Stunden-Lauf |
| P9 | Präsenz ausdrücklich ungemappt | G4: drei vollständige Anwesenheitszyklen je Gerät |
| P10 | 81 Ressourcen und sieben Einstellungen implementiert; beide Endpunkte mit zwei FP2 live bestätigt | Fehlende Felder in anderen Modi, Position und Schlafberichte separat belegen |

## Reaktionszeit und Push

Priorisiertes Polling, getrennte Einstellungsintervalle und ein begrenzter
Geschwindigkeitstest sind ab 0.4.0b1 implementiert. Die nächste Erweiterung
folgt dem [quellenbelegten Push-Plan](PUSH_PLAN.md): vorhandene lokale
HomeKit-Präsenz zuordnen, danach OpenAPI-/RocketMQ-Vitaldaten mit separatem
Entwicklerzugang am eigenen Konto prüfen. Der Offline-Prototyp ist kein
Live-Push-Nachweis.

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
ermöglicht diese Beta die Anmeldung und den experimentellen Betrieb vor Abschluss
dieser Langzeitnachweise. Die Zustimmung erlaubt die jeweiligen Kontozugriffe;
sie verändert keinen Evidenzstatus. Eine Anmeldung wird erst beim bewussten
Start ausgeführt, nicht beim Installieren der Integration.
