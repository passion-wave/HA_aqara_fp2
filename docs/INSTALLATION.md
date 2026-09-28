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
Im Versionsdialog die Daten-Beta **0.4.0b1** auswählen.

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

Standardmäßig liegen zwischen Kontozugriffen mindestens 30 Sekunden.
Login und anschließende Geräteprüfung behalten diesen Mindestabstand auch
bei experimentell verkürzten Leseabständen. Deshalb zeigt die Einrichtung
einen Fortschritt an. Serverpausen können eine spätere Wiederholung erfordern.

Die Geräte-IDs stammen beispielsweise aus einem lokalen Aqara-Mitschnitt. Eine
Zeile pro Gerät eingeben; keine Tokens oder vollständigen Requests in dieses Feld
kopieren. Details: [Anmeldung und Speicherung](AUTHENTICATION.md).

## Zusätzliche Daten nach dem Update

Version 0.4.0b1 übernimmt das bestehende Konfigurationsschema und die lokale
Sitzung. Nach dem Update und Neustart erscheinen tatsächlich gelieferte
Ressourcen bei den vorhandenen FP2. Der erste Hintergrundlauf benötigt
mehrere Minuten. Zonen und Einstellungen sind zunächst deaktiviert; nur die
benötigten Entitäten einschalten. Umfang und Status sind im
[Datenkatalog](DATEN.md) erklärt.

## Prioritäten und Geschwindigkeit

In **Konfigurieren** lassen sich Status-/Vitalintervall, seltene Einstellungen,
QLINK-Intervall und Kontoabstand getrennt einstellen. Standardmäßig gelten
60 / 3600 / 300 Sekunden und 30 Sekunden Kontoabstand. Der administrative
Test mit zehn Abfragen ist in [Abfragegeschwindigkeit](POLLING.md) erklärt.
Der neue [Push-Plan](PUSH_PLAN.md) beschreibt die getrennten lokalen und
Cloud-Pfade samt noch erforderlichen Nachweisen.

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
