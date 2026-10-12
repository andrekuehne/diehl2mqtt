from dataclasses import replace
import json
import unittest
from watermeter.settings import Settings
from watermeter.discovery import messages


class DiscoveryTests(unittest.TestCase):
    def test_contract_and_stability(self):
        settings = Settings()
        configs = {topic: json.loads(payload) for topic, payload in messages(settings)}
        self.assertEqual(len(configs), 3)
        for topic, config in configs.items():
            self.assertEqual(topic, f"homeassistant/sensor/{config['unique_id']}/config")
            self.assertEqual(config['device']['identifiers'], ['diehl_hydrus_12345678'])
            self.assertEqual(config['state_topic'], 'watermeter/12345678/state')
            self.assertEqual(config['availability_topic'], 'watermeter/12345678/availability')
            self.assertNotIn('expire_after', config)
            self.assertIn('.get(', config['value_template'])
            self.assertNotIn('float(0)', config['value_template'])
        self.assertEqual([t for t, _ in messages(replace(settings, name='Renamed'))], list(configs))
        total = next(c for c in configs.values() if c['unique_id'].endswith('_total_m3'))
        self.assertEqual((total['device_class'], total['state_class'], total['unit_of_measurement']),
                         ('water', 'total_increasing', 'm³'))
        status = next(c for c in configs.values() if c['unique_id'].endswith('_status'))
        self.assertEqual(status['entity_category'], 'diagnostic')
        self.assertNotIn('state_class', status)
