"""Stable retained single-sensor Home Assistant discovery."""
from .reading import encode


# Historical volumes and meter-local dates deliberately have no statistical
# state class or timezone conversion. Only the live total represents usage.
SENSORS = (
    ("total_m3", "Total water", {"unit_of_measurement": "m³", "device_class": "water", "state_class": "total_increasing"}),
    ("flow_temperature_c", "Flow temperature", {"unit_of_measurement": "°C", "device_class": "temperature", "state_class": "measurement"}),
    ("status", "Status", {"entity_category": "diagnostic"}),
    ("target_m3", "Billing period water", {"unit_of_measurement": "m³", "device_class": "water"}),
    ("target_datetime", "Billing period date", {"icon": "mdi:calendar-clock"}),
    ("total_at_set_date_m3", "Water at set date", {"unit_of_measurement": "m³", "device_class": "water"}),
    ("set_date", "Set date", {"device_class": "date"}),
    ("total_backward_m3", "Backward water", {"unit_of_measurement": "m³", "device_class": "water"}),
    ("timestamp", "Decoder timestamp", {"device_class": "timestamp", "entity_category": "diagnostic"}),
    ("received_at", "Last received", {"device_class": "timestamp", "entity_category": "diagnostic"}),
    # rtl_wmbus supplies raw amplitude, despite wmbusmeters' rssi_dbm label.
    ("rssi_dbm", "Signal strength", {"icon": "mdi:signal", "state_class": "measurement", "entity_category": "diagnostic"}),
)


def messages(settings):
    device_id = f"diehl_hydrus_{settings.meter_id}"
    device = {"identifiers": [device_id], "manufacturer": "Diehl Metering",
              "model": "HYDRUS 2.0 / DME173",
              "name": f"Diehl Hydrus 2.0 ID {settings.meter_id}"}
    for field, name, extra in SENSORS:
        unique_id = f"{device_id}_{field}"
        payload = {"name": name, "unique_id": unique_id,
                   "default_entity_id": f"sensor.{unique_id}",
                   "state_topic": settings.state_topic,
                   "value_template": "{{ value_json.get('" + field + "') }}",
                   "availability_topic": settings.availability_topic,
                   "payload_available": "online", "payload_not_available": "offline",
                   "qos": 1, "device": device, **extra}
        if "unit_of_measurement" not in extra:
            payload["value_template"] = ("{{ value_json.get('" + field + "') if value_json.get('" +
                                         field + "') is not none else 'unknown' }}")
        if field == "status":
            # Metadata and any future decoder fields remain inspectable in HA
            # as well as in the complete retained state message.
            payload["json_attributes_topic"] = settings.state_topic
        yield f"{settings.discovery_prefix}/sensor/{unique_id}/config", encode(payload)
