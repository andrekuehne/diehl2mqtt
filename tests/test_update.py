"""Native update security and rollback checks; no production hardware or network."""
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch

from watermeter import health, lxc, update


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / 'install.json'
        self.config.write_text(json.dumps(dict(kind='diehl2mqtt-lxc', release='v0.4.0')))
        for name in ('old', 'new'):
            path = self.root / 'releases' / name
            path.mkdir(parents=True)
            (path / 'bundle.json').write_text(json.dumps(dict(version='v0.4.0' if name == 'old' else 'v0.5.0')))
        (self.root / 'current').symlink_to('releases/old')
        for name, value in (('ROOT', self.root), ('CONFIG', self.config)):
            patcher = patch.object(update, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def archive(self, name, kind=tarfile.REGTYPE, link=''):
        path = self.root / 'bundle.tar.gz'
        with tarfile.open(path, 'w:gz') as out:
            info = tarfile.TarInfo(name)
            info.type, info.linkname = kind, link
            info.size = 1 if kind == tarfile.REGTYPE else 0
            out.addfile(info, io.BytesIO(b'x') if info.size else None)
        return path

    def test_reject_archive_escapes_links_and_devices(self):
        for name, kind, link in (('/tmp/escape', tarfile.REGTYPE, ''),
                                 ('watermeter/../../escape', tarfile.REGTYPE, ''),
                                 ('watermeter/link', tarfile.SYMTYPE, '/etc'),
                                 ('watermeter/link', tarfile.LNKTYPE, 'bundle.json'),
                                 ('bin/device', tarfile.CHRTYPE, '')):
            with self.subTest(name=name, kind=kind):
                dest = self.root / 'unpack'
                dest.mkdir(exist_ok=True)
                with self.assertRaises(update.UpdateError):
                    update.extract(self.archive(name, kind, link), dest)
                self.assertEqual(update.current_name(), 'old')

    def test_checksum_failure_keeps_current_and_cleans_staging(self):
        with patch.object(update, 'download', return_value=b'0' * 64 + b'  diehl2mqtt-v0.5.0-app-amd64.tar.gz\n'), \
             patch.object(update.urllib.request, 'urlopen', return_value=io.BytesIO(b'corrupt archive')):
            with self.assertRaisesRegex(update.UpdateError, 'checksum mismatch'):
                update.stage('v0.5.0')
        self.assertEqual(update.current_name(), 'old')
        self.assertEqual(list(self.root.glob('.staging-*')), [])

    def test_abi_mismatch_requires_redeploy(self):
        metadata = dict(format=1, version='v0.5.0', architecture='x86_64', python=list(sys.version_info[:2]), os=['debian', '12'])
        with patch.object(update.platform, 'machine', return_value='x86_64'):
            update.compatible(metadata, 'v0.5.0', dict(ID='debian', VERSION_ID='12'))
            for field, value in (('architecture', 'aarch64'), ('python', [3, 99]), ('os', ['debian', '13'])):
                with self.assertRaises(update.UpdateError):
                    update.compatible(dict(metadata, **{field: value}), 'v0.5.0', dict(ID='debian', VERSION_ID='12'))

    def test_queue_validate_and_explicit_rollback_preserve_settings(self):
        self.config.write_text(json.dumps(dict(kind='diehl2mqtt-lxc', release='v0.4.0', custom='preserved')))
        with patch.object(lxc, 'RUNTIME', self.root):
            update.queue('new')
            self.assertEqual(update.current_name(), 'new')
            lxc.finish(update.read_state(), True)
            self.assertEqual(json.loads(self.config.read_text())['custom'], 'preserved')
            self.assertEqual(update.read_state()['previous'], 'old')
            update.queue(update.read_state()['previous'])
            lxc.finish(update.read_state(), True)
            self.assertEqual(update.current_name(), 'old')
            self.assertEqual(json.loads(self.config.read_text())['release'], 'v0.4.0')

    def test_failed_validation_restores_previous_release(self):
        with patch.object(lxc, 'RUNTIME', self.root):
            update.queue('new')
            lxc.finish(update.read_state(), False)
        self.assertEqual(update.current_name(), 'old')
        self.assertEqual(update.read_state()['phase'], 'rolled_back')
        self.assertEqual(json.loads(self.config.read_text())['release'], 'v0.4.0')

    def test_launcher_recovers_from_spawn_failure(self):
        update.queue('new')
        class Child:
            returncode = 3
            def poll(self): return 3
        with patch.object(lxc, 'RUNTIME', self.root), patch.object(update, 'context'), \
             patch.object(lxc, 'start', side_effect=[OSError('failed'), Child()]), \
             patch.dict(os.environ, {'METER_AES_KEY': '', 'MQTT_PASSWORD': ''}):
            self.assertEqual(lxc.run(['live']), 3)
        self.assertEqual(update.current_name(), 'old')
        self.assertEqual(update.read_state()['phase'], 'rolled_back')

    def test_launcher_recovers_interrupted_pointer_switch(self):
        update.atomic_json(self.root / 'update.json', dict(phase='pending', old='old', new='new', version='v0.5.0'))
        class Child:
            returncode = 3
            def poll(self): return 3
        with patch.object(lxc, 'RUNTIME', self.root), patch.object(update, 'context'), \
             patch.object(lxc, 'start', return_value=Child()) as start, \
             patch.dict(os.environ, {'METER_AES_KEY': '', 'MQTT_PASSWORD': ''}):
            self.assertEqual(lxc.run(['live']), 3)
        self.assertEqual([call.args[0] for call in start.call_args_list], ['new', 'old'])
        self.assertEqual(update.current_name(), 'old')

    def test_maintenance_window_requires_live_identity_and_bounded_time(self):
        now = time.monotonic()
        state = dict(heartbeat=now, deadline=now + 59, pid=os.getpid(), started=health.identity(os.getpid()))
        update.atomic_json(self.root / 'rollout.json', state)
        self.assertTrue(health.updating(self.root))
        for overrides in (dict(deadline=now + 120), dict(heartbeat=now - 10), dict(started='wrong')):
            update.atomic_json(self.root / 'rollout.json', dict(state, **overrides))
            self.assertFalse(health.updating(self.root))

    def test_running_launcher_updates_and_rolls_back_real_processes(self):
        for mode in ('success', 'fail', 'timeout'):
            with self.subTest(mode=mode):
                update.switch('old')
                (self.root / 'update.json').unlink(missing_ok=True)
                process = subprocess.Popen([sys.executable, 'tests/update_harness.py', str(self.root), mode],
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    deadline = time.monotonic() + 8
                    while not health.healthy(self.root) and time.monotonic() < deadline:
                        time.sleep(0.02)
                    self.assertTrue(health.healthy(self.root))
                    old_pid = json.loads((self.root / 'health.json').read_text())['processes'][0]['pid']
                    update.queue('new')
                    deadline = time.monotonic() + 12
                    while update.read_state().get('phase') == 'pending' and time.monotonic() < deadline:
                        time.sleep(0.05)
                    self.assertEqual(update.read_state()['phase'], 'complete' if mode == 'success' else 'rolled_back')
                    self.assertEqual(update.current_name(), 'new' if mode == 'success' else 'old')
                    self.assertIsNone(health.identity(old_pid))
                finally:
                    process.terminate()
                    process.communicate(timeout=12)
                self.assertEqual(process.returncode, 0)
                self.assertFalse(health.healthy(self.root))
                for path in self.root.glob('*.pid'):
                    self.assertIsNone(health.identity(int(path.read_text())))

    def test_nonmanaged_installation_refused(self):
        self.config.unlink()
        with self.assertRaises(update.UpdateError):
            update.context()

    @unittest.skipUnless(Path('/tests/package-app.py').exists(), 'requires built test image')
    def test_real_image_bundle_roundtrip(self):
        archive = self.root / 'real.tar.gz'
        with archive.open('wb') as out:
            subprocess.run(['/usr/bin/python3', '/tests/package-app.py', '--version', 'v0.5.0',
                            '--image', 'ghcr.io/andrekuehne/diehl2mqtt@sha256:' + '0' * 64], stdout=out, check=True)
        import hashlib
        checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
        with patch.object(update, 'download', return_value=(checksum + '  diehl2mqtt-v0.5.0-app-amd64.tar.gz\n').encode()), \
             patch.object(update.urllib.request, 'urlopen', side_effect=lambda *a, **k: archive.open('rb')):
            name = update.stage('v0.5.0')
        self.assertTrue((update.release_path(name) / 'watermeter/watermeter/__main__.py').is_file())
        self.assertEqual(update.current_name(), 'old')
