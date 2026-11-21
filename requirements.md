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
| 2 | Web-MVP: Login, Generieren, Live-Fortschritt, Prüfen, APKG- und JSON-Download | anki-studio | **erledigt** (21.11.2026); dazu Zugangsdaten und Modellliste |
| 3 | Sync: Anmeldung, lokale Sammlung, Deckauswahl, Schreiben und Synchronisieren | anki-studio | **lokal umgesetzt**; echter Lauf nur mit eigenem freigegebenem Testbenutzer noch offen |
| 4 | Deployment im LXC: systemd, uv, Pfade, Backup | anki-studio | **Skripte fertig** (`install.sh` mit Übernahme der Vorschau, `update.sh`); Ausführung auf Auftrag; Backup offen (Proxmox-Host) |
| 5 | Optional: Karten durchsuchen und bearbeiten (AS-013) | anki-studio | offen |

## 4. Anforderungen

### 4.1 Oberfläche und Funktionen

**AS-001 – Generieren · muss · umgesetzt**
Mehrere Dateien hochladen (PDF, DOCX, HTML, Markdown, Text; je höchstens 100 MiB wie im Generator). Pro Datei ein Job. Alle Optionen von `anki-flashcards generate` sind wählbar: Profil, Modell, Sprache, Limit, zusätzliche Anweisungen, Chunk-Größe, Timeout, API-Basis, PDF-Modus mit den Optionen des strukturierten Modus (Formeln, OCR erzwingen, nicht lesbare Elemente zulassen, CPU zulassen, Bild-Backend, Bild-Profil, aufbereiteten Text speichern), Unterdecks. Vorbelegung aus der YAML-Konfiguration; selten genutzte Optionen eingeklappt. Optionen des strukturierten Modus nur sichtbar, wenn dieser Modus gewählt ist.
*Umsetzung:* `/generate` mit allen Optionen; Platzhalter und Vorbelegung berechnet der Generator selbst (`resolve_generate_settings`); `forms.GenerateForm` prüft Typen und Bereiche; je Datei ein Job (`tests/test_forms.py`, `tests/test_web_generate.py`, Browser-Test). *Abweichung, vom Projektinhaber am 21.11.2026 akzeptiert:* „Aufbereiteten Text speichern“ ist kein Schalter; im strukturierten Modus wird der Text immer als `source.md` im Job-Ordner gespeichert, weil die Bibliothek ein `source_text_dir` aus der YAML sonst nicht abschalten ließe und der Job-Ordner privat ist und mit dem Job gelöscht wird.

**AS-002 – Ziel wählen · muss · umgesetzt**
Ziel ist entweder ein Deck der synchronisierten Sammlung (Auswahl aus vorhandenen Decks oder neuer Name, `::` für Unterdecks), eine neue APKG-Datei zum Download oder eine hochgeladene APKG zum Erweitern.
*Umsetzung:* Neue APKG, hochgeladene APKG (höchstens 512 MiB, nur mit einem Dokument) oder die synchronisierte Sammlung sind Ziele eines Jobs. Das Deck-Feld schlägt nach einem Abgleich vorhandene Decks vor und akzeptiert neue Namen; ein Sammlungs-Job gleicht vor der Generierung ab und liest seinen Unterdeck-Kontext ausschließlich über den Sammlungs-Worker (`generation.py`, `routes/generate.py`, `tests/test_sync.py`).

**AS-003 – Datenübertragung bestätigen · muss · umgesetzt**
Bei `pdf_mode: native` und beim Bild-Backend `profile` muss der Benutzer vor dem Start ausdrücklich bestätigen, dass das Dokument beziehungsweise Bildausschnitte an den Provider gehen. Ohne Bestätigung startet der Job nicht. Während des Laufs kommen dieselben Ankündigungen als `Notice` mit `level == "transfer"` und werden hervorgehoben.
*Umsetzung:* `generation.transfer_notice` erkennt `native` und das Bild-Backend `profile` im strukturierten Modus anhand der wirksamen Einstellungen (auch wenn das Profil den Modus vorgibt); Formular und Runner verlangen die Bestätigung; die Job-Seite hebt `transfer`-Hinweise hervor (`tests/test_generation.py`, `tests/test_web_generate.py`).

**AS-004 – Live-Fortschritt · muss · umgesetzt**
Job-Seite mit Live-Fortschritt aus den Generator-Ereignissen: Phase, Schritte, Abschnitte, Anzahl einzigartiger Karten, Hinweise und Warnungen, Statistik der Aufbereitung. Ein Job lässt sich abbrechen (R-172 des Generators).
*Umsetzung:* Job-Seite mit Phase, Schritten, Abschnitten, Kartenzahl, Hinweisen, Warnungen und Statistik aus `events.jsonl`; Live-Übertragung per Server-Sent Events (`/jobs/<id>/events`, htmx-SSE-Erweiterung) mit Fortsetzung nach Verbindungsabbruch; Abbrechen für wartende und laufende Jobs. Belegt durch `tests/test_live.py`, `tests/test_worker.py` und einen Chrome-Test mit simuliertem Ollama (zehn Abschnitte, Fortschritt live, Abschluss ohne Neuladen).

**AS-005 – Karten prüfen · muss · umgesetzt**
Nach der Generierung erscheinen die Karten in einer Tabelle: Frage, Antwort, Unterdeck, Tags. Einzelne Karten lassen sich bearbeiten, löschen oder abwählen. Erst danach wird geschrieben. Bearbeitete Karten durchlaufen dieselbe Pydantic-Validierung des Generators (`Card`).
*Umsetzung:* Kartenliste statt Tabelle (auf dem Handy bedienbar) mit Bearbeiten, Abwählen und Löschen über htmx; Prüfstand in `review.json`; Schreiben mit `deduplicate_cards` und `write_apkg` des Generators (`review.py`, `routes/review.py`; `tests/test_review.py`, `tests/test_web_review.py`, Chrome-Test).

