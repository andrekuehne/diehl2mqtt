"""Run the real LXC launcher with the existing simulated receiver pipeline."""
import os
from pathlib import Path
import subprocess
import sys
from watermeter import lxc, update

root = Path(sys.argv[1])
update.ROOT = root
update.CONFIG = root / 'install.json'
lxc.RUNTIME = root
update.os.geteuid = lambda: 0  # No host privilege needed for the simulated guest.
if sys.argv[2] == 'timeout':
    lxc.VALIDATION_SECONDS = 1

def start(name, args):
    if name == 'new' and sys.argv[2] == 'timeout':
        return subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
    mode = 'receiver-exit' if name == 'new' and sys.argv[2] == 'fail' else 'silence'
    return subprocess.Popen([sys.executable, str(Path(__file__).with_name('lifecycle_harness.py')), str(root), mode],
                            start_new_session=True)

lxc.start = start
raise SystemExit(lxc.run(['live']))
