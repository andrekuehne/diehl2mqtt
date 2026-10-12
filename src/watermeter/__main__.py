import argparse
import os
from pathlib import Path
import sys
from .settings import Settings, ConfigError, secret, scrub_environment
from .reading import encode


def main():
    parser = argparse.ArgumentParser(description="Diehl HYDRUS reader")
    parser.add_argument("mode", choices=("live", "offline", "versions"), nargs="?", default="live")
    parser.add_argument("--fixture", default="/usr/share/watermeter/fixture.hex")
    args = parser.parse_args()
    if args.mode == "versions":
        print(Path("/usr/share/watermeter/versions.txt").read_text(), end="")
        return 0
    try:
        from .private import require_tmpfs
        require_tmpfs()
        settings = Settings.load(offline=args.mode == "offline")
        key = secret(os.environ, "METER_AES_KEY", required=True, aes=True)
        password = secret(os.environ, "MQTT_PASSWORD") if settings.mqtt else ""
        env = scrub_environment()
        if args.mode == "offline":
            from .offline import decode
            for reading in decode(settings, key, env, args.fixture):
                print(encode(reading), flush=True)
            return 0
        from .supervisor import run
        return run(settings, key, password, env)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr, flush=True)
        return 2
    except Exception:
        print("Reader failed safely; check runtime files and installed binaries", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
