# Aqara Presence Lab
## Vollständige Implementierungsspezifikation für Codex

**Stand:** 26. September 2026 · **Spezifikation:** 1.0 · **Domain:** `aqara_presence_lab`  
**Ziel:** Home-Assistant-Custom-Integration für zusätzliche Aqara-Präsenzsensordaten aus der privaten Aqara-App-Schnittstelle.  
**Lieferstand dieses Projekts:** Implementierungsauftrag, pseudonymisierte Protokoll-Fixtures, Offline-Parser und offline prüfbarer Signaturkandidat. **Noch keine installierbare Home-Assistant-Integration und kein verifizierter Live-Client.**

---

## 0. Verbindlicher Arbeitsauftrag an Codex

Implementiere das in diesem Dokument beschriebene Projekt schrittweise. Beginne mit den vorhandenen Offline-Tests, dann mit dem unabhängigen API-Kern und erst anschließend mit der Home-Assistant-Anbindung. Unterscheide jederzeit zwischen beobachtetem Protokoll, extern belegtem Implementierungsansatz, Hypothese und erfolgreich am Zielendpunkt getesteter Funktion.

**Nicht verhandelbar:**

1. Keine persönlichen Zugangsdaten, Gerätekennungen oder Mitschnitte in Git, Logs, Fehlermeldungen oder Antworten eines KI-Werkzeugs übernehmen. Geheimnisse werden ausschließlich lokal eingegeben und verarbeitet.
2. Keine Signatur, Authentifizierungsfehlercodes, Refresh-Endpunkte oder Enum-Bedeutungen erfinden. Der unten dokumentierte Signaturalgorithmus ist ein fundierter Kandidat, aber am hier gefundenen Trait-Endpunkt noch nicht bestätigt.
3. Bestehende lokale HomeKit-Device-Präsenzsensoren und deren Automationen bleiben unverändert. Diese Integration ergänzt sie; sie ersetzt oder übernimmt keine Geräte.
4. Fehlende Werte sind nicht `0`, `false` oder `defaultValue`. Alte Cloudwerte sind nicht automatisch aktuelle Messwerte. `positionId` ist keine Personenkoordinate.
5. Kein Live-Polling, bis das jeweilige Protokollprofil bewusst getestet und freigegeben ist. Das vorhandene Starterprogramm sendet keinerlei Netzwerkverkehr.
6. Keine Konfigurationsänderungen an Aqara-Geräten, kein Moduswechsel und keine Schreib-Endpunkte im ersten Release. Ein Leseaufruf mit `needSubscribe=true` kann dennoch sitzungsbezogene Nebenwirkungen haben; deshalb ausdrücklich testen.

Ein offener Live-Gate blockiert nur den betroffenen produktiven Pfad. Parser, Benutzerführung, Testdoubles, Fehlerbehandlung und Integration mit simulierten Antworten können unabhängig davon fertiggestellt werden. Niemals einen erfolgreichen Mock-Test als erfolgreichen Gerätetest ausgeben.

## 1. Zielbild und Einordnung

### 1.1 Nutzungskontext

Der Nutzer betreibt Home Assistant im Container-/Docker-Umfeld. Aqara FP2 sind bereits über HomeKit Device angebunden; vorhandene lokale Präsenz- und Zoneninformationen sollen erhalten bleiben. Der zusätzliche Nutzen liegt insbesondere in der Untersuchung von Daten, die bislang nur in der Aqara-App sichtbar sind. Perspektivisch interessieren Personenpositionen, Personenanzahl und Schlafdaten.

Der hier übergebene Mitschnitt belegt zunächst **Geräteinformationen, Helligkeitswerte und mehrere rohe Zustandsfelder**. Er belegt noch keinen Zugriff auf Personenkoordinaten, Schlafphasen, Herzfrequenz oder Atemfrequenz. Diese Funktionen sind Erweiterungen mit eigenen Freigabekriterien, keine zugesicherte MVP-Funktion.

### 1.2 Architekturentscheidung

Primäres Ziel ist eine **native Custom Integration**, später über HACS installierbar. Kein Supervisor-Add-on, kein zwingender separater Container, kein eigener Cloud-Dienst und kein dauerhaft laufender Proxyman. Der API-Kern bleibt von Home Assistant unabhängig. Ein optionaler MQTT-Adapter kann später denselben Kern verwenden, gehört aber nicht zum ersten Lieferumfang.

HACS ist der spätere Verteilungsweg, nicht das Protokoll oder die Laufzeitumgebung. Die erforderliche Repository-Struktur liegt unter `custom_components/<domain>`; Veröffentlichung und Repository-Aufnahme sind separate Schritte. [S5]

```text
Bestehende Aqara-Geräte ── lokale HomeKit-Verbindung ── vorhandene HA-Entitäten
           │                                          unverändert
           └── Aqara-Cloud
                    │ HTTPS, privates App-Protokoll
                    ▼
           Aqara-API-Kern / AuthProvider / Signer
                    │ typisierte Beobachtungen + Datenqualität
                    ▼
           Home Assistant DataUpdateCoordinator
                    │
          zusätzliche Entitäten + Diagnose + Reparaturhinweise
```

Das ist **kein cloudfreier Zugriff**: Der beobachtete Host liegt in der Aqara-Cloud. Der Entwurf benötigt lediglich keine zusätzliche Cloud des Integrationsentwicklers.

### 1.3 Umfang nach Freigabestufe

| Stufe | Lieferumfang | Voraussetzung |
|---|---|---|
| Offline-Basis | Parser, Datenmodell, Test-Fixtures, Analysebericht, Signaturkandidat | Bereits teilweise im Starter vorhanden |
| Live-Probe | Kontrollierter Einzelabruf des belegten Endpunkts | Eigene lokale Zugangsdaten; ausdrücklicher Start |
| MVP | Einrichtung, Geräteauswahl, zuletzt gemeldete Helligkeit, rohe Diagnosewerte, Fehlerbehandlung | Wiederholbare gültige Abfragen, geprüftes Profil |
| Semantisch verifizierte Präsenz | Zusätzlicher Cloud-Präsenzsensor, standardmäßig deaktiviert | Beobachtete Wechsel und bestätigte Enum-/Aktualitätssemantik |
| Produktiver Komfort | Automatische Neuanmeldung mit Einwilligung, Reauth, Migration, HACS-Paket | Login am eigenen Konto und Wiederanlauf getestet |
| Erweiterungen | Schlaf, Personenpositionen, Anzahl, echte Push-Daten | Jeweils separater Mitschnitt und Vertragstest |

## 2. Evidenz: Was der Mitschnitt wirklich beweist

### 2.1 Beobachteter HTTP-Vertrag

```http
POST https://rpc-ger.aqara.com/app/v1.0/lumi/app/qlink/trait/read
Content-Type: application/json
Area: EU
Appid: 7be1984f0556276133336839
App-Version: 6.4.1
Token: <NUR_LOKAL>
Userid: <NUR_LOKAL>
Time: <EPOCH_MILLISEKUNDEN>
Nonce: <NONCE>
Sign: <SIGNATUR>
```

Weitere Header waren vorhanden, darunter `PhoneId`, `Clientid`, Mobilgeräte-/Push-Tokens, `Cookie`, Sprache und Geräteinformationen. Ihr Vorhandensein beweist nicht ihre Notwendigkeit. Der Header `Appid` ist im untersuchten externen Implementierungsansatz ebenfalls als EU-App-Konstante enthalten; er ist kein persönliches Zugangstoken. [S0, S1]

Requeststruktur:

```json
{
  "devices": [
    {
      "deviceId": "lumi1.000000000001",
      "traits": [
        {"path": "2.160.33000", "needSubscribe": true},
        {"path": "4.154.32989", "needSubscribe": true}
      ]
    }
  ],
  "needParam": true
}
```

Dieses kurze Beispiel erklärt ausschließlich die Struktur. Es ist kein byteidentischer Replay-Body. Der vollständige rekonstruierte Request steht im Anhang und in `fixtures/trait_read.request.json`.

Antwortstruktur:

```json
{
  "result": [
    {
      "deviceId": "lumi1.000000000001",
      "deviceModel": "lumi.motion.agl001",
      "positionId": "real2.0000000000000000001",
      "traits": []
    }
  ],
  "code": 0,
  "message": "Success",
  "msgDetails": "Success",
  "requestId": "REDACTED_REQUEST_ID"
}
```

Im Chat wurden keine vollständigen Response-HTTP-Header übergeben. Insbesondere sind HTTP-Status, serverseitiger `Date`-Header und Rate-Limit-Header nicht dokumentiert. `code=0` ist im übergebenen JSON beobachtet; andere Aqara-Codes dieses Endpunkts sind unbekannt.

### 2.2 Zwei Geräte; Reihenfolge nicht identisch

Die pseudonymisierten Fixtures verwenden Sensor A für das Gerät mit **9 lx** und Sensor B für das Gerät mit **110 lx**. Beide melden `deviceModel=lumi.motion.agl001`. Sensor B enthält zusätzliche Metadaten zur Sturzüberwachung.

| Beobachtung | Sensor A | Sensor B |
|---|---:|---:|
| Trait-Einträge im Request einschließlich Wiederholungen | 37 | 31 |
| Unterschiedliche angefragte Pfade | 25 | 31 |
| Zurückgegebene Trait-Einträge | 20 | 25 |
| Helligkeit, als JSON-String | `"9"` | `"110"` |
| Präsenzkandidat `2.160.33000` | `"0"` | `"0"` |
| Gerätestatuskandidat `0.128.32901` | Zahl `1` | Zahl `1` |
| Feld `2.160.33044` | Kein `value` | Zahl `3731446` |

Im Request steht B vor A, in der Antwort A vor B. **Nie mit Array-Indizes zuordnen.** Die Zuordnung erfolgt ausschließlich über `deviceId`, danach über `path`.

### 2.3 Formatprobleme der Chatkopie

Die Chatkopie enthält HTML-Leerzeichen (`&#x20;`), Darstellungseffekte bei Backslashes/Unterstrichen und eine doppelt eingefügte Antwort mit einem unvollständigen ersten Objekt. Für das Projekt wurde daraus genau **eine gültige, manuell rekonstruierte Fixture** erstellt.

Diese Fixture ist absichtlich nicht byteidentisch zur Originalantwort oder zum ursprünglichen Request. Namen, Geräte-/Raumkennungen und Request-ID sind ersetzt. Zeitstempel und Werttypen bleiben erhalten. Die Fixture ist daher **pseudonymisiert und für Parser-Tests geeignet, aber kein Original-Signatur-Testvektor**.

Ein späterer Importassistent darf Formatprobleme erklären und eine Vorschau anbieten. Er darf niemals stillschweigend signierte Requests verändern. Der Live-Parser akzeptiert genau ein vollständiges JSON-Objekt; er repariert weder HTML noch abgeschnittene oder aneinandergehängte Antworten.

### 2.4 Zeitstempel richtig lesen

Der übergebene Request-Header `Time=1790355356562` entspricht **25. September 2026, 18:55:56.562 Uhr Europe/Berlin**. Das ist der Zeitwert des Clients, kein unabhängig belegter serverseitiger Empfangszeitpunkt.

| Feld | Epoch-Millisekunden | Europe/Berlin |
|---|---:|---|
| Helligkeit Sensor A | 1790354656410 | 25.09.2026, 18:44:16.410 |
| Helligkeit Sensor B | 1790355274126 | 25.09.2026, 18:54:34.126 |
| Präsenzkandidat Sensor A | 1737821236919 | 25.01.2025, 17:07:16.919 |
| Präsenzkandidat Sensor B | 1790332365586 | 25.09.2026, 12:32:45.586 |
| Sturzstatuskandidat Sensor B | 1684265219105 | 16.05.2023, 21:26:59.105 |

**Interpretation:** Ein sehr alter `traitTime` kann auf einen alten Cachewert, ein inaktives Merkmal oder den letzten Zustandswechsel verweisen. Welche Bedeutung zutrifft, ist noch offen. Ein alter Zeitstempel beweist weder „Sensor kaputt“ noch „Raum seitdem leer“. Ein frischer HTTP-Abruf beweist umgekehrt keine frische physische Messung.

