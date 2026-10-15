"""Versioned binary selection must stay inside the active application bundle."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from watermeter import provenance, lxc
from watermeter.settings import Settings, ConfigError
from watermeter.supervisor import Supervisor


class NativeSelectionTests(unittest.TestCase):
    def test_both_variants_follow_the_running_bundle_during_upgrade_and_rollback(self):
        with tempfile.TemporaryDirectory() as temp:
            for release in ('old', 'new', 'old'):
                root = Path(temp) / release
                root.mkdir(exist_ok=True)
                (root / 'bundle.json').write_text('{}')
                (root / 'provenance').mkdir(exist_ok=True)
                (root / 'provenance/versions.txt').write_text('rtl_wmbus_dev_commit=' + release + '\n')
                with patch.object(provenance, 'APPLICATION_ROOT', root):
                    for decoder, name in (('reference', 'rtl_wmbus'), ('dev', 'rtl_wmbus_dev')):
                        commands = Supervisor(Settings(decoder=decoder), {}, '/config', '/unused').commands
                        self.assertEqual(commands[1][0], str(root / 'bin' / name))
                        self.assertEqual(commands[2][0], str(root / 'bin/wmbusmeters'))
                    self.assertEqual(provenance.versions()['rtl_wmbus_dev_commit'], release)

    def test_missing_native_decoder_cannot_use_another_release_on_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'bundle.json').write_text('{}')
            other = root / 'other-release/bin'
            other.mkdir(parents=True)
            for name in ('rtl_sdr', 'rtl_wmbus_dev', 'wmbusmeters'):
                path = other / name
                path.write_text('#!/bin/sh\nexit 0\n')
                path.chmod(0o755)
            with patch.object(provenance, 'APPLICATION_ROOT', root):
                supervisor = Supervisor(Settings(decoder='dev'), {'PATH': str(other)}, '/config', root)
                with patch('watermeter.supervisor.subprocess.Popen') as spawn:
                    with self.assertRaisesRegex(ConfigError, 'Selected dev'):
                        supervisor.run()
                spawn.assert_not_called()

    def test_launcher_starts_the_selected_release_application(self):
        with patch.object(lxc.update, 'release_path', return_value=Path('/releases/selected')), \
             patch.object(lxc.subprocess, 'Popen') as spawn:
            lxc.start('selected', ['live'])
        env = spawn.call_args.kwargs['env']
        self.assertEqual(env['PYTHONPATH'], '/releases/selected/watermeter')
        self.assertTrue(env['PATH'].startswith('/releases/selected/venv/bin:/releases/selected/bin:'))
