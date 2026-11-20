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

Nicht Ziel sind Lernen im Browser, Zugriff aus dem Internet, mehrere Benutzer und das Bearbeiten von API-Schlüsseln in der Oberfläche.

Die Entscheidungen zu Basis, Rolle, Generator-Einbindung, Backend, Frontend, Live-Fortschritt, Zugriff, Secrets, Deployment und Name stehen in Abschnitt 2 der Übergabe und gelten unverändert.

## 3. Phasen und Stand

| Phase | Inhalt | Ort | Stand |
|---|---|---|---|
| 0 | Sync-Prototyp | lokal und gegen den echten Server | lokal erledigt (Übergabe Abschnitt 7.1); gegen den echten Server mit Testbenutzer offen |
| 0b | Container-Bestandsaufnahme und GPU-Test | Container | Bestandsaufnahme erledigt (Abschnitt 5); GPU-Test offen |
| 1 | Vorbereitung des Generators: R-170 bis R-176, Version 0.2.0 | Generator-Repo | **erledigt**: Generator 0.2.0, Git-Tag `v0.2.0`; R-170 bis R-176 dort umgesetzt (Übergabe Abschnitt 12) |
| 2 | Web-MVP: Login, Generieren, Live-Fortschritt, Prüfen, APKG- und JSON-Download | anki-studio | offen |
| 3 | Sync: Anmeldung, lokale Sammlung, Deckauswahl, Schreiben und Synchronisieren | anki-studio | offen |
| 4 | Deployment im LXC: systemd, uv, Pfade, Backup | anki-studio | offen |
| 5 | Optional: Karten durchsuchen und bearbeiten (AS-013) | anki-studio | offen |

## 4. Anforderungen

### 4.1 Oberfläche und Funktionen

**AS-001 – Generieren · muss · offen**
Mehrere Dateien hochladen (PDF, DOCX, HTML, Markdown, Text; je höchstens 100 MiB wie im Generator). Pro Datei ein Job. Alle Optionen von `anki-flashcards generate` sind wählbar: Profil, Modell, Sprache, Limit, zusätzliche Anweisungen, Chunk-Größe, Timeout, API-Basis, PDF-Modus mit den Optionen des strukturierten Modus (Formeln, OCR erzwingen, nicht lesbare Elemente zulassen, CPU zulassen, Bild-Backend, Bild-Profil, aufbereiteten Text speichern), Unterdecks. Vorbelegung aus der YAML-Konfiguration; selten genutzte Optionen eingeklappt. Optionen des strukturierten Modus nur sichtbar, wenn dieser Modus gewählt ist.

**AS-002 – Ziel wählen · muss · offen**
Ziel ist entweder ein Deck der synchronisierten Sammlung (Auswahl aus vorhandenen Decks oder neuer Name, `::` für Unterdecks), eine neue APKG-Datei zum Download oder eine hochgeladene APKG zum Erweitern.

**AS-003 – Datenübertragung bestätigen · muss · offen**
Bei `pdf_mode: native` und beim Bild-Backend `profile` muss der Benutzer vor dem Start ausdrücklich bestätigen, dass das Dokument beziehungsweise Bildausschnitte an den Provider gehen. Ohne Bestätigung startet der Job nicht. Während des Laufs kommen dieselben Ankündigungen als `Notice` mit `level == "transfer"` und werden hervorgehoben.

**AS-004 – Live-Fortschritt · muss · offen**
Job-Seite mit Live-Fortschritt aus den Generator-Ereignissen: Phase, Schritte, Abschnitte, Anzahl einzigartiger Karten, Hinweise und Warnungen, Statistik der Aufbereitung. Ein Job lässt sich abbrechen (R-172 des Generators).

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

**AS-010 – Modelle · muss · offen**
Docling- und Bildmodelle herunterladen (entspricht `models download`), mit Fortschritt; anzeigen, ob eine GPU erkannt wird.

**AS-011 – Sync-Status · muss · offen**
Seite mit Endpunkt, angemeldetem Benutzer, Zeitpunkt und Ergebnis des letzten Syncs, Knopf „Jetzt synchronisieren“.

**AS-012 – Gestaltung · muss · offen**
Schlicht und aufgeräumt, gut lesbar, Dark Mode, auf Desktop und Handy bedienbar. Keine externen Ressourcen zur Laufzeit.

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

**AS-030 – Login · muss · offen**
Ein Passwort; nur sein Hash steht in der Umgebungsdatei. Session-Cookie `HttpOnly`, `SameSite=Strict`. Prüfung des `Host`-Headers gegen eine Liste erlaubter Namen.

**AS-031 – Secrets · muss · offen**
API-Schlüssel der Provider, Sync-Zugangsdaten und Login-Hash nur in der Umgebungsdatei. Die YAML enthält wie im Generator nur Variablennamen (`api_key_env`). Keine Secrets in Logs, Job-Dateien, Fehlermeldungen oder der Oberfläche.

**AS-032 – Jobs · muss · offen**
Ein Job läuft zur Zeit (eine GPU, ein Benutzer); weitere warten in einer Warteschlange. Jeder Job hat einen Ordner mit Upload, Ereignisprotokoll, Karten-JSON und Ergebnis. Nach einem Neustart sind abgeschlossene Jobs weiter sichtbar; laufende gelten als abgebrochen. Alte Jobs werden nach einer einstellbaren Frist gelöscht.

