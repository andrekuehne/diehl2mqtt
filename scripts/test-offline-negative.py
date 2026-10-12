"""Run inside the image with the public synthetic fixture/key only."""
from dataclasses import replace
from pathlib import Path
import os
import secrets
import tempfile
from watermeter.offline import decode
from watermeter.private import require_tmpfs
from watermeter.settings import Settings, secret, scrub_environment, ConfigError

require_tmpfs()
settings = Settings.load(offline=True)
key = "00112233445566778899aabbccddeeff"  # Public synthetic test data.
env = scrub_environment()
fixture = "/usr/share/watermeter/fixture.hex"
assert decode(settings, key, env, fixture)
with tempfile.TemporaryDirectory(dir="/run/watermeter") as tmp:
    corrupt = Path(tmp) / "corrupt.hex"
    packet = Path(fixture).read_text()
    # Destroy encrypted data while retaining a structurally plausible header.
    corrupt.write_text(packet[:40] + "ff" * ((len(packet.strip()) - 40) // 2) + "\n")
    for label, configured, runtime_key, input_file in (
        ("wrong key", settings, secrets.token_hex(16), fixture),
        ("wrong ID", replace(settings, meter_id="87654321"), key, fixture),
        ("wrong driver", replace(settings, driver="hydrus"), key, fixture),
        ("corrupt telegram", settings, key, str(corrupt)),
    ):
        try:
            decode(configured, runtime_key, env, input_file)
        except ConfigError:
            print("PASS:", label, "rejected")
        else:
            print("FAIL:", label, "was accepted")
            raise SystemExit(1)
