"""Test only; never copied into the production image."""
from dataclasses import replace
import os
from pathlib import Path
import sys
from watermeter.settings import Settings
from watermeter.supervisor import Supervisor

root = Path(sys.argv[1])
mode = sys.argv[2]
helper = str(Path(__file__).with_name("pipeline_child.py").resolve())
commands = [[sys.executable, helper, role, mode, str(root)] for role in ("receiver", "demod", "decoder")]
settings = Settings()
if mode == "startup":
    commands[1] = ["/definitely/missing/watermeter-executable"]
try:
    publisher = None
    if mode.startswith(('log-', 'json-')):
        settings = replace(settings, mqtt=mode.startswith('log-'), log_level=mode.split('-', 1)[1])
        commands = [[sys.executable, helper, role, 'readings', str(root)]
                    for role in ('receiver', 'demod', 'decoder')]
        class RecordingPublisher:
            connected = True
            def set_alive(self, alive):
                pass
            def start(self):
                pass
            def close(self):
                pass
            def submit(self, payload):
                (root / 'published.json').write_text(payload)
        if settings.mqtt:
            publisher = RecordingPublisher()
    if mode == "broker-outage":
        from watermeter.mqtt import Publisher
        publisher = Publisher(replace(Settings(), mqtt=True, discovery=True, host="127.0.0.1", port=9))
    raise SystemExit(Supervisor(settings, dict(os.environ), root, root, publisher=publisher, commands=commands).run())
except Exception:
    raise SystemExit(2)
