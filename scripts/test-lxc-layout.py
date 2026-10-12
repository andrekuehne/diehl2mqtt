#!/usr/bin/env python3
"""Exercise the installed guest layout in a disposable image, without USB/secrets."""
import importlib.util
import os
from pathlib import Path
import subprocess

spec = importlib.util.spec_from_file_location('installer', '/tmp/install-proxmox.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
installer.write_secret(Path('/'), 'meter_aes_key', '00112233445566778899aabbccddeeff', (0, 0))
installer.bootstrap_updates(Path('/'), 'v0.4.0', 'ghcr.io/andrekuehne/diehl2mqtt@sha256:' + '0' * 64, (0, 0))
subprocess.run(['/usr/local/bin/update', '--status'], check=True)
subprocess.run(['/opt/venv/bin/python', '-c', 'import paho.mqtt, watermeter.update, watermeter.lxc'], check=True)
subprocess.run(['/usr/local/bin/wmbusmeters', '--listdrivers'], check=True, stdout=subprocess.DEVNULL)
subprocess.run(['/usr/local/bin/rtl_wmbus', '-V'], check=True, stdout=subprocess.DEVNULL)
assert Path('/opt/diehl2mqtt/launcher/watermeter/lxc.py').is_file()
assert os.readlink('/opt/diehl2mqtt/current') == 'releases/v0.4.0-initial'
assert Path('/etc/diehl2mqtt/secrets/meter_aes_key').stat().st_mode & 0o777 == 0o600
print('PASS: native LXC layout, venv, binaries, updater and protected synthetic secret')