## 3. Vollständiger Trait-Katalog

Evidenzstufen: **beobachtet** bedeutet, dass Wertform/Beschriftung aus dem Mitschnitt hervorgeht. **Kandidat** bedeutet plausible Semantik ohne ausreichenden Wechseltest. **Unbekannt** darf nicht mit frei erfundenen Bedeutungen ergänzt werden. Einheiten und `propertyId` sind Zusatzmetadaten, keine austauschbaren Endpunkte.

### 3.1 Messwerte und relevante Zustandskandidaten

| Trait-Pfad | Beobachtung | `propertyId` | Entscheidung für MVP |
|---|---|---|---|
| `4.154.32989` | Helligkeit; `unit=lux`, Werte `"9"`/`"110"` | `0.4.85` | Numerisch dekodieren; HA-Einheit `lx`; Aktualität separat |
| `2.160.33000` | Binäres Enum; beide Werte `"0"`; Gruppe Präsenz | `3.51.85` | `presence_raw`; 0/1-Bedeutung erst testen |
| `0.128.32901` | Binäres Enum; Zahl `1` | `8.0.2045` | `device_status_raw`; nicht als bewiesen online behandeln |
| `2.160.33001` | Enum `0,1,2,3`; kein Wert | nicht enthalten | Keine Bewegungsrichtung/Ereignisse erfinden |
| `2.160.33044` | Nur B liefert `3731446`; keine Einheit | nicht enthalten | Rohe Zahl; keine Anwesenheitsdauer ableiten |
| `2.160.33045` | Einheit `ms`; 0 bis 604800000; kein Wert | nicht enthalten | Unbekanntes Zeitfeld; nie aus Nachbarfeld berechnen |
| `5.168.33019` | Enum `0,1,2`; `"0"`; Sturz-Gruppe | `4.31.85` | Nur rohe Diagnose; keine Warnautomation |
| `0.129.33013` | JSON-Listen als Strings, z. B. `"[4,6]"` | `14.49.85` | Struktur dekodieren, Codebedeutung unbekannt |

Die `step=10.0`-Angabe des Lux-Traits darf **keine Rundung auf 10er-Schritte** verursachen. Der beobachtete Wert `9` muss unverändert als 9 lx erhalten bleiben.

### 3.2 Geräte- und Gruppenmetadaten

| Trait-Pfad | Beobachtung | Umgang |
|---|---|---|
| `0.130.32913` | Gerätename, `8.0.8101` | Als vorgeschlagenen Anzeigenamen verwenden |
| `0.130.33016` | Raumname, `8.0.8102` | Diagnose/Vorschlag; HA-Bereich nicht automatisch ändern |
| `0.130.32914` | Referenz entspricht dem obersten `positionId`, `8.0.8108` | Undurchsichtige Ortsreferenz; keine X-/Y-Position |
| `0.129.32906` | Wert `"1"`, Enum und Default | Unbekannte Geräte-Metadaten |
| `0.129.32907` | Wert `"31"`, Default | Unbekannte Geräte-Metadaten; nicht als Bitmaske interpretieren |
| `2.130.32913` | „Anwesenheitssensor“/„Occupancy Sensor“ | Gruppenbeschreibung |
| `2.130.32915` | Nur Default `"1"` | Keine Messung |
| `2.130.32919` | `presence_detector` | Typbeschreibung der Gruppe |
| `2.130.33012` | Wert `"1"` | Unbekanntes Gruppenflag, keine Anwesenheit |
| `4.130.32913` | „Beleuchtungsstärke“/„Illuminance“ | Gruppenbeschreibung |
| `4.130.32915` | Nur Default `"1"` | Keine Messung |
| `4.130.32919` | `illumination` | Typbeschreibung |
| `4.130.33012` | Wert `"1"` | Unbekanntes Gruppenflag |
| `5.130.32913` | „Sturzüberwachung“ | Gruppenbeschreibung bei B |
| `5.130.32915` | Nur Default `"1"` | Keine Messung |
| `5.130.32919` | `fall_down` | Typbeschreibung bei B |
| `5.130.33012` | Wert `"1"` | Unbekanntes Gruppenflag |

### 3.3 Angefragt, aber in dieser Antwort nicht enthalten

`0.129.32909`, `0.129.32912`, `1.147.32969`, `2.130.33108`, `4.130.33108`, `5.130.33108`.

Fehlen ist nicht gleich „dauerhaft nicht unterstützt“. Beobachtung als `requested_not_returned` speichern. Ein bereits angelegtes Gerät oder eine Entität darf wegen einer einzelnen unvollständigen Antwort nicht gelöscht werden. Die Maschinenrepräsentation aller 31 unterschiedlichen Pfade befindet sich in `config/trait_catalog.json`.

## 4. Datenmodell und Parser-Vertrag

### 4.1 Typisierte Ebenen

Implementiere mindestens `AccountIdentity`, `DeviceSelection`, `RawTrait`, `TraitObservation`, `DeviceSnapshot`, `AccountSnapshot`, `TransportHealth` und `ProtocolProfile`. Home-Assistant-Klassen dürfen im API-Kern nicht importiert werden.

```python
@dataclass(frozen=True)
class TraitObservation:
    path: str
    has_value: bool
    raw_value: JsonValue
    normalized_value: JsonValue | None
    default_value: JsonValue | None
    source_time_ms: int | None
    received_at_utc: datetime
    property_ids: tuple[str, ...]
    semantic_status: str
    freshness_status: str
    value_status: str
```

Dies ist ein **Zielvertrag**, kein Hinweis darauf, dass der Starter bereits diese vollständige Laufzeitstruktur implementiert. Der vorhandene Offline-Parser deckt einen bewusst kleineren Teil ab.

### 4.2 Wertzustände strikt trennen

| Eingabe | Interner Zustand | HA-Konsequenz |
|---|---|---|
| `value` fehlt | `missing` | Keine Ersatzmessung aus Default |
| `value: null` | `null` | Unbekannt, sofern Profil nichts anderes belegt |
| `value: "0"` | `present` | Rohwert 0; keine Python-String-Truthiness |
| `value: 0` | `present` | Zahl 0 |
| `value: false` | `present` | Boolean; nicht still als Zahl dekodieren |
| `value: ""` | `present` | Leerer String; je Decoder gültig oder ungültig |
| Nicht numerischer Lux-Wert | `invalid` | Kein NaN/Infinity und kein „0 lx“ |

`defaultValue` beschreibt eine Vorgabe, keinen aktuellen Zustand. `enums` ist teilweise ein JSON-kodierter String: ausschließlich mit einem JSON-Decoder auswerten, niemals mit `eval`, `literal_eval` als generellem Ersatz oder ausführbaren Templates.

### 4.3 Strenge Eingangsvalidierung

Projektseitige Schutzlimits, nicht dokumentierte Aqara-Limits: 2 MiB entpackte Antwort, 100 Geräte, 200 Traits pro Gerät. Der HTTP-Client begrenzt den tatsächlich gelesenen/dekomprimierten Stream, nicht nur `Content-Length`. Für den ersten Nutzungsfall werden nur die zwei ausgewählten Geräte abgefragt.

Doppelte JSON-Schlüssel, ungültige Top-Level-Struktur, nicht endliche JSON-Zahlen und abgeschnittenes JSON ablehnen. Identische doppelte Traits können verlustfrei zusammengefasst werden; widersprüchliche Doppelwerte werden isoliert gemeldet, nicht per „letzter gewinnt“ geraten. Im Starter führt ein Konflikt noch zum Abbruch der gesamten Offline-Analyse; im späteren Client ist gerätebezogene Fehlerisolation vorzuziehen.

Unbekannte Felder begrenzt im internen Rohmodell erhalten, aber nicht ungefiltert als HA-Attribute oder Diagnose exportieren. Geräte und Traits anhand ihrer IDs zuordnen. Strings mit Unicode unverändert behandeln. Große Integer-Kennungen nicht in Gleitkommazahlen umwandeln.

### 4.4 Aktualisierung und Teilantworten

Metadaten, letzter beobachteter Wert und aktuelles Ergebnis sind getrennte Speicherplätze. Wenn ein erfolgreich abgefragter Trait ausdrücklich ohne Wert zurückkommt, darf ein früherer Wert nicht als neue Beobachtung gelten. Ein historischer Wert kann für Diagnosen erhalten bleiben, jedoch mit seinem ursprünglichen Beobachtungszeitpunkt.

Fehlt ein Gerät in der Antwort, erhöht sich nur dessen Fehlerstatus. Andere korrekt gelieferte Geräte bleiben nutzbar. Eine Antwort kann zusätzliche nicht ausgewählte Geräte enthalten: diese nicht automatisch registrieren oder veröffentlichen. Das schützt auch gegen unbeabsichtigt zu breite Account-Abfragen.

## 5. Authentifizierung und Request-Signierung

### 5.1 Neuer Recherchebefund: ein konkreter Kandidat

Die untersuchte SleepRadar-Datei `aqara_fp2_sleep/aqara_fp2_sleep_poller.py` implementiert eine EU-Konfiguration mit **demselben Host und derselben App-ID wie im Nutzermitschnitt**. Sie enthält einen Signaturaufbau und einen Login. Der gelesene Git-Blob hat SHA `b48a4417deebd04cf4e6b3eb3d918300e6081d25`. Das ist eine Datei-/Blob-Referenz, kein Release- oder Commit-Tag. [S1]

Damit muss Codex nicht blind nach einem Signaturalgorithmus suchen. Dennoch gilt: Die externe Implementierung verwendet einen anderen Datenendpunkt (`/app/v1.0/lumi/res/query`). **Übertragbarkeit auf `/app/v1.0/lumi/app/qlink/trait/read` ist zu testen, nicht vorauszusetzen.** Im vom Nutzer bereitgestellten Mitschnitt ist `Token` maskiert; außerdem fehlen die verlässlich originalen Body-Bytes. Die enthaltene `Sign`-Zeichenfolge kann deshalb hier nicht gegen den Kandidaten verifiziert werden.

### 5.2 Kandidat für die Signatur

Das aus der Quelle abgeleitete Profil heißt im Projekt `sleepradar_eu_candidate_v1`. Für dieses Profil lautet die Konstruktion:

```text
Material mit Token:
Appid=<app_id>&Nonce=<nonce>&Time=<epoch_ms>&Token=<token>&<EXAKTER_BODY>&<app_key>

Material ohne Token, beispielsweise beim Login:
Appid=<app_id>&Nonce=<nonce>&Time=<epoch_ms>&<EXAKTER_BODY>&<app_key>

Sign = lowercase_hex(MD5(UTF8(Material)))
```

Der optionale Token-Teil entfällt vollständig, wenn kein Token vorhanden ist. Ein leerer Body wird im externen Kandidaten nicht als zusätzliches leeres Segment angehängt. Der Body ist keine neu sortierte Schlüssel-Liste, sondern der tatsächliche JSON-Text. Der externe Kandidat verwendet einen frisch erzeugten Nonce und Epoch-Millisekunden. [S1]

`src/aqara_presence_lab/signing_candidate.py` setzt diese Konstruktion **ohne Netzwerkzugriff** um und nimmt den Body bereits als Bytes entgegen. `fixtures/signing.synthetic.json` enthält einen ausschließlich synthetischen Regressionstest mit dem erwarteten Digest `55e1c74bbca214902ece1aa35bcc1046`.

**Dieser Digest ist kein Beweis für die Aqara-Kompatibilität.** Er prüft, dass die selbst beschriebene Konstruktion deterministisch umgesetzt ist. Die Konstante `QLINK_LIVE_VERIFIED=False` im Starter ist bewusst keine Freigabe für produktives Polling.

Der herstellerspezifische App-Key und der öffentliche RSA-Schlüssel sind in der externen Quelle enthalten. Codex soll sie anhand der referenzierten Datei prüfen und in ein nachvollziehbar versioniertes Protokollprofil aufnehmen, nicht persönliche Zugangsdaten aus dem Chat übernehmen. Vor Übernahme von Quellcode ist dessen Lizenz am tatsächlich verwendeten Stand zu prüfen. Im Starter sind weder Hersteller-Keymaterial noch persönliche Credentials enthalten.

### 5.3 Bytes zuerst, Signatur danach, dieselben Bytes senden

