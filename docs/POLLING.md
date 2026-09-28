# Priorisierte Abfragen

Ab 0.4.0b1 haben Status-/Vitaldaten und Einstellungen eigene Zeitpläne. Die bisherigen QLINK-Abfragen bleiben als getrennte Quelle bestehen.

| Option | Standard | Erlaubter Bereich | Bedeutung |
|---|---:|---:|---|
| Status-/Vitalintervall | 60 s | 10–3600 s | Ziel pro Gerät für die 81 Ressourcenfelder |
| Einstellungen | 3600 s | 900–86400 s | Ziel pro Gerät für die sieben Einstellungen |
| QLINK | 300 s | 60–3600 s | Gemeinsame Trait-Abfrage aller ausgewählten Geräte |
| Kontoabstand | 30 s | 30 / 15 / 10 / 5 s | Mindestabstand zwischen tatsächlichen HTTP-Anfragen |

Einstellbar unter **Einstellungen → Geräte & Dienste → Aqara Presence Lab → Konfigurieren**. Die Änderung lädt den Eintrag neu und erhält Entitätskennungen und Aktivierungen. Bei vielen Geräten kann der tatsächliche Rundlauf länger als das Zielintervall werden. Einstellungen, QLINK, Netzwerkdauer und Serverpausen brauchen ebenfalls Zeit; es gibt keine garantierte maximale Ende-zu-Ende-Latenz.

Beim Start kommen zunächst alle Statusgruppen, dann die Einstellungen. Im Dauerbetrieb werden fällige Statusgruppen bevorzugt; nach spätestens zwei Statusrunden erhält eine überfällige Einstellungsgruppe einen Platz. Alle Geräte und Endpunkte teilen denselben Kontolimiter; es gibt keine parallelen HTTP-Abfragen. Die Vitalgruppe enthält auch Präsenz-/Zonenfelder und Gerätemodus. Es werden keine Einstellungen geschrieben und keine Modi gewechselt.

## Fehlerverhalten

Kürzere Kontoabstände sind experimentell. Fehler setzen den effektiven Abstand auf mindestens 30 Sekunden zurück, ohne bestehende Wartezeiten zu verkürzen. HTTP- und Transportfehler behalten exponentiellen Backoff, Jitter und `Retry-After`. Eine bloße lokale Cooldown-Abweisung löst diese Rückstufung nicht aus. Erfolgreiche Antworten heben die Rückstufung nicht automatisch auf. Das gemeinsame Limit bleibt bei einem Integrationsreload erhalten; ein geändertes Abstandsprofil oder ein HA-Neustart setzt das konfigurierte Profil neu an.

Vor und nach einer Anmeldung gelten weiterhin mindestens 30 Sekunden. Ein fehlgeschlagener optionaler Ressourcenabruf löst keine eigenständige Login-Schleife aus. Ungültige Gruppen werden unverfügbar; Werte werden nicht durch Null ersetzt. Empfangsalter und Quellenqualität bleiben getrennt: häufige HTTP-Antworten beweisen keine aktuellen Radarmessungen.

## Begrenzter Geschwindigkeitstest

Die Administratoraktion `aqara_presence_lab.benchmark_polling` nimmt nur `entry_id` entgegen. Sie setzt eine gesunde, geladene Integration und eine vorhandene Sitzung voraus. Der einmalige Ablauf liest höchstens zehn Ressourcen-Gruppen, abwechselnd über die gewählten Geräte: drei mit 15, drei mit 10 und vier mit 5 Sekunden konfiguriertem Abstand. Bereits laufende Wartezeiten werden beim Stufenwechsel eingehalten; deshalb kann die erste Anfrage einer schnelleren Stufe noch den vorigen Abstand haben.

Während des Tests pausieren normale Zusatz- und QLINK-Abfragen. Beim ersten Fehler endet der Versuch. Anschließend wird das vorherige Profil wiederhergestellt, bei Fehlern oder Abbruch mit konservativem Mindestabstand. Entladen bricht den Versuch ab. Es gibt weder automatische Wiederholung noch neue Anmeldung durch den Test.

Die Integrationsdiagnose enthält unter `polling_probe` Abschlussstatus, Anzahl, tatsächliche Anfrageabstände, HTTP-Dauer, Wartezeit und Anzahl gelieferter/geänderter Felder. Sie enthält keine Messwertfolgen, Gerätekennungen oder Credentials. `request_gap_seconds` ist ein Abstand zwischen HTTP-Anfragen, keine Geräteerkennungslatenz. Ein erfolgreicher Kurztest bestätigt nur diese konkreten Anfragen, keine dauerhafte Freigabe eines Aqara-Limits.

## Live-Ergebnis dieser Installation

Am 28.09.2026 bestanden zehn von zehn begrenzten Testabfragen, einschließlich
dreier tatsächlich gemessener 5-s-Abstände. Die Antwortdauer lag bei 108–178 ms.
Danach wurde für die zwei FP2 ein Statusziel von 30 s je Gerät mit 10 s
Kontomindestabstand gewählt, bei stündlichen Einstellungen und QLINK alle 300 s.
Dies ist das lokale Betriebsprofil; neue Installationen behalten die konservativen
Standardwerte aus der Tabelle. Details, Rohstatistiken ohne Messwerte und Grenzen:
[Validierung](VALIDIERUNG.md#kontrollierter-live-test-am-28092026).
