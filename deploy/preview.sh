#!/usr/bin/env bash
# Vorschau-Betrieb von Anki Studio im LXC "anki-studio" (bis zur Installation nach AS-040).
#
# Aufruf vom Entwicklungsrechner, nachdem main gepusht ist:
#   ssh ct-anki-studio 'bash -s' < deploy/preview.sh
#
# Das Skript ist idempotent. Es installiert bei Bedarf git und uv, holt den Stand von main
# aus GitHub nach /opt/anki-studio, installiert die Abhängigkeiten aus uv.lock, legt eine
# fehlende Konfiguration an (vorhandene Dateien bleiben unverändert) und startet den Dienst
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
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends git ca-certificates
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

ensure_config() {
  install -d -m 0755 "$CONFIG_DIR"
  if [[ ! -e "$CONFIG_DIR/studio.yaml" ]]; then
    log "$CONFIG_DIR/studio.yaml anlegen"
    printf 'host: 0.0.0.0\nport: %s\n' "$PORT" > "$CONFIG_DIR/studio.yaml"
  fi
  if [[ ! -e "$CONFIG_DIR/env" ]]; then
    log "$CONFIG_DIR/env anlegen (0600, noch ohne Einträge)"
    install -m 0600 /dev/null "$CONFIG_DIR/env"
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
  if ! curl -fsS --retry 20 --retry-connrefused --retry-delay 1 -o /dev/null "http://127.0.0.1:$PORT/healthz"; then
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
