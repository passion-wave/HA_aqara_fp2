# Plan für Push und möglichst kurze Reaktionszeiten

Stand: 28. September 2026. **Plan und Machbarkeitsnachweise; kein neuer Cloud-Push-Kanal in 0.4.0b1.** Priorisiertes Polling und der begrenzte Geschwindigkeitstest sind dagegen implementiert.

## Entscheidung

Die beste belegte Architektur kombiniert lokale HomeKit-Präsenz mit einem getrennten Kanal für experimentelle Cloud-Vitalwerte. Ein einziger nachgewiesener Push-Weg für alle FP2-Werte steht nicht zur Verfügung. Eine garantierte Millisekundenlatenz lässt sich aus den Quellen nicht ableiten.

| Daten | Bevorzugter Weg | Nachweis / Grenze |
|---|---|---|
| Präsenz, konfigurierte Zonen, Helligkeit | Bestehendes HomeKit Device im LAN | Lokaler Push unterstützt; bei instabiler Verbindung Polling möglich. In dieser Installation ein FP2 mit drei Präsenz- und einer Helligkeitsentität vorhanden. |
| Herz-/Atemfrequenz, Schlaf und Bewegung | Jetzt priorisiertes Ressourcen-Polling; als nächstes OpenAPI/RocketMQ prüfen | Ressourcen in Implementierungsquellen belegt; tatsächliche Push-Lieferung und Frequenz im eigenen EU-Konto offen. |
| Einstellungen | Seltene Abfrage; später optionale Änderungsereignisse | Stündliches Polling reicht für gemeldete Einstellungen; kein dauerndes Wiederholen nötig. |
| Personenkoordinaten | Eigener späterer Versuch | Community-Implementierungen liefern Targets; Einheiten, Ursprung und Bedeutung müssen vor Darstellung nachgewiesen werden. |