Der produktive Client muss genau einmal serialisieren:

```text
Python-Datenstruktur
    → festgelegte JSON-Serialisierung
    → UTF-8 body_bytes
    → Signatur über body_bytes
    → HTTP POST mit genau body_bytes
```

Nach Signierung darf nicht über `json=payload` erneut serialisiert werden. Verwende beim gewählten HTTP-Client den Body-Bytes-Parameter. Whitespace, Unicode-Escaping, Reihenfolge, Zeilenende und Boolean-Schreibweise können die Signatur beeinflussen. Nicht nachträglich deduplizieren, sortieren oder `needSubscribe` ändern.

Bei einem **neuen** Request sind andere Whitespaces als im Original erlaubt, sofern die Signatur zu exakt diesen tatsächlich gesendeten Bytes passt und das Protokollprofil dies zulässt. Für einen **Signaturvergleich mit einem Capture** sind dagegen die Originalbytes nötig. `Content-Length`, `Host` und Connection-Header berechnet bzw. verwaltet die HTTP-Bibliothek; den alten Wert `3112` niemals fest übernehmen.

### 5.4 Login-Kandidat aus der externen Implementierung

Extern belegter, am Nutzerkonto noch ungetesteter Weg: [S1]

```http
POST /app/v1.0/lumi/user/login
```

```json
{
  "account": "<AQARA-APP-ACCOUNT_NUR_LOKAL>",
  "encryptType": 2,
  "password": "<BASE64_RSA_CHIFFRAT>"
}
```

Der externe Code bildet zunächst den MD5-Hexdigest des UTF-8-Passworts, verschlüsselt dessen ASCII-/UTF-8-Text mit dem veröffentlichten RSA-Public-Key und PKCS#1-v1.5-Verschlüsselung und kodiert das Ergebnis mit Base64. Anschließend wird auch der Login-Request signiert, noch ohne Sitzungstoken. Bei erfolgreicher Antwort liest er `result.token` und `result.userId`.

Diese Altprotokoll-Konstruktion ist **keine Empfehlung für eigene Passwortspeicherung**. Niemals das Passwort oder den MD5-Wert als Ersatzgeheimnis veröffentlichen. Für RSA eine etablierte Kryptografie-Bibliothek verwenden, keine selbst geschriebene RSA-Implementierung. Kryptografieabhängigkeit im späteren HA-Manifest erst nach Prüfung der unterstützten HA-/Python-Version pinnen.

Ein separat dokumentierter Refresh-Token-Endpunkt ist damit **nicht** nachgewiesen. Automatische Erneuerung bedeutet zunächst einen erneuten Login, nicht einen erfundenen Refresh-Aufruf. MFA, CAPTCHA, föderierte Konten und abweichende Authentifizierung können diesen Weg verhindern; dann kontrolliert in den manuellen Reauth-Pfad wechseln.

### 5.5 Credential-Modi und klare Einwilligung

**Modus A – vorhandene Sitzung:** Token und Benutzerkennung lokal importieren. Kein Passwort erforderlich. Bei Ablauf erneute Sitzung importieren. Geeignet für den ersten kontrollierten Machbarkeitstest, aber kein Versprechen eines wartungsfreien Betriebs.

**Modus B – automatische Neuanmeldung:** Erst nach erfolgreichem Login-Profiltest anbieten. Konto und Passwort lokal speichern, ausschließlich nach ausdrücklicher Einwilligung. Die Oberfläche erklärt, dass Wiederanmeldung für dieses private Protokoll ein gespeichertes Kontogeheimnis benötigt. Kein ungetesteter „Mit Aqara verbinden“-OAuth-Knopf.

Falls ein Konto nur über einen Loginweg nutzbar ist, für den kein verifiziertes Profil existiert, steht allein Modus A zur Verfügung. Der Assistent darf weder Passwörter erraten noch Schutzprüfungen umgehen. Das Produkt darf diesen Zustand nicht als abgeschlossene automatische Authentifizierung darstellen.

### 5.6 Protokollprofil und Freigabe

```text
ProtocolProfile
  id, version, source_reference
  allowed_host = rpc-ger.aqara.com
  area = EU
  app_id
  signing_strategy
  login_strategy | unsupported
  header_policy
  body_serialization_policy
  trait_read_path
  subscribe_policy: captured_true | validated_false | unknown
  error_map: only evidenced application codes
  validation_state: candidate | signature_matched | endpoint_validated
  tested_app_version, tested_at, evidence_refs
```

Account-spezifische Live-Nachweise sind nicht auf andere Konten übertragbar. Ein lokaler Validierungsbericht enthält nur Ergebnis, Profilversion, Status und bereinigte Metadaten, keine signierten Request-Bytes und keine Tokens. Eine manuell gesetzte Boolesche Variable ohne Testbeleg ist keine technische Freigabe.

### 5.7 Zustandsmaschine für die Anmeldung

```text
UNCONFIGURED → CREDENTIALS_ENTERED → PROBING
PROBING → READY | AUTH_ACTION_REQUIRED | PROTOCOL_UNSUPPORTED | TRANSIENT_FAILURE
READY → RETRY_WAIT                         bei Netzwerk/Rate Limit
READY → REAUTHENTICATING                   bei belegt abgelaufener Sitzung + Einwilligung
REAUTHENTICATING → READY                   nach gültigem Login und Read-Probe
REAUTHENTICATING → AUTH_ACTION_REQUIRED    bei Ablehnung oder notwendiger Nutzerinteraktion
READY → AUTH_ACTION_REQUIRED              bei ungültiger Sitzung ohne Auto-Login
```

Alle parallelen Anforderungen teilen denselben Login-Lock. Maximal ein automatischer Neuanmeldeversuch je bestätigtem Authentifizierungsfehler, danach gegebenenfalls Benutzeraktion statt Endlosschleife. Netzwerkfehler führen nicht zur Löschung gültiger Credentials. Ein gültiges neues Token wird erst nach verifiziertem Konto-/Leseergebnis atomar übernommen.

Bei Tokenimport die Benutzerkennung aus einem serverseitig belegten Zusammenhang validieren. Ein erfolgreiches Login kann eine Nutzerkennung liefern; der Trait-Endpunkt allein beweist nicht zwingend die Bindung eines beliebigen eingegebenen `Userid`-Headers. Ohne belastbaren Identitätsnachweis keine stille Migration zu einem anderen Konto. Bestehende Geräteauswahl muss zur erfolgreichen Sitzung passen.

## 6. Live-Validierungsplan: klare Gates statt Bauchgefühl

### G0 – Offline-Datenvertrag

Die beigefügten Fixtures werden korrekt geparst; alle Prüfungen für fehlende Werte, Zeiten und umgekehrte Gerätereihenfolge sind grün. Kein Netzwerk. Bereits damit dürfen Parser und UI mit Testdaten entwickelt werden.

### G1 – Signaturabgleich ohne Request

Lokal einen frischen Proxyman-Export des eigenen Requests mit unveränderten Body-Bytes einlesen. Token und Signatur verbleiben auf dem Rechner. Kandidat aus Abschnitt 5 berechnen und konstantzeitlich mit der Capture-Signatur vergleichen. Der Bericht lautet ausschließlich „passt“ oder „passt nicht“, mit Profilversion. Keine Signaturbasis oder Credentials ausgeben.

Ein Fehlschlag kann am Profil, an Body-Rekonstruktion, Schlüsselstand oder Header-Regeln liegen. Er ist kein Beweis für ein falsches Passwort. Keine zufälligen Signaturalgorithmen oder massenhaften Varianten gegen den Server ausprobieren.

### G2 – einzelne autorisierte Leseprobe

Bei explizitem Start maximal einen kontrollierten Request senden. Wiederholungen nur innerhalb des dokumentierten Versuchslimits. Zunächst die beobachtete Pfadauswahl und `needParam=true` beibehalten. Wird ein bereits verbrauchter Nonce abgelehnt, ist das nicht ungewöhnlich genug, um daraus die Unbrauchbarkeit des Kandidaten abzuleiten; einen **neu signierten** Request mit frischer Zeit/Nonce testen, sobald G1 erfüllt ist.

Angeforderte und gelieferte IDs abgleichen, Schema prüfen, Statuswerte protokollieren. Niemals die alten Chatwerte als Live-Antwort einsetzen. Eine Minimalabfrage ist eine eigene Versuchsvariante und muss nach Änderung neu signiert werden.

### G3 – unabhängig von App und Proxy

Nach dem erfolgreichen Einzelabruf Aqara-App schließen und Proxyman aus dem Datenpfad entfernen. Nochmals kontrolliert neu signierte Requests vom späteren Home-Assistant-Host ausführen. Geänderte Beleuchtung und tatsächliche Anwesenheitswechsel als unabhängige Beobachtung notieren. Ein weiterhin erfolgreicher Abruf ohne Werteänderung reicht nicht als Frischebeweis.

### G4 – Semantik der Präsenz

Je Gerät mindestens drei vollständige Zyklen „leer → betreten → still anwesend → verlassen“ dokumentieren. Aqara-App, vorhandene lokale HomeKit-Zone und Cloud-Rohwert mit Zeitstempeln gegenüberstellen. Hysterese, Nachlauf, Verzögerung und aktivierter Gerätemodus festhalten. Nicht nur Bewegung testen: Stillanwesenheit ist relevant.

Erst wenn 0/1-Zuordnung, Aktualisierung und Geräte-/Modusbezug eindeutig sind, einen semantischen Cloud-Präsenzsensor aktivieren. Die Beobachtung eines einzelnen Rohwerts `0` genügt nicht.

### G5 – Wiederanmeldung und Robustheit

Absichtlich eine lokal gespeicherte Test-Sitzung verwerfen bzw. eine reguläre Abmeldung nutzen, ohne das Konto zu sperren. Erfolgreiche manuelle Wiederanmeldung und gegebenenfalls automatische Neuanmeldung prüfen. Tokenwechsel darf keine neuen HA-Entitäten erzeugen. Konto-Wechsel muss erkannt werden. Einen echten Tokenablauf kann man nicht durch einen erfundenen Mock-Fehler als live getestet ersetzen.

### G6 – Produktionsfreigabe

Mindestens ein 24-stündiger Beobachtungslauf mit konservativem Intervall, einem HA-Neustart, einem temporären Netzwerkfehler und dokumentierter Datenqualitätsprüfung. Anschließend Statusbericht mit getesteten und nicht getesteten Funktionen erstellen. 24 Stunden sind ein projektspezifisches Abnahmekriterium, keine Garantie für zukünftige API-Stabilität.

### Versuchsbudget

Für manuell gestartete Proben höchstens zehn Requests pro Untersuchungsschritt; standardmäßig mindestens 30 Sekunden Abstand. Produktions-Polling zunächst 300 Sekunden pro Account-Batch. Diese Grenzen sind konservative Projektentscheidungen, **keine von Aqara bestätigten API-Limits**. Bei Ablehnung/Rate Limit sofort langsamer werden und nicht auf andere Regionen ausweichen.

## 7. HTTP-Client und Subscription-Frage

Ein `AsyncAqaraClient` erhält eine asynchrone HTTP-Session, einen `AuthProvider`, `Signer`, Clock und Rate-Limiter per Dependency Injection. Er bietet `async_read_traits(device_ids, profile)`, `async_validate_credentials()` und optional `async_login()`. `async_close()` schließt nur Ressourcen, die der Client selbst erzeugt hat.

Für Home Assistant eine vom Framework vorgesehene Session verwenden; keinen synchronen `requests`-/`urllib`-Aufruf im Eventloop. Netzwerk-I/O gehört in den Coordinator, nicht in Entity-Properties. [S2, S7]

**Transportregeln:** HTTPS mit regulärer Zertifikatsprüfung; fester EU-Host aus Allowlist; keine beliebigen Import-URLs, keine Redirects mit Credentials; keine Übernahme fremder Proxy-Einstellungen aus einem Capture. Verbindungs- und Gesamt-Timeout, begrenzte Antwortgröße, Cancellation-Propagation. POST-Pfad auf die freigegebenen Lese-/Login-Endpunkte beschränken.

### `needSubscribe=true` ist kein Push-Beweis

