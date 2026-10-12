"""Run against actual pinned decoder when installed; no valid owner key required."""
from pathlib import Path
import os
import secrets
import shutil
import tempfile
import unittest
from watermeter.offline import decode
from watermeter.settings import Settings, ConfigError


@unittest.skipUnless(shutil.which("wmbusmeters"), "wmbusmeters not available")
class OfflineTests(unittest.TestCase):
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
