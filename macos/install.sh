#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
CONFIG_DIR="$HOME/.config/sshtunnel"
LIBEXEC_DIR="$HOME/.local/libexec/sshtunnel"
AGENT_DIR="$HOME/Library/LaunchAgents"
PLIST="$AGENT_DIR/com.wxyucs.sshtunnel.plist"
DOMAIN="gui/$(id -u)"

mkdir -p "$CONFIG_DIR" "$LIBEXEC_DIR" "$AGENT_DIR"
install -m 755 "$SCRIPT_DIR/run.sh" "$LIBEXEC_DIR/run"

CONFIG_CREATED=0
if [ ! -e "$CONFIG_DIR/config.env" ]; then
    install -m 600 "$SCRIPT_DIR/config.example.env" "$CONFIG_DIR/config.env"
    CONFIG_CREATED=1
    echo "Created $CONFIG_DIR/config.env; edit it to start the tunnel."
fi

launchctl bootout "$DOMAIN" "$PLIST" >/dev/null 2>&1 || true
install -m 644 "$SCRIPT_DIR/com.wxyucs.sshtunnel.plist" "$PLIST"

if [ "$CONFIG_CREATED" -eq 0 ]; then
    launchctl bootstrap "$DOMAIN" "$PLIST"
    echo "Installed and started com.wxyucs.sshtunnel."
else
    echo "Installed com.wxyucs.sshtunnel without starting it."
    echo "After editing $CONFIG_DIR/config.env, run: make -C $SCRIPT_DIR restart"
fi
