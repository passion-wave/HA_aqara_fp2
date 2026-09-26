# Mitentwickeln

Die [Spezifikation](docs/IMPLEMENTIERUNG.md) beschreibt den Datenvertrag und die
Live-Gates. Ein simuliertes Testergebnis ist niemals ein Live-Nachweis. Insbesondere
werden Enum-Bedeutungen, Refresh-Endpunkte und Personenkoordinaten nicht geraten.

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest --cov --cov-report=term-missing
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy
.venv/bin/python scripts/check_repository.py
.venv/bin/python scripts/build_release.py
```

Der Standardtestlauf blockiert Internetzugriff. Keine echten Credentials in CI
hinterlegen. Änderungen am gemeinsamen API-Kern müssen Parser, Laborwerkzeug und
Home-Assistant-Adapter gemeinsam berücksichtigen. Fehlertexte bleiben bereinigt.

Bitte kleine Pull Requests mit konkretem Verhalten, Tests und aktualisierten
deutschen und englischen Texten erstellen. Jede neue Protokollfunktion benötigt
eine Quellenreferenz und einen eigenen dokumentierten Vertragstest.

