#!/bin/ash
set -e

: "${IDENTITY_FILE:?IDENTITY_FILE is required}"
: "${USER:?USER is required}"
: "${HOST:?HOST is required}"

privoxy /etc/privoxy/config

exec ssh -N -T \
    -o StrictHostKeyChecking=no \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=15 \
    -o ServerAliveCountMax=3 \
    -D 0.0.0.0:1080 \
    -i "$IDENTITY_FILE" \
    "$USER@$HOST"
