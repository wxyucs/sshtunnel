#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
CONFIG_DIR="$HOME/.config/sshtunnel"
BIN_DIR="$HOME/.local/bin"
BIN="$BIN_DIR/sshtunnel"
LEGACY_PLIST="$HOME/Library/LaunchAgents/com.wxyucs.sshtunnel.plist"
LEGACY_DOMAIN="gui/$(id -u)"

if ! command -v python3 >/dev/null 2>&1; then
    echo "sshtunnel: Python 3.9 or newer is required" >&2
    exit 1
fi

python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' || {
    echo "sshtunnel: Python 3.9 or newer is required" >&2
    exit 1
}

mkdir -p "$CONFIG_DIR" "$BIN_DIR"
install -m 755 "$SCRIPT_DIR/sshtunnel.py" "$BIN"

if [ ! -e "$CONFIG_DIR/config.json" ]; then
    install -m 600 "$SCRIPT_DIR/config.example.json" "$CONFIG_DIR/config.json"
    echo "Created $CONFIG_DIR/config.json"
fi

# Remove the superseded launchd integration without deleting user configuration.
launchctl bootout "$LEGACY_DOMAIN" "$LEGACY_PLIST" >/dev/null 2>&1 || true
rm -f "$LEGACY_PLIST" "$HOME/.local/libexec/sshtunnel/run"

echo "Installed $BIN"
if [ -e "$CONFIG_DIR/config.env" ]; then
    echo "Legacy config.env was preserved; migrate its values into config.json."
fi
echo "Edit $CONFIG_DIR/config.json, then run: $BIN start --web"
