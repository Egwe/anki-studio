# Anki Studio

Schlichte Web-Oberfläche für den [Anki Flashcard Generator](https://github.com/Egwe/anki-flashcard-generator), betrieben im Heimnetz und als Client des eigenen Anki-Sync-Servers.

Anforderungen und ihr Status stehen in [requirements.md](./requirements.md), Arbeitsregeln in [AGENTS.md](./AGENTS.md), die Ausgangslage in [docs/anki-studio-uebergabe.md](./docs/anki-studio-uebergabe.md).

## Stand

Das Projektgerüst steht: Die Anwendung startet, zeigt eine Startseite mit den installierten Versionen von Anki Studio, Generator und Anki und liefert alle Frontend-Dateien selbst aus. Login, Generieren, Live-Fortschritt und Kartenprüfung folgen als nächste Pakete (Phase 2).

## Installation (lokal)

Voraussetzung ist [uv](https://docs.astral.sh/uv/). Die Python-Version steht in `.python-version` (3.13, wie im Container). Fehlt sie, installiert `uv python install 3.13` sie für uv.

```bash
uv sync
```

`uv sync` installiert die Abhängigkeiten aus `uv.lock` in `.venv`, darunter `anki==26.09.4` (genau die Version des Sync-Servers) und den Generator vom Git-Tag `v0.2.0`.

## Lokal starten

```bash
cp studio.example.yaml studio.yaml
uv run anki-studio serve --config studio.yaml
```

Danach ist die Oberfläche unter <http://127.0.0.1:8000> erreichbar. Ohne `--config` wird die Datei aus `ANKI_STUDIO_CONFIG` gelesen; ohne beides gelten die Standardwerte. Es läuft immer genau ein Serverprozess.

## Konfiguration

`studio.yaml` enthält die Einstellungen der Web-Anwendung, nicht die Generator-Konfiguration und keine Secrets. Unbekannte Schlüssel und ungültige Werte werden beim Start mit einer Meldung abgelehnt.

| Schlüssel | Standard | Bedeutung |
|---|---|---|
| `host` | `127.0.0.1` | Adresse, auf der der Server lauscht; im Container `0.0.0.0` |
| `port` | `8000` | Port der Oberfläche (1–65535) |

## Vorschau im Container

Bis zur regulären Installation (AS-040, Phase 4) läuft im LXC „anki-studio“ eine Vorschau des aktuellen Stands von `main`. Nach einem Push auf `main` aktualisiert sie dieser Aufruf vom Entwicklungsrechner:

```bash
ssh ct-anki-studio 'bash -s' < deploy/preview.sh
```

Das Skript ist idempotent und erledigt Folgendes:

- installiert bei Bedarf `git` (apt) und uv 0.13.7 (mit Prüfsumme) nach `/usr/local/bin`,
- holt `main` aus GitHub als Git-Checkout nach `/opt/anki-studio`,
- installiert die Abhängigkeiten mit `uv sync --locked --no-dev` und dem System-Python 3.13 (Cache in `/var/cache/anki-studio/uv`),
- legt `/etc/anki-studio/studio.yaml` (Host `0.0.0.0`, Port 8000) und eine leere `/etc/anki-studio/env` (0600) an, falls sie fehlen; vorhandene Dateien bleiben unverändert,
- startet den systemd-Dienst `anki-studio-preview` neu und prüft `/healthz`.

Der Dienst läuft ohne Root-Rechte mit einem dynamischen systemd-Benutzer; Daten landen in `/var/lib/anki-studio`. Die Oberfläche ist dann im LAN unter `http://<Container-Adresse>:8000` erreichbar. Im Container wird kein Code bearbeitet (AGENTS.md Abschnitt 8).

## Tests und Prüfungen

```bash
uv sync
.venv/bin/python -m ruff check src tests
.venv/bin/python -m ruff format --check src tests
.venv/bin/python -m pytest
```

Die Tests brauchen weder Netzwerk noch GPU, API-Schlüssel oder Sync-Server.

## Sicherheit im Browser

Jede Antwort trägt eine Content Security Policy, die nur Anki Studio selbst als Quelle für Skripte, Styles, Bilder und Verbindungen erlaubt. Der Browser blockiert dadurch jede externe Ressource. Die interaktive API-Dokumentation von FastAPI ist abgeschaltet, weil sie Dateien von einem CDN laden würde.

## Mitgelieferte Frontend-Bibliotheken

Alle Dateien liegen unter [src/anki_studio/static/vendor/](./src/anki_studio/static/vendor/) und werden ohne CDN ausgeliefert. Sie stammen unverändert aus den npm-Paketen; die sha512-Integrität der Pakete wurde gegen die npm-Registry geprüft, `SHA256SUMS` hält die Prüfsummen der Dateien fest. Lizenztexte stehen in `vendor/licenses/`.

| Bibliothek | Version | Datei | Lizenz |
|---|---|---|---|
| [htmx](https://htmx.org) | 2.0.11 | `htmx-2.0.11.min.js` | 0BSD |
| [htmx-ext-sse](https://htmx.org/extensions/sse/) | 2.2.4 | `htmx-ext-sse-2.2.4.min.js` | 0BSD |
| [Alpine.js](https://alpinejs.dev) | 3.17.5 | `alpinejs-3.17.5.min.js` | MIT |
| [Pico CSS](https://picocss.com) | 2.1.1 | `pico-2.1.1.min.css` | MIT |

## Bekannte Grenzen

- Noch keine fachliche Funktion: Generieren, Prüfen, Sync und Deployment folgen in den Phasen 2 bis 4.
- Noch kein Login (AS-030 folgt im nächsten Paket). Den Server bis dahin nur lokal oder im eigenen LAN betreiben.
- Die Vorschau im Container ersetzt nicht die Installation nach AS-040: kein eigener Systembenutzer, kein Update-Skript mit Versionswahl, keine Backups.
