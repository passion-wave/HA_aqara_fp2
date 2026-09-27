# Validierungsbericht

**Stand: 27.09.2026 · Integrationsversion: 0.3.0b1 · zusätzliche Ressourcen**

## Testbasis und Nachweisgrenzen

Die Ausgangsdatei `Aqara_Presence_Lab_Implementierung.md` wurde vollständig gelesen
und unverändert als [IMPLEMENTIERUNG.md](IMPLEMENTIERUNG.md) übernommen.
Die vier JSON-Fixtures stammen aus Anhang A: Request mit 31 und 37 Traits,
Antwort mit 20 und 25 Traits. Helligkeit **9 und 110 lx** wird unverändert
gelesen; Geräte werden auch bei umgekehrter Antwortreihenfolge richtig zugeordnet.
Diese historischen Beispiele sind keine aktuellen Messungen.

Der Loginvertrag stammt aus dem festgelegten MIT-lizenzierten
[SleepRadar-Quellstand](PROTOCOL_SOURCE.md). Die Softwareprüfungen verwenden
synthetische Konten und simulierte Serverantworten. Netzwerk-Sockets sind in
den Standardtests gesperrt. Eine erfolgreiche Simulation beweist keine reale
Anmeldung, aktuelle Sensordaten oder einen stabilen Dauerbetrieb.

## Automatisierte Prüfung

Lokaler Abschlusslauf der Version 0.3.0b1: **804 Tests bestanden**, keine fehlgeschlagenen oder
übersprungenen Tests, **94 % Coverage.py-Abdeckung einschließlich Verzweigungen**.
Ruff bestätigt 74 Python-Dateien; Mypy prüft alle 28 Integrationsmodule.
Repository-Vertrag, Dependency-Check, reproduzierbares Release-ZIP und
Gitleaks 8.30.1 sind erfolgreich. Der vollständige öffentliche Dateibestand
wurde ohne private lokale Captures auf Geheimnisse geprüft.