**AS-006 – Ergebnis · muss · umgesetzt**
Nach dem Schreiben: hinzugefügte und übersprungene Karten, Aufteilung nach Unterdecks, Sync-Ergebnis. Downloads: APKG, Karten-JSON, aufbereiteter Text (falls erzeugt).
*Umsetzung:* Das Ergebnis zeigt hinzugefügte und übersprungene Karten sowie die Aufteilung nach Unterdecks. Für APKG-Ziele stehen APKG, Karten-JSON und gegebenenfalls aufbereiteter Text zum Download bereit; ein Sammlungsziel zeigt zusätzlich das Ergebnis des Nach-Syncs und bietet bewusst keine APKG an (`review.py`, `collection_write.py`, `tests/test_sync.py`).

**AS-007 – Decks · muss · umgesetzt**
Deckbaum der synchronisierten Sammlung mit Kartenanzahl. Ebenso für eine hochgeladene APKG (entspricht `anki-flashcards decks`).
*Umsetzung:* `/decks` zeigt nach einem erfolgreichen Abgleich den Deckbaum der lokalen, synchronisierten Sammlung mit direkten Kartenanzahlen. Zusätzlich nimmt die Seite eine APKG bis 512 MiB als Job entgegen, liest sie ausschließlich mit `inspect_apkg` des Generators und zeigt deren Baum. Alle Sammlungszugriffe laufen über `CollectionWorker`; das Paket bleibt unverändert (`decks.py`, `routes/decks.py`, `tests/test_decks_export.py`).

**AS-008 – Export · muss · umgesetzt**
Karten-JSON hochladen und als APKG ausgeben oder in die Sammlung schreiben (entspricht `anki-flashcards export`).
*Umsetzung:* `/export` nimmt versionierte Karten-JSON bis 100 MiB entgegen, prüft sie mit öffentlichen Generator-Schnittstellen und schreibt sie als Job entweder in eine neue APKG oder nach sicherem Vor-/Nach-Sync in die lokale Sammlung. Deckname oder YAML-Standard werden dabei verwendet (`card_export.py`, `routes/export.py`, `tests/test_sync.py`).

**AS-009 – Konfiguration · muss · umgesetzt**
Wirksame Werte mit Herkunft anzeigen (entspricht `config show`). Profile und Standardwerte der YAML bearbeiten, validiert über das Schema des Generators und atomar gespeichert. API-Schlüssel erscheinen nur als „gesetzt“ oder „fehlt“.
*Ergänzung 21.11.2026:* Die Generator-YAML liegt im Datenordner, damit Anki Studio sie schreiben darf (AS-015); ihre Bearbeitung über die Oberfläche ersetzt das Bearbeiten im Container (AS-016).
*Umsetzung:* Seite „Einstellungen → Konfiguration“ mit wirksamen Werten und Herkunft (`configuration_diagnostics`), Profil-Editor mit Modellliste, Standardwerten, YAML-Download und geprüftem Upload; Änderungen über `config_editor.py` mit `AppConfig` und `save_config` des Generators (`tests/test_config_editor.py`, `tests/test_web_config.py`, Chrome-Test).

**AS-010 – Modelle · muss · umgesetzt**
Docling- und Bildmodelle herunterladen (entspricht `models download`), mit Fortschritt; anzeigen, ob eine GPU erkannt wird.
*Umsetzung:* „Einstellungen → Modelle und GPU“ liest die wirksame Generator-Konfiguration und zeigt Docling, nutzbaren Beschleuniger beziehungsweise ein CUDA-Architekturproblem, Formel-Batch-Größe, Modellordner und benötigte Komponenten mit ihrem Manifest-Status. „Fehlende Modelle herunterladen“ legt eine aufgabenartige Job-Art `models` an; `ModelsRunner` ruft `prepare_models` des Generators auf und reicht seine Hinweise über die vorhandene SSE-Job-Seite weiter. Belegt durch `tests/test_structured.py`; die reguläre Suite lädt weder Modelle noch PyTorch oder Netzwerkdaten.

**AS-011 – Sync-Status · muss · umgesetzt**
Seite mit Endpunkt, angemeldetem Benutzer, Zeitpunkt und Ergebnis des letzten Syncs, Knopf „Jetzt synchronisieren“.
*Umsetzung:* `/sync` zeigt den nicht geheimen Endpunkt, Benutzerstatus, Zeitpunkt, Ergebnis und Server-Hinweis des letzten Abgleichs und legt per Knopf einen Sync-Job an. Passwort und `hkey` erscheinen nicht (`routes/sync.py`, `templates/sync.html`, `tests/test_sync.py`).

**AS-012 – Gestaltung · muss · umgesetzt**
Schlicht und aufgeräumt, gut lesbar, Dark Mode, auf Desktop und Handy bedienbar. Keine externen Ressourcen zur Laufzeit.
*Umsetzung:* Grundlayout auf Pico CSS mit Dark Mode nach Systemeinstellung; Login und alle angemeldeten Hauptseiten wurden im Browser bei 1280 px, 390 CSS-Pixeln und im Dark Mode geprüft. Lange Werte in Statuslisten umbrechen auf schmalen Ansichten. Alle Frontend-Dateien werden mitgeliefert; eine Content Security Policy erlaubt nur Anki Studio selbst als Quelle (`tests/test_app.py`).

