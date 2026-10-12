#!/usr/bin/env python3
"""Create a direct OCI/LXC reader on Proxmox VE 9.1+, and monitor its USB device.

Standard-library only. Run on the PVE host, never inside a guest. Production
secrets are prompted locally and written only into the new guest's rootfs.
"""
import argparse
import fcntl
import getpass
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid

DEFAULT_RELEASE = "v0.3.0"
REPOSITORY = "https://github.com/andrekuehne/diehl2mqtt"
PVE_CONFIG = Path("/etc/pve/lxc")
CONFIG_DIR = Path("/etc/diehl2mqtt-lxc")
RUNTIME_DIR = Path("/run/diehl2mqtt-lxc")
USB_SYSFS = Path("/sys/bus/usb/devices")
HELPER = Path("/usr/local/libexec/diehl2mqtt-proxmox.py")
UNIT_DIR = Path("/etc/systemd/system")


class InstallError(Exception):
    pass


def run(*args, timeout=120, check=True):
    # pct creates root-owned ancestors before entering the mapped extraction
    # namespace. Its children must be able to traverse those directories.
    # Keep the installer's private umask, and override it only in pct's child.
    child_umask = 0o022 if Path(str(args[0])).name == "pct" else -1
    result = subprocess.run([str(a) for a in args], capture_output=True,
                            text=True, timeout=timeout, umask=child_umask)
    if check and result.returncode:
        # No secrets ever enter child arguments or input. Never dump CT config.
        raise InstallError(f"{args[0]} {args[1]} failed: {result.stderr.strip()[-1500:]}")
    return result


def command_json(*args):
    return json.loads(run(*args).stdout)


def text(path):
    return Path(path).read_text().strip()


def valid(value, pattern, label):
    if not re.fullmatch(pattern, value, re.ASCII):
        raise InstallError(f"Invalid {label}")
    return value


def ctid_value(value):
    value = int(value)
    if not 100 <= value <= 999999999:
        raise ValueError("CT ID must be between 100 and 999999999")
    return value


def prompt(label, default="", pattern=None):
    value = input(f"{label}" + (f" [{default}]" if default else "") + ": ").strip() or default
    if pattern:
        valid(value, pattern, label)
    return value


def device(port):
    valid(port, r"\d+-\d+(?:\.\d+)*", "USB port")
    directory = USB_SYSFS / port
    try:
        vendor = text(directory / "idVendor")
        product = text(directory / "idProduct")
        serial = text(directory / "serial") if (directory / "serial").exists() else ""
        bus, address = int(text(directory / "busnum")), int(text(directory / "devnum"))
        if not 1 <= bus <= 999 or not 1 <= address <= 999:
            return None
        return {"port": port, "vendor": vendor, "product": product, "serial": serial,
                "path": f"/dev/bus/usb/{bus:03d}/{address:03d}"}
    except (OSError, ValueError):
        return None


def same_device(expected, current):
    return bool(current and all(expected[k] == current[k]
                                for k in ("port", "vendor", "product", "serial")))


def select_device():
    found = []
    for directory in sorted(USB_SYSFS.iterdir()):
        if re.fullmatch(r"\d+-\d+(?:\.\d+)*", directory.name):
            item = device(directory.name)
            if item and item["vendor"] == "0bda" and item["product"] in ("2832", "2838"):
                found.append(item)
    if not found:
        raise InstallError("No Realtek 0bda:2832/2838 SDR found on this host. Connect it first.")
    if len(found) != 1:
        raise InstallError("This installer currently requires exactly one RTL-SDR on the host")
    for item in found:
        print(f"SDR: USB port {item['port']} ({item['vendor']}:{item['product']})")
    port = prompt("SDR USB port", found[0]["port"] if len(found) == 1 else "",
                  r"\d+-\d+(?:\.\d+)*")
    for item in found:
        if item["port"] == port:
            return item
    raise InstallError("Choose one of the listed SDR ports")


def preflight():
    if os.geteuid() != 0:
        raise InstallError("Run as root in the Proxmox host shell")
    if platform.machine() != "x86_64":
        raise InstallError("The published image currently supports amd64 only")
    for binary in ("pveversion", "pct", "pvesh", "systemctl"):
        if not shutil.which(binary):
            raise InstallError("This script must run on the Proxmox VE host")
    version = run("pveversion").stdout
    match = re.search(r"pve-manager/(\d+)\.(\d+)", version)
    if not match or tuple(map(int, match.groups())) < (9, 1):
        raise InstallError("Direct OCI application containers require Proxmox VE 9.1+")
    if "entrypoint" not in run("pct", "help", "create").stdout:
        raise InstallError("Update pve-container: OCI application entrypoint support is missing")
    print(version.strip())


