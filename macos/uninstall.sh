#!/bin/sh
set -eu

BIN="$HOME/.local/bin/sshtunnel"

if [ -x "$BIN" ]; then
    "$BIN" stop --web >/dev/null 2>&1 || true
fi
rm -f "$BIN"

echo "Removed the sshtunnel CLI."
echo "Configuration, runtime state, and logs were preserved."
