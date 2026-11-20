# Anki Studio

Schlichte Web-Oberfläche für den [Anki Flashcard Generator](https://github.com/Egwe/anki-flashcard-generator), betrieben im Heimnetz und als Client des eigenen Anki-Sync-Servers.

Anforderungen und ihr Status stehen in [requirements.md](./requirements.md), Arbeitsregeln in [AGENTS.md](./AGENTS.md), die Ausgangslage in [docs/anki-studio-uebergabe.md](./docs/anki-studio-uebergabe.md).

## Stand

Das Projektgerüst und der Login stehen: Nach der Anmeldung zeigt die Startseite die installierten Versionen von Anki Studio, Generator und Anki; alle Frontend-Dateien liefert die Anwendung selbst aus. Generieren, Live-Fortschritt und Kartenprüfung folgen als nächste Pakete (Phase 2).

## Installation (lokal)

Voraussetzung ist [uv](https://docs.astral.sh/uv/). Die Python-Version steht in `.python-version` (3.13, wie im Container). Fehlt sie, installiert `uv python install 3.13` sie für uv.

```bash
uv sync
```

`uv sync` installiert die Abhängigkeiten aus `uv.lock` in `.venv`, darunter `anki==26.09.4` (genau die Version des Sync-Servers) und den Generator vom Git-Tag `v0.2.0`.

## Lokal starten

```bash
cp studio.example.yaml studio.yaml
cp .env.example .env
uv run anki-studio hash-password      # Zeile ANKI_STUDIO_PASSWORD_HASH=… in .env eintragen
uv run --env-file .env anki-studio serve --config studio.yaml
```

Danach ist die Oberfläche unter <http://127.0.0.1:8000> erreichbar. Ohne `--config` wird die Datei aus `ANKI_STUDIO_CONFIG` gelesen; ohne beides gelten die Standardwerte. Es läuft immer genau ein Serverprozess.

## Anmeldung

Jede Seite außer der Anmeldung, `/healthz` und den statischen Dateien verlangt eine Anmeldung mit einem Passwort (AS-030). Die Secrets stehen nur in der Umgebung, lokal in `.env`, im Container in `/etc/anki-studio/env` (0600):

| Variable | Bedeutung |
|---|---|
| `ANKI_STUDIO_PASSWORD_HASH` | scrypt-Hash des Passworts, erzeugt mit `anki-studio hash-password`. Fehlt er, erklärt die Anmeldeseite die Einrichtung, und niemand kann sich anmelden. |
| `ANKI_STUDIO_SESSION_SECRET` | Schlüssel für das Session-Cookie, mindestens 32 Zeichen. Fehlt er, gilt ein zufälliger Schlüssel bis zum nächsten Neustart. |

`anki-studio hash-password` fragt das Passwort zweimal ab (mindestens 8 Zeichen) und gibt nur die Zeile für die Umgebungsdatei aus. Im Container setzt dieser Aufruf vom Entwicklungsrechner das Passwort und startet die Vorschau neu:

```bash
ssh -t ct-anki-studio '/opt/anki-studio/.venv/bin/anki-studio hash-password >> /etc/anki-studio/env && systemctl restart anki-studio-preview'
```

Für ein neues Passwort vorher die alte Zeile `ANKI_STUDIO_PASSWORD_HASH=…` aus der Datei löschen.

Die Session hält 14 Tage; das Cookie ist `HttpOnly` und `SameSite=Strict`. Nach einem falschen Passwort antwortet der Server erst nach einer Sekunde. Anfragen an einen Hostnamen, der nicht in `allowed_hosts` steht, beantwortet Anki Studio mit 400 (Schutz vor DNS-Rebinding).

## Konfiguration

`studio.yaml` enthält die Einstellungen der Web-Anwendung, nicht die Generator-Konfiguration und keine Secrets. Unbekannte Schlüssel und ungültige Werte werden beim Start mit einer Meldung abgelehnt.

| Schlüssel | Standard | Bedeutung |
|---|---|---|
| `host` | `127.0.0.1` | Adresse, auf der der Server lauscht; im Container `0.0.0.0` |
| `port` | `8000` | Port der Oberfläche (1–65535) |
| `allowed_hosts` | `localhost`, `127.0.0.1` | Namen und IP-Adressen, unter denen der Browser Anki Studio aufruft, ohne Port und ohne Platzhalter |

## Vorschau im Container

Bis zur regulären Installation (AS-040, Phase 4) läuft im LXC „anki-studio“ eine Vorschau des aktuellen Stands von `main`. Nach einem Push auf `main` aktualisiert sie dieser Aufruf vom Entwicklungsrechner:

```bash
ssh ct-anki-studio 'bash -s' < deploy/preview.sh
```

Das Skript ist idempotent und erledigt Folgendes:

- installiert bei Bedarf `git` (apt) und uv 0.13.7 (mit Prüfsumme) nach `/usr/local/bin`,
- holt `main` aus GitHub als Git-Checkout nach `/opt/anki-studio`,
- installiert die Abhängigkeiten mit `uv sync --locked --no-dev` und dem System-Python 3.13 (Cache in `/var/cache/anki-studio/uv`),
- legt `/etc/anki-studio/studio.yaml` (Host `0.0.0.0`, Port 8000) und `/etc/anki-studio/env` (0600) an, falls sie fehlen, und ergänzt fehlende Einträge: `allowed_hosts` mit Hostname und Adressen des Containers sowie einen zufälligen `ANKI_STUDIO_SESSION_SECRET`; vorhandene Werte bleiben unverändert,
- startet den systemd-Dienst `anki-studio-preview` neu und prüft `/healthz`.

Der Dienst läuft ohne Root-Rechte mit einem dynamischen systemd-Benutzer; Daten landen in `/var/lib/anki-studio`. Die Oberfläche ist dann im LAN unter `http://<Container-Adresse>:8000` erreichbar. Weitere Namen, etwa der NetBird-Name, kommen von Hand in `allowed_hosts` der `/etc/anki-studio/studio.yaml`; danach den Dienst neu starten. Das Passwort setzt der Befehl im Abschnitt „Anmeldung“. Im Container wird kein Code bearbeitet (AGENTS.md Abschnitt 8).

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
- Die Verbindung ist unverschlüsseltes HTTP; Betrieb nur im LAN und über NetBird. Das Cookie trägt deshalb kein `Secure`-Attribut.
- Die Verzögerung nach falschen Passwörtern bremst nur einzelne Versuche; parallele Versuche werden nicht gezählt oder gesperrt.
- Die Vorschau im Container ersetzt nicht die Installation nach AS-040: kein eigener Systembenutzer, kein Update-Skript mit Versionswahl, keine Backups.
