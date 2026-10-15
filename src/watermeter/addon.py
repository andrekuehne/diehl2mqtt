"""Home Assistant configuration adapter and supervised receiver recovery."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging
import os
from pathlib import Path
import signal
import threading
import urllib.request

from .health import healthy
from .log import configure, log
from .private import require_tmpfs
from .privileges import APP_UID, APP_GID, drop_privileges
from .settings import ConfigError, Settings, secret
from .supervisor import run

ROOT = Path('/tmp/watermeter')
OPTIONS = Path('/data/options.json')
MAX_OPTIONS = 128 * 1024


def mqtt_service(token):
    """The declared mqtt:want service grants access without broad API rights."""
    if not token:
        raise ConfigError('Automatic MQTT needs the Supervisor MQTT service; or disable mqtt_auto')
    request = urllib.request.Request('http://supervisor/services/mqtt',
                                     headers={'Authorization': 'Bearer ' + token})
    try:
        # Never send Supervisor credentials through a host proxy or redirect.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *_args, **_kwargs):
                return None
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(request, timeout=5) as response:
            raw = response.read(MAX_OPTIONS + 1)
        data = json.loads(raw)
        if len(raw) > MAX_OPTIONS or data.get('result') != 'ok':
            raise ValueError()
        service = data['data']
        if not isinstance(service['host'], str) or not service['host']:
            raise ValueError()
        if type(service['port']) is not int or type(service.get('ssl', False)) is not bool:
            raise ValueError()
        if not all(isinstance(service.get(k, ''), str) for k in ('username', 'password')):
            raise ValueError()
        return service
    except Exception:
        raise ConfigError('Supervisor MQTT service unavailable; start Mosquitto or configure manual MQTT') from None


def load_options(path=OPTIONS):
    try:
        with Path(path).open('rb') as stream:
            raw = stream.read(MAX_OPTIONS + 1)
        options = json.loads(raw)
        if len(raw) > MAX_OPTIONS or not isinstance(options, dict):
            raise ValueError()
        return options
    except (OSError, ValueError):
        raise ConfigError('Cannot read add-on Configuration options') from None


def configuration(options, token='', root=ROOT, service=mqtt_service):
    """Use data-only Settings validation; never place credentials in os.environ."""
    strings = {
        'meter_id': '', 'aes_key': '', 'meter_name': 'Water', 'frequency': '868.95M',
        'algorithm': 'both', 'log_level': 'info', 'decoder': 'reference',
        'mqtt_host': '', 'mqtt_username': '', 'mqtt_password': '',
        'mqtt_ca_certificate': '', 'mqtt_client_certificate': '', 'mqtt_client_key': '',
        'mqtt_topic_prefix': 'watermeter', 'mqtt_client_id': '',
        'ha_discovery_prefix': 'homeassistant', 'ha_status_topic': 'homeassistant/status',
    }
    values = {}
    for name, default in strings.items():
        value = options.get(name, default)
        if not isinstance(value, str):
            raise ConfigError(f'Configuration {name} must be text')
        values[name] = value
    for name, default in (('mqtt_auto', True), ('mqtt_tls', False), ('ha_discovery', True),
                          ('fast_math', False)):
        value = options.get(name, default)
        if type(value) is not bool:
            raise ConfigError(f'Configuration {name} must be a boolean')
        values[name] = value
    port = options.get('mqtt_port', 1883)
    if type(port) is not int:
        raise ConfigError('Configuration mqtt_port must be a port number')
    if values['mqtt_auto']:
        broker = service(token)
        values.update(mqtt_host=broker['host'], mqtt_username=broker.get('username', ''),
                      mqtt_password=broker.get('password', ''), mqtt_tls=broker.get('ssl', False))
        port = broker['port']
    env = {
        'METER_ID': values['meter_id'], 'METER_NAME': values['meter_name'],
        'WMBUS_FREQUENCY': values['frequency'], 'MQTT_ENABLED': 'true',
        'WMBUS_FAST_MATH': str(values['fast_math']), 'WMBUS_ALGORITHM': values['algorithm'],
        'LOG_LEVEL': values['log_level'], 'WMBUS_DECODER': values['decoder'],
        'MQTT_HOST': values['mqtt_host'], 'MQTT_PORT': str(port),
        'MQTT_USERNAME': values['mqtt_username'], 'MQTT_TLS': str(values['mqtt_tls']),
        'MQTT_TOPIC_PREFIX': values['mqtt_topic_prefix'],
        'HA_DISCOVERY_ENABLED': str(values['ha_discovery']),
        'HA_DISCOVERY_PREFIX': values['ha_discovery_prefix'],
        'HA_STATUS_TOPIC': values['ha_status_topic'],
    }
    if values['mqtt_client_id']:
        env['MQTT_CLIENT_ID'] = values['mqtt_client_id']
    key = secret({'METER_AES_KEY': values['aes_key']}, 'METER_AES_KEY', required=True, aes=True)
    password = secret({'MQTT_PASSWORD': values['mqtt_password']}, 'MQTT_PASSWORD')
    for option, variable, filename in (
        ('mqtt_ca_certificate', 'MQTT_CA_FILE', 'mqtt-ca.pem'),
        ('mqtt_client_certificate', 'MQTT_CLIENT_CERT_FILE', 'mqtt-client.pem'),
        ('mqtt_client_key', 'MQTT_CLIENT_KEY_FILE', 'mqtt-client-key.pem'),
    ):
        if values[option]:
            path = Path(root) / filename
            # root is private tmpfs; refuse links even on a repeated launch.
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'w') as stream:
                stream.write(values[option])
            env[variable] = str(path)
    settings = Settings.load(env)
    if password and not settings.username:
        raise ConfigError('MQTT password requires a username')
    return settings, key, password


def child_environment(env):
    # Supervisor token, options and inherited Docker settings must not reach SDR children.
    return {k: v for k, v in env.items() if k in (
        'PATH', 'PYTHONPATH', 'PYTHONUNBUFFERED', 'PYTHONDONTWRITEBYTECODE',
        'LANG', 'LC_ALL', 'TZ', 'HOME')}


@contextmanager
def health_server(root=ROOT, port=8099):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            valid = self.path == '/health'
            ok = valid and healthy(root)
            self.send_response(200 if ok else 503 if valid else 404)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'healthy': ok}).encode())

        def log_message(self, *_args):
            pass
    server = HTTPServer(('0.0.0.0', port), Handler)
    server.timeout = 1
    thread = threading.Thread(target=server.serve_forever, name='addon-health', daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def receive(settings, key, password, env, root=ROOT, reader=run, retry=5):
    stopped = threading.Event()
    previous = {s: signal.signal(s, lambda *_: stopped.set()) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        while not stopped.is_set():
            # Supervisor cleans up the whole pipeline and publishes offline on failure.
            if reader(settings, key, password, env, root=root) == 0:
                return 0
            log('Receiver stopped unexpectedly; retrying in five seconds (check USB passthrough)', logging.WARNING)
            if stopped.wait(retry):
                break
        return 0
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def main():
    os.umask(0o077)
    configure()
    try:
        ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
        if ROOT.is_symlink() or ROOT.stat().st_uid != os.getuid() or ROOT.stat().st_mode & 0o077:
            raise ConfigError('Add-on runtime directory must be private')
        require_tmpfs(ROOT)
        # Remove the token from the process environment before starting any child.
        token = os.environ.pop('SUPERVISOR_TOKEN', '')
        options = load_options()
        configure(options.get('log_level', 'info'))
        # Read options while root. Every receiver
        # process, certificate file and network-serving thread starts non-root.
        if os.getuid() == 0:
            os.chown(ROOT, APP_UID, APP_GID)
        drop_privileges()
        settings, key, password = configuration(options, token)
        env = child_environment(os.environ)
        del options, token
        log(f'App receiver running without root privileges (uid={os.getuid()}, gid={os.getgid()})')
        with health_server():
            return receive(settings, key, password, env)
    except ConfigError as exc:
        log(str(exc), logging.ERROR)
        return 2
    except Exception:
        log('Add-on failed safely; check Configuration, USB passthrough and runtime permissions', logging.ERROR)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
