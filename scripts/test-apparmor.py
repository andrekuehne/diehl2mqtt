#!/usr/bin/env python3
"""Load a unique disposable host AppArmor profile and test an isolated app.

Requires Docker and host AppArmor. CI uses sudo for profile loading; --loader
docker uses only a temporary helper with MAC_ADMIN and a securityfs mount.
Neither mode touches real USB devices, production configuration or brokers.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile
import uuid

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--loader', choices=('sudo', 'docker'), default='sudo')
args = parser.parse_args()
name = 'diehl2mqtt-test-' + uuid.uuid4().hex


def command(*argv):
    subprocess.run(argv, check=True)


with tempfile.TemporaryDirectory(prefix='diehl2mqtt-apparmor-') as tmp:
    profile = Path(tmp) / 'apparmor.txt'
    profile.write_text((root / 'ha-addon/apparmor.txt').read_text().replace('profile diehl2mqtt ', f'profile {name} ', 1))

    def load(flag):
        if args.loader == 'sudo':
            command('sudo', '-n', 'apparmor_parser', flag, '-W', str(profile))
        else:
            command('docker', 'run', '--rm', '--network', 'none', '--cap-add', 'MAC_ADMIN',
                    '--security-opt', 'apparmor=unconfined',
                    '--mount', 'type=bind,src=/sys/kernel/security,dst=/sys/kernel/security',
                    '--mount', f'type=bind,src={profile},dst=/profile,readonly',
                    'watermeter:test', 'apparmor_parser', flag, '-W', '/profile')

    loaded = False
    try:
        load('-r')
        loaded = True
        command('docker', 'volume', 'create', name)
        setup = '''import json,os,pathlib
p=pathlib.Path('/data')
(p/'options.json').write_text(json.dumps(dict(meter_id='12345678',aes_key='00112233445566778899aabbccddeeff',mqtt_auto=False,mqtt_host='127.0.0.1')))
(p/'options.json').chmod(0o600)
(p/'writable-control').touch()
(p/'writable-control').chmod(0o666)
(p/'001').mkdir()
(p/'001/001').write_bytes(b'group-write-test')
(p/'001/001').chmod(0o660)
'''
        command('docker', 'run', '--rm', '--network', 'none', '--mount', f'type=volume,src={name},dst=/data',
                '--entrypoint', 'python', 'watermeter:ha-addon', '-c', setup)
        command('docker', 'run', '--rm', '--network', 'none', '--security-opt', f'apparmor={name}',
                '--tmpfs', '/tmp:rw,noexec,nosuid,nodev',
                '--mount', f'type=volume,src={name},dst=/data',
                '--mount', f'type=volume,src={name},dst=/dev/bus/usb',
                '--mount', f'type=bind,src={root / "scripts/apparmor-smoke.py"},dst=/opt/watermeter/apparmor_smoke.py,readonly',
                '--mount', f'type=bind,src={root / "tests/fixtures/dme173_12345678.hex"},dst=/opt/watermeter/test.hex,readonly',
                '--entrypoint', '/usr/bin/tini', 'watermeter:ha-addon', '-g', '--',
                'python', '/opt/watermeter/apparmor_smoke.py')
    finally:
        subprocess.run(['docker', 'volume', 'rm', '-f', name], check=False)
        if loaded:
            load('-R')