Der Mitschnitt enthält dieses Flag sowohl im Request als auch in Trait-Antworten. Daraus folgen weder WebSocket-URL noch MQTT-Topic, RocketMQ-Zugang oder ein automatisch eingerichteter Push-Kanal. Das Flag könnte eine sitzungsbezogene Subscription, eine Datenanforderung oder nur Metadaten betreffen.

Im ersten kontrollierten Test wird die Capture-Semantik beibehalten. Danach ist `needSubscribe=false` eine separat signierte und protokollierte Versuchsvariante. Ohne Vergleich darf Codex den Wert weder automatisch umstellen noch dauerhaft `true` mit hoher Frequenz pollen. Bleibt unklar, ob wiederholte Reads zusätzliche Subscriptions erzeugen, kein produktiver Dauerbetrieb unter diesem Profil. Später nachgewiesener Push bekommt einen eigenen Adapter mit Reconnect und vollständigem Unsubscribe beim Entladen.

## 8. Aktualität, Verfügbarkeit und Messqualität

### 8.1 Vier voneinander unabhängige Zeiten

`requested_at` beschreibt den Requeststart. `received_at` beschreibt den lokalen Antwortempfang. `traitTime` ist der rohe Quellenzeitstempel mit zunächst unbekannter Semantik. `last_value_change_observed_at` beschreibt die erste lokal beobachtete Änderung des Wertes. Keine dieser Zeiten darf still als andere ausgegeben werden.

Timeouts und Altersgrenzen für Empfangsausfälle verwenden eine monotone Uhr. Exportierte Zeiten sind UTC mit Zeitzone. Europe/Berlin ist lediglich die Darstellung. Bei einem zukünftigen Quellenzeitstempel nicht auf „frisch“ schließen: `clock_anomaly` melden und den Rohwert erhalten.

### 8.2 Datenqualitätszustände

`unverified`, `reported`, `current_validated`, `missing`, `invalid`, `transport_unavailable`, `stale_confirmed`, `clock_anomaly`.

`reported` bedeutet: gültiger Wert aus der letzten Cloudantwort, Aktualität als physischer Messwert nicht garantiert. `current_validated` darf nur ein Profil mit belegter Zeit-/Zustandssemantik liefern. Ein unveränderter Wert mit altem Änderungszeitpunkt kann weiterhin gültig sein; ein alter Messzeitpunkt kann veraltet sein. Diese Unterscheidung ist pro Trait/Modus festzulegen.

Für MVP keine starre „alle `traitTime` älter als fünf Minuten verwerfen“-Regel. Ebenso wenig jeden erfolgreichen HTTP-Abruf als Aktualisierung des Messzeitpunkts behandeln. Bei ungeklärter Semantik Helligkeit ausdrücklich als „zuletzt gemeldet“ bezeichnen und Präsenzinterpretation unterdrücken.

### 8.3 Fehlende und nicht erreichbare Geräte

Ein erkannter Transportausfall setzt die betroffenen Messentitäten auf `unavailable`; eine erfolgreiche Antwort ohne aktuellen Wert ergibt `unknown` bzw. eine qualitätsbedingt nicht verfügbare Live-Entität. Verbindungsdiagnose bleibt lesbar, gerade wenn die Messentitäten nicht verfügbar sind.

Der produktive Coordinator benötigt eine vom Erfolg weiterer Requests unabhängige Verfügbarkeitsprüfung: Ein Timer muss ausstehende/überalterte Empfangszustände markieren können. Dieser Timer aktualisiert nur lokale Qualität und startet keinen zusätzlichen HTTP-Request. Bei Entladen alle Timer entfernen.

Ein später verifiziertes Offline-Flag wird gerätespezifisch berücksichtigt. Bis dahin darf `0.128.32901=1` keine als bewiesen dargestellte Online-Anzeige erzeugen. Nach Neustart keine gespeicherten Präsenzwerte als aktuelle Zustände wiederherstellen; höchstens klar gekennzeichnete historische Diagnose.

## 9. Polling, Last und Wiederholungsstrategie

Ein Coordinator pro Konto, ein gemeinsamer Batch für die ausgewählten Geräte. Keine Anfrage pro Entität. Home Assistants `DataUpdateCoordinator` ist für gemeinsame API-Abrufe mehrerer Entitäten vorgesehen. Das spätere Profil wird als `cloud_polling` deklariert. [S2, S6]

| Einstellung | Projektdefault | Begründung |
|---|---:|---|
| Pollintervall | 300 Sekunden | Konservative Ergänzung zur bestehenden lokalen Präsenz |
| Minimal einstellbar nach Validierung | 60 Sekunden | Kein Cloud-Echtzeitversprechen |
| Parallele Reads pro Account | 1 | Vermeidet konkurrierende Sitzungen/Last |
| Manueller Refresh | Gemeinsamer 30-Sekunden-Cooldown | Coalescing mit laufendem/nächstem Poll |
| Connect-Timeout | 10 Sekunden | Begrenztes Warten |
| Gesamt-Timeout | 20 Sekunden | Verhindert hängenden Coordinator |
| Transiente Wiederholungen je Aktion | Maximal 2 zusätzlich | Danach normaler Backoff statt Schleife |
| Backoff | 60, 120, 240 … bis 3600 Sekunden mit Jitter | Konservativ, sofern Server nicht länger vorgibt |

300 Sekunden ergeben rechnerisch höchstens 288 reguläre Poll-Batches am Tag; 60 Sekunden 1440. Diese Zahlen ignorieren Einrichtung, Retries und manuelle Abrufe und sind keine zugesicherte Aqara-Quote.

`Retry-After` als Sekunden oder HTTP-Datum berücksichtigen. Wiederholungen, automatische Neuanmeldung und manuelle Aktionen teilen denselben Rate-Limiter. Im Retry-Wait keine zusätzlichen Poll-Timer aktiv lassen. Aufeinanderfolgende gleiche Fehler werden im Log zusammengefasst; Wiederherstellung einmal melden.

Ein Profil ohne bestätigtes Polling-/Subscriptionverhalten verbleibt im Probenmodus. Die Integration darf eine unklare Read-Semantik nicht durch schnelleres Polling „lösen“. Für schnelle Lichtsteuerung weiter die bestehende lokale HomeKit-Präsenz verwenden.

## 10. Home-Assistant-Integration

### 10.1 Geplante Struktur – noch nicht im Starter implementiert

```text
custom_components/aqara_presence_lab/
  __init__.py
  manifest.json
  const.py
  config_flow.py
  coordinator.py
  entity.py
  sensor.py
  binary_sensor.py
  button.py
  diagnostics.py
  repairs.py
  services.yaml              # nur falls ein expliziter Diagnose-Service nötig ist
  strings.json
  translations/de.json
  translations/en.json
  api/
    client.py
    auth.py
    signing.py
    profiles.py
    models.py
    parsing.py
    freshness.py
    errors.py
    redaction.py
```

Ein kompakter interner API-Kern ist für das erste Release ausreichend. Spätere Auslagerung in ein eigenes Paket ist möglich, aber keine Voraussetzung. Vermeide zwei voneinander abweichende Parser im Labor und in der Integration; gemeinsame Regeln und Vertragstests verwenden.

### 10.2 Manifest

`domain=aqara_presence_lab`, `name=Aqara Presence Lab`, `config_flow=true`, `iot_class=cloud_polling`, `integration_type=hub`; echte Version, Maintainer und tatsächlich existierende Dokumentations-/Issue-URLs vor Release eintragen. Kryptografieabhängigkeiten nur mit geprüften Versionen. Keine erfundene GitHub-URL und kein fremder Maintainer. Manifestanforderungen mit der offiziellen Dokumentation und Hassfest prüfen. [S6]

Die unterstützte HA-Version muss aus Tests hervorgehen. Die vorhandene Offline-Python-3.11-Kompatibilität ist **keine** Aussage über die Python-Version des aktuellen Home Assistant. Bei Implementierung zuerst die tatsächlich eingesetzte HA-Version feststellen und die dort unterstützten API-/Schema-Imports verwenden.

### 10.3 Setup und Lebenszyklus

`async_setup_entry` erstellt API-Client und Coordinator und speichert Laufzeitobjekte in `ConfigEntry.runtime_data`. Erster Abruf erfolgt über die vorgesehene First-Refresh-Funktion. Danach Sensor-/Binary-Sensor-/Button-Plattformen gemeinsam weiterleiten. `async_unload_entry` entlädt Plattformen, stoppt Timer, entfernt Listener und gibt eigene Ressourcen frei. [S2]

Ein Netzwerkproblem beim Start wird als temporär behandelt; ein belegter Authentifizierungsfehler löst Reauth aus. Home Assistant sieht hierfür unter anderem `ConfigEntryNotReady` und `ConfigEntryAuthFailed` vor. Ein beliebiger HTTP-403 oder unbekannter Aqara-Code darf nicht automatisch als abgelaufener Token kategorisiert werden. [S4]

`CoordinatorEntity` verwenden, `should_poll=False`; Entity-Properties lesen ausschließlich aus dem Snapshot. Messwertänderungen und Diagnose-Liveness getrennt aktualisieren: Ein bei jedem Poll geänderter Empfangszeitstempel soll nicht alle unveränderten Messwerte erneut in den Recorder schreiben. Beim Einsatz von `always_update=False` dafür sorgen, dass Diagnose-/Verfügbarkeitsänderungen dennoch korrekt signalisiert werden. [S2]

### 10.4 Identität, Geräte und Migration

Ein Config Entry pro Region und serverseitig validiertem Konto. Einen stabilen Account-Key beispielsweise aus SHA-256 über `EU:<userid>` bilden. Das ist eine stabile interne Kennung, keine Garantie vollständiger Anonymität. Geräte-Unique-IDs verwenden Account-Key plus Aqara-Geräte-ID; Entity-Unique-IDs zusätzlich einen **stabilen semantischen Schlüssel**.

Anzeigenamen, Raumnamen und Token dürfen Unique-IDs nicht verändern. Reauth aktualisiert denselben Config Entry und erzeugt keine Duplikate. Eine Kontoabweichung wird erkannt und nicht still überschrieben. Die offiziellen Reauth-/Reconfigure-Flows bieten dafür passende Hilfsfunktionen. [S3]

Keine automatische Zusammenführung mit vorhandenen HomeKit-Geräten nur aufgrund ähnlicher Namen oder ID-Endungen. Keine Änderung bestehender Bereiche, Automationen oder Entity-IDs. Eine Cloud-Raumbezeichnung ist zunächst ein Vorschlag, kein administrativer Auftrag.

Schemaversionen für Config Entry und Protokollprofil getrennt verwalten. Migrationen testen, bevor das Schema hochgezählt wird. Das spätere Release dokumentiert eindeutig, welche Migrationen rückwärtskompatibel sind; ein Backup vor Versionswechsel gehört zur Installationsanleitung.

### 10.5 Entitäten im MVP

| Entitätsschlüssel | Typ | Standard | Semantik |
|---|---|---|---|
| `reported_illuminance` | Sensor, Illuminance, `lx` | Ein | Zuletzt gemeldeter Cloudwert, nicht als Echtzeit bezeichnet |
| `connection_problem` | Binary Sensor, Problem, Diagnose | Ein, accountbezogen | Eigener Integrationszustand; bleibt bei API-Ausfall lesbar |
| `connection_status` | Enum-Sensor, Diagnose | Ein, accountbezogen | `ready`, `retry_wait`, `reauth_required`, `protocol_unsupported` usw. |
| `last_successful_read` | Timestamp-Sensor, Diagnose | Ein | Letzter erfolgreicher Leseabruf, kein Messzeitpunkt |
| `data_quality` | Enum-Sensor, Diagnose | Ein, gerätebezogen | Qualität gemäß Abschnitt 8 |
| `presence_raw` | Sensor ohne Einheit/State Class, Diagnose | Aus | Nur Code, keine ungeprüfte Belegung |
| `device_status_raw` | Sensor ohne Einheit/State Class, Diagnose | Aus | Nicht als bewiesen online/offline benennen |
| `presence_source_time` | Timestamp-Sensor, Diagnose | Aus | Quellenzeit des Präsenzkandidaten |
| `fall_state_raw` | Sensor, Diagnose | Aus | Nur bei beobachtetem Feld; keine Sturzwarnung |
| `refresh` | Button | Ein, accountbezogen | Ein Read über denselben Rate-Limiter |
| `cloud_occupancy` | Binary Sensor, Occupancy | Erst nach Mappingfreigabe; Aus | Zusätzliche verifizierte Cloudpräsenz |

