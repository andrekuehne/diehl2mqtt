import json
import os
from pathlib import Path
import secrets
import tempfile
import unittest
from watermeter.settings import Settings, ConfigError, secret, scrub_environment
from watermeter.private import private_config
from watermeter.reading import accept, InvalidReading


class ConfigurationTests(unittest.TestCase):
    def test_aes_validation_and_precedence(self):
        key = secrets.token_hex(16)
        for bad in ("", key[:-1], key + " ", key + "\n", "g" * 32):
            with self.assertRaises(ConfigError):
                secret({"METER_AES_KEY": bad}, "METER_AES_KEY", aes=True)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "secret"
            for ending in ("", "\n", "\r\n"):
                path.write_text(key + ending)
                self.assertTrue(secret({"METER_AES_KEY_FILE": str(path), "METER_AES_KEY": "invalid"},
                                       "METER_AES_KEY", aes=True) == key)
            for bad in (key + "\n\n", key + " \n", "", key + "\r", key + "\nextra"):
                path.write_text(bad)
                with self.assertRaises(ConfigError):
                    secret({"METER_AES_KEY_FILE": str(path), "METER_AES_KEY": key}, "METER_AES_KEY", aes=True)
            path.unlink()
            with self.assertRaises(ConfigError):
                secret({"METER_AES_KEY_FILE": str(path), "METER_AES_KEY": key}, "METER_AES_KEY", aes=True)

    def test_private_config_cleanup(self):
        key = secrets.token_hex(16)
        with tempfile.TemporaryDirectory() as tmp:
            with private_config(Settings(), key, Path(tmp)) as directory:
                self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
                for path in directory.rglob("*"):
                    self.assertEqual(path.stat().st_mode & 0o777, 0o700 if path.is_dir() else 0o600)
                self.assertTrue(key in (directory / "wmbusmeters.d/meter").read_text())
            self.assertFalse(directory.exists())

    def test_configuration_rejects_injection(self):
        for name, value in (("METER_ID", "123"), ("METER_ID", "12345678\n"),
                            ("METER_NAME", "X\nkey=bad"), ("METER_NAME", "X=bad"),
                            ("METER_DRIVER", "auto"), ("WMBUS_MODE", "t1"),
                            ("WMBUS_FREQUENCY", "868.95M;id"), ("MQTT_ENABLED", "maybe")):
            with self.subTest(name=name), self.assertRaises(ConfigError):
                Settings.load({name: value})
        self.assertFalse(Settings.load({"MQTT_HOST": ""}).mqtt)
        for name, value in (("MQTT_HOST", "mqtt://host"), ("MQTT_PORT", "0"),
                            ("MQTT_TOPIC_PREFIX", "///"), ("MQTT_TOPIC_PREFIX", "root/+"),
                            ("MQTT_CLIENT_ID", "bad id"), ("MQTT_CLIENT_CERT_FILE", "cert"),
                            ("MQTT_TLS", "insecure")):
            with self.subTest(name=name), self.assertRaises(ConfigError):
                Settings.load({"MQTT_ENABLED": "yes", "MQTT_HOST": "host", name: value})
        s = Settings.load({"MQTT_ENABLED": "yes", "MQTT_HOST": "host", "METER_ID": "00123456",
                           "MQTT_TLS": "true", "MQTT_TOPIC_PREFIX": "custom///"})
        self.assertEqual((s.port, s.prefix, s.client_id), (8883, "custom", "watermeter_00123456"))

    def test_password_file(self):
        password = secrets.token_urlsafe(20)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "password"
            path.write_text(password + "\n")
            self.assertTrue(secret({"MQTT_PASSWORD_FILE": str(path), "MQTT_PASSWORD": "wrong"}, "MQTT_PASSWORD") == password)
            path.unlink()
            with self.assertRaises(ConfigError):
                secret({"MQTT_PASSWORD_FILE": str(path), "MQTT_PASSWORD": password}, "MQTT_PASSWORD")

    def test_scrubbing(self):
        from unittest.mock import patch
        with patch.dict(os.environ, {"METER_AES_KEY": secrets.token_hex(16), "MQTT_PASSWORD": "ephemeral"}):
            env = scrub_environment()
            self.assertNotIn("METER_AES_KEY", env)
            self.assertNotIn("MQTT_PASSWORD", env)
            self.assertNotIn("METER_AES_KEY", os.environ)


class ReadingTests(unittest.TestCase):
    def setUp(self):
        self.reading = json.loads(Path("tests/fixtures/reading.json").read_text())

    def test_valid_and_optional_unknown(self):
        self.reading.pop("flow_temperature_c")
        self.reading["status"] = None
        reading = accept(json.dumps(self.reading), Settings())
        self.assertEqual(reading["driver"], "dme173")
        self.assertEqual(reading["total_m3"], 0.252)
        self.assertTrue(reading["received_at"].endswith("Z"))
        self.assertNotIn("flow_temperature_c", reading)

    def test_bad_readings(self):
        for change in ({"id": "87654321"}, {"meter": "auto"}, {"driver": "bad"},
                       {"total_m3": None}, {"total_m3": True}, {"total_m3": -1},
                       {"total_m3": "0.2"}, {"total_m3": float("nan")},
                       {"target_m3": float("inf")}, {"flow_temperature_c": "warm"},
                       {"key": "disallowed"}):
            with self.subTest(change=change), self.assertRaises(InvalidReading):
                accept(json.dumps(self.reading | change), Settings())
        for raw in ("not json", "[]", "{}"):
            with self.assertRaises(InvalidReading):
                accept(raw, Settings())
