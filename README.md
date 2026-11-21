# Anki Studio

A straightforward web interface for the [Anki Flashcard Generator](https://github.com/Egwe/anki-flashcard-generator). It runs in a home network and acts as a client of a self-hosted Anki sync server.

The binding requirements and their status are in [requirements.md](./requirements.md); [AGENTS.md](./AGENTS.md) contains the contribution rules. The original German handover is preserved in [docs/anki-studio-uebergabe.md](./docs/anki-studio-uebergabe.md).

## Status

The web MVP and local sync integration are implemented. After login, you can configure provider keys and models, upload documents, create flashcards, review and edit them, write them to an APKG or safely to the local Anki collection, inspect decks, export card JSON, and run a safe sync. The real test against the user's sync server remains open until an explicitly approved, separate test user is available.

The interface defaults to English. Select **Deutsch** in the language control in the navigation to use the German interface. It changes interface labels and new job messages only; the language of generated cards remains the value selected in the generator form or configuration.

The [German user guide](./docs/benutzerhandbuch.html) explains usage. The [German developer guide](./docs/entwicklerhandbuch.html) documents modules, flows, tests, and deployment. Both HTML files work without a server or build step.

## Install in the container

Target: Anki Studio runs as the `anki-studio` systemd service in the `anki-studio` LXC. It is available in the home network and through NetBird at `http://<container-ip>:8000`.

All commands below run as `root` **inside the container**.

### Prerequisites

- Debian 13 (`trixie`) LXC with root access, for example `ssh ct-anki-studio` or the Proxmox console.
- Internet access for GitHub, PyPI, the PyTorch index, and Hugging Face.
- Around 12 GB of free space: about 7 GB for the application and PyTorch, 2 GB for PDF models, and the rest for jobs and the collection. Check with `df -h /`.
- For GPU-backed structured PDFs, NVIDIA drivers in the container and a working `nvidia-smi`. All other features work without a GPU.

### First installation

```bash
ssh ct-anki-studio
apt-get update
apt-get install -y git ca-certificates
git clone https://github.com/Egwe/anki-studio.git /opt/anki-studio
/opt/anki-studio/deploy/install.sh
```

The first run can take several minutes because it installs PyTorch. The idempotent installer installs missing packages and uv, creates the `anki-studio` system user, installs the locked dependencies including the `pdf` extra, preserves existing data and environment settings, creates missing configuration, installs the hardened service, starts it, and checks `/healthz`.

Do not clone into `/root` and do not edit `/opt/anki-studio` manually. The service uses its own system user; the scripts maintain the checkout and reject a dirty update.

### Set the initial login password

```bash
/opt/anki-studio/.venv/bin/anki-studio hash-password >> /etc/anki-studio/env
systemctl restart anki-studio
```

The command asks twice and writes only a password hash. Later, change it in the browser under **Settings → Access and sync**.

### Configure in the browser

Open `http://<container-ip>:8000`; `hostname -I` in the container displays the address.

1. **Settings → Credentials:** enter provider API keys. Ollama in the home network needs no key, only an endpoint in its profile.
2. **Settings → Configuration:** check profiles and select the default profile. For a Quadro K1200 set **Formulas per call** to `1`; previous `generator.yaml` files can be uploaded here.
3. **Settings → Models and GPU:** **Download missing models** downloads the roughly 1.9 GB model set as a live job.
4. **Settings → Access and sync:** enter the endpoint, user name, and password of the Anki sync server. Then use **Sync → Synchronise now**. Begin with a dedicated test user and verify the outcome in AnkiDroid.

If the application is opened under another name, for example a NetBird name, add it to `allowed_hosts` in `/etc/anki-studio/studio.yaml` and restart the service.

### Update and diagnostics

```bash
/opt/anki-studio/deploy/update.sh
systemctl status anki-studio --no-pager
journalctl -u anki-studio -n 50 --no-pager
```

`update.sh` needs a clean installation, fetches public `main`, runs the newest installer, preserves configuration and data, and checks `/healthz`. From another machine:

```bash
ssh ct-anki-studio /opt/anki-studio/deploy/update.sh
```

### Paths

| Path | Purpose |
|---|---|
| `/opt/anki-studio` | Git checkout of `main` and `.venv`; changed only by scripts |
| `/etc/anki-studio/studio.yaml` | Host, port, `allowed_hosts`, and data directory |
| `/etc/anki-studio/env` | Login hash, session secret, and `ANKI_STUDIO_SECRET_KEY` (mode 0600) |
| `/var/lib/anki-studio` | Generator YAML, encrypted keys, runtime credentials, jobs, models, and local collection |
| `/var/cache/anki-studio/uv` | uv package cache |
| `/etc/systemd/system/anki-studio.service` | Service unit |

`/etc/anki-studio/env` and `/var/lib/anki-studio` belong together: the key in the former decrypts stored API and sync credentials in the latter.

### Reset a forgotten password

A browser-changed password in `/var/lib/anki-studio/runtime.env` takes precedence over `/etc/anki-studio/env`. Remove both old entries, generate a new hash, and restart:

```bash
sed -i '/^ANKI_STUDIO_RUNTIME_PASSWORD_HASH_B64=/d' /var/lib/anki-studio/runtime.env 2>/dev/null
sed -i '/^ANKI_STUDIO_PASSWORD_HASH=/d' /etc/anki-studio/env
/opt/anki-studio/.venv/bin/anki-studio hash-password >> /etc/anki-studio/env
systemctl restart anki-studio
```

## Local development

Use Python 3.11 or newer and [uv](https://docs.astral.sh/uv/). Development and tests must use private test data, never the project owner's Anki Desktop collection or real sync account.

```bash
uv sync
cp .env.example .env
# Set ANKI_STUDIO_PASSWORD_HASH, ANKI_STUDIO_SESSION_SECRET, and
# ANKI_STUDIO_SECRET_KEY in .env. The file is not committed.
.venv/bin/anki-studio serve --host 127.0.0.1 --port 8000
```

The default data directory is `./data`; use a local `studio.yaml` or documented environment variables to override paths and hosts. The first start creates `generator.yaml` below the data directory. Never commit `.env`, local configuration, collections, uploads, models, APKG files, or generated card JSON.

## Using the application

### Login and language

Login is mandatory. The signed session cookie is `HttpOnly` and `SameSite=Strict`; the host header must match `allowed_hosts`. New sessions start in English. The language selector is available before and after login and remembers English or German across login and logout. It deliberately does not change the card-generation language.

### Configuration, profiles, keys, and models

**Settings → Configuration** displays effective values and their source, edits profiles and defaults, downloads YAML, and accepts a fully validated YAML replacement. The bundled template contains profiles for Ollama, OpenAI, Anthropic, Google Gemini, Mistral, DeepSeek, OpenRouter, Groq, xAI, Moonshot, and an OpenAI-compatible server. Existing profiles are never silently overwritten.

**Settings → Credentials** stores provider keys encrypted in the data directory. Values may be entered, replaced, deleted, and checked with a provider model-list request, but never read back. Environment keys take precedence and remain read-only. **Load models** sends only the relevant key to the provider, never a document; free-text model entry remains possible.

### Generate, review, and write cards

**Generate** accepts PDF, DOCX, HTML, Markdown, and text files up to 100 MiB each. Every file becomes a serial job. Choose profile, model overrides, card language, limits, instructions, PDF mode, and one target:

- a new APKG;
- an uploaded APKG to extend (one document only, up to 512 MiB); or
- the synchronised local Anki collection.

`native` PDFs and structured image descriptions through a profile require confirmation before document content is transferred to a provider. Generation does not write the final destination. Review, edit, deselect, or delete cards first; edited cards pass the generator's validation and writing also uses duplicate detection.

Job pages provide live stages, progress, notices, warnings, conversion statistics, and cancellation. Finished APKG jobs offer APKG, card JSON, and processed-text downloads when available.

### Decks, export, and synchronisation

**Decks** shows direct-card-count trees of the last safely synchronised collection and can inspect an uploaded APKG without changing it. **Export** accepts version-1 generator card JSON and writes it to a new APKG or safely to the collection.

**Sync** reports safe setup and last-result information and creates a no-upload sync job. A full upload is never automatic. A requested full download happens only when no unconfirmed local changes exist; unsafe or ambiguous server responses stop with an explanation. Media sync is not implemented yet.

## GPU-backed structured PDFs

Install the `pdf` extra locally with `uv sync --extra pdf`; the container installer does this automatically. **Settings → Models and GPU** reports Docling availability, the usable accelerator or CUDA architecture problem, formula batch size, model directory, and required components. Missing components download as a job.

The bundled CUDA 12.6 PyTorch build supports the passed-through Quadro K1200. Use `pdf_conversion.formula_batch_size: 1` for formulas on its 4 GiB VRAM.

## Tests and checks

After code changes, run:

```bash
uv sync
.venv/bin/python -m ruff check src tests
.venv/bin/python -m ruff format --check src tests
.venv/bin/python -m pytest
```

The regular suite has no network, real sync server, API key, GPU, or SSH dependency. Marked sync integration tests use a private `anki.syncserver` on `127.0.0.1`. For UI changes, also inspect changed pages at desktop width, narrow width, and dark mode.

## Browser security

Anki Studio runs only on the LAN and through NetBird; do not expose its port publicly. All runtime assets are local: no CDN, web fonts, or analytics. The CSP allows only Anki Studio resources, and uploads are size-checked before storage in isolated job folders.

## Bundled frontend libraries

| Library | Version | License |
|---|---:|---|
| Pico CSS | 2.1.1 | MIT |
| htmx | 2.0.11 | BSD-2-Clause |
| htmx SSE extension | 2.2.4 | BSD-2-Clause |
| Alpine.js | 3.17.5 | MIT |

They are versioned below `src/anki_studio/static/vendor/` and served by the application.

## Known limits

- One authenticated user and one application process only.
- The local collection is a disposable sync-client copy; never change the sync server directly.
- Media sync is pending.
- Existing collection cards cannot yet be searched, edited, or deleted in the browser.
- The real sync-server run needs an approved test user.
- Regular installation is performed by the project owner; Proxmox-host backups remain a separate task.