HA dokumentiert den lokalen Push-Pfad samt Polling-Rückfall. Er umgeht das Cloud-Abfrageintervall und ist deshalb die bevorzugte Ausgangsbasis für schnelle Präsenz; das ist eine Architekturentscheidung, kein gemessener Geschwindigkeitsrekord. [HomeKit Device](https://www.home-assistant.io/integrations/homekit_controller/)

Aqara schränkt die Freigabe von Herz-/Atemfrequenz für Drittanbieterökosysteme ausdrücklich ein. Daraus folgt kein offiziell unterstützter lokaler Vitaldatenkanal. Der vorhandene experimentelle Privat-API-Abruf ist davon getrennt. [Aqara FP2](https://partnerships.aqara.com/products/presence-sensor-fp2-6)

## Phase 1: Vorhandene lokale Ereignisse zuordnen

1. Vorhandene HomeKit-Entity-Registry-Einträge ausdrücklich dem jeweiligen FP2 und seinen Zonen zuordnen; keine Namensheuristik und keine neue Paarung.
2. Optionalen Adapter mit HA-Ereignishelfern implementieren. Anfangszustand übernehmen, danach nur die ausgewählten Entitäten beobachten. Unload, Rename, Entfernen und Reload vollständig behandeln.
3. Quellen separat ausweisen. `unknown` und `unavailable` bleiben unbekannt, ein alter Cloudwert darf lokale Präsenz nicht überschreiben. Ausbleibende Zustandsänderungen bedeuten bei Präsenz keine veraltete Messung.
4. Automationen können die vorhandenen lokalen Entitäten bereits direkt verwenden. Der Adapter dient nur der ausdrücklichen Zuordnung und gemeinsamen Ansicht; lokale Ereignisse dürfen keine zusätzliche Cloudabfrage auslösen.

**Machbarkeit:** Zwei Offline-Tests der echten HA-Ereignishelfer prüften Filterung, Zustände und Listener-Cleanup. Die aktuelle Geräte-/Entitätszuordnung wurde ausschließlich lesend geprüft. HAP-Übertragung und physische Erkennungslatenz wurden dabei nicht gemessen. Details und reproduzierbarer Test: [Lokaler Push](research/LOCAL_PUSH.md).

## Phase 2: Separaten Cloud-Push-Zugang vorbereiten

1. Entwicklerprojekt in der richtigen Aqara-Region mit `Appid`, `Keyid`, `Appkey`, autorisiertem OpenAPI-Token und `openId`-Bindung bereitstellen. Die bestehende Privat-API-Sitzung ist kein nachgewiesener Ersatz.
2. Schlüssel über Secret-Referenzen, Tokens in eigenem privatem Store mit atomarem Refresh speichern; Identität und Geräteauswahl serverseitig prüfen. Credentials bleiben außerhalb von Logs und Diagnose.
3. RocketMQ-Verbindung als separaten lokalen Dienst betreiben und per authentifiziertem SSE in HA anbinden. Keine Java-Laufzeit in die HACS-Integration einbetten. Wiederverwendbare Bridge erst nach Prüfung von Lizenz, Wartungszustand und Authentifizierung auswählen.
4. Nur autorisierte Geräte und bekannte Resource-/Traitfelder verarbeiten. Nachrichten begrenzen, Typen/Einheiten/Modus prüfen, Duplikate und Reihenfolge behandeln. Gepufferte Snapshots dürfen nicht als frisch empfangenes Radarsignal gelten.
5. Verbindungsabbruch mit Backoff und langsamer Abfrage zur Wiederherstellung des Zustands behandeln. Push und Polling bleiben als Quellen unterscheidbar; bisherige IDs und Automationen erhalten.

Aqara dokumentiert Ressourcen-Abonnements und Änderungsberichte. Diese verwenden den separaten OpenAPI-Vertrag. Die neuere AIOT-Einführung nennt MQTT, aber der geprüfte veröffentlichte API-Vertrag enthält noch keine ausreichenden Broker-/Topic-/Subscribe-Details für einen getesteten Adapter. `needSubscribe=true` im bestehenden privaten HTTP-Request belegt ebenfalls keine empfangbare Push-Verbindung. [Offizielle Push-API](https://opendoc.aqara.com/en/docs/developmanual/messagePush/messagePushAPI.html), [AIOT-Einführung](https://docs.aqara.com/docs/aqara-developer/aiot-api/introduction/)

**Machbarkeit und genaue Quellen:** [Cloud-Push-Recherche](research/CLOUD_PUSH.md). Offline-Vertragsprüfungen mit synthetischen Nachrichten belegen Parser-/Replay-Verhalten, keine Anmeldung oder Live-Zustellung. Der nächste echte Cloud-Nachweis benötigt das separate Entwicklerprojekt; es wurde hier keines angelegt.

## Phase 3: Vergleich und Abnahme

- Zuerst je Kanal ausschließlich lesende Proben mit festem Nachrichten-/Zeitbudget und bereinigten Zählern durchführen. Bei Fehlern stoppen, kein blindes Wiederholen der Anmeldung.
- Für Präsenz physische Eintritte/Austritte mit unabhängigem Referenzzeitpunkt erfassen; Ein-/Ausschaltlatenz getrennt auswerten. Ein HA-State-Event allein unterscheidet HomeKit-Push nicht vom HomeKit-Polling-Rückfall.
- Für Vitalwerte echte Änderungen am zulässigen FP2 im Schlafmodus nachweisen. Cloud-Zeitstempel erst nach Validierung als Messzeit nutzen. Gleichbleibende Werte können reale Konstanz oder Cache bedeuten.
- Empfang → HA-Veröffentlichung separat messen. Cloud-Transport, Bridge-Batching, Radarfilter und physische Messung nicht zu einer unbelegten Zahl zusammenfassen.
- Duplikate, falsche Geräte, beschädigte Nachrichten, Reconnect, Serverlimit, Tokenwechsel, Neustart und Quellenkonflikte testen. Keine falschen Abwesenheitswerte oder rückwärts überschriebenen Zustände.
- Erst nach bestandenem Live-Nachweis Polling für tatsächlich pushfähige Gruppen verlangsamen; für nicht gelieferte Felder bleibt der jetzige Pollingpfad erhalten.

Erfolg bedeutet: lokale Präsenz ohne zusätzliche Cloudwartezeit, belegte Vitaldatenereignisse mit stabiler Konto-/Gerätebindung und reproduzierbare Ausfallbehandlung. Ein funktionierender SSE-Socket allein erfüllt diese Kriterien nicht.
