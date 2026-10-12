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
if role == "decoder" and mode in ("readings", "broker-outage"):
    print("not json", flush=True)
    print(json.dumps({"_": "telegram", "meter": "dme173", "id": "12345678", "total_m3": 1.2}), flush=True)
if mode == "timezone":
    (root / (role + ".timezone")).write_text(json.dumps({
        "tz": os.environ.get("TZ"),
        "winter": time.strftime("%H:%M", time.localtime(1767268800)),
        "summer": time.strftime("%H:%M", time.localtime(1782907200)),
    }))
    if role == "decoder":
        print(json.dumps({"_": "telegram", "meter": "dme173", "id": "12345678", "total_m3": 1.2,
                          "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.localtime())}), flush=True)
if role == "decoder" and mode == "oversized":
    print("x" * 80000, end="", flush=True)
while True:
    time.sleep(0.1)