def check_unused(ctid):
    # Cluster-wide, including VM IDs and guests on other nodes.
    guests = command_json("pvesh", "get", "/cluster/resources", "--type", "vm",
                          "--output-format", "json")
    if any(int(item["vmid"]) == ctid for item in guests):
        raise InstallError("That ID already belongs to a VM or CT; nothing was changed")
    if (PVE_CONFIG / f"{ctid}.conf").exists() or (CONFIG_DIR / f"{ctid}.json").exists():
        raise InstallError("Existing CT/configuration found; nothing was changed")


def check_exclusive(usb):
    for path in CONFIG_DIR.glob("*.json"):
        saved = json.loads(path.read_text())
        if same_device(saved["usb"], usb):
            unit = f"diehl2mqtt-lxc@{ctid_value(saved['ctid'])}.timer"
            enabled = run("systemctl", "is-enabled", "--quiet", unit, check=False).returncode == 0
            active = run("systemctl", "is-active", "--quiet", unit, check=False).returncode == 0
            if enabled or active:
                raise InstallError("Another managed reader uses this SDR; disable its timer before installing a replacement")


def release_image(version):
    valid(version, r"v\d+\.\d+\.\d+", "release version")
    base = f"{REPOSITORY}/releases/download/{version}/"
    def download(name):
        with urllib.request.urlopen(base + name, timeout=30) as response:
            data = response.read(65537)
        if len(data) > 65536:
            raise InstallError("Unexpected release metadata size")
        return data
    image_data = download("image.txt")
    sums = download("SHA256SUMS").decode().splitlines()
    expected = [line.split()[0] for line in sums if line.split()[1:] == ["image.txt"]]
    if expected != [hashlib.sha256(image_data).hexdigest()]:
        raise InstallError("Release image.txt checksum mismatch")
    return valid(image_data.decode().strip(),
                 r"ghcr\.io/andrekuehne/diehl2mqtt@sha256:[0-9a-f]{64}", "release image")


def collect_settings(args):
    if not sys.stdin.isatty():
        raise InstallError("Use an interactive terminal; do not pipe the script into Python")
    next_id = str(command_json("pvesh", "get", "/cluster/nextid", "--output-format", "json"))
    ctid = ctid_value(args.ctid or prompt("New CT ID", next_id, r"\d+"))
    check_unused(ctid)
    hostname = prompt("CT hostname", "diehl2mqtt", r"[a-zA-Z0-9][a-zA-Z0-9.-]{0,62}")
    node = socket.gethostname().split(".")[0]
    valid(node, r"[a-zA-Z0-9][a-zA-Z0-9_-]*", "node name")
    stores = command_json("pvesh", "get", f"/nodes/{node}/storage", "--content", "rootdir",
                          "--enabled", "1", "--output-format", "json")
    available = [s["storage"] for s in stores if s.get("active")]
    if not available:
        raise InstallError("No active storage supports container root disks")
    print("Root disk storage: " + ", ".join(available))
    storage = prompt("Root disk storage", "local-lvm" if "local-lvm" in available else available[0],
                     r"[a-zA-Z0-9][a-zA-Z0-9_-]*")
    if storage not in available:
        raise InstallError("Select active container-root storage from the list")
    bridge = prompt("Network bridge", "vmbr0", r"[a-zA-Z0-9_.-]{1,15}")
    if not (Path("/sys/class/net") / bridge / "bridge").exists():
        raise InstallError("The selected bridge does not exist on this node")
    vlan = prompt("VLAN tag (empty for untagged)")
    if vlan and (not vlan.isdecimal() or not 1 <= int(vlan) <= 4094):
        raise InstallError("VLAN must be 1-4094")
    address = prompt("IPv4: dhcp or address/prefix", "dhcp")
    gateway = ""
    if address != "dhcp":
        if ipaddress.ip_interface(address).version != 4 or "/" not in address:
            raise InstallError("Use an IPv4 address with prefix")
        gateway = prompt("IPv4 gateway (empty for none)")
        if gateway:
            gateway = str(ipaddress.IPv4Address(gateway))
    usb = select_device()
    check_exclusive(usb)
    env = {"METER_ID": prompt("Eight-digit Wireless M-Bus meter ID", pattern=r"[0-9]{8}"),
           "METER_AES_KEY_FILE": "/etc/diehl2mqtt/secrets/meter_aes_key"}
    mode = prompt("MQTT mode: auth, anonymous, or off", "auth", r"auth|anonymous|off")
    env["MQTT_ENABLED"] = "false" if mode == "off" else "true"
    if mode != "off":
        env["MQTT_HOST"] = prompt("MQTT hostname/IP (no scheme/port)", pattern=r"[a-zA-Z0-9_.:-]+")
        if ":" in env["MQTT_HOST"]:
            ipaddress.IPv6Address(env["MQTT_HOST"])
        env["MQTT_TLS"] = prompt("MQTT TLS: true or false", "false", r"true|false")
        port = int(prompt("MQTT port", "8883" if env["MQTT_TLS"] == "true" else "1883", r"[0-9]+"))
        if not 1 <= port <= 65535:
            raise InstallError("MQTT port must be 1-65535")
        env["MQTT_PORT"] = str(port)
    if mode == "auth":
        env["MQTT_USERNAME"] = prompt("MQTT username", pattern=r"[^\x00-\x20\x7f]+")
        env["MQTT_PASSWORD_FILE"] = "/etc/diehl2mqtt/secrets/mqtt_password"
    return {"ctid": ctid, "hostname": hostname, "storage": storage, "bridge": bridge,
            "vlan": vlan, "address": address, "gateway": gateway, "usb": usb, "env": env,
            "release": args.release, "image": release_image(args.release),
            "marker": "d2m-" + uuid.uuid4().hex[:12]}