**AS-014 – Modelle des Providers auswählen · soll · umgesetzt**
Ist für einen Provider ein Schlüssel hinterlegt oder braucht er keinen (etwa Ollama), lädt Anki Studio auf ausdrückliche Aktion die Liste der verfügbaren Modelle beim Provider und bietet sie zur Auswahl an: im Generierungsformular und beim Bearbeiten eines Profils. Dabei geht nur der Schlüssel an den Provider, kein Dokumentinhalt. Fehler (Schlüssel ungültig, Provider nicht erreichbar) erscheinen verständlich; die freie Eingabe eines Modellnamens bleibt möglich.
*Umsetzung:* `model_catalog.py` mit Tabelle je Provider, Route `/models` (htmx-Fragmente) im Generierungsformular („Modelle laden“) und auf der Seite Zugangsdaten („Prüfen“); belegt durch `tests/test_model_catalog.py`, `tests/test_web_models.py` und einen Chrome-Test mit Klick gegen einen simulierten Ollama-Server. Seit P7 auch im Profil-Editor, dort schon vor dem Speichern.

**AS-015 – Vorlage mit allen Providern · muss · umgesetzt**
Die Generator-Konfiguration enthält immer ein Profil für jeden unterstützten Provider, auch ohne hinterlegten Schlüssel: Ollama (Text und Bild), OpenAI (auch native PDF), Anthropic, Google Gemini, Mistral, DeepSeek, OpenRouter, Groq, xAI, Moonshot und ein eigener OpenAI-kompatibler Server. Fehlt die Datei, legt Anki Studio sie aus einer mitgelieferten Vorlage an; fehlende Standardprofile ergänzt es beim Start, vorhandene Profile bleiben unverändert. Die Datei liegt im Datenordner (`<data_dir>/generator.yaml`), `pdf_conversion.models_dir` ist dort absolut. Die Vorlage im Repository enthält keine Adressen aus dem Heimnetz.
*Umsetzung:* `resources/generator-template.yaml`, `generator_config.ensure_generator_config` beim Start (`tests/test_generator_config.py`, `tests/test_app.py`). In der Vorschau liegt seit dem 21.11.2026 die Konfiguration des Projektinhabers als Ausgangspunkt (`input_dir`/`output_dir` entfernt, `models_dir` absolut, vertauschte Ausgabegrenzen der OpenAI-Profile korrigiert); die übrigen Standardprofile ergänzt Anki Studio.

**AS-016 – Bedienung ohne Container-Zugriff · muss · umgesetzt**
Alles, was im täglichen Betrieb eingestellt wird, geht über die Oberfläche: Generator-Konfiguration und Profile (AS-009, AS-015), API-Schlüssel (AS-035), Modellwahl (AS-014), später Sync-Zugang und Login-Passwort. Shell-Zugriff auf den Container bleibt für Installation, Updates und Notfälle.
*Umsetzung:* Zusätzlich zu Generator-Konfiguration und Profilen (P7), API-Schlüsseln (P4c), Modellwahl (P4d) und der Sync-Statusseite (P10) bietet **Einstellungen → Zugang und Sync** das Ändern des Login-Passworts sowie das vollständige Einrichten oder Abschalten der Sync-Verbindung. `RuntimeEnvironment` schreibt die vollständigen täglichen Werte atomar mit 0600 als zweite systemd-`EnvironmentFile` unter dem Datenordner; sie wird nach der Administrator-Umgebung geladen und überschreibt diese beim Neustart. Passwort und Sync-Zugang bleiben damit Umgebungswerte, nicht YAML-, Job- oder Logdaten; Session-Schlüssel und Sync-Passwort stehen dort verschlüsselt (AS-031). Das Ändern des Login-Passworts verlangt das aktuelle Passwort und dreht den Session-Schlüssel; ein leeres Sync-Passwortfeld behält bei gleichem Benutzernamen das gespeicherte Passwort; jeder Speichervorgang startet den Dienst kontrolliert neu. Belegt durch `tests/test_runtime_env.py` und `tests/test_web_access.py`.

**AS-013 – Karten in der Sammlung durchsuchen und bearbeiten · kann · offen**
Suche über `col.find_notes`, Bearbeiten und Löschen generierter Notizen. Zurückgestellt auf Phase 5.

### 4.2 Sync

**AS-020 – Anmeldung · muss · umgesetzt**
Endpunkt in der Konfiguration von Anki Studio, Benutzername und Passwort in der Umgebungsdatei. Anmeldung über `Collection.sync_login(username, password, endpoint)`; das Ergebnis (`SyncAuth` mit `hkey`, `endpoint`) wird verwendet, das Passwort nicht weiter gespeichert oder angezeigt.
*Umsetzung:* `sync_endpoint` in `studio.yaml`, `ANKI_STUDIO_SYNC_USERNAME` und `ANKI_STUDIO_SYNC_PASSWORD` nur aus der Umgebung; `SyncService` meldet sich je Job an. `hkey` und Passwort bleiben nur im Speicher (`sync.py`, `tests/test_sync.py`).

**AS-021 – Erster Abgleich · muss · umgesetzt**
Ist die lokale Kopie leer, antwortet `sync_collection` mit `FULL_DOWNLOAD`. Anki Studio lädt die Sammlung dann herunter: `col.close_for_full_sync()`, `col.full_upload_or_download(auth=auth, server_usn=None, upload=False)`, danach **`col.reopen(after_full_sync=True)`**. Ein einfaches `reopen()` scheitert mit `CollectionAlreadyOpen` (im Prototyp beobachtet).
*Umsetzung:* `SyncService` führt genau diese Reihenfolge über den Sammlungs-Worker aus und speichert erst danach den nicht geheimen Status (`tests/test_sync.py` gegen lokalen `anki.syncserver`).

