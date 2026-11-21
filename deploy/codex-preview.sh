#!/usr/bin/env bash
# Deploy the committed local Codex branch as an isolated container preview.
#
# Run on the development computer from a clean repository checkout:
#   deploy/codex-preview.sh
#
# Unlike deploy/preview.sh this script neither fetches nor changes public main.
# It streams `git archive HEAD` to a separate checkout and starts only
# anki-studio-codex-preview on port 8001.
set -euo pipefail

readonly REMOTE="ct-anki-studio"
readonly STAGE_PREFIX="/opt/.anki-studio-codex-stage."

log() {
  printf '==> %s\n' "$*"
}

require_clean_repository() {
  if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "Dieses Skript muss aus einem Git-Arbeitsverzeichnis laufen." >&2
    exit 1
  fi
  if [[ -n "$(git status --porcelain)" ]]; then
    echo "Arbeitsverzeichnis ist nicht sauber; erst committen oder Änderungen sichern." >&2
    exit 1
  fi
}

create_stage() {
  local stage
  stage="$(ssh "$REMOTE" "mktemp -d ${STAGE_PREFIX}XXXXXX")"
  case "$stage" in
    "${STAGE_PREFIX}"*) printf '%s\n' "$stage" ;;
    *) echo "Ungültiger Staging-Pfad vom Container." >&2; exit 1 ;;
  esac
}

main() {
  local stage commit
  require_clean_repository
  commit="$(git rev-parse --short HEAD)"
  stage="$(create_stage)"
  log "Commit $commit als getrennte Codex-Vorschau übertragen"
  if ! git archive --format=tar HEAD | ssh "$REMOTE" "tar -xf - -C '$stage'"; then
    ssh "$REMOTE" "rm -rf '$stage'" || true
    exit 1
  fi
  ssh "$REMOTE" "bash '$stage/deploy/codex-preview-remote.sh' '$stage' '$commit'"
}

main "$@"
