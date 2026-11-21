#!/usr/bin/env bash
# Update a regular Anki Studio installation (AS-040).
#
# The first installation uses deploy/install.sh. This script deliberately
# refuses missing or locally modified production checkouts and preserves all
# configuration and user data.
set -euo pipefail

readonly APP_DIR="/opt/anki-studio"
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
  update
}

main "$@"
