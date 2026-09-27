<p align="center"><img src="docs/assets/banner.svg" alt="Aqara Presence Lab — zusätzliche Cloud-Daten, nachvollziehbare Qualität" width="100%"></p>

# Aqara Presence Lab

[![CI](https://github.com/passion-wave/HA_aqara_fp2/actions/workflows/ci.yml/badge.svg)](https://github.com/passion-wave/HA_aqara_fp2/actions/workflows/ci.yml)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://www.hacs.xyz/docs/faq/custom_repositories/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Eine Home-Assistant-Integration für zusätzliche **Aqara-FP2-Cloud-Daten** mit
Anmeldung am europäischen Aqara-Konto, lokaler Speicherung in `secrets.yaml`
und automatischer Neuanmeldung nach bestätigtem Sitzungsablauf.
Die vorhandene lokale HomeKit-Anbindung bleibt unabhängig.

> **0.2.0b1 ist eine experimentelle Anmelde-Beta.** Sie bietet einen vollständigen
> Einrichtungs- und Wiederanmeldeweg. Der Login basiert auf dem belegten
> SleepRadar-Protokoll; seine reale Funktion am jeweiligen Konto wird erst bei
> der bewusst gestarteten Anmeldung geprüft. Softwaretests ersetzen keine
> Live-Abnahme oder Langzeitprüfung.

## Funktionen

- Anmeldung mit Aqara-Konto und Passwort; alternativ vorhandene Einträge in `secrets.yaml` verwenden.
- Passwörter getrennt von Config Entries, Sitzungstokens in einem privaten lokalen Speicher.
- Automatische Neuanmeldung bei bestätigtem Tokenablauf mit Prüfung derselben Kontoidentität und des Gerätezugriffs.
- Ein gemeinsamer Datenabruf pro Konto, konfigurierbares Intervall und manuelle Aktualisierung mit gemeinsamem Mindestabstand.
- Zuletzt gemeldete Helligkeit, numerische Rohcodes, Verbindungsstatus und Datenqualität.
- Bereinigte Diagnose und Ereignislogs ohne Zugangsdaten, signierte Header oder Rohantworten.
- Deutsche und englische Oberfläche; Reauth und Geräteänderungen erhalten die bestehende Kontoidentität.

Die Einrichtung benötigt die Geräte-IDs der gewünschten FP2. Eine automatische
Gerätesuche über einen unbelegten Endpunkt wird nicht vorausgesetzt. Die
Cloud-Präsenzcodes haben noch keine bestätigte Bedeutung; Personenanzahl,
Koordinaten und Schlafdaten sind nicht freigegeben. Ein HTTP-Erfolg beweist
keine neue physische Messung.

## Installation und Start

Getestete Basis: **Home Assistant 2026.9.3**, Python 3.14, Aqara-Region **EU**.

1. In HACS als benutzerdefiniertes Repository hinzufügen:
   `https://github.com/passion-wave/HA_aqara_fp2`, Kategorie **Integration**.
2. **Aqara Presence Lab**, Version **0.2.0b1**, herunterladen und Home Assistant neu starten.
3. Unter **Einstellungen → Geräte & Dienste → Integration hinzufügen** nach **Aqara Presence Lab** suchen.
4. Den Anmeldeweg öffnen, automatische Anmeldung erlauben und Zugangsdaten lokal eingeben oder vorhandene Secret-Namen angeben.
5. Geräte-IDs eintragen, die Verbindungsprüfung abwarten und Geräte sowie Intervall auswählen.

Die Einrichtungsprüfung kann wegen der gemeinsamen Mindestabstände etwas dauern.
Nach erfolgreichem Login und Geräteabruf entstehen die zusätzlichen Entitäten.
Die Offline-Vorschau bleibt als unabhängige Erklärung verfügbar.

`secrets.yaml` ist eine lokale Klartextdatei, kein verschlüsselter Tresor.
Home-Assistant-Verzeichnis und Backups enthalten deshalb Zugangsdaten.
Die Integration gibt diese weder in Logs noch in Diagnoseexporten aus.

## Dokumentation

| Dokument | Inhalt |
|---|---|
| [Installation und Betrieb](docs/INSTALLATION.md) | Einrichtung, HACS-Update, Reauth und Entfernen |
| [Anmeldung und Speicherung](docs/AUTHENTICATION.md) | Secret-Einträge, Sitzungswechsel und Fehlerverhalten |
| [Logs und Diagnose](docs/LOGGING.md) | Ereignisse, Logstufen und bereinigte Supportdaten |
| [Validierung](docs/VALIDIERUNG.md) | Tatsächliche Tests und offene Live-Nachweise |
| [Lokales Labor](docs/LAB.md) | HAR-Import, Signaturvergleich und Einzelproben |
| [Architektur](docs/ARCHITECTURE.md) | Datenfluss, Identität und Lebenszyklus |
| [Roadmap](docs/ROADMAP.md) | Ausstehende Protokoll- und Langzeitprüfungen |
| [Dashboard](examples/dashboard.yaml) | Standardkarten mit Platzhalter-Entitäten |
| [Protokollquelle](docs/PROTOCOL_SOURCE.md) | Fixierter SleepRadar-Quellstand und Lizenz |
| [Ursprünglicher Auftrag](docs/IMPLEMENTIERUNG.md) | Unveränderte Spezifikation und Fixtures |

## Entwicklung

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest --cov
.venv/bin/ruff check .
.venv/bin/mypy
```

Standardtests verwenden synthetische Konten und blockieren Netzwerk-Sockets.
Details: [Mitentwickeln](CONTRIBUTING.md), [Datenschutz](SECURITY.md),
[Änderungen](CHANGELOG.md).

Ein unabhängiges Community-Projekt von Passion Wave, nicht von Aqara unterstützt.
Die Verwendung als HACS-Custom-Repository bedeutet keine Aufnahme in den HACS-Standardkatalog.
