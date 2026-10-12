"""Runtime config only; caller owns lifetime and child-environment scrubbing."""
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import tempfile
from .settings import ConfigError


@contextmanager
def private_config(settings, key, root=Path("/run/watermeter"), offline=False):
    root = Path(root)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink() or root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077:
        raise ConfigError("Runtime directory must be private and owned by the reader")
    directory = Path(tempfile.mkdtemp(prefix="decoder-", dir=root))
    try:
        os.chmod(directory, 0o700)
        meters = directory / "wmbusmeters.d"
        meters.mkdir(mode=0o700)
        data = {
            directory / "wmbusmeters.conf": (
                f"device=stdin:{'hex' if offline else 'rtlwmbus'}\n"
                "format=json\nloglevel=normal\nnonet=true\n"
                "logtelegrams=false\nignoreduplicates=false\n"
                f"listento={settings.mode}\n"),
            meters / "meter": (
                f"name={settings.name}\nid={settings.meter_id}\n"
                f"driver={settings.driver}:{settings.mode}\nkey={key}\n"),
        }
        for path, contents in data.items():
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as stream:
                stream.write(contents)
        yield directory
    finally:
        shutil.rmtree(directory)
