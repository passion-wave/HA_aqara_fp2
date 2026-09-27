# Validierungsbericht

**Stand: 27.09.2026 · Integrationsversion: 0.1.0b1 · Labor-Beta**

## Tatsächliche Testbasis

Die Ausgangsdatei `Aqara_Presence_Lab_Implementierung.md` wurde vollständig gelesen
und unverändert als [IMPLEMENTIERUNG.md](IMPLEMENTIERUNG.md) übernommen.
Ein separates Starterprogramm oder ZIP lag im Arbeitsverzeichnis nicht vor.
Die vier JSON-Fixtures wurden daher direkt aus Anhang A extrahiert, als JSON
validiert und anschließend mit dem neu implementierten gemeinsamen Kern geprüft.

- Request: 31 und 37 Trait-Einträge, Antwort: 20 und 25 Einträge.
- Zuordnung über Geräte-ID trotz umgekehrter Reihenfolge.
- Helligkeit: **9 und 110 lx**, unverändert und ohne Rundung nach `step`.
- Synthetischer Signaturvektor stimmt mit der dokumentierten Formel überein.
- Fixture-Provenienz bleibt `wire_exact=false`, `live_validated=false`.

## Automatisierte Prüfung

Lokaler Abschlusslauf: **321 Tests bestanden**, **93 % Coverage.py-Abdeckung
einschließlich Verzweigungen**, keine fehlgeschlagenen oder übersprungenen Tests.
Mypy prüft alle 24 Integrationsmodule; Ruff bestätigt 59 formatierte Python-Dateien.
Der reproduzierbare ZIP-Build und Gitleaks 8.30.1 sind ebenfalls erfolgreich.

