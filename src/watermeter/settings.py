"""Strict data-only configuration. Errors never include user-supplied values."""
from dataclasses import dataclass
import ipaddress
import os
from pathlib import Path
import re

LOG_LEVELS = ("debug", "info", "warning", "error", "critical")


class ConfigError(ValueError):
    pass


def text(env, name, default="", limit=256):
    value = env.get(name, default)
    if len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ConfigError(f"Invalid {name}")
    return value


def boolean(env, name, default=False):
    value = text(env, name, str(default)).lower()
    if value in ("true", "yes", "on", "1"):
        return True
    if value in ("false", "no", "off", "0"):
        return False
    raise ConfigError(f"Invalid boolean {name}")


def topic(env, name, default, root=True):
    value = text(env, name, default, 256)
    if root:
        value = value.rstrip("/")
    if not value or "+" in value or "#" in value or not value.strip("/"):
        raise ConfigError(f"Invalid topic {name}")
    return value


def secret(env, name, required=False, aes=False):
    path = env.get(name + "_FILE", "")
    if path:
        try:
            with Path(path).open("rb") as stream:
                raw = stream.read(4097)
            if len(raw) > 4096:
                raise ValueError()
            value = raw.decode("ascii" if aes else "utf-8")
        except (OSError, ValueError):
            raise ConfigError(f"Cannot read valid {name}_FILE") from None
        if value.endswith("\r\n"):
            value = value[:-2]
        elif value.endswith("\n"):
            value = value[:-1]
    else:
        value = env.get(name, "")
    if aes and not re.fullmatch(r"[0-9a-fA-F]{32}", value):
        raise ConfigError("METER_AES_KEY must contain exactly 32 hexadecimal characters")
    if (required or path) and not value:
        raise ConfigError(f"Missing {name}")
    if len(value) > 4096 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ConfigError(f"Invalid {name}")
    return value


def scrub_environment():
    for name in ("METER_AES_KEY", "METER_AES_KEY_FILE", "MQTT_PASSWORD", "MQTT_PASSWORD_FILE"):
        os.environ.pop(name, None)
    return dict(os.environ)


@dataclass(frozen=True)
class Settings:
    meter_id: str = "12345678"
    driver: str = "dme173"
    name: str = "Water"
    frequency: str = "868.95M"
    mode: str = "c1"
    mqtt: bool = False
    host: str = ""
    port: int = 1883
    username: str = ""
    tls: bool = False
    ca: str = ""
    cert: str = ""
    client_key: str = ""
    prefix: str = "watermeter"
    client_id: str = "watermeter_12345678"
    discovery: bool = False
    discovery_prefix: str = "homeassistant"
    status_topic: str = "homeassistant/status"
    fast_math: bool = False
    algorithm: str = "both"
    log_level: str = "info"
    decoder: str = "reference"

    @classmethod
    def load(cls, env=None, offline=False):
        env = os.environ if env is None else env
        log_level = text(env, "LOG_LEVEL", "info")
        if log_level not in LOG_LEVELS:
            raise ConfigError("LOG_LEVEL must be debug, info, warning, error or critical")
        meter_id = "12345678" if offline else text(env, "METER_ID", "12345678")
        driver = "dme173" if offline else text(env, "METER_DRIVER", "dme173")
        name = text(env, "METER_NAME", "Water")
        frequency = text(env, "WMBUS_FREQUENCY", "868.95M")
        mode = text(env, "WMBUS_MODE", "c1")
        fast_math = boolean(env, "WMBUS_FAST_MATH")
        algorithm = text(env, "WMBUS_ALGORITHM", "both")
        if algorithm not in ("both", "runlength", "time2"):
            raise ConfigError("WMBUS_ALGORITHM must be both, runlength or time2")
        decoder = text(env, "WMBUS_DECODER", "reference")
        if decoder not in ("reference", "dev"):
            raise ConfigError("WMBUS_DECODER must be reference or dev")
        receiver = dict(fast_math=fast_math, algorithm=algorithm, log_level=log_level, decoder=decoder)
        if not re.fullmatch(r"[0-9]{8}", meter_id):
            raise ConfigError("METER_ID must be an eight-character decimal string")
        if driver != "dme173" or mode != "c1":
            raise ConfigError("Only METER_DRIVER=dme173 and WMBUS_MODE=c1 are supported")
        if not name or name != name.strip() or "=" in name or "#" in name:
            raise ConfigError("Invalid METER_NAME")
        match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([kM]?)", frequency)
        if not match or not 863e6 <= float(match[1]) * {"": 1, "k": 1000, "M": 1e6}[match[2]] <= 870e6:
            raise ConfigError("WMBUS_FREQUENCY must be between 863 and 870 MHz")
        enabled = False if offline else boolean(env, "MQTT_ENABLED")
        if not enabled:
            return cls(meter_id, driver, name, frequency, mode, client_id=f"watermeter_{meter_id}", **receiver)
        host = text(env, "MQTT_HOST")
        if not host or any(c.isspace() for c in host) or "/" in host or "@" in host:
            raise ConfigError("MQTT_HOST is required and must be a hostname or IP address")
        if ":" in host:
            try:
                ipaddress.IPv6Address(host)
            except ValueError:
                raise ConfigError("Invalid MQTT_HOST") from None
        tls = boolean(env, "MQTT_TLS")
        port = text(env, "MQTT_PORT", "8883" if tls else "1883")
        if not re.fullmatch(r"[0-9]{1,5}", port) or not 1 <= int(port) <= 65535:
            raise ConfigError("Invalid MQTT_PORT")
        cert = text(env, "MQTT_CLIENT_CERT_FILE", limit=4096)
        client_key = text(env, "MQTT_CLIENT_KEY_FILE", limit=4096)
        ca = text(env, "MQTT_CA_FILE", limit=4096)
        if bool(cert) != bool(client_key):
            raise ConfigError("MQTT client certificate and key must be configured together")
        if (cert or ca) and not tls:
            raise ConfigError("MQTT certificate settings require MQTT_TLS=true")
        client_id = text(env, "MQTT_CLIENT_ID", f"watermeter_{meter_id}", 128)
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", client_id):
            raise ConfigError("Invalid MQTT_CLIENT_ID")
        return cls(meter_id, driver, name, frequency, mode, True, host, int(port),
                   text(env, "MQTT_USERNAME"), tls, ca, cert, client_key,
                   topic(env, "MQTT_TOPIC_PREFIX", "watermeter"), client_id,
                   boolean(env, "HA_DISCOVERY_ENABLED", True),
                   topic(env, "HA_DISCOVERY_PREFIX", "homeassistant"),
                   topic(env, "HA_STATUS_TOPIC", "homeassistant/status", root=False), **receiver)

    @property
    def state_topic(self):
        return f"{self.prefix}/{self.meter_id}/state"

    @property
    def availability_topic(self):
        return f"{self.prefix}/{self.meter_id}/availability"