**AS-022 – Normaler Sync · muss · umgesetzt**
Vor jedem Schreiben in die Sammlung und danach `col.sync_collection(auth, sync_media=False)`. Diese Funktion führt den schrittweisen Sync selbst aus; das Feld `required` sagt, was **danach noch** nötig ist (`SyncCollectionResponse.ChangesRequired`):

| `required` | Bedeutung nach `sync_collection` | Reaktion |
|---|---|---|
| `NO_CHANGES` | Schrittweiser Sync erledigt (auch wenn Änderungen übertragen wurden) | fertig |
| `FULL_DOWNLOAD` | Server verlangt Komplett-Download | nur erlaubt, wenn lokal nichts verloren geht (AS-023) |
| `FULL_UPLOAD` | Server verlangt Komplett-Upload | **nie automatisch** (AS-023) |
| `FULL_SYNC` | Konflikt, Richtung muss gewählt werden | abbrechen und erklären |
| `NORMAL_SYNC` | gehört zu `sync_status()`, nicht zum Ergebnis von `sync_collection` | – |

Liefert der Server `new_endpoint`, wird dieser übernommen. `server_message` wird angezeigt, falls nicht leer.
*Umsetzung:* Der Sync-Job ruft `sync_collection(auth, sync_media=False)` auf, übernimmt einen neuen Endpunkt und zeigt den Server-Hinweis. `SyncService.write_cards` führt auf demselben Sammlungs-Worker einen Abgleich vor dem Generator-Schreibvorgang und einen weiteren danach aus; eine lokale Änderungsmarkierung entsteht unmittelbar vor dem Schreiben. Der Ablauf ist gegen den temporären lokalen `anki.syncserver` getestet (`tests/test_sync.py`).

**AS-023 – Kein automatischer Komplett-Upload · muss · umgesetzt**
Ein Komplett-Upload überschreibt die Daten auf dem Server und damit auf allen Geräten. Er findet niemals automatisch statt. Verlangt der Server einen Komplett-Sync, während die lokale Kopie eigene, noch nicht gesendete Änderungen hat, bricht Anki Studio ab und erklärt die Lage. Ein Komplett-Download ist nur erlaubt, wenn lokal nichts verloren geht.
*Umsetzung:* `FULL_UPLOAD` und `FULL_SYNC` brechen immer ab. Ein `FULL_DOWNLOAD` ist nur ohne lokal markierte, noch nicht bestätigte Änderungen möglich (`tests/test_sync.py`).

**AS-024 – Nicht in die Server-Daten schreiben · muss · umgesetzt**
Anki Studio schreibt nie direkt in `/opt/anki-sync-server/data` oder eine andere Server-Datei. Das umgeht die Sync-Buchhaltung und beschädigt die Synchronisierung.
*Umsetzung:* `SyncService` nutzt ausschließlich öffentliche pylib-Sync-Aufrufe über den konfigurierten HTTP(S)-Endpunkt; es enthält keinen Pfad oder Schreibzugriff auf Serverdaten.

**AS-025 – Serieller Zugriff · muss · umgesetzt**
Die pylib-Sammlung ist nicht threadsicher. Alle Zugriffe auf die Sammlung laufen nacheinander über einen Worker. Generierung (KI, Docling) läuft außerhalb dieser Sperre.
*Umsetzung:* `CollectionWorker` besitzt die lokale `Collection` in genau einem eigenen Thread und führt Funktionen nacheinander aus; Routen und Job-Runner erhalten keine `Collection` (`tests/test_sync.py`).

**AS-026 – Medien · kann · offen**
Medien-Sync (`sync_media`) erst, wenn Karten Bilder oder Audio enthalten (R-205 des Generators). Zurückgestellt bis dahin.

### 4.3 Betrieb und Sicherheit

**AS-030 – Login · muss · umgesetzt**
Ein Passwort; nur sein Hash steht in der Umgebungsdatei. Session-Cookie `HttpOnly`, `SameSite=Strict`. Prüfung des `Host`-Headers gegen eine Liste erlaubter Namen.
*Umsetzung:* scrypt-Hash aus der Standardbibliothek in `ANKI_STUDIO_PASSWORD_HASH`, erzeugt mit `anki-studio hash-password`; signiertes Session-Cookie `anki_studio_session` (`HttpOnly`, `SameSite=Strict`, 14 Tage); alle Seiten außer Anmeldung, `/healthz` und statischen Dateien verlangen die Anmeldung; `allowed_hosts` in `studio.yaml`, fremde Hosts erhalten 400. Belegt durch `tests/test_auth.py`, `tests/test_hosts.py`, `tests/test_passwords.py` und einen Browser-Test (hell, dunkel, schmal).

**AS-031 – Secrets · muss · umgesetzt**
Login-Hash, Session-Schlüssel, Schlüssel der Verschlüsselung und Sync-Zugangsdaten nur in der Umgebungsdatei. API-Schlüssel der Provider in der Umgebungsdatei oder, über die Oberfläche eingegeben, verschlüsselt im Datenordner (AS-035; Änderung vom 21.11.2026, ursprünglich nur Umgebungsdatei). Die YAML enthält wie im Generator nur Variablennamen (`api_key_env`). Keine Secrets in Logs, Job-Dateien, Fehlermeldungen oder der Oberfläche.
*Umsetzung:* Login-Hash, Session-, Verschlüsselungs- und Sync-Zugangsdaten kommen nur aus der Umgebung; Fehlermeldungen nennen die Variable, nie den Wert; `repr` blendet die Werte aus (`tests/test_credentials.py`); API-Schlüssel nach AS-035.
*Ergänzung 21.11.2026 (AS-016):* In der Oberfläche geänderte Werte liegen in `<data_dir>/runtime.env`, der zweiten `EnvironmentFile` des Dienstes. Session-Schlüssel und Sync-Passwort stehen dort als Fernet-Token unter `ANKI_STUDIO_SECRET_KEY` wie die API-Schlüssel, Login-Hash, Endpunkt und Benutzername nur Base64-kodiert. Ohne Schlüssel wird nichts gespeichert; ein nicht entschlüsselbarer Wert stoppt den Start mit dem Variablennamen (`tests/test_runtime_env.py`, `tests/test_credentials.py`, `tests/test_web_access.py`).

