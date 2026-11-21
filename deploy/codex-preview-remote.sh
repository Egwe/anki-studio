#!/usr/bin/env bash
# Install the archive supplied by deploy/codex-preview.sh inside the container.
# This helper is not invoked directly: its first argument is a validated
# /opt staging directory created by the local deployment script. It stays on
# the same filesystem as the target checkout, so the virtual environment can
# be moved atomically after dependency installation.
set -euo pipefail

readonly APP_DIR="/opt/anki-studio-codex"
readonly PREVIOUS_DIR="/opt/anki-studio-codex.previous"
readonly CONFIG_DIR="/etc/anki-studio-codex-preview"
readonly DATA_DIR="/var/lib/anki-studio-codex-preview"
readonly UV_CACHE="/var/cache/anki-studio-codex-preview/uv"
readonly USER="anki-studio-codex"
readonly GROUP="anki-studio-codex"
readonly UNIT="anki-studio-codex-preview"
readonly PORT="8001"
readonly ENV_FILE="$CONFIG_DIR/env"
readonly LOGIN_SOURCE_ENV="/etc/anki-studio/env"

stage=${1:?Staging-Pfad fehlt}
commit=${2:?Commit fehlt}

log() {
  printf '==> %s\n' "$*"
}

require_root() {
  if [[ $EUID -ne 0 ]]; then
    echo "Bitte als root ausführen." >&2
    exit 1
  fi
}

require_stage() {
  case "$stage" in
    /opt/.anki-studio-codex-stage.*) ;;
    *) echo "Ungültiger Staging-Pfad." >&2; exit 1 ;;
  esac
  if [[ ! -f "$stage/pyproject.toml" || ! -f "$stage/deploy/codex-preview-remote.sh" ]]; then
    echo "Unvollständiges Codex-Archiv." >&2
    exit 1
  fi
}

ensure_service_user() {
  getent passwd "$USER" >/dev/null && return
  log "Systembenutzer $USER anlegen"
  useradd --system --user-group --home-dir /nonexistent --shell /usr/sbin/nologin "$USER"
}

host_list() {
  local addresses name
  read -ra addresses <<< "$(hostname -I)"
  for name in localhost 127.0.0.1 "$(hostname)" "${addresses[@]}"; do
    printf '  - %s\n' "$name"
  done
}

ensure_config() {
  local studio="$CONFIG_DIR/studio.yaml"
  install -d -o root -g "$GROUP" -m 0750 "$CONFIG_DIR"
  install -d -o "$USER" -g "$GROUP" -m 0750 "$DATA_DIR" "$UV_CACHE"
  [[ -e "$studio" ]] && return
  log "$studio anlegen (Sync absichtlich deaktiviert)"
  {
    printf 'host: 0.0.0.0\nport: %s\nallowed_hosts:\n' "$PORT"
    host_list
    printf 'data_dir: %s\njob_retention_days: 14\n' "$DATA_DIR"
  } > "$studio"
  chown root:"$GROUP" "$studio"
  chmod 0640 "$studio"
}

ensure_env_value() {
  local key=$1 value=$2
  grep -q "^$key=." "$ENV_FILE" && return
  printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
}

copy_login_hash() {
  local login_hash
  grep -q '^ANKI_STUDIO_PASSWORD_HASH=.' "$ENV_FILE" && return
  [[ -r "$LOGIN_SOURCE_ENV" ]] || return
  login_hash="$(grep -m 1 '^ANKI_STUDIO_PASSWORD_HASH=.' "$LOGIN_SOURCE_ENV" || true)"
  [[ -n "$login_hash" ]] && printf '%s\n' "$login_hash" >> "$ENV_FILE"
}

ensure_environment() {
  [[ -e "$ENV_FILE" ]] || install -o root -g root -m 0600 /dev/null "$ENV_FILE"
  ensure_env_value "ANKI_STUDIO_SESSION_SECRET" "$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
  ensure_env_value "ANKI_STUDIO_SECRET_KEY" "$(python3 -c 'import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')"
  copy_login_hash
}

replace_checkout() {
  local incoming="$APP_DIR.new"
  rm -rf "$incoming" "$PREVIOUS_DIR"
  mv "$stage" "$incoming"
  if [[ -e "$APP_DIR" ]]; then
    mv "$APP_DIR" "$PREVIOUS_DIR"
  fi
  mv "$incoming" "$APP_DIR"
  # mktemp creates the staging directory as 0700. The separate system user
  # needs read and execute access to immutable program files, never to data.
  chmod -R a+rX "$APP_DIR"
}

install_dependencies() {
  if ! command -v uv >/dev/null; then
    echo "uv fehlt; zuerst die reguläre Vorschau oder Installation einrichten." >&2
    exit 1
  fi
  log "Abhängigkeiten des Codex-Standes installieren"
  (cd "$APP_DIR" && UV_CACHE_DIR="$UV_CACHE" uv sync --quiet --locked --no-dev --extra pdf)
}

install_unit() {
  cat > "/etc/systemd/system/$UNIT.service" <<UNIT_FILE
[Unit]
Description=Anki Studio (isolierte Codex-Vorschau $commit)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
Group=$GROUP
WorkingDirectory=$APP_DIR
Environment=ANKI_STUDIO_CONFIG=$CONFIG_DIR/studio.yaml
EnvironmentFile=$ENV_FILE
EnvironmentFile=-$DATA_DIR/runtime.env
ExecStart=$APP_DIR/.venv/bin/anki-studio serve
Restart=always
RestartSec=2
UMask=0077
NoNewPrivileges=yes
PrivateTmp=yes
ProtectHome=yes
ProtectSystem=strict
ReadWritePaths=$DATA_DIR

[Install]
WantedBy=multi-user.target
UNIT_FILE
  systemctl daemon-reload
  systemctl enable --quiet "$UNIT"
}

restart_and_check() {
  log "Dienst $UNIT neu starten"
  systemctl restart "$UNIT"
  if ! curl -fs --retry 20 --retry-connrefused --retry-delay 1 -o /dev/null "http://127.0.0.1:$PORT/healthz"; then
    journalctl -u "$UNIT" -n 30 --no-pager >&2
    echo "Codex-Vorschau antwortet nicht." >&2
    return 1
  fi
  log "Codex-Vorschau läuft auf Port $PORT"
}

restore_previous() {
  # Restore the last isolated Codex checkout after a failed update.
  if [[ ! -e "$PREVIOUS_DIR" ]]; then
    return
  fi
  log "Vorherigen Codex-Stand wiederherstellen"
  rm -rf "$APP_DIR"
  mv "$PREVIOUS_DIR" "$APP_DIR"
  systemctl restart "$UNIT" || true
}

main() {
  require_root
  require_stage
  ensure_service_user
  ensure_config
  ensure_environment
  replace_checkout
  if ! install_dependencies; then
    restore_previous
    exit 1
  fi
  install_unit
  if restart_and_check; then
    return
  fi
  restore_previous
  exit 1
}

main "$@"
