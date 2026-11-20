# Anforderungen – Anki Studio

Stand: 20.11.2026

## 1. Zweck und Geltung

Dieses Dokument ist die verbindliche Spezifikation von Anki Studio. Es übernimmt die Anforderungen aus Abschnitt 5 der Originalübergabe [docs/anki-studio-uebergabe.md](./docs/anki-studio-uebergabe.md) mit ihren stabilen IDs `AS-…` und schreibt sie fort. Die Übergabe bleibt unverändert; Abweichungen, Ergänzungen und Ergebnisse stehen hier. Wie gearbeitet wird, regelt [AGENTS.md](./AGENTS.md).

Die Begriffe **muss**, **soll** und **kann** sind verbindlich zu unterscheiden:

- **muss**: notwendige Anforderung; Abweichungen müssen ausdrücklich entschieden und dokumentiert werden.
- **soll**: verbindlicher Standard, sofern keine begründete technische Ausnahme dokumentiert ist.
- **kann**: sinnvolle spätere Erweiterung, aber kein Implementierungsauftrag (AGENTS.md Abschnitt 3).

### Statuslegende

- **umgesetzt**: im Code vorhanden und durch Tests oder einen ausgeführten Lauf belegt.
- **teilweise**: ein Teil ist umgesetzt und belegt; der Rest ist im Text benannt.
- **offen**: angefordert, aber noch nicht umgesetzt.

Der Status bezieht sich auf den Programmcode, nicht darauf, dass eine Anforderung hier beschrieben ist.

## 2. Ziel und Abgrenzung

