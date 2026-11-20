#!/usr/bin/env bash
# Vorschau-Betrieb von Anki Studio im LXC "anki-studio" (bis zur Installation nach AS-040).
#
# Aufruf vom Entwicklungsrechner, nachdem main gepusht ist:
#   ssh ct-anki-studio 'bash -s' < deploy/preview.sh
#
# Das Skript ist idempotent. Es installiert bei Bedarf git und uv, holt den Stand von main
# aus GitHub nach /opt/anki-studio, installiert die Abhängigkeiten aus uv.lock, legt eine
# fehlende Konfiguration an (vorhandene Werte bleiben unverändert) und startet den Dienst
# anki-studio-preview neu. Der Dienst läuft ohne Root-Rechte mit einem dynamischen Benutzer.
set -euo pipefail

readonly REPO_URL="https://github.com/Egwe/anki-studio.git"
readonly BRANCH="main"
readonly APP_DIR="/opt/anki-studio"
readonly CONFIG_DIR="/etc/anki-studio"
readonly UV_CACHE="/var/cache/anki-studio/uv"
readonly UNIT="anki-studio-preview"
readonly UV_VERSION="0.13.7"
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
  local tmp archive="uv-x86_64-unknown-linux-gnu.tar.gz"
  tmp="$(mktemp -d)"
  curl -fsSL -o "$tmp/$archive" "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/$archive"
  curl -fsSL -o "$tmp/$archive.sha256" "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/$archive.sha256"
  (cd "$tmp" && sha256sum --quiet -c "$archive.sha256")
  tar -xzf "$tmp/$archive" -C "$tmp" --strip-components=1
  install -m 0755 "$tmp/uv" "$tmp/uvx" /usr/local/bin/
  rm -rf "$tmp"
}

update_checkout() {
  if [[ ! -d "$APP_DIR/.git" ]]; then
    log "Repository nach $APP_DIR klonen"
    git clone --quiet --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
  fi
  log "Stand von $BRANCH holen"
  git -C "$APP_DIR" fetch --quiet origin "$BRANCH"
  git -C "$APP_DIR" checkout --quiet --detach "origin/$BRANCH"
  log "Commit $(git -C "$APP_DIR" log -1 --format='%h %s')"
}

sync_environment() {
  log "Abhängigkeiten aus uv.lock installieren"
  mkdir -p "$UV_CACHE"
  (cd "$APP_DIR" && UV_CACHE_DIR="$UV_CACHE" UV_PYTHON_DOWNLOADS=never uv sync --quiet --locked --no-dev)
}

host_list() {
  local addresses name
  read -ra addresses <<< "$(hostname -I)"
  for name in localhost 127.0.0.1 "$(hostname)" "${addresses[@]}"; do
    printf '  - %s\n' "$name"
  done
}

ensure_config() {
  local studio="$CONFIG_DIR/studio.yaml" env_file="$CONFIG_DIR/env"
  install -d -m 0755 "$CONFIG_DIR"
  if [[ ! -e "$studio" ]]; then
    log "$studio anlegen"
    printf 'host: 0.0.0.0\nport: %s\n' "$PORT" > "$studio"
  fi
  if ! grep -q '^allowed_hosts:' "$studio"; then
    log "allowed_hosts mit Namen und Adressen des Containers in $studio ergänzen"
    { printf 'allowed_hosts:\n'; host_list; } >> "$studio"
  fi
  if [[ ! -e "$env_file" ]]; then
    log "$env_file anlegen (0600)"
    install -m 0600 /dev/null "$env_file"
  fi
  if ! grep -q '^ANKI_STUDIO_SESSION_SECRET=.' "$env_file"; then
    log "zufälligen Session-Schlüssel in $env_file ergänzen"
    printf 'ANKI_STUDIO_SESSION_SECRET=%s\n' \
      "$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')" >> "$env_file"
  fi
  if ! grep -q '^ANKI_STUDIO_PASSWORD_HASH=.' "$env_file"; then
    log "Noch kein Login-Passwort gesetzt; siehe README, Abschnitt Anmeldung."
  fi
}

install_unit() {
  cat > "/etc/systemd/system/$UNIT.service" <<UNIT_FILE
[Unit]
Description=Anki Studio (Vorschau bis AS-040)
After=network-online.target
Wants=network-online.target

[Service]
DynamicUser=yes
StateDirectory=anki-studio
Environment=ANKI_STUDIO_CONFIG=$CONFIG_DIR/studio.yaml
EnvironmentFile=$CONFIG_DIR/env
ExecStart=$APP_DIR/.venv/bin/anki-studio serve
Restart=on-failure
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes

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
  update_checkout
  sync_environment
  ensure_config
  install_unit
  restart_and_check
}

main "$@"
