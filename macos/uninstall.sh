#!/bin/sh
set -eu

PLIST="$HOME/Library/LaunchAgents/com.wxyucs.sshtunnel.plist"
DOMAIN="gui/$(id -u)"

launchctl bootout "$DOMAIN" "$PLIST" >/dev/null 2>&1 || true
rm -f "$PLIST" "$HOME/.local/libexec/sshtunnel/run"

echo "Removed the launch agent and runner."
echo "Configuration was preserved at $HOME/.config/sshtunnel/config.env"
