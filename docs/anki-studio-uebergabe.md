# Übergabe: Anki Studio

Web-Oberfläche für den Anki Flashcard Generator mit Anbindung an einen selbst betriebenen Anki-Sync-Server.

- **Stand:** 20.11.2026, Generator-Version **0.2.0** (Git-Tag `v0.2.0`)
- **Quelle:** Repository [Egwe/anki-flashcard-generator](https://github.com/Egwe/anki-flashcard-generator), Datei `docs/anki-studio-uebergabe.md`
- **Leser:** die Claude-Code-Session im neuen Repository „anki-studio“ und der Projektinhaber

Diese Datei ist die Ausgangslage für das neue Projekt. Sie fasst zusammen, was entschieden ist, welche Infrastruktur schon läuft, was ein lokaler Prototyp bereits bestätigt hat und welche Schnittstellen der Generator anbietet. Fachliche Details zum Generator stehen in dessen `requirements.md` (Abschnitt 13: R-170 bis R-176), `README.md`, `docs/benutzerhandbuch.html` und `docs/entwicklerhandbuch.html` (Modulkarten `pipeline.py` und `apkg.py`).

**Schnelleinstieg:** Abschnitt 1 und 2 (Ziel, Entscheidungen) → Abschnitt 3 (Infrastruktur, SSH) → Abschnitt 11 (Schnittstellen mit Codebeispielen) → Abschnitt 7 (Vorgehen).

---

## 1. Ziel

Anki Studio ist eine schlichte, schöne Web-Oberfläche für den Anki Flashcard Generator, betrieben im Heimnetz.

1. **Alle Funktionen der CLI im Browser:** Dokumente hochladen, Karten erzeugen, alle Optionen einstellen, Konfiguration ansehen und bearbeiten, Modelle herunterladen, JSON nach APKG exportieren, Decks ansehen.
2. **Karten landen direkt auf allen Geräten:** Anki Studio ist ein weiterer Client des eigenen Anki-Sync-Servers. Geprüfte Karten werden in die Sammlung geschrieben und synchronisiert. Danach erscheinen sie in Anki Desktop und AnkiDroid nach deren nächstem Sync.
3. **APKG bleibt als Alternative:** Statt in die Sammlung zu schreiben, kann jedes Ergebnis als APKG- oder JSON-Datei heruntergeladen werden.

### Ausdrücklich nicht Ziel

- **Lernen im Browser.** Zum Lernen gibt es Anki Desktop und AnkiDroid. Anki Studio wird kein vollständiger Anki-Client.
- **Zugriff aus dem Internet.** Nur im LAN; von unterwegs über das vorhandene NetBird-VPN.
- **Mehrere Benutzer.** Ein Benutzer, ein Login.
- **API-Schlüssel in der Oberfläche bearbeiten.** Schlüssel stehen in einer Umgebungsdatei auf dem Server.

---

## 2. Getroffene Entscheidungen

| Thema | Entscheidung | Begründung |
|---|---|---|
| Basis | **Eigene Anwendung**, nicht auf [aitsc/ankiweb](https://github.com/aitsc/ankiweb) aufbauen | ankiweb hat Sync ausdrücklich ausgeschlossen, übernimmt die originale Anki-Oberfläche als kompilierte Bundles (nicht umgestaltbar), pinnt `anki==25.9.4` (Generator und Server nutzen 26.09.4) und ist AGPL-3.0. Ein Fork wäre mehr Arbeit, nicht weniger. |
| Muster aus ankiweb | Als Vorlage lesen, nicht kopieren | Brauchbar: Sammlungszugriff seriell über einen Worker mit `asyncio.Lock` (pylib ist nicht threadsicher), Passwort-Login mit Session-Cookie, Prüfung des `Host`-Headers, Zwischenablage für Uploads. Bei Übernahme von Code gilt AGPL. |
| Rolle | Anki Studio ist ein **Sync-Client** wie Desktop und AnkiDroid | Der Sync-Server ist die zentrale Datenquelle. Das offizielle `anki`-Paket enthält die Client-Sync-Funktionen. |
| Generator-Einbindung | **Python-Abhängigkeit über Git-Tag**, kein Git-Submodul | Gleich gute Versionsfestlegung, einfacheres Deployment (`uv sync`). Für gleichzeitige Entwicklung an beiden Repos eine lokale editable-Quelle per uv. |
| Backend | **FastAPI** + uvicorn | Python wie der Generator; Pydantic-Modelle des Generators direkt nutzbar. |
| Frontend | **Jinja2 + HTMX + Alpine.js + Pico CSS** | Kein Node-Build, alles in Python testbar (pytest + `TestClient`), schlichtes und sauberes Aussehen mit Dark Mode. Alle Frontend-Dateien werden mitgeliefert (kein CDN), damit es offline im LAN funktioniert. Falls Pico zu schlicht wird: Tailwind + DaisyUI über die eigenständige Tailwind-CLI. |
| Live-Fortschritt | Server-Sent Events | Der Generator meldet strukturierte Ereignisse (R-171); SSE reicht für eine Richtung und funktioniert mit dem HTMX-SSE-Plugin. |
| Lernen im Browser | **Nicht bauen** | Entscheidung des Projektinhabers. |
| Zugriff | **Nur LAN**, von außen über NetBird-VPN | Kein Reverse Proxy mit öffentlichem HTTPS nötig. Login bleibt trotzdem Pflicht, weil hinter der App API-Schlüssel und damit Kosten stehen. |
| Secrets | **Nur Umgebungsdatei** auf dem Server (`EnvironmentFile` der systemd-Unit, Rechte 0600) | Entscheidung des Projektinhabers; das Projekt richtet sich an technisch versierte Nutzer. Die Oberfläche zeigt nur „gesetzt“ oder „fehlt“. |
| Deployment | **Eigener LXC** auf Proxmox, systemd, uv; nicht im Container des Sync-Servers | Dessen Community-Update-Skript baut seine Python-Umgebung neu. Getrennte Aufgaben, getrennte Backups. |
| Name | „Anki Studio“ (Paket `anki_studio`) | „AnkiWeb“ ist der Name des offiziellen Dienstes von Ankitects. |

---

## 3. Vorhandene Infrastruktur

### 3.1 Anki-Sync-Server (läuft, getestet)

Installiert mit dem Proxmox-Community-Script [anki-sync-server](https://community-scripts.org/scripts/anki-sync-server). Desktop und AnkiDroid sind verbunden; Karten vom Desktop erscheinen auf dem Handy.

Angaben aus dem Script (Stand 20.11.2026, auf dem Server zu prüfen):

| Punkt | Wert |
|---|---|
| Basis | Debian 13, unprivilegierter LXC, 1 vCPU, 512 MB RAM, 4 GB Disk |
| Installation | `uv venv --python 3.12 /opt/anki-sync-server/venv`, darin pip-Paket `anki==<neueste GitHub-Release>` (bei Installation 26.09.4) |
| Dienst | systemd-Unit `anki-sync-server`, `ExecStart=/opt/anki-sync-server/venv/bin/python -m anki.syncserver`, läuft als root |
| Konfiguration | `/opt/anki-sync-server/.env` (0600): `SYNC_USER1=anki:<zufälliges Passwort>`, `SYNC_BASE=/opt/anki-sync-server/data`, `SYNC_HOST=0.0.0.0`, `SYNC_PORT=8080` |
| Endpunkt | `http://<IP des Sync-LXC>:8080/` (unverschlüsseltes HTTP, nur LAN/VPN) |
| Weitere Benutzer | Zusätzliche Zeilen `SYNC_USER2=name:passwort` in der `.env`, danach Dienst neu starten |
| Updates | Update-Funktion des Community-Scripts: stoppt den Dienst, sichert `.env` und `data`, installiert die neueste `anki`-Release, startet neu |

**Version beachten:** Der Server sollte nicht älter sein als die Clients. Anki Studio pinnt deshalb genau die `anki`-Version des Servers (zurzeit voraussichtlich `26.09.4`, auf dem Server prüfen) und wird bei einem Server-Update im selben Schritt angehoben. Der Generator erlaubt `anki>=24.11,<27`.

### 3.2 Container für Anki Studio (angelegt)

- Eigener LXC auf demselben Proxmox-Host ist bereits angelegt.
- **GPU-Durchreichung ist eingerichtet:** NVIDIA Quadro K1200.
- **SSH-Zugang vom Rechner des Projektinhabers ist eingerichtet.** Die Claude-Session im Anki-Studio-Repo darf sich per SSH verbinden, den Container untersuchen und einrichten. Hostname oder Alias beim Projektinhaber erfragen oder in dessen `~/.ssh/config` nachsehen. Adressen und Zugangsdaten gehören nicht ins Repository.
- Vor Änderungen am Container (Pakete, Dienste, Benutzer) kurz mit dem Projektinhaber abstimmen; reine Bestandsaufnahme ist unkritisch.

Erste Bestandsaufnahme im Container (Vorschlag):

```bash
cat /etc/os-release; uname -r; nproc; free -h; df -h /
nvidia-smi                        # Treiber, CUDA-Version, Speicher
ls -l /dev/nvidia*                # durchgereichte Geräte
python3 --version; command -v uv
getent hosts <sync-lxc>; curl -sS -o /dev/null -w '%{http_code}\n' http://<sync-lxc>:8080/
```

### 3.3 Die GPU (NVIDIA Quadro K1200) – zu prüfen

Die K1200 ist eine Maxwell-Karte (GM107, Compute Capability 5.0, 4 GB GDDR5). Ob sie für den strukturierten PDF-Modus des Generators (Docling, R-158) taugt, ist offen:

- Neuere PyTorch-CUDA-Builds unterstützen ältere Architekturen teils nicht mehr. Prüfen mit `python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_arch_list())"`. `sm_50` muss in der Liste stehen, sonst einen älteren CUDA-Build von PyTorch (z. B. `cu126`) testen.
- Der Treiber im Container muss zur Version des Host-Treibers passen.
- 4 GB VRAM sind knapp, wenn Docling und das lokale Bildmodell gleichzeitig laden. Messen statt vermuten.
- Der Generator erkennt die GPU über `anki_flashcards.docling_pdf.available_accelerator()` (gibt `"cuda"` – auch für ROCm –, `"xpu"`, `"mps"` oder `None` zurück; braucht das Extra `pdf` mit PyTorch). Damit lässt sich der Test direkt mit dem Generator machen.
- **Ausweichwege, falls die Karte nicht reicht:** `pdf_mode: native` (Upload an einen freigegebenen Provider), `allow_cpu` mit `formulas: false` für kurze Dokumente, Bildbeschreibung über ein Profil (z. B. Ollama auf einem Rechner mit stärkerer GPU) oder `pdf_mode: local`.

Der Generator nimmt keinen stillen Moduswechsel vor (R-158); Anki Studio darf das auch nicht.

---

## 4. Architektur

```
 Browser (LAN / NetBird)
        │  HTTP, SSE
        ▼
 ┌───────────────────────── LXC „anki-studio“ ─────────────────────────┐
 │ FastAPI + Jinja2/HTMX                                               │
 │   ├─ Auth (ein Passwort, Session-Cookie, Host-Prüfung)              │
 │   ├─ Jobs (ein Worker-Thread, Job-Ordner, Ereignisse → SSE)         │
 │   │     └─ anki_flashcards.pipeline (Generator 0.2.0)               │
 │   ├─ Sammlung (lokale Kopie, serieller Zugriff)                     │
 │   └─ Sync (sync_login, sync_collection, Schutz vor Komplett-Upload) │
 │ /var/lib/anki-studio: collection/, jobs/, models/                    │
 └───────────────────────────────┬─────────────────────────────────────┘
                                 │ Anki-Sync-Protokoll (HTTP, LAN)
                                 ▼
 ┌──────────── LXC „anki-sync-server“ ────────────┐
 │ python -m anki.syncserver  :8080              │ ◄── Anki Desktop
 │ /opt/anki-sync-server/data (maßgebliche Daten) │ ◄── AnkiDroid
 └────────────────────────────────────────────────┘
```

### Ablauf einer Generierung

```
Upload → Job anlegen → pipeline.produce_cards()  (local | structured | native)
       → Karten-JSON im Job-Ordner → Prüfen/Bearbeiten im Browser
       → Ziel wählen:
           a) Sammlung: Sync holen → pipeline.write_collection() → Sync senden
           b) Download: pipeline.write_apkg() (neu oder hochgeladene APKG erweitern); JSON-Download
```

---

## 5. Anforderungen an Anki Studio

Begriffe wie im Generator: **muss**, **soll**, **kann**. IDs mit Präfix `AS-`. Status aller Anforderungen: offen.

### 5.1 Oberfläche und Funktionen

**AS-001 – Generieren · muss**
Mehrere Dateien hochladen (PDF, DOCX, HTML, Markdown, Text; je höchstens 100 MiB wie im Generator). Pro Datei ein Job. Alle Optionen von `anki-flashcards generate` sind wählbar: Profil, Modell, Sprache, Limit, zusätzliche Anweisungen, Chunk-Größe, Timeout, API-Basis, PDF-Modus mit den Optionen des strukturierten Modus (Formeln, OCR erzwingen, nicht lesbare Elemente zulassen, CPU zulassen, Bild-Backend, Bild-Profil, aufbereiteten Text speichern), Unterdecks. Vorbelegung aus der YAML-Konfiguration; selten genutzte Optionen eingeklappt. Optionen des strukturierten Modus nur sichtbar, wenn dieser Modus gewählt ist.

**AS-002 – Ziel wählen · muss**
Ziel ist entweder ein Deck der synchronisierten Sammlung (Auswahl aus vorhandenen Decks oder neuer Name, `::` für Unterdecks), eine neue APKG-Datei zum Download oder eine hochgeladene APKG zum Erweitern.

**AS-003 – Datenübertragung bestätigen · muss**
Bei `pdf_mode: native` und beim Bild-Backend `profile` muss der Benutzer vor dem Start ausdrücklich bestätigen, dass das Dokument beziehungsweise Bildausschnitte an den Provider gehen. Ohne Bestätigung startet der Job nicht. Während des Laufs kommen dieselben Ankündigungen als `Notice` mit `level == "transfer"` und werden hervorgehoben.

**AS-004 – Live-Fortschritt · muss**
Job-Seite mit Live-Fortschritt aus den Generator-Ereignissen: Phase, Schritte, Abschnitte, Anzahl einzigartiger Karten, Hinweise und Warnungen, Statistik der Aufbereitung. Ein Job lässt sich abbrechen (R-172 des Generators).

**AS-005 – Karten prüfen · muss**
Nach der Generierung erscheinen die Karten in einer Tabelle: Frage, Antwort, Unterdeck, Tags. Einzelne Karten lassen sich bearbeiten, löschen oder abwählen. Erst danach wird geschrieben. Bearbeitete Karten durchlaufen dieselbe Pydantic-Validierung des Generators (`Card`).

**AS-006 – Ergebnis · muss**
Nach dem Schreiben: hinzugefügte und übersprungene Karten, Aufteilung nach Unterdecks, Sync-Ergebnis. Downloads: APKG, Karten-JSON, aufbereiteter Text (falls erzeugt).

**AS-007 – Decks · muss**
Deckbaum der synchronisierten Sammlung mit Kartenanzahl. Ebenso für eine hochgeladene APKG (entspricht `anki-flashcards decks`).

**AS-008 – Export · muss**
Karten-JSON hochladen und als APKG ausgeben oder in die Sammlung schreiben (entspricht `anki-flashcards export`).

**AS-009 – Konfiguration · muss**
Wirksame Werte mit Herkunft anzeigen (entspricht `config show`). Profile und Standardwerte der YAML bearbeiten, validiert über das Schema des Generators und atomar gespeichert. API-Schlüssel erscheinen nur als „gesetzt“ oder „fehlt“.

**AS-010 – Modelle · muss**
Docling- und Bildmodelle herunterladen (entspricht `models download`), mit Fortschritt; anzeigen, ob eine GPU erkannt wird.

**AS-011 – Sync-Status · muss**
Seite mit Endpunkt, angemeldetem Benutzer, Zeitpunkt und Ergebnis des letzten Syncs, Knopf „Jetzt synchronisieren“.

**AS-012 – Gestaltung · muss**
Schlicht und aufgeräumt, gut lesbar, Dark Mode, auf Desktop und Handy bedienbar. Keine externen Ressourcen zur Laufzeit.

**AS-013 – Karten in der Sammlung durchsuchen und bearbeiten · kann · später**
Suche über `col.find_notes`, Bearbeiten und Löschen generierter Notizen.

### 5.2 Sync

**AS-020 – Anmeldung · muss**
Endpunkt in der Konfiguration von Anki Studio, Benutzername und Passwort in der Umgebungsdatei. Anmeldung über `Collection.sync_login(username, password, endpoint)`; das Ergebnis (`SyncAuth` mit `hkey`, `endpoint`) wird verwendet, das Passwort nicht weiter gespeichert oder angezeigt.

**AS-021 – Erster Abgleich · muss**
Ist die lokale Kopie leer, antwortet `sync_collection` mit `FULL_DOWNLOAD`. Anki Studio lädt die Sammlung dann herunter: `col.close_for_full_sync()`, `col.full_upload_or_download(auth=auth, server_usn=None, upload=False)`, danach **`col.reopen(after_full_sync=True)`**. Ein einfaches `reopen()` scheitert mit `CollectionAlreadyOpen` (im Prototyp beobachtet).

**AS-022 – Normaler Sync · muss**
Vor jedem Schreiben in die Sammlung und danach `col.sync_collection(auth, sync_media=False)`. Diese Funktion führt den schrittweisen Sync selbst aus; das Feld `required` sagt, was **danach noch** nötig ist (`SyncCollectionResponse.ChangesRequired`):

| `required` | Bedeutung nach `sync_collection` | Reaktion |
|---|---|---|
| `NO_CHANGES` | Schrittweiser Sync erledigt (auch wenn Änderungen übertragen wurden) | fertig |
| `FULL_DOWNLOAD` | Server verlangt Komplett-Download | nur erlaubt, wenn lokal nichts verloren geht (AS-023) |
| `FULL_UPLOAD` | Server verlangt Komplett-Upload | **nie automatisch** (AS-023) |
| `FULL_SYNC` | Konflikt, Richtung muss gewählt werden | abbrechen und erklären |
| `NORMAL_SYNC` | gehört zu `sync_status()`, nicht zum Ergebnis von `sync_collection` | – |

Liefert der Server `new_endpoint`, wird dieser übernommen. `server_message` wird angezeigt, falls nicht leer.

**AS-023 – Kein automatischer Komplett-Upload · muss**
Ein Komplett-Upload überschreibt die Daten auf dem Server und damit auf allen Geräten. Er findet niemals automatisch statt. Verlangt der Server einen Komplett-Sync, während die lokale Kopie eigene, noch nicht gesendete Änderungen hat, bricht Anki Studio ab und erklärt die Lage. Ein Komplett-Download ist nur erlaubt, wenn lokal nichts verloren geht.

**AS-024 – Nicht in die Server-Daten schreiben · muss**
Anki Studio schreibt nie direkt in `/opt/anki-sync-server/data` oder eine andere Server-Datei. Das umgeht die Sync-Buchhaltung und beschädigt die Synchronisierung.

**AS-025 – Serieller Zugriff · muss**
Die pylib-Sammlung ist nicht threadsicher. Alle Zugriffe auf die Sammlung laufen nacheinander über einen Worker. Generierung (KI, Docling) läuft außerhalb dieser Sperre.

**AS-026 – Medien · kann · später**
Medien-Sync (`sync_media`) erst, wenn Karten Bilder oder Audio enthalten (R-205 des Generators).

### 5.3 Betrieb und Sicherheit

**AS-030 – Login · muss**
Ein Passwort; nur sein Hash steht in der Umgebungsdatei. Session-Cookie `HttpOnly`, `SameSite=Strict`. Prüfung des `Host`-Headers gegen eine Liste erlaubter Namen.

**AS-031 – Secrets · muss**
API-Schlüssel der Provider, Sync-Zugangsdaten und Login-Hash nur in der Umgebungsdatei. Die YAML enthält wie im Generator nur Variablennamen (`api_key_env`). Keine Secrets in Logs, Job-Dateien, Fehlermeldungen oder der Oberfläche.

**AS-032 – Jobs · muss**
Ein Job läuft zur Zeit (eine GPU, ein Benutzer); weitere warten in einer Warteschlange. Jeder Job hat einen Ordner mit Upload, Ereignisprotokoll, Karten-JSON und Ergebnis. Nach einem Neustart sind abgeschlossene Jobs weiter sichtbar; laufende gelten als abgebrochen. Alte Jobs werden nach einer einstellbaren Frist gelöscht.

**AS-033 – Uploads · muss**
Größengrenze vor dem Speichern prüfen, Dateinamen nie ungeprüft als Pfad verwenden, Uploads nur im Job-Ordner ablegen.

**AS-034 – Tests · muss**
Reguläre Tests laufen ohne Netzwerk, ohne echten Sync-Server, ohne API-Schlüssel und ohne GPU. KI-Aufrufe werden wie im Generator simuliert (Patch-Ziel `anki_flashcards.pipeline.generate_cards` usw. oder `report`/`cancel`-Argumente). Für Sync-Tests eignet sich ein lokal gestarteter `python -m anki.syncserver` mit Testbenutzer auf `127.0.0.1` (siehe Prototyp in Abschnitt 7.1).

### 5.4 Deployment (R-201 des Generators)

**AS-040 – Installation · muss**
Im LXC „anki-studio“: eigener Systembenutzer statt root; Programm mit uv in `/opt/anki-studio`; Daten in `/var/lib/anki-studio`; Konfiguration `/etc/anki-studio/config.yaml` (Generator-YAML) und `/etc/anki-studio/studio.yaml` (Endpunkt, Datenpfade, Port); Secrets in `/etc/anki-studio/env` (0600) als `EnvironmentFile`; systemd-Unit mit uvicorn. Ein Installations- und Update-Skript im Repo (`deploy/`).

**AS-041 – GPU · soll**
Strukturierter Modus mit der durchgereichten GPU, sofern Abschnitt 3.3 sie als nutzbar bestätigt. Sonst dokumentieren, welche Ausweichwege gelten.

**AS-042 – Backup · soll**
vzdump beider Container. Maßgeblich sind die Daten des Sync-Servers; die Sammlung von Anki Studio ist eine Kopie und lässt sich neu herunterladen.

**AS-043 – Community-Script · kann · später**
Daraus ein eigenes Proxmox-Community-Script (`ct/` + `install/`) machen.

---

## 6. Repository-Aufbau (Vorschlag)

```
anki-studio/
  pyproject.toml           # fastapi, uvicorn, jinja2, python-multipart, sse-starlette o. ä.,
                           # anki==<Server-Version>,
                           # anki-flashcard-generator @ git+https://github.com/Egwe/anki-flashcard-generator@v0.2.0
                           # optional-dependencies: pdf = ["anki-flashcard-generator[pdf] @ …"] für Docling
  src/anki_studio/
    app.py                 # App-Factory, Middleware (Auth, Host-Prüfung)
    auth.py
    settings.py            # Einstellungen von Anki Studio (Pfade, Endpunkt, Port)
    jobs.py                # Warteschlange, Worker-Thread, Job-Ordner, Ereignisse
    collection.py          # lokale Sammlung, serieller Zugriff
    sync.py                # Login, Sync, Schutz vor Komplett-Upload
    routes/                # generate, review, decks, export, config, models, sync
    templates/  static/    # htmx, alpine, pico: mitgeliefert, kein CDN
  deploy/                  # systemd-Unit, install.sh, update.sh, env.example
  tests/
  AGENTS.md  README.md  requirements.md
```

Einbindung des Generators während der Entwicklung (Nachbar-Checkout):

```toml
[tool.uv.sources]
anki-flashcard-generator = { path = "../anki-flashcard-generator", editable = true }
```

Für das Deployment den Git-Tag verwenden. Der Remote des Generators ist `git@github.com:Egwe/anki-flashcard-generator.git`. Ist das Repository privat, braucht der Container einen Deploy-Key oder ein Token mit Lesezugriff.

Arbeitsweise: Die Regeln aus `AGENTS.md` des Generators (Branch je Anforderungspaket, kleine Commits, Docstrings an jeder Funktion, Never Nesting, Ruff mit `C90`/`D`, pytest, ehrlicher Requirement-Status) sollten in ein eigenes `AGENTS.md` von Anki Studio übernommen werden.

---

## 7. Vorgehen

| Phase | Inhalt | Ort | Stand |
|---|---|---|---|
| 0 | **Sync-Prototyp** | lokal und gegen den echten Server | lokal erledigt (7.1); gegen den echten Server mit Testbenutzer offen |
| 0b | **Container-Bestandsaufnahme** per SSH (Abschnitt 3.2) und GPU-Test (Abschnitt 3.3) | Container | offen |
| 1 | Vorbereitung des Generators: R-170 bis R-176, Version 0.2.0 | Generator-Repo | **erledigt** (Abschnitt 12) |
| 2 | Web-MVP: Login, Generieren, Live-Fortschritt, Prüfen, APKG- und JSON-Download | anki-studio | offen |
| 3 | Sync: Anmeldung, lokale Sammlung, Deckauswahl, Schreiben und Synchronisieren | anki-studio | offen |
| 4 | Deployment im LXC: systemd, uv, Pfade, Backup | anki-studio | offen |
| 5 | Optional: Karten durchsuchen und bearbeiten (AS-013) | anki-studio | offen |

### 7.1 Ergebnis des lokalen Sync-Prototyps (20.11.2026)

Aufbau: `python -m anki.syncserver` (anki 26.09.4) auf `127.0.0.1` mit Testbenutzer, ein „Desktop“-Client und ein „Anki-Studio“-Client, beide mit pylib 26.09.4 und dem Generator 0.2.0.

| Schritt | Beobachtung |
|---|---|
| Desktop legt eine Notiz an, erster Sync gegen leeren Server | `FULL_UPLOAD`; Komplett-Upload wie erwartet |
| Anki Studio mit leerer Sammlung: `sync_login`, `sync_collection` | `hkey` gesetzt; `FULL_DOWNLOAD` |
| Komplett-Download | gelingt mit `close_for_full_sync()` → `full_upload_or_download(upload=False)` → `reopen(after_full_sync=True)`; Notiz vorhanden |
| `apkg.collection_subdeck_context(col, "EL1")` | vorhandenes Unterdeck des Desktops erkannt |
| `pipeline.write_collection(...)` mit neuem Notiztyp „KI Karteikarte (Front/Back)“, danach `sync_collection` | **`NO_CHANGES`: normaler Sync, kein Komplett-Sync** |
| Zweite Karte, Sync | `NO_CHANGES` |
| Desktop-Sync | `NO_CHANGES`; Desktop hat alle 3 Notizen und das neue Unterdeck |

Noch zu prüfen: derselbe Ablauf gegen den echten Server mit einem eigenen Testbenutzer (`SYNC_USER2=test:…`) und das Ergebnis in AnkiDroid. Die echte Sammlung bleibt dabei unberührt.

---

## 8. Risiken und offene Punkte

| Punkt | Umgang |
|---|---|
| GPU K1200 mit aktuellem PyTorch | Abschnitt 3.3; Ergebnis dokumentieren |
| Erster Import des Notiztyps erzwingt Komplett-Sync | Lokal widerlegt (7.1); gegen den echten Server bestätigen |
| Versionsabstand `anki` Server ↔ Anki Studio | Gleiche Version pinnen; Updates gemeinsam |
| Stabile GUIDs des Generators (`genanki.guid_for(deck, normalisierte Frage)`) | Wird eine generierte Notiz in ein anderes Deck verschoben und dieselbe Frage im ursprünglichen Deck erneut erzeugt, entsteht eine zweite Notiz mit gleicher GUID. Für Sync unkritisch (Sync nutzt Notiz-IDs); bei späteren APKG-Importen zu beachten. |
| Relative Pfade in der YAML | Werden relativ zur YAML-Datei aufgelöst. Mit `/etc/anki-studio/config.yaml` landeten Modelle sonst in `/etc/anki-studio/models`. In Anki Studio `pdf_conversion.models_dir` absolut setzen (z. B. `/var/lib/anki-studio/models`); `input_dir`, `output_dir`, `source_text_dir` und `generation.json_output` nicht verwenden, sondern Pfade je Job ausdrücklich übergeben. |
| Prozessweite Umgebungsvariablen | `model_storage.configure_model_storage()` setzt Cache-Variablen (Hugging Face, Torch) für den ganzen Prozess. Unkritisch bei einem Modellordner pro Prozess. |
| Lizenz | Das `anki`-Paket ist AGPL-3.0. Für den privaten Betrieb unkritisch; vor einer Veröffentlichung von Anki Studio klären. |
| Unverschlüsseltes HTTP zum Sync-Server | Nur LAN beziehungsweise NetBird; nicht ins Internet öffnen. |

---

## 9. Was der Generator ab 0.2.0 bereitstellt

| Bereich | Modul | Nutzen |
|---|---|---|
| Abläufe | `anki_flashcards.pipeline` | Alle CLI-Abläufe ohne Oberfläche; Ereignisse; Abbruch; getrenntes Erzeugen und Schreiben; Sammlung als Ziel |
| Konfiguration | `anki_flashcards.config`: `AppConfig`, `load_config`, `save_config` | YAML-Schema mit strenger Validierung, atomares Speichern (R-117) |
| Einstellungen | `anki_flashcards.settings`: `load_selected_config`, `resolve_generate_settings`, `resolve_export_settings`, `configuration_diagnostics` | Priorität Default → YAML/Profil → expliziter Wert; Diagnose ohne Secrets |
| Karten | `anki_flashcards.models`: `Card`, `save_cards`, `load_cards`, `deduplicate_cards` | Validierung und versioniertes Karten-JSON |
| Anki | `anki_flashcards.apkg`: `create_apkg`, `append_apkg`, `inspect_apkg`, `read_subdeck_context`, `add_cards_to_collection`, `collection_decks`, `collection_subdeck_context`, `ExportResult` | Pakete und offene Sammlungen schreiben und lesen |
| Docling | `anki_flashcards.docling_pdf`: `available_accelerator`, `require_docling` | GPU- und Installationsprüfung für AS-010 |
| Fehler | `anki_flashcards.errors`: `FlashcardError`, `GenerationCancelled` | Verständliche Anwendungsfehler; Abbruch als eigener Typ |

---

## 10. Einstellungen aus Formularwerten

`resolve_generate_settings(cli, config, config_path)` erwartet ein Mapping **nur mit ausdrücklich gesetzten Werten**. Fehlende Schlüssel bedeuten „aus YAML/Profil oder Default“. Die Oberfläche übergibt Formularwerte genauso: leere Felder weglassen, nicht als `None` setzen. `False`, `0` und `""` sind gültige ausdrückliche Werte (zum Beispiel `limit=0` für unbegrenzt). In der Herkunftsanzeige erscheinen solche Werte als `cli`; gemeint ist „explizit vom Aufrufer“.

| Schlüssel | Typ | Bedeutung |
|---|---|---|
| `input_file` | `Path` | **Pflicht.** Absoluter Pfad der hochgeladenen Datei im Job-Ordner |
| `output` | `Path` | **Pflicht** ohne `output_dir` in der YAML. Ziel-APKG; bei Sammlungszielen ein Platzhalter im Job-Ordner (wird dann nicht benutzt) |
| `deck` | `str` | Zieldeck, `::` für Unterdecks; Default: Dateiname ohne Endung |
| `extend` | `bool` | nur für APKG-Ziele |
| `profile`, `model`, `api_base`, `timeout` | `str`, `str`, `str`, `int` (1–3600) | Modellwahl |
| `limit`, `language`, `instructions`, `chunk_size` | `int` (≥ 0), `str`, `str`, `int` (1000–100000) | Generierung |
| `pdf_mode` | `PDFMode` (`local`, `structured`, `native`) | PDF-Verarbeitung |
| `subdecks` | `bool` | KI-Unterdecks |
| `json_output` | `Path` | Karten-JSON (nur von `run_generate` geschrieben) |
| `formulas`, `force_ocr`, `allow_unreadable`, `allow_cpu` | `bool` | strukturierter Modus |
| `picture_backend`, `picture_profile` | `PictureBackend` (`local`, `profile`, `none`), `str` | Bildbeschreibung |
| `source_text` | `Path` | Aufbereiteter Markdown-Text; die Datei darf noch nicht existieren |

**Typen und Wertebereiche prüft in der CLI Typer, nicht `resolve_generate_settings`.** Das gilt auch für Anki Studio:

- Enum-Werte als Enum übergeben: `PDFMode("structured")`, `PictureBackend("none")` aus `anki_flashcards.config`. Ein einfacher String wird ungeprüft übernommen und lässt später zum Beispiel `configuration_diagnostics` mit `AttributeError` scheitern (geprüft am 20.11.2026).
- Bereiche selbst prüfen, am besten mit einem eigenen Pydantic-Formularmodell: `limit ≥ 0`, `chunk_size` 1000–100000, `timeout` 1–3600. Ungültige Werte führen sonst erst tief im Ablauf zu einem `ValueError` statt einer verständlichen Meldung.
- Pfade als `Path`, absolut und innerhalb des Job-Ordners.

`config_path` immer ausdrücklich übergeben (`load_selected_config(Path("/etc/anki-studio/config.yaml"))`), sonst greifen `ANKI_CONFIG` oder `./config.yaml`. Der API-Schlüssel wird beim Auflösen aus `os.environ[profile.api_key_env]` gelesen; die systemd-`EnvironmentFile` reicht dafür. Der Generator lädt als Bibliothek **keine** `.env`-Datei; das tut nur `cli.run()`.

---

## 11. Schnittstellen des Generators ab 0.2.0

Alle Funktionen sind synchron und blockieren. Generierung und Modell-Downloads laufen in Anki Studio in einem Worker-Thread; der `report`-Callback wird in diesem Thread aufgerufen. Erwartete Fehler sind immer `FlashcardError` (Meldung für Benutzer geeignet); `GenerationCancelled` ist eine Unterklasse.

### 11.1 Ereignisse (`anki_flashcards.pipeline`)

| Klasse | Felder | `event_to_dict(event)["type"]` |
|---|---|---|
| `Notice` | `text: str`, `level: NoticeLevel` (`info`, `warning`, `transfer`) | `notice` |
| `StageStarted` | `stage: Stage` (`conversion`, `generation`), `description: str` | `stage_started` |
| `StageProgress` | `stage`, `label: str`, `completed: int`, `total: int`, `cards: int \| None` | `stage_progress` |
| `StageFinished` | `stage` (kommt auch nach Fehler oder Abbruch) | `stage_finished` |
| `ConversionFinished` | `stats: ConversionStats` (`pages`, `ocr_pages`, `tables`, `formulas`, `formulas_skipped`, `pictures_described`, `pictures_undescribed`, `pictures_decorative`, `unreadable: list[str]`) | `conversion_finished` |

- Typen: `PipelineEvent` (Union der fünf Klassen), `Reporter = Callable[[PipelineEvent], None]`, `CancelCheck = Callable[[], bool]`.
- `event_to_dict(event) -> dict` liefert JSON-fähige Daten, zum Beispiel `{"type": "stage_progress", "stage": "generation", "label": "Chunk", "completed": 2, "total": 5, "cards": 14}`.
- Texte enthalten kein Rich-Markup. Sie sind teils deutsch, teils englisch, genau wie die CLI-Ausgabe.
- `level == "transfer"` kennzeichnet: nativer PDF-Upload (vor dem Upload) und Bildausschnitte an ein Profil-Bildmodell (vor der Aufbereitung).

### 11.2 Abläufe

| Funktion | Rückgabe | Zweck |
|---|---|---|
| `produce_cards(settings, subdeck_context, *, report=None, cancel=None)` | `CardRun(cards, source_text, conversion)` | Karten erzeugen, **nichts schreiben** (außer `source_text`, falls gesetzt). `output`, `extend`, `json_output` werden ignoriert. Leeres Ergebnis → `FlashcardError`. |
| `subdeck_context_from_collection(settings, collection, *, report=None)` | `SubdeckContext \| None` | Unterdeck-Kontext aus einer offenen Sammlung; `None` ohne Unterdeck-Modus |
| `apkg_subdeck_context(settings, *, report=None)` | `SubdeckContext \| None` | dasselbe für ein APKG-Ziel |
| `write_collection(collection, deck, cards)` | `ExportResult` | Karten in eine offene Sammlung, **ein** Undo-Schritt (`add_notes`) |
| `validate_output(output, extend)` / `write_apkg(output, deck, cards, extend)` | `None` / `ExportResult` | APKG-Ziel prüfen und schreiben |
| `run_generate(settings, *, report=None, cancel=None)` | `GenerateResult(run, export, json_output)` | kompletter `generate`-Ablauf mit APKG-Ziel |
| `run_export(settings: ExportSettings)` | `ExportResult` | Karten-JSON → APKG |
| `prepare_models(config, config_path, *, formulas=None, picture_backend=None, report=None)` | `Path` (Modellordner) | `models download`; Download-Hinweise als `Notice` |

`ExportResult` (aus `anki_flashcards.apkg`): `path`, `deck`, `added`, `skipped`, `added_by_deck: dict[str, int]` (volle Decknamen, zum Beispiel `EL1::Filter`). Bei Sammlungszielen ist `path` die Sammlungsdatei.

**Abbruch:** `cancel` wird geprüft vor dem Start (also vor einem nativen Upload), nach jedem Aufbereitungsschritt, nach der Aufbereitung, nach jedem Chunk und in `run_generate` vor dem Schreiben. Liefert er `True`, folgt `GenerationCancelled`; es wurde nichts geschrieben. Ein laufender Provider-Request wird nicht unterbrochen.

### 11.3 Sammlung lesen und schreiben (`anki_flashcards.apkg`)

| Funktion | Verhalten |
|---|---|
| `collection_decks(collection) -> list[dict]` | je normalem Deck `{"id", "name", "cards"}` mit direkter Kartenanzahl; nur lesend |
| `collection_subdeck_context(collection, deck_name, *, examples=5) -> SubdeckContext` | Unterdecks erster Ebene mit bis zu 5 Beispielfragen (Klartext, ≤ 200 Zeichen); Groß-/Kleinschreibung egal; nur lesend |
| `add_cards_to_collection(collection, deck_name, cards) -> ExportResult` | wie `pipeline.write_collection`: Notiztyp „KI Karteikarte (Front/Back)“ anlegen oder wiederverwenden (abweichende Felder → Fehler), fehlende Decks anlegen, Duplikate (normalisierte Frage) im Deck bzw. Decks-Baum überspringen, Felder HTML-escapen, stabile GUID, alle Notizen in einem `add_notes`-Aufruf. Leere Liste oder leerer Deckname → Fehler vor jeder Änderung. |

Das Paket öffnet, sperrt, synchronisiert oder schließt keine Sammlung selbst. Das ist Aufgabe von Anki Studio (AS-020 bis AS-025).

### 11.4 Beispiel: Job mit Prüfschritt und Sammlungsziel

```python
import json
import threading
from pathlib import Path

from anki_flashcards.config import PDFMode
from anki_flashcards.errors import FlashcardError, GenerationCancelled
from anki_flashcards.models import Card, deduplicate_cards, save_cards
from anki_flashcards.pipeline import (
    event_to_dict, produce_cards, subdeck_context_from_collection, write_collection,
)
from anki_flashcards.settings import load_selected_config, resolve_generate_settings

config, config_path = load_selected_config(Path("/etc/anki-studio/config.yaml"))
form = {"deck": "EL1", "subdecks": True, "pdf_mode": PDFMode.STRUCTURED}  # nur gesetzte, geprüfte Felder
settings = resolve_generate_settings(
    {"input_file": job_dir / "upload.pdf", "output": job_dir / "unused.apkg", **form},
    config,
    config_path,
)

stop = threading.Event()

def report(event):                       # läuft im Worker-Thread
    line = json.dumps(event_to_dict(event), ensure_ascii=False)
    append_to_job_log(job_dir, line)     # Anki Studio: Ereignisprotokoll → SSE

# 1. Sync holen und Kontext lesen (im seriellen Sammlungs-Worker)
context = collection_worker.run(lambda col: subdeck_context_from_collection(settings, col, report=report))

# 2. Karten erzeugen (Worker-Thread, außerhalb der Sammlungssperre)
try:
    run = produce_cards(settings, context, report=report, cancel=stop.is_set)
except GenerationCancelled:
    ...                                  # Job als abgebrochen markieren
except FlashcardError as error:
    ...                                  # str(error) anzeigen
save_cards(job_dir / "cards.json", run.cards, deck=settings.deck, source=str(settings.input_file))

# 3. Nach dem Prüfen im Browser: bearbeitete Karten validieren und schreiben
reviewed = deduplicate_cards([Card.model_validate(item) for item in edited_items])
result = collection_worker.run(lambda col: write_collection(col, settings.deck, reviewed))
# danach sync_collection(...) und result.added / result.skipped / result.added_by_deck anzeigen
```

Für ein APKG-Ziel im Schritt 3 stattdessen `validate_output(path, extend)` vor der Generierung und `write_apkg(path, deck, reviewed, extend)` danach. Für APKG-Erweiterung mit Unterdecks liefert `apkg_subdeck_context(settings)` den Kontext. Ohne Prüfschritt erledigt `run_generate` alles in einem Aufruf.

### 11.5 Weitere Bausteine für die Seiten

| Seite | Aufrufe |
|---|---|
| Decks (APKG) | `apkg.inspect_apkg(path)` |
| Export | `ExportSettings(cards_file, output, deck, extend)` aus `anki_flashcards.settings` → `pipeline.run_export`; oder `models.load_cards` → `write_collection` |
| Konfiguration anzeigen | `settings.configuration_diagnostics(settings, config_path)` (enthält Herkunft je Wert, Schlüssel nur als `set (hidden)` / `not set`) |
| Konfiguration bearbeiten | `config.load_config(path)` → `AppConfig` (Pydantic; `AppConfig.model_json_schema()` für Formulare) → `config.save_config(path, config)` (atomar) |
| Modelle | `pipeline.prepare_models(...)`; GPU-Anzeige mit `docling_pdf.available_accelerator()`; Docling vorhanden: `docling_pdf.require_docling()` (wirft `FlashcardError`, falls nicht installiert) |

---

## 12. Änderungen im Generator-Repo für Anki Studio

Commits auf `main` (Merge-Commits je Paket):

| Paket | Commit | Inhalt |
|---|---|---|
| Übergabe und Requirements | `ee9a0b4` (Merge `3f9343b`) | Diese Datei, R-170 bis R-176, R-200/R-201 an Anki Studio übertragen |
| Generierungsdienst (R-170–R-173) | `8e922c3` (Merge `095962c`) | Neues Modul `src/anki_flashcards/pipeline.py`; `cli.py` ist nur noch Optionen und Darstellung (`_ConsoleReporter`); `errors.GenerationCancelled`; Tests `tests/test_pipeline.py`; CLI-Ausgabe und Exit-Codes unverändert |
| Sammlung als Ziel (R-174) | `9a72964` (Merge `9417a80`) | `apkg.add_cards_to_collection`, `collection_decks`, `collection_subdeck_context`; `pipeline.write_collection`, `subdeck_context_from_collection`; Notizen jetzt in einem `add_notes`-Aufruf (auch beim APKG-Erweitern); Tests `tests/test_collection.py` gegen eine echte temporäre Sammlung; Regel in `AGENTS.md` präzisiert |
| Version 0.2.0 (R-175, R-176) | Release-Commit, Tag `v0.2.0` | Version in `pyproject.toml` und `__init__.py`, finale Fassung dieser Datei |

Für Tests in Anki Studio wichtig: Patch-Ziele für simulierte KI und Docling liegen jetzt in `anki_flashcards.pipeline` (zum Beispiel `anki_flashcards.pipeline.generate_cards`, `.generate_native_cards`, `.convert_pdf`, `.require_accelerator`), nicht mehr in `anki_flashcards.cli`.

Prüfstand bei Übergabe: 160 Tests grün (`pytest`), `ruff check` und `ruff format --check` ohne Befund, Wheel-Build enthält `pipeline.py`.
