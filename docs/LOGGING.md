# Logs und Diagnose

Die Integration protokolliert Zustandswechsel und technische Ergebnisse mit
einer festgelegten Feldauswahl. Konto, Passwort, Token, Benutzer- und Geräte-IDs,
Secret-Werte, Request-Header, signierte Bodies und freie Servernachrichten werden
nicht in Integrationslogs übernommen. Fehler aus Netzwerk- und Dateibibliotheken
werden als feste Fehlerklassen weitergegeben.

## Logstufen

- **Info:** Konto- und Geräteprüfung, bestätigte Sitzung und hergestellte Verbindung.
- **Warnung:** Abgelehnte Anmeldung, erforderliche Benutzeraktion, Serverpause, Verbindungsverlust oder Protokollproblem.
- **Debug:** Bereinigte technische Abläufe und Zähler; auch hier keine Credentials.

Für eine zeitlich begrenzte Fehlersuche:

```yaml
logger:
  default: warning
  logs:
    custom_components.aqara_presence_lab: debug
```

Bei vorhandenem `logger`-Abschnitt nur den Eintrag unter `logs` ergänzen.
Alternativ die Debug-Protokollierung der Integration in **Geräte & Dienste**
verwenden. Eine globale HTTP- oder Proxy-Aufzeichnung ist hierfür nicht nötig.

## Interpretation

| Ergebnis | Bedeutung und nächster Schritt |
|---|---|
| Anmeldung erfolgreich | Neue Sitzung erhalten; der Gerätezugriff wird zusätzlich geprüft. |
| `session_validated` | Kontoidentität und Gerätezugriff geprüft; während der Einrichtung erfolgt die Dateispeicherung erst mit der abschließenden Bestätigung. |
| Authentifizierung erforderlich | Zugangsdaten oder zusätzliche Bestätigung in der Einrichtung prüfen. |
| Rate-Limit | Gemeinsame Wartezeit abwarten; manuelle Abrufe umgehen diese nicht. |
| Verbindungsfehler | Netzwerk-/Serverstörung; gespeicherte Zugangsdaten bleiben erhalten. |
| API-/Signaturfehler | Protokoll überprüfen; unbekannte Codes lösen keine Login-Schleife aus. |
| Geräteantwort unvollständig | Auswahl und Verfügbarkeit der Geräte prüfen. |

Numerische Aqara-Anwendungscodes und beobachtete HTTP-Statuswerte dürfen im
bereinigten Bericht enthalten sein. Normale unveränderte Messwerte sollen das
Log nicht füllen. Für Support Integrationsdiagnose und einen relevanten
bereinigten Logausschnitt verwenden; Config-Entry-Rohdaten, Captures und
gespeicherte Sitzungen werden nicht exportiert.
