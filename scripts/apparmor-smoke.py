#!/usr/bin/env python3
"""Run inside the enforced production profile; only public test data."""
import json
import ctypes
import os
from pathlib import Path
import signal
import subprocess
import time
import urllib.request

from watermeter import addon
from watermeter.health import identity
from watermeter.private import private_config, require_tmpfs
from watermeter.privileges import APP_UID, APP_GID, drop_privileges

root = addon.ROOT
root.mkdir(mode=0o700)
require_tmpfs(root)
options = addon.load_options()
os.chown(root, APP_UID, APP_GID)
drop_privileges()
settings, key, password = addon.configuration(options)
del options
assert os.getuid() == 10001 and os.getgid() == 0 and os.getgroups() == []
status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
assert all(int(status[k].strip(), 16) == 0 for k in ('CapEff', 'CapPrm', 'CapInh', 'CapAmb', 'CapBnd'))
assert status['NoNewPrivs'].strip() == '1'
try:
    os.setuid(0)
except PermissionError:
    pass
else:
    raise AssertionError('Root could be regained')

# Root-owned group-writable fixture checks HAOS-style DAC without touching USB.
# This is a regular file, NOT a simulated SDR or a hardware reception test.
with open('/dev/bus/usb/001/001', 'r+b') as stream:
    assert stream.read() == b'group-write-test'
    stream.seek(0)
    stream.write(b'group-write-pass')

# These paths pass ordinary filesystem permissions but AppArmor must block them.
for path in ('/tmp/outside-runtime', '/data/writable-control'):
    try:
        Path(path).write_text('must be denied')
    except PermissionError:
        pass
    else:
        raise AssertionError('AppArmor permitted an unexpected write')
try:
    subprocess.run(['/bin/sh', '-c', 'exit 0'], check=True)
except PermissionError:
    pass
else:
    raise AssertionError('AppArmor permitted a shell')

with private_config(settings, key, root, offline=True) as config:
    result = subprocess.run(['wmbusmeters', f'--useconfig={config}'],
                            input=Path('/opt/watermeter/test.hex').read_text(),
                            capture_output=True, text=True, timeout=10, env=addon.child_environment(os.environ) | {'TZ': 'UTC0'})
    assert result.returncode == 0, 'Decoder failed in enforced profile'
    reading = next(json.loads(line) for line in result.stdout.splitlines() if line.startswith('{'))
    assert reading['id'] == '12345678' and reading['total_m3'] == 0.252
    # Decode config is ephemeral, never writable outside the runtime directory.
assert not list(root.glob('decoder-*'))

# Exercise DNS, TLS trust-store loading and real libusb enumeration without RF.
import socket
import ssl
assert socket.getaddrinfo('localhost', 1883)
assert ssl.create_default_context().cert_store_stats()['x509_ca'] > 0
# A negative RTL-SDR lookup alone cannot detect broken USB enumeration. Check
# libudev's parent-directory access even on CI VMs with no USB controllers.
# Where root hubs exist, libusb must actually find devices. Read descriptors
# only: never open any host USB device or start RF reception.
assert list(Path('/sys/bus').iterdir()), 'Cannot enumerate sysfs buses'
root_hubs = list(Path('/sys/bus/usb/devices').glob('usb*'))
libusb = ctypes.CDLL('libusb-1.0.so.0')
context = ctypes.c_void_p()
devices = ctypes.c_void_p()
libusb.libusb_get_device_list.restype = ctypes.c_ssize_t
assert libusb.libusb_init(ctypes.byref(context)) == 0
try:
    count = libusb.libusb_get_device_list(context, ctypes.byref(devices))
    try:
        assert count >= 0, f'USB enumeration failed with error {count}'
        if root_hubs:
            assert count >= len(root_hubs), f'USB enumeration found {count} devices for {len(root_hubs)} root hubs'
    finally:
        if count >= 0:
            libusb.libusb_free_device_list(devices, 1)
finally:
    libusb.libusb_exit(context)
# An impossible index also keeps this safe/deterministic when host sysfs lists
# an SDR: no receiver is selected, even though its USB nodes are not mounted.
result = subprocess.run(['rtl_sdr', '-d', '2147483647', '-f', '868.95M', '-s', '1600000', '-'],
                        capture_output=True, timeout=10)
assert result.returncode != 0 and any(message in result.stderr for message in
                                     (b'No supported devices', b'No matching devices found'))
child = subprocess.Popen(['rtl_wmbus', '-f', '-p', 'S'], stdin=subprocess.PIPE,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
time.sleep(0.2)
assert child.poll() is None
os.killpg(child.pid, signal.SIGTERM)
child.wait(timeout=5)
child.stdin.close()

state = dict(heartbeat=time.monotonic(), processes=[dict(pid=os.getpid(), started=identity(os.getpid()))] * 4)
(root / 'health.json').write_text(json.dumps(state))
with addon.health_server(root) as server:
    with urllib.request.urlopen('http://127.0.0.1:8099/health', timeout=2) as response:
        assert response.status == 200
    # Docker's root-started healthcheck drops privileges before reading health.
    assert subprocess.run(['python', '-m', 'watermeter.privileges']).returncode == 0
print('PASS: enforced AppArmor, denied shell/writes, non-root USB-style permissions, actual decoder, libusb enumeration, TLS, health and signals')
