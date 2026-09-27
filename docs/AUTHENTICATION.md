# Anmeldung und lokale Speicherung

## Anmeldeweg

Die Integration verwendet den im [SleepRadar-Quellstand](PROTOCOL_SOURCE.md)
implementierten EU-Login `/app/v1.0/lumi/user/login`. Die Passwortaufbereitung
folgt dessen RSA-Verfahren; eine erfolgreiche Serverantwort liefert Token und
Benutzerkennung. Dies ist ein privates App-Protokoll und kein OAuth-Angebot der
offiziellen Aqara Open API. Ein erfundener Refresh-Endpunkt wird nicht aufgerufen.

Der Nutzer startet die Anmeldung bewusst im Home-Assistant-Assistenten und
erlaubt die automatische Wiederanmeldung. Eine Installation, Offline-Vorschau
oder das bloße Öffnen der ersten Seite startet keine Anmeldung.

## Zugangsdaten

- **Lokal eingeben:** Der Assistent schreibt eigene benannte Einträge in die
  `secrets.yaml` des Home-Assistant-Konfigurationsverzeichnisses. Andere Einträge
  und Kommentare bleiben erhalten. Geschrieben wird erst nach erfolgreicher
  Prüfung und Abschluss der Einrichtung.
- **Vorhandene Secrets verwenden:** Der Assistent erhält die Namen bereits
  angelegter Konto- und Passwort-Einträge.

Beispiel mit ausdrücklich fiktiven Werten:

```yaml
# /config/secrets.yaml
aqara_account: "DEIN_AQARA_KONTO"
aqara_password: "DEIN_AQARA_PASSWORT"
```

Im Assistenten die Schlüsselnamen `aqara_account` und `aqara_password` angeben,
ohne vorangestelltes `!secret`. Konto und Passwort werden nicht in den Config
Entry kopiert. Er enthält Referenzen, serverseitig bestätigte Kontoidentität,
Geräteauswahl und Betriebsoptionen.

Unterstützt werden Einträge als einfache Zeichenketten in einer YAML-Zuordnung.
Mehrdeutige Dateien mit doppelten Schlüsseln, speziellen Tags wie `!include` oder
`!env_var`, Dateiverknüpfungen und Dateien über 1 MiB werden abgewiesen, ohne
ihren Inhalt zu protokollieren. Die Integration verändert solche Dateien nicht.

`secrets.yaml` speichert Werte im Klartext. Dateirechte und das lokale
Home-Assistant-System schützen die Datei; eine zusätzliche Verschlüsselung wird
nicht behauptet. Sitzungstokens liegen getrennt in einem privaten Speicher unter
`.storage`. Beide Bereiche gehören in die eigene Backup- und Zugriffskontrolle.

## Automatische Neuanmeldung

Eine vorhandene Sitzung wird bei Neustart wiederverwendet. Ein normaler Abruf
löst keine erneute Anmeldung aus. Bei belegtem Sitzungsablauf wird ein
gemeinsamer Anmeldeversuch ausgeführt. Parallele Sensoren starten keine
zusätzlichen Logins. Ein neuer Token wird erst nach Prüfung derselben
Benutzerkennung und der gewählten Geräte dauerhaft übernommen.

Login, Datenabruf und manuelles Aktualisieren beachten gemeinsame Mindestabstände
und Serverpausen. Ein Netzwerkfehler beim Datenabruf allein löst keinen Login aus.
Ist eine Neuanmeldung bereits nötig und scheitert sie an einer vorübergehenden
Verbindungsstörung oder Serverpause, darf ein späterer Abruf nach dem Backoff
einen neuen Versuch machen. Innerhalb eines Aufrufs gibt es keine Login-Schleife.
Abgelehnte Zugangsdaten, unbekannte Anwendungscodes und Signaturprobleme
beenden den automatischen Anmeldeweg; Home Assistant zeigt die erforderliche
Benutzeraktion an.

Bei einer geänderten Anmeldung bleibt die Kontoidentität gleich. Für ein anderes
Aqara-Konto einen separaten Eintrag einrichten. Geräte- und Entitätskennungen
werden nicht aufgrund eines Tokenwechsels neu erzeugt.

## Grenzen der Beta

Der reale Login am Nutzerkonto sowie Dauerbetrieb und Subscription-Verhalten
bleiben gesonderte Nachweise. Der ausdrückliche Start des experimentellen
Anmeldewegs ersetzt sie nicht; er ermöglicht ihre kontrollierte Erprobung.
Die [Validierung](VALIDIERUNG.md) dokumentiert den tatsächlichen Stand.
