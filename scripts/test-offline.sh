#!/bin/sh
set -eu
# Public synthetic fixture/key only. Never load a production meter key here.
image=${WATERMETER_IMAGE:-watermeter:local}
exec docker run --rm --network none --tmpfs /run/watermeter:mode=0700 \
    -e METER_AES_KEY=00112233445566778899aabbccddeeff "$image" offline
