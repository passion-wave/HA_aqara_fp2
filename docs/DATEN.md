# FP2-Daten und Entitäten

Ab Version **0.3.0b1** liest die Integration neben den bisherigen 31 qlink-Traits
zwei zusätzliche Ressourcengruppen. Der Katalog enthält **81 Statusfelder und
sieben Einstellungen pro Gerät**. Das ist der unterstützte Abfrageumfang,
nicht die zugesicherte Anzahl verfügbarer Sensoren. Firmware, Gerätemodus,
Zonenkonfiguration und Cloud-Antwort entscheiden, welche Werte zurückkommen.

## Zuordnung

| Gruppe | Felder / Bedeutung | Darstellung |
|---|---|---|
| Helligkeit | Bisheriger qlink-Wert und separat `lux` aus der Ressourcenabfrage | Lux; Quelle bleibt erkennbar |
| Gerätemodus | `set_device_mode4`: 3 Zonen, 5 Sturz, 9 Schlaf | Diagnose mit lesbarem Modus und Rohcode |
| Schlaf | `sleep_state`, `body_movement_value` | Schlaf-Rohcode und Bewegungswert ohne erfundene Einheit |
| Vitalwerte | `heartrate_value`, `respiration_rate_value` | Gemeldete Herzfrequenz in bpm, Atemfrequenz in br/min |
| Personen | `people_counting`, `people_counting_by_mins` | Getrennte gemeldete Werte; Dezimalwerte bleiben erhalten |
| Zonenpräsenz | `detection_area1` bis `detection_area30` | Gemeldete Zonenpräsenz, 1 = an / 0 = aus laut Protokollquelle |
| Zonenstatistik | `all_zone_statistics`, `zone1_statistics` bis `zone30_statistics` | Statistik des in der Quelle beschriebenen 10-Sekunden-Fensters |
| Minutenstatistik | `zone1_people_counting_by_mins` bis `zone7_people_counting_by_mins` | Getrennte Minutenwerte der unterstützten Zonen |
| Verbindung | `device_offline_status`: 1 verbunden / 0 getrennt | Vom Gerät berichteter Verbindungsstatus, getrennt vom API-Zugriff |
| Installation | Winkel, Montageposition, Ansicht, `attitude_status` | Diagnose; unbekannter Ausrichtungscode bleibt Rohwert |
| Einstellungen | Präsenz-/Sturzempfindlichkeit, Erkennungsrichtung, Koordinatenumkehr, Annäherungsdistanz, Lichtstörungsfilter, KI-Personenerkennung | Ausschließlich lesbare Diagnose, keine Schalter zum Ändern |

