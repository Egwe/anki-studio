#!/usr/bin/env bash
# Remove the isolated Codex preview from the LXC "anki-studio".
#
# Codex tested its branch as a separate service on port 8001 before that
# branch was merged into main (21.11.2026). This script removes exactly that
# preview: service, system user, program, configuration, data, and uv cache.
# The regular installation and the preview of main stay untouched.
#
# Run as root in the target container only after the owner's approval:
#   ssh ct-anki-studio 'bash -s' < deploy/remove-codex-preview.sh
set -euo pipefail

readonly UNIT="anki-studio-codex-preview"
readonly USER="anki-studio-codex"
readonly PATHS=(
  "/opt/anki-studio-codex"
  "/opt/anki-studio-codex.previous"
  "/etc/anki-studio-codex-preview"
  "/var/lib/anki-studio-codex-preview"
  "/var/cache/anki-studio-codex-preview"
)

log() {
  printf '==> %s\n' "$*"
}

require_root() {
  if [[ $EUID -ne 0 ]]; then
    echo "Bitte als root ausführen." >&2
    exit 1
  fi
}

remove_unit() {
  local unit_file="/etc/systemd/system/$UNIT.service"
  [[ -e "$unit_file" ]] || return 0
  log "Dienst $UNIT stoppen und entfernen"
  systemctl disable --now --quiet "$UNIT"
  rm -f "$unit_file"
  systemctl daemon-reload
}

remove_paths() {
  local path
  for path in "${PATHS[@]}" /opt/.anki-studio-codex-stage.*; do
    [[ -e "$path" ]] || continue
    log "$path entfernen"
    rm -rf --one-file-system "$path"
  done
}

remove_user() {
  getent passwd "$USER" >/dev/null || return 0
  log "Systembenutzer $USER entfernen"
  userdel "$USER"
}

main() {
  require_root
  remove_unit
  remove_paths
  remove_user
  log "Codex-Vorschau entfernt"
}

main "$@"
