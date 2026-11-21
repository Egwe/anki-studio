#!/usr/bin/env bash
# Update a regular Anki Studio installation (AS-040).
#
# Run as root in the target container from the local repository folder:
#   ssh ct-anki-studio 'bash -s' < deploy/update.sh
#
# The first installation uses deploy/install.sh. This script deliberately
# refuses missing or locally modified production checkouts, moves the
# checkout to the newest main and then runs that version's installer, so
# fixes in install.sh apply in the same update. Configuration and user data
# are preserved.
set -euo pipefail

readonly APP_DIR="/opt/anki-studio"
readonly BRANCH="main"
readonly UNIT="anki-studio"
readonly PORT="8000"

log() {
  printf '==> %s\n' "$*"
}

require_root() {
  if [[ $EUID -ne 0 ]]; then
    echo "Bitte als root ausführen." >&2
    exit 1
  fi
}

require_installation() {
  if [[ ! -x "$APP_DIR/deploy/install.sh" || ! -d "$APP_DIR/.git" ]]; then
    echo "Keine reguläre Installation gefunden; zuerst deploy/install.sh ausführen." >&2
    exit 1
  fi
  if [[ -n "$(git -C "$APP_DIR" status --porcelain)" ]]; then
    echo "Checkout in $APP_DIR ist nicht sauber; Update abgebrochen." >&2
    exit 1
  fi
}

fetch_main() {
  log "neuesten Stand von $BRANCH holen"
  git -C "$APP_DIR" fetch --quiet origin "$BRANCH"
  git -C "$APP_DIR" checkout --quiet --detach "origin/$BRANCH"
}

update() {
  log "geprüftes Update installieren"
  "$APP_DIR/deploy/install.sh"
  if ! curl -fs --retry 20 --retry-connrefused --retry-delay 1 -o /dev/null "http://127.0.0.1:$PORT/healthz"; then
    journalctl -u "$UNIT" -n 30 --no-pager >&2
    echo "Anki Studio antwortet nicht." >&2
    exit 1
  fi
  log "Update abgeschlossen"
}

main() {
  require_root
  require_installation
  fetch_main
  update
}

main "$@"
