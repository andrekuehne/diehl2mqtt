#!/bin/sh
umask 077
exec /opt/venv/bin/python -m watermeter.update "$@"
