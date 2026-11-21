#!/usr/bin/env bash
# Install or update Anki Studio from the published main branch (AS-040).
#
# Run as root in the target container only from a checked and published main:
#   ssh ct-anki-studio 'bash -s' < deploy/install.sh
#
# Existing /etc/anki-studio/env, /etc/anki-studio/studio.yaml, and
# /var/lib/anki-studio are deliberately preserved. This script never copies
# development files or edits an existing user configuration.
#
# A running preview (deploy/preview.sh) is taken over: its service is stopped
# and removed, and its data (login, generator YAML, stored API keys, models,
# jobs) moves from systemd's DynamicUser folder to /var/lib/anki-studio.
set -euo pipefail

readonly REPO_URL="https://github.com/Egwe/anki-studio.git"
readonly BRANCH="main"
readonly APP_DIR="/opt/anki-studio"
readonly CONFIG_DIR="/etc/anki-studio"
readonly DATA_DIR="/var/lib/anki-studio"
readonly UV_CACHE="/var/cache/anki-studio/uv"
readonly USER="anki-studio"
readonly GROUP="anki-studio"
readonly UNIT="anki-studio"
readonly PREVIEW_UNIT="anki-studio-preview"
readonly PREVIEW_DATA_DIR="/var/lib/private/anki-studio"
readonly PORT="8000"
readonly UV_VERSION="0.13.7"

log() {
  printf '==> %s\n' "$*"
}

require_root() {
  if [[ $EUID -ne 0 ]]; then
    echo "Bitte als root ausführen." >&2
    exit 1
  fi
}

ensure_git() {
  command -v git >/dev/null && return
  log "git installieren"
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends git ca-certificates >/dev/null
}

ensure_uv() {
  if command -v uv >/dev/null && [[ "$(uv --version | cut -d' ' -f2)" == "$UV_VERSION" ]]; then
    return
  fi
  log "uv $UV_VERSION installieren"
  local temporary archive="uv-x86_64-unknown-linux-gnu.tar.gz"
  temporary="$(mktemp -d)"
  curl -fsSL -o "$temporary/$archive" "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/$archive"
  curl -fsSL -o "$temporary/$archive.sha256" "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/$archive.sha256"
  (cd "$temporary" && sha256sum --quiet -c "$archive.sha256")
  tar -xzf "$temporary/$archive" -C "$temporary" --strip-components=1
  install -m 0755 "$temporary/uv" "$temporary/uvx" /usr/local/bin/
  rm -rf "$temporary"
}

ensure_service_user() {
  getent passwd "$USER" >/dev/null && return
  log "Systembenutzer $USER anlegen"
  useradd --system --user-group --home-dir /nonexistent --shell /usr/sbin/nologin "$USER"
}

update_checkout() {
  if [[ ! -d "$APP_DIR/.git" ]]; then
    log "Repository nach $APP_DIR klonen"
    git clone --quiet --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
  fi
  if [[ -n "$(git -C "$APP_DIR" status --porcelain)" ]]; then
    echo "Checkout in $APP_DIR ist nicht sauber; Update abgebrochen." >&2
    exit 1
  fi
  log "geprüften Stand von $BRANCH holen"
  git -C "$APP_DIR" fetch --quiet origin "$BRANCH"
  git -C "$APP_DIR" checkout --quiet --detach "origin/$BRANCH"
  # Program files contain no configuration or user data; the service account
  # needs read and execute access even when root has a restrictive umask.
  chmod -R a+rX "$APP_DIR"
  log "Commit $(git -C "$APP_DIR" log -1 --format='%h %s')"
}

install_dependencies() {
  log "Abhängigkeiten aus uv.lock installieren"
  install -d -o "$USER" -g "$GROUP" -m 0750 "$UV_CACHE"
  (cd "$APP_DIR" && UV_CACHE_DIR="$UV_CACHE" uv sync --quiet --locked --no-dev --extra pdf)
}

retire_preview() {
  local unit_file="/etc/systemd/system/$PREVIEW_UNIT.service"
  if [[ -e "$unit_file" ]]; then
    log "Vorschau-Dienst $PREVIEW_UNIT stoppen und entfernen"
    systemctl disable --now --quiet "$PREVIEW_UNIT"
    rm -f "$unit_file"
    systemctl daemon-reload
  fi
  [[ -L "$DATA_DIR" ]] || return 0
  # DynamicUser keeps the state in /var/lib/private (0700, root) and links it
  # to /var/lib/anki-studio; the fixed service user cannot pass through that.
  if [[ "$(readlink -f "$DATA_DIR")" != "$PREVIEW_DATA_DIR" ]]; then
    echo "$DATA_DIR ist ein unerwarteter Link; Installation abgebrochen." >&2
    exit 1
  fi
  log "Daten der Vorschau nach $DATA_DIR übernehmen"
  rm "$DATA_DIR"
  mv "$PREVIEW_DATA_DIR" "$DATA_DIR"
  chown -R "$USER:$GROUP" "$DATA_DIR"
}

host_list() {
  local addresses name
  read -ra addresses <<< "$(hostname -I)"
  for name in localhost 127.0.0.1 "$(hostname)" "${addresses[@]}"; do
    printf '  - %s\n' "$name"
  done
}

ensure_studio_yaml() {
  local studio="$CONFIG_DIR/studio.yaml"
  [[ -e "$studio" ]] && return
  log "$studio anlegen"
  {
    printf 'host: 0.0.0.0\nport: %s\nallowed_hosts:\n' "$PORT"
    host_list
    printf 'data_dir: %s\njob_retention_days: 14\n' "$DATA_DIR"
  } > "$studio"
  chown root:"$GROUP" "$studio"
  chmod 0640 "$studio"
}

append_env_if_missing() {
  local key=$1 value=$2 environment="$CONFIG_DIR/env"
  grep -q "^$key=." "$environment" && return
  printf '%s=%s\n' "$key" "$value" >> "$environment"
}

ensure_env_file() {
  local environment="$CONFIG_DIR/env"
  if [[ ! -e "$environment" ]]; then
    log "$environment anlegen (0600)"
    install -m 0600 /dev/null "$environment"
  fi
  append_env_if_missing "ANKI_STUDIO_SESSION_SECRET" "$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
  append_env_if_missing "ANKI_STUDIO_SECRET_KEY" "$(python3 -c 'import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')"
  if ! grep -q '^ANKI_STUDIO_PASSWORD_HASH=.' "$environment"; then
    log "Noch kein Login-Passwort gesetzt; siehe README, Installation Schritt 4."
  fi
}

ensure_directories() {
  install -d -o root -g "$GROUP" -m 0750 "$CONFIG_DIR"
  install -d -o "$USER" -g "$GROUP" -m 0750 "$DATA_DIR"
  ensure_studio_yaml
  ensure_env_file
}

install_unit() {
  cat > "/etc/systemd/system/$UNIT.service" <<UNIT_FILE
[Unit]
Description=Anki Studio
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
Group=$GROUP
WorkingDirectory=$APP_DIR
Environment=ANKI_STUDIO_CONFIG=$CONFIG_DIR/studio.yaml
EnvironmentFile=$CONFIG_DIR/env
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
    echo "Anki Studio antwortet nicht." >&2
    exit 1
  fi
  log "Anki Studio läuft auf Port $PORT"
}

main() {
  require_root
  ensure_git
  ensure_uv
  ensure_service_user
  update_checkout
  install_dependencies
  retire_preview
  ensure_directories
  install_unit
  restart_and_check
}

main "$@"