def create_command(settings, archive):
    network = (f"name=eth0,type=veth,bridge={settings['bridge']},host-managed=1,"
               f"ip={settings['address']},ip6=manual,firewall=1")
    if settings["gateway"]:
        network += f",gw={settings['gateway']}"
    if settings["vlan"]:
        network += f",tag={settings['vlan']}"
    return ["pct", "create", str(settings["ctid"]), str(archive), "--hostname", settings["hostname"],
            "--rootfs", settings["storage"] + ":2", "--cores", "1", "--memory", "512",
            "--swap", "0", "--unprivileged", "1", "--net0", network, "--onboot", "0",
            "--tags", "diehl2mqtt;" + settings["marker"], "--start", "0"]


def configure_text(original, env):
    output = []
    for line in original.splitlines():
        match = re.match(r"lxc\.environment(?:\.runtime)?:\s*(\w+)=", line)
        if match and match[1] in env:
            continue
        output.append(line)
    for name, value in env.items():
        valid(name, r"[A-Z_][A-Z_0-9]*", "environment name")
        valid(value, r"[^\x00-\x1f\x7f]+", "environment value")
        output.append(f"lxc.environment.runtime: {name}={value}")
    output.append("lxc.mount.entry: tmpfs run/watermeter tmpfs nosuid,nodev,mode=0700,create=dir 0 0")
    return "\n".join(output) + "\n"


def mapped_root(config):
    result = {"u": 100000, "g": 100000}
    if not re.search(r"^unprivileged:\s*1\s*$", config, re.M):
        raise InstallError("Refusing secrets for a privileged guest")
    for kind in result:
        maps = re.findall(r"^lxc\.idmap:\s*" + kind + r"\s+(\d+)\s+(\d+)\s+(\d+)", config, re.M)
        if maps:
            roots = [int(host) for guest, host, size in maps if int(guest) == 0 and int(size) >= 1]
            if len(roots) != 1 or roots[0] == 0:
                raise InstallError("Unsupported root UID/GID mapping")
            result[kind] = roots[0]
    return result["u"], result["g"]


def write_secret(rootfs, name, value, owner):
    directory = rootfs / "etc/diehl2mqtt/secrets"
    for part in (rootfs / "etc", directory.parent, directory):
        if part.is_symlink():
            raise InstallError("Refusing a symlink in the guest secret path")
        part.mkdir(exist_ok=True)
    for part in (directory.parent, directory):
        part.chmod(0o700)
        os.chown(part, *owner)
    fd = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(value + "\n")
        os.fchown(stream.fileno(), *owner)


def managed_config(ctid):
    saved = json.loads((CONFIG_DIR / f"{ctid}.json").read_text())
    config = (PVE_CONFIG / f"{ctid}.conf").read_text()
    tags = re.search(r"^tags:\s*(.*)$", config, re.M)
    if saved["ctid"] != ctid or not tags or saved["marker"] not in tags[1].split(";"):
        raise InstallError("CT ownership marker mismatch; refusing to manage a reused CT ID")
    return saved, config