**AS-032 – Jobs · muss · umgesetzt**
Ein Job läuft zur Zeit (eine GPU, ein Benutzer); weitere warten in einer Warteschlange. Jeder Job hat einen Ordner mit Upload, Ereignisprotokoll, Karten-JSON und Ergebnis. Nach einem Neustart sind abgeschlossene Jobs weiter sichtbar; laufende gelten als abgebrochen. Alte Jobs werden nach einer einstellbaren Frist gelöscht.
*Umgesetzt:* Dienste `jobs.JobStore` (Ordner `<data_dir>/jobs/<id>` mit `job.json`, `events.jsonl`, `upload/`) und `worker.JobWorker` (ein Thread, Warteschlange, Abbruch, Wiederanlauf: wartende und laufende Jobs gelten nach einem Neustart als abgebrochen, Löschfrist `job_retention_days`), belegt durch `tests/test_jobs.py` und `tests/test_worker.py`. Seit P4 startet die Anwendung den Worker; `cards.json`, `review.json` und `result.json` liegen im Job-Ordner (P6).

**AS-033 – Uploads · muss · umgesetzt**
Größengrenze vor dem Speichern prüfen, Dateinamen nie ungeprüft als Pfad verwenden, Uploads nur im Job-Ordner ablegen.
*Umgesetzt:* `uploads.py` bereinigt Dateinamen, lässt nur die Dokumenttypen des Generators zu, prüft die gemeldete Größe vor dem Schreiben und zählt beim Kopieren erneut; der Job-Ordner entsteht erst nach der Prüfung (`tests/test_uploads.py`, `tests/test_jobs.py`). Die Route `/generate` prüft alle Dateien vor dem Anlegen eines Jobs; `limits.BodyLimitMiddleware` lehnt POST-Anfragen ohne Längenangabe (411) oder über der Grenze (413) ab, bevor der Körper gelesen wird (`tests/test_limits.py`).

**AS-035 – API-Schlüssel über die Oberfläche · muss · umgesetzt**
API-Schlüssel der Provider lassen sich in der Oberfläche setzen, ersetzen und löschen. Sicherheitskonzept:
- *Nur schreibend:* Die Oberfläche zeigt je Variable nur Herkunft und Status („aus der Umgebungsdatei“, „gespeichert am …“, „fehlt“), nie den Wert, auch nicht teilweise.
- *Verschlüsselt:* Gespeicherte Schlüssel liegen als Fernet-Token (AES-128-CBC mit HMAC-SHA256, Bibliothek `cryptography`) in `<data_dir>/secrets.enc`, Rechte 0600, atomar ersetzt. Der Schlüssel dafür, `ANKI_STUDIO_SECRET_KEY`, steht nur in der Umgebungsdatei und wird vom Installations- beziehungsweise Vorschau-Skript erzeugt. Fehlt er, ist Speichern nicht möglich; es gibt keinen Klartext-Ersatz.
- *Begrenzte Namen:* Nur Variablen aus Großbuchstaben, Ziffern und Unterstrich mit der Endung `_API_KEY`, `_TOKEN` oder `_KEY`, nie `ANKI_STUDIO_*`. So lässt sich über die Oberfläche keine andere Umgebungsvariable setzen (etwa `PATH` oder `LD_PRELOAD`).
- *Vorrang:* Werte aus der Umgebungsdatei gelten und sind in der Oberfläche nicht änderbar. Gespeicherte Werte übernimmt Anki Studio beim Start und nach jeder Änderung in die Umgebung des eigenen Prozesses, aus der Generator (`api_key_env`) und LiteLLM lesen.
- *Keine Spuren:* keine Werte in Logs, Job-Dateien, Ereignissen, Fehlermeldungen oder HTML; protokolliert wird nur „Schlüssel X geändert“.
- *Grenzen, ausdrücklich dokumentiert:* Im LAN läuft die Eingabe wie das Login-Passwort über unverschlüsseltes HTTP (über NetBird ist der Tunnel verschlüsselt). Ein Backup mit Datenordner und Umgebungsdatei enthält Schlüssel und verschlüsselte Datei zusammen; die Verschlüsselung schützt Kopien des Datenordners ohne Umgebungsdatei, etwa ausgelagerte Job-Ordner. HTTPS bleibt eine spätere Option.

*Umsetzung:* `secret_store.SecretStore`, Seite „Einstellungen → Zugangsdaten“ (`routes/keys.py`), `ANKI_STUDIO_SECRET_KEY` in `credentials.py` und `deploy/preview.sh`; belegt durch `tests/test_secret_store.py`, `tests/test_web_keys.py` (Wert nie in Seite, Log oder Datei), `tests/test_credentials.py` und einen Browser-Test (hell, dunkel, 390 px).

