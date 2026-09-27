# Validierungsbericht

**Stand: 27.09.2026 · Integrationsversion: 0.2.0b1 · Anmelde-Beta**

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

Lokaler Abschlusslauf: **583 Tests bestanden**, keine fehlgeschlagenen oder
übersprungenen Tests, **93 % Coverage.py-Abdeckung einschließlich Verzweigungen**.
Ruff bestätigt 68 Python-Dateien; Mypy prüft alle 27 Integrationsmodule.
Repository-Vertrag, Dependency-Check, reproduzierbares Release-ZIP und
Gitleaks 8.30.1 sind erfolgreich. Der vollständige öffentliche Dateibestand
wurde ohne private lokale Captures auf Geheimnisse geprüft.

Die zusätzlichen Ergebnisse unter Linux sowie die offiziellen HACS- und
Hassfest-Prüfungen stehen in der
[GitHub-CI](https://github.com/passion-wave/HA_aqara_fp2/actions/workflows/ci.yml).

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
| Durchgehender Ablauf | Echter HA-Flow → RSA/Transport/Parser mit simuliertem HTTP → echte Secret-/Sessiondateien → Setup → Tokenablauf → Neuanmeldung → Neustart mit neuem Token |
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
| G2 – eigener EU-Trait-Endpunkt | **Nicht bestanden**; vier frühere autorisierte Proben mit inzwischen abgelehnter Sitzung |
| G3 – App/Proxy unabhängig, Subscription und Frische | **Offen** |
| G4 – Präsenzsemantik | **Offen**, kein Cloud-Occupancy-Sensor |
| G5 – echte Sitzungserneuerung / Login | **Offen**, Softwareablauf automatisiert geprüft |
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

Es gab in diesem Implementierungsschritt **keine echte Kontoanmeldung und keine
weiteren Aqara-Anfragen**. Wiederholung mit dem alten Token kann die Sitzung
nicht erneuern. Version 0.2.0b1 stellt dafür den bewusst gestarteten Loginweg
bereit. Die früheren lokalen Headerexperimente sind kein produktives Profil.

## Freigabe und nächste Abnahme

Freigegeben ist die **experimentelle Anmelde-Beta** mit lokaler
Zugangsdatenverwaltung, Sitzungserneuerung, Einrichtung, Entitäten und Diagnose.
Der Nutzerauftrag erlaubt diesen experimentellen Betrieb vor Abschluss der
Langzeitnachweise; deren Evidenzstatus bleibt offen. Der zuvor ausschließlich
statische Vorschauweg ist nicht mehr die einzige Einrichtungsoption.

Die reale Anmeldung am Nutzerkonto wird erst nach Fertigstellung und Rückfrage
gestartet. Anschließend sind Gerätezugriff, unabhängig veränderte Messwerte,
Subscription-Verhalten, Sitzungserneuerung und Dauerbetrieb zu prüfen.
Präsenzsemantik, Personenposition/-anzahl und Schlafdaten werden nicht aus den
vorliegenden Rohcodes abgeleitet.

Am laufenden Home Assistant des Nutzers wurden keine Änderungen vorgenommen.
Der erwartete Konfigurationsmount war nicht verfügbar; seine tatsächliche
HA-Version ist noch nicht bestätigt. Die oben genannte Version ist die getestete
Entwicklungsbasis.
