#!/bin/sh
# linuxserver-style entrypoint: honor PUID/PGID, own /data + /config, drop privileges.
set -e

PUID=${PUID:-1000}
PGID=${PGID:-1000}

if [ "$(id -u)" = "0" ]; then
    # Re-map the libarr user/group to the host-provided ids (runs as root only
    # long enough to do this — then we drop to the libarr user).
    groupmod -o -g "$PGID" libarr 2>/dev/null || true
    usermod -o -u "$PUID" libarr 2>/dev/null || true
    mkdir -p /data /config
    chown -R libarr:libarr /data /config
    exec gosu libarr "$@"
fi

exec "$@"