**AS-033 – Uploads · muss · offen**
Größengrenze vor dem Speichern prüfen, Dateinamen nie ungeprüft als Pfad verwenden, Uploads nur im Job-Ordner ablegen.

**AS-034 – Tests · muss · offen**
Reguläre Tests laufen ohne Netzwerk, ohne echten Sync-Server, ohne API-Schlüssel und ohne GPU. KI-Aufrufe werden wie im Generator simuliert (Patch-Ziel `anki_flashcards.pipeline.generate_cards` usw. oder `report`/`cancel`-Argumente). Für Sync-Tests eignet sich ein lokal gestarteter `python -m anki.syncserver` mit Testbenutzer auf `127.0.0.1` (Prototyp in Abschnitt 7.1 der Übergabe).

### 4.4 Deployment (R-201 des Generators)

**AS-040 – Installation · muss · offen**
Im LXC „anki-studio“: eigener Systembenutzer statt root; Programm mit uv in `/opt/anki-studio`; Daten in `/var/lib/anki-studio`; Konfiguration `/etc/anki-studio/config.yaml` (Generator-YAML) und `/etc/anki-studio/studio.yaml` (Endpunkt, Datenpfade, Port); Secrets in `/etc/anki-studio/env` (0600) als `EnvironmentFile`; systemd-Unit mit uvicorn. Ein Installations- und Update-Skript im Repo (`deploy/`).

**AS-041 – GPU · soll · offen**
Strukturierter Modus mit der durchgereichten GPU, sofern der GPU-Test (Abschnitt 5.3) sie als nutzbar bestätigt. Sonst dokumentieren, welche Ausweichwege gelten.

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
| CPU | 1 vCPU (Host: Intel Xeon W-2145, 16 Threads) |
| Arbeitsspeicher | 2 GiB, 512 MiB Swap |
| Platte | Root-Dateisystem 9,8 GB, davon 6,8 GB frei |
| GPU | NVIDIA Quadro K1200: Maxwell, Compute Capability 5.0 (`sm_50`), 4096 MiB, im Leerlauf 0 MiB belegt |
| Treiber | 580.173.02. Kernelmodul auf dem Host und Userspace im Container haben dieselbe Version. Der Userspace stammt aus dem NVIDIA-`.run`-Installer mit `--no-kernel-module`, nicht aus Debian-Paketen. `nvidia-smi` funktioniert und meldet CUDA 13.0 als höchste vom Treiber unterstützte Version. |
| Geräte | `/dev/nvidia2`, `/dev/nvidiactl`, `/dev/nvidia-uvm`, `/dev/nvidia-uvm-tools` durchgereicht; `libcuda.so.1` und `libnvidia-ml.so.1` vorhanden; kein `/dev/dri` |
| Python und Werkzeuge | System-Python 3.13.5; nicht installiert: uv, pip, git, gcc; `curl` vorhanden |
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

### 5.3 GPU-Test

Offen. Ablauf, Messwerte und Ergebnis werden hier dokumentiert, sobald der Projektinhaber die nötigen Installationen im Container freigegeben hat.

## 6. Offene Punkte und Risiken

| Punkt | Umgang |
|---|---|
| `anki`-Version des Sync-Servers | Voraussichtlich 26.09.4; vom Projektinhaber zu bestätigen, dann in `pyproject.toml` genau pinnen und nur gemeinsam mit einem Server-Update anheben |
| Sync gegen den echten Server | Prototyp-Ablauf mit eigenem Testbenutzer wiederholen und das Ergebnis in AnkiDroid prüfen (Phase 0); die echte Sammlung bleibt unberührt |
| Erster Import des Notiztyps erzwingt Komplett-Sync | Lokal widerlegt (Übergabe Abschnitt 7.1); gegen den echten Server bestätigen |
| GPU K1200 mit aktuellem PyTorch | GPU-Test (Abschnitt 5.3); bis dahin gelten die Ausweichwege `local` und `native` |
| GPU-Erkennung meldet `cuda` trotz fehlendem `sm_50` | Abschnitt 5.2; im GPU-Test belegen und danach über eine Änderung im Generator entscheiden |
| Ressourcen des Containers | Abschnitt 5.2; Anpassung durch den Projektinhaber vor dem GPU-Test mit Docling |
| Stabile GUIDs des Generators | Wird eine generierte Notiz in ein anderes Deck verschoben und dieselbe Frage im ursprünglichen Deck erneut erzeugt, entsteht eine zweite Notiz mit gleicher GUID. Für Sync unkritisch, bei späteren APKG-Importen zu beachten. |
| Relative Pfade in der YAML | `pdf_conversion.models_dir` absolut setzen; `input_dir`, `output_dir`, `source_text_dir` und `generation.json_output` nicht verwenden, Pfade je Job ausdrücklich übergeben |
| Prozessweite Umgebungsvariablen | `model_storage.configure_model_storage()` setzt Cache-Variablen für den ganzen Prozess; unkritisch bei einem Modellordner pro Prozess |
| Lizenz | Das `anki`-Paket ist AGPL-3.0; für den privaten Betrieb unkritisch, vor einer Veröffentlichung von Anki Studio klären |
| Unverschlüsseltes HTTP zum Sync-Server | Nur LAN beziehungsweise NetBird; nicht ins Internet öffnen |
