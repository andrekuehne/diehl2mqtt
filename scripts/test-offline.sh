#!/bin/sh
set -eu
# Pass only variable names; values never enter argv. No USB/broker dependencies.
image=${WATERMETER_IMAGE:-watermeter:local}
if [ -n "${METER_AES_KEY_FILE:-}" ]; then
    exec docker run --rm --network none --tmpfs /run/watermeter:mode=0700 \
        --mount "type=bind,src=$METER_AES_KEY_FILE,dst=/run/secrets/meter_aes_key,readonly" \
        -e METER_AES_KEY_FILE=/run/secrets/meter_aes_key "$image" offline
fi
exec docker run --rm --network none --tmpfs /run/watermeter:mode=0700 \
    -e METER_AES_KEY "$image" offline
