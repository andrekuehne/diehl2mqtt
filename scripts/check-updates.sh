#!/bin/sh
set -eu
# Read-only: list candidates; never change pins or pull/deploy the reader.
python3 - <<'PY'
from pathlib import Path
import re
text = Path('Dockerfile').read_text()
for name in ('BASE_IMAGE', 'RTL_WMBUS_REF', 'WMBUSMETERS_REF'):
    print('Pinned:', re.search(r'^ARG ' + name + r'=(.+)$', text, re.M)[0])
PY
for repo in xaelsouth/rtl-wmbus wmbusmeters/wmbusmeters; do
    echo "Upstream stable tags: $repo"
    git ls-remote --tags "https://github.com/$repo.git" | sort -Vk2 | tail -8
done
python3 - <<'PY'
import json
import urllib.request
with urllib.request.urlopen('https://pypi.org/pypi/paho-mqtt/json', timeout=20) as response:
    print('Latest published paho-mqtt:', json.load(response)['info']['version'])
PY
if command -v docker >/dev/null 2>&1; then
    docker buildx imagetools inspect debian:bookworm-slim
fi
