"""Check actual bot configuration against both native build/runtime pins."""
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = {
    'xaelsouth/rtl-wmbus': 'RTL_WMBUS_REF',
    'wmbusmeters/wmbusmeters': 'WMBUSMETERS_REF',
}


class RenovateTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / 'renovate.json').read_text())
        self.dockerfile = (ROOT / 'Dockerfile').read_text()

    def test_extracts_every_native_pin_without_drift(self):
        managers = self.config['customManagers']
        self.assertEqual({m['depNameTemplate'] for m in managers}, set(EXPECTED))
        self.assertEqual(len(managers), len(EXPECTED))
        for manager in managers:
            with self.subTest(dependency=manager['depNameTemplate']):
                self.assertEqual(manager['customType'], 'regex')
                self.assertEqual(manager['managerFilePatterns'], ['/^Dockerfile$/'])
                self.assertEqual(manager['datasourceTemplate'], 'git-refs')
                self.assertEqual(manager['currentValueTemplate'], 'master')
                self.assertEqual(manager['packageNameTemplate'], 'https://github.com/' + manager['depNameTemplate'])
                self.assertEqual(len(manager['matchStrings']), 1)
                # These expressions use only syntax common to Python and RE2;
                # translate the named capture spelling for this CI check.
                expression = manager['matchStrings'][0].replace('(?<currentDigest>', '(?P<currentDigest>')
                matches = list(re.finditer(expression, self.dockerfile))
                self.assertEqual(len(matches), 2, 'Renovate must find both build/runtime occurrences')
                pins = [m.group('currentDigest') for m in matches]
                self.assertTrue(all(re.fullmatch('[0-9a-f]{40}', pin) for pin in pins))
                self.assertEqual(len(set(pins)), 1, 'Build/runtime decoder revisions must match')
                variable = EXPECTED[manager['depNameTemplate']]
                actual = re.findall(r'^ARG ' + variable + '=([0-9a-f]{40})$', self.dockerfile, re.M)
                self.assertEqual(pins, actual)

    def test_bot_scopes_do_not_overlap_and_auto_merge_is_disabled(self):
        self.assertEqual(self.config['enabledManagers'], ['custom.regex'])
        self.assertIs(self.config['automerge'], False)
        self.assertTrue(self.config['dependencyDashboard'])
        dependabot = (ROOT / '.github/dependabot.yml').read_text()
        self.assertEqual(set(re.findall(r'package-ecosystem: (\S+)', dependabot)),
                         {'docker', 'github-actions', 'pip'})


if __name__ == '__main__':
    unittest.main()
