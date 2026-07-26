#!/bin/sh
set -eu

CONFIG_FILE=${SSHTUNNEL_CONFIG:-"$HOME/.config/sshtunnel/config.env"}

if [ ! -r "$CONFIG_FILE" ]; then
    echo "sshtunnel: configuration is not readable: $CONFIG_FILE" >&2
    exit 1
fi

# This file is created and controlled by the current user.
# shellcheck disable=SC1090
. "$CONFIG_FILE"

: "${SSH_HOST:?SSH_HOST is required}"
: "${SSH_USER:?SSH_USER is required}"

SSH_PORT=${SSH_PORT:-22}
SOCKS_BIND_ADDRESS=${SOCKS_BIND_ADDRESS:-127.0.0.1}
SOCKS_PORT=${SOCKS_PORT:-1080}
SERVER_ALIVE_INTERVAL=${SERVER_ALIVE_INTERVAL:-15}
SERVER_ALIVE_COUNT_MAX=${SERVER_ALIVE_COUNT_MAX:-3}
SSH_IDENTITY_FILE=${SSH_IDENTITY_FILE:-}

case "$SSH_PORT:$SOCKS_PORT:$SERVER_ALIVE_INTERVAL:$SERVER_ALIVE_COUNT_MAX" in
    *[!0-9:]*)
        echo "sshtunnel: ports and alive counters must be integers" >&2
        exit 1
        ;;
esac

set -- /usr/bin/ssh \
    -N -T \
    -o BatchMode=yes \
    -o ExitOnForwardFailure=yes \
    -o "ServerAliveInterval=$SERVER_ALIVE_INTERVAL" \
    -o "ServerAliveCountMax=$SERVER_ALIVE_COUNT_MAX" \
    -p "$SSH_PORT" \
    -D "$SOCKS_BIND_ADDRESS:$SOCKS_PORT"

if [ -n "$SSH_IDENTITY_FILE" ]; then
    if [ ! -r "$SSH_IDENTITY_FILE" ]; then
        echo "sshtunnel: identity file is not readable: $SSH_IDENTITY_FILE" >&2
        exit 1
    fi
    set -- "$@" -i "$SSH_IDENTITY_FILE"
fi

exec "$@" "$SSH_USER@$SSH_HOST"
