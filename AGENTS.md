# Arbeitsregeln für Agents – Anki Studio

## 1. Geltung und Informationsquellen

Diese Regeln gelten für das gesamte Repository und für menschliche wie automatisierte Mitwirkende.

- [requirements.md](./requirements.md) ist die verbindliche Spezifikation von Anki Studio mit stabilen IDs `AS-…` und ehrlichem Status.
- [docs/anki-studio-uebergabe.md](./docs/anki-studio-uebergabe.md) ist die unveränderte Originalübergabe aus dem Generator-Repo (Stand Generator 0.2.0). Sie wird nicht überschrieben; Fortschreibungen und Abweichungen stehen in requirements.md.
- [README.md](./README.md) beschreibt den aktuell nutzbaren Stand: Installation, lokaler Start, Deployment, Bedienung und bekannte Grenzen.
- `docs/benutzerhandbuch.html` und `docs/entwicklerhandbuch.html` entstehen, sobald die erste nutzbare Oberfläche steht (Phase 2), und werden danach in jedem Paket gepflegt (Abschnitt 10).
- Der Anki Flashcard Generator ist eine Python-Abhängigkeit mit eigenen Regeln und eigener Dokumentation: dessen `AGENTS.md`, `requirements.md` (Abschnitt 13, R-170 bis R-176) und `docs/entwicklerhandbuch.html`. Für das Verhalten der Bibliothek sind diese maßgeblich.
- Diese Datei beschreibt **wie** gearbeitet wird, nicht den behaupteten Implementierungsstand.

Bei Konflikten zwischen bereits implementiertem Verhalten und den Anforderungen wird das Verhalten nicht stillschweigend geändert: Zuerst Anforderung, Auswirkung und gewünschten Status klären, dann Code, Tests und Dokumentation gemeinsam aktualisieren. Neue Anforderungen sind „offen“, bis sie implementiert und validiert sind.

## 2. Grundprinzipien

1. **Kleine, überprüfbare Lösungen:** Einfach halten, keine vorzeitige Infrastruktur (kein Node-Build, keine Datenbank, keine Container-Orchestrierung, keine Mehrbenutzerfähigkeit).
2. **Unix-Philosophie:** Module und Funktionen erfüllen eine klar benannte Aufgabe und lassen sich unabhängig testen und kombinieren.
3. **Trennung der Belange:** Web-Schicht, Jobs, Sammlung, Sync, Einstellungen und Deployment bleiben getrennt.
4. **Generator als Bibliothek:** Anki Studio ruft die öffentlichen Schnittstellen des Generators auf und dupliziert keine Fachlogik (Kartenerzeugung, Validierung, Duplikaterkennung, APKG-Schreiben, Konfigurationsschema).
5. **Daten des Nutzers zuerst:** Der Sync-Server ist die maßgebliche Datenquelle für alle Geräte. Im Zweifel bricht Anki Studio ab und erklärt die Lage, statt Daten zu überschreiben.
6. **Keine Funktionsbehauptungen ohne Beleg:** Dokumentation, Tests oder ausgeführte Befehle müssen den gemeldeten Stand stützen.
7. **Keine ungefragten Zusatzänderungen:** Keine unverbundenen Refactorings, Dependency-Upgrades oder Formatänderungen. Eng mit der Änderung verbundene Fehler werden behoben und begründet.

## 3. Arbeitsablauf, Branches und Commits

Entwickelt wird ausschließlich lokal in diesem Repository auf dem Rechner des Projektinhabers. Der Container ist nur Zielsystem (Abschnitt 8).

### Verbindlicher Branch-Workflow

Alle offenen **Muss- und Soll-Anforderungen** werden schrittweise abgearbeitet. **Kann-Anforderungen** sind keine impliziten Implementierungsaufträge.

Für jede Gruppe inhaltlich zusammengehöriger Requirements gilt dieser Zyklus:

