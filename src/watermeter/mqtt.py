"""Bounded latest-state publisher; only the worker performs network I/O."""
import ssl
import threading
import time
import paho.mqtt.client as mqtt
from .discovery import messages
from .settings import ConfigError
from .supervisor import log


class VerifiedTLSClient(mqtt.Client):
    # Paho 2.1.0's wrapper leaves failed-handshake sockets to GC and uses the
    # 60-second keepalive as a handshake timeout. Keep the pinned adapter small.
    def _ssl_wrap_socket(self, tcp_sock):
        wrapped = None
        try:
            wrapped = self._ssl_context.wrap_socket(tcp_sock, server_hostname=self._host,
                                                   do_handshake_on_connect=False)
            wrapped.settimeout(self.connect_timeout)
            wrapped.do_handshake()
            return wrapped
        except BaseException:
            (wrapped if wrapped is not None else tcp_sock).close()
            raise


class Publisher:
    def __init__(self, settings, password=""):
        self.settings = settings
        self._password = password
        if password and not settings.username:
            raise ConfigError("MQTT_PASSWORD requires MQTT_USERNAME")
        self._tls = None
        if settings.tls:
            try:
                self._tls = ssl.create_default_context(cafile=settings.ca or None)
                if settings.cert:
                    self._tls.load_cert_chain(settings.cert, settings.client_key)
            except (OSError, ValueError, ssl.SSLError):
                raise ConfigError("Cannot load MQTT TLS trust or client certificate files") from None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._latest = None
        self._version = 0
        self._generation = 0
        self._alive = False
        self.connected = False
        self._thread = None
        self.acknowledged = 0

    def submit(self, payload):
        with self._lock:
            self._latest = payload
            self._version += 1

    def set_alive(self, alive):
        with self._lock:
            self._alive = alive

    def start(self):
        self._thread = threading.Thread(target=self._worker, name="mqtt", daemon=True)
        self._thread.start()

    def _on_connect(self, client, _userdata, _flags, reason, _properties):
        if reason.is_failure:
            log("MQTT connection rejected; check authentication and broker policy")
            self.connected = False
            return
        self.connected = True
        self._generation += 1
        log("MQTT connected")
        if self.settings.discovery:
            rc, _ = client.subscribe(self.settings.status_topic, qos=1)
            if rc != mqtt.MQTT_ERR_SUCCESS:
                self.connected = False
                log("MQTT birth subscription failed")

    def _on_subscribe(self, _client, _userdata, _mid, reasons, _properties):
        if any(reason.is_failure for reason in reasons):
            log("MQTT birth subscription rejected; check broker ACL")
            self.connected = False

    def _on_disconnect(self, _client, _userdata, _flags, _reason, _properties):
        self.connected = False
        if not self._stop.is_set():
            log("MQTT disconnected; reception continues during retry")

    def _on_message(self, _client, _userdata, message):
        if message.topic == self.settings.status_topic and message.payload == b"online":
            self._generation += 1

    def _client(self):
        s = self.settings
        client = VerifiedTLSClient(mqtt.CallbackAPIVersion.VERSION2, client_id=s.client_id,
                             clean_session=True, protocol=mqtt.MQTTv311)
        client.connect_timeout = 3
        client.max_inflight_messages_set(1)
        client.max_queued_messages_set(8)
        client.reconnect_delay_set(min_delay=1, max_delay=60)
        client.will_set(s.availability_topic, "offline", qos=1, retain=True)
        if s.username:
            client.username_pw_set(s.username, self._password or None)
        if self._tls:
            client.tls_set_context(self._tls)
        client.on_connect, client.on_disconnect = self._on_connect, self._on_disconnect
        client.on_message, client.on_subscribe = self._on_message, self._on_subscribe
        return client

    def _publish(self, client, topic, payload, shutdown=False):
        info = client.publish(topic, payload, qos=1, retain=True)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            return False
        deadline = time.monotonic() + 2
        while self.connected and (shutdown or not self._stop.is_set()) and time.monotonic() < deadline:
            if info.is_published():
                self.acknowledged += 1
                return True
            if client.loop(timeout=0.1) != mqtt.MQTT_ERR_SUCCESS:
                return False
        log("MQTT publish acknowledgement unavailable; latest state will replay")
        return False

    def _session(self, client):
        sent_version, sent_generation = -1, -1
        deadline = time.monotonic() + 4
        while not self._stop.is_set():
            if client.loop(timeout=0.1) != mqtt.MQTT_ERR_SUCCESS:
                return
            if not self.connected:
                if time.monotonic() >= deadline:
                    return
                continue
            with self._lock:
                payload, version, alive = self._latest, self._version, self._alive
            generation = self._generation
            replay = generation != sent_generation
            if replay and self.settings.discovery:
                for topic, config in messages(self.settings):
                    if not self._publish(client, topic, config):
                        return
            if payload is not None and (replay or version != sent_version):
                if not self._publish(client, self.settings.state_topic, payload):
                    return
                sent_version = version
            if replay and alive:
                if not self._publish(client, self.settings.availability_topic, "online"):
                    return
            sent_generation = generation

    def _worker(self):
        backoff = 1
        while not self._stop.is_set():
            client = self._client()  # Discard obsolete Paho pending data on every retry.
            try:
                client.connect(self.settings.host, self.settings.port, keepalive=60)
                self._session(client)
                if self.connected:
                    backoff = 1
            except Exception:
                log("MQTT connection/TLS failure; reception continues during retry")
            finally:
                try:
                    if self._stop.is_set() and self.connected:
                        self._publish(client, self.settings.availability_topic, "offline", shutdown=True)
                    client.disconnect()
                    client.loop(timeout=0.1)
                except Exception:
                    pass
                self.connected = False
            if self._stop.wait(backoff):
                break
            backoff = min(backoff * 2, 60)

    def close(self):
        self.set_alive(False)
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=6)
