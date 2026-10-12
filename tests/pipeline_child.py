import json
import os
from pathlib import Path
import signal
import sys
import subprocess
import time

role, mode, root = sys.argv[1:]
root = Path(root)
(root / (role + ".pid")).write_text(str(os.getpid()))

descendant = None

def stop(sig, _):
    (root / (role + ".signal")).write_text(str(sig))
    if descendant:
        descendant.wait(timeout=2)
    raise SystemExit(0)

signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
if mode == "descendants" and role == "receiver":
    descendant = subprocess.Popen([sys.executable, __file__, "descendant", "silence", str(root)])
if mode == role + "-exit":
    time.sleep(0.3)
    raise SystemExit(0)
if role == "decoder" and mode == "eof":
    sys.stdout.close()
    os.close(1)
if role == "decoder" and mode == "readings":
    print("not json", flush=True)
    print(json.dumps({"_": "telegram", "meter": "dme173", "id": "12345678", "total_m3": 1.2}), flush=True)
while True:
    time.sleep(0.1)
