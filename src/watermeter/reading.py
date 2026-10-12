"""Decryption/identity boundary shared by stdout and MQTT."""
from datetime import datetime, timezone
import json
import math


class InvalidReading(ValueError):
    pass


def finite_tree(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise InvalidReading()
    if isinstance(value, dict):
        for item in value.values():
            finite_tree(item)
    elif isinstance(value, list):
        for item in value:
            finite_tree(item)


def accept(line, settings):
    try:
        reading = json.loads(line)
        if not isinstance(reading, dict) or reading.get("_") != "telegram":
            raise InvalidReading()
        if reading.get("id") != settings.meter_id:
            raise InvalidReading()
        if reading.get("driver", reading.get("meter")) != settings.driver:
            raise InvalidReading()
        if "meter" in reading and reading["meter"] != settings.driver:
            raise InvalidReading()
        finite_tree(reading)
        # An encrypted/header-only packet is never a real state.
        total = reading.get("total_m3")
        if type(total) not in (int, float) or total < 0:
            raise InvalidReading()
        for field in ("flow_temperature_c", "target_m3", "total_backward_m3", "total_at_set_date_m3"):
            if reading.get(field) is not None and type(reading[field]) not in (int, float):
                raise InvalidReading()
        if reading.get("status") is not None and not isinstance(reading["status"], str):
            raise InvalidReading()
        # No secret/config fields can cross the gateway boundary.
        if any("key" in k.lower() or "password" in k.lower() for k in reading):
            raise InvalidReading()
        reading["driver"] = settings.driver
        reading["received_at"] = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        return reading
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise InvalidReading("Rejected undecoded, malformed, or unrelated telegram") from None


def encode(reading):
    return json.dumps(reading, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
