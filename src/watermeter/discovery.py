"""Stable retained single-sensor Home Assistant discovery."""
from .reading import encode


def messages(settings):
    device_id = f"diehl_hydrus_{settings.meter_id}"
    device = {"identifiers": [device_id], "manufacturer": "Diehl Metering",
              "model": "HYDRUS 2.0 / DME173", "name": settings.name}
    sensors = (
        ("total_m3", "Total water", {"unit_of_measurement": "m³", "device_class": "water", "state_class": "total_increasing"}),
        ("flow_temperature_c", "Flow temperature", {"unit_of_measurement": "°C", "device_class": "temperature", "state_class": "measurement"}),
        ("status", "Status", {"entity_category": "diagnostic"}),
    )
    for field, name, extra in sensors:
        unique_id = f"{device_id}_{field}"
        payload = {"name": name, "unique_id": unique_id, "state_topic": settings.state_topic,
                   "value_template": "{{ value_json.get('" + field + "') }}",
                   "availability_topic": settings.availability_topic,
                   "payload_available": "online", "payload_not_available": "offline",
                   "qos": 1, "device": device, **extra}
        if field == "status":
            payload["value_template"] = "{{ value_json.get('status') if value_json.get('status') is not none else 'unknown' }}"
        yield f"{settings.discovery_prefix}/sensor/{unique_id}/config", encode(payload)