Schlaf-, Herz-, Atem- und Bewegungswerte werden nur angezeigt, wenn dieselbe
verfügbare Ressourcengruppe den Schlafmodus **9** meldet. Beim Wechsel in einen
anderen Modus werden vorhandene Schlafentitäten unverfügbar. Die Integration
ändert den FP2-Modus nicht. Aqara beschreibt getrennte Betriebsmodi; die
Funktionen stehen deshalb nicht alle gleichzeitig zur Verfügung.
[Hersteller-FAQ](https://eu.aqara.com/products/aqara-presence-sensor-fp2)

`people_counting` wird nicht zu einer Ganzzahl gerundet. Für Personen- und
Zonenstatistiken werden weder Zählereignisse aufsummiert noch aktuelle Personen
aus historischen Werten geschätzt. „10 Sekunden“ und „Minute“ beschreiben die
Quellstatistik, nicht das Abrufintervall der Integration.

## Nach dem Update

Bestehende Anmeldung und Geräteauswahl werden weiterverwendet. Auf der
Integrationsseite stehen die vorhandenen Geräte sowie die Kontodiagnose
**Zusatzdatenstatus**. Nach dem ersten erfolgreichen Ressourcenabruf entstehen
weitere Entitäten direkt beim jeweiligen FP2. Eine Neuanmeldung ist dafür nicht
vorgesehen, solange die gespeicherte Sitzung noch gültig ist.

Die Integration legt neue Ressourcenentitäten erst nach einem tatsächlich
enthaltenen, gültigen Wert an. Zonen und Einstellungen sind standardmäßig
deaktiviert: In **Einstellungen → Geräte & Dienste → Aqara Presence Lab → Gerät**
die deaktivierten Entitäten einblenden und die gewünschten aktivieren. Sie
behalten ihre Kennung über Tokenwechsel und Neustarts hinweg.

Zusatzabfragen laufen nacheinander im Hintergrund. Alle Kontozugriffe teilen
standardmäßig mindestens 30 Sekunden Abstand. Bei zwei Geräten benötigen die vier zusätzlichen
Abfragen deshalb normalerweise ungefähr zwei Minuten nach dem Trait-Abruf;
Serverpausen und konkurrierende Abrufe können diese Zeit verlängern. Es werden
nicht 81 einzelne Anfragen pro Gerät gesendet: alle Statusfelder werden
zusammen angefordert, die sieben Einstellungen in einer zweiten Anfrage.
Ab 0.4.0b1 läuft der Statusabruf unabhängig im Rundlauf, Einstellungen
standardmäßig nur stündlich. Details und kürzere experimentelle Abstände:
[Priorisierte Abfragen](POLLING.md).

## Qualität und fehlende Werte

- **Keine Entität:** Das Feld wurde noch nicht gültig geliefert oder benötigt einen anderen gemeldeten Modus.
- **unknown:** Eine bereits bekannte Entität hat in der neuesten Antwort keinen gültigen Wert; ein unbekannter Enum-Code wird als Attribut erhalten.
- **unavailable:** Abfragegruppe fehlgeschlagen, lokaler Empfang veraltet oder erforderlicher Schlafmodus nicht verfügbar.
- **Zusatzdatenstatus:** `idle`, `updating`, `ready`, `partial_failure` oder `unavailable` beschreibt die Abfragen, nicht die physische Messfrische.

Jede Antwort ersetzt die vorherige Gruppe. Fehlende Werte werden weder mit Null
gefüllt noch aus dem letzten Abruf ergänzt. Fehler und Fristen gelten getrennt
für Gerät und Abfragegruppe. Ein Ausfall der Einstellungsabfrage macht keinen
erfolgreich gelesenen Schlafwert oder qlink-Wert ungültig.

Die Attribute `data_quality`, `value_status` und `semantic_evidence` zeigen die
Nachweisgrenze. `source_documented` bedeutet, dass die Zuordnung in der fixierten
Protokollquelle steht. Es bedeutet keine eigene physische Validierung. Bei Schlaf-
und Ausrichtungsrohcoden bleibt die Semantik `unknown`. Ressourcenzeitstempel
werden ohne belegte Einheit nicht in Messzeitpunkte umgerechnet; Empfangszeit
und Quellenzeit bleiben getrennt. Es gibt noch keine `state_class` für
Langzeitstatistiken dieser Werte.

## Noch nicht erschlossene Daten

Genaue X-/Y-Koordinaten, individuelle Personen-IDs, Schlafphasenberichte,
Schlafdauer und eine validierte aktuelle Sturzmeldung sind durch die derzeitigen
Quellen für diese private API nicht hinreichend belegt. Die historische
qlink-Sturzkennung bleibt ein optionaler Rohcode. Aus einer Koordinatenumkehr-
Einstellung entsteht kein Positionssensor, aus `attitude_status` kein Sturzalarm.

Für weitere Felder braucht es einen passenden aktuellen App-Mitschnitt mit
gezielter Funktion und anschließend eine Zuordnungsprüfung. Ein anderer
Aqara-OpenAPI-/Push-Zugang erfordert einen eigenen belegten Vertrag und dessen
Zugangsdaten. Die bisherige Anmeldung wird nicht als Berechtigung für einen
unbekannten Dienst verwendet. Quellen und Lizenzen: [Protokollquelle](PROTOCOL_SOURCE.md).
