# Cloud-Push: Quellen, Offline-Nachweis und Integrationsplan

Recherche vom **28. September 2026**. Ergebnis: **OpenAPI → RocketMQ → lokale
SSE-Bridge ist konkret belegbar**. Ein unmittelbar mit dem vorhandenen privaten
App-Login nutzbarer Pushkanal ist bisher nicht belegt. Hier wurde kein Aqara-Konto
abgefragt, kein Broker verbunden und keine Subscription eingerichtet. Die
Integration bleibt bis zur getrennten Umsetzung bei ihrem Polling.

## Welche Schnittstelle tatsächlich verfügbar ist

| Weg | Beleg | Voraussetzung / Grenze |
| --- | --- | --- |
| OpenAPI-RocketMQ | Offizieller Vertrag und unabhängige FP2-Implementierungen | Developer-Projekt, Schlüssel und separate Kontoautorisierung; sinnvollster konkret umsetzbarer Cloud-Push-Kandidat |
| OpenAPI-HTTP-Push | Offiziell dokumentiert | Erreichbarer Callback, geprüfte Signaturen, Replay-Schutz und zuverlässige Antworten; zusätzliche externe Erreichbarkeit nötig |
| AIOT-v4-MQTT | In offizieller Einführung genannt | Der veröffentlichte Vertrag enthält noch keine Subscription-Operation; derzeit keine implementierbare Verbindungsspezifikation |
| Aqara-Studio-WebSocket/MQTT | Offizielle lokale Studio-API | Zugängliche Studio-Instanz samt eigenem Token; kein Ersatz für den Aqara-Home-App-Login |
| Privates QLINK `needSubscribe: true` | Vorhandener Capture-/Lesepfad | Kein belegter Broker, Topic, WebSocket, Session-Handshake oder Nachrichtenvertrag |
| AMQP | In den geprüften Primärquellen kein passender Vertrag | RocketMQ ist nicht ohne Weiteres durch einen AMQP-Client ersetzbar |

