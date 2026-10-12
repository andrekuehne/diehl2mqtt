import json
from datetime import datetime
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from watermeter.health import healthy, identity
from watermeter.settings import Settings
from watermeter.supervisor import Supervisor


class LifecycleTests(unittest.TestCase):
    def test_pipeline_overrides_berlin_timezone_in_summer_and_winter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # POSIX timezone rules reproduce Berlin without relying on tzdata.
            berlin = "CET-1CEST,M3.5.0,M10.5.0/3"
            with patch.dict(os.environ, {"TZ": berlin}):
                process = self.launch(root, "timezone")
                try:
                    deadline = time.monotonic() + 4
                    while (len(list(root.glob("*.timezone"))) < 3 or
                           not (root / "last_received_at").exists()) and time.monotonic() < deadline:
                        time.sleep(0.02)
                    self.assertEqual(len(list(root.glob("*.timezone"))), 3)
                    for path in root.glob("*.timezone"):
                        self.assertEqual(json.loads(path.read_text()),
                                         {"tz": "UTC0", "winter": "12:00", "summer": "12:00"})
                    self.assertEqual(os.environ["TZ"], berlin)
                finally:
                    process.send_signal(signal.SIGTERM)
                    stdout, stderr = process.communicate(timeout=8)
            self.assertEqual(process.returncode, 0, stderr)
            reading = json.loads(stdout)
            timestamp = datetime.fromisoformat(reading["timestamp"].replace("Z", "+00:00"))
            received = datetime.fromisoformat(reading["received_at"].replace("Z", "+00:00"))
            self.assertLess(abs((received - timestamp).total_seconds()), 2)
            self.no_children(root)

    def test_usb_diagnostics_keep_errors_without_upstream_secrets(self):
        supervisor = Supervisor(Settings(), {}, "/unused", "/unused")
        with patch("watermeter.supervisor.log") as output:
            supervisor.diagnostic(0, b"usb_open err")
            supervisor.diagnostic(0, b"or -3\nprivate-key=never-log-this\n")
            supervisor.diagnostic(0, b"usb_claim_interface error -6\nFailed to open rtlsdr device #0.\n")
            supervisor.diagnostic(0, b"usb_open error -3\n")
            supervisor.diagnostic(2, b"decrypt failed: never-log-this\n")
        messages = [call.args[0] for call in output.call_args_list]
        self.assertIn("Pipeline component 1: USB access denied (permissions or security policy) (libusb -3)", messages)
        self.assertIn("Pipeline component 1: USB device busy (another reader or kernel driver) (libusb -6)", messages)
        self.assertIn("Pipeline component 1: could not open RTL-SDR", messages)
        self.assertEqual(sum("libusb -3" in message for message in messages), 1)
        self.assertNotIn("never-log-this", "\n".join(messages))
        self.assertLessEqual(len(supervisor.diagnostic_tails[0]), 256)

    def test_failure_drains_pending_diagnostic_and_reports_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            supervisor = Supervisor(Settings(), dict(os.environ), tmp, tmp)
            child = subprocess.Popen([sys.executable, "-c", "import sys; sys.stderr.write('usb_open error -4\\n'); sys.exit(9)"],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            supervisor.children.append(child)
            os.set_blocking(child.stderr.fileno(), False)
            try:
                child.wait(timeout=3)
                with patch("watermeter.supervisor.log") as output:
                    self.assertEqual(supervisor.failure("pipeline stopped"), 1)
                messages = [call.args[0] for call in output.call_args_list]
                self.assertIn("Pipeline component 1: USB device disconnected (libusb -4)", messages)
                self.assertIn("Pipeline component 1 exited with code 9", messages)
            finally:
                supervisor.cleanup()

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
