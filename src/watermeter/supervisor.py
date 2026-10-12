"""Own every pipeline member; bounded I/O and whole-session cleanup."""
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import subprocess
import sys
import time
from .health import identity
from .private import private_config
from .reading import accept, encode, InvalidReading
from .settings import ConfigError


def log(message):
    print(message, file=sys.stderr, flush=True)


class Supervisor:
    def __init__(self, settings, env, config, root, publisher=None, commands=None):
        self.settings, self.config, self.root = settings, config, Path(root)
        # rtl_wmbus formats local time without an offset; wmbusmeters parses
        # that timestamp as UTC. UTC0 works without a tzdata installation and
        # overrides both inherited TZ and HA's mounted local timezone.
        self.env = dict(env, TZ="UTC0")
        self.publisher = publisher
        demodulator = ["rtl_wmbus", "-f", "-p", "S"]
        if settings.fast_math:
            demodulator.append("-a")
        if settings.algorithm == "runlength":
            demodulator.extend(["-t", "0"])
        elif settings.algorithm == "time2":
            demodulator.extend(["-r", "0"])
        self.commands = commands or [
            ["rtl_sdr", "-f", settings.frequency, "-s", "1600000", "-"],
            demodulator,
            ["wmbusmeters", f"--useconfig={config}"],
        ]
        self.children = []
        self.stop_signal = None
        self.last_received = None
        self.diagnostics = set()
        self.diagnostic_tails = {}

    def stop(self, signum, _frame):
        self.stop_signal = signum

    def status(self):
        processes = [{"pid": p, "started": identity(p)} for p in [os.getpid()] + [c.pid for c in self.children]]
        state = {"heartbeat": time.monotonic(), "processes": processes,
                 "last_received_at": self.last_received,
                 "mqtt_connected": bool(self.publisher and self.publisher.connected)}
        temp = self.root / "health.tmp"
        with temp.open("w") as stream:
            json.dump(state, stream)
        os.chmod(temp, 0o600)
        temp.replace(self.root / "health.json")

    def diagnostic(self, index, data):
        # Do not relay upstream text: even config parser errors may contain secrets.
        # Pipe reads need not align with messages. Keep only a bounded overlap.
        lower = self.diagnostic_tails.get(index, b"") + data.lower()
        self.diagnostic_tails[index] = lower[-256:]
        categories = []
        for token, safe in ((b"no supported devices", "no supported SDR found"),
                            (b"permission", "USB permission problem"),
                            (b"kernel driver is active", "device claimed by kernel driver"),
                            (b"failed to detach", "could not detach USB kernel driver"),
                            (b"detaching kernel driver failed", "could not detach USB kernel driver"),
                            (b"failed to open rtlsdr", "could not open RTL-SDR"),
                            (b"usb_claim_interface", "could not claim USB interface"),
                            (b"no matching devices", "no matching SDR found"),
                            (b"short write", "SDR output pipe closed or short write"),
                            (b"failed to submit transfer", "could not submit USB transfer"),
                            (b"decrypt", "decryption diagnostic; verify runtime key")):
            if token in lower:
                categories.append(safe)
        # Decode only the known libusb status codes, never arbitrary upstream text.
        usb_errors = {-1: "USB I/O error", -2: "invalid USB parameter",
                      -3: "USB access denied (permissions or security policy)",
                      -4: "USB device disconnected", -5: "USB device or interface not found",
                      -6: "USB device busy (another reader or kernel driver)",
                      -7: "USB transfer timed out", -8: "USB transfer overflow",
                      -9: "USB pipe error", -10: "USB operation interrupted",
                      -11: "USB memory allocation failed", -12: "USB operation unsupported",
                      -99: "USB operation failed"}
        for match in re.finditer(rb"(?:libusb\w*|usb_open|usb_claim_interface) (?:error|failed(?: with)?) (-[0-9]{1,2})(?![0-9])", lower):
            code = int(match[1])
            if code in usb_errors:
                categories.append(f"{usb_errors[code]} (libusb {code})")
        for category in categories or ["diagnostic (upstream text suppressed)"]:
            if (index, category) not in self.diagnostics:
                self.diagnostics.add((index, category))
                log(f"Pipeline component {index + 1}: {category}")

    def failure(self, message):
        # An early exit can race the selector. Read pending errors before cleanup
        # closes the pipes; otherwise the useful USB failure can be lost entirely.
        for index, child in enumerate(self.children):
            try:
                data = os.read(child.stderr.fileno(), 65536)
            except BlockingIOError:
                data = b""
            if data:
                self.diagnostic(index, data)
            code = child.poll()
            if code is not None:
                log(f"Pipeline component {index + 1} exited with code {code}")
        log(message)
        return 1

    def cleanup(self):
        sig = self.stop_signal or signal.SIGTERM
        for child in self.children:
            try:
                os.killpg(child.pid, sig)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 3
        while any(c.poll() is None for c in self.children) and time.monotonic() < deadline:
            time.sleep(0.02)
        # Kill sessions even when the immediate child exited but a descendant survived.
        for child in self.children:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()
            for stream in (child.stdin, child.stdout, child.stderr):
                if stream:
                    stream.close()
        for name in ("health.json", "health.tmp"):
            (self.root / name).unlink(missing_ok=True)

    def run(self):
        previous = {s: signal.signal(s, self.stop) for s in (signal.SIGTERM, signal.SIGINT)}
        selector = selectors.DefaultSelector()
        buffer = b""
        invalid_reported = False
        try:
            pipe = subprocess.DEVNULL
            for command in self.commands:
                if not shutil.which(command[0]):
                    raise ConfigError("Required pipeline executable is missing")
                child = subprocess.Popen(command, stdin=pipe, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, env=self.env,
                                         start_new_session=True, bufsize=0)
                self.children.append(child)
                if pipe != subprocess.DEVNULL:
                    pipe.close()
                pipe = child.stdout
                os.set_blocking(child.stderr.fileno(), False)
                selector.register(child.stderr, selectors.EVENT_READ, len(self.children) - 1)
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, "decoder")
            if self.publisher:
                self.publisher.set_alive(True)
                self.publisher.start()
            log("Receiver running: C1 at configured frequency; waiting for decrypted telegrams")
            log(f"Demodulator: algorithm={self.settings.algorithm}, fast_math={str(self.settings.fast_math).lower()}")
            while not self.stop_signal:
                if any(child.poll() is not None for child in self.children):
                    return self.failure("Receiver pipeline failed; check component diagnostics above")
                self.status()
                for event, _ in selector.select(0.2):
                    data = os.read(event.fileobj.fileno(), 65536)
                    if not data:
                        selector.unregister(event.fileobj)
                        if event.data == "decoder":
                            return self.failure("Unexpected decoder EOF; check component diagnostics above")
                        continue
                    if event.data != "decoder":
                        self.diagnostic(event.data, data)
                        continue
                    buffer += data
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        try:
                            if len(line) > 65536:
                                raise InvalidReading()
                            reading = accept(line, self.settings)
                        except InvalidReading:
                            if not invalid_reported:
                                log("Ignoring malformed, unrelated, or undecoded reader output")
                                invalid_reported = True
                            continue
                        payload = encode(reading)
                        print(payload, flush=True)
                        self.last_received = reading["received_at"]
                        (self.root / "last_received_at").write_text(self.last_received + "\n")
                        os.chmod(self.root / "last_received_at", 0o600)
                        if self.publisher:
                            self.publisher.submit(payload)
                    if len(buffer) > 65536:
                        log("Decoder output exceeded bounded line limit")
                        return 1
            log("Receiver stopping")
            return 0
        finally:
            # Offline means receiver is shutting down, even on a pipeline failure.
            if self.publisher:
                self.publisher.set_alive(False)
                self.publisher.close()
            self.cleanup()
            selector.close()
            for sig, handler in previous.items():
                signal.signal(sig, handler)


def run(settings, key, password, env, root=Path("/run/watermeter")):
    versions = Path("/usr/share/watermeter/versions.txt")
    if versions.exists():
        for line in versions.read_text().splitlines():
            log(line)
    root = Path(root)
    os.umask(0o077)
    with private_config(settings, key, root) as config:
        publisher = None
        if settings.mqtt:
            from .mqtt import Publisher
            publisher = Publisher(settings, password)
        return Supervisor(settings, env, config, root, publisher).run()