**AS-034 – Tests · muss · umgesetzt**
Reguläre Tests laufen ohne Netzwerk, ohne echten Sync-Server, ohne API-Schlüssel und ohne GPU. KI-Aufrufe werden wie im Generator simuliert (Patch-Ziel `anki_flashcards.pipeline.generate_cards` usw. oder `report`/`cancel`-Argumente). Für Sync-Tests eignet sich ein lokal gestarteter `python -m anki.syncserver` mit Testbenutzer auf `127.0.0.1` (Prototyp in Abschnitt 7.1 der Übergabe).
*Umgesetzt:* Testgerüst mit pytest und FastAPI-`TestClient`, ohne Netzwerk, GPU, Schlüssel und externen Sync-Server; simulierte KI-Läufe über gepatchte `pipeline.generate_cards` beziehungsweise `pipeline.generate_native_cards` in `tests/test_generation.py`, `tests/test_web_generate.py` und `tests/test_live.py`; markierte Sync-Integrationstests starten einen temporären `anki.syncserver` ausschließlich auf `127.0.0.1`. Sie belegen Erst-Download, Vor-/Nach-Sync und Schreiben geprüfter Karten sowie Karten-JSON in die Sammlung (`tests/test_sync.py`).

### 4.4 Deployment (R-201 des Generators)

**AS-040 – Installation · muss · teilweise**
Im LXC „anki-studio“: eigener Systembenutzer statt root; Programm mit uv in `/opt/anki-studio`; Daten in `/var/lib/anki-studio`; Konfiguration `/etc/anki-studio/config.yaml` (Generator-YAML) und `/etc/anki-studio/studio.yaml` (Endpunkt, Datenpfade, Port); Secrets in `/etc/anki-studio/env` (0600) als `EnvironmentFile`; systemd-Unit mit uvicorn. Ein Installations- und Update-Skript im Repo (`deploy/`).
*Änderung 21.11.2026:* Die Generator-YAML liegt im Datenordner (`/var/lib/anki-studio/generator.yaml`), weil sie über die Oberfläche bearbeitet wird (AS-015, AS-016); `/etc/anki-studio` enthält nur `studio.yaml` und `env`.
*Umsetzung:* `deploy/install.sh` und `deploy/update.sh` verwenden ausschließlich den veröffentlichten `main`-Zweig, richten einen eigenen Systembenutzer, `/opt/anki-studio`, `/var/lib/anki-studio`, `/etc/anki-studio/{studio.yaml,env}` (0600) und eine gehärtete systemd-Unit ein, bewahren Konfiguration und Daten und prüfen `/healthz`. Eine isolierte Codex-Vorschau mit gleichem Dienstaufbau (eigener Nutzer, `ProtectSystem=strict`, `ReadWritePaths` nur Datenordner) lief im Container einschließlich GPU-Modell-Download. Seit P14 übernimmt `install.sh` eine laufende Vorschau: Dienst `anki-studio-preview` stoppen und entfernen, Daten aus `/var/lib/private/anki-studio` nach `/var/lib/anki-studio` verschieben und dem Dienstbenutzer übergeben; `preview.sh` verweigert danach den Start. `deploy/remove-codex-preview.sh` entfernt die überholte Codex-Vorschau. `update.sh` setzt den Checkout vor dem Installer auf den neuesten `main`, damit Installer-Änderungen im selben Update wirken. Die Schritt-für-Schritt-Anleitung vom Klonen bis zur Einrichtung im Browser steht im README. *Offen:* Ausführen der regulären Installation durch den Projektinhaber.

**AS-041 – GPU · soll · umgesetzt**
Strukturierter Modus mit der durchgereichten GPU, sofern der GPU-Test (Abschnitt 5.3) sie als nutzbar bestätigt. Sonst dokumentieren, welche Ausweichwege gelten.
*Umsetzung:* Das optionale Extra `pdf` installiert Docling über den Generator und PyTorch `2.14.1`/Torchvision `0.29.1` aus dem expliziten `cu126`-Index; `deploy/preview.sh` installiert dieses Extra. Die Oberfläche zeigt die GPU-Prüfung des Generators und erklärt einen Build ohne passende CUDA-Architektur. Der GPU-Test bestätigt die K1200 mit `cu126` als nutzbar; für Formeln ist `pdf_conversion.formula_batch_size: 1` nötig (Abschnitt 5.3). Am 21.11.2026 wurde der aktuelle Codex-Vorschaustand zusätzlich im Container geprüft: Docling erkennt CUDA unter dem Dienstkonto, alle sechs benötigten Komponenten wurden mit der öffentlichen Generator-Schnittstelle in dessen isolierten Modellordner geladen, und eine echte CUDA-Matrixrechnung auf der K1200 lieferte ein endliches Ergebnis. Ein weiterer providerfreier Rauchtest wandelte eine selbst erzeugte Einseiten-PDF mit Docling und GPU erfolgreich um (eine Seite, keine unlesbaren Elemente); die Kartenerzeugung war dabei nur an der regulären Testnaht ersetzt, PDF, Markdown und APKG wurden danach entfernt. Der UI-Ablauf wurde mit ausschließlich temporären Test-Credentials gegen den echten Endpunkt `/settings/models/download` und den normalen Job-Worker geprüft; der Job endete erfolgreich, sein Testdatenordner wurde entfernt. Kein Dokumentinhalt ging dabei an einen Provider.

**AS-042 – Backup · soll · offen**
vzdump beider Container. Maßgeblich sind die Daten des Sync-Servers; die Sammlung von Anki Studio ist eine Kopie und lässt sich neu herunterladen.
*Offen:* `vzdump` ist eine Aktion auf dem Proxmox-Host, der nicht Teil des freigegebenen Containers ist. Dafür braucht es eine eigene Freigabe des Projektinhabers; weder das Installationsskript noch die Codex-Vorschau verändert den Host.

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
- Beim Messstand Generator 0.2.0 scheiterte die feste Batch-Größe 5 des Docling-Formelmodells am VRAM. Generator 0.2.1 bietet nun `pdf_conversion.formula_batch_size`; für die K1200 ist der Wert 1 belegt und über die Konfigurationsseite einstellbar. Damit funktionieren Formeln, belegen aber bis zu 3,8 GiB VRAM.
- Mit Formeln ist der VRAM fast voll (3,8 GiB von 4 GiB). Ein zweiter GPU-Prozess hätte keinen Platz; das passt zu einem Job zur Zeit (AS-032).
- Docling meldete, dass es den Kernel-Cache unter `models/cache/torch/kernels` nicht anlegen konnte. Das schaltet nur diesen Cache ab und hatte keine sichtbare Auswirkung.

