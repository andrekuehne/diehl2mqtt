from contextlib import redirect_stderr
import io
import logging
import unittest

from watermeter.log import configure, log
from watermeter.settings import Settings
from watermeter.supervisor import Supervisor


class LoggingTests(unittest.TestCase):
    def tearDown(self):
        configure()

    def test_severity_thresholds_and_no_duplicate_handlers(self):
        levels = ('debug', 'info', 'warning', 'error', 'critical')
        for threshold, level in enumerate(levels):
            with self.subTest(level=level), redirect_stderr(io.StringIO()) as output:
                configure(level)
                configure(level)
                for severity in levels:
                    log(severity + ' message', getattr(logging, severity.upper()))
                self.assertEqual(output.getvalue().splitlines(), [
                    f'[{severity.upper()}] {severity} message' for severity in levels[threshold:]])

    def test_usb_errors_survive_error_threshold_and_debug_never_relays_secrets(self):
        for level in ('debug', 'error'):
            with self.subTest(level=level), redirect_stderr(io.StringIO()) as output:
                configure(level)
                supervisor = Supervisor(Settings(), {}, '/unused', '/unused')
                supervisor.diagnostic(0, b'private-key=never-log-this\n')
                supervisor.diagnostic(0, b'usb_open error -3\n')
                self.assertIn('[ERROR] Pipeline component 1: USB access denied', output.getvalue())
                self.assertNotIn('never-log-this', output.getvalue())
                self.assertEqual('upstream text suppressed' in output.getvalue(), level == 'debug')
