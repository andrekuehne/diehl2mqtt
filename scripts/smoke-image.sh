#!/bin/sh
set -eu
for binary in rtl_sdr rtl_test rtl_wmbus wmbusmeters; do
    command -v "$binary" >/dev/null
    if ldd "$(command -v "$binary")" | grep -q 'not found'; then
        echo "Missing runtime libraries" >&2
        exit 1
    fi
done
wmbusmeters --version
rtl_wmbus -V
wmbusmeters --listdrivers | grep -E '^dme173[[:space:]]'
wmbusmeters --listfields=dme173 | grep total_m3
# These two utilities use nonzero help exits, not --version.
rtl_sdr -h >/tmp/rtl_sdr-help 2>&1 || test "$?" -eq 1
rtl_test -h >/tmp/rtl_test-help 2>&1 || test "$?" -eq 1
grep -q Usage /tmp/rtl_sdr-help
grep -q Usage /tmp/rtl_test-help
rm /tmp/rtl_sdr-help /tmp/rtl_test-help
python3 -c 'import ssl; print(ssl.OPENSSL_VERSION)'
python -c 'import paho.mqtt; print("paho-mqtt", paho.mqtt.__version__)'
cat /usr/share/watermeter/versions.txt
