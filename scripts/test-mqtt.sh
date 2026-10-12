#!/bin/sh
set -eu
# Test image adds a disposable broker; production image never runs a broker.
docker build --target test -t watermeter:test .
exec docker run --rm --network none --tmpfs /run/watermeter:mode=0700 watermeter:test
