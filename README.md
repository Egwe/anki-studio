# Anki Studio

Schlichte Web-Oberfläche für den [Anki Flashcard Generator](https://github.com/Egwe/anki-flashcard-generator), betrieben im Heimnetz und als Client des eigenen Anki-Sync-Servers.

Anforderungen und ihr Status stehen in [requirements.md](./requirements.md), Arbeitsregeln in [AGENTS.md](./AGENTS.md), die Ausgangslage in [docs/anki-studio-uebergabe.md](./docs/anki-studio-uebergabe.md).

## Stand

Der Web-MVP und die lokale Sync-Integration stehen: Nach der Anmeldung lassen sich API-Schlüssel eintragen, Modelle beim Provider auswählen, Dokumente hochladen und Karten erzeugen. Jede Datei wird ein Job mit Live-Fortschritt; danach werden die Karten geprüft, bearbeitet oder abgewählt und entweder in eine APKG oder nach sicherem Vor-/Nach-Sync in die lokale Anki-Sammlung geschrieben. Profile, Standardwerte und API-Schlüssel werden in der Oberfläche gepflegt. Der strukturierte PDF-Modus zeigt GPU und Modellbestand und lädt fehlende Modelle als Job. Decks lassen sich aus der zuletzt synchronisierten Sammlung oder einer APKG lesen, und Karten-JSON kann in eine APKG oder die Sammlung exportiert werden. Der echte Test gegen den eigenen Sync-Server benötigt weiterhin einen ausdrücklich freigegebenen Testbenutzer.

Ausführlich: [docs/benutzerhandbuch.html](./docs/benutzerhandbuch.html) für die Bedienung, [docs/entwicklerhandbuch.html](./docs/entwicklerhandbuch.html) für Module, Abläufe und Tests. Beide Dateien lassen sich ohne Server im Browser öffnen.

## Installation (lokal)

Voraussetzung ist [uv](https://docs.astral.sh/uv/). Die Python-Version steht in `.python-version` (3.13, wie im Container). Fehlt sie, installiert `uv python install 3.13` sie für uv.

```bash
uv sync
```

`uv sync` installiert die Abhängigkeiten aus `uv.lock` in `.venv`, darunter `anki==26.09.4` (genau die Version des Sync-Servers) und den Generator vom Git-Tag `v0.2.1`.

## Lokal starten

```bash
cp studio.example.yaml studio.yaml
cp .env.example .env
uv run anki-studio hash-password      # Zeile ANKI_STUDIO_PASSWORD_HASH=… in .env eintragen
uv run --env-file .env anki-studio serve --config studio.yaml
```

Beim ersten Start legt Anki Studio die Konfiguration des Generators als `data/generator.yaml` an, mit einem Profil für jeden unterstützten Provider (AS-015). API-Schlüssel der Profile kommen vorerst in `.env`. Danach ist die Oberfläche unter <http://127.0.0.1:8000> erreichbar. Ohne `--config` wird die Datei aus `ANKI_STUDIO_CONFIG` gelesen; ohne beides gelten die Standardwerte. Es läuft immer genau ein Serverprozess.

## Anmeldung

Jede Seite außer der Anmeldung, `/healthz` und den statischen Dateien verlangt eine Anmeldung mit einem Passwort (AS-030). Die Secrets stehen nur in der Umgebung, lokal in `.env`, im Container in `/etc/anki-studio/env` (0600):

| Variable | Bedeutung |
|---|---|
| `ANKI_STUDIO_PASSWORD_HASH` | scrypt-Hash des Passworts, erzeugt mit `anki-studio hash-password`. Fehlt er, erklärt die Anmeldeseite die Einrichtung, und niemand kann sich anmelden. |
| `ANKI_STUDIO_SESSION_SECRET` | Schlüssel für das Session-Cookie, mindestens 32 Zeichen. Fehlt er, gilt ein zufälliger Schlüssel bis zum nächsten Neustart. |
| `ANKI_STUDIO_SECRET_KEY` | Fernet-Schlüssel (32 Byte, URL-sicheres Base64), mit dem Anki Studio API-Schlüssel aus der Oberfläche verschlüsselt. Fehlt er, lassen sich dort keine Schlüssel speichern. |
| `ANKI_STUDIO_SYNC_USERNAME` | Benutzername des eigenen Anki-Sync-Servers; nur zusammen mit Passwort und `sync_endpoint` wirksam. |
| `ANKI_STUDIO_SYNC_PASSWORD` | Passwort des Sync-Benutzers; wird nie gespeichert, angezeigt oder in einen Job geschrieben. |

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
| `data_dir` | `data` | Ordner für Jobs (und später die Sammlung); relativ zur `studio.yaml`; im Container `/var/lib/anki-studio` |
| `job_retention_days` | `14` | Abgeschlossene Jobs werden nach so vielen Tagen gelöscht (1–3650) |
| `generator_config` | `<data_dir>/generator.yaml` | YAML des Generators; nur setzen, wenn sie woanders liegen soll (relativ zur `studio.yaml`) |
| `sync_endpoint` | – | HTTP(S)-Endpunkt des eigenen Anki-Sync-Servers, ohne Zugangsdaten; Benutzer und Passwort stehen nur in der Umgebung |

### Generator-Konfiguration mit allen Providern

Die Generator-YAML liegt im Datenordner, damit Anki Studio sie schreiben und später über die Oberfläche bearbeiten kann (AS-009, AS-015). Fehlt sie, entsteht sie aus der mitgelieferten Vorlage [src/anki_studio/resources/generator-template.yaml](./src/anki_studio/resources/generator-template.yaml) mit Profilen für Ollama (Text und Bild), OpenAI (auch native PDF), Anthropic, Gemini, Mistral, DeepSeek, OpenRouter, Groq, xAI, Moonshot und einen eigenen OpenAI-kompatiblen Server, Rechte 0600 und absolutem `models_dir`. Bei jedem Start ergänzt Anki Studio fehlende Standardprofile; vorhandene Profile und Werte bleiben unverändert. Gespeichert wird über `save_config` des Generators, dabei gehen Kommentare der Datei verloren. Die Vorlage enthält nur Variablennamen für Schlüssel und keine Adressen aus dem Heimnetz.

## Konfiguration in der Oberfläche

Unter **Einstellungen → Konfiguration** (AS-009, AS-016) stehen die wirksamen Werte mit ihrer Herkunft (wie `anki-flashcards config show`), alle Profile und die Standardwerte. Profile lassen sich anlegen, bearbeiten (Modell – mit „Modelle laden“ auch vor dem Speichern –, API-Basis, Schlüsselvariable, Timeout, PDF-Modus, Bildfähigkeit, Optionen als `name: wert`-Zeilen), auf die Vorlage zurücksetzen (Standardprofile) oder löschen (eigene, nicht verwendete Profile). Das Formular **Standardwerte** setzt Standardprofil, Kartenwerte und die strukturierte PDF-Aufbereitung einschließlich `formula_batch_size`. Die ganze Datei lässt sich herunterladen und durch eine hochgeladene ersetzen. Jede Änderung prüft das Schema des Generators; gespeichert wird atomar mit seinem `save_config`, wobei Kommentare der Datei verloren gehen.

## Strukturierter PDF-Modus auf der GPU

Für `pdf_mode: structured` installiert das optionale Extra `pdf` Docling über den Generator und PyTorch 2.14.1 aus dem CUDA-12.6-Index – dem Build, der die Quadro K1200 (`sm_50`) noch unterstützt (requirements.md, Abschnitt 5.3). Lokal bleibt das Extra weg (`uv sync`); im Container installiert es die Vorschau (`uv sync --extra pdf`, rund 6 GB). Der Lock gilt deshalb nur für Linux x86_64.

**Einstellungen → Modelle und GPU** (AS-010) zeigt, ob Docling installiert ist, ob PyTorch die GPU nutzen kann (sonst mit Begründung aus der Architekturprüfung des Generators), die Batch-Größe der Formelerkennung, den Modellordner und welche Modelle die Konfiguration braucht und welche vorhanden sind. **Fehlende Modelle herunterladen** lädt sie als Job mit Live-Fortschritt (rund 1,9 GB von Hugging Face). Für die K1200 gehört unter **Konfiguration → Standardwerte** bei „Formeln je Aufruf“ eine `1` hinein.

## Zugangsdaten (API-Schlüssel)

Unter **Einstellungen → Zugangsdaten** stehen alle Variablen, die Profile der Generator-YAML als `api_key_env` nennen, mit den Profilen, die sie nutzen, und ihrem Status: „aus der Umgebungsdatei“ (hat Vorrang, dort nicht änderbar), „gespeichert“ (mit Datum) oder „fehlt“. Ein eingegebener Schlüssel wird verschlüsselt in `<data_dir>/secrets.enc` gespeichert (Fernet, Rechte 0600) und nie wieder angezeigt; er lässt sich ersetzen oder löschen. Anki Studio übernimmt gespeicherte Schlüssel beim Start und nach jeder Änderung in die Umgebung des eigenen Prozesses, aus der Generator und LiteLLM sie lesen. Erlaubt sind nur Namen mit der Endung `_API_KEY`, `_TOKEN` oder `_KEY` außerhalb von `ANKI_STUDIO_*`; das Journal nennt nur den Namen. Sicherheitskonzept und Grenzen: AS-035 in [requirements.md](./requirements.md).

## Modelle des Providers

Im Formular **Generieren** steht unter dem Profil das Feld **Modell** mit dem Knopf **Modelle laden**: Anki Studio fragt den Provider des gewählten Profils nach seinen Modellen und bietet sie zur Auswahl an; die Auswahl landet im Feld, Tippen bleibt möglich (AS-014). Auf der Seite **Zugangsdaten** prüft **Prüfen**, ob ein Schlüssel funktioniert, und listet die Modelle. Unterstützt sind Ollama (`/api/tags`, ohne Schlüssel), OpenAI und OpenAI-kompatible Server, Mistral, DeepSeek, OpenRouter, Groq, xAI und Moonshot (`/models`), Anthropic (`/v1/models`) und Gemini (`/v1beta/models`, Schlüssel im Header). Abgefragt wird nur auf Knopfdruck, und dabei geht nur der API-Schlüssel an den Provider. Modelle für Embeddings, Sprache, Bilder, Moderation und Reranking blendet die Liste aus.

## Generieren und Jobs

**Generieren** (`/generate`) zeigt alle Optionen von `anki-flashcards generate`. Felder, die leer bleiben, übernimmt der Generator aus seiner YAML; die Platzhalter zeigen die wirksamen Werte, berechnet vom Generator selbst. Selten genutzte Optionen sind eingeklappt, die Optionen des strukturierten PDF-Modus erscheinen nur in diesem Modus. Ziel ist eine neue APKG, eine hochgeladene APKG (höchstens 512 MiB, nur mit einem Dokument) oder die synchronisierte Sammlung. Für das Sammlungsziel schlägt das Deck-Feld nach einem Abgleich vorhandene Namen vor und akzeptiert neue; der Job synchronisiert vor der Generierung und liest vorhandene Unterdecks nur aus der lokalen Kopie.

Geht Dokumentinhalt an einen Provider (`pdf_mode: native` oder Bild-Backend `profile` im strukturierten Modus), startet der Job nur mit ausdrücklicher Bestätigung (AS-003); der Server prüft das beim Absenden und beim Start des Jobs erneut.

Jede Datei wird ein eigener **Job**. Es läuft immer nur ein Job, weitere warten. Ein Job-Ordner `<data_dir>/jobs/<id>/` enthält `job.json` (Zustand), `events.jsonl` (Ereignisse des Generators), `upload/` (das Dokument), bei Bedarf `target/` (die APKG zum Erweitern), `cards.json` (die erzeugten Karten) und im strukturierten Modus `source.md` (der aufbereitete Text; er wird immer im Job-Ordner gespeichert). Die Job-Seite zeigt Status, Optionen und Verlauf **live** (Server-Sent Events, AS-004): einen Fortschrittsbalken für den laufenden Schritt (Abschnitte, bisher erzeugte Karten), Hinweise, Warnungen, Datenübertragungen und die Statistik der Aufbereitung; am Ende lädt sie ihren Inhalt einmal neu. Nach einem Verbindungsabbruch setzt der Browser an der letzten Stelle fort. Wartende und laufende Jobs lassen sich abbrechen. Nach einem Neustart gelten wartende und laufende Jobs als abgebrochen.

## Karten prüfen, schreiben, herunterladen

Ist ein Job fertig, zeigt seine Seite die Karten zur **Prüfung** (AS-005): Jede Karte lässt sich bearbeiten (Frage, Antwort, Unterdeck, Tags durch Leerzeichen getrennt), abwählen oder löschen; jede Änderung durchläuft die Kartenprüfung des Generators. **Ausgewählte Karten schreiben** schreibt sie mit dem gewählten Deck in eine neue oder hochgeladene APKG oder als eigenen Job in die Sammlung. Beim Sammlungsziel wird die Auswahl bis zum Ende des Schreibjobs gesperrt, vor und nach dem offiziellen Generator-Schreibvorgang sicher synchronisiert und kein APKG-Download angeboten. Die Duplikaterkennung überspringt bekannte Fragen. Danach zeigt die Seite das **Ergebnis** (AS-006) – neue und übersprungene Karten, Aufteilung nach Unterdecks und beim Sammlungsziel das Ergebnis des Nach-Syncs – sowie die passenden Downloads. Geschrieben wird je Job genau einmal; der Prüfstand liegt in `review.json`, das Ergebnis in `result.json` im Job-Ordner, `cards.json` bleibt die unveränderte Ausgabe des Generators.

Uploads werden vor dem Speichern geprüft: nur die Dokumenttypen des Generators, je höchstens 100 MiB, höchstens zehn Dateien; Anfragen ohne Längenangabe oder über der Grenze lehnt der Server ab, bevor er sie liest.

## Decks und Karten-JSON

**Decks** (`/decks`) zeigt nach einem erfolgreichen Abgleich den Baum der synchronisierten Sammlung mit direkten Kartenanzahlen. Zusätzlich liest die Seite eine hochgeladene APKG (höchstens 512 MiB) als Job; das Paket bleibt unverändert. Jeder Zugriff auf die lokale Sammlung läuft seriell über ihren eigenen Worker.

**Export** (`/export`) nimmt eine versionierte Karten-JSON (`schema_version: 1`) aus Anki Studio oder dem Generator entgegen (höchstens 100 MiB), prüft sie im Generator und schreibt sie als Job in eine neue APKG oder sicher in die Sammlung. Ein leeres Zielfeld nimmt das Standard-Deck aus der Generator-YAML; `::` trennt Unterdecks. Für das Sammlungsziel gelten derselbe Vor-/Nach-Sync und die Duplikaterkennung wie beim geprüften Generierungsjob.

## Synchronisierung

**Sync** (`/sync`) zeigt Endpunkt, Benutzer, Passwortstatus und das Ergebnis des letzten Abgleichs, aber niemals das Passwort oder den vom Server ausgegebenen `hkey`. **Jetzt synchronisieren** legt einen Job an. Beim ersten Abgleich lädt Anki Studio eine leere lokale Sammlung vollständig vom Server und öffnet sie danach korrekt neu. Schrittweise Abgleiche laufen ohne Medien-Sync.

Ein automatisch angeforderter Komplett-Upload findet nie statt. Verlangt der Server einen Komplett-Sync oder einen Komplett-Download bei lokalen, noch nicht bestätigten Änderungen, bricht Anki Studio ab und erklärt die Lage. Die lokale Sammlung liegt unter `<data_dir>/collection/`; der Sync-Status enthält keine Zugangsdaten oder `hkey`. Das Verhalten ist lokal gegen einen temporären Sync-Server getestet; echte Sync-Tests erfolgen ausschließlich mit einem eigenen freigegebenen Testbenutzer.

## Vorschau im Container

Bis zur regulären Installation (AS-040, Phase 4) läuft im LXC „anki-studio“ eine Vorschau des aktuellen Stands von `main`. Nach einem Push auf `main` aktualisiert sie dieser Aufruf vom Entwicklungsrechner:

```bash
ssh ct-anki-studio 'bash -s' < deploy/preview.sh
```

Das Skript ist idempotent und erledigt Folgendes:

- installiert bei Bedarf `git` (apt) und uv 0.13.7 (mit Prüfsumme) nach `/usr/local/bin`,
- holt `main` aus GitHub als Git-Checkout nach `/opt/anki-studio`,
- installiert die Abhängigkeiten mit `uv sync --locked --no-dev --extra pdf` (mit Docling und PyTorch für die GPU) und dem System-Python 3.13 (Cache in `/var/cache/anki-studio/uv`),
- erzeugt in `/etc/anki-studio/env` einen fehlenden `ANKI_STUDIO_SECRET_KEY`,
- ergänzt in `studio.yaml` einen fehlenden Eintrag `data_dir` (`/var/lib/anki-studio`) und entfernt den Eintrag `generator_config` und die Minimaldatei in `/etc`, die frühere Versionen des Skripts angelegt haben; die Generator-YAML liegt seitdem in `/var/lib/anki-studio/generator.yaml` und wird von Anki Studio selbst gepflegt,
- legt `/etc/anki-studio/studio.yaml` (Host `0.0.0.0`, Port 8000) und `/etc/anki-studio/env` (0600) an, falls sie fehlen, und ergänzt fehlende Einträge: `allowed_hosts` mit Hostname und Adressen des Containers sowie einen zufälligen `ANKI_STUDIO_SESSION_SECRET`; vorhandene Werte bleiben unverändert,
- startet den systemd-Dienst `anki-studio-preview` neu und prüft `/healthz`.

Der Dienst läuft ohne Root-Rechte mit einem dynamischen systemd-Benutzer; Daten landen in `/var/lib/anki-studio`. Die Oberfläche ist dann im LAN unter `http://<Container-Adresse>:8000` erreichbar. Weitere Namen, etwa der NetBird-Name, kommen von Hand in `allowed_hosts` der `/etc/anki-studio/studio.yaml`; danach den Dienst neu starten. Das Passwort setzt der Befehl im Abschnitt „Anmeldung“. Im Container wird kein Code bearbeitet (AGENTS.md Abschnitt 8).

## Reguläre Installation und Update

Nach einem geprüften und auf das öffentliche `main` gepushten Stand installiert der Projektinhaber die reguläre Instanz einmalig mit:

```bash
ssh ct-anki-studio 'bash -s' < deploy/install.sh
```

`deploy/install.sh` installiert bei Bedarf git und die festgelegte uv-Version, checkt ausschließlich `origin/main` nach `/opt/anki-studio` aus, installiert die lockfile-genauen Abhängigkeiten und richtet `anki-studio` als eigenen Systembenutzer ein. Es erhält `/etc/anki-studio/env`, `/etc/anki-studio/studio.yaml` und `/var/lib/anki-studio` unverändert, ergänzt fehlende Session- und Verschlüsselungsschlüssel und startet den gehärteten systemd-Dienst `anki-studio`. Ein Update desselben geprüften `main`-Workflows erfolgt mit:

```bash
ssh ct-anki-studio 'bash -s' < deploy/update.sh
```

`deploy/update.sh` verweigert einen fehlenden oder lokalen veränderten Produktionscheckout und ruft dann den idempotenten Installer auf. Beide Skripte prüfen zum Schluss `/healthz`. Die reguläre Installation wird erst ausgeführt, wenn dieser Codex-Stand nach `main` übernommen wurde; die bestehende `anki-studio-preview`-Vorschau bleibt davon getrennt.

Für die Arbeit auf einem lokalen Codex-Zweig gibt es zusätzlich `deploy/codex-preview.sh`. Es überträgt ausschließlich den **committeten, sauberen** lokalen Stand als `git archive` in einen eigenen Checkout, Datenordner, Systembenutzer und Dienst `anki-studio-codex-preview`; die Vorschau hat keinen Sync-Endpunkt und entfernt die Sync-Credentials aus ihrer Dienstumgebung. Sie wurde im Container zweimal erfolgreich mit Health-Check ausgeführt und ändert weder `main` noch `anki-studio-preview`.

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

- Der echte Abgleich gegen den eigenen Sync-Server und die Sichtprüfung in AnkiDroid stehen nur mit einem eigenen freigegebenen Testbenutzer aus. Deployment nach AS-040 folgt in Phase 4.
- Der strukturierte PDF-Modus läuft nur mit dem Extra `pdf`; ohne Docling bricht ein solcher Job mit einer Meldung des Generators ab. Ein laufender Modell-Download lässt sich nicht abbrechen, nur ein wartender.
- Die Verbindung ist unverschlüsseltes HTTP; Betrieb nur im LAN und über NetBird. Das Cookie trägt deshalb kein `Secure`-Attribut, und auch API-Schlüssel gehen im LAN unverschlüsselt zum Server (über NetBird im verschlüsselten Tunnel).
- Ein Backup mit Datenordner und Umgebungsdatei enthält die verschlüsselten Schlüssel zusammen mit dem Entschlüsselungsschlüssel.
- Die Verzögerung nach falschen Passwörtern bremst nur einzelne Versuche; parallele Versuche werden nicht gezählt oder gesperrt.
- Die regulären Installations- und Update-Skripte sind lokal geprüft und die isolierte Codex-Vorschau ist im Container geprüft. Die eigentliche Produktionsinstallation bleibt bis zur Übernahme nach `main` aus; ein hostseitiger vzdump-Backupablauf (AS-042) braucht eine gesonderte Freigabe für den Proxmox-Host.
