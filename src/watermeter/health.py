"""Process health, independent of RF silence and MQTT connectivity."""
import json
import os
from pathlib import Path
import time


def identity(pid):
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        if fields[0] in ("Z", "X"):
            return None
        return fields[19]  # starttime guards against PID reuse
    except (OSError, IndexError):
        return None


def healthy(root=Path("/run/watermeter")):
    try:
        state = json.loads((root / "health.json").read_text())
        return (0 <= time.monotonic() - state["heartbeat"] < 5
                and len(state["processes"]) == 4
                and all(identity(p["pid"]) == p["started"] and p["started"] is not None
                        for p in state["processes"]))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def updating(root=Path('/run/watermeter')):
    """Allow a short, live launcher's validation window during app replacement."""
    try:
        state = json.loads((root / 'rollout.json').read_text())
        now = time.monotonic()
        return (0 <= now - state['heartbeat'] < 5
                and 0 < state['deadline'] - now <= 60
                and state['started'] is not None
                and identity(state['pid']) == state['started'])
    except (OSError, ValueError, KeyError, TypeError):
        return False


if __name__ == "__main__":
    raise SystemExit(0 if healthy() or updating() else 1)
