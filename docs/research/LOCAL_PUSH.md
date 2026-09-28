# Lokale FP2-Ereignisse und Plan für Push-Präsenz

Stand: 28. September 2026. Recherche und Machbarkeitsprüfung; der unten beschriebene Adapter ist noch nicht implementiert.

Für schnelle Präsenzautomationen ist die vorhandene **HomeKit-Device-Anbindung** der bevorzugte Weg. Sie kann Ereignisse im LAN liefern und benötigt dafür keinen zusätzlichen Aqara-Cloud-Poll. Herz- und Atemfrequenz bleiben ein eigener Datenpfad: Eine offiziell unterstützte lokale FP2-Schnittstelle dafür ist durch die recherchierten Quellen nicht belegt. Eine gemessene physische Erkennungslatenz liegt aus dieser Untersuchung nicht vor.

## Belegte Möglichkeiten und Grenzen

| Weg | Belegte Daten / Eigenschaft | Konsequenz |
| --- | --- | --- |
| FP2 → HomeKit Device → HA | Lokale Push-Anbindung; bei instabilen IP-Verbindungen ist Polling als Rückfall möglich. | Beste belegte Ausgangsbasis für Präsenz ohne Cloud-Abfrageintervall. [HA: HomeKit Device](https://www.home-assistant.io/integrations/homekit_controller/) |
| FP2-HomeKit-Funktionsumfang | Aqara nennt Zonenpräsenz und Helligkeit sowie direkte Einbindung in HA. | Bestehende HomeKit-Entitäten verwenden; keine zusätzlichen Vitaldaten daraus ableiten. [Aqara FP2](https://www.aqara.com/us/product/presence-sensor-fp2/) |
| Herz- und Atemfrequenz | Aqara beschreibt Schlafmessungen in Echtzeit, schränkt aber ausdrücklich ein, dass Herz- und Atemfrequenz derzeit nicht für Drittanbieterökosysteme freigegeben sind. | Die Herstellerwerbung belegt weder einen HomeKit-Vitaldatenkanal noch dessen Zeitverhalten. Der experimentelle Cloud-Zugriff dieses Projekts ist davon zu unterscheiden. [Aqara FP2, Schlafmonitoring-Fußnote](https://partnerships.aqara.com/products/presence-sensor-fp2-6) |
| Matter | Die Entwicklerdokumentation führt `lumi.motion.agl001` unter Nicht-Matter-Geräten; Tabellenstand 26. November 2025. Die Produktseite nennt Matter im Abschnitt über mögliche zusätzliche Funktionen. | Kein nachgewiesener aktueller FP2-Matter-Pfad für diese Installation. Eine Zukunftsankündigung ist keine verfügbare Firmwarefunktion. [Aqara Entwicklerdokumentation](https://opendoc.aqara.com/en/docs/developmanual/apiDocument/trait-details.html), [Produktseite](https://www.aqara.com/us/product/presence-sensor-fp2/) |
| Eigenes LAN-Protokoll für Vitaldaten | In den geprüften offiziellen Produkt-, HomeKit- und Entwicklerunterlagen wurde kein verwendbarer FP2-Vertrag dafür gefunden. | Offen lassen; keine geratenen Ports, HTTP-Endpunkte oder Nachrichtenformate implementieren. Ein SDK-Geräteeintrag allein würde diesen Vertrag ebenfalls nicht belegen. |

Die FP2-Anleitung beschreibt, dass konfigurierte Aqara-Zonen nach HomeKit synchronisiert werden und dort eigene Präsenzsensoren ergeben. Die Anleitung stammt von 2023; sie ist ein Beleg für diesen Grundmechanismus, kein vollständiges Verzeichnis späterer Firmwarefunktionen. [Offizielle FP2-Anleitung, Abschnitt Apple Home](https://www.aqara.com/wp-content/uploads/2023/07/Presence-Sensor-FP2_.pdf)

## Tatsächlich geprüft

Eine ausschließlich lesende, aggregierte Abfrage der vorhandenen HA-Gerätezuordnung fand ein HomeKit-Gerät mit Modell `PS-S02D`: drei Präsenzentitäten, eine Helligkeitsentität und eine Identify-Schaltfläche. Die vier Messentitäten hatten gültige Zustände. Vitaldatenentitäten waren in dieser Auswahl nicht vorhanden. Namen, Gerätekennungen, Messwerte und Zugangsdaten wurden für diesen Bericht nicht übernommen.

Das bestätigt die unmittelbar verfügbare HA-Anbindung dieses Geräts. Es ist weder eine vollständige Enumeration aller HAP-Characteristics noch ein Nachweis für die Fähigkeiten weiterer FP2-Geräte. Es wurden keine Geräte zurückgesetzt, umgepaart oder auf neue Modi umgestellt.

Der installierte offizielle HA-Quellstand 2026.9.3 wurde zusätzlich gelesen:

- `HomeKitOccupancySensor` verwendet `OCCUPANCY_DETECTED`; der Lichtsensor verwendet `LIGHT_LEVEL_CURRENT`. [Präsenzabbildung](https://github.com/home-assistant/core/blob/2026.9.3/homeassistant/components/homekit_controller/binary_sensor.py), [Sensorabbildungen](https://github.com/home-assistant/core/blob/2026.9.3/homeassistant/components/homekit_controller/sensor.py)
- Die Verbindung registriert Ereignis-Callbacks und abonniert meldbare Characteristics. `process_new_events` aktualisiert anschließend die Entitäten. Auch Pollantworten können denselben Verarbeitungspfad erreichen. **Ein HA-Zustandswechsel allein beweist daher nicht, ob sein Ursprung Push oder Polling war.** [Verbindungsimplementierung](https://github.com/home-assistant/core/blob/2026.9.3/homeassistant/components/homekit_controller/connection.py)

Zwei isolierte Tests des echten HA-Helfers `async_track_state_change_event` bestanden gegen HA 2026.9.3 mit gesperrten IP-Sockets: Ereignisse wurden nur für die ausgewählte Entität geliefert; `off`, `on`, `unknown` und `unavailable` blieben unterscheidbar. Nach Abmeldung kam kein weiterer Callback. Das prüft den vorgesehenen lokalen Anschluss innerhalb von HA. Es simuliert weder Radar noch HAP und misst keine Geräte-, LAN- oder Cloud-Latenz.

## Umsetzungsvorschlag

1. **Vorhandene Präsenz zuerst verwenden.** Automationen können bereits direkt auf den bestehenden HomeKit-Präsenzentitäten aufbauen. Eine zusätzliche Projekterweiterung ist erst für eine gemeinsame Ansicht oder explizite Zuordnung zu Cloud-Zonen erforderlich. Bestehende Entity-IDs, Geräteidentitäten und Automationen bleiben dabei erhalten.
2. **Optionaler lokaler Adapter.** In den Optionen werden die vorhandenen Präsenz- und optional Helligkeitsentitäten ausdrücklich ausgewählt. Keine automatische Zuordnung anhand gleicher Raum- oder Anzeigenamen. Der Adapter liest zunächst den aktuellen Zustand und registriert mit `async_track_state_change_event` nur die ausgewählten Entitäten. HA empfiehlt diese gezielten Ereignishelfer; die zurückgegebene Funktion entfernt die Registrierung. [HA-Ereignishelfer](https://developers.home-assistant.io/docs/integration_listen_events/)
3. **Quellen und Verfügbarkeit erhalten.** `on` und `off` ergeben Präsenzwerte; `unknown`, `unavailable`, entfernte oder nicht vorhandene Entitäten ergeben keinen falschen Abwesenheitswert. Die lokale Quell-Entity-ID bleibt intern nachvollziehbar. Eine gemeinsame Ansicht weist die Quelle aus; ein alter Cloud-Wert darf ein jüngeres lokales Ereignis nicht still überschreiben. Die HA-Empfangszeit ist keine Radar-Messzeit. Ein unveränderter Präsenzzustand wird nicht allein wegen fehlender Zustandswechsel als veraltet eingestuft.
4. **Lebenszyklus vollständig behandeln.** Registrierungen bei Unload und Optionsänderungen entfernen; Entity-Registry-Umbenennungen und Löschungen behandeln; erneutes Laden ohne doppelte Listener testen. Der Adapter besitzt keinen eigenen HomeKit-Controller und keine Kopie der HomeKit-Schlüssel. Vorhandene Paarungen werden weiterverwendet.
5. **Vitalwerte getrennt betreiben.** Herz-/Atemfrequenz und andere Schlafwerte verbleiben im validierten Cloud-Ressourcenpfad mit dessen Modus-, Datenqualitäts- und Rate-Limit-Regeln. Kürzere Pollintervalle müssen neue Messwerte nachweisen; eine schnelle HTTP-Antwort mit unverändertem Cloud-Cache genügt nicht. Einstellungen können unabhängig selten abgefragt werden. Lokale Präsenzereignisse dürfen keine zusätzliche Cloud-Anfrage auslösen.

Ein eigenständiges Cloud-Push-Protokoll wäre eine weitere Erweiterung. Vor dessen Implementierung müssen Geräteunterstützung, Anmeldung, Event-Schema, Zuordnung, Reconnect und zulässiges Abonnement nachgewiesen sein. Aus HomeKit-Unterstützung folgt kein Cloud-Abonnement für Vitalwerte.

## Mess- und Abnahmeplan

Die Ende-zu-Ende-Zeit umfasst Radarerkennung, Gerätefilter, Übertragung und HA-Verarbeitung. Herstellerbegriffe wie Echtzeit nennen hier keine garantierte Millisekundenzahl. Weder die Dauer eines HTTP-Requests noch die Laufzeit des Offline-Tests ersetzt diese Messung.

Für einen kontrollierten Praxistest werden vorhandene lokale Entitäten passiv beobachtet. Je Zone sind wiederholte Eintritts- und Austrittsversuche mit unabhängig protokolliertem Referenzzeitpunkt nötig; beispielsweise mindestens zehn Ereignisse pro Richtung. Empfangszeit und Referenzzeit müssen auf eine vergleichbare Uhr bezogen sein. Ein-/Ausschaltverzögerung getrennt auswerten und Anzahl, Median, Maximum sowie Messunsicherheit nennen. Ein p95 wird erst bei ausreichend vielen Versuchen belastbar. Währenddessen keine Sensoreinstellungen verändern.

Parallel können die ohnehin laufenden Cloud-Abfragen protokollieren, wann sich ein Feld erstmals ändert. Ohne verifizierten Gerätezeitstempel ist das nur ein Vergleich der Beobachtungszeitpunkte. Unveränderte Vitalwerte können echte konstante Werte oder Cache-Inhalte sein; ihre Herkunft lässt sich nicht durch häufigeres Abfragen allein entscheiden.

Abnahmekriterien für den geplanten Adapter:

- Ein lokaler Zustandswechsel erreicht die gewählte Ansicht ohne zusätzliches Aqara-HTTP-Request.
- Ungültige oder verschwundene Quellen erzeugen keine künstliche Abwesenheit.
- Quellenwechsel ist sichtbar; Präsenz wird nicht aus Schlaf-Rohcodes abgeleitet.
- Entladen, erneutes Laden und Umbenennen hinterlassen keine Listener oder falsche Zuordnung.
- Diagnosen enthalten ausschließlich Struktur und erlaubte Statusangaben; keine Messwertfolgen, Konten, Schlüssel oder Raumbezeichnungen.

Eine rein lesende Ereignisbeobachtung kann den laufenden HomeKit-Pfad auswerten. Ein späterer Ausfalltest mit getrenntem Internet oder WLAN wäre ein eigener, potenziell störender Testschritt; er wurde hier nicht durchgeführt. Der genaue HAP-Push-Ursprung müsste gezielt und datensparsam auf Verbindungsebene bestätigt werden, bevor ein Messergebnis als reine Push-Latenz bezeichnet wird.

## Reproduzierbare Offline-Prüfung

Die folgenden beiden temporären Tests wurden mit der vorhandenen Entwicklungsumgebung ausgeführt; Ergebnis: **2 bestanden**. Sie können außerhalb des Repositories als `/tmp/test_fp2_local_event_contract.py` abgelegt werden. Sie prüfen nur die offizielle HA-Ereignisschnittstelle, keinen bereits implementierten Projektadapter.

```python
import pytest
from homeassistant.core import callback
from homeassistant.helpers.event import async_track_state_change_event

pytestmark = pytest.mark.asyncio


async def test_scoped_presence_events_preserve_unavailable(hass):
    events = []

    @callback
    def changed(event):
        events.append((event.data["entity_id"], event.data["new_state"].state))

    remove = async_track_state_change_event(hass, ["binary_sensor.synthetic_fp2"], changed)
    values = ["off", "on", "unknown", "unavailable", "off"]
    for value in values:
        hass.states.async_set("binary_sensor.synthetic_fp2", value)
        hass.states.async_set("binary_sensor.unrelated", value)
        await hass.async_block_till_done()
    assert events == [("binary_sensor.synthetic_fp2", value) for value in values]
    remove()


async def test_unload_removes_listener(hass):
    events = []

    @callback
    def changed(event):
        events.append(event.data["new_state"].state)

    remove = async_track_state_change_event(hass, ["binary_sensor.synthetic_fp2"], changed)
    hass.states.async_set("binary_sensor.synthetic_fp2", "on")
    await hass.async_block_till_done()
    remove()
    hass.states.async_set("binary_sensor.synthetic_fp2", "off")
    await hass.async_block_till_done()
    assert events == ["on"]
```

Aufruf aus dem Repository mit installierten Entwicklungsabhängigkeiten:

```sh
.venv314/bin/pytest -q -c /dev/null --rootdir=/tmp -p no:cacheprovider \
  --asyncio-mode=auto --disable-socket --allow-unix-socket \
  /tmp/test_fp2_local_event_contract.py
```

Unix-Sockets für den lokalen Testbetrieb bleiben erlaubt; IP-Netzwerkzugriffe sind gesperrt. Der Test benötigt weder ein FP2-Gerät noch Aqara- oder HomeKit-Zugangsdaten.
