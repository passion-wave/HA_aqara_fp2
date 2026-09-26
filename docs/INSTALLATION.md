# Installation und Betrieb

## Voraussetzungen

Die Beta wird mit Home Assistant **2026.9.3** auf Python **3.14.6** geprüft.
Ein älterer HA-Stand ist nicht freigegeben. Docker / Home Assistant Container
benötigt kein Add-on und keinen zusätzlichen Dienst. Das private Protokollprofil
ist ausschließlich für den beobachteten EU-Host angelegt.

## HACS

HACS öffnen, Menü **Benutzerdefinierte Repositories**, Repository-URL
`https://github.com/passion-wave/HA_aqara_fp2`, Kategorie **Integration**.
Anschließend Aqara Presence Lab herunterladen und HA regulär neu starten.
Bei Auswahl einer Vorabversion in HACS die Beta-Anzeige aktivieren.

Die Oberfläche unter **Geräte & Dienste** bietet eine Offline-Vorschau und zeigt
den Status des Live-Protokolls. In dieser Beta bleibt die Live-Einrichtung
gesperrt, solange das Profil nicht nachweisbar validiert ist. Die Vorschau
führt keinen HTTP-Aufruf aus und legt keine normalen Sensoren an.

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

## Konfiguration nach künftiger Live-Freigabe

Die Architektur verwendet einen Entry pro bestätigtem EU-Konto und eine explizite
Geräteauswahl. Der Startwert für das Pollintervall beträgt 300 Sekunden, die
Untergrenze 60 Sekunden. Ein Refresh nutzt denselben Account-Limiter.
Eine neue Sitzung aktualisiert den bestehenden Entry; ein Kontowechsel wird
nicht als Reauth akzeptiert. Aktuell ist nur die Laborprobe für lokale Tests zugänglich.

## Diagnose

Zuerst Verbindungsstatus und Datenqualität betrachten. Rohwert `0` heißt ohne
Semantiknachweis nicht „Raum leer“. Alte `traitTime`-Werte werden nicht als neue
Messungen ausgegeben. Sensorwerte können `unknown` oder `unavailable` sein;
die Verbindungsdiagnose bleibt bei einem Transportfehler lesbar.

Keine Rohantworten, cURL-Kommandos oder HAR-Dateien in Issues hochladen.
Ein Supportbericht soll nur Versionen, Fehlerklasse und die bereinigte
Integrationsdiagnose enthalten. Bekannte Grenzen stehen im [Validierungsbericht](VALIDIERUNG.md).

## Update, Rollback und Entfernen

Vor einem Update Konfiguration einschließlich `.storage` sichern. Die erste Beta
verwendet Config-Entry-Schema 1; es gibt keine frühere produktive Datenmigration.
Unbekannte zukünftige Schemaversionen werden nicht heruntergestuft.

Für einen Rollback die frühere Integrationsversion wiederherstellen und neu starten.
Nur bei einer dokumentierten inkompatiblen Schemamigration zusätzlich das passende
Backup verwenden. Niemals HomeKit-Pairings, lokale Präsenzsensoren oder Automationen
löschen. Beim Entfernen ausschließlich den Aqara-Presence-Lab-Entry und danach
das HACS-Paket entfernen. HA verwaltet die Recorder-Historie nach eigener
Aufbewahrungsregel; diese Integration löscht keine Verlaufsdaten.

