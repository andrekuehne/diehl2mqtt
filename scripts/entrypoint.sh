#!/bin/sh
set -eu
umask 077
if [ -f /etc/diehl2mqtt/install.json ]; then
    exec /usr/bin/python3 /opt/diehl2mqtt/launcher/watermeter/lxc.py "$@"
fi
exec python -m watermeter "$@"