def detach_dvb(usb):
    for interface in USB_SYSFS.glob(usb["port"] + ":*"):
        driver = interface / "driver"
        if driver.is_symlink():
            if driver.resolve().name not in ("dvb_usb_rtl28xxu", "rtl2832_sdr"):
                raise InstallError("Selected USB interface has an unexpected host driver")
            (driver / "unbind").write_text(interface.name + "\n")


def stop_guest(ctid):
    run("pct", "shutdown", ctid, "--timeout", "20", "--forceStop", "1", timeout=45)


def health_command(ctid):
    # pct exec does not necessarily inherit the image's PATH/PYTHONPATH.
    return ["pct", "exec", str(ctid), "--keep-env", "0", "--", "/usr/bin/env",
            "PYTHONPATH=/opt/watermeter", "/opt/venv/bin/python", "-m", "watermeter.health"]


def reconcile(ctid, saved, config, state, now):
    current = device(saved["usb"]["port"])
    running = run("pct", "status", ctid).stdout.strip() == "status: running"
    if not same_device(saved["usb"], current):
        if running:
            stop_guest(ctid)
        return {"message": "Waiting for the selected SDR on its configured USB port"}
    expected = f"path={current['path']},uid=0,gid=0,mode=0600"
    dev = re.search(r"^dev0:\s*(.*)$", config, re.M)
    # Match the path only; pct may reorder device options when saving config.
    options = dev[1].split(",") if dev else []
    paths = [part.removeprefix("path=") for part in options
             if part.startswith("path=") or "=" not in part]
    changed = paths != [current["path"]]
    if changed and running:
        stop_guest(ctid)
        running = False
    if changed:
        run("pct", "set", ctid, "--dev0", expected)
    detach_dvb(current)
    if not running:
        run("pct", "start", ctid, timeout=60)
        return {"message": "Reader started", "started": now}
    started = state.get("started", now)
    if now - started >= 60:
        try:
            healthy = run(*health_command(ctid), timeout=10, check=False).returncode == 0
        except subprocess.TimeoutExpired:
            healthy = False
        if not healthy:
            stop_guest(ctid)
            run("pct", "start", ctid, timeout=60)
            return {"message": "Reader restarted after failed health check", "started": now}
    return {"message": "Reader running", "started": started}