1. Auf aktuellem, sauberem `main` einen beschreibenden Feature-Branch erstellen, beispielsweise `feature/app-skeleton`, `feature/login`, `feature/job-queue`, `feature/sync-client` oder `feature/deploy-scripts`.
2. Betroffene Requirement-IDs bestimmen und bestehenden Code, Tests, Dokumentation sowie tatsächliches Verhalten prüfen.
3. Ein kleines, abgegrenztes Paket bearbeiten.
4. Zuerst fokussierte Tests ausführen und danach alle relevanten Qualitätsprüfungen (Abschnitt 9).
5. Direkt betroffene Dokumentation und Requirement-Status im selben Paket aktualisieren.
6. Änderungen und Git-Diff prüfen und **einen eigenen kleinen Commit** erstellen. Größere Pakete dürfen mehrere fachlich geschlossene Zwischencommits erhalten.
7. Erst wenn alle Prüfungen erfolgreich sind, auf `main` wechseln und den Feature-Branch mit einem nachvollziehbaren Merge-Commit (`--no-ff`) integrieren. Kein Merge bei roten Tests.
8. Den gemergten Stand auf `main` prüfen. Erst danach mit dem nächsten Paket und einem neuen Branch beginnen.

Nicht mehrere unabhängige Requirements bis zu einem großen Schluss-Commit aufstauen. Nach erfolgreichem Merge kann der lokale Feature-Branch gelöscht werden. Vor einem Branchwechsel muss das Arbeitsverzeichnis sauber sein oder die aktuelle Arbeit anderweitig ausdrücklich gesichert werden.

### Git-Regeln

- Keine Dateien aus dem Arbeitsverzeichnis des Nutzers verwerfen, überschreiben oder zurücksetzen.
- Keine destruktiven Git-Befehle oder History-Rewrites ohne ausdrücklichen Auftrag.
- Nicht committen: Secrets, `.env`, lokale Konfigurationen, virtuelle Umgebungen, Caches, Anki-Sammlungen (`*.anki2`, `*.colpkg`), Job- und Datenordner, Uploads, heruntergeladene Modelle, erzeugte APKG- und Karten-JSON-Dateien.
- Commit-Nachrichten beschreiben das abgeschlossene Anforderungspaket und verwenden bei Agent-Commits den vorgesehenen Co-authored-by-Trailer.
- Der Commit ersetzt nicht den Abschlussbericht mit getestetem Verhalten und ausgeführten Prüfungen.
- Remote `origin` ist das **öffentliche** GitHub-Repository `Egwe/anki-studio`. Nach jedem erfolgreichen Merge und der Prüfung auf `main` wird `main` dorthin gepusht (Freigabe des Projektinhabers vom 20.11.2026). Feature-Branches bleiben lokal. Weil das Repository öffentlich ist, gilt die Liste „Nicht committen“ besonders streng.

## 4. Python- und Coderegeln

### Never Nesting

Für jede neue oder geänderte Funktion gilt:

- Guard Clauses und frühe Rückgaben statt tiefer `if`-Pyramiden.
- Kleine, fachlich benannte Funktionen statt verschachtelter Schleifen mit mehreren Entscheidungsebenen.
- Tabellen, Enums oder Strategieobjekte für echte Varianten statt langer `if`/`elif`-Ketten, sofern dies die Lesbarkeit verbessert.
- Keine Komplexität lediglich in anonyme Funktionen oder unklare Helfer verschieben.
- Keine breiten `except Exception`-Blöcke als Kontrollfluss; nur an einer echten System-/Bibliotheksgrenze abfangen und in eine verständliche Anwendungsfehlermeldung übersetzen.
- Kontextmanager und `try`-Blöcke klein halten.

### Dokumentation von Funktionen und Klassen

Jede benannte Funktion, Methode und Klasse – auch privat und in Tests – erhält einen konkreten Docstring (Google-Stil). Er dokumentiert:

- Zweck und Verhalten,
- alle Parameter inklusive Einheiten oder Grenzen, sofern relevant,
- Rückgabewert und Datenform,
- relevante Exceptions und Seiteneffekte wie Datei-, Netzwerk-, Sammlungs- oder Sync-Zugriffe.

Beispiel:

```python
def job_dir(root: Path, job_id: str) -> Path:
    """Return the folder of one job inside the data directory.

    Args:
        root: Absolute jobs directory, e.g. ``/var/lib/anki-studio/jobs``.
        job_id: Identifier generated by the application; 32 hex characters.

    Returns:
        Absolute path below ``root``; the folder is not created.

    Raises:
        ValueError: If ``job_id`` is not a valid identifier.
    """
```

Bei Klassen werden wesentliche Attribute beziehungsweise Konstruktorparameter dokumentiert. Funktionen ohne Parameter wiederholen nicht „keine Parameter“. Funktionen mit dem Hauptzweck eines Seiteneffekts geben `None` im Docstring an. Docstrings beschreiben beobachtbares Verhalten, nicht den Quelltext Satz für Satz.

