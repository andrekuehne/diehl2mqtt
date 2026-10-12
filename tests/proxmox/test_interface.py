"""Installer dialog and bootstrap checks without creating a guest."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('ui_installer', ROOT / 'scripts/install-proxmox.py')
app = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(app)


class InterfaceTests(unittest.TestCase):
    def test_default_and_advanced_settings_keep_required_meter_prompts(self):
        import argparse
        args = argparse.Namespace(ctid=None, memory=None, disk=None, release='v0.5.0')
        cases = [
            ('default', ['00123456', 'broker.invalid', '1883', 'mqtt'], 512, 2),
            ('advanced', ['123', 'reader', '1024', '8', 'vmbr1', '42',
                          '192.0.2.123/24', '192.0.2.1', '00123456', 'broker.invalid', '1883', 'mqtt'], 1024, 8),
        ]
        for mode, inputs, memory, disk in cases:
            with self.subTest(mode=mode), patch.object(app, 'UI', True), \
                 patch.object(app.sys.stdin, 'isatty', return_value=True), \
                 patch.object(app, 'choose', side_effect=[mode, 'local-lvm', 'auth', 'false']), \
                 patch.object(app, 'prompt', side_effect=inputs) as prompt, \
                 patch.object(app, 'command_json', side_effect=[123, [{'storage': 'local-lvm', 'active': 1}]]), \
                 patch.object(app, 'check_unused'), patch.object(app, 'check_exclusive'), \
                 patch.object(app, 'select_device', return_value={'port': '1-2'}), \
                 patch.object(app, 'release_image', return_value='test-image'), \
                 patch.object(app.Path, 'exists', return_value=True):
                settings = app.collect_settings(args)
            self.assertEqual(settings['memory'], memory)
            self.assertEqual(settings['disk'], disk)
            self.assertEqual(settings['env']['METER_ID'], '00123456')
            meter = next(c for c in prompt.call_args_list if c.args[0] == 'Eight-digit Wireless M-Bus meter ID')
            self.assertEqual(len(meter.args), 1)
            if mode == 'advanced':
                self.assertEqual(settings['bridge'], 'vmbr1')
                self.assertEqual(settings['vlan'], '42')
                self.assertEqual(settings['gateway'], '192.0.2.1')

    @unittest.skipUnless(shutil.which('whiptail'), 'requires whiptail')
    def test_real_password_dialog_keeps_screen_and_value_separate(self):
        import fcntl
        import pty
        import select
        import struct
        import sys
        import termios
        import time
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 28, 90, 0, 0))
        def terminal():
            os.setsid()
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)
        source = ROOT / 'scripts/install-proxmox.py'
        code = ("import importlib.util,json; "
                f"s=importlib.util.spec_from_file_location('installer',{str(source)!r}); "
                "a=importlib.util.module_from_spec(s); s.loader.exec_module(a); a.UI=True; "
                "print(json.dumps(a.secret('MQTT password')))")
        child = subprocess.Popen([sys.executable, '-c', code], stdin=slave, stderr=slave,
                                 stdout=subprocess.PIPE, env=dict(os.environ, TERM='xterm-256color'),
                                 preexec_fn=terminal)
        os.close(slave)
        try:
            time.sleep(.25)
            os.write(master, b'public-synthetic-password\r')
            output = child.communicate(timeout=5)[0]
            screen = b''
            while select.select([master], [], [], .1)[0]:
                try:
                    screen += os.read(master, 65536)
                except OSError:
                    break
            self.assertEqual(child.returncode, 0)
            self.assertEqual(json.loads(output), 'public-synthetic-password')
            self.assertNotIn(b'public-synthetic-password', screen)
            self.assertIn(b'MQTT password', screen)
            self.assertIn(b'\x1b[', screen)
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate()
            os.close(master)

    def test_password_is_returned_privately_and_never_in_arguments(self):
        with patch.object(app, 'UI', True), patch.object(app.subprocess, 'run',
             return_value=subprocess.CompletedProcess([], 0, stderr=' synthetic password ')) as run:
            self.assertEqual(app.secret('MQTT password'), ' synthetic password ')
        args = run.call_args.args[0]
        self.assertIn('--passwordbox', args)
        self.assertNotIn(' synthetic password ', args)
        self.assertEqual(run.call_args.kwargs['stderr'], subprocess.PIPE)
        self.assertEqual(run.call_args.kwargs['stdout'], app.sys.stderr)

    def test_dialog_cancel_does_not_create_a_guest(self):
        with patch.object(app, 'preflight'), patch.object(app.sys, 'argv', ['install', '--ui']), \
             patch.object(app.sys.stdin, 'isatty', return_value=True), \
             patch.object(app.sys.stderr, 'isatty', return_value=True), \
             patch.object(app.shutil, 'which', return_value='/usr/bin/whiptail'), \
             patch.dict(os.environ, TERM='xterm'), \
             patch.object(app.subprocess, 'run', return_value=subprocess.CompletedProcess([], 255, '')), \
             patch.object(app, 'execute_install') as execute:
            with self.assertRaises(SystemExit):
                app.main()
            execute.assert_not_called()

    def test_confirmation_defaults_to_no(self):
        with patch.object(app, 'UI', True), patch.object(app.subprocess, 'run',
             return_value=subprocess.CompletedProcess([], 1, '')) as run:
            self.assertFalse(app.confirm('Create CT?'))
        self.assertIn('--defaultno', run.call_args.args[0])

    def test_invalid_meter_id_reopens_dialog_without_default_identity(self):
        with patch.object(app, 'UI', True), patch.object(app, 'dialog', side_effect=['bad', '', '00123456']) as dialog:
            self.assertEqual(app.prompt('Meter ID', pattern=r'[0-9]{8}'), '00123456')
        self.assertEqual(dialog.call_args_list[0].args, ('inputbox', 'Meter ID', ''))
        self.assertEqual(dialog.call_args_list[1].args[0], 'msgbox')


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        for name, script in {
            'pct': 'exit 0', 'pveversion': 'exit 0',
            'curl': '''[ "${TEST_FAIL:-0}" = 1 ] && exit 22
while [ "$#" -gt 0 ]; do
  if [ "$1" = -o ]; then
    if [ "${TEST_CORRUPT:-0}" = 1 ]; then printf bad > "$2"; else /bin/cp "$TEST_SOURCE" "$2"; fi
    exit 0
  fi
  shift
done
exit 1''',
            'python3': '''printf '%s\\n' "$@" > "$TEST_ARGS"
cat > "$TEST_INPUT"
exit "${TEST_CODE:-0}"''',
        }.items():
            path = self.bin / name
            path.write_text('#!/bin/sh\n' + script + '\n')
            path.chmod(0o700)
        self.env = dict(os.environ, PATH=str(self.bin) + ':' + os.environ['PATH'], TMPDIR=str(self.root),
                        TEST_SOURCE=str(ROOT / 'scripts/install-proxmox.py'),
                        TEST_ARGS=str(self.root / 'args'), TEST_INPUT=str(self.root / 'input'))

    def launch(self, *args, **extra):
        code = (ROOT / 'ct/diehl2mqtt.sh').read_text()
        return subprocess.run(['bash', '-c', code, '--', *args], input='terminal-preserved\n',
                              text=True, capture_output=True, env=dict(self.env, **extra))

    def test_pin_matches_installer_and_release(self):
        wrapper = (ROOT / 'ct/diehl2mqtt.sh').read_text()
        checksum = re.search(r'^INSTALLER_SHA256=([0-9a-f]{64})$', wrapper, re.M)[1]
        self.assertEqual(checksum, hashlib.sha256((ROOT / 'scripts/install-proxmox.py').read_bytes()).hexdigest())
        self.assertIn('INSTALLER_RELEASE=' + app.DEFAULT_RELEASE, wrapper)

    def test_one_line_form_preserves_input_arguments_and_cleans_up(self):
        result = self.launch('--memory', '1024', '--disk', '8')
        self.assertEqual(result.returncode, 0, result.stderr)
        args = (self.root / 'args').read_text().splitlines()
        self.assertEqual(args[1:], ['--ui', '--memory', '1024', '--disk', '8'])
        self.assertEqual((self.root / 'input').read_text(), 'terminal-preserved\n')
        self.assertEqual(list(self.root.glob('diehl2mqtt-install.*')), [])

    def test_failed_or_corrupt_download_never_executes_python(self):
        for flags in (dict(TEST_FAIL='1'), dict(TEST_CORRUPT='1')):
            result = self.launch(**flags)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((self.root / 'args').exists())
            self.assertEqual(list(self.root.glob('diehl2mqtt-install.*')), [])

    def test_plain_override_and_exit_status_are_preserved(self):
        result = self.launch('--plain', TEST_CODE='7')
        self.assertEqual(result.returncode, 7)
        self.assertNotIn('--ui', (self.root / 'args').read_text().splitlines())
        self.assertEqual(list(self.root.glob('diehl2mqtt-install.*')), [])
