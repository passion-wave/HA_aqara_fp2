# Installation und Betrieb

## Voraussetzungen

Die Beta wird mit Home Assistant **2026.9.3** auf Python **3.14.6** geprüft.
Ein älterer HA-Stand ist nicht freigegeben. Docker / Home Assistant Container
benötigt kein Add-on und keinen zusätzlichen Dienst. Das private Protokollprofil
ist ausschließlich für den beobachteten EU-Host angelegt.

## HACS

Das Repository ist seit dem 27.09.2026 öffentlich. Die
[offizielle HACS-Remoteprüfung](https://github.com/passion-wave/HA_aqara_fp2/actions/runs/36302490172)
ist bestanden; die Installation als benutzerdefiniertes Repository ist verfügbar.

HACS öffnen, Menü **Benutzerdefinierte Repositories**, Repository-URL
`https://github.com/passion-wave/HA_aqara_fp2`, Kategorie **Integration**.
Anschließend Aqara Presence Lab herunterladen und HA regulär neu starten.
Im Versionsdialog die Anmelde-Beta **0.2.0b1** auswählen.

Unter **Geräte & Dienste → Integration hinzufügen → Aqara Presence Lab** den
Anmeldeweg öffnen. Die Zustimmung aktiviert den experimentellen Cloud-Zugriff
und die automatische Neuanmeldung. Konto und Passwort lokal eingeben oder
vorhandene Secret-Namen verwenden; anschließend die Geräte-IDs der FP2 angeben.
Der Assistent prüft Login und Gerätezugriff, bevor die Einrichtung abgeschlossen
wird. Die Offline-Vorschau ist weiterhin eine separate Erklärung ohne Entitäten.

## Manuell / Container

Das Release-ZIP enthält `custom_components/aqara_presence_lab/...`.
Es wird in das auf `/config` gemountete HA-Verzeichnis entpackt. Ergebnis:

```text
/config/custom_components/aqara_presence_lab/manifest.json
/config/custom_components/aqara_presence_lab/__init__.py
```

Keinen zweiten verschachtelten `custom_components`-Ordner anlegen. Danach den
eigenen HA-Container mit dem üblichen Betriebsverfahren neu starten.
Dieses Projekt nimmt keinen automatischen Neustart oder Eingriff am laufenden HA vor.

## Einrichtung und Wiederanmeldung

Die Architektur verwendet einen Entry pro bestätigtem EU-Konto und eine explizite
Geräteauswahl. Der Startwert für das Pollintervall beträgt 300 Sekunden, die
Untergrenze 60 Sekunden. Ein Refresh nutzt denselben Account-Limiter.
Eine neue Sitzung aktualisiert den bestehenden Entry; ein Kontowechsel wird
nicht als Reauth akzeptiert. Nach Ablauf eines bestätigten Sitzungstokens kann
die Integration eine neue Anmeldung durchführen. Die Zugangsdaten werden
aus den gespeicherten Secret-Referenzen gelesen. Zusätzliche Bestätigungen oder
abgelehnte Zugangsdaten werden als erforderliche Benutzeraktion angezeigt.
Vorübergehende Netzwerkfehler erlauben einen späteren Versuch nach dem Backoff;
ein einzelner Abruf wiederholt die Anmeldung nicht in einer Schleife.

Zwischen Kontozugriffen liegen mindestens 30 Sekunden; auch Login und die
anschließende Geräteprüfung teilen diesen Abstand. Deshalb zeigt die Einrichtung
einen Fortschritt an. Serverpausen können eine spätere Wiederholung erfordern.

Die Geräte-IDs stammen beispielsweise aus einem lokalen Aqara-Mitschnitt. Eine
Zeile pro Gerät eingeben; keine Tokens oder vollständigen Requests in dieses Feld
kopieren. Details: [Anmeldung und Speicherung](AUTHENTICATION.md).

## Diagnose

Zuerst Verbindungsstatus und Datenqualität betrachten. Rohwert `0` heißt ohne
Semantiknachweis nicht „Raum leer“. Alte `traitTime`-Werte werden nicht als neue
Messungen ausgegeben. Sensorwerte können `unknown` oder `unavailable` sein;
die Verbindungsdiagnose bleibt bei einem Transportfehler lesbar.

Keine Rohantworten, cURL-Kommandos oder HAR-Dateien in Issues hochladen.
Ein Supportbericht soll nur Versionen, Fehlerklasse und die bereinigte
Integrationsdiagnose enthalten. Bekannte Grenzen stehen im [Validierungsbericht](VALIDIERUNG.md).
Die verfügbaren Logstufen und Fehlerklassen erklärt [Logs und Diagnose](LOGGING.md).

## Update, Rollback und Entfernen

Vor einem Update Konfiguration einschließlich `secrets.yaml` und `.storage`
sichern. Version 0.2.0b1 verwendet Config-Entry-Schema 2. Alte Einträge aus Schema 1
benötigen eine neue geprüfte Anmeldung; der alte unbestätigte Token wird nicht als
Identitätsnachweis übernommen. Unbekannte zukünftige Schemaversionen werden
nicht heruntergestuft.

Für einen Rollback die frühere Integrationsversion wiederherstellen und neu starten.
Nur bei einer dokumentierten inkompatiblen Schemamigration zusätzlich das passende
Backup verwenden. Niemals HomeKit-Pairings, lokale Präsenzsensoren oder Automationen
löschen. Beim Entfernen ausschließlich den Aqara-Presence-Lab-Entry und danach
das HACS-Paket entfernen. HA verwaltet die Recorder-Historie nach eigener
Aufbewahrungsregel; diese Integration löscht keine Verlaufsdaten.
Der private Sitzungsspeicher wird beim Entfernen bereinigt. Secret-Einträge
werden nicht ungefragt gelöscht, da sie anderweitig referenziert sein können.