Bei reinen „zuletzt gemeldet“-Werten zunächst `state_class=None`, damit ungeprüfte/alte Daten nicht als aktuelle Langzeitmessungen eingeordnet werden. Nach nachgewiesener Aktualitätssemantik kann ein gesondert geplanter Messsensor `SensorStateClass.MEASUREMENT` erhalten. Home Assistant verlangt für `ILLUMINANCE` die Einheit `lx`; Timestamp-Sensoren geben zeitzonenbewusste `datetime`-Werte zurück. [S7]

Für nicht belegte Fähigkeiten **keine leeren Scheinentitäten** wie `person_count`, `heart_rate`, `sleep_stage` oder X-/Y-Sensoren anlegen. Ein fehlendes Capability-Flag darf ebenso wenig aus einer unvollständigen Antwort dauerhaft abgeleitet werden.

### 10.6 Beschränkte Aktionen

MVP bietet ausschließlich Refresh, Konfiguration und bereinigte Diagnosen. Kein generischer Dienst „Beliebigen Aqara-Endpunkt aufrufen“, kein frei konfigurierbarer Host und keine generischen Schreibaktionen. Authentifizierung ist eine ausdrücklich autorisierte Kontoaktion; sie wird nicht als harmlose Leseoperation getarnt.

## 11. Benutzerführung: Einrichtung, Reauth und Fehlerhilfen

### 11.1 Erstkonfiguration

Die erste Seite erklärt: „Ergänzt deine lokalen Aqara-Sensoren um Cloud-Daten. Deine bestehende HomeKit-Verbindung bleibt erhalten.“ Es gibt eine **Offline-Vorschau** und den **Live-Einrichtungsweg**. Die Offline-Vorschau erzeugt keine normalen produktiven Präsenzentitäten.

Der Live-Weg führt durch Region EU, Protokollstatus, Credential-Modus, lokale Eingabe/Import, Verbindungsprüfung, Geräteauswahl und Aktualisierungsintervall. Der Status zeigt verständliche Fortschritte: „Eingabe prüfen“, „Sitzung prüfen“, „Geräteantwort lesen“, „Datenqualität prüfen“.

Der minimal notwendige Protokoll-Import ist bevorzugt ein lokal erzeugtes, strukturiertes Credential-Paket. Ein vollständiges HAR darf wegen enthaltener anderer App-/Kontodaten nicht der Standard sein. Ein optionaler Importer wählt nur den erlaubten Host und Pfad aus, zeigt eine bereinigte Vorschau und übernimmt keine fremden Domains.

### 11.2 cURL- und HAR-Import

Ein cURL-Import ist ein Parser, **kein Shell-Aufruf**. Nie `subprocess(..., shell=True)`, nie `eval`, keine Ausführung mitkopierter Flags, Dateien oder Command-Substitutionen. Zulässige Felder ausdrücklich definieren; `@datei`, Pipes, Umleitungen und mehrdeutige Mehrfachheader ablehnen. Shell-Quoting plattformspezifisch testen; JSON/HAR oder Byte-Export bevorzugen, wenn cURL-Quoting die Originalbytes nicht eindeutig erhält.

HAR-Import: Größenlimit vor Verarbeitung; nur ausgewählte Entries; `postData.text` als Body nicht still neu serialisieren; bei fehlender Binär-/Encodingtreue keine Signaturgarantie behaupten. Login-Responses und fremde Authorization-Header nicht in Analysen ausgeben. Das Starter-CLI ist **kein** HAR-/cURL-Importer; dieser ist eine zusätzliche Implementierungsaufgabe.

### 11.3 Reauth ohne Datenverlust

Dialog: „Die Aqara-Sitzung ist nicht mehr gültig. Deine Geräte und bisherigen Aufzeichnungen bleiben bestehen.“ Schaltflächen: „Sitzung erneuern“, gegebenenfalls „Erneut anmelden“, „Später“. Keine Neuerstellung aller Geräte verlangen. Nach Erfolg die vorhandene Auswahl erhalten und per Probe bestätigen. Andere Region oder Konto nicht unbemerkt übernehmen. [S3]

### 11.4 Fehlermeldungen mit nächster Handlung

| Interner Schlüssel | Nutzertext | Handlung |
|---|---|---|
| `invalid_capture` | „Der Export ist unvollständig oder kein einzelner JSON-Datensatz.“ | Neu lokal exportieren; keine Zugangsdaten posten |
| `missing_credentials` | „Die Sitzung enthält nicht alle erforderlichen Angaben.“ | Lokale Eingabe vervollständigen |
| `signature_unverified` | „Das Signaturprofil ist für diesen Endpunkt noch nicht bestätigt.“ | Diagnoseprobe durchführen |
| `signature_rejected` | „Die Anfrage wurde nicht akzeptiert. Sitzung oder Protokollprofil prüfen.“ | Keine Login-Endlosschleife |
| `cannot_connect` | „Aqara ist momentan nicht erreichbar.“ | Automatischer begrenzter Retry |
| `rate_limited` | „Aqara begrenzt gerade die Anfragen.“ | Angezeigte Pause respektieren |
| `auth_required` | „Bitte die Aqara-Sitzung erneuern.“ | Reauth öffnen |
| `account_mismatch` | „Diese Sitzung gehört nicht zum eingerichteten Konto.“ | Richtige Sitzung verwenden |
| `no_selected_device_data` | „Für dieses Gerät wurden keine verwertbaren Werte geliefert.“ | Auswahl und App-Modus prüfen |
| `freshness_unverified` | „Ein Cloudwert liegt vor; seine Aktualität ist noch nicht bestätigt.“ | Rohwert und Quellenzeit prüfen |
| `api_changed` | „Die Aqara-Antwort entspricht nicht dem getesteten Format.“ | Bereinigte Diagnose, kein stiller Fallback |

Feldfehler direkt an der Eingabe anzeigen; technische Rohantworten nur geschützt lokal und nicht in der Benutzeroberfläche. Deutsch und Englisch vollständig übersetzen. Grundinformationen zuerst, Rohpfade unter einem Diagnosebereich. Nutzer nicht mit Zugangstoken oder Signaturmaterial in Benachrichtigungen konfrontieren.

## 12. Dashboard-Konzept und YAML-Vorlage

Das erste Dashboard verwendet ausschließlich Standardkarten. Oben Verbindung und Datenqualität, darunter die zuletzt gemeldete Helligkeit, anschließend optionale Diagnosen. Lokale Präsenz bleibt ein separat beschrifteter Bereich mit den vorhandenen HomeKit-Entitäten.

Keine grüne „Alles aktuell“-Anzeige aus einem bloßen HTTP-Erfolg ableiten. Ein Code `0` aus dem ungeprüften Präsenzfeld darf nicht als „Raum leer“ erscheinen. Nicht vorhandene Schlaf-/Positionsfunktionen werden nicht als Nullwerte visualisiert.

Die folgenden Entity-IDs sind **Platzhalter für die spätere Implementierung**, keine im Nutzer-HA bereits vorhandenen Namen. Nach Einrichtung im Entity-Registry prüfen und anpassen:

```yaml
title: Aqara Zusatzdaten
views:
  - title: Übersicht
    path: aqara-zusatzdaten
    cards:
      - type: markdown
        content: >-
          ## Aqara Zusatzdaten
          Lokale Präsenz bleibt unabhängig. Die folgenden Werte stammen
          aus der Aqara-Cloud und werden mit ihrer Datenqualität angezeigt.
      - type: entities
        title: Verbindung und Qualität
        show_header_toggle: false
        entities:
          - entity: sensor.aqara_cloud_connection_status
            name: Verbindung
          - entity: binary_sensor.aqara_cloud_connection_problem
            name: Verbindungsproblem
          - entity: sensor.aqara_cloud_last_successful_read
            name: Letzter erfolgreicher Abruf
          - entity: button.aqara_cloud_refresh
            name: Jetzt aktualisieren
      - type: entities
        title: Sensor A – zuletzt gemeldet
        show_header_toggle: false
        entities:
          - entity: sensor.aqara_sensor_a_data_quality
            name: Datenqualität
          - entity: sensor.aqara_sensor_a_reported_illuminance
            name: Helligkeit aus der Cloud
      - type: entities
        title: Sensor B – zuletzt gemeldet
        show_header_toggle: false
        entities:
          - entity: sensor.aqara_sensor_b_data_quality
            name: Datenqualität
          - entity: sensor.aqara_sensor_b_reported_illuminance
            name: Helligkeit aus der Cloud
```

Keine automatische Änderung eines bestehenden Dashboards. Eine separate Beispielansicht liefern; Nutzer entscheiden selbst über die Übernahme. In der Offline-Vorschau sichtbar „Beispieldaten vom 25.09.2026“, keine aktuelle Uhrzeit auf historische Fixtures setzen.

## 13. Fehlermatrix und Wiederherstellung

| Fehlerklasse | Verhalten des Clients | Verhalten in HA |
|---|---|---|
| DNS/Connect/Timeout | Begrenzte Wiederholungen mit Backoff | Messwerte unavailable; Ursache sichtbar |
| TLS/Zertifikatsfehler | Abbrechen, niemals TLS-Prüfung deaktivieren | Reparaturhinweis zur Verbindung |
| HTTP 429 | `Retry-After` beachten, gemeinsamer Account-Limiter | Wartezeit/Status anzeigen |
| HTTP 5xx | Als Transport-/Serverfehler behandeln, auch wenn Body verwirrend ist | Temporärer Ausfall |
| HTTP 401/403, unbekannter Body | Zugriff abgelehnt, Ursache noch unklassifiziert | Keine automatische Passwort-Endlosschleife |
| Belegter Tokenablauf | Ein erlaubter Neuanmeldeversuch oder Reauth | Bestehenden Entry erhalten |
| Belegter Signaturfehler | Protokollpfad stoppen, kein blindes Login | Profil-/Clock-/Body-Diagnose |
| Unbekannter Aqara-Code | Code numerisch/typisiert erfassen; Rohtext nicht loggen | `api_changed`/unbekannte Ablehnung |
| HTTP-Erfolg, `code != 0` | Anwendungserfolg verneinen | Fehlerzustand statt Fixture-Fallback |
| HTML statt JSON | Strikter Parsefehler | Protokollfehler |
| Defektes Gerät in Teilantwort | Nur betroffenes Gerät isolieren | Andere Geräte bleiben verfügbar |
| Trait ohne `value` | Aktuellen Wert als fehlend behandeln | Unknown; nicht Default |
| Neues Enum | Rohwert erhalten, Semantik unbekannt | Keine geratenen Labels |
| Clock-Sprung/future `traitTime` | Anomalie markieren; keine manuelle Systemzeitänderung | Qualitätshinweis |
| HA-Neustart | Neu einlesen und aktuellen Read abwarten | Keine Phantom-Präsenz aus Cache |
| Integration entladen | Tasks, Timer und Listener abbrechen | Kein weiterlaufender Poller |

Bei `CancelledError` bzw. Task-Abbruch nicht in einen generischen Netzwerkretry wechseln. Zwei unterschiedliche Retry-Schleifen auf Client- und Coordinator-Ebene dürfen sich nicht multiplizieren. Der Coordinator steuert Wiederholung und nächste zulässige Zeit zentral.

## 14. Datenschutz, Geheimnisse und Diagnosen

Die geteilten Header enthielten neben dem maskierten Token weitere Konto-/Geräte-/Push-Kennungen. Im Projektpaket wurden diese entfernt oder ersetzt. Roh-Captures bleiben ausschließlich in einem lokalen, von Git ausgeschlossenen Verzeichnis `private/` oder `captures/`. Nicht in öffentliche Issues, Markdown oder Codex-Prompts kopieren.

