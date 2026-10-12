"""Small native-LXC launcher: atomic app switch, health validation and rollback."""
import json
import fcntl
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

# This file runs with system Python, independently of the versioned venv.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from watermeter import update
from watermeter.health import healthy, identity

RUNTIME = Path('/run/watermeter')
VALIDATION_SECONDS = 60


def finish(state, success):
    old, new = state['old'], state['new']
    chosen = new if success else old
    if not success:
        update.switch(old)
    metadata = json.loads((update.release_path(chosen) / 'bundle.json').read_text())
    installed = json.loads(update.CONFIG.read_text())
    installed.update(release=metadata['version'], image=metadata.get('image', ''))
    update.atomic_json(update.CONFIG, installed)
    update.atomic_json(update.ROOT / 'update.json', {
        'phase': 'complete' if success else 'rolled_back',
        'version': metadata['version'], 'previous': old if success else None,
        'failed': None if success else new,
    })
    (RUNTIME / 'rollout.json').unlink(missing_ok=True)


def start(name, args):
    root = update.release_path(name)
    env = dict(os.environ, PYTHONPATH=str(root / 'watermeter'),
               PATH=f"{root / 'venv/bin'}:{root / 'bin'}:/usr/local/bin:/usr/bin:/bin")
    return subprocess.Popen([str(root / 'venv/bin/python'), '-m', 'watermeter', *args],
                            env=env, start_new_session=True)


def stop(child):
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()


def run(args):
    update.context()
    if os.environ.get('METER_AES_KEY') or os.environ.get('MQTT_PASSWORD'):
        raise update.UpdateError('Managed LXC startup requires secret files')
    RUNTIME.mkdir(mode=0o700, exist_ok=True)
    stopping = False
    def terminate(_signal, _frame):
        nonlocal stopping
        stopping = True
    previous_handlers = {s: signal.signal(s, terminate) for s in (signal.SIGTERM, signal.SIGINT)}
    child, active, deadline, stable = None, None, None, None
    try:
        while not stopping:
            selected = update.current_name()
            state = update.read_state()
            if state.get('phase') == 'pending' and selected == state.get('old'):
                # Recover a power loss between writing the transaction and changing the link.
                with (update.ROOT / 'update.lock').open('a') as lock:
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        pass
                    else:
                        update.switch(state['new'])
                        continue
            pending = state.get('phase') == 'pending' and state.get('new') == selected
            if selected != active:
                if child:
                    stop(child)
                active = selected
                try:
                    child = start(active, args)
                except (OSError, subprocess.SubprocessError):
                    if not pending:
                        raise
                    child = None
                    finish(state, False)
                    active = None
                    continue
                deadline, stable = time.monotonic() + VALIDATION_SECONDS, None
            now = time.monotonic()
            if pending:
                update.atomic_json(RUNTIME / 'rollout.json', {
                    'heartbeat': now, 'deadline': deadline,
                    'pid': os.getpid(), 'started': identity(os.getpid()),
                })
                if child.poll() is not None or now >= deadline:
                    stop(child)
                    finish(state, False)
                    print('Application update failed health validation; restoring the previous release', file=sys.stderr, flush=True)
                    active = None
                    continue
                if healthy(RUNTIME):
                    processes = json.loads((RUNTIME / 'health.json').read_text())['processes']
                    if processes[0]['pid'] == child.pid:
                        stable = stable if stable is not None else now
                        if now - stable >= 5:
                            finish(state, True)
                            print('Application update validated', file=sys.stderr, flush=True)
                    else:
                        stable = None
                else:
                    stable = None
            elif child.poll() is not None:
                return child.returncode or 1
            time.sleep(0.25)
        return 0
    finally:
        if child:
            stop(child)
        (RUNTIME / 'rollout.json').unlink(missing_ok=True)
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    os.umask(0o077)
    try:
        raise SystemExit(run(sys.argv[1:]))
    except (update.UpdateError, OSError, ValueError, KeyError, subprocess.SubprocessError):
        print('Managed application launcher failed safely; inspect update --status', file=sys.stderr)
        raise SystemExit(1)
