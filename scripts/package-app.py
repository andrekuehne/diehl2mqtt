#!/usr/bin/env python3
"""Export the tested image's native application, never its runtime configuration."""
import argparse
import io
import json
from pathlib import Path
import platform
import re
import sys
import tarfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True)
    parser.add_argument('--image', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', args.version):
        parser.error('Expected a stable release version')
    if not re.fullmatch(r'ghcr\.io/andrekuehne/diehl2mqtt@sha256:[0-9a-f]{64}', args.image):
        parser.error('Expected the immutable published image reference')
    os_release = platform.freedesktop_os_release()
    metadata = dict(format=1, version=args.version, image=args.image,
                    architecture=platform.machine(), python=list(sys.version_info[:2]),
                    os=[os_release['ID'], os_release['VERSION_ID']])
    with tarfile.open(fileobj=sys.stdout.buffer, mode='w|gz', dereference=False) as archive:
        def clean(info):
            if info.name.startswith('venv/bin') or '__pycache__' in Path(info.name).parts:
                return None
            if not (info.isdir() or info.isfile() or
                    (info.issym() and info.name == 'venv/lib64' and info.linkname == 'lib')):
                raise ValueError('Unexpected application link or special file')
            info.uid = info.gid = 0
            info.uname = info.gname = ''
            info.mtime = 0
            return info
        for source, target in (('/opt/watermeter', 'watermeter'), ('/opt/venv', 'venv'),
                               ('/usr/share/watermeter', 'provenance')):
            archive.add(source, arcname=target, filter=clean)
        for name in ('wmbusmeters', 'rtl_wmbus', 'rtl_wmbus_dev', 'entrypoint.sh', 'healthcheck.sh', 'update'):
            archive.add('/usr/local/bin/' + name, arcname='bin/' + name, filter=clean)
        data = json.dumps(metadata).encode()
        info = tarfile.TarInfo('bundle.json')
        info.size, info.mode = len(data), 0o644
        archive.addfile(info, io.BytesIO(data))


if __name__ == '__main__':
    main()
