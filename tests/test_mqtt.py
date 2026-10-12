"""Production Publisher against a disposable real broker on loopback only."""
from dataclasses import replace
import json
import os
from pathlib import Path
import queue
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import paho.mqtt.client as mqtt
from watermeter.mqtt import Publisher
from watermeter.reading import accept, encode
from watermeter.settings import Settings, secret
from watermeter.discovery import messages


def wait_for(predicate, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("Timed out waiting for broker behavior")


class Broker:
    def __init__(self, root, extra=""):
        self.root = Path(root)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.path = self.root / "mosquitto.conf"
        self.path.write_text(("user root\n" if os.geteuid() == 0 else "") +
                             f"listener {self.port} 127.0.0.1\nallow_anonymous true\npersistence false\n" + extra)
        self.process = None

    def start(self):
        self.process = subprocess.Popen([os.getenv("MOSQUITTO_BIN", "mosquitto"), "-c", str(self.path)],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def ready():
            if self.process.poll() is not None:
                raise AssertionError("Disposable broker failed to start")
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.1):
                    return True
            except OSError:
                return False
        wait_for(ready, 5)

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=5)
        self.process = None


class Subscriber:
    def __init__(self, port, topics="#", username=None, password=None):
        self.records = []
        self.lock = threading.Lock()
        self.ready = threading.Event()
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="test_" + secrets.token_hex(6))
        if username:
            self.client.username_pw_set(username, password)
        self.client.on_connect = lambda client, *_: client.subscribe(topics, qos=1)
        self.client.on_subscribe = lambda *_: self.ready.set()
        def received(_client, _userdata, message):
            with self.lock:
                self.records.append((message.topic, message.payload.decode(), message.retain, message.qos))
        self.client.on_message = received
        self.client.connect("127.0.0.1", port, 60)
        self.client.loop_start()
        if not self.ready.wait(4):
            self.close()
            raise AssertionError("Subscriber failed")

    def records_for(self, topic):
        with self.lock:
            return [r for r in self.records if r[0] == topic]

    def close(self):
        self.client.disconnect()
        self.client.loop_stop()


