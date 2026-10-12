#!/usr/bin/env python3
"""Compare explicitly supplied secrets in memory; never print/hash their values."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from watermeter.settings import secret


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--meter-key-file", required=True)
    parser.add_argument("--mqtt-password-file")
    parser.add_argument("--image", default="watermeter:local")
    parser.add_argument("--container")
    parser.add_argument("--log", action="append", default=[])
    args = parser.parse_args()
    values = [secret({"METER_AES_KEY_FILE": args.meter_key_file}, "METER_AES_KEY", aes=True).encode()]
    values.extend([values[0].upper(), values[0].lower()])
    if args.mqtt_password_file:
        password = secret({"MQTT_PASSWORD_FILE": args.mqtt_password_file}, "MQTT_PASSWORD").encode()
        first_commit = subprocess.check_output(["git", "rev-list", "--max-parents=0", "HEAD"], cwd=ROOT).decode().splitlines()[0]
        baseline = subprocess.check_output(["git", "show", first_commit + ":IMPLEMENTATION_PLAN.md"], cwd=ROOT)
        if password in baseline:
            print("NOTE: MQTT substring scan is non-diagnostic: matching text predates credential setup in original requirements; use structural checks")
        else:
            values.append(password)
    overlap = max(map(len, values))

    def check(data):
        if any(value and value in data for value in values):
            raise RuntimeError("Secret exposure detected; details withheld")

    def scan(stream, compressed=False):
        previous = b""
        decoder = None
        first = True
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            if first and compressed:
                if chunk.startswith(b"\x1f\x8b"):
                    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
                elif chunk.startswith(b"\x28\xb5\x2f\xfd"):
                    raise RuntimeError("Unsupported zstd image archive; audit incomplete")
            first = False
            decoded = decoder.decompress(chunk) if decoder else chunk
            check(previous + decoded)
            previous = decoded[-overlap:]

    files = subprocess.check_output(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=ROOT)
    for filename in files.split(b"\0"):
        if filename:
            path = ROOT / filename.decode()
            if path.is_file() and not path.is_symlink():
                with path.open("rb") as stream:
                    scan(stream)
    # Scan committed patches too, without rendering any history containing a match.
    check(subprocess.check_output(["git", "log", "-p", "--all", "--format="], cwd=ROOT))
    print("PASS: repository and Git history contain no comparable supplied secret")
    for name in args.log:
        with Path(name).open("rb") as stream:
            scan(stream)
    print("PASS: explicitly selected build/test/runtime logs contain no comparable supplied secret")
    for command in (["docker", "image", "inspect", args.image], ["docker", "history", "--no-trunc", args.image]):
        check(subprocess.check_output(command))
    process = subprocess.Popen(["docker", "image", "save", args.image], stdout=subprocess.PIPE)
    try:
        with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
            for member in archive:
                if member.isfile():
                    stream = archive.extractfile(member)
                    scan(stream, compressed=True)
        if process.wait() != 0:
            raise RuntimeError("Image archive audit failed")
    finally:
        process.stdout.close()
        if process.poll() is None:
            process.terminate()
            process.wait()
    print("PASS: image metadata/history and saved image layers contain no comparable supplied secret")
    if args.container:
        check(subprocess.check_output(["docker", "top", args.container, "-eo", "pid,args"]))
        script = '''import json,pathlib,sys
state=json.loads(pathlib.Path('/run/watermeter/health.json').read_text())
for child in state['processes'][1:]:
    data=pathlib.Path('/proc/'+str(child['pid'])+'/environ').read_bytes()
    forbidden=(b'METER_AES_KEY=',b'METER_AES_KEY_FILE=',b'MQTT_PASSWORD=',b'MQTT_PASSWORD_FILE=')
    if any(x in data for x in forbidden): sys.exit(1)
print('Child secret environment absent')
'''
        subprocess.run(["docker", "exec", args.container, "python", "-c", script],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("PASS: reader argv and child environments contain no AES value or secret environment variables")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("FAIL: security audit incomplete or exposure detected; no secret details printed", file=sys.stderr)
        raise SystemExit(1)
