# Sicherheit und Datenschutz

Private Captures, Zugangsdaten und signierte Requests gehören ausschließlich nach
`private/` oder `captures/`. Beide Verzeichnisse sind von Git ausgeschlossen.
Standardtests blockieren Netzwerkverbindungen und verwenden synthetische Sitzungen.

Bitte Sicherheitsprobleme über GitHubs **Security → Report a vulnerability** melden,
wenn private Meldungen im Repository verfügbar sind. Andernfalls zunächst nur eine
abstrakte Problembeschreibung ohne ausnutzbare Details oder Geheimnisse im Issue
veröffentlichen. Keine Kontogeheimnisse an Maintainer senden.

HA-Konfiguration und Backups können Zugangsdaten enthalten. Diese Integration
behauptet keine zusätzliche Verschlüsselung gespeicherter Config Entries.
Diagnoseexporte werden aus einer erlaubten Feldauswahl neu aufgebaut.

Der Transport akzeptiert nur den festen EU-Aqara-Host, prüft TLS-Zertifikate,
verweigert Redirects und begrenzt entpackte Antworten. Es gibt keine Telemetrie,
keinen beliebigen HTTP-Dienst und keine Geräte-Schreibaktionen.