### 5.4 Ende-zu-Ende-Test im Container (21.11.2026)

Ein echter Lauf mit der Pipeline des Generators in der Umgebung der Vorschau gegen den Ollama-Server des Projektinhabers, mit dem lokalen Modell `gemma3:4b` (bewusst kein Cloud-Modell) und einem kurzen, unverfänglichen Text: Mit Generator 0.2.0 scheiterte der Abschnitt an Mehrwort-Tags; mit 0.2.1 entstanden 2 Karten in 12,5 s mit den Tags `Ohmsches_Gesetz`, `Spannung`, `Widerstand`. Der Ollama-Server ist vom Container aus erreichbar und bietet 11 Modelle an.

### 5.5 Vorschau-Betrieb

Seit dem 20.11.2026 läuft im Container eine Vorschau des Stands von `main` als systemd-Dienst `anki-studio-preview` auf Port 8000, eingerichtet und aktualisiert mit `deploy/preview.sh` (README, Abschnitt „Vorschau im Container“; Regeln in AGENTS.md Abschnitt 8). Sie ersetzt nicht die Installation nach AS-040.

Zugriff von unterwegs: NetBird führt über einen Routing-Peer ins Heimnetz; die Oberfläche wird auch dann unter der LAN-Adresse des Containers und Port 8000 aufgerufen. Weitere Hostnamen in `allowed_hosts` sind dafür nicht nötig (Auskunft des Projektinhabers vom 21.11.2026).

## 6. Offene Punkte und Risiken

| Punkt | Umgang |
|---|---|
| `anki`-Version des Sync-Servers | Vom Projektinhaber bestätigt: 26.09.4, in `pyproject.toml` genau gepinnt; nur gemeinsam mit einem Server-Update anheben |
| Sync gegen den echten Server | Prototyp-Ablauf mit eigenem Testbenutzer wiederholen und das Ergebnis in AnkiDroid prüfen (Phase 0); die echte Sammlung bleibt unberührt |
| Erster Import des Notiztyps erzwingt Komplett-Sync | Lokal widerlegt (Übergabe Abschnitt 7.1); gegen den echten Server bestätigen |
| GPU K1200 mit aktuellem PyTorch | Nutzbar mit `cu126` (Abschnitt 5.3); vor einem PyTorch- oder Treiber-Update erneut prüfen |
| Formeln auf 4 GiB VRAM | Generator 0.2.1: `pdf_conversion.formula_batch_size` (R-159 des Generators); für die K1200 mit AS-041 auf `1` setzen |
| GPU-Erkennung meldet `cuda` trotz fehlendem `sm_50` | Erledigt: Generator 0.2.1 prüft die Architektur gegen den PyTorch-Build (R-160 des Generators) und nennt eine nicht unterstützte GPU ausdrücklich. |
| Stabile GUIDs des Generators | Wird eine generierte Notiz in ein anderes Deck verschoben und dieselbe Frage im ursprünglichen Deck erneut erzeugt, entsteht eine zweite Notiz mit gleicher GUID. Für Sync unkritisch, bei späteren APKG-Importen zu beachten. |
| Relative Pfade in der YAML | `pdf_conversion.models_dir` absolut setzen; `input_dir`, `output_dir`, `source_text_dir` und `generation.json_output` nicht verwenden, Pfade je Job ausdrücklich übergeben |
| Prozessweite Umgebungsvariablen | `model_storage.configure_model_storage()` setzt Cache-Variablen für den ganzen Prozess; unkritisch bei einem Modellordner pro Prozess |
| `tenacity` fehlt in den Abhängigkeiten | Erledigt: Generator 0.2.1 deklariert es; die direkte Abhängigkeit hier ist entfernt, `tests/test_dependencies.py` sichert den Import. |
| Mehrwort-Tags kleiner Modelle | Erledigt: In einem echten Lauf im Container (gemma3:4b über Ollama) verwarf der Generator 0.2.0 den ganzen Abschnitt wegen Tags wie „Ohmsches Gesetz“; Generator 0.2.1 zieht sie zu `Ohmsches_Gesetz` zusammen (R-177 des Generators). |
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
| P4c | `feature/secret-store` | API-Schlüssel verschlüsselt über die Oberfläche | AS-035, AS-031 | erledigt |
| P4d | `feature/model-list` | Modelle vom Provider laden und auswählen | AS-014 | erledigt |
| P5 | `feature/live-progress` | Live-Fortschritt per SSE | AS-004 | erledigt |
| P6 | `feature/card-review` | Karten prüfen, bearbeiten, abwählen; APKG schreiben; Downloads | AS-005, AS-006 | erledigt |
| P7 | `feature/config-editor` | Konfiguration anzeigen (Herkunft) und Profile und Standardwerte bearbeiten | AS-009, AS-016 | erledigt |
| G1 | Generator-Repo | Generator 0.2.1: `tenacity`, Mehrwort-Tags, Batch-Größe Formeln, genauere GPU-Prüfung; Anki Studio auf `v0.2.1` | – | erledigt (vorgezogen) |
| P8 | `feature/structured-mode` | Extra `pdf` mit PyTorch `cu126`, Modelle laden, GPU-Anzeige | AS-041, AS-010 | erledigt: Code, Tests, Modell-Download, CUDA-Validierung, providerfreier strukturierter Rauchtest und UI-Job der Codex-Vorschau geprüft |
| P9 | `feature/decks-export` | Decks einer APKG, Export Karten-JSON → APKG | AS-007, AS-008 (APKG-Teile) | erledigt; Sammlungsteile mit P11 |
| P10 | `codex/sync-foundation` | Sync-Anmeldung, lokaler Sammlungs-Worker, sicherer Erst- und Normal-Sync, Statusseite | AS-020–AS-025, AS-011, AS-031, AS-034 | erledigt (lokal); Sammlung als Ziel mit P11 |
| P11 | `codex/collection-target` | Sammlung als Ziel für Generierung, Prüfung und Karten-JSON; Sammlung-Deckbaum; Vor-/Nach-Sync | AS-002, AS-006–AS-008, AS-011, AS-022, AS-034 | **lokal erledigt**: 127.0.0.1-Integrationstests; echter Testbenutzer bleibt offen |
| P12 | `codex/deployment-foundation` | reguläre Installations-/Update-Skripte und isolierte Codex-Vorschau | AS-040, AS-041 (Vorschau), AS-042 | **teilweise erledigt**: Skripte und Codex-Vorschau im Container geprüft; reguläre Installation und Proxmox-Backup bewusst noch nicht ausgeführt |
| P13 | `codex/runtime-access-settings` | Login-Passwort und Sync-Zugang im Browser, atomare Laufzeit-Umgebung, kontrollierter Neustart | AS-016 | erledigt |
| M1 | `codex/main` → `main` | Review und Übernahme des Codex-Stands P9–P13 (Merge `26c6563`) | – | erledigt |
| P14 | `feature/codex-review-fixes` | Befunde des Reviews: Sync-Fehlertexte und Wiederöffnen nach gescheitertem Komplett-Download, aktuelles Passwort beim Ändern, Sync-Passwort behalten, Session-Schlüssel und Sync-Passwort verschlüsselt in `runtime.env`, Übernahme der Vorschau durch `install.sh`, Entfernen der Codex-Vorschau | AS-016, AS-022, AS-031, AS-040 | erledigt |
| Phase 3 | P10, P11 | Sync-Client, Sammlung als Ziel, Sync-Status | AS-020–AS-025, AS-002, AS-006, AS-007, AS-008, AS-011 | **lokal umgesetzt**; echter Server-Test mit Testbenutzer offen |
| Phase 4 | P12, P14 | Installation und Update nach AS-040, Backup | AS-040, AS-042 | Skripte fertig; Ausführung von `install.sh` erst auf Auftrag; Backup offen (Proxmox-Host) |

