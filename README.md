# Anki Studio

Schlichte Web-Oberfläche für den [Anki Flashcard Generator](https://github.com/Egwe/anki-flashcard-generator), betrieben im Heimnetz und als Client des eigenen Anki-Sync-Servers.

Stand: Projektgerüst im Aufbau; noch keine nutzbare Funktion. Anforderungen und Status stehen in [requirements.md](./requirements.md), Arbeitsregeln in [AGENTS.md](./AGENTS.md).

## Mitgelieferte Frontend-Bibliotheken

Alle Dateien liegen unter [src/anki_studio/static/vendor/](./src/anki_studio/static/vendor/) und werden ohne CDN ausgeliefert. Sie stammen unverändert aus den npm-Paketen; die sha512-Integrität der Pakete wurde gegen die npm-Registry geprüft, `SHA256SUMS` hält die Prüfsummen der Dateien fest. Lizenztexte stehen in `vendor/licenses/`.

| Bibliothek | Version | Datei | Lizenz |
|---|---|---|---|
| [htmx](https://htmx.org) | 2.0.11 | `htmx-2.0.11.min.js` | 0BSD |
| [htmx-ext-sse](https://htmx.org/extensions/sse/) | 2.2.4 | `htmx-ext-sse-2.2.4.min.js` | 0BSD |
| [Alpine.js](https://alpinejs.dev) | 3.17.5 | `alpinejs-3.17.5.min.js` | MIT |
| [Pico CSS](https://picocss.com) | 2.1.1 | `pico-2.1.1.min.css` | MIT |