@unittest.skipUnless(os.getenv("WATERMETER_TEST_MQTT") == "1", "enable isolated broker integration explicitly")
class MQTTIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.broker = Broker(self.root)
        self.publishers = []
        self.subscribers = []

    def tearDown(self):
        for publisher in self.publishers:
            publisher.close()
        for subscriber in self.subscribers:
            subscriber.close()
        self.broker.stop()
        self.tmp.cleanup()

    def settings(self, **kwargs):
        return replace(Settings(), **({"mqtt": True, "discovery": True, "host": "127.0.0.1", "port": self.broker.port} | kwargs))

    def publisher(self, settings=None, password=""):
        p = Publisher(settings or self.settings(), password)
        self.publishers.append(p)
        p.set_alive(True)
        p.start()
        return p

    def subscriber(self, **kwargs):
        s = Subscriber(self.broker.port, **kwargs)
        self.subscribers.append(s)
        return s

    def payload(self, settings=None):
        settings = settings or Settings()
        reading = json.loads(Path("tests/fixtures/reading.json").read_text())
        reading["id"] = settings.meter_id
        return encode(accept(json.dumps(reading), settings))

    def test_retained_birth_duplicates_shutdown(self):
        self.broker.start()
        p = self.publisher()
        s = self.subscriber()
        wait_for(lambda: s.records_for(p.settings.availability_topic))
        self.assertFalse(s.records_for(p.settings.state_topic))
        p.submit(self.payload())
        wait_for(lambda: s.records_for(p.settings.state_topic))
        late = self.subscriber()
        discovery_count = len(list(messages(p.settings)))
        wait_for(lambda: len(late.records) >= discovery_count + 2)
        self.assertTrue(all(r[2] and r[3] == 1 for r in late.records))
        configs = [r for r in late.records if r[0].endswith("/config")]
        self.assertEqual(len(configs), discovery_count)
        self.assertTrue(all(json.loads(r[1])["name"].endswith(" " + p.settings.meter_id) for r in configs))
        first = s.records_for(p.settings.state_topic)[-1][1]
        count = len([r for r in s.records if r[0].endswith("/config")])
        p.submit(first)  # repeated absolute reading does not fabricate a delta
        wait_for(lambda: len(s.records_for(p.settings.state_topic)) >= 2)
        self.assertEqual(count, len([r for r in s.records if r[0].endswith("/config")]))
        s.client.publish(p.settings.status_topic, "online", qos=1).wait_for_publish(3)
        wait_for(lambda: len([r for r in s.records if r[0].endswith("/config")]) >= count + discovery_count)
        wait_for(lambda: len(s.records_for(p.settings.state_topic)) >= 3)
        self.assertEqual(s.records_for(p.settings.state_topic)[-1][1], first)
        self.assertGreaterEqual(p.acknowledged, 10)
        p.close()
        wait_for(lambda: s.records_for(p.settings.availability_topic)[-1][1] == "offline")
        late2 = self.subscriber()
        wait_for(lambda: late2.records_for(p.settings.availability_topic))
        self.assertEqual(late2.records_for(p.settings.availability_topic)[-1][1], "offline")

    def test_complete_decoded_telegram_is_retained_and_replayed(self):
        self.broker.start()
        p = self.publisher()
        raw = json.loads(Path("tests/fixtures/reading.json").read_text()) | {
            "total_backward_m3": 0.012, "total_at_set_date_m3": 0.15,
            "set_date": "2025-12-31", "timestamp": "2026-10-12T12:00:00Z",
            "extra_decoder_data": {"counter": 7, "flags": ["OK"]},
        }
        accepted = accept(encode(raw), p.settings)
        p.submit(encode(accepted))
        s = self.subscriber()
        wait_for(lambda: s.records_for(p.settings.state_topic))
        self.assertEqual(json.loads(s.records_for(p.settings.state_topic)[-1][1]), accepted)
        for field, value in raw.items():
            self.assertEqual(accepted[field], value)
        late = self.subscriber()
        wait_for(lambda: late.records_for(p.settings.state_topic))
        retained = late.records_for(p.settings.state_topic)[-1]
        self.assertTrue(retained[2])
        self.assertEqual(json.loads(retained[1]), accepted)
        s.client.publish(p.settings.status_topic, "online", qos=1).wait_for_publish(3)
        wait_for(lambda: len(s.records_for(p.settings.state_topic)) >= 2)
        self.assertEqual(json.loads(s.records_for(p.settings.state_topic)[-1][1]), accepted)

    def test_initial_absence_restart_and_bounded_cache(self):
        p = self.publisher()
        for i in range(2000):
            p.submit(encode({"total_m3": i, "received_at": "unchanged-receipt-time"}))
        self.assertFalse(p.connected)
        self.assertEqual(json.loads(p._latest)["total_m3"], 1999)
        self.broker.start()
        s = self.subscriber()
        wait_for(lambda: s.records_for(p.settings.state_topic), 15)
        self.assertEqual(json.loads(s.records_for(p.settings.state_topic)[-1][1])["total_m3"], 1999)
        self.broker.stop()
        wait_for(lambda: not p.connected)
        p.submit(self.payload())
        latest = p._latest
        self.broker.start()
        late = self.subscriber()
        wait_for(lambda: late.records_for(p.settings.state_topic), 15)
        self.assertEqual(late.records_for(p.settings.state_topic)[-1][1], latest)
        wait_for(lambda: len([r for r in late.records if r[0].endswith("/config")]) == len(list(messages(p.settings))))

    def test_discovery_disabled_and_overrides(self):
        self.broker.start()
        settings = self.settings(meter_id="00123456", name="Basement", prefix="custom/water",
                                 client_id="distinct_test_client", discovery=False)
        p = self.publisher(settings)
        s = self.subscriber()
        p.submit(self.payload(settings))
        wait_for(lambda: s.records_for("custom/water/00123456/state"))
        self.assertFalse([r for r in s.records if r[0].endswith("/config")])
        self.assertEqual(p._client()._client_id, b"distinct_test_client")

    def test_custom_discovery_birth_and_optional_unknowns(self):
        self.broker.start()
        settings = self.settings(meter_id="00123456", name="Basement", prefix="custom/water",
                                 discovery_prefix="custom/ha", status_topic="custom/birth")
        p = self.publisher(settings)
        s = self.subscriber()
        reading = json.loads(self.payload(settings))
        reading.pop("flow_temperature_c")
        reading["status"] = None
        p.submit(encode(reading))
        discovery_count = len(list(messages(settings)))
        wait_for(lambda: len([r for r in s.records if r[0].endswith("/config")]) == discovery_count)
        configs = [json.loads(r[1]) for r in s.records if r[0].endswith("/config")]
        self.assertTrue(all(c["unique_id"].startswith("diehl_hydrus_00123456_") for c in configs))
        self.assertTrue(all(c["device"]["name"] == "Basement" for c in configs))
        self.assertTrue(all(c["name"].endswith(" 00123456") for c in configs))
        wait_for(lambda: s.records_for(settings.state_topic))
        result = json.loads(s.records_for(settings.state_topic)[-1][1])
        self.assertNotIn("flow_temperature_c", result)
        self.assertIsNone(result["status"])
        s.client.publish("custom/birth", "online", qos=1).wait_for_publish(3)
        wait_for(lambda: len([r for r in s.records if r[0].endswith("/config")]) >= 2 * discovery_count)
        wait_for(lambda: len(s.records_for(settings.state_topic)) >= 2)
        self.assertEqual(json.loads(s.records_for(settings.state_topic)[-1][1]), reading)

    def test_last_will_after_process_death(self):
        self.broker.start()
        s = self.subscriber()
        process = subprocess.Popen([sys.executable, "tests/mqtt_crash_harness.py", str(self.broker.port)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            wait_for(lambda: s.records_for("watermeter/12345678/availability"))
            process.kill()
            process.wait(timeout=4)
            wait_for(lambda: s.records_for("watermeter/12345678/availability")[-1][1] == "offline")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()

    def test_authentication_and_password_file_precedence(self):
        password = secrets.token_urlsafe(20)
        passwd = self.root / "passwd"
        passwd.write_text("test:" + password + "\n")
        subprocess.run([os.getenv("MOSQUITTO_PASSWD_BIN", "mosquitto_passwd"), "-U", str(passwd)],
                       check=True, capture_output=True)
        self.broker.path.write_text(self.broker.path.read_text().replace("allow_anonymous true", "allow_anonymous false")
                                   + f"password_file {passwd}\n")
        self.broker.start()
        bad = self.publisher(self.settings(username="test"), "wrong")
        time.sleep(1)
        self.assertFalse(bad.connected)
        bad.close()
        password_file = self.root / "password"
        password_file.write_text(password + "\n")
        chosen = secret({"MQTT_PASSWORD": "wrong", "MQTT_PASSWORD_FILE": str(password_file)}, "MQTT_PASSWORD")
        p = self.publisher(self.settings(username="test"), chosen)
        s = self.subscriber(username="test", password=password)
        p.submit(self.payload())
        wait_for(lambda: s.records_for(p.settings.state_topic))

    def tls_files(self):
        def openssl(*args):
            subprocess.run(["openssl", *args], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ca, cakey, cert, key = (self.root / n for n in ("ca.pem", "ca.key", "server.pem", "server.key"))
        csr = self.root / "server.csr"
        openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(cakey), "-out", str(ca),
                "-subj", "/CN=Watermeter Test CA", "-days", "1",
                "-addext", "keyUsage=critical,keyCertSign,cRLSign")
        openssl("req", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(csr), "-subj", "/CN=localhost")
        ext = self.root / "ext"
        ext.write_text("subjectAltName=DNS:localhost\nbasicConstraints=critical,CA:FALSE\n"
                       "keyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n")
        openssl("x509", "-req", "-in", str(csr), "-CA", str(ca), "-CAkey", str(cakey), "-CAcreateserial",
                "-out", str(cert), "-days", "1", "-extfile", str(ext))
        self.broker.path.write_text(self.broker.path.read_text() + f"cafile {ca}\ncertfile {cert}\nkeyfile {key}\n")
        return str(ca)

    def test_verified_tls_untrusted_and_hostname_mismatch(self):
        ca = self.tls_files()
        self.broker.start()
        for settings in (self.settings(tls=True), self.settings(tls=True, ca=ca)):
            p = self.publisher(settings)
            time.sleep(0.8)
            self.assertFalse(p.connected)
            p.close()
        valid = self.publisher(replace(self.settings(tls=True, ca=ca), host="localhost"))
        valid.submit(self.payload())
        wait_for(lambda: valid.acknowledged >= 5)
        self.assertTrue(valid.connected)

    def test_mutual_tls_requires_client_certificate(self):
        ca = self.tls_files()
        key, csr, cert = (self.root / n for n in ("client.key", "client.csr", "client.pem"))
        def openssl(*args):
            subprocess.run(["openssl", *args], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        openssl("req", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(csr), "-subj", "/CN=watermeter-test")
        ext = self.root / "client.ext"
        ext.write_text("basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=clientAuth\n")
        openssl("x509", "-req", "-in", str(csr), "-CA", ca, "-CAkey", str(self.root / "ca.key"), "-CAcreateserial",
                "-out", str(cert), "-days", "1", "-extfile", str(ext))
        self.broker.path.write_text(self.broker.path.read_text() + "require_certificate true\n")
        self.broker.start()
        missing = self.publisher(replace(self.settings(tls=True, ca=ca), host="localhost"))
        time.sleep(0.8)
        self.assertEqual(missing.acknowledged, 0)
        missing.close()
        valid = self.publisher(replace(self.settings(tls=True, ca=ca, cert=str(cert), client_key=str(key)), host="localhost"))
        valid.submit(self.payload())
        wait_for(lambda: valid.acknowledged >= 5)
        self.assertTrue(valid.connected)