Zugangsgeheimnisse sind zur Laufzeit vom öffentlichen Protokollprofil getrennt. Für die HA-Integration die vorgesehenen persistenten Konfigurationsmechanismen verwenden, aber **keine zusätzliche Verschlüsselung behaupten**, die nicht implementiert und geprüft wurde. Dateirechte, administrativer Zugriff und Backup-Schutz gehören zur Sicherheitsannahme. Ein Passwortfeld mit verdeckter Darstellung ist keine Verschlüsselung ruhender Daten.

Diagnosen werden als neue Allowlist-Struktur aufgebaut: Profilversion, Integrationsversion, Gerätezähler, anonyme Gerätealiase, vorhandene Pfade, Typen, Wertstatus, Fehlerklasse, Zeit-/Qualitätsstatus. Namen, Raumbezeichnungen, Geräte-/Account-/Client-/Phone-IDs, Tokens, Cookies, Push-Tokens, Signatur, App-Key, Passwörter und signierte Header bleiben draußen. Standarddiagnosen enthalten keine personenbezogenen Schlafdaten und keine vollständigen unbekannten Stringwerte. Home Assistant bietet eine Diagnoseplattform und Redaktionshilfen; rekursive und pfadbezogene Tests sind trotzdem erforderlich. [S8]

Ein separater freiwilliger Supportexport darf erst nach Vorschau mehr Messwerte enthalten. Der vorhandene Offline-Bericht gibt bestimmte Messwerte und Quellenzeiten aus und ist daher keine vollständige Anonymisierung beliebiger Daten. Diagnostik-Aliase müssen innerhalb eines Exports konsistent sein; keine originalen ID-Endungen verwenden.

Keine Telemetrie, keine Uploads an Entwickler, keine automatische Account-/Region-Suche. Zugangsdaten nur an den geprüften Host senden, Redirects ablehnen. Nach der Proxyman-Analyse kann der Nutzer Proxy und zusätzliche Zertifikatsvertrauensstellung wieder deaktivieren; die spätere Integration benötigt sie nicht.

## 15. Tests und Abnahmekriterien

### 15.1 Bereits mitgelieferte Tests

Der Starter verwendet die Python-Standardbibliothek und `unittest`. Er prüft Parsing und den Signaturkandidaten vollständig offline. Der konkret ausgeführte Teststatus steht in `docs/VALIDIERUNG.md`. Diese Tests prüfen weder die Aqara-Cloud noch die HA-Integration.

### 15.2 Zusätzliche verpflichtende Testgruppen für Codex

| Gruppe | Wesentliche Testfälle |
|---|---|
| Parser | Vollständige Fixture; Reihenfolge B/A vs. A/B; Default ohne Wert; `null`; `"0"`; bool; Unicode; JSON-Strings; negative/ungültige Zeiten; große IDs |
| Duplikate | Identische Traits deduplizieren; widersprüchliche Werte/Typen isolieren; doppelte JSON-Schlüssel ablehnen |
| Signierung | Synthetischer Vektor; Token vorhanden/fehlend; Byte-/Whitespace-/Unicode-Änderung; frischer Nonce/Time; kein Secret-Logging |
| Auth | Tokenimport; fehlende Werte; Login-Erfolg; Ablehnung; unbekannter Code; MFA nicht unterstützt; Single-Flight-Neuanmeldung |
| HTTP | Timeout, Cancellation, TLS, Redirect, ungültiger Host, gzip-Dekompressionslimit, HTTP-Fehler trotz `code=0`, `Retry-After` als Datum/Sekunden |
| Qualität | Alter Änderungszeitpunkt vs. alte Messung; frischer HTTP-Abruf ohne Änderung; zukünftige Zeit; Empfangsausfall; Timer ohne weitere Poll-Erfolge |
| Coordinator | Ein Batch pro Konto; manuelle/automatische Abrufe coalescen; kein Doppelretry; mehrere Geräte/Teilantworten |
| Config Flow | Erstkonfiguration; Offlinevorschau ohne echte Entitäten; Duplicate Account; Reauth; Kontoabweichung; Reconfigure; falsche Region |
| Entitäten | Stabile Unique-IDs; keine Defaults; Lux 9 bleibt 9; keine fehlenden Fantasie-Capabilities; korrekte Einheiten; Diagnose bei Ausfall lesbar |
| Migration | Tokenwechsel ohne Duplikate; Anzeigename geändert; Schemawechsel; Rollbackbericht |
| Sicherheit | Test-Secrets in allen Fehlerpfaden; keine Geheimnisse in repr/Logs/Diagnosen; cURL nie ausgeführt; unbekannte HAR-Domains verworfen |
| Integration | Setup/Unload/Reload; HA-Neustart; keine zurückbleibenden Tasks; keine Veränderung lokaler HomeKit-Entitäten |

CI darf keine echten Credentials benötigen. Netzwerkzugriffe im Standard-Testlauf blockieren bzw. mocken. Live-Tests sind opt-in, nur im lokalen eigenen Konto, standardmäßig deaktiviert und nie als öffentliche CI mit Geheimnissen ausführen.

### 15.3 Definition of Done

**Offline fertig:** alle Fixtures reproduzierbar, Parser-/Signer-Tests grün, Katalog vollständig, keine persönlichen Kennungen im Repository.

**MVP live fertig:** G1–G3 erfüllt, stabiles freigegebenes Profil, installierbare Integration, kontrolliertes Polling, Einrichtung/Reauth mit verständlichen Zuständen, Messwerte korrekt gekennzeichnet, sämtliche simulierten Fehlerpfade getestet.

**Produktiver Betrieb freigegeben:** zusätzlich G5/G6 und dokumentierte HA-Kompatibilität. Cloud-Präsenz erfordert gesondert G4. Koordinaten/Schlafdaten sind erst mit eigener Evidenz erledigt. Kein Häkchen aufgrund von Stub-Funktionen oder Mock-Antworten.

## 16. Umsetzung in Arbeitspaketen

| Paket | Aufgabe | Abnahme |
|---|---|---|
| P0 | Bestehenden Starter ausführen und Evidenzinventar prüfen | Offlinebericht stimmt mit zwei Geräten und 9/110 lx überein |
| P1 | API-Datenmodell, Teilantwort-Isolation und Qualitätsmodell vervollständigen | Parser-/Qualitätstests grün |
| P2 | Lokalen Import und Signaturabgleich bauen | Keine Shellausführung; lokaler Capture-Test möglich |
| P3 | Asynchronen Transport und kontrolliertes Probe-Kommando implementieren | Host-Allowlist, TLS, Limits, Cancellation und Rate-Limit-Tests |
| P4 | EU-Profil am echten Endpunkt validieren | G1–G3 mit bereinigtem Bericht; andernfalls Blocker dokumentiert |
| P5 | AuthProvider und optionale Neuanmeldung implementieren | Identität, Einwilligung und Reauth fehlerfest |
| P6 | HA-Config-Flow, Coordinator und Minimalentitäten bauen | Setup/Unload/Reload und UI-Tests |
| P7 | Diagnose, Reparaturhinweise, Beispiel-Dashboard und Dokumentation | Keine Geheimnisse, verständliche Fehlerzustände |
| P8 | Staging-HA, Dauertest und Release-Paket | G5/G6, Hassfest/HACS-Prüfung, Versionsbericht |
| P9 | Zusätzliche Präsenzsemantik validieren | G4 und separate Freigabe |
| P10 | Optionale weitere Datenkanäle untersuchen | Eigenes Capture, Schema und Vertragstests pro Kanal |

Codex soll pro Paket einen kleinen nachvollziehbaren Commit erzeugen, **nachdem** der Nutzer das Projekt in seinem eigenen lokalen Repository geöffnet hat. Das hier gelieferte ZIP erstellt kein entferntes GitHub-Repository und nimmt keine Änderungen am laufenden Home Assistant vor.

Ein blockiertes P4 verhindert nicht die Entwicklung von P5–P7 mit Mocks. Der Abschlussbericht muss den Unterschied nennen und den Livebetrieb gesperrt lassen. Protokolländerungen nicht durch ungetestete „Best Guess“-Werte kaschieren.

## 17. Gezielte Erweiterungen

### 17.1 Schlafdaten

Die externe SleepRadar-Implementierung fragt über `/app/v1.0/lumi/res/query` unter anderem `heartrate_value`, `respiration_rate_value`, `sleep_state`, `body_movement_value` und `lux` ab. Das ist ein nützlicher Ansatzpunkt, aber diese Daten und deren Antwortschema sind **nicht Teil des hier gelieferten Trait-Captures**. [S1]

Für eine Erweiterung einen eigenständigen Adapter `SleepResourceAdapter` vorsehen. Erst eine tatsächliche Antwort des eigenen Geräts im passenden Modus aufnehmen, Werte-/Zeitsemantik prüfen und Entity-Mapping separat versionieren. `subjectId` nicht automatisch mit `deviceId` gleichsetzen, sondern am eigenen Request bestätigen. Keine fremde Schlafcode-Tabelle ohne passende Testevidenz übernehmen.

Schlafwerte nicht für medizinische Aussagen oder sicherheitskritische Entscheidungen verwenden. Ein plausibler Vitalwert beweist keine tatsächliche Belegung. Keine automatischen Tag-/Nacht-Moduswechsel im Rahmen dieser read-orientierten Integration; ein späterer Moduswechsel benötigt ein gesondertes, ausdrücklich autorisiertes Schreibkonzept.

### 17.2 Personenpositionen und Anzahl

App-Raumkarte in einem separaten lokalen Mitschnitt öffnen. Nur tatsächlich beobachtete weitere HTTP-/WebSocket-/Push-Verbindungen analysieren. Vor Umsetzung klären: Snapshot vs. Delta, Track-ID, Koordinatensystem, Einheit, Ursprung, Achsenrichtung, Raum-/Zonenzuordnung, Löschung verschwundener Tracks, Reihenfolge und Updatezeit.

Ein `positionId` mit dem Inhalt `real2...` ist in diesem Capture lediglich eine referenzartige Kennung, die mit einem Geräte-Trait übereinstimmt. Es gibt keine belegten X-/Y-Koordinaten. Ebenso wenig kann die Anzahl aus Listen wie `[4,6]` oder aus der Anzahl zurückgelieferter Geräte abgeleitet werden.

Keine Echtzeitkarte aus erfundenen Koordinaten erzeugen. Ein optionaler späterer Kartenadapter erhält erst nach Schema-Validierung Daten. Personen werden als temporäre Tracks behandelt, nicht ohne Beleg als identifizierte Familienmitglieder.

### 17.3 Sturz-Gruppe

Die Metadaten `fall_down` und `Sturzüberwachung` belegen eine Gruppe, nicht eine sicher nutzbare Alarmfunktion. Kein absichtlicher Sturztest. Bis zur sicheren Klärung nur Rohdiagnose; keine Benachrichtigung „Person gestürzt“ aus einem geratenen Enum. Diese Integration ist kein Notrufsystem.

## 18. Installation, Veröffentlichung und Betrieb

### 18.1 Was jetzt ausführbar ist