Testumgebung: **Home Assistant 2026.9.3**, **Python 3.14.6**,
`pytest-homeassistant-custom-component==0.13.366`, `aiohttp==3.14.3`,
`cryptography==48.0.1`. Lokal macOS/Python 3.14.6;
GitHub Actions prüft zusätzlich auf Linux/Python 3.14.7.
Die verbindlichen Ausführungsergebnisse stehen in der
[CI dieses Repositorys](https://github.com/passion-wave/HA_aqara_fp2/actions/workflows/ci.yml).

| Prüfgruppe | Inhalt |
|---|---|
| Parser | Fixture, Reihenfolge, Unicode, große IDs, Typen, Defaults, null, ungültige Zahlen und Zeiten |
| Strenge Eingabe | Doppelte JSON-Schlüssel, Traitkonflikte, Limits, abgeschnittene Daten, isolierte Gerätefehler |
| Signierung | Synthetischer Vektor, optionale Tokens, exakte Bytes, Unicode und Whitespace, sichere Fehler |
| Transport | HTTP-Fehler vor JSON-Erfolg, Timeout, TLS, Redirects, Host/Proxy-Schutz, Cancellation |
| Größenlimits | Tatsächlich gelesener Stream, gzip-Dekompression und komprimierte Größenbombe |
| Import | HAR-Auswahl, minimale Pakete, konservatives cURL-Parsing ohne Ausführung, Dateirechte |
| Auth | Simulierter Loginvertrag, lokale RSA-Rundreise, Einwilligung, Kontomismatch, Single-Flight |
| Rate-Limits | Monotone Cooldowns, Backoff/Jitter, Retry-After in Sekunden und als Datum, Probejournal |
| Qualität | Ungeklärte Quellenzeit, bestätigte Semantik als Testfall, Zukunftszeit, fehlende Werte |
| HA-Einrichtung | Offline ohne Entry/Entitäten, Live-Gate, simulierte Geräteauswahl, Duplicate Account, Reauth, Reconfigure |
| HA-Laufzeit | Batching, Refresh, unabhängiger Empfangstimer, Verfügbarkeit, Setup/Unload/Reload, Schema |
| Entitäten | Stabile Kennungen, korrekte Einheiten, Rohcodes, keine Fantasie-Capabilities, HomeKit unverändert |
| Datenschutz | Keine Test-Secrets in Repr, Fehlern oder Diagnose-Allowlist |
| Paket | Deterministisches ZIP, kompilierbare Runtime-Dateien, Übersetzungsabdeckung, vollständiger Katalog |

Alle Standardtests blockieren Netzwerk-Sockets. Kein Test verwendet persönliche
Zugangsdaten. Testdoubles umgehen Gates ausschließlich innerhalb der Tests, um
noch nicht live freigegebene Laufzeitpfade zu prüfen.

Zusätzliche Prüfungen: Ruff-Lint und Formatierung, Mypy für die komplette
Integration, `pip check`, Repository-Vertrag, Gitleaks-Secret-Scan und die
offiziellen Hassfest-/HACS-Actions. Die Gitleaks-Ausnahme betrifft ausschließlich
die eine verifizierte öffentliche Herstellerkonstante im festgelegten Quelldateipfad.

Hassfest und der Secret-Scan wurden auch auf GitHub erfolgreich ausgeführt.
Auch `hacs.json` und `manifest.json` bestehen die **unveränderten offiziellen
HACS-Schemas** aus Commit `adb7d83e33d24325535fb43b8226572405143757` von
[`hacs/integration`](https://github.com/hacs/integration/blob/adb7d83e33d24325535fb43b8226572405143757/custom_components/hacs/utils/validate.py).
Der bereinigte Schema-Prüfbericht ist dem Beta-Release beigefügt. Der
[finale GitHub-CI-Lauf](https://github.com/passion-wave/HA_aqara_fp2/actions/runs/36266205069)
bestätigt alle 321 Tests, Hassfest, Linting, Typprüfung und Secret-Scan.
Nach der Öffentlichschaltung am 27.09.2026 besteht auch die
[offizielle HACS-Remoteprüfung](https://github.com/passion-wave/HA_aqara_fp2/actions/runs/36302490172).
Die frühere Sperre aufgrund privater Repository-Sichtbarkeit ist damit aufgehoben.
Die Aqara-Live-Gates bleiben unabhängig davon offen. Im ersten GitHub-Lauf waren alle
306 Tests erfolgreich, der zusätzliche Artifact-Upload scheiterte jedoch am
kontoweiten GitHub-Speicherlimit. Dieser optionale Upload beeinflusst deshalb
künftig nicht den Teststatus; Coverage bleibt in Logs und Run Summary erhalten.
Das Release-ZIP wird separat an das GitHub-Release angehängt.

## Live-Abnahme

| Gate | Status |
|---|---|
| G0 – Offline-Vertrag | Automatisiert geprüft |
| G1 – eigener Original-Capture | **Offen**; Werkzeug vorhanden |
| G2 – eigener EU-Trait-Endpunkt | **Offen**; bewusste Einzelprobe vorhanden |
| G3 – App/Proxy unabhängig, Subscription und Frische | **Offen** |
| G4 – Präsenzsemantik | **Offen**, kein Cloud-Occupancy-Sensor |
| G5 – echte Sitzungserneuerung / Login | **Offen** |
| G6 – 24 Stunden, Neustart und Ausfall | **Nicht durchgeführt** |

Es wurden **keine Aqara-Liveaufrufe** und keine Änderungen an einem laufenden
Home Assistant oder an Aqara-Geräten vorgenommen. Der erwartete lokale
HA-Konfigurationsmount war nicht verfügbar. Die tatsächlich verwendete
HA-Version des Nutzers ist daher nicht bestätigt; die genannte Version ist die
getestete Entwicklungsbasis.

## Freigabeentscheidung und verbleibende Arbeit

Freigegeben ist die **installierbare Labor-Beta mit Offline-Vorschau und lokalen
Prüfwerkzeugen**. Nicht freigegeben sind produktives Cloud-Polling, automatische
Anmeldung, semantische Präsenz, Personenpositionen/-anzahl und Schlafdaten.

Der produktive Gate ist im ausgelieferten Profil technisch geschlossen. Es gibt
keinen Benutzer-Schalter zur Umgehung. Selbst ein erfolgreicher Trait-Read beweist
noch keine Bindung des eingegebenen `Userid` an das Token. Vor Live-Einrichtung
muss deshalb ein belegter Identitätsadapter samt Konto-/Geräteprüfung ergänzt
und getestet werden. Ebenso benötigt `needSubscribe=false` einen eigenen
Profilvertrag und Vergleichstest. Die aktuelle Laborprobe erhält `true` wie im
Capture. Eine Profiländerung ohne Nachweis ist keine Freigabe.

Diese Einschränkungen entsprechen ausdrücklich der gelieferten Spezifikation.
Sie sind keine durch Mock-Tests erledigten Arbeitspakete. Der nächste Schritt ist
G1 lokal mit einem frischen eigenen Export; Geheimnisse bleiben auf dem Rechner.
