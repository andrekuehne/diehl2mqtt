#!/bin/sh
set -eu
# No AES key/Compose secret required. Keep exclusive ownership of the receiver.
exec docker run --rm --network none \
    --mount type=bind,src=/dev/bus/usb,dst=/dev/bus/usb \
    --device-cgroup-rule 'c 189:* rmw' \
    --entrypoint rtl_test "${WATERMETER_IMAGE:-watermeter:local}" -t