### Web-Schicht

- Routen nehmen Anfragen entgegen, validieren Formularwerte über Pydantic-Modelle und rendern Antworten. Abläufe stehen in Diensten (`jobs`, `collection`, `sync`, `settings`), die weder Request/Response noch Templates kennen.
- Templates enthalten keine Fachlogik. Alpine.js nur für kleine Zustände der Oberfläche.
- Zustandsändernde Aktionen nur per `POST`.
- Lange Abläufe laufen nie im Request: Generierung im Job-Worker, Sammlungszugriffe im Sammlungs-Worker. Fortschritt erreicht den Browser per Server-Sent Events.
- Kein Node-Build. HTMX, Alpine.js, Pico CSS und Erweiterungen werden mit fester Version unter `static/vendor/` mitgeliefert; Version und Lizenz stehen im README. Zur Laufzeit keine externen Ressourcen (CDN, Webfonts, Analytics).

### Weitere Regeln

- Python 3.11+, Abhängigkeiten und Umgebung über uv (`pyproject.toml`, `uv.lock`).
- Ruff-Konfiguration wie im Generator: dessen Regelauswahl inklusive `C90` (max-complexity 8) und `D` (Google-Konvention).
- Öffentliche und fachliche Schnittstellen typisieren; dynamische Bibliotheksgrenzen (pylib, Generator-Ereignisse) gezielt kapseln.
- Keine toten Kommentare oder kommentierter alter Code. Kommentare nur für nicht offensichtliche Gründe und Annahmen.
- Abhängigkeiten nur ergänzen, wenn eine Anforderung sie braucht; danach Manifest, Lockfile und Dokumentation aktualisieren.

## 5. Einbindung des Generators

- Abhängigkeit fest auf einen Git-Tag: `anki-flashcard-generator @ git+https://github.com/Egwe/anki-flashcard-generator@v<Version>`. Auf `main` steht immer ein Tag. Eine lokale editable-Quelle (`[tool.uv.sources]`, `../anki-flashcard-generator`) ist nur während eines Pakets erlaubt, das beide Repos gleichzeitig ändert, und wird vor dem Merge durch den neuen Tag ersetzt.
- Den Generator nie in `site-packages`, als Kopie oder per Monkeypatch im Produktivcode verändern. Fehlt eine Schnittstelle, wird sie im Generator-Repo als eigenes Paket nach dessen `AGENTS.md` ergänzt, dort getestet, getaggt und hier per Versionsanhebung übernommen. Arbeiten im Generator-Repo nur nach Absprache mit dem Projektinhaber.
- Nur öffentliche Schnittstellen verwenden (Übergabe Abschnitt 9–11; Generator-Entwicklerhandbuch, Modulkarten `pipeline.py` und `apkg.py`). Keine privaten Funktionen (`_…`).
- Formularwerte vor `settings.resolve_generate_settings` selbst prüfen: Enums als Enum-Objekte übergeben (`PDFMode`, `PictureBackend`), Wertebereiche prüfen (Limit ≥ 0, Chunk-Größe 1000–100000, Timeout 1–3600 s), `config_path` immer ausdrücklich übergeben. Die Bibliothek prüft das nicht selbst und lädt keine `.env`.
- Jede Karte, auch nach Bearbeitung im Browser, durchläuft die `Card`-Validierung und die Duplikaterkennung des Generators.
- Kein stiller Wechsel von PDF-Modus, Modell oder Provider. Übertragungen von Dokumentinhalten an einen Provider (`pdf_mode: native`, Bild-Backend `profile`) erfordern vorher eine ausdrückliche Bestätigung (AS-003).
- Pfade je Job ausdrücklich übergeben; `pdf_conversion.models_dir` absolut setzen. `input_dir`, `output_dir`, `source_text_dir` und `generation.json_output` aus der YAML werden nicht verwendet.

## 6. Anki-Sammlung und Sync

