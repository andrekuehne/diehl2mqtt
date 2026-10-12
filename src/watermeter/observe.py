"""Subscribe only to this meter; require a newly received live state."""
from datetime import datetime, timezone
import json
import math
import os
import secrets
import sys
import time
import paho.mqtt.client as mqtt
from .discovery import messages
from .mqtt import Publisher, VerifiedTLSClient
from .settings import ConfigError, Settings, secret, scrub_environment


def main():
    started = datetime.now(timezone.utc)
    try:
        settings = Settings.load()
        if not settings.mqtt:
            raise ConfigError("Set MQTT_ENABLED=true for broker observation")
        password = secret(os.environ, "MQTT_PASSWORD")
        scrub_environment()
        # Reuse exactly the production TLS policy, with a separate subscriber ID/no will.
        policy = Publisher(settings, password)
        client = VerifiedTLSClient(mqtt.CallbackAPIVersion.VERSION2,
                                  client_id="watermeter_observe_" + secrets.token_hex(6),
                                  protocol=mqtt.MQTTv311)
        client.connect_timeout = 3
        if settings.username:
            client.username_pw_set(settings.username, password or None)
        if policy._tls:
            client.tls_set_context(policy._tls)
        required = {topic for topic, _ in messages(settings)} if settings.discovery else set()
        configs = set()
        latest = None
        online = False
        failure = False

        def connected(c, _u, _f, reason, _p):
            nonlocal failure
            if reason.is_failure:
                failure = True
                return
            topics = [(settings.state_topic, 1), (settings.availability_topic, 1)] + [(t, 1) for t in required]
            c.subscribe(topics)

        def received(_c, _u, message):
            nonlocal latest, online
            if message.topic in required:
                config = json.loads(message.payload)
                if config.get("state_topic") == settings.state_topic:
                    configs.add(message.topic)
            elif message.topic == settings.availability_topic:
                online = message.payload == b"online"
            elif message.topic == settings.state_topic:
                reading = json.loads(message.payload)
                stamp = datetime.fromisoformat(reading["received_at"].replace("Z", "+00:00"))
                total = reading.get("total_m3")
                if (stamp >= started and reading.get("id") == settings.meter_id
                        and reading.get("driver", reading.get("meter")) == settings.driver
                        and type(total) in (int, float) and math.isfinite(total)):
                    latest = reading

        client.on_connect, client.on_message = connected, received
        client.connect(settings.host, settings.port, keepalive=60)
        deadline = time.monotonic() + 900
        try:
            while time.monotonic() < deadline and not failure:
                if client.loop(timeout=0.2) != mqtt.MQTT_ERR_SUCCESS:
                    break
                if latest and online and configs == required:
                    print(json.dumps({"result": "PASS", "received_at": latest["received_at"],
                                      "state": latest, "discovery_count": len(configs),
                                      "availability": "online"}, ensure_ascii=False, allow_nan=False), flush=True)
                    return 0
        finally:
            client.disconnect()
        print("No new live MQTT state with expected discovery/availability within observation window", file=sys.stderr)
        return 1
    except Exception:
        print("Broker observation failed safely; check reachability, trust, credentials and topic ACLs", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
