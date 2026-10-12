#!/bin/sh
umask 077
export PYTHONPATH=/opt/watermeter
exec /opt/venv/bin/python -m watermeter.update "$@"