- Anki Studio ist ein Sync-Client wie Anki Desktop und AnkiDroid. Seine Sammlung ist eine Kopie und darf jederzeit neu heruntergeladen werden.
- Nie direkt in die Daten oder Dateien des Sync-Servers schreiben (AS-024).
- **Nie ein automatischer Komplett-Upload** (AS-023). Ein Komplett-Download nur, wenn lokal nichts verloren geht. Bei `FULL_SYNC` oder unklarer Lage abbrechen und erklären.
- Nach einem Komplett-Sync die Sammlung mit `reopen(after_full_sync=True)` öffnen.
- Die pylib-Sammlung ist nicht threadsicher: alle Zugriffe nacheinander über einen Worker, ein uvicorn-Prozess, keine zweite Instanz auf derselben Sammlung.
- In die Sammlung wird nur über `pipeline.write_collection` geschrieben (offizielle Anki-API, ein Undo-Schritt). Keine SQL-Zugriffe auf die Sammlung.
- Die `anki`-Version ist genau die des Sync-Servers und wird nur zusammen mit einem Server-Update angehoben.
- Entwicklung und Tests nie mit dem Hauptbenutzer oder der echten Sammlung des Projektinhabers. Gegen den echten Sync-Server nur mit einem eigenen Testbenutzer und nach Freigabe. Die lokale Anki-Desktop-Sammlung des Projektinhabers wird nie geöffnet.
- Medien-Sync erst mit AS-026.

## 7. Sicherheit, Secrets und Uploads

- Secrets (Sync-Zugangsdaten, Login-Hash, Session-Schlüssel, Verschlüsselungsschlüssel `ANKI_STUDIO_SECRET_KEY`) stehen nur in der Umgebung: im Betrieb `/etc/anki-studio/env` (0600) als `EnvironmentFile`, lokal in einer nicht committeten `.env`. `.env.example` enthält nur Platzhalter.
- API-Schlüssel der Provider dürfen zusätzlich über die Oberfläche eingegeben werden und liegen dann nur verschlüsselt im Datenordner; Regeln und Grenzen in AS-035 (Entscheidung des Projektinhabers vom 21.11.2026). Die Oberfläche ist für Schlüssel nur schreibend.
- Secrets und der Sync-`hkey` erscheinen nie in YAML, Logs, Job-Dateien, Ereignisprotokollen, Fehlermeldungen, Templates, Tests oder Commits. Die Oberfläche zeigt nur „gesetzt“ oder „fehlt“.
- Login ist Pflicht (AS-030): Session-Cookie `HttpOnly` und `SameSite=Strict`, Prüfung des `Host`-Headers gegen erlaubte Namen.
- Uploads (AS-033): Größe vor dem Speichern prüfen, Dateinamen nie ungeprüft als Pfad verwenden, nur im Job-Ordner ablegen.
- Hochgeladene Dokumente bleiben lokal, gelten als privat und werden nach der eingestellten Frist gelöscht.
- Betrieb nur im LAN und über NetBird. Keine Portfreigaben, kein öffentlicher Zugang.

## 8. Infrastruktur und Deployment

- Zielsystem ist der LXC „anki-studio“, erreichbar mit `ssh ct-anki-studio` (Alias in `~/.ssh/config` des Projektinhabers): Debian, NVIDIA Quadro K1200 durchgereicht.
- **Kein Entwicklungsort:** Im Container wird kein Code bearbeitet und nicht experimentiert. Code gelangt nur über die Skripte in `deploy/` dorthin, und zwar aus einem geprüften und gepushten Stand von `main` (sauberes Arbeitsverzeichnis, alle Prüfungen grün).
- **Vorschau-Betrieb** (Freigabe des Projektinhabers vom 20.11.2026, gilt bis zur Installation nach AS-040): `deploy/preview.sh` legt in `/opt/anki-studio` einen Git-Checkout von `main` aus GitHub an, aktualisiert ihn und startet den Dienst `anki-studio-preview` neu. Nach jedem Merge darf die Vorschau so aktualisiert und im Container getestet werden, damit der Projektinhaber den Stand im Browser prüfen kann. Der Checkout wird nur durch das Skript verändert, nie von Hand.
- Lesende Bestandsaufnahme ist jederzeit erlaubt.
- Änderungen im Container (Pakete, Treiber, Benutzer, Dienste, Neustarts, Dateien außerhalb von `/opt/anki-studio`, `/var/lib/anki-studio`, `/etc/anki-studio`) nur nach Freigabe durch den Projektinhaber. Freigegebene Einrichtungsschritte landen als wiederholbares Skript in `deploy/`, nicht als einmalige Handarbeit.
- Ein Deployment ist eine Aktion nach außen und erfolgt nur auf ausdrücklichen Auftrag. Ausgenommen ist das Aktualisieren der Vorschau mit `deploy/preview.sh`.
- Install- und Update-Skripte sind idempotent, behalten `/var/lib/anki-studio` und `/etc/anki-studio`, überschreiben nie eine vorhandene `env` und lassen den Dienst als eigenen Systembenutzer laufen.
- Den Container des Sync-Servers und den Proxmox-Host nicht verändern.
- Ins Repository gehören nur der SSH-Alias, keine IP-Adressen, weiteren Hostnamen, Schlüssel oder Passwörter. Ergebnisse von Bestandsaufnahmen und GPU-Tests werden ohne Adressen in requirements.md beziehungsweise README dokumentiert.

