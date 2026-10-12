#!/usr/bin/env python3
"""Check repository metadata and release alignment without user configuration."""
from pathlib import Path
import re
import yaml

root = Path(__file__).resolve().parents[1]
config = yaml.safe_load((root / 'ha-addon/config.yaml').read_text())
repository = yaml.safe_load((root / 'repository.yaml').read_text())
assert repository['name'] and repository['url'] == config['url']
assert config['arch'] == ['amd64'] and config['usb'] and config['tmpfs']
assert config['services'] == ['mqtt:want'] and not config.get('full_access', False)
assert not config.get('hassio_api', False) and not config.get('host_network', False)
assert config['stage'] == 'experimental'
assert not config.get('privileged') and config.get('apparmor', True)
assert (root / 'ha-addon/apparmor.txt').is_file()
assert set(config['options']) == set(config['schema'])
assert config['options']['meter_id'] is None and config['options']['aes_key'] is None
assert config['schema']['aes_key'] == config['schema']['mqtt_password'] == 'password'
version = config['version']
assert re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version)
assert 'ARG HA_ADDON_VERSION=' + version in (root / 'Dockerfile').read_text()
assert 'DEFAULT_RELEASE = "v' + version + '"' in (root / 'scripts/install-proxmox.py').read_text()
translations = yaml.safe_load((root / 'ha-addon/translations/en.yaml').read_text())
assert set(translations['configuration']) == set(config['schema'])
print('PASS: Home Assistant metadata, required settings and release versions align')