def manage(ctid):
    RUNTIME_DIR.mkdir(mode=0o700, exist_ok=True)
    with (RUNTIME_DIR / f"{ctid}.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        saved, config = managed_config(ctid)
        mapped_root(config)
        state_path = RUNTIME_DIR / f"{ctid}.json"
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        updated = reconcile(ctid, saved, config, state, time.time())
        state_path.write_text(json.dumps(updated))
        if updated["message"] != state.get("message"):
            print(updated["message"])


def install_units():
    HELPER.parent.mkdir(parents=True, exist_ok=True)
    if Path(__file__).resolve() != HELPER:
        shutil.copyfile(__file__, HELPER)
    HELPER.chmod(0o755)
    (UNIT_DIR / "diehl2mqtt-lxc@.service").write_text(
        "[Unit]\nDescription=Check diehl2mqtt LXC %i and its SDR\nAfter=pve-cluster.service\n"
        "Requires=pve-cluster.service\n\n[Service]\nType=oneshot\nUMask=0077\n"
        f"ExecStart={HELPER} --manage %i\nTimeoutStartSec=120\n")
    (UNIT_DIR / "diehl2mqtt-lxc@.timer").write_text(
        "[Unit]\nDescription=Monitor diehl2mqtt LXC %i\n\n[Timer]\nOnBootSec=20s\n"
        "OnUnitInactiveSec=20s\nAccuracySec=3s\n\n[Install]\nWantedBy=timers.target\n")
    run("systemctl", "daemon-reload")


def show_plan(settings):
    print(f"\nCreate unprivileged CT {settings['ctid']}: {settings['hostname']}")
    print(f"1 core, 512 MiB RAM, 2 GiB disk on {settings['storage']}")
    print(f"Network: {settings['bridge']}, IPv4 {settings['address']}; USB port {settings['usb']['port']}")
    print(f"Release {settings['release']}, pinned image {settings['image']}")
    print("Install skopeo if needed. Detach only this SDR's DVB driver if active.")
    print("A host timer starts the CT at boot, checks health, and handles USB reconnects.")


def execute_install(settings):
    ctid = settings["ctid"]
    if input("Create this new CT? [y/N]: ").strip().lower() != "y":
        return
    aes = getpass.getpass("Meter AES key (32 hex characters): ")
    valid(aes, r"[0-9a-fA-F]{32}", "AES key: expected exactly 32 hexadecimal characters")
    password = ""
    if "MQTT_PASSWORD_FILE" in settings["env"]:
        password = getpass.getpass("MQTT password: ")
        valid(password, r"[^\x00-\x1f\x7f]+", "MQTT password")
    check_unused(ctid)
    check_exclusive(settings["usb"])
    if not same_device(settings["usb"], device(settings["usb"]["port"])):
        raise InstallError("The selected SDR changed; run setup again")
    if not shutil.which("skopeo"):
        run("apt-get", "update", timeout=300)
        run("apt-get", "install", "-y", "--no-install-recommends", "skopeo", timeout=600)
    created = False
    mounted = False
    try:
        with tempfile.TemporaryDirectory(prefix="diehl2mqtt-oci-") as temp:
            # Public archive must be readable by Proxmox's extraction user namespace.
            Path(temp).chmod(0o755)
            archive = Path(temp) / "image.tar"
            run("skopeo", "copy", "--override-os", "linux", "--override-arch", "amd64",
                "docker://" + settings["image"], "oci-archive:" + str(archive), timeout=1200)
            archive.chmod(0o644)
            run(*create_command(settings, archive), timeout=600)
            created = True
        path = PVE_CONFIG / f"{ctid}.conf"
        original = path.read_text()
        owner = mapped_root(original)
        path.write_text(configure_text(original, settings["env"]))
        run("pct", "mount", ctid)
        mounted = True
        rootfs = Path(f"/var/lib/lxc/{ctid}/rootfs")
        write_secret(rootfs, "meter_aes_key", aes, owner)
        if password:
            write_secret(rootfs, "mqtt_password", password, owner)
        aes = password = ""
        run("pct", "unmount", ctid)
        mounted = False
        CONFIG_DIR.mkdir(mode=0o700, exist_ok=True)
        CONFIG_DIR.chmod(0o700)
        saved = {k: settings[k] for k in ("ctid", "usb", "marker", "image", "release")}
        (CONFIG_DIR / f"{ctid}.json").write_text(json.dumps(saved, indent=2) + "\n")
        install_units()
        manage(ctid)
        run("systemctl", "enable", "--now", f"diehl2mqtt-lxc@{ctid}.timer")
        print(f"\nCT {ctid} installed. Health and real reception still need checking:")
        print("  " + " ".join(health_command(ctid)))
        print(f"  pct console {ctid}    # Ctrl-A, Q to detach")
        print(f"Stop monitoring before intentionally stopping/removing this CT:")
        print(f"  systemctl disable --now diehl2mqtt-lxc@{ctid}.timer")
        print(f"  pct shutdown {ctid}")
    except Exception:
        if created:
            print(f"Installation incomplete. CT {ctid} is retained for inspection; no guest was deleted.", file=sys.stderr)
        else:
            print(f"CT creation did not complete. Inspect CT {ctid} and its storage before retrying; "
                  "Proxmox may have cleaned it up or left partial files. This installer deletes nothing.",
                  file=sys.stderr)
        raise
    finally:
        aes = password = ""
        if mounted:
            run("pct", "unmount", ctid, check=False)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", default=DEFAULT_RELEASE)
    parser.add_argument("--ctid", type=ctid_value)
    parser.add_argument("--dry-run", action="store_true", help="Prompt/validate and show plan; make no changes")
    parser.add_argument("--check", action="store_true", help="Check PVE version and connected SDRs only")
    parser.add_argument("--manage", type=ctid_value, help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.manage is not None:
            if os.geteuid() != 0:
                raise InstallError("The host monitor requires root")
            manage(args.manage)
            return
        preflight()
        if args.check:
            for p in sorted(USB_SYSFS.iterdir()):
                if re.fullmatch(r"\d+-\d+(?:\.\d+)*", p.name):
                    item = device(p.name)
                    if item and item["vendor"] == "0bda":
                        print(f"USB port {item['port']}: {item['vendor']}:{item['product']}")
            return
        settings = collect_settings(args)
        show_plan(settings)
        if not args.dry_run:
            execute_install(settings)
    except (InstallError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"Setup stopped: {error}", file=sys.stderr)
        sys.exit(1)
    except (KeyboardInterrupt, EOFError):
        print("\nSetup interrupted", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
