#!/bin/sh
set -eu

UNIT_DIR="$HOME/.config/systemd/user"

systemctl --user disable --now sshtunnel.service >/dev/null 2>&1 || true
rm -f "$UNIT_DIR/sshtunnel.service" "$HOME/.local/libexec/sshtunnel/run"
systemctl --user daemon-reload

echo "Removed the systemd user service and runner."
echo "Configuration was preserved at $HOME/.config/sshtunnel/config.env"
