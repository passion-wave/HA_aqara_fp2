<p align="center"><img src="docs/assets/banner.svg" alt="Aqara Presence Lab — zusätzliche Cloud-Daten, nachvollziehbare Qualität" width="100%"></p>

# Aqara Presence Lab

[![CI](https://github.com/passion-wave/HA_aqara_fp2/actions/workflows/ci.yml/badge.svg)](https://github.com/passion-wave/HA_aqara_fp2/actions/workflows/ci.yml)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://www.hacs.xyz/docs/faq/custom_repositories/)
[![Status](https://img.shields.io/badge/status-experimentelle%20Beta-f59e0b)](docs/VALIDIERUNG.md)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Eine native Home-Assistant-Custom-Integration zur Untersuchung zusätzlicher
**Aqara-FP2-Cloud-Daten**. Sie ergänzt die bestehende lokale HomeKit-Anbindung.
Die Integration benötigt keinen eigenen Cloud-Dienst, keinen Supervisor und
keinen dauerhaft laufenden Proxy.

> **Version 0.1.0b1 ist eine Labor-Beta.** Das HACS-Paket, die Offline-Vorschau,
> Parser, Prüfwerkzeuge und HA-Anbindung sind implementiert. Der private
> Aqara-Trait-Endpunkt ist am eigenen Konto noch nicht live bestätigt.
> **Produktives Cloud-Polling bleibt deshalb gesperrt.** Eine Installation
> allein liefert noch keine laufenden Cloud-Sensoren.

## Funktionsumfang

| Bereich | Stand |
|---|---|
| HACS-Custom-Repository / manuelle Installation | Installierbares Paket |
| Einrichtung in Deutsch und Englisch | Offline-Vorschau und verständliche Live-Sperre |
| Helligkeit | Parser erhält 9 / 110 lx unverändert; als „zuletzt gemeldet“ modelliert |
| Rohe Präsenz-, Geräte- und Sturzfelder | Diagnosewerte ohne erfundene Enum-Bedeutung |
| Asynchroner API-Client | Fester EU-Host, TLS, Limits, Rate-Limiter, Fehlerisolation |
| Lokaler Signaturvergleich / einzelne Leseprobe | Explizite Laborwerkzeuge; keine automatische Freigabe |
| HA-Lebenszyklus, Entitäten und Reauth | Gegen simulierte Antworten testbar |
| Dauerpolling / automatische Anmeldung | Gesperrt bis zu unabhängigen Live-Nachweisen |
| Cloud-Präsenz, Personenanzahl, Positionen, Schlaf | Nicht freigegeben; keine Scheinentitäten |

`positionId` ist eine Ortsreferenz, keine Personenkoordinate. Ein erfolgreicher
HTTP-Abruf beweist keine neue physische Messung. Fehlende Werte werden niemals
durch `0`, `false` oder einen Default ersetzt.

## Installation

Voraussetzung für diese Beta: **Home Assistant 2026.9.3**, Python 3.14.
Diese Version ist die getestete Basis, keine Zusage für ältere Versionen.

1. Home-Assistant-Konfiguration sichern.
2. In HACS unter **Benutzerdefinierte Repositories**
   `https://github.com/passion-wave/HA_aqara_fp2` mit Typ **Integration** hinzufügen.
3. **Aqara Presence Lab** herunterladen; für die Beta gegebenenfalls
   Vorabversionen anzeigen lassen. Home Assistant neu starten.
4. Unter **Einstellungen → Geräte & Dienste → Integration hinzufügen** nach
   **Aqara Presence Lab** suchen und die **Offline-Vorschau** öffnen.

Alternativ den Ordner `custom_components/aqara_presence_lab` aus dem Repository
oder Release-ZIP nach `/config/custom_components/aqara_presence_lab` kopieren.
Bestehende HomeKit-Geräte bleiben bestehen; kein Reset oder erneutes Pairing nötig.

Die Vorschau zeigt ausdrücklich historische Beispieldaten vom **25.09.2026** und
erstellt keine produktiven Präsenzentitäten. Der Live-Assistent erläutert die noch
offenen Nachweise. Zugangsdaten niemals in GitHub-Issues oder Chats einfügen.

## Dokumentation

| Dokument | Inhalt |
|---|---|
| [Installation und Betrieb](docs/INSTALLATION.md) | HACS, Docker, Update, Diagnose und Rollback |
| [Validierung](docs/VALIDIERUNG.md) | Tatsächliche Tests, Grenzen und offene Gates |
| [Lokales Labor](docs/LAB.md) | Offline-Analyse, Import, Signaturvergleich und Leseprobe |
| [Architektur](docs/ARCHITECTURE.md) | Datenfluss, Identität, Qualität und Sicherheit |
| [Roadmap](docs/ROADMAP.md) | P0–P10 und nächste Live-Nachweise |
| [Dashboard](examples/dashboard.yaml) | Separate Standardkarten mit Platzhalter-IDs |
| [Protokollquelle](docs/PROTOCOL_SOURCE.md) | Fixierter Quellstand und Lizenzprüfung |
| [Vollständiger Auftrag](docs/IMPLEMENTIERUNG.md) | Unveränderte Spezifikation inklusive Fixtures |

## Entwicklung und Support

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest --cov
```

Tests verwenden keine echten Aqara-Zugangsdaten und blockieren Netzwerk-Sockets.
Sie ersetzen weder den Gerätetest noch den geforderten 24-Stunden-Lauf.
Details: [Mitentwickeln](CONTRIBUTING.md), [Datenschutz](SECURITY.md),
[Änderungen](CHANGELOG.md), [Fehler melden](https://github.com/passion-wave/HA_aqara_fp2/issues/new/choose).

Ein unabhängiges Community-Projekt von Passion Wave, nicht von Aqara unterstützt.
Nutzung als HACS-Custom-Repository bedeutet keine Aufnahme in den HACS-Standardkatalog.

