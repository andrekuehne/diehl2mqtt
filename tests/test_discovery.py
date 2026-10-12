from dataclasses import replace
import json
import unittest
from watermeter.settings import Settings
from watermeter.discovery import SENSORS, messages


class DiscoveryTests(unittest.TestCase):
    def test_contract_and_stability(self):
        settings = Settings()
        configs = {topic: json.loads(payload) for topic, payload in messages(settings)}
        self.assertEqual(len(configs), 11)
        for topic, config in configs.items():
            self.assertEqual(topic, f"homeassistant/sensor/{config['unique_id']}/config")
            self.assertEqual(config['device']['identifiers'], ['diehl_hydrus_12345678'])
            self.assertEqual(config['state_topic'], 'watermeter/12345678/state')
            self.assertEqual(config['availability_topic'], 'watermeter/12345678/availability')
            self.assertEqual(config['device']['name'], 'Diehl Hydrus 2.0 ID 12345678')
            self.assertIn(config['name'], {name for _, name, _ in SENSORS})
            self.assertEqual(config['default_entity_id'], 'sensor.' + config['unique_id'])
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
        self.assertEqual(status['json_attributes_topic'], settings.state_topic)

    def test_all_decoder_fields_and_timestamps_have_safe_semantics(self):
        configs = {json.loads(payload)['unique_id']: json.loads(payload)
                   for _, payload in messages(Settings())}
        fields = {'total_m3', 'flow_temperature_c', 'status', 'target_m3', 'target_datetime',
                  'total_at_set_date_m3', 'set_date', 'total_backward_m3', 'timestamp', 'received_at', 'rssi_dbm'}
        self.assertEqual(set(configs), {'diehl_hydrus_12345678_' + f for f in fields})
        for field in ('target_m3', 'total_at_set_date_m3', 'total_backward_m3'):
            self.assertNotIn('state_class', configs['diehl_hydrus_12345678_' + field])
        local_date = configs['diehl_hydrus_12345678_target_datetime']
        self.assertNotIn('device_class', local_date)
        self.assertNotIn('as_datetime', local_date['value_template'])
        self.assertEqual(configs['diehl_hydrus_12345678_set_date']['device_class'], 'date')
        self.assertEqual(configs['diehl_hydrus_12345678_received_at']['device_class'], 'timestamp')
        signal = configs['diehl_hydrus_12345678_rssi_dbm']
        self.assertEqual(signal['name'], 'Signal strength')
        self.assertEqual(signal['entity_category'], 'diagnostic')
        self.assertEqual(signal['state_class'], 'measurement')
        self.assertNotIn('unit_of_measurement', signal)
        self.assertNotIn('device_class', signal)
        self.assertIn("else 'unknown'", signal['value_template'])

    def test_device_name_preserves_leading_zeros_and_existing_identity(self):
        configs = [json.loads(payload) for _, payload in messages(replace(Settings(), meter_id='00123456'))]
        self.assertEqual(configs[0]['name'], 'Total water')
        self.assertEqual(configs[0]['default_entity_id'], 'sensor.diehl_hydrus_00123456_total_m3')
        self.assertEqual(configs[0]['unique_id'], 'diehl_hydrus_00123456_total_m3')
        self.assertTrue(all(c['device']['name'] == 'Diehl Hydrus 2.0 ID 00123456' for c in configs))
        self.assertTrue(all('00123456' not in c['name'] for c in configs))
        renamed = [json.loads(payload) for _, payload in messages(
            replace(Settings(), meter_id='00123456', name='Basement'))]
        self.assertEqual(renamed, configs)