Im entpackten Projektverzeichnis:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m aqara_presence_lab fixtures/trait_read.response.json
```

Benötigt Python 3.11 oder neuer für den Offline-Starter; keine zusätzlichen Pakete. Dieser Aufruf liest nur eine lokale JSON-Datei und gibt einen begrenzten Analysebericht aus. Er führt keinen Login durch und legt keine HA-Entitäten an.

### 18.2 Installation nach Umsetzung durch Codex

Erst wenn `custom_components/aqara_presence_lab` vollständig implementiert, getestet und freigegeben ist: HA-Konfiguration sichern, Integrationsordner nach `/config/custom_components/aqara_presence_lab` kopieren, Home Assistant regulär neu starten, Integration über „Geräte & Dienste“ hinzufügen. **Den jetzigen `src/`-Ordner nicht als fertige Custom Integration installieren.**

Kein Löschen der HomeKit-Kopplung, kein Zurücksetzen der FP2, keine Neuerstellung vorhandener Automationen. Nach Einrichtung zuerst zusätzliche Diagnose/Helligkeit prüfen und anschließend nur die tatsächlich freigegebenen Entitäten aktivieren.

### 18.3 HACS und CI

Später ein echtes Repository mit vollständigem `custom_components`-Ordner, `hacs.json`, versionierten Releases, Beschreibung, Lizenz-/Quellenhinweisen und Supportanleitung anlegen. HACS-Konfiguration und Manifest gegen die dann geltenden Vorgaben prüfen. Die Aufnahme in einen öffentlichen Katalog ist nicht identisch mit der Nutzung als Custom Repository. [S5]

Standard-CI: Tests, Typprüfung, Linting, Secret-Scan, Hassfest und passende HACS-Prüfung. Abhängigkeiten nach erfolgreichem Test auf die tatsächlich verwendeten Versionen festlegen. Keine ungetestete Kompatibilitätsmatrix mit zukünftigen HA-Versionen versprechen.

### 18.4 Betriebsleitfaden

Bei Verbindungsausfall zuerst `connection_status` und letzte erfolgreiche Leseprobe prüfen. Bei `auth_required` den Reauth-Dialog verwenden, nicht HA mehrfach neu starten. Bei unbestätigter Aktualität die lokale Präsenz weiter nutzen. Bei API-Änderung Integration pausieren und bereinigte Diagnose sichern; nicht mit aggressivem Polling nachhelfen.

Ein Rollback betrifft nur die zusätzliche Integration. Lokale HomeKit-Geräte bleiben unverändert. Gespeicherte Verlaufsdaten nicht automatisch löschen. Beim vollständigen Entfernen der Integration eigene Credentials, Listener, Tasks und erzeugte Reparaturhinweise bereinigen; Verhalten gegenüber bestehender Recorder-Historie dokumentieren.

## 19. Offene Punkte und Verantwortlichkeit

| Offener Punkt | Bereits vorhandene Grundlage | Konkreter nächster Nachweis |
|---|---|---|
| Trait-Endpunkt akzeptiert Signaturkandidaten | Gleicher EU-Host/App-ID, externe Signaturkonstruktion | Lokaler Signaturvergleich und Read-Probe |
| Session kann ohne iPhone weiter genutzt werden | App-Request und externer Loginansatz | Tests bei geschlossener App und ohne Proxy |
| Login am eigenen Konto funktioniert | Extern dokumentierter Passwort-/RSA-Weg | Ein bewusster lokaler Login; ggf. Reauth-Fallback |
| `needSubscribe` für Polling geeignet | Flag im Request/Response | Kontrollierter Vergleich, keine heimliche Dauer-Subscription |
| Präsenzcode 0/1 bedeutet leer/belegt | Gruppenname plus binäres Rohfeld | Wiederholte Stillanwesenheits-/Verlasstests |
| `traitTime` ist Mess-/Änderungszeit | Sehr unterschiedliche historische Zeitwerte | Korrelation mit tatsächlichen Wechseln |
| `0.128.32901` beschreibt Onlinezustand | Enum und aktueller Rohwert | Unabhängiger Online-/Offline-Vergleich ohne Reset |
| Personen-/Schlafdaten erreichbar | Nutzerziel; externer Schlaf-Endpunkt als Ansatz | Getrennte Captures und Schema-Tests |

Diese offenen Punkte machen die Spezifikation nicht zu einer erfundenen fertigen Integration. Sie sind explizite Entwicklungs- und Abnahmeaufgaben. Der automatische Dauerbetrieb darf erst die nachgewiesenen Teilfunktionen freigeben.

## 20. Fertiger Startauftrag für Codex

```text
Arbeite im Projekt „Aqara Presence Lab“.

Lies zuerst AGENTS.md, dann IMPLEMENTIERUNG.md und docs/VALIDIERUNG.md.
Führe die vorhandenen Offline-Tests aus und prüfe die Fixtures.
Implementiere die Arbeitspakete P0 bis P8 in nachvollziehbaren Schritten.

Ziel ist eine native Home-Assistant-Custom-Integration für den dokumentierten
Aqara-Trait-Endpunkt. Bestehende lokale HomeKit-Geräte bleiben unverändert.
Verwende den dokumentierten Signatur-/Login-Kandidaten als klar markiertes
Protokollprofil, nicht als bereits am Zielendpunkt bestätigte Tatsache.

Keine Credentials aus Dateien in Chatantworten/Logs kopieren. Niemals cURL
als Shellkommando ausführen. Keine echten Netzwerkaufrufe in Standardtests.
Live-Proben ausschließlich nach lokal ausdrücklich erteilter Freigabe.
Persönliche Secrets niemals von mir in einen Chat kopieren lassen.

Keine frei erfundenen Enum-Mappings, Refresh-Endpunkte, Personenkoordinaten
oder Schlafsensoren. Fehlende Werte niemals durch defaultValue ersetzen.
Alte Quellenzeit und Zeitpunkt eines erfolgreichen Abrufs getrennt behandeln.

Wenn Live-Evidenz fehlt, implementiere Parser, Client-Interfaces, Testdoubles,
Config Flow, Fehlerbehandlung und UI weiter. Lass den produktiven Live-Gate
für das unbestätigte Profil geschlossen. Markiere solche Arbeitspakete als
„implementiert, live unbestätigt“, nicht als vollständig validiert.

Liefere am Ende geänderte Dateien, Testergebnisse, tatsächlichen
Funktionsstatus, noch offene Live-Gates und eine eindeutige Installationsanleitung.
```

## 21. Quellen und Nachvollziehbarkeit

Technische Aussagen über das Capture stammen aus [S0]. Architekturentscheidungen, Intervalle, Schutzlimits, Testanzahl und Freigabegates sind **Projektentscheidungen**, keine von Aqara zugesagten Eigenschaften. Externe Quellen wurden am 26.09.2026 gelesen; bewegliche Branches und Dokumentationen sind vor Implementierung erneut auf Kompatibilität zu prüfen.

**[S0] Nutzer-Capture.** In dieser Unterhaltung am 26.09.2026 bereitgestellter Request/Response-Text; Headerzeit 25.09.2026. Bereinigte Rekonstruktionen sind im Anhang und im Fixture-Verzeichnis enthalten. Es liegt keine unabhängige Live-Verifikation vor.

**[S1] SleepRadar, primärer Implementierungsquelltext.** `florianhorner/ha-fp2-sleep`, Datei `aqara_fp2_sleep/aqara_fp2_sleep_poller.py`, gelesen über die GitHub-Schnittstelle; Blob-SHA `b48a4417deebd04cf4e6b3eb3d918300e6081d25`. Relevanz: EU-App-ID/Host, Signaturaufbau, RSA-Passwortverarbeitung, Login- und Ressourcen-Endpunkt. Die Quelle ist kein offizieller Aqara-Vertrag.

`https://github.com/florianhorner/ha-fp2-sleep/blob/main/aqara_fp2_sleep/aqara_fp2_sleep_poller.py`

**[S2] Home Assistant Developer Docs – Fetching data.** Coordinator, gemeinsame Abfragen, asynchroner Datenabruf und Lebenszyklus.

`https://developers.home-assistant.io/docs/integration_fetching_data/`

**[S3] Home Assistant Developer Docs – Config flow.** Einrichtung, stabile Identität, Reauth und Reconfigure.

`https://developers.home-assistant.io/docs/core/integration/config_flow/`

**[S4] Home Assistant Developer Docs – Handling setup failures.** Temporäre Startfehler und abgelaufene Credentials.

`https://developers.home-assistant.io/docs/integration_setup_failures/`

**[S5] HACS – Integrations.** Struktur-/Verteilungsanforderungen an Custom Integrations.

`https://www.hacs.xyz/docs/publish/integration/`

**[S6] Home Assistant Developer Docs – Integration manifest.** Integrationsmetadaten, Version, I/O-Klasse und Anforderungen.

`https://developers.home-assistant.io/docs/creating_integration_manifest/`

**[S7] Home Assistant Developer Docs – Sensor entity.** Einheit `lx`, Timestamp-Werte, Entity-Properties und State Classes.

`https://developers.home-assistant.io/docs/core/entity/sensor/`

**[S8] Home Assistant Developer Docs – Integration diagnostics.** Diagnoseplattform und Redaktionshilfen.

`https://developers.home-assistant.io/docs/core/integration/diagnostics/`

---

## Anhang A – Vollständige pseudonymisierte Fixtures

Die folgenden JSON-Blöcke sind identisch zu den beigefügten Dateien. Sie machen diese Markdown-Spezifikation auch ohne ZIP als Eingabe für Codex nutzbar. IDs und Namen sind synthetisch, Zeitstempel und Messwerte aus dem Capture; niemals die Beispiel-IDs für echte Abfragen verwenden. Kein Block enthält eine gültige Sitzung oder eine Originalsignatur.

### A.1 Request – inklusive beobachteter Wiederholungen

```json
{
  "devices": [
    {
      "traits": [
        {
          "path": "0.128.32901",
          "needSubscribe": true
        },
        {
          "path": "0.129.32907",
          "needSubscribe": true
        },
        {
          "path": "0.129.33013",
          "needSubscribe": true
        },
        {
          "path": "0.129.32909",
          "needSubscribe": true
        },
        {
          "path": "0.129.32906",
          "needSubscribe": true
        },
        {
          "path": "0.129.32912",
          "needSubscribe": true
        },
        {
          "path": "0.130.32914",
          "needSubscribe": true
        },
        {
          "path": "0.130.32913",
          "needSubscribe": true
        },
        {
          "path": "0.130.33016",
          "needSubscribe": true
        },
        {
          "path": "1.147.32969",
          "needSubscribe": true
        },
        {
          "path": "2.160.33001",
          "needSubscribe": true
        },
        {
          "path": "2.160.33044",
          "needSubscribe": true
        },
        {
          "path": "2.160.33000",
          "needSubscribe": true
        },
        {
          "path": "2.160.33045",
          "needSubscribe": true
        },
        {
          "path": "2.130.32913",
          "needSubscribe": true
        },
        {
          "path": "2.130.32915",
          "needSubscribe": true
        },
        {
          "path": "2.130.33108",
          "needSubscribe": true
        },
        {
          "path": "2.130.32919",
          "needSubscribe": true
        },
        {
          "path": "2.130.33012",
          "needSubscribe": true
        },
        {
          "path": "4.154.32989",
          "needSubscribe": true
        },
        {
          "path": "4.130.32913",
          "needSubscribe": true
        },
        {
          "path": "4.130.32915",
          "needSubscribe": true
        },
        {
          "path": "4.130.33108",
          "needSubscribe": true
        },
        {
          "path": "4.130.32919",
          "needSubscribe": true
        },
        {
          "path": "4.130.33012",
          "needSubscribe": true
        },
        {
          "path": "5.130.32913",
          "needSubscribe": true
        },
        {
          "path": "5.130.32915",
          "needSubscribe": true
        },
        {
          "path": "5.130.33108",
          "needSubscribe": true
        },
        {
          "path": "5.130.32919",
          "needSubscribe": true
        },
        {
          "path": "5.130.33012",
          "needSubscribe": true
        },
        {
          "path": "5.168.33019",
          "needSubscribe": true
        }
      ],
      "deviceId": "lumi1.000000000002"
    },
    {
      "traits": [
        {
          "path": "0.128.32901",
          "needSubscribe": true
        },
        {
          "path": "0.129.32907",
          "needSubscribe": true
        },
        {
          "path": "0.129.33013",
          "needSubscribe": true
        },
        {
          "path": "0.129.32909",
          "needSubscribe": true
        },
        {
          "path": "0.129.32906",
          "needSubscribe": true
        },
        {
          "path": "0.129.32912",
          "needSubscribe": true
        },
        {
          "path": "0.130.32914",
          "needSubscribe": true
        },
        {
          "path": "0.130.32913",
          "needSubscribe": true
        },
        {
          "path": "0.130.33016",
          "needSubscribe": true
        },
        {
          "path": "1.147.32969",
          "needSubscribe": true
        },
        {
          "path": "2.160.33001",
          "needSubscribe": true
        },
        {
          "path": "2.160.33044",
          "needSubscribe": true
        },
        {
          "path": "2.160.33000",
          "needSubscribe": true
        },
        {
          "path": "2.160.33045",
          "needSubscribe": true
        },
        {
          "path": "2.130.32913",
          "needSubscribe": true
        },
        {
          "path": "2.130.32915",
          "needSubscribe": true
        },
        {
          "path": "2.130.33108",
          "needSubscribe": true
        },
        {
          "path": "2.130.32919",
          "needSubscribe": true
        },
        {
          "path": "2.130.33012",
          "needSubscribe": true
        },
        {
          "path": "0.130.32914",
          "needSubscribe": true
        },
        {
          "path": "0.128.32901",
          "needSubscribe": true
        },
        {
          "path": "0.129.32907",
          "needSubscribe": true
        },
        {
          "path": "0.129.33013",
          "needSubscribe": true
        },
        {
          "path": "0.129.32909",
          "needSubscribe": true
        },
        {
          "path": "0.129.32906",
          "needSubscribe": true
        },
        {
          "path": "0.129.32912",
          "needSubscribe": true
        },
        {
          "path": "0.130.32914",
          "needSubscribe": true
        },
        {
          "path": "0.130.32913",
          "needSubscribe": true
        },
        {
          "path": "0.130.33016",
          "needSubscribe": true
        },
        {
          "path": "1.147.32969",
          "needSubscribe": true
        },
        {
          "path": "4.154.32989",
          "needSubscribe": true
        },
        {
          "path": "4.130.32913",
          "needSubscribe": true
        },
        {
          "path": "4.130.32915",
          "needSubscribe": true
        },
        {
          "path": "4.130.33108",
          "needSubscribe": true
        },
        {
          "path": "4.130.32919",
          "needSubscribe": true
        },
        {
          "path": "4.130.33012",
          "needSubscribe": true
        },
        {
          "path": "0.130.32914",
          "needSubscribe": true
        }
      ],
      "deviceId": "lumi1.000000000001"
    }
  ],
  "needParam": true
}
```