Anki Studio ist eine schlichte Web-Oberfläche für den [Anki Flashcard Generator](https://github.com/Egwe/anki-flashcard-generator), betrieben im Heimnetz. Sie bietet alle Funktionen der CLI im Browser, schreibt geprüfte Karten als weiterer Client des eigenen Anki-Sync-Servers direkt in die Sammlung und bietet APKG- und JSON-Dateien als Alternative zum Download an (Übergabe Abschnitt 1).

Nicht Ziel sind Lernen im Browser, Zugriff aus dem Internet und mehrere Benutzer.

Die Entscheidungen zu Basis, Rolle, Generator-Einbindung, Backend, Frontend, Live-Fortschritt, Zugriff, Deployment und Name stehen in Abschnitt 2 der Übergabe und gelten unverändert.

**Änderung vom 21.11.2026 (Entscheidung des Projektinhabers):** Anki Studio soll vollständig über die Oberfläche bedienbar sein, ohne Arbeit im Container (AS-016). Dazu gehören die Generator-Konfiguration mit allen Providern (AS-015, AS-009), die Eingabe von API-Schlüsseln (AS-035) und die Auswahl der Modelle aus der Liste des Providers (AS-014). Das ersetzt für Provider-Schlüssel die Entscheidung der Übergabe „Secrets nur in der Umgebungsdatei, nicht in der Oberfläche bearbeitbar“. Login-Hash, Session-Schlüssel und der Schlüssel für die Verschlüsselung bleiben in der Umgebungsdatei.

## 3. Phasen und Stand

| Phase | Inhalt | Ort | Stand |
|---|---|---|---|
| 0 | Sync-Prototyp | lokal und gegen den echten Server | lokal erledigt (Übergabe Abschnitt 7.1); gegen den echten Server mit Testbenutzer offen |
| 0b | Container-Bestandsaufnahme und GPU-Test | Container | **erledigt** (Abschnitt 5) |
| 1 | Vorbereitung des Generators: R-170 bis R-176, Version 0.2.0 | Generator-Repo | **erledigt**: Generator 0.2.0, Git-Tag `v0.2.0`; R-170 bis R-176 dort umgesetzt (Übergabe Abschnitt 12) |
| 2 | Web-MVP: Login, Generieren, Live-Fortschritt, Prüfen, APKG- und JSON-Download | anki-studio | offen |
| 3 | Sync: Anmeldung, lokale Sammlung, Deckauswahl, Schreiben und Synchronisieren | anki-studio | offen |
| 4 | Deployment im LXC: systemd, uv, Pfade, Backup | anki-studio | offen |
| 5 | Optional: Karten durchsuchen und bearbeiten (AS-013) | anki-studio | offen |

## 4. Anforderungen

### 4.1 Oberfläche und Funktionen

**AS-001 – Generieren · muss · umgesetzt**
Mehrere Dateien hochladen (PDF, DOCX, HTML, Markdown, Text; je höchstens 100 MiB wie im Generator). Pro Datei ein Job. Alle Optionen von `anki-flashcards generate` sind wählbar: Profil, Modell, Sprache, Limit, zusätzliche Anweisungen, Chunk-Größe, Timeout, API-Basis, PDF-Modus mit den Optionen des strukturierten Modus (Formeln, OCR erzwingen, nicht lesbare Elemente zulassen, CPU zulassen, Bild-Backend, Bild-Profil, aufbereiteten Text speichern), Unterdecks. Vorbelegung aus der YAML-Konfiguration; selten genutzte Optionen eingeklappt. Optionen des strukturierten Modus nur sichtbar, wenn dieser Modus gewählt ist.
*Umsetzung:* `/generate` mit allen Optionen; Platzhalter und Vorbelegung berechnet der Generator selbst (`resolve_generate_settings`); `forms.GenerateForm` prüft Typen und Bereiche; je Datei ein Job (`tests/test_forms.py`, `tests/test_web_generate.py`, Browser-Test). *Abweichung, vom Projektinhaber am 21.11.2026 akzeptiert:* „Aufbereiteten Text speichern“ ist kein Schalter; im strukturierten Modus wird der Text immer als `source.md` im Job-Ordner gespeichert, weil die Bibliothek ein `source_text_dir` aus der YAML sonst nicht abschalten ließe und der Job-Ordner privat ist und mit dem Job gelöscht wird.

**AS-002 – Ziel wählen · muss · teilweise**
Ziel ist entweder ein Deck der synchronisierten Sammlung (Auswahl aus vorhandenen Decks oder neuer Name, `::` für Unterdecks), eine neue APKG-Datei zum Download oder eine hochgeladene APKG zum Erweitern.
*Umgesetzt:* neue APKG oder hochgeladene APKG (höchstens 512 MiB, nur mit einem Dokument) als Ziel des Jobs; Unterdeck-Kontext aus der APKG. *Offen:* Schreiben und Download nach der Prüfung (AS-005/AS-006), Sammlung als Ziel (Phase 3).

**AS-003 – Datenübertragung bestätigen · muss · umgesetzt**
Bei `pdf_mode: native` und beim Bild-Backend `profile` muss der Benutzer vor dem Start ausdrücklich bestätigen, dass das Dokument beziehungsweise Bildausschnitte an den Provider gehen. Ohne Bestätigung startet der Job nicht. Während des Laufs kommen dieselben Ankündigungen als `Notice` mit `level == "transfer"` und werden hervorgehoben.
*Umsetzung:* `generation.transfer_notice` erkennt `native` und das Bild-Backend `profile` im strukturierten Modus anhand der wirksamen Einstellungen (auch wenn das Profil den Modus vorgibt); Formular und Runner verlangen die Bestätigung; die Job-Seite hebt `transfer`-Hinweise hervor (`tests/test_generation.py`, `tests/test_web_generate.py`).

**AS-004 – Live-Fortschritt · muss · teilweise**
Job-Seite mit Live-Fortschritt aus den Generator-Ereignissen: Phase, Schritte, Abschnitte, Anzahl einzigartiger Karten, Hinweise und Warnungen, Statistik der Aufbereitung. Ein Job lässt sich abbrechen (R-172 des Generators).
*Umgesetzt:* Job-Seite mit Phase, Schritten, Abschnitten, Kartenzahl, Hinweisen, Warnungen und Statistik aus `events.jsonl`, Abbrechen für wartende und laufende Jobs. *Offen:* Live-Übertragung per SSE; bis dahin lädt sich die Seite alle drei Sekunden neu.

**AS-005 – Karten prüfen · muss · offen**
Nach der Generierung erscheinen die Karten in einer Tabelle: Frage, Antwort, Unterdeck, Tags. Einzelne Karten lassen sich bearbeiten, löschen oder abwählen. Erst danach wird geschrieben. Bearbeitete Karten durchlaufen dieselbe Pydantic-Validierung des Generators (`Card`).

**AS-006 – Ergebnis · muss · offen**
Nach dem Schreiben: hinzugefügte und übersprungene Karten, Aufteilung nach Unterdecks, Sync-Ergebnis. Downloads: APKG, Karten-JSON, aufbereiteter Text (falls erzeugt).

**AS-007 – Decks · muss · offen**
Deckbaum der synchronisierten Sammlung mit Kartenanzahl. Ebenso für eine hochgeladene APKG (entspricht `anki-flashcards decks`).

**AS-008 – Export · muss · offen**
Karten-JSON hochladen und als APKG ausgeben oder in die Sammlung schreiben (entspricht `anki-flashcards export`).

**AS-009 – Konfiguration · muss · offen**
Wirksame Werte mit Herkunft anzeigen (entspricht `config show`). Profile und Standardwerte der YAML bearbeiten, validiert über das Schema des Generators und atomar gespeichert. API-Schlüssel erscheinen nur als „gesetzt“ oder „fehlt“.
*Ergänzung 21.11.2026:* Die Generator-YAML liegt im Datenordner, damit Anki Studio sie schreiben darf (AS-015); ihre Bearbeitung über die Oberfläche ersetzt das Bearbeiten im Container (AS-016).

**AS-010 – Modelle · muss · offen**
Docling- und Bildmodelle herunterladen (entspricht `models download`), mit Fortschritt; anzeigen, ob eine GPU erkannt wird.

**AS-011 – Sync-Status · muss · offen**
Seite mit Endpunkt, angemeldetem Benutzer, Zeitpunkt und Ergebnis des letzten Syncs, Knopf „Jetzt synchronisieren“.

**AS-012 – Gestaltung · muss · teilweise**
Schlicht und aufgeräumt, gut lesbar, Dark Mode, auf Desktop und Handy bedienbar. Keine externen Ressourcen zur Laufzeit.
*Umgesetzt:* Grundlayout auf Pico CSS mit Dark Mode nach Systemeinstellung, in Desktop-Breite, 390 px Breite und dunkel im Browser geprüft. Alle Frontend-Dateien werden mitgeliefert; eine Content Security Policy erlaubt nur Anki Studio selbst als Quelle (`tests/test_app.py`). *Offen:* alle weiteren Seiten.

**AS-014 – Modelle des Providers auswählen · soll · offen**
Ist für einen Provider ein Schlüssel hinterlegt oder braucht er keinen (etwa Ollama), lädt Anki Studio auf ausdrückliche Aktion die Liste der verfügbaren Modelle beim Provider und bietet sie zur Auswahl an: im Generierungsformular und beim Bearbeiten eines Profils. Dabei geht nur der Schlüssel an den Provider, kein Dokumentinhalt. Fehler (Schlüssel ungültig, Provider nicht erreichbar) erscheinen verständlich; die freie Eingabe eines Modellnamens bleibt möglich.

**AS-015 – Vorlage mit allen Providern · muss · umgesetzt**
Die Generator-Konfiguration enthält immer ein Profil für jeden unterstützten Provider, auch ohne hinterlegten Schlüssel: Ollama (Text und Bild), OpenAI (auch native PDF), Anthropic, Google Gemini, Mistral, DeepSeek, OpenRouter, Groq, xAI, Moonshot und ein eigener OpenAI-kompatibler Server. Fehlt die Datei, legt Anki Studio sie aus einer mitgelieferten Vorlage an; fehlende Standardprofile ergänzt es beim Start, vorhandene Profile bleiben unverändert. Die Datei liegt im Datenordner (`<data_dir>/generator.yaml`), `pdf_conversion.models_dir` ist dort absolut. Die Vorlage im Repository enthält keine Adressen aus dem Heimnetz.
*Umsetzung:* `resources/generator-template.yaml`, `generator_config.ensure_generator_config` beim Start (`tests/test_generator_config.py`, `tests/test_app.py`). In der Vorschau liegt seit dem 21.11.2026 die Konfiguration des Projektinhabers als Ausgangspunkt (`input_dir`/`output_dir` entfernt, `models_dir` absolut, vertauschte Ausgabegrenzen der OpenAI-Profile korrigiert); die übrigen Standardprofile ergänzt Anki Studio.

**AS-016 – Bedienung ohne Container-Zugriff · muss · offen**
Alles, was im täglichen Betrieb eingestellt wird, geht über die Oberfläche: Generator-Konfiguration und Profile (AS-009, AS-015), API-Schlüssel (AS-035), Modellwahl (AS-014), später Sync-Zugang und Login-Passwort. Shell-Zugriff auf den Container bleibt für Installation, Updates und Notfälle.

**AS-013 – Karten in der Sammlung durchsuchen und bearbeiten · kann · offen**
Suche über `col.find_notes`, Bearbeiten und Löschen generierter Notizen. Zurückgestellt auf Phase 5.

### 4.2 Sync

**AS-020 – Anmeldung · muss · offen**
Endpunkt in der Konfiguration von Anki Studio, Benutzername und Passwort in der Umgebungsdatei. Anmeldung über `Collection.sync_login(username, password, endpoint)`; das Ergebnis (`SyncAuth` mit `hkey`, `endpoint`) wird verwendet, das Passwort nicht weiter gespeichert oder angezeigt.

**AS-021 – Erster Abgleich · muss · offen**
Ist die lokale Kopie leer, antwortet `sync_collection` mit `FULL_DOWNLOAD`. Anki Studio lädt die Sammlung dann herunter: `col.close_for_full_sync()`, `col.full_upload_or_download(auth=auth, server_usn=None, upload=False)`, danach **`col.reopen(after_full_sync=True)`**. Ein einfaches `reopen()` scheitert mit `CollectionAlreadyOpen` (im Prototyp beobachtet).

**AS-022 – Normaler Sync · muss · offen**
Vor jedem Schreiben in die Sammlung und danach `col.sync_collection(auth, sync_media=False)`. Diese Funktion führt den schrittweisen Sync selbst aus; das Feld `required` sagt, was **danach noch** nötig ist (`SyncCollectionResponse.ChangesRequired`):

| `required` | Bedeutung nach `sync_collection` | Reaktion |
|---|---|---|
| `NO_CHANGES` | Schrittweiser Sync erledigt (auch wenn Änderungen übertragen wurden) | fertig |
| `FULL_DOWNLOAD` | Server verlangt Komplett-Download | nur erlaubt, wenn lokal nichts verloren geht (AS-023) |
| `FULL_UPLOAD` | Server verlangt Komplett-Upload | **nie automatisch** (AS-023) |
| `FULL_SYNC` | Konflikt, Richtung muss gewählt werden | abbrechen und erklären |
| `NORMAL_SYNC` | gehört zu `sync_status()`, nicht zum Ergebnis von `sync_collection` | – |

Liefert der Server `new_endpoint`, wird dieser übernommen. `server_message` wird angezeigt, falls nicht leer.

**AS-023 – Kein automatischer Komplett-Upload · muss · offen**
Ein Komplett-Upload überschreibt die Daten auf dem Server und damit auf allen Geräten. Er findet niemals automatisch statt. Verlangt der Server einen Komplett-Sync, während die lokale Kopie eigene, noch nicht gesendete Änderungen hat, bricht Anki Studio ab und erklärt die Lage. Ein Komplett-Download ist nur erlaubt, wenn lokal nichts verloren geht.

**AS-024 – Nicht in die Server-Daten schreiben · muss · offen**
Anki Studio schreibt nie direkt in `/opt/anki-sync-server/data` oder eine andere Server-Datei. Das umgeht die Sync-Buchhaltung und beschädigt die Synchronisierung.

**AS-025 – Serieller Zugriff · muss · offen**
Die pylib-Sammlung ist nicht threadsicher. Alle Zugriffe auf die Sammlung laufen nacheinander über einen Worker. Generierung (KI, Docling) läuft außerhalb dieser Sperre.

**AS-026 – Medien · kann · offen**
Medien-Sync (`sync_media`) erst, wenn Karten Bilder oder Audio enthalten (R-205 des Generators). Zurückgestellt bis dahin.

### 4.3 Betrieb und Sicherheit

**AS-030 – Login · muss · umgesetzt**
Ein Passwort; nur sein Hash steht in der Umgebungsdatei. Session-Cookie `HttpOnly`, `SameSite=Strict`. Prüfung des `Host`-Headers gegen eine Liste erlaubter Namen.
*Umsetzung:* scrypt-Hash aus der Standardbibliothek in `ANKI_STUDIO_PASSWORD_HASH`, erzeugt mit `anki-studio hash-password`; signiertes Session-Cookie `anki_studio_session` (`HttpOnly`, `SameSite=Strict`, 14 Tage); alle Seiten außer Anmeldung, `/healthz` und statischen Dateien verlangen die Anmeldung; `allowed_hosts` in `studio.yaml`, fremde Hosts erhalten 400. Belegt durch `tests/test_auth.py`, `tests/test_hosts.py`, `tests/test_passwords.py` und einen Browser-Test (hell, dunkel, schmal).

**AS-031 – Secrets · muss · teilweise**
Login-Hash, Session-Schlüssel, Schlüssel der Verschlüsselung und Sync-Zugangsdaten nur in der Umgebungsdatei. API-Schlüssel der Provider in der Umgebungsdatei oder, über die Oberfläche eingegeben, verschlüsselt im Datenordner (AS-035; Änderung vom 21.11.2026, ursprünglich nur Umgebungsdatei). Die YAML enthält wie im Generator nur Variablennamen (`api_key_env`). Keine Secrets in Logs, Job-Dateien, Fehlermeldungen oder der Oberfläche.
*Umgesetzt:* Login-Hash und Session-Schlüssel kommen nur aus der Umgebung; Fehlermeldungen nennen die Variable, nie den Wert; `repr` blendet die Werte aus (`tests/test_credentials.py`). *Offen:* API-Schlüssel (AS-035) und Sync-Zugangsdaten (mit AS-020).

**AS-032 – Jobs · muss · teilweise**
Ein Job läuft zur Zeit (eine GPU, ein Benutzer); weitere warten in einer Warteschlange. Jeder Job hat einen Ordner mit Upload, Ereignisprotokoll, Karten-JSON und Ergebnis. Nach einem Neustart sind abgeschlossene Jobs weiter sichtbar; laufende gelten als abgebrochen. Alte Jobs werden nach einer einstellbaren Frist gelöscht.
*Umgesetzt:* Dienste `jobs.JobStore` (Ordner `<data_dir>/jobs/<id>` mit `job.json`, `events.jsonl`, `upload/`) und `worker.JobWorker` (ein Thread, Warteschlange, Abbruch, Wiederanlauf: wartende und laufende Jobs gelten nach einem Neustart als abgebrochen, Löschfrist `job_retention_days`), belegt durch `tests/test_jobs.py` und `tests/test_worker.py`. Seit P4 startet die Anwendung den Worker; `cards.json` liegt im Job-Ordner. *Offen:* das Ergebnis des Schreibens im Job-Ordner (AS-006).

**AS-033 – Uploads · muss · umgesetzt**
Größengrenze vor dem Speichern prüfen, Dateinamen nie ungeprüft als Pfad verwenden, Uploads nur im Job-Ordner ablegen.
*Umgesetzt:* `uploads.py` bereinigt Dateinamen, lässt nur die Dokumenttypen des Generators zu, prüft die gemeldete Größe vor dem Schreiben und zählt beim Kopieren erneut; der Job-Ordner entsteht erst nach der Prüfung (`tests/test_uploads.py`, `tests/test_jobs.py`). Die Route `/generate` prüft alle Dateien vor dem Anlegen eines Jobs; `limits.BodyLimitMiddleware` lehnt POST-Anfragen ohne Längenangabe (411) oder über der Grenze (413) ab, bevor der Körper gelesen wird (`tests/test_limits.py`).

**AS-035 – API-Schlüssel über die Oberfläche · muss · offen**
API-Schlüssel der Provider lassen sich in der Oberfläche setzen, ersetzen und löschen. Sicherheitskonzept:
- *Nur schreibend:* Die Oberfläche zeigt je Variable nur Herkunft und Status („aus der Umgebungsdatei“, „gespeichert am …“, „fehlt“), nie den Wert, auch nicht teilweise.
- *Verschlüsselt:* Gespeicherte Schlüssel liegen als Fernet-Token (AES-128-CBC mit HMAC-SHA256, Bibliothek `cryptography`) in `<data_dir>/secrets.enc`, Rechte 0600, atomar ersetzt. Der Schlüssel dafür, `ANKI_STUDIO_SECRET_KEY`, steht nur in der Umgebungsdatei und wird vom Installations- beziehungsweise Vorschau-Skript erzeugt. Fehlt er, ist Speichern nicht möglich; es gibt keinen Klartext-Ersatz.
- *Begrenzte Namen:* Nur Variablen aus Großbuchstaben, Ziffern und Unterstrich mit der Endung `_API_KEY`, `_TOKEN` oder `_KEY`, nie `ANKI_STUDIO_*`. So lässt sich über die Oberfläche keine andere Umgebungsvariable setzen (etwa `PATH` oder `LD_PRELOAD`).
- *Vorrang:* Werte aus der Umgebungsdatei gelten und sind in der Oberfläche nicht änderbar. Gespeicherte Werte übernimmt Anki Studio beim Start und nach jeder Änderung in die Umgebung des eigenen Prozesses, aus der Generator (`api_key_env`) und LiteLLM lesen.
- *Keine Spuren:* keine Werte in Logs, Job-Dateien, Ereignissen, Fehlermeldungen oder HTML; protokolliert wird nur „Schlüssel X geändert“.
- *Grenzen, ausdrücklich dokumentiert:* Im LAN läuft die Eingabe wie das Login-Passwort über unverschlüsseltes HTTP (über NetBird ist der Tunnel verschlüsselt). Ein Backup mit Datenordner und Umgebungsdatei enthält Schlüssel und verschlüsselte Datei zusammen; die Verschlüsselung schützt Kopien des Datenordners ohne Umgebungsdatei, etwa ausgelagerte Job-Ordner. HTTPS bleibt eine spätere Option.

**AS-034 – Tests · muss · teilweise**
Reguläre Tests laufen ohne Netzwerk, ohne echten Sync-Server, ohne API-Schlüssel und ohne GPU. KI-Aufrufe werden wie im Generator simuliert (Patch-Ziel `anki_flashcards.pipeline.generate_cards` usw. oder `report`/`cancel`-Argumente). Für Sync-Tests eignet sich ein lokal gestarteter `python -m anki.syncserver` mit Testbenutzer auf `127.0.0.1` (Prototyp in Abschnitt 7.1 der Übergabe).
*Umgesetzt:* Testgerüst mit pytest und FastAPI-`TestClient`, ohne Netzwerk, GPU, Schlüssel und Sync-Server. *Offen:* simulierte KI-Läufe und Sync-Tests mit den jeweiligen Funktionen.

### 4.4 Deployment (R-201 des Generators)

**AS-040 – Installation · muss · offen**
Im LXC „anki-studio“: eigener Systembenutzer statt root; Programm mit uv in `/opt/anki-studio`; Daten in `/var/lib/anki-studio`; Konfiguration `/etc/anki-studio/config.yaml` (Generator-YAML) und `/etc/anki-studio/studio.yaml` (Endpunkt, Datenpfade, Port); Secrets in `/etc/anki-studio/env` (0600) als `EnvironmentFile`; systemd-Unit mit uvicorn. Ein Installations- und Update-Skript im Repo (`deploy/`).
*Änderung 21.11.2026:* Die Generator-YAML liegt im Datenordner (`/var/lib/anki-studio/generator.yaml`), weil sie über die Oberfläche bearbeitet wird (AS-015, AS-016); `/etc/anki-studio` enthält nur `studio.yaml` und `env`.

**AS-041 – GPU · soll · offen**
Strukturierter Modus mit der durchgereichten GPU, sofern der GPU-Test (Abschnitt 5.3) sie als nutzbar bestätigt. Sonst dokumentieren, welche Ausweichwege gelten.
*Stand:* Der GPU-Test bestätigt die K1200 mit PyTorch `cu126` als nutzbar; Formeln brauchen eine kleinere Batch-Größe (Abschnitt 5.3). *Offen:* Installation des Extras `pdf` mit PyTorch aus dem `cu126`-Index in Anki Studio.

**AS-042 – Backup · soll · offen**
vzdump beider Container. Maßgeblich sind die Daten des Sync-Servers; die Sammlung von Anki Studio ist eine Kopie und lässt sich neu herunterladen.

**AS-043 – Community-Script · kann · offen**
Daraus ein eigenes Proxmox-Community-Script (`ct/` + `install/`) machen. Zurückgestellt bis nach Phase 4.

## 5. Zielsystem: Container „anki-studio“

### 5.1 Bestandsaufnahme (20.11.2026, nur lesend)

Zugang mit `ssh ct-anki-studio`. Erhoben mit `os-release`, `uname`, `lscpu`, `free`, `df`, `nvidia-smi`, `/proc/driver/nvidia/version`, `ldconfig`, `systemctl`, `getent`, `ss` und HTTP-Statusabfragen.

| Punkt | Befund |
|---|---|
| System | Debian 13.7 (trixie), unprivilegierter LXC (UID 0 im Container → 100000 auf dem Host), Proxmox-Kernel 7.0.14-25-pve |
| CPU | 1 vCPU (Host: Intel Xeon W-2145, 16 Threads); **nach Anpassung am 20.11.2026: 4 vCPU** |
| Arbeitsspeicher | 2 GiB, 512 MiB Swap; **nach Anpassung: 8 GiB** |
| Platte | Root-Dateisystem 9,8 GB, davon 6,8 GB frei; **nach Anpassung: 32 GB** |
| GPU | NVIDIA Quadro K1200: Maxwell, Compute Capability 5.0 (`sm_50`), 4096 MiB, im Leerlauf 0 MiB belegt |
| Treiber | 580.173.02. Kernelmodul auf dem Host und Userspace im Container haben dieselbe Version. Der Userspace stammt aus dem NVIDIA-`.run`-Installer mit `--no-kernel-module`, nicht aus Debian-Paketen. `nvidia-smi` funktioniert und meldet CUDA 13.0 als höchste vom Treiber unterstützte Version. |
| Geräte | `/dev/nvidia2`, `/dev/nvidiactl`, `/dev/nvidia-uvm`, `/dev/nvidia-uvm-tools` durchgereicht; `libcuda.so.1` und `libnvidia-ml.so.1` vorhanden; kein `/dev/dri` |
| Python und Werkzeuge | System-Python 3.13.5; nicht installiert: uv, pip, git, gcc; `curl` vorhanden. git und uv kommen seit dem 20.11.2026 mit der Vorschau (Abschnitt 5.4). |
| Dienste | nur Grunddienste: ssh, cron, dbus, journald, logind, networkd, postfix (nur lokal); keine fehlgeschlagenen Units. Offener Port nach außen: 22 (SSH nur mit Schlüssel, `PasswordAuthentication no`). |
| Benutzer | nur `root` und `nobody`; Gruppen `video` und `render` vorhanden, ohne Mitglieder |
| Verzeichnisse | `/opt` leer; `/var/lib/anki-studio` und `/etc/anki-studio` existieren nicht |
| Netz | HTTPS zu PyPI, `download.pytorch.org`, GitHub und Hugging Face erreichbar |
| Zeit und Pakete | Zeitzone Europe/Berlin, Uhr synchron; keine ausstehenden Paket-Updates |

### 5.2 Bewertung

- **Treiber:** Host und Container passen zusammen. Nach Ankündigung von NVIDIA ist der Treiberzweig 580 der letzte mit Unterstützung für Maxwell. Ein späteres Treiber-Update auf dem Host würde die K1200 deshalb unbrauchbar machen und ist vorher zu prüfen.
- **PyTorch-Builds:** Für die K1200 kommen nur Builds infrage, die `sm_50` enthalten. `cu130` scheidet aus, weil CUDA 13 Maxwell nicht mehr unterstützt. Nach den Release-Hinweisen von PyTorch fehlt `sm_50` auch in den `cu128`-Builds ab 2.8. Der Index `download.pytorch.org` bietet am 20.11.2026 `cu126`-Builds bis Torch 2.14.1 und `cu118`-Builds bis 2.7.1 an. Ob die aktuellen `cu126`-Builds `sm_50` noch enthalten, klärt der GPU-Test; `cu118` mit Torch 2.7.1 ist der Ausweichweg (`docling-ibm-models` verlangt `torch>=2.2.2,<3`).
- **GPU-Erkennung des Generators:** `docling_pdf.available_accelerator()` prüft nur `torch.cuda.is_available()`. Das liefert auch mit einem Build ohne `sm_50` `True`; PyTorch warnt dann nur, und der Fehler „no kernel image is available for execution on the device“ kommt erst während der Aufbereitung. Der GPU-Test muss deshalb echte CUDA-Operationen ausführen. Eine genauere Prüfung im Generator wäre eine Änderung im Generator-Repo und erfolgt nur nach Absprache (AGENTS.md Abschnitt 5).
- **Ressourcen:** 2 GiB Arbeitsspeicher reichen für den strukturierten Modus voraussichtlich nicht; der Generator hat auf der CPU 2,5–3 GB während der Aufbereitung gemessen. PyTorch mit CUDA-Bibliotheken belegt in der virtuellen Umgebung ein Vielfaches der 2,2 GB der CPU-Variante, die Modelle weitere rund 1,9 GB. 6,8 GB freier Platz reichen dafür nicht. 1 vCPU bremst Installation, PDF-Parsing und OCR. Die Ressourcen des Containers ändert der Projektinhaber auf dem Proxmox-Host.
- **Ohne strukturierten Modus** (`local`, `native`) genügen die vorhandenen Ressourcen für Anki Studio voraussichtlich.

### 5.3 GPU-Test (20.11.2026)

Vom Projektinhaber freigegeben und nach der Anpassung der Ressourcen ausgeführt. Alles lag in einem Testordner unter `/root`, der danach vollständig gelöscht wurde, einschließlich des Testdokuments; weder Pakete noch Caches sind zurückgeblieben.

**Stufe A – PyTorch allein**

| Punkt | Ergebnis |
|---|---|
| Build | `torch 2.14.1+cu126` und `torchvision 0.29.1+cu126` aus dem `cu126`-Index, System-Python 3.13, uv 0.13.7 |
| `sm_50` | enthalten: `torch.cuda.get_arch_list()` liefert `sm_50`, `sm_60`, `sm_70`, `sm_75`, `sm_80`, `sm_86`, `sm_90` |
| Echte Rechnungen | Matrixmultiplikation fp32 und fp16, cuDNN-Faltung und `torchvision.ops.nms` laufen auf der K1200 ohne Fehler |
| Größe | virtuelle Umgebung 6,3 GB, mit Docling 7,2 GB; Installation ohne Cache knapp 3 Minuten |

**Stufe B – Docling über den Generator 0.2.0**

Aufruf über die öffentliche Schnittstelle `pipeline.produce_cards`, die Kartenerzeugung durch eine Attrappe ersetzt; gemessen wird also nur die Aufbereitung. Testdokument ist dieselbe 15-seitige Vorlesung (EL1, V03), die auf der CPU nach über 50 Minuten noch nicht fertig war (README des Generators). Docling 2.151.1; der Download aller Modelle (1,9 GB) dauerte 96 Sekunden.

| Lauf | Einstellungen | Dauer | VRAM-Spitze | RAM-Spitze | Ergebnis |
|---|---|---|---|---|---|
| 1 | Formeln aus, Bild-Backend `none` | 40,6 s | 1,5 GiB | 2,4 GiB | 15 Seiten, OCR auf allen Seiten |
| 2 | Formeln an, Bild-Backend `local` | 181,5 s | 3,5 GiB | 3,1 GiB | 18 Abbildungen beschrieben (rund 5 s je Abbildung); **30 von 32 Formelblöcken unlesbar**, weil das Formelmodell je Batch 1,5–2,1 GiB zusätzlich anfordert (CUDA out of memory) |
| 3 | wie Lauf 2, aber Formelmodell mit Batch-Größe 1 und Bild-Backend `none` (Experiment) | 284,1 s | 3,8 GiB | 2,6 GiB | **alle 32 Formelblöcke als LaTeX**, nichts unlesbar |

Lauf 2 überschnitt sich 14 Sekunden mit der ersten Vorschau-Installation; das ändert die Größenordnung nicht. Die inhaltliche Qualität der Bildbeschreibungen wurde nicht bewertet.

**Bewertung**

- Die K1200 ist für den strukturierten Modus nutzbar. Zu verwenden ist PyTorch aus dem `cu126`-Index; `cu128` und `cu130` scheiden aus (Abschnitt 5.2).
- Formeln scheitern mit der festen Batch-Größe 5 des Docling-Formelmodells am VRAM. Der Generator 0.2.0 bietet dafür keine Einstellung, und Anki Studio darf Docling oder den Generator nicht selbst patchen (AGENTS.md Abschnitt 5). Lösung wäre eine Option im Generator, etwa eine Batch-Größe für das Formelmodell; das ist ein eigenes Paket im Generator-Repo nach Absprache. Bis dahin sind Formeln auf der K1200 nur mit `formulas: false` verlässlich; mit `formulas: true` bricht der Generator korrekt mit einer Liste unlesbarer Formeln ab.
- Mit Formeln ist der VRAM fast voll (3,8 GiB von 4 GiB). Ein zweiter GPU-Prozess hätte keinen Platz; das passt zu einem Job zur Zeit (AS-032).
- Docling meldete, dass es den Kernel-Cache unter `models/cache/torch/kernels` nicht anlegen konnte. Das schaltet nur diesen Cache ab und hatte keine sichtbare Auswirkung.

### 5.4 Vorschau-Betrieb

Seit dem 20.11.2026 läuft im Container eine Vorschau des Stands von `main` als systemd-Dienst `anki-studio-preview` auf Port 8000, eingerichtet und aktualisiert mit `deploy/preview.sh` (README, Abschnitt „Vorschau im Container“; Regeln in AGENTS.md Abschnitt 8). Sie ersetzt nicht die Installation nach AS-040.

Zugriff von unterwegs: NetBird führt über einen Routing-Peer ins Heimnetz; die Oberfläche wird auch dann unter der LAN-Adresse des Containers und Port 8000 aufgerufen. Weitere Hostnamen in `allowed_hosts` sind dafür nicht nötig (Auskunft des Projektinhabers vom 21.11.2026).

## 6. Offene Punkte und Risiken

| Punkt | Umgang |
|---|---|
| `anki`-Version des Sync-Servers | Vom Projektinhaber bestätigt: 26.09.4, in `pyproject.toml` genau gepinnt; nur gemeinsam mit einem Server-Update anheben |
| Sync gegen den echten Server | Prototyp-Ablauf mit eigenem Testbenutzer wiederholen und das Ergebnis in AnkiDroid prüfen (Phase 0); die echte Sammlung bleibt unberührt |
| Erster Import des Notiztyps erzwingt Komplett-Sync | Lokal widerlegt (Übergabe Abschnitt 7.1); gegen den echten Server bestätigen |
| GPU K1200 mit aktuellem PyTorch | Nutzbar mit `cu126` (Abschnitt 5.3); vor einem PyTorch- oder Treiber-Update erneut prüfen |
| Formeln auf 4 GiB VRAM | Batch-Größe des Formelmodells im Generator einstellbar machen (Abschnitt 5.3); vom Projektinhaber am 21.11.2026 für Generator 0.2.1 freigegeben |
| GPU-Erkennung meldet `cuda` trotz fehlendem `sm_50` | Mit `cu126` kein Problem; bleibt ein Risiko, falls ein Build ohne `sm_50` installiert wird. Genauere Prüfung im Generator 0.2.1 (freigegeben am 21.11.2026). |
| Stabile GUIDs des Generators | Wird eine generierte Notiz in ein anderes Deck verschoben und dieselbe Frage im ursprünglichen Deck erneut erzeugt, entsteht eine zweite Notiz mit gleicher GUID. Für Sync unkritisch, bei späteren APKG-Importen zu beachten. |
| Relative Pfade in der YAML | `pdf_conversion.models_dir` absolut setzen; `input_dir`, `output_dir`, `source_text_dir` und `generation.json_output` nicht verwenden, Pfade je Job ausdrücklich übergeben |
| Prozessweite Umgebungsvariablen | `model_storage.configure_model_storage()` setzt Cache-Variablen für den ganzen Prozess; unkritisch bei einem Modellordner pro Prozess |
| `tenacity` fehlt in den Abhängigkeiten | LiteLLM braucht es für `num_retries` des Generators, aber weder LiteLLM 1.110 noch der Generator 0.2.0 deklarieren es; ohne es scheitert jeder KI-Aufruf. Anki Studio führt es als direkte Abhängigkeit. Im Generator 0.2.1 deklarieren (freigegeben am 21.11.2026); danach entfällt die direkte Abhängigkeit hier. |
| Aufbereiteter Text immer im Job-Ordner | Abweichung von AS-001, vom Projektinhaber am 21.11.2026 akzeptiert |
| Lizenz | Das `anki`-Paket ist AGPL-3.0; für den privaten Betrieb unkritisch, vor einer Veröffentlichung von Anki Studio klären |
| Unverschlüsseltes HTTP zum Sync-Server | Nur LAN beziehungsweise NetBird; nicht ins Internet öffnen |

## 7. Paketplan und Arbeitsstand

Jedes Paket ist ein Branch mit kleinen Commits, wird nach grünen Prüfungen mit `--no-ff` nach `main` gemergt, sofort gepusht und danach mit `deploy/preview.sh` in die Vorschau gebracht (AGENTS.md Abschnitte 3 und 8). Diese Tabelle wird bei jedem Merge aktualisiert, damit jede weitere Person oder KI den Stand sofort findet.

| Paket | Branch | Inhalt | IDs | Stand |
|---|---|---|---|---|
| P0 | – | Repository, Übergabe, Requirements, Bestandsaufnahme, GPU-Test | – | erledigt |
| P1 | `feature/project-skeleton` | Gerüst, Einstellungen, mitgelieferte Frontend-Dateien, Startseite, CSP | AS-012, AS-034 | erledigt |
| P1b | `feature/container-preview` | Vorschau im Container | – | erledigt |
| P2 | `feature/login` | Login, Session, Host-Prüfung | AS-030, AS-031 | erledigt |
| P3 | `feature/job-queue` | Uploads, Job-Ordner, Worker | AS-032, AS-033 | erledigt |
| P4 | `feature/generate` | Formular, Runner, Job-Seiten, Handbücher | AS-001–AS-004 | erledigt |
| P4b | `feature/provider-template` | Vorlage mit allen Providern, Generator-YAML im Datenordner, Konfiguration des Projektinhabers in die Vorschau | AS-015, AS-009 (Teil) | erledigt |
| P4c | `feature/secret-store` | API-Schlüssel verschlüsselt über die Oberfläche | AS-035, AS-031 | als Nächstes |
| P4d | `feature/model-list` | Modelle vom Provider laden und auswählen | AS-014 | offen |
| P5 | `feature/live-progress` | Live-Fortschritt per SSE | AS-004 | offen |
| P6 | `feature/card-review` | Karten prüfen, bearbeiten, abwählen; APKG schreiben; Downloads | AS-005, AS-006 | offen |
| P7 | `feature/config-editor` | Konfiguration anzeigen (Herkunft) und Profile und Standardwerte bearbeiten | AS-009, AS-016 | offen |
| G1 | Generator-Repo | Generator 0.2.1: `tenacity`, Batch-Größe Formeln, genauere GPU-Prüfung; danach Anki Studio auf `v0.2.1` | – | freigegeben, offen |
| P8 | `feature/structured-mode` | Extra `pdf` mit PyTorch `cu126`, Modelle laden, GPU-Anzeige | AS-041, AS-010 | offen |
| P9 | `feature/decks-export` | Decks einer APKG, Export Karten-JSON → APKG | AS-007, AS-008 (APKG-Teile) | offen |
| Phase 3 | `feature/sync-…` | Sync-Client, Sammlung als Ziel, Sync-Status; braucht einen Testbenutzer des Projektinhabers | AS-020–AS-025, AS-002, AS-006, AS-007, AS-008, AS-011 | offen |
| Phase 4 | `feature/deploy-…` | Installation und Update nach AS-040, Backup | AS-040, AS-042 | offen |

**Übernahme durch eine andere Person oder KI:** `AGENTS.md` lesen, dann `git log --oneline --first-parent main` für die erledigten Pakete und diese Tabelle für das nächste. Prüfungen: `uv sync`, `ruff check`, `ruff format --check`, `pytest` (README). Die Vorschau aktualisiert `ssh ct-anki-studio 'bash -s' < deploy/preview.sh`.
