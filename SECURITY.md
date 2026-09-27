# Sicherheit und Datenschutz

Private Captures, Zugangsdaten und signierte Requests gehören ausschließlich nach
`private/` oder `captures/`. Beide Verzeichnisse sind von Git ausgeschlossen.
Standardtests blockieren Netzwerkverbindungen und verwenden synthetische Sitzungen.

Bitte Sicherheitsprobleme über GitHubs **Security → Report a vulnerability** melden,
wenn private Meldungen im Repository verfügbar sind. Andernfalls zunächst nur eine
abstrakte Problembeschreibung ohne ausnutzbare Details oder Geheimnisse im Issue
veröffentlichen. Keine Kontogeheimnisse an Maintainer senden.

Konto und Passwort liegen als benannte Werte in `secrets.yaml`; Config Entries
enthalten nur Referenzen und Konfiguration. Tokens werden getrennt unter
`.storage` gespeichert. Neue private Dateien erhalten Modus `0600`.
HA-Konfiguration und Backups können Zugangsdaten enthalten. `secrets.yaml` ist
Klartext; die Integration behauptet keine zusätzliche Verschlüsselung.
Diagnoseexporte und Logs werden aus einer erlaubten Feldauswahl aufgebaut.
Auch bei Debug-Logging werden keine Zugangsdaten oder freien Serverantworten
ausgegeben. Fehler beim Parsen von Secrets werden nicht mit YAML-Inhalten
protokolliert.

Die automatische Anmeldung wird ausdrücklich aktiviert. Ein erneuter Login
erfolgt nur bei bestätigtem Sitzungsablauf. Benutzerkennung und gewählte Geräte
werden geprüft, bevor ein neuer Token dauerhaft ersetzt wird. MFA/CAPTCHA und
abgelehnte Anmeldungen erfordern Benutzeraktion; sie werden nicht umgangen.

Der Transport akzeptiert nur den festen EU-Aqara-Host, prüft TLS-Zertifikate,
verweigert Redirects und begrenzt entpackte Antworten. Es gibt keine Telemetrie,
keinen beliebigen HTTP-Dienst und keine Geräte-Schreibaktionen.
