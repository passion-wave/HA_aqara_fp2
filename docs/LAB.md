# Lokales Labor

Die Werkzeuge verwenden denselben API-Kern wie die HA-Integration. Sie laufen
aus dem Repository mit der [Entwicklungsumgebung](../CONTRIBUTING.md).
Kein Kommando übernimmt automatisch eine Produktionsfreigabe.

## Offline-Datenvertrag

```bash
.venv/bin/python scripts/lab.py offline fixtures/trait_read.response.json
```

Das liest ausschließlich eine lokale Datei und gibt einen begrenzten Bericht aus.
Die Fixture enthält zwei pseudonymisierte Geräte und historische Werte vom
25.09.2026. Sie ist kein byteidentischer Original-Capture und kann keinen echten
Signaturvergleich bestehen. Der separate Signatur-Testvektor ist synthetisch.

## Einmaliger lokaler Import

Bevorzugtes Austauschformat ist ein kleines JSON-Paket mit Base64-kodierten
Original-Body-Bytes und den notwendigen Request-Headern. Es enthält Geheimnisse
und darf nur lokal gespeichert werden. `scripts/lab.py import` erstellt die
Ausgabedatei mit Modus `0600`, überschreibt keine vorhandene Datei und zeigt nur
eine bereinigte Vorschau.

```bash
mkdir -m 700 private
.venv/bin/python scripts/lab.py import har private/read.har --output private/session.json
```

Bei mehreren passenden HAR-Einträgen ist zusätzlich `--entry-index N` notwendig
(nullbasierter Index in `log.entries`). Es wird ausschließlich der exakte
HTTPS-EU-Trait-Endpunkt akzeptiert. Andere Domains, Login-Antworten und fremde
Header werden nicht übernommen. `postData.text` wird nicht neu serialisiert;
eine HAR-Textdarstellung ist trotzdem keine Garantie für Originalbytes.

Proxyman kann bei JSON zusätzlich `params` exportieren. Der Import akzeptiert
dort eine leere Liste oder einen einzelnen Eintrag, dessen `name` exakt dem
Bodytext entspricht und dessen `value` leer ist. Dafür muss der MIME-Typ
`application/json` sein. Abweichende Parameter werden abgelehnt; zur Signierung
wird ausschließlich der unveränderte Bodytext verwendet. Diese Unterstützung
ist seit dem Entwicklungsstand nach 0.1.0b1 enthalten.

Alternativ kann `import curl` eine gespeicherte **Textdatei** mit einem einfachen
POSIX-cURL-Export lesen. Sie wird nie als Shellkommando ausgeführt. Nur URL,
POST-Methode, eindeutige Header und ein direkter Body sind zulässig. Dateiimporte
mit `@`, Pipes, Umleitungen, Variablen, Command-Substitutionen und unbekannte Flags
werden abgelehnt. Für PowerShell-/Windows-Quoting ein strukturiertes Paket nutzen.

## G1: Signatur lokal vergleichen

```bash
.venv/bin/python scripts/lab.py signature private/session.json
```

Kein Netzwerkaufruf. Die Ausgabe enthält `matched` oder `not_matched` und die
Profilversion. Token, Signaturbasis, User-ID und Body erscheinen nicht im Bericht.
Ein erfolgreicher Vergleich beweist nur die Kandidatenberechnung zum importierten
Request. Die persönliche Sitzung bleibt auf diesem Rechner.

## G2: Eine bewusst autorisierte Leseprobe

Erst nach G1 und nach Lesen des [Live-Validierungsplans](IMPLEMENTIERUNG.md#6-live-validierungsplan-klare-gates-statt-bauchgefühl):

```bash
.venv/bin/python scripts/lab.py probe private/session.json --allow-live
```

`--allow-live` autorisiert genau diesen Aufruf. Ohne den Schalter erfolgt kein
Request. G1 wird nochmals über die Originalbytes geprüft. Der Request erhält
frische Zeit, Nonce und Signatur; Body-Auswahl und `needSubscribe=true` bleiben
erhalten. Dieses Flag kann unbekannte sitzungsbezogene Nebenwirkungen haben.
Es werden keine Geräteeinstellungen verändert.

Das Labor speichert unter `private/probe-budget.json` einen gesperrten lokalen
Zähler: höchstens zehn Versuche je Untersuchungsschritt, mindestens 30 Sekunden
Abstand pro Konto. Serverpausen werden berücksichtigt. Den Budgetstand nicht
löschen oder wechseln, um die Begrenzung zu umgehen. Bei wiederholter Ablehnung
die Untersuchung beenden und das Profil prüfen.

## G3 und weitere Nachweise

Für einen späteren, kontrollierten Vergleich kann `--step G3` verwendet werden.
App schließen und Proxy aus dem Datenpfad entfernen; tatsächliche Änderungen
unabhängig beobachten. Der Bericht dokumentiert ausschließlich das Ergebnis
dieses Requests. Er beweist weder die Schritte des Versuchsaufbaus noch frische
Messwerte, Kontoidentität, Login, Präsenzsemantik oder 24 Stunden Stabilität.

`needSubscribe=false` ist in diesem Release noch keine freigegebene Importvariante.
Der dafür notwendige Vergleich erfordert eine gesonderte Erweiterung des
Protokollprofils mit Vertragstest. Es gibt keinen generischen Endpoint-Caller.

Kein Capturing, Login oder Liveaufruf gehört in öffentliche GitHub Actions.
Für Support nur bereinigte Berichte verwenden, niemals `private/session.json`.
