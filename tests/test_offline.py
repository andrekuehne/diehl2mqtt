"""Run against actual pinned decoder when installed; no valid owner key required."""
from pathlib import Path
import os
import secrets
import shutil
import json
import subprocess
import tempfile
import unittest
from watermeter.offline import decode
from watermeter.settings import Settings, ConfigError


@unittest.skipUnless(shutil.which("wmbusmeters"), "wmbusmeters not available")
class OfflineTests(unittest.TestCase):
    def test_rtlwmbus_metadata_keeps_utc_timestamp_and_raw_signal(self):
        from watermeter.private import private_config
        from watermeter.reading import accept
        from watermeter.supervisor import Supervisor
        packet = Path("tests/fixtures/dme173_12345678.hex").read_text().strip()
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings()
            env = dict(os.environ, TZ="CET-1CEST,M3.5.0,M10.5.0/3")
            with private_config(settings, "00112233445566778899aabbccddeeff", Path(tmp)) as config:
                pipeline = Supervisor(settings, env, config, tmp)
                for stamp in ("2026-01-01 12:00:00", "2026-07-01 12:00:00"):
                    frame = f"C1;1;1;{stamp}.000000;133;0;12345678;0x{packet}\n"
                    decoded = subprocess.run(pipeline.commands[2], input=frame, text=True,
                                             capture_output=True, env=pipeline.env, timeout=10)
                    self.assertEqual(decoded.returncode, 0)
                    reading = accept(decoded.stdout.strip(), settings)
                    self.assertEqual(reading["timestamp"], stamp.replace(" ", "T") + "Z")
                    self.assertEqual(reading["rssi_dbm"], 133)
                    self.assertEqual(reading["total_m3"], 0.252)
                    self.assertEqual(reading["driver"], "dme173")
                    self.assertEqual(reading["meter"], "dme173")
                    self.assertEqual(reading["status"], "OK")

    def test_synthetic_fixture_decrypts_with_public_key(self):
        from dataclasses import replace
        with tempfile.TemporaryDirectory() as tmp:
            fixture = "tests/fixtures/dme173_12345678.hex"
            key = "00112233445566778899aabbccddeeff"
            readings = decode(Settings(), key, dict(os.environ), fixture, Path(tmp))
            self.assertEqual(readings[0]["id"], "12345678")
            self.assertEqual(readings[0]["total_m3"], 0.252)
            self.assertEqual(readings[0]["flow_temperature_c"], 16.8)
            for configured in (replace(Settings(), meter_id="87654321"),
                               replace(Settings(), driver="hydrus")):
                with self.assertRaises(ConfigError):
                    decode(configured, key, dict(os.environ), fixture, Path(tmp))
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_encrypted_fixture_rejects_wrong_runtime_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConfigError):
                decode(Settings(), secrets.token_hex(16), dict(os.environ),
                       "tests/fixtures/dme173_12345678.hex", Path(tmp))
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_invalid_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "corrupt.hex"
            path.write_text("corrupt")
            with self.assertRaises(ConfigError):
                decode(Settings(), secrets.token_hex(16), dict(os.environ), path, Path(tmp))

    def test_timeout_and_no_key_in_argv_or_environment(self):
        from unittest.mock import patch
        import subprocess
        key = secrets.token_hex(16)
        with tempfile.TemporaryDirectory() as tmp:
            with patch("watermeter.offline.subprocess.run", side_effect=subprocess.TimeoutExpired("decoder", 10)) as run:
                with self.assertRaises(ConfigError):
                    decode(Settings(), key, dict(os.environ), "tests/fixtures/dme173_12345678.hex", Path(tmp))
                argv = run.call_args.args[0]
                self.assertTrue(all(key not in part for part in argv))
                self.assertEqual(run.call_args.kwargs["timeout"], 10)
                self.assertNotIn("METER_AES_KEY", run.call_args.kwargs["env"])
            self.assertEqual(list(Path(tmp).iterdir()), [])
