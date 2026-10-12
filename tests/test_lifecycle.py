import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from watermeter.health import healthy, identity


class LifecycleTests(unittest.TestCase):
    def launch(self, root, mode):
        return subprocess.Popen([sys.executable, "tests/lifecycle_harness.py", str(root), mode],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def no_children(self, root):
        for pid_file in root.glob("*.pid"):
            self.assertIsNone(identity(int(pid_file.read_text())))

    def test_component_failure_and_eof(self):
        for mode in ("receiver-exit", "demod-exit", "decoder-exit", "eof", "startup", "oversized"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                process = self.launch(root, mode)
                stdout, _ = process.communicate(timeout=8)
                self.assertNotEqual(process.returncode, 0)
                self.assertEqual(stdout, "")
                self.no_children(root)
                self.assertFalse(healthy(root))

    def test_signals_silence_and_readings(self):
        for sig in (signal.SIGTERM, signal.SIGINT):
            for mode in ("silence", "readings", "descendants", "broker-outage"):
                with self.subTest(sig=sig, mode=mode), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    process = self.launch(root, mode)
                    deadline = time.monotonic() + 4
                    while not healthy(root) and time.monotonic() < deadline:
                        time.sleep(0.02)
                    self.assertTrue(healthy(root))
                    # All children have installed their signal handlers before signaling.
                    expected = 4 if mode == "descendants" else 3
                    while len(list(root.glob("*.pid"))) != expected and time.monotonic() < deadline:
                        time.sleep(0.02)
                    time.sleep(0.2)
                    process.send_signal(sig)
                    stdout, stderr = process.communicate(timeout=8)
                    self.assertEqual(process.returncode, 0, stderr)
                    if mode in ("readings", "broker-outage"):
                        reading = json.loads(stdout)
                        self.assertEqual(reading["total_m3"], 1.2)
                        self.assertEqual((root / "last_received_at").read_text().strip(), reading["received_at"])
                    else:
                        self.assertEqual(stdout, "")
                    for path in root.glob("*.signal"):
                        self.assertEqual(int(path.read_text()), sig)
                    self.assertEqual(len(list(root.glob("*.signal"))), expected)
                    self.no_children(root)
                    self.assertFalse(healthy(root))
