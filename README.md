# BB Baseball Stats 2026

Statische Statistikseite für die Baseball-Ligen in Berlin-Brandenburg.

## Enthaltene Ligen

- **Landesliga Baseball:** zusammengeführt aus `LLBBDivA (6208)` und `LLBBDivB (6209)`
- **Verbandsliga Baseball:** `VLBB (6205)`

Die Liga kann oben auf jeder Seite ausgewählt werden. Die Auswahl wird als `?league=landesliga` oder `?league=verbandsliga` in der URL gespeichert und zusätzlich im Browser gemerkt.

Im ZIP ist der aktuelle Landesliga-Datensatz bereits enthalten. Für die Verbandsliga wird bis zum ersten Abruf ein Hinweis angezeigt; danach ersetzt `sync_data.py` den Platzhalter durch die echten Daten.

## Website starten

1. `start_server.bat` doppelklicken.
2. Im Browser `http://localhost:8000/dashboard.html` öffnen.

Alternativ kann in VS Code **Live Server** verwendet werden. Die HTML-Dateien dürfen nicht direkt per Doppelklick geöffnet werden, weil der Browser lokale JSON-Dateien sonst blockieren kann.

## Daten aktualisieren

### Landesliga

1. `landesliga_data_fetcher_vscode.py` in VS Code öffnen.
2. Rechts oben **Run Python File** ausführen.

Ausgabe:

```text
bsm_league_data/landesliga_2026/combined.json
```

### Verbandsliga

1. `verbandsliga_data_fetcher_vscode.py` in VS Code öffnen.
2. Rechts oben **Run Python File** ausführen.

Ausgabe:

```text
bsm_league_data/verbandsliga_2026/combined.json
```

### Website-Dateien synchronisieren

Lokal liest die Website zuerst direkt aus `bsm_league_data`. Für eine portable Kopie oder GitHub Pages danach zusätzlich `sync_data.py` ausführen. Das Skript kopiert vorhandene Datensätze nach:

```text
data/landesliga_2026.json
data/verbandsliga_2026.json
```

Fehlt eine Liga, wird sie übersprungen und eine verständliche Meldung ausgegeben.

## Seiten

- `dashboard.html`: Tabelle, Bestenlisten und Spiele
- `index.html`: vollständige Batting- und Pitching-Statistiken
- `player.html`: Spielersuche und Spielerprofil mit Radar-Perzentilen

## Geschätzte Kennzahlen

`wOBA*`, `OPS+*`, `wRC+*`, `FIP*`, `ERA+*`, `FIP-*` und `WAR*` werden aus den veröffentlichten BSM-Rohdaten berechnet. Sie sind keine offiziellen Kennzahlen, weil unter anderem vollständige Park-, Defensiv- und Baserunning-Daten fehlen.

## Tests

JavaScript:

```bash
npm test
```

Python:

```bash
python -m unittest discover -s tests -p "test_*.py"
```