## 9. Tests und Validierung

### Testregeln

- Jedes neue oder geänderte Verhalten erhält fokussierte Tests, die ohne die Änderung fehlschlagen würden.
- Erfolgsfall, relevante Grenzen, Fehlerfälle und Regressionen prüfen; keine Tests nur zur Erhöhung einer Prozentzahl.
- Bei Bugfixes zuerst eine Reproduktion oder einen fehlschlagenden Test erstellen, sofern praktikabel.
- Reguläre Tests laufen ohne Netzwerk, ohne echten Sync-Server, ohne API-Schlüssel, ohne GPU und ohne SSH.
- KI-Aufrufe simulieren: Patch-Ziele `anki_flashcards.pipeline.*` oder die Argumente `report` und `cancel` des Generators.
- Sammlungstests gegen eine echte temporäre `Collection` in `tmp_path`.
- Sync-Integrationstests gegen einen lokal gestarteten `python -m anki.syncserver` auf `127.0.0.1` mit Testbenutzer und temporärem `SYNC_BASE`, mit eigener pytest-Markierung; der Server wird danach beendet.
- Web über FastAPI `TestClient`, inklusive Login, Host-Prüfung und SSE-Ereignissen.
- Temporäre Dateien und lokale Testserver nach Verwendung aufräumen beziehungsweise beenden.

### Mindestens auszuführen

Nach Codeänderungen in der projekteigenen virtuellen Umgebung:

```bash
uv sync
.venv/bin/python -m ruff check src tests
.venv/bin/python -m ruff format --check src tests
.venv/bin/python -m pytest
```

Bei Änderungen an der Oberfläche zusätzlich lokal starten und die betroffenen Seiten im Browser prüfen: Desktop, schmale Breite, Dark Mode. Shell-Skripte in `deploy/` mindestens mit `bash -n` prüfen, mit `shellcheck`, falls vorhanden. Reine Markdown-Änderungen benötigen keine Python-Tests; Git-Diff und Dokumentationskonsistenz sind trotzdem zu prüfen.

## 10. Dokumentation und Abschluss

- Neue Funktionen werden erst nach Implementierung und Validierung als „umgesetzt“ markiert.
- README enthält eine kompakte Übersicht: Installation, lokaler Start, Deployment, Bedienung, Defaults, mitgelieferte Frontend-Bibliotheken mit Version und Lizenz, bekannte Grenzen.
- `docs/benutzerhandbuch.html` erklärt jede Seite und jede Aktion der Oberfläche verständlich. **Bei jeder Änderung des Benutzerverhaltens werden README und Benutzerhandbuch im selben Paket angepasst.**
- `docs/entwicklerhandbuch.html` erklärt Module, Abläufe (Jobs, Sync-Zustände, Sammlungs-Worker), Datenformate, Test-Nahtstellen und Deployment. **Bei Änderungen daran wird es im selben Paket angepasst**, einschließlich betroffener Diagramme.
- Beide Handbücher sind ohne Build-Schritt im Browser nutzbar, setzen keine externen Ressourcen voraus und behalten Suche, Links und Kopierfunktionen.
- requirements.md erhält stabile IDs und einen ehrlichen Status; die Originalübergabe wird nicht überschrieben.
- Keine zusätzlichen Planungs- oder Notizdateien anlegen, wenn die Information in requirements.md, README.md oder diese Datei gehört.
- Abschlussmeldungen enthalten kurz: umgesetzte Requirement-IDs, geänderte wesentliche Dateien, tatsächlich ausgeführte Prüfungen und verbleibende Einschränkungen.
- Kein Push, keine externe Veröffentlichung und kein Deployment ohne ausdrücklichen Auftrag. Ausgenommen sind der Push von `main` nach jedem Merge (Abschnitt 3) und das Aktualisieren der Vorschau (Abschnitt 8).