#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
CONFIG_DIR="$HOME/.config/sshtunnel"
LIBEXEC_DIR="$HOME/.local/libexec/sshtunnel"
UNIT_DIR="$HOME/.config/systemd/user"

if ! command -v systemctl >/dev/null 2>&1; then
    echo "sshtunnel: systemctl is required" >&2
    exit 1
fi

mkdir -p "$CONFIG_DIR" "$LIBEXEC_DIR" "$UNIT_DIR"
install -m 755 "$SCRIPT_DIR/run.sh" "$LIBEXEC_DIR/run"
install -m 644 "$SCRIPT_DIR/sshtunnel.service" "$UNIT_DIR/sshtunnel.service"

CONFIG_CREATED=0
if [ ! -e "$CONFIG_DIR/config.env" ]; then
    install -m 600 "$SCRIPT_DIR/config.example.env" "$CONFIG_DIR/config.env"
    CONFIG_CREATED=1
    echo "Created $CONFIG_DIR/config.env; edit it to start the tunnel."
fi

systemctl --user daemon-reload

if [ "$CONFIG_CREATED" -eq 0 ]; then
    systemctl --user enable --now sshtunnel.service
    echo "Installed and started sshtunnel.service."
else
    systemctl --user enable sshtunnel.service
    echo "Installed sshtunnel.service without starting it."
    echo "After editing $CONFIG_DIR/config.env, run: systemctl --user start sshtunnel"
fi