### A.2 Eine eindeutige Response – doppelte Chatkopie entfernt

```json
{
  "result": [
    {
      "traits": [
        {
          "path": "2.130.32915",
          "defaultValue": "1",
          "needSubscribe": true
        },
        {
          "path": "2.130.32913",
          "defaultValue": "MotionSensor",
          "value": "Anwesenheitssensor",
          "needSubscribe": true
        },
        {
          "path": "2.130.32919",
          "enums": "[\"presence_detector\"]",
          "defaultValue": "presence_detector",
          "value": "presence_detector",
          "needSubscribe": true
        },
        {
          "path": "4.130.32919",
          "enums": "[\"illumination\"]",
          "defaultValue": "illumination",
          "value": "illumination",
          "needSubscribe": true
        },
        {
          "path": "4.154.32989",
          "unit": "lux",
          "min": 0.0,
          "max": 83000.0,
          "traitTime": 1790354656410,
          "step": 10.0,
          "value": "9",
          "propertyId": [
            "0.4.85"
          ],
          "needSubscribe": true
        },
        {
          "path": "0.130.32914",
          "value": "real2.0000000000000000001",
          "propertyId": [
            "8.0.8108"
          ],
          "needSubscribe": true
        },
        {
          "path": "0.130.32913",
          "defaultValue": "人体存在传感器",
          "value": "Praesenzsensor A",
          "propertyId": [
            "8.0.8101"
          ],
          "needSubscribe": true
        },
        {
          "path": "4.130.32915",
          "defaultValue": "1",
          "needSubscribe": true
        },
        {
          "path": "0.128.32901",
          "enums": "[\"0\",\"1\"]",
          "value": 1,
          "propertyId": [
            "8.0.2045"
          ],
          "needSubscribe": true
        },
        {
          "path": "0.130.33016",
          "value": "Raum A",
          "propertyId": [
            "8.0.8102"
          ],
          "needSubscribe": true
        },
        {
          "path": "4.130.32913",
          "value": "Beleuchtungsstärke",
          "needSubscribe": true
        },
        {
          "path": "0.129.33013",
          "defaultValue": "[0,1,2,3,4,5,6]",
          "traitTime": 1737823004988,
          "value": "[4,6]",
          "propertyId": [
            "14.49.85"
          ],
          "needSubscribe": true
        },
        {
          "path": "2.160.33001",
          "enums": "[\"0\",\"1\",\"2\",\"3\"]",
          "needSubscribe": true
        },
        {
          "path": "2.160.33045",
          "unit": "ms",
          "min": 0.0,
          "max": 604800000.0,
          "step": 1.0,
          "needSubscribe": true
        },
        {
          "path": "2.130.33012",
          "enums": "[\"0\",\"1\"]",
          "defaultValue": "1",
          "value": "1",
          "needSubscribe": true
        },
        {
          "path": "2.160.33000",
          "enums": "[\"0\",\"1\"]",
          "traitTime": 1737821236919,
          "value": "0",
          "propertyId": [
            "3.51.85"
          ],
          "needSubscribe": true
        },
        {
          "path": "2.160.33044",
          "needSubscribe": true
        },
        {
          "path": "4.130.33012",
          "enums": "[\"0\",\"1\"]",
          "defaultValue": "1",
          "value": "1",
          "needSubscribe": true
        },
        {
          "path": "0.129.32906",
          "enums": "[\"0\",\"1\"]",
          "defaultValue": "1",
          "value": "1",
          "needSubscribe": true
        },
        {
          "path": "0.129.32907",
          "defaultValue": "31",
          "value": "31",
          "needSubscribe": true
        }
      ],
      "positionId": "real2.0000000000000000001",
      "deviceModel": "lumi.motion.agl001",
      "deviceId": "lumi1.000000000001"
    },
    {
      "traits": [
        {
          "path": "5.130.33012",
          "enums": "[\"0\",\"1\"]",
          "defaultValue": "1",
          "value": "1",
          "needSubscribe": true
        },
        {
          "path": "0.130.33016",
          "value": "Raum B",
          "propertyId": [
            "8.0.8102"
          ],
          "needSubscribe": true
        },
        {
          "path": "5.130.32913",
          "defaultValue": "Attitude_x005f_x0001_Detector",
          "value": "Sturzüberwachung",
          "needSubscribe": true
        },
        {
          "path": "2.160.33001",
          "enums": "[\"0\",\"1\",\"2\",\"3\"]",
          "needSubscribe": true
        },
        {
          "path": "2.160.33045",
          "unit": "ms",
          "min": 0.0,
          "max": 604800000.0,
          "step": 1.0,
          "needSubscribe": true
        },
        {
          "path": "5.130.32915",
          "defaultValue": "1",
          "needSubscribe": true
        },
        {
          "path": "2.160.33000",
          "enums": "[\"0\",\"1\"]",
          "traitTime": 1790332365586,
          "value": "0",
          "propertyId": [
            "3.51.85"
          ],
          "needSubscribe": true
        },
        {
          "path": "2.160.33044",
          "value": 3731446,
          "needSubscribe": true
        },
        {
          "path": "5.130.32919",
          "enums": "[\"fall_down\"]",
          "defaultValue": "fall_down",
          "value": "fall_down",
          "needSubscribe": true
        },
        {
          "path": "0.129.32906",
          "enums": "[\"0\",\"1\"]",
          "defaultValue": "1",
          "value": "1",
          "needSubscribe": true
        },
        {
          "path": "0.129.32907",
          "defaultValue": "31",
          "value": "31",
          "needSubscribe": true
        },
        {
          "path": "2.130.32915",
          "defaultValue": "1",
          "needSubscribe": true
        },
        {
          "path": "2.130.32913",
          "defaultValue": "MotionSensor",
          "value": "Occupancy Sensor",
          "needSubscribe": true
        },
        {
          "path": "5.168.33019",
          "enums": "[\"0\",\"1\",\"2\"]",
          "unit": "",
          "defaultValue": "0",
          "traitTime": 1684265219105,
          "value": "0",
          "propertyId": [
            "4.31.85"
          ],
          "needSubscribe": true
        },
        {
          "path": "2.130.32919",
          "enums": "[\"presence_detector\"]",
          "defaultValue": "presence_detector",
          "value": "presence_detector",
          "needSubscribe": true
        },
        {
          "path": "4.130.32919",
          "enums": "[\"illumination\"]",
          "defaultValue": "illumination",
          "value": "illumination",
          "needSubscribe": true
        },
        {
          "path": "4.154.32989",
          "unit": "lux",
          "min": 0.0,
          "max": 83000.0,
          "traitTime": 1790355274126,
          "step": 10.0,
          "value": "110",
          "propertyId": [
            "0.4.85"
          ],
          "needSubscribe": true
        },
        {
          "path": "0.130.32914",
          "value": "real2.0000000000000000002",
          "propertyId": [
            "8.0.8108"
          ],
          "needSubscribe": true
        },
        {
          "path": "0.130.32913",
          "defaultValue": "人体存在传感器",
          "value": "Praesenzsensor B",
          "propertyId": [
            "8.0.8101"
          ],
          "needSubscribe": true
        },
        {
          "path": "4.130.32915",
          "defaultValue": "1",
          "needSubscribe": true
        },
        {
          "path": "0.128.32901",
          "enums": "[\"0\",\"1\"]",
          "value": 1,
          "propertyId": [
            "8.0.2045"
          ],
          "needSubscribe": true
        },
        {
          "path": "4.130.32913",
          "value": "Illuminance",
          "needSubscribe": true
        },
        {
          "path": "0.129.33013",
          "defaultValue": "[0,1,2,3,4,5,6]",
          "traitTime": 1693004666931,
          "value": "[2,4,202,102,101,201,203]",
          "propertyId": [
            "14.49.85"
          ],
          "needSubscribe": true
        },
        {
          "path": "2.130.33012",
          "enums": "[\"0\",\"1\"]",
          "defaultValue": "1",
          "value": "1",
          "needSubscribe": true
        },
        {
          "path": "4.130.33012",
          "enums": "[\"0\",\"1\"]",
          "defaultValue": "1",
          "value": "1",
          "needSubscribe": true
        }
      ],
      "positionId": "real2.0000000000000000002",
      "deviceModel": "lumi.motion.agl001",
      "deviceId": "lumi1.000000000002"
    }
  ],
  "code": 0,
  "requestId": "REDACTED_REQUEST_ID",
  "message": "Success",
  "msgDetails": "Success"
}
```

### A.3 Herkunft und Bereinigung

```json
{
  "source": "Vom Nutzer am 2026-09-26 eingefügter Proxyman-Mitschnitt; manuell rekonstruiert",
  "fixture_version": 1,
  "wire_exact": false,
  "pseudonymised": true,
  "capture_header_time_ms": 1790355356562,
  "capture_header_time_berlin": "2026-09-25T18:55:56.562+02:00",
  "endpoint": {
    "method": "POST",
    "host": "rpc-ger.aqara.com",
    "path": "/app/v1.0/lumi/app/qlink/trait/read"
  },
  "observed_app_version": "6.4.1",
  "observed_area": "EU",
  "public_app_id": "7be1984f0556276133336839",
  "removed": [
    "Cookie",
    "PhoneId",
    "Userid",
    "Clientid",
    "voipDeviceToken",
    "Device-Token",
    "Token",
    "Sign",
    "Nonce",
    "original deviceId",
    "original positionId",
    "original names",
    "original requestId"
  ],
  "reconstruction_notes": [
    "Doppelt eingefügte Antwort auf einen eindeutigen Datensatz reduziert.",
    "HTML-Leerzeichen und darstellungsbedingte Unterstrich-Escapes manuell bereinigt.",
    "JSON-String-Werte für enums und Wertelisten bleiben Strings.",
    "Request-Reihenfolge und doppelte Trait-Pfade erhalten.",
    "Keine Original-Body-Bytes: kein gültiger Signatur-Testvektor."
  ],
  "request_trait_counts": {
    "sensor_a": 37,
    "sensor_b": 31
  },
  "response_trait_counts": {
    "sensor_a": 20,
    "sensor_b": 25
  },
  "live_validated": false
}
```

### A.4 Synthetischer Signaturtest, kein Live-Nachweis

```json
{
  "app_id": "demo-app",
  "nonce": "00000000000000000000000000000000",
  "time_ms": "1700000000000",
  "body_utf8": "{\"devices\":[],\"needParam\":true}",
  "app_key": "demo-key",
  "token": "demo-token",
  "expected_signature": "55e1c74bbca214902ece1aa35bcc1046",
  "evidence": "Synthetic formula regression only; NOT a captured or server-validated vector."
}
```
