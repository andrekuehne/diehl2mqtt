"""Bounded real upstream decode with no USB or broker."""
from pathlib import Path
import re
import subprocess
from .private import private_config
from .reading import accept, InvalidReading
from .settings import ConfigError


def decode(settings, key, env, fixture, root=Path("/run/watermeter")):
    if settings.driver != "dme173":
        raise ConfigError("Offline fixture requires METER_DRIVER=dme173")
    try:
        packet = Path(fixture).read_text(encoding="ascii").removesuffix("\n")
        if not re.fullmatch(r"(?:[0-9a-fA-F]{2}){10,256}", packet):
            raise ValueError()
    except (OSError, ValueError):
        raise ConfigError("Invalid offline fixture") from None
    with private_config(settings, key, root, offline=True) as directory:
        try:
            result = subprocess.run(["wmbusmeters", f"--useconfig={directory}"],
                                    input=packet + "\n", text=True, capture_output=True,
                                    timeout=10, env=env)
        except subprocess.TimeoutExpired:
            raise ConfigError("Offline decoder timed out") from None
        if result.returncode:
            raise ConfigError("Offline decoder failed; check fixture, driver and runtime key")
        readings = []
        for line in result.stdout.splitlines():
            try:
                readings.append(accept(line, settings))
            except InvalidReading:
                continue
        if not readings:
            raise ConfigError("Offline decode produced no decrypted measurement; check runtime key and fixture")
        return readings
