#!/usr/bin/env python3
"""Actual add-on process in a disposable container: fake RF only, no host USB."""
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import urllib.error
import urllib.request

root = Path('/tmp/addon-smoke')
root.mkdir(mode=0o700)
os.chown(root, 10001, 0)
# Supervisor/Docker tmpfs may be noexec; only data belongs under /tmp.
bin_dir = Path('/opt/addon-smoke-bin')
bin_dir.mkdir()
helper = '''#!/opt/venv/bin/python
import os, pathlib, sys, time
root = pathlib.Path('/tmp/addon-smoke')
name = pathlib.Path(sys.argv[0]).name
assert not any(k in os.environ for k in ('SUPERVISOR_TOKEN', 'METER_AES_KEY', 'MQTT_PASSWORD'))
assert os.environ['TZ'] == 'UTC0'
if name == 'rtl_sdr':
    marker = root / 'first-start'
    if not marker.exists():
        marker.touch()
        time.sleep(0.5)
        sys.exit(1)
if name == 'wmbusmeters':
    print('{"_":"telegram","meter":"dme173","id":"00123456","total_m3":1.2,"rssi_dbm":133}', flush=True)
if name == 'rtl_wmbus':
    assert sys.argv[1:] == ['-f', '-p', 'S', '-a', '-t', '0']
while True:
    time.sleep(0.1)
'''
for binary in ('rtl_sdr', 'rtl_wmbus', 'wmbusmeters'):
    path = bin_dir / binary
    path.write_text(helper)
    path.chmod(0o755)
data = Path('/data')
data.mkdir(exist_ok=True)
(data / 'options.json').write_text(json.dumps(dict(
    meter_id='00123456', aes_key='00112233445566778899aabbccddeeff',
    mqtt_auto=False, mqtt_host='127.0.0.1', mqtt_port=9, fast_math=True, algorithm='runlength')))
env = dict(os.environ, PATH=str(bin_dir) + ':' + os.environ['PATH'], SUPERVISOR_TOKEN='synthetic-token',
           TZ='CET-1CEST,M3.5.0,M10.5.0/3')
out = root / 'stdout'
err = root / 'stderr'
with out.open('w') as stdout, err.open('w') as stderr:
    child = subprocess.Popen(['python', '-m', 'watermeter.addon'], env=env, stdout=stdout, stderr=stderr)
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            assert child.poll() is None, err.read_text()
            try:
                with urllib.request.urlopen('http://127.0.0.1:8099/health', timeout=1) as response:
                    if response.status == 200 and 'retrying' in err.read_text():
                        break
            except (OSError, urllib.error.HTTPError):
                pass
            time.sleep(0.1)
        else:
            raise AssertionError('Add-on did not recover from simulated USB failure: ' + err.read_text())
        # RF silence and an unavailable MQTT broker must not fail process health.
        time.sleep(6)
        with urllib.request.urlopen('http://127.0.0.1:8099/health', timeout=1) as response:
            assert response.status == 200
        reading = json.loads(out.read_text().splitlines()[-1])
        assert reading['id'] == '00123456' and reading['total_m3'] == 1.2
        assert reading['rssi_dbm'] == 133
        state = json.loads(Path('/tmp/watermeter/health.json').read_text())
        for process in state['processes']:
            status = dict(line.split(':', 1) for line in Path(f"/proc/{process['pid']}/status").read_text().splitlines() if ':' in line)
            assert set(status['Uid'].split()) == {'10001'}
            assert set(status['Gid'].split()) == {'0'}
            assert not status['Groups'].strip()
            assert all(int(status[k].strip(), 16) == 0 for k in ('CapEff', 'CapPrm', 'CapInh', 'CapAmb', 'CapBnd'))
            assert status['NoNewPrivs'].strip() == '1'
        assert subprocess.run(['python', '-m', 'watermeter.privileges']).returncode == 0
        assert '/tmp/watermeter' in str(next(Path('/tmp/watermeter').glob('decoder-*')))
        child.send_signal(signal.SIGTERM)
        assert child.wait(timeout=12) == 0
        assert not list(Path('/tmp/watermeter').glob('decoder-*'))
        assert not Path('/tmp/watermeter/health.json').exists()
        assert '00112233445566778899aabbccddeeff' not in out.read_text() + err.read_text()
        assert 'synthetic-token' not in out.read_text() + err.read_text()
        print('PASS: add-on options, non-root/capability-free processes, tmpfs, child environment, USB recovery, quiet health and shutdown')
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
