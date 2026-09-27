# Protokollquelle und lokales Labor

Der implementierte Kandidat wurde am 26.09.2026 erneut anhand des [festen SleepRadar-Quellstands](https://github.com/florianhorner/ha-fp2-sleep/blob/3af017fc995d5f05e65720ae5b1ed0690a04504c/aqara_fp2_sleep/aqara_fp2_sleep_poller.py) geprüft. Der Git-Blob ist unverändert `b48a4417deebd04cf4e6b3eb3d918300e6081d25`. Der gleiche Commit enthält eine MIT-Lizenz, Copyright 2026 Florian Horner; [Lizenzkopie](licenses/SleepRadar-MIT.txt) und [Hinweise](../THIRD_PARTY_NOTICES.md) liegen im Projekt.

Die eigene Implementierung übernimmt den beschriebenen Signaturaufbau, Loginvertrag und die beiden öffentlichen Herstellerkonstanten. Sie übernimmt keinen Poller-Code und keine unbelegten Fehlercode-Vermutungen. Die Quelle benutzt `/app/v1.0/lumi/res/query`. Am 27.09.2026 wurden die eigene Anmeldung und der erfolgreiche Geräteabruf über `/app/v1.0/lumi/app/qlink/trait/read` mit zwei FP2 am EU-Konto bestätigt. MFA und echte Sitzungserneuerung bleiben separat zu prüfen. `cryptography==48.0.1` führt die RSA-PKCS1v15-Passwortverschlüsselung aus; ein gespeicherter Passwort-Hash wird nicht als Ersatzgeheimnis veröffentlicht.

Ab 0.2.0b1 nutzt der bewusst aktivierte Anmeldeweg die belegten Loginheader:
`Sys-Type: 1`, `Lang: en`, `User-Agent: pyAqara/1.0.0`, `App-Version: 3.0.0`
und eine frische Phone-ID nach dem Quellenvertrag. Neu erzeugte Loginsitzungen
behalten den Systemtyp bei Folgeabrufen. Dieser Kontext ist getrennt vom
iOS-Systemtyp `0` des historischen HAR. Passwörter werden über Secret-Referenzen
geladen; der neue Kontoclient übernimmt Wiederanmeldung und atomare
Sitzungsspeicherung nach Konto- und Geräteprüfung.

## Ressourcenquelle ab 0.3.0b1

Der zusätzliche Katalog ist gegen den fixierten Commit
[`ca46546673d52ab819b3da5be7d98d4bb33f854a`](https://github.com/Serein-Zhang/ha-aqara-devices-V3-Fork/tree/ca46546673d52ab819b3da5be7d98d4bb33f854a)
von `Serein-Zhang/ha-aqara-devices-V3-Fork` geprüft. `const.py` definiert die
81 Statusattribute und sieben Einstellungs-IDs; `api.py` beschreibt die lesenden
Endpunkte und die begrenzten Antwortformen; `fp2.py` liefert die genannten
Einheiten und Enum-Zuordnungen. Die [MIT-Lizenz](licenses/AqaraDevices-MIT.txt)
liegt auch im Runtime-Paket; alle Blob-IDs stehen in den
[Third-party notices](../THIRD_PARTY_NOTICES.md).

- Status: `/app/v1.0/lumi/res/query`
- Einstellungen: `/app/v1.0/lumi/res/query/by/resourceId`
- Jeweils ein `subjectId` pro Aufruf und eine gemeinsame `options`-Liste;
  keine unbelegte Mehrgeräte-Bündelung.
- Header und Signatur folgen dem bestehenden Kontoprofil. Die qlink-spezifische
  Ablaufzuordnung wird nicht auf neue Endpunkte übertragen.
- Keine Aufrufe von Schreib-, Historien- oder Steuerungsendpunkten.
- Keine Nullersatzwerte aus dem Quellprojekt: fehlend, null und ungültig bleiben
  getrennt. Fremde Geräte und widersprüchliche Antworten werden isoliert.
- Quellenzeitstempel bleiben ohne gesicherten Einheitenvertrag uninterpretiert.
  Physische Aktualität bleibt `unverified`.

Die neue Enum-Quelle belegt die Darstellung gemeldeter Ressourcen, keine eigene
physische Prüfung. Insbesondere bleibt das qlink-Präsenzmapping unverändert
ungeklärt. Umfang, Modusabhängigkeit und bewusst nicht erschlossene Felder sind
im [Datenkatalog](DATEN.md) beschrieben.

## Befehle

Aus dem Repository mit der eingerichteten Entwicklungsumgebung:

```sh
python scripts/lab.py offline fixtures/trait_read.response.json
python scripts/lab.py import har private/export.har --output private/session.json
python scripts/lab.py signature private/session.json
```

`import har` akzeptiert genau einen passenden EU-Read-Entry; bei mehreren muss `--entry-index N` den Originalindex im HAR auswählen. Fremde Domains werden verworfen. cURL kann mit `import curl` als eingeschränkter POSIX-Text eingelesen werden; die Zeichenfolge wird nie ausgeführt. Übliche Fortsetzungen mit Backslash und LF werden als POSIX-Befehlssyntax außerhalb einfacher Anführungszeichen dekodiert. Einfach gequotete Bodybytes einschließlich Zeilenumbrüchen bleiben unverändert; mehrdeutige oder ungültige Bodies werden nicht repariert. Shell-Erweiterungen, Umleitungen, externe Body-Dateien, Proxy-/TLS-/Redirect-Flags und mehrdeutige Header sind gesperrt. Ein vollständiges HAR kann andere Kontogeheimnisse enthalten und bleibt ausschließlich lokal. Für regelmäßige Verwendung ist das minimale strukturierte Paket vorzuziehen.

Das erzeugte Paket enthält nur den erlaubten Request, minimal erforderliche Header und `body_base64` mit unveränderten UTF-8-Bytes. Es enthält Geheimnisse und wird exklusiv mit Dateirechten `0600` angelegt. Kein Überschreiben vorhandener Dateien. `wire_exact` ist nur eine Herkunftsangabe und schaltet nichts frei; HAR-Text und cURL behaupten keine Bytetreue. G1 berechnet die Signatur erneut und vergleicht konstantzeitlich. Der öffentliche Bericht enthält ausschließlich Status und Profilversion. Niemals Paket oder Capture in Git, Issues oder Chat kopieren.

## Bewusste Einzelprobe

Erst bei lokal erfolgreichem G1 und einem frischen eigenen Export:

```sh
python scripts/lab.py probe private/session.json --allow-live
```

Dieser konkrete Befehl autorisiert genau einen HTTPS-Request. Ohne `--allow-live` bleibt er offline. Vor jedem Request wird G1 über dieselben lokalen Capture-Bytes erneut berechnet. Der Client sendet die unveränderten Body-Bytes mit neuem Nonce, neuer Zeit und neuer Signatur. `needSubscribe=true` bleibt wie beobachtet erhalten; es kann sitzungsbezogene Nebenwirkungen haben. Es gibt keine Wiederholung, keinen Login und keinen Hintergrundpoller. Nur die angegebenen Geräte werden verarbeitet.

Das lokale, mit Dateisperre geschützte Journal `private/probe-budget.json` zählt auch fehlgeschlagene Versuche: höchstens zehn pro Konto und Untersuchungsschritt, mindestens 30 Sekunden Abstand. `Retry-After`, Netzwerk- und Serverfehler verlängern die Pause auch über CLI-Neustarts hinweg. Das Journal enthält keine Tokens. Nach Schließen von App und Proxy kann `--step G3` den zweiten dokumentierten Untersuchungsschritt kennzeichnen. Ein G3-HTTP-Erfolg allein beweist weder Frische noch Präsenzsemantik. Keine beliebigen Host-/Endpunkt-Optionen, keine automatischen Regionswechsel.

Die Ausgabe enthält Schemaerfolg, Geräteanzahl und ausdrückliche Hinweise auf unbestätigte Identität/Aktualität. Ein Laborbericht schaltet die HA-Einrichtung nicht automatisch um. Der neue Anmeldeweg wird separat bewusst aktiviert. G3, G4 (Präsenz), G5 (Reauth), G6 (24 Stunden und Neustart) sowie Subscription-Verhalten bleiben eigenständige Nachweise; die Nutzerzustimmung behauptet keine Produktionsvalidierung.

## Transport und Tests

Alle Standardtests blockieren Netzwerk-Sockets. Getestet werden exakte gesendete Bytes, TLS-/Host-/Redirect-Regeln, Cancellation, Streamlimits einschließlich gzip-Bombe, Rate-Limits, unbekannte 401/403-Antworten, strikte Importe, Einwilligung und Single-Flight-Reauth. Ein HTTP-Erfolg oder synthetischer Signaturvektor zählt niemals als Gerätetest. Am 27.09.2026 bestand der erste echte lokale G1-Vergleich. Vier anschließend autorisierte G2-Proben blieben erfolglos; die letzte bestätigte am privaten Endpunkt Code 108 mit `msgDetails = "Token has expired"`. Der inzwischen erfolgreiche reguläre Loginweg erzeugt eine neue geprüfte Sitzung. Das frühere Laborjournal bleibt mit vier Versuchen unverändert; der autorisierte Integrationsbetrieb ist ein eigener Ablauf. Details stehen im [Validierungsbericht](VALIDIERUNG.md).
