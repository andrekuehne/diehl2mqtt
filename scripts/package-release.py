#!/usr/bin/env python3
"""Package committed public inputs only; never copy host settings or secrets."""
import argparse
import hashlib
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def committed(name):
    return git("show", "HEAD:" + name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--packages-file", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", args.version):
        parser.error("Expected version vMAJOR.MINOR.PATCH")
    if not re.fullmatch(r"ghcr\.io/[a-z0-9._/-]+@sha256:[0-9a-f]{64}", args.image):
        parser.error("Expected immutable GHCR image reference")
    args.output.mkdir(parents=True, exist_ok=True)
    stamp = int(git("show", "-s", "--format=%ct", "HEAD"))
    revision = git("rev-parse", "HEAD").decode().strip()
    dockerfile = committed("Dockerfile").decode()
    refs = {}
    for name in ("RTL_WMBUS_REF", "WMBUSMETERS_REF"):
        matches = set(re.findall(r"^ARG " + name + r"=([0-9a-f]{40})$", dockerfile, re.M))
        if len(matches) != 1:
            raise ValueError("Expected one immutable native source pin")
        refs[name] = matches.pop()

    def archive(directory, path):
        def normalize(info):
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = stamp
            return info
        with tarfile.open(path, "w:gz") as stream:
            stream.add(directory, arcname=directory.name, filter=normalize)

    with tempfile.TemporaryDirectory(prefix="diehl2mqtt-release-") as temp:
        temp = Path(temp)
        deploy = temp / ("diehl2mqtt-" + args.version)
        deploy.mkdir()
        for name in ("compose.yaml", "compose.mqtt.yaml", "compose.mqtt.auth.yaml",
                     ".env.example", "scripts/setup-secret.sh", "scripts/setup-mqtt-secret.sh"):
            path = deploy / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(committed(name))
            if name.endswith(".sh"):
                path.chmod(0o755)
        compose = (deploy / "compose.yaml").read_text()
        block = "    build:\n      context: .\n      target: final\n"
        if compose.count(block) != 1:
            raise ValueError("Unexpected Compose build structure")
        compose = compose.replace(block, "")
        compose = compose.replace("${WATERMETER_IMAGE:-watermeter:local}", "${WATERMETER_IMAGE:?Set the published image digest}")
        (deploy / "compose.yaml").write_text(compose)
        env = (deploy / ".env.example").read_text()
        if env.count("WATERMETER_IMAGE=watermeter:local") != 1:
            raise ValueError("Unexpected example image setting")
        (deploy / ".env.example").write_text(env.replace("WATERMETER_IMAGE=watermeter:local", "WATERMETER_IMAGE=" + args.image))
        (deploy / "README.md").write_bytes(committed("deploy/README.md"))
        (deploy / "release.txt").write_text(f"version={args.version}\nrevision={revision}\nplatform=linux/amd64\nimage={args.image}\n")
        archive(deploy, args.output / (deploy.name + "-deploy.tar.gz"))

        source = temp / ("diehl2mqtt-" + args.version + "-sources")
        source.mkdir()
        (source / "diehl2mqtt.tar").write_bytes(git("archive", "--format=tar", "--prefix=diehl2mqtt/", "HEAD"))
        for name, url, ref in (
            ("rtl-wmbus", "https://github.com/xaelsouth/rtl-wmbus.git", refs["RTL_WMBUS_REF"]),
            ("wmbusmeters", "https://github.com/wmbusmeters/wmbusmeters.git", refs["WMBUSMETERS_REF"]),
        ):
            checkout = temp / (name + "-checkout")
            subprocess.run(["git", "init", "-q", str(checkout)], check=True)
            subprocess.run(["git", "-C", str(checkout), "fetch", "-q", "--depth=1", url, ref], check=True)
            actual = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "FETCH_HEAD"]).decode().strip()
            if actual != ref:
                raise ValueError("Native source pin mismatch")
            with (source / (name + "-" + ref + ".tar")).open("wb") as out:
                subprocess.run(["git", "-C", str(checkout), "archive", "--format=tar", "--prefix=" + name + "/", ref], check=True, stdout=out)
        (source / "THIRD_PARTY_NOTICES.md").write_bytes(committed("THIRD_PARTY_NOTICES.md"))
        (source / "packages.txt").write_bytes(Path(args.packages_file).read_bytes())
        (source / "README.txt").write_text(
            "Unmodified pinned native sources and project build materials for " + args.version + ".\n"
            "Extract the tar files to inspect source, licenses, Dockerfile and build instructions.\n"
            "The project archive contains the exact committed wrapper and dependency pins.\n"
            "Paho's hashed wheel is specified in requirements.txt; its source and notices are at\n"
            "https://pypi.org/project/paho-mqtt/2.1.0/ and https://github.com/eclipse-paho/paho.mqtt.python.\n"
            "Debian runtime package versions are recorded in packages.txt; package copyrights\n"
            "remain in the image under /usr/share/doc. Debian source packages are available at\n"
            "https://sources.debian.org/ and historical versions at https://snapshot.debian.org/.\n"
            "These archives contain no runtime credentials.\n"
        )
        archive(source, args.output / (source.name + ".tar.gz"))
    (args.output / "image.txt").write_text(args.image + "\n")
    names = ["diehl2mqtt-" + args.version + "-deploy.tar.gz", "diehl2mqtt-" + args.version + "-sources.tar.gz", "image.txt"]
    with (args.output / "SHA256SUMS").open("w") as checksums:
        for name in names:
            digest = hashlib.sha256((args.output / name).read_bytes()).hexdigest()
            checksums.write(f"{digest}  {name}\n")
    print("Packaged committed deployment and pinned native sources for " + args.version)


if __name__ == "__main__":
    main()