Aqara unterscheidet selbst [Cloud API und Local API for Studio](https://docs.aqara.com/docs/aqara-developer/introduction/).
Der [Studio-WebSocket](https://docs.aqara.com/docs/aqara-developer/data-export-api/websocket-api/)
verwendet `/open/ws`, einen Studio-Token und ausgehende Heartbeats spätestens alle
30 Sekunden. Diese Angaben gelten nicht automatisch für `rpc-ger.aqara.com`.

### Neue AIOT-Dokumentation: konkreter offener Punkt

Die [AIOT-Einführung](https://docs.aqara.com/docs/aqara-developer/aiot-api/introduction/)
nennt MQTT für Statusänderungen. [Getting Started](https://docs.aqara.com/docs/aqara-developer/aiot-api/getting-started-with-the-aiot-api/)
beschreibt `{regionaler OpenAPI-Host}/v4.0/open/api` sowie Developer-`Appid`,
`Keyid`, `Nonce`, `Time`, `Sign` und gegebenenfalls autorisierten `Accesstoken`.
Es erwähnt außerdem Rückgaben von MQTT-Client-ID, Host, Port, Zugangsdaten und Ablauf.

Die Prüfung der [offiziellen OpenAPI-YAML am gepinnten Stand](https://github.com/aqara/aqara-developer-docs/blob/7db4de3b4bfcab4a42e1fc19b50a5d8eb05ec56d/openapi/aiot-api/en/aiot-api.yaml)
ergibt jedoch acht HTTP-Pfade und **null Subscription-Operationen**. `Subscription`
ist nur ein Tag. MQTT-Endpunkt, Topic, Transportverschlüsselung, QoS,
Erneuerung und Ereignisschema fehlen. Daher weder einen Pfad erraten noch private
App-Zugangsdaten an einen mutmaßlichen Broker senden. Sobald Aqara diesen Vertrag
veröffentlicht, ist ein direkter Python-MQTT-Adapter neu zu bewerten.

## RocketMQ: Einrichtung und belastbarer Umfang

Benötigt werden ein Developer-Projekt mit `Appid`, `Keyid`, privatem `Appkey`
und eine Autorisierung des Aqara-Home-Kontos in dessen Serverregion. Der reguläre
[Projektprozess](https://opendoc.aqara.com/en/docs/developmanual/manageApplication/manageProject.html)
beschreibt Prüfung/Freigabe und anschließende Schlüsselverwaltung. Etwaige
Demo-Projekt-Berechtigungen sind separat im tatsächlichen Projekt zu prüfen.

Die [Kontoautorisierung](https://opendoc.aqara.com/en/docs/developmanual/authManagement/aqaraauthMode.html)
erfolgt über OAuth oder `config.auth.getAuthCode` und `config.auth.getToken`:
Verifikationscode per E-Mail/SMS, zehn Minuten gültig; Antwort mit `openId`,
`accessToken`, `refreshToken`, `expiresIn`. Der Standardzugriff gilt sieben Tage;
die Schnittstelle erlaubt andere Laufzeiten. `config.auth.refreshToken` erneuert
die Tokens. Dieser Vertrag ist getrennt von unserer privaten Passwortanmeldung.
OpenAPI-Signaturen müssen nach dessen eigenen Regeln umgesetzt werden.

Die offiziellen [Push-Modi](https://opendoc.aqara.com/en/docs/developmanual/messagePush/messagePushMode.html)
belegen RocketMQ, zwölf Stunden serverseitige Nachrichtenaufbewahrung und drei
Empfangsmodi: alle Ressourcen, alle Traits oder ausgewählte Ressourcen. Bei
„All reception“ sind die entsprechenden individuellen Subscribe-Aufrufe
absichtlich gesperrt. Eine solche Ablehnung ist kein Anlass für Login-Schleifen.
Im Beispiel dienen `Appid` als Topic/Consumer-Gruppe und `Keyid`/`Appkey` als
ACL-Zugang. Die tatsächliche Nameserver-Adresse muss aus dem regionalen Projekt
kommen; die dokumentierte China-Adresse ist kein belegter EU-Standard.

Im gezielten Modus verwendet die [Resource-Subscribe-API](https://opendoc.aqara.com/en/docs/developmanual/messagePush/messagePushAPI.html)
`config.resource.subscribe` mit `data.resources`, `subjectId` und `resourceIds`.
Der [Nachrichtenvertrag](https://opendoc.aqara.com/en/docs/developmanual/messagePush/messagePushFormat.html)
liefert `resource_report`, `msgId`, `openId`, Zeit und einzelne Ressourcen mit
`subjectId`, `resourceId`, `statusCode`, `value`. Dokumentierte Push-Zeiten sind
Millisekunden; das beweist keine identische Zeiteinheit unserer privaten Pollingantworten.

### FP2-Felder: Quellbeleg ist noch kein Kontonachweis

Die aktuelle [Darkdragon14-FP2-Zuordnung](https://github.com/Darkdragon14/ha-aqara-devices/blob/00e964ad29b6cb0b4d5a1f11e22acec022e1a0a7/custom_components/ha_aqara_devices/fp2.py)
führt Puls `0.8.85`, Atmung `0.9.85`, Bewegung `13.11.85`, Schlafcode `13.106.85`,
Lux `0.4.85` und Betriebsmodus `14.49.85`. Sie trennt schnelle, mittlere und langsame
Pollinggruppen; daraus folgt keine garantierte Push-Frequenz.

Der [FHEM-Adapter](https://github.com/MrStrategy/FHEM-AqaraFP2/blob/2c1d99bb33a6382f0efd2b8e8967d169b529bf8a/fp2_state.py)
ergänzt folgende konkrete Ressourcenzuordnungen:

| Ressource | Im Adapter verarbeiteter Inhalt |
| --- | --- |
| `3.51.85`, `3.52.85` | Präsenz / Bettstatus |
| `4.22.700` | JSON-Zielliste mit `id`, `x`, `y`, `rangeId`, `state` |
| `3.1.85` … `3.30.85` | Zonenmeldungen |
| `13.120.85`, `13.121.85` … `13.150.85` | Gesamt-/Zonenstatistik |
| `0.60.85`, `0.61.85`, `0.121.85` … `0.127.85` | Zählwerte und zeitbezogene Statistik |

Der Adapter wertet `state == 1` als aktives Ziel und leitet Zonen als `rangeId + 1`
ab. Das ist Community-Semantik; Einheit, Achsenausrichtung und Ursprung der
Koordinaten sind damit nicht nachgewiesen. Er berechnet Personenzahlen aus
aktiven Zielen und unterstützt zusätzlich optionale Ressourcenabfragen.
Ein Parserzweig beweist nicht, dass alle Felder in jeder Region/Firmware und in
jedem FP2-Modus tatsächlich gepusht werden.

Für Schlaf-/Vitaldaten bleibt die bestehende Modusprüfung erforderlich. Die
[Herstellerbeschreibung](https://partnerships.aqara.com/products/presence-sensor-fp2-6)
nennt Einzelschlaf als Voraussetzung der Schlafüberwachung. Unveränderte oder
leere Bettwerte dürfen keine belegte Anwesenheit vortäuschen; Schlafcode `0..2`
wird weiterhin nicht zu Präsenz umgedeutet.

## Latenz, Wiederanlauf und Datenverlust

Die [RocketMQ-Bridge](https://github.com/Darkdragon14/aqara-rocketmq-bridge/blob/565413e4fdd425757f13ecbb68bb363eaab6fab0/README.md)
stellt `/health` und Bearer-geschütztes `/events` bereit. Sie benötigt einen
Container oder HAOS-Add-on; Java läuft außerhalb von Home Assistant. Standardmäßig
fasst sie lokale Ereignisse in 100-ms-Schritten zusammen. Das ist nur ihr
Weiterleitungsintervall, **keine FP2-Messrate und keine Ende-zu-Ende-Latenzzusage**.

Der [SSE-Controller](https://github.com/Darkdragon14/aqara-rocketmq-bridge/blob/565413e4fdd425757f13ecbb68bb363eaab6fab0/service/src/main/java/darkdragon/aqara/bridge/web/EventsController.java)
sendet beim Verbindungsaufbau einen Snapshot, danach Batches und Heartbeats.
Der [Broadcaster](https://github.com/Darkdragon14/aqara-rocketmq-bridge/blob/565413e4fdd425757f13ecbb68bb363eaab6fab0/service/src/main/java/darkdragon/aqara/bridge/stream/EventBroadcaster.java)
speichert jeweils den letzten Wert pro Geräteschlüssel/Ressource im RAM und
vergibt pro Prozess einen Cursor. Mehrere schnelle Änderungen können zusammenfallen.
Es gibt hier keinen vollständigen Ereignisverlauf oder garantierten
`Last-Event-ID`-Replay. Der Schutz gegen rückwärts laufende Quellzeiten ist im
geprüften Stand auf `spec_report` begrenzt; für `resource_report` muss unser
Adapter zusätzlich selbst prüfen. Snapshots dürfen alte Daten nicht als neu
gemessen markieren oder einmalige Ereignisse erneut auslösen.

Keine geprüfte Primärquelle liefert eine allgemeine FP2-Push-Latenzgarantie oder
eine für dieses Nutzerprojekt bestätigte Quote. Frequenz und Berechtigung sind
bei einem später autorisierten Test zu messen. Pro-Feld-Berichtsabstände,
Quellzeit, lokale Empfangszeit und HA-Veröffentlichung getrennt erfassen; monotone
Zeit für lokale Laufzeitmessung, UTC nur für Quellzeitvergleich.

## Bereits ausgeführter Offline-Nachweis

```sh
.venv314/bin/python scripts/push_probe.py --demo
.venv314/bin/pytest -q tests/test_push_probe.py
```

Der eigenständig geschriebene Prototyp validiert **bereits dekodierte**
`snapshot`-/`batch`-JSONs. Er implementiert weder SSE-Transport noch Cloud-Login.
Er prüft keine Broker-Authentizität oder Nachrichtensignatur.
Synthetische Tests prüfen Bindung an ausgewählte Geräte, FP2-Allowlist,
Duplikate, ältere Meldungen, widersprüchliche Werte, Cursor-Neustart,
Snapshot-Erhalt fehlender Felder, Koordinatenform, Größen-/Typgrenzen und
geheimnisfreie Ausgaben. Nur Metadaten werden ausgegeben. Ressourcenwerte bleiben
bis auf die Ziel-Listenform und Stringgrenzen uninterpretiert; das validiert keine
physiologische Messqualität oder Einheiten. `spec_report` wird bewusst als
ununterstützt gezählt, bis dessen separate Zuordnung getestet ist.

Lokale sanitiserte Replays können mit `--file` eingelesen werden. Dateiformat:
`{"selected_subjects":["synthetic-fp2"],"frames":[...]}`. Der Prozess hat keine
Netzwerkfunktion, keine Credential-Parameter und bestätigt niemals `live_verified`.
Die Tests laufen mit blockierten Netzwerksockets. Reale Aufzeichnungen gehören
nicht ins Repository. Ein Cursor-Neustart oder undatierter/widersprüchlicher
Wert meldet Reconciliation-Bedarf statt automatischer Aktualitätsbehauptung.

## Konkreter Integrationsplan

1. **Voraussetzungen klären:** regionales Developer-Projekt, Empfangsmodus,
   Berechtigungen und getrennte Autorisierung. Bestehende Privat-Session nicht
   umwidmen. Tokenrotation atomar speichern und `openId` unverändert binden.
2. **Begrenzter Live-Nachweis:** ein ausgewählter FP2; zuerst die konkret
   freigegebenen Präsenz-/Lux-/Vital-/Schlafressourcen empfangen. Zonenwechsel,
   leeres Bett und Moduswechsel mit Zustimmung beobachten. Verfügbarkeit und
   p50/p95/max der gemessenen Verzögerungen berichten, fehlende Werte ausweisen.
3. **Optionaler SSE-Adapter:** externe Bridge-Version fest pinnen, deren Zustand
   prüfen, lokale authentifizierte Verbindung mit begrenzten Frames/Queues,
   Abbruch bei Entladen und begrenztem Reconnect-Backoff. Kein Java im HACS-Paket.
4. **Gemeinsame Beobachtungen:** Konto/Gerät/Ressource strikt binden; private
   Trait-Pfade, OpenAPI-Ressourcen und `spec_report` getrennt parsen. Nur überprüfte
   Zuordnungen in bestehende Sensoren übernehmen. Quell- und Empfangszeit,
   Herkunft, Replaystatus und Fehlerqualität erhalten. Snapshot ersetzt keinen
   frischen Zustand; fehlende Felder bleiben unverändert.
5. **Hybridbetrieb:** Push aktualisiert bestätigte Felder sofort nach Empfang;
   priorisiertes Polling dient Startwerten, fehlenden Feldern, Reconciliation und
   Ausfallüberbrückung. Gemeinsame Arbitration verhindert, dass ein älterer Poll
   neuere Pushdaten überschreibt. Reconnect erzeugt keinen Poll-Sturm.
6. **Abnahme:** Tokenablauf, Broker-/Bridge-Neustart, Cursorreset, Duplikate,
   verspätete Meldungen, lange Offlinephase, 429/403, Gerätemoduswechsel,
   HA-Neustart/Entladen und Log-Redaktion testen. Erst danach UI-Option aktivieren.

Die einzige heute durchgeführte Machbarkeitsprüfung ist offline. Offen bleiben
Projektberechtigung, tatsächliche Feldlieferung, gemessene Latenz und ein
vollständiger offizieller AIOT-MQTT-Vertrag. Produktive Push-Unterstützung ist mit
diesem Dokument noch nicht zugesagt.

## Gepinnte Quellstände und Lizenzgrenze

| Projekt / Datei | Commit | Blob |
| --- | --- | --- |
| aqara/aqara-developer-docs, `openapi/aiot-api/en/aiot-api.yaml` | `7db4de3b4bfcab4a42e1fc19b50a5d8eb05ec56d` | `d5950147f63582405a9166278485ec87f8ba4654` |
| Darkdragon14/aqara-rocketmq-bridge, `RocketMqMessageParser.java` | `565413e4fdd425757f13ecbb68bb363eaab6fab0` | `f50019103241f3c1a76b26217d9b7a2c95562375` |
| gleiches Projekt, `EventBroadcaster.java` | gleich | `de2c2b81878c02c51ef17fbde7768a7298099c86` |
| Darkdragon14/ha-aqara-devices, `fp2.py` | `00e964ad29b6cb0b4d5a1f11e22acec022e1a0a7` | `599f87350d941be8ad14cfd22055b8aed19bdfab` |
| MrStrategy/FHEM-AqaraFP2, `fp2_state.py` | `2c1d99bb33a6382f0efd2b8e8967d169b529bf8a` | `dcc2b35413fe0566322329f4e6cce6eeee496452` |

Bridge: Apache-2.0; FHEM-Adapter und Darkdragon-Integration: MIT.
Es wurde kein Fremdprogramm ausgeführt und kein Fremdcode in den Prototyp kopiert.
Die Lizenz- und Abhängigkeitsprüfung eines später ausgelieferten Bridge-Artefakts
bleibt Teil der Umsetzung.
