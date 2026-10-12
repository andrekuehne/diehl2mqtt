"""Supervisor adapter with synthetic options and an isolated health endpoint."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

from watermeter import addon
from watermeter.health import identity
from watermeter.settings import ConfigError


class AddonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.options = dict(meter_id='00123456', aes_key='00112233445566778899aabbccddeeff',
                            mqtt_auto=False, mqtt_host='broker.invalid', mqtt_username='mqtt',
                            mqtt_password='test-password')

    def tearDown(self):
        self.tmp.cleanup()

    def configure(self, **changes):
        return addon.configuration(self.options | changes, root=self.root)

    def test_manual_configuration_preserves_mqtt_contract(self):
        settings, key, password = self.configure()
        self.assertEqual(key, self.options['aes_key'])
        self.assertEqual(password, 'test-password')
        self.assertEqual(settings.state_topic, 'watermeter/00123456/state')
        self.assertEqual(settings.availability_topic, 'watermeter/00123456/availability')
        self.assertEqual(settings.client_id, 'watermeter_00123456')
        self.assertEqual(settings.host, 'broker.invalid')
        self.assertTrue(settings.discovery)
        self.assertEqual(settings.status_topic, 'homeassistant/status')

    def test_auto_service_and_explicit_overrides(self):
        broker = dict(host='core-mosquitto', port=1883, username='generated', password='service-password', ssl=False)
        with patch.object(addon, 'mqtt_service', return_value=broker) as service:
            settings, _, password = addon.configuration(self.options | {'mqtt_auto': True}, 'test-token',
                                                       self.root, service=service)
        service.assert_called_once_with('test-token')
        self.assertEqual((settings.host, settings.username, password),
                         ('core-mosquitto', 'generated', 'service-password'))
        custom, _, _ = self.configure(mqtt_topic_prefix='custom/water', mqtt_client_id='custom_client',
                                     ha_discovery=False, ha_discovery_prefix='custom/ha', ha_status_topic='custom/birth')
        self.assertEqual(custom.state_topic, 'custom/water/00123456/state')
        self.assertEqual(custom.client_id, 'custom_client')
        self.assertFalse(custom.discovery)
        self.assertEqual(custom.status_topic, 'custom/birth')

    def test_invalid_options_never_echo_values(self):
        for changes in ({'meter_id': 12345678}, {'meter_id': ''}, {'aes_key': 'bad-secret'},
                        {'mqtt_port': True}, {'mqtt_port': 0}, {'mqtt_auto': 'false'},
                        {'mqtt_password': 'bad\npassword'}, {'mqtt_host': 'mqtt://secret.invalid'},
                        {'mqtt_username': ''}, {'mqtt_client_key': 'private-key-without-certificate'}):
            with self.subTest(changes=list(changes)):
                with self.assertRaises(ConfigError) as caught:
                    self.configure(**changes)
                for value in changes.values():
                    if isinstance(value, str) and len(value) > 8:
                        self.assertNotIn(value, str(caught.exception))

    def test_tls_from_configuration_and_private_key_permissions(self):
        settings, _, _ = self.configure(mqtt_tls=True, mqtt_port=8883,
                                       mqtt_ca_certificate='test-ca', mqtt_client_certificate='test-cert',
                                       mqtt_client_key='test-key')
        self.assertTrue(settings.tls)
        self.assertEqual(Path(settings.client_key).read_text(), 'test-key')
        self.assertEqual(Path(settings.client_key).stat().st_mode & 0o777, 0o600)
        Path(settings.client_key).unlink()
        target = self.root / 'do-not-modify'
        target.write_text('unchanged')
        Path(settings.client_key).symlink_to(target)
        with self.assertRaises(OSError):
            self.configure(mqtt_tls=True, mqtt_client_certificate='cert', mqtt_client_key='new-key')
        self.assertEqual(target.read_text(), 'unchanged')

    def test_child_environment_excludes_secrets_and_supervisor_token(self):
        env = addon.child_environment(dict(PATH='/bin', PYTHONPATH='/opt/watermeter',
                                          SUPERVISOR_TOKEN='token', METER_AES_KEY='key',
                                          MQTT_PASSWORD='password', MQTT_PASSWORD_FILE='/data/password',
                                          HTTP_PROXY='http://proxy', OTHER_SECRET='secret'))
        self.assertEqual(env, {'PATH': '/bin', 'PYTHONPATH': '/opt/watermeter'})

    def test_service_response_validation_and_no_credential_redirect(self):
        @contextmanager
        def response(raw):
            class Response:
                def read(self, _limit):
                    return raw
            yield Response()
        payload = {'result': 'ok', 'data': dict(host='core-mosquitto', port=1883, username='mqtt', password='pw')}
        with patch.object(addon.urllib.request, 'build_opener') as opener:
            opener.return_value.open.return_value = response(json.dumps(payload).encode())
            self.assertEqual(addon.mqtt_service('token'), payload['data'])
            request = opener.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, 'http://supervisor/services/mqtt')
            self.assertEqual(request.get_header('Authorization'), 'Bearer token')
            redirect = opener.call_args.args[1]
            self.assertIsNone(redirect.redirect_request(None, None, 302, '', {}, 'https://other.invalid'))
        for raw in (b'{}', b'invalid', json.dumps({'result': 'ok', 'data': {'host': 'x', 'port': '1883'}}).encode()):
            with patch.object(addon.urllib.request, 'build_opener') as opener:
                opener.return_value.open.return_value = response(raw)
                with self.assertRaises(ConfigError):
                    addon.mqtt_service('token')

    def test_options_file_validation(self):
        path = self.root / 'options.json'
        for raw in ('[]', 'not JSON', 'x' * (addon.MAX_OPTIONS + 1)):
            path.write_text(raw)
            with self.assertRaises(ConfigError):
                addon.load_options(path)
        path.write_text(json.dumps(self.options))
        self.assertEqual(addon.load_options(path), self.options)

    def test_watchdog_measures_process_health_not_rf_or_mqtt(self):
        import time
        processes = [dict(pid=os.getpid(), started=identity(os.getpid()))] * 4
        state = dict(heartbeat=time.monotonic(), processes=processes, last_received_at=None, mqtt_connected=False)
        with addon.health_server(self.root, port=0) as server:
            url = 'http://127.0.0.1:' + str(server.server_port) + '/health'
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(url)
            self.assertEqual(caught.exception.code, 503)
            caught.exception.close()
            (self.root / 'health.json').write_text(json.dumps(state))
            with urllib.request.urlopen(url) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(json.load(response), {'healthy': True})
            state['heartbeat'] -= 10
            (self.root / 'health.json').write_text(json.dumps(state))
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(url)
            caught.exception.close()

    def test_receiver_failure_retries_and_stop_is_not_restarted(self):
        settings, key, password = self.configure()
        calls = []
        def reader(*args, **kwargs):
            calls.append((args, kwargs))
            return 1 if len(calls) == 1 else 0
        old = signal.getsignal(signal.SIGTERM)
        self.assertEqual(addon.receive(settings, key, password, {}, self.root, reader=reader, retry=0), 0)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1][1]['root'], self.root)
        self.assertEqual(signal.getsignal(signal.SIGTERM), old)