## 8. Codex-Abschlussbericht (21.11.2026)

Der isolierte Codex-Fachstand wurde auf `codex/main` mit dem Merge-Commit
`c25a48b` zusammengeführt. Er ergänzt die lokale Sync- und Sammlungsarbeit,
die isolierte Container-Vorschau, die GPU-Validierung sowie die vollständige
Bedienung im Alltag: Unter **Einstellungen → Zugang und Sync** lassen sich
Login-Passwort und Sync-Verbindung ohne Shell-Zugriff ändern. Die Werte bleiben
in einer privaten optionalen systemd-`EnvironmentFile`; der Dienst startet nach
einer atomaren Änderung kontrolliert neu. Globale Branches wurden dabei nicht
verändert: `main` und `origin/main` standen weiterhin auf `c74ba4e`.

Die fokussierten lokalen Prüfungen (`ruff`, Format, `tests/test_runtime_env.py`,
`tests/test_settings.py`, `tests/test_credentials.py`) waren grün. Die volle
Prüffolge `uv sync --locked --extra pdf`, Ruff-Check, Format-Check und pytest
lief anschließend erfolgreich im isolierten Codex-Checkout des freigegebenen
Containers. Die Codex-Vorschau wurde danach mit `c25a48b` aktualisiert; ihr
eigener Dienst `anki-studio-codex-preview` war aktiv, beantwortete `/healthz`
und las die optionale Laufzeit-Umgebung nach seiner eigenen Basis-Umgebung.

Nicht als unvollständige Codex-Implementierung zu verstehen sind die klar
abgegrenzten nächsten Betriebsaktionen: Die reguläre Installation (AS-040)
darf erst nach einer bewussten Übernahme in das globale `main` erfolgen; das
Proxmox-Backup (AS-042) braucht eine separate Host-Freigabe. Ein echter
Sync-Test bleibt bis zur Bereitstellung eines ausdrücklich freigegebenen
Testbenutzers aus.

*Übernahme nach `main` (21.11.2026):* Claude hat `codex/main` gegen `main` geprüft (Sync-Sicherheit nach AS-023, Sammlungs-Worker, Laufzeit-Umgebung, Routen, Deploy-Skripte) und mit dem Merge-Commit `26c6563` übernommen. Die Befunde behebt P14: allgemeine Sync-Fehlermeldung ohne Grund, fehlendes Wiederöffnen der Sammlung nach gescheitertem Komplett-Download, Passwortänderung ohne aktuelles Passwort, Sync-Passwort und Session-Schlüssel nur Base64-kodiert im Datenordner, keine Übernahme der Vorschau durch `install.sh` (Port- und Datenordnerkonflikt mit `DynamicUser`), Codex-Vorschau-Skripte mit Nicht-`main`-Ständen.

**Übernahme durch eine andere Person oder KI:** `AGENTS.md` lesen, dann `git log --oneline --first-parent main` für die erledigten Pakete und diese Tabelle für das nächste. Prüfungen: `uv sync`, `ruff check`, `ruff format --check`, `pytest` (README). Die Vorschau aktualisiert `ssh ct-anki-studio 'bash -s' < deploy/preview.sh`.