Auch unter Linux bestanden **804 Tests** mit **94 % Abdeckung**. Die offiziellen
HACS-/Hassfest-Prüfungen und Gitleaks sind im
[Release-CI-Lauf](https://github.com/passion-wave/HA_aqara_fp2/actions/runs/36348723833)
erfolgreich. Das veröffentlichte ZIP wurde erneut heruntergeladen und stimmt
bytegenau mit dem lokal geprüften Paket überein (SHA-256:
`f6b94412a8bfd8525ac93f1a6b8c3b9608ab9b4b2365e97d52e900393e9e35b7`).

Testumgebung: **Home Assistant 2026.9.3**, **Python 3.14.6**,
`pytest-homeassistant-custom-component==0.13.366`, `aiohttp==3.14.3`,
`cryptography==48.0.1`. GitHub Actions prüft zusätzlich unter Linux/Python 3.14.

| Prüfgruppe | Inhalt |
|---|---|
| Parser und Qualität | Gerätezuordnung, Unicode, große IDs, null/fehlende Werte, doppelte Schlüssel, Traitkonflikte, Grenzen, Quellenzeit und Zukunftsanomalien |
| Signierung und Transport | Exakte Bytes, RSA-Passwortaufbereitung, HTTP-Fehler vor Bodycodes, TLS, feste Hosts, Redirect-/Proxy-Schutz, Timeout, Cancellation, begrenzte Dekompression |
| Sitzungslebenszyklus | Gespeicherte Sitzung, belegter Ablauf, gemeinsamer Login, gleiche Kontoidentität, vollständige Geräteprüfung, dauerhafte Übernahme erst nach erfolgreicher Speicherung |
| Fehler und Pausen | HTTP 429/503, Retry-After, monotone Kontolimits, keine Login-Schleifen bei unbekannten Codes, begrenzte Wiederverwendung gepufferter Antworten |
| Secrets und Dateien | Echte temporäre Dateien, Erhalt fremder Einträge/Kommentare, atomare Schreibvorgänge, Dateirechte, Parallelität, Syntax-/Größenlimits, Symlink-/Hardlink-Ablehnung, Neustart |
| HA-Assistent | Einwilligung, lokale Eingabe oder Secret-Referenzen, Fortschritt, Geräteauswahl, Abbruch, Speicherfehler, Duplicate Account, Reauth und Reconfigure |
| HA-Laufzeit | Setup/Unload/Reload, Migration alter Token-Einträge, gemeinsame Abrufe, Entitätskennungen, Verfügbarkeit, unabhängiger Empfangstimer, Repairs und Diagnose |
| Durchgehender Ablauf | Echter HA-Flow → RSA/Transport/Parser mit simuliertem HTTP → echte Secret-/Sessiondateien → HA-Plattformen und Zusatzentitäten → Tokenablauf → Neuanmeldung → Neustart mit neuem Token |
| Datenschutz | Keine synthetischen Credentials in DEBUG-Logs, Repr, Fehlern, Config Entries oder Diagnoseexporten; feste Feldauswahl statt Rohantworten |
| Distribution | Ruff, Mypy, Dependency-Check, Übersetzungsvertrag, reproduzierbares Runtime-ZIP, Gitleaks sowie offizielle Hassfest-/HACS-Prüfung |

Der vollständige Ablauf ersetzt ausschließlich die HTTP-Antworten und die
Warteuhr. Passwortverschlüsselung, Signierung, Parser, HA-Assistent und private
Dateispeicherung laufen zusammen. Einzeltests prüfen zusätzlich Fehlerwege und
die echten HA-Entitätsplattformen. Es werden keine persönlichen Zugangsdaten
in Tests oder CI verwendet.

## Bisherige Live-Beobachtungen

| Gate | Status |
|---|---|
| G0 – Offline-Vertrag | Automatisiert geprüft |
| G1 – eigener Original-Capture | **Bestanden am 27.09.2026**; exakter lokaler Signaturvergleich |
| G2 – eigener EU-Trait-Endpunkt | **Bestanden am 27.09.2026** im regulären Integrationsbetrieb mit zwei FP2; vier frühere Capture-Proben waren abgelehnt |
| G3 – App/Proxy unabhängig, Subscription und Frische | **Offen** |
| G4 – Präsenzsemantik | **Offen**; qlink-Rohcodes ungemappt, zusätzliche Zonenwerte nur laut Quelle bezeichnet |
| G5 – echte Sitzungserneuerung / Login | Login bestätigt; echte Ablauf-/Erneuerungsprüfung weiterhin **offen** |
| G6 – 24 Stunden, Neustart und Ausfall am Nutzerkonto | **Nicht durchgeführt** |

G1 ergab `matched` für `sleepradar_eu_candidate_v1`, Profilversion 1.
Der lokale HAR enthält zwei Geräte; die gespeicherte Antwort besteht den
Parservertrag. Der Request war bereits älter als einen Tag. Die tatsächlichen
Capture-Bytes, Zugangsdaten und Rohantworten bleiben ausschließlich lokal.

Am 27.09.2026 wurden vor dieser Anmeldeimplementierung insgesamt vier autorisierte
G2-Leseproben durchgeführt. Die erste lieferte einen damals nur allgemein
angezeigten Anwendungsfehler. Die drei folgenden lieferten HTTP 200 und Code 108,
auch mit den exakt beobachteten zusätzlichen App-Kontextheadern. Die vierte
Antwort bestätigte ausdrücklich `Token has expired`; nur das Vergleichsergebnis
wurde ausgegeben. Diese direkte Beobachtung begründet die Ablaufzuordnung für
den privaten EU-Trait-Endpunkt, nicht für beliebige Aqara-APIs.

## Regulärer Betrieb am eigenen Konto

Am 27.09.2026 wurde Version 0.2.0b1 über HACS installiert und Home Assistant
neu gestartet. Die Anmeldung erfolgte durch den Nutzer direkt im HA-Assistenten.
Anschließend war der Konfigurationseintrag geladen, die Kontoverbindung bereit,
und beide ausgewählten FP2 lieferten gültige qlink-Antworten. Die Beobachtung
enthielt 31 angeforderte Pfade pro Gerät und jeweils sechs nicht zurückgegebene
Pfade. Die gemeldete Helligkeit betrug zum Kontrollzeitpunkt bei beiden Geräten
0 lx; dieser Wert ist keine unabhängige physische Messprüfung.

Damit sind Anmeldung und regulärer Gerätezugriff bestätigt. Ein separater
Test mit gezielter Wertänderung, ein realer Tokenablauf sowie 24 Stunden Betrieb
wurden dadurch nicht ersetzt. Capture-Bytes, Gerätekennungen, Zugangsdaten und
Rohantworten bleiben ausschließlich lokal.

## Zusätzliche Ressourcen in 0.3.0b1

Die neuen Abfragen verwenden 81 Statusattribute und sieben Einstellungen aus
fixierten MIT-lizenzierten Quellen. Automatisierte Tests prüfen unter anderem
Gerätebindung, Antwortvarianten, Typgrenzen, Duplikatkonflikte, getrennte
Abfragegruppen, optionale Entitäten, Moduswechsel, Empfangsfristen, gemeinsame
Rate-Limits, Entladen und das Vermeiden zusätzlicher Login-Schleifen.

Die Freigabe bleibt experimentell. Ein erfolgreiches Lesen der Ressourcen
bestätigt nur die tatsächlich erhaltenen Felder des jeweiligen Geräts.
Koordinaten, Schlafberichte und unbekannte Rohcodes werden nicht hinzugedichtet.
Aktueller Umfang: [Datenkatalog](DATEN.md).


### Live-Abnahme der Zusatzabfragen

Version **0.3.0b1** wurde am 27.09.2026 über HACS installiert und nach dem
regulären HA-Neustart anhand der laufenden Integrationsdiagnose bestätigt.
Die bestehende Sitzung wurde weiterverwendet; eine erneute Eingabe von
Zugangsdaten war nicht erforderlich.

| Beobachtung | Ergebnis |
|---|---|
| Konfiguration und bestehende Verbindung | Geladen, `ready`, kein veralteter Transportstatus |
| Regulärer Trait-Abruf nach Neustart | Erfolgreich; keine fehlgeschlagene Abfrage zum Kontrollzeitpunkt |
| Gerät A: Statusressourcen | 42 gültige Werte, 39 fehlende Felder |
| Gerät A: Einstellungen | Alle sieben Werte geliefert |
| Gerät B: Statusressourcen | 41 gültige Werte, 40 fehlende Felder |
| Gerät B: Einstellungen | Alle sieben Werte geliefert |
| Zusatzabfragen insgesamt | Vier erfolgreich, keine Fehler oder Parserkonflikte, Status `ready` |
| Darstellung in HA | 18 zusätzliche aktive Entitäten; optionale Zonen und Einstellungen separat deaktiviert |

Die Moduszuordnung wurde anhand der HA-Zustände und numerischen Rohcodes
geprüft. Schlafentitäten erschienen nur im passenden Modus; ein unbekannter
Montagecode blieb unbekannt.

Diese Abnahme bestätigt beide zusätzlichen Endpunkte und die Gerätezuordnung
für die tatsächlich gelieferten Felder. Sie ist keine Prüfung der fehlenden
Felder in anderen Modi, kein Vergleich mit unabhängig beobachteten Personen
und kein 24-Stunden-Test. Persönliche Gerätekennungen, Messwerte und private
Sitzungsdaten werden in diesem öffentlichen Bericht nicht veröffentlicht.
