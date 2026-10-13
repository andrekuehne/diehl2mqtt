"""Dependency monitoring must never silently miss pin drift or spam issues."""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('watch', Path(__file__).resolve().parents[2] / 'scripts/watch-native-dependencies.py')
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)
OLD, NEW = 'a' * 40, 'b' * 40
NOW = datetime(2026, 10, 13, tzinfo=timezone.utc)
VARIABLE = 'RTL_WMBUS_REF'


class API:
    def __init__(self, sha=NEW, archived=False, date='2026-10-12T00:00:00Z'):
        self.sha, self.archived, self.date = sha, archived, date
        self.writes = []

    def request(self, path, method='GET', data=None):
        if method != 'GET':
            self.writes.append((path, method, data))
        elif '/commits/' in path:
            return {'sha': self.sha, 'commit': {'committer': {'date': self.date}}}
        else:
            return {'default_branch': 'master', 'archived': self.archived}


class MonitorTests(unittest.TestCase):
    def test_all_build_runtime_pins_must_match(self):
        dockerfile = '\n'.join(f'ARG {name}={OLD}' for name in watch.DEPENDENCIES)
        dockerfile += '\n' + dockerfile
        self.assertEqual(set(watch.pinned_refs(dockerfile).values()), {OLD})
        with self.assertRaises(ValueError):
            watch.pinned_refs(dockerfile.replace(OLD, NEW, 1))

    def test_current_active_dependency_needs_no_issue(self):
        self.assertIsNone(watch.inspect(API(sha=OLD), VARIABLE, OLD, NOW))

    def test_new_commit_archived_and_stale_upstreams_are_reported(self):
        for api in (API(), API(sha=OLD, archived=True), API(sha=OLD, date='2024-01-01T00:00:00Z')):
            body = watch.inspect(api, VARIABLE, OLD, NOW)
            self.assertIn(f'diehl2mqtt-native:{VARIABLE}', body)
            self.assertIn('never changes pins', body)
        self.assertIn('archived', watch.inspect(API(sha=OLD, archived=True), VARIABLE, OLD, NOW))
        self.assertIn('over a year', watch.inspect(API(sha=OLD, date='2024-01-01T00:00:00Z'), VARIABLE, OLD, NOW))

    def test_bad_api_data_fails_instead_of_claiming_current(self):
        with self.assertRaises(ValueError):
            watch.inspect(API(sha='bad'), VARIABLE, OLD, NOW)

    def test_one_issue_is_reused_and_dismissal_respected(self):
        api = API()
        body = watch.inspect(api, VARIABLE, OLD, NOW)
        watch.sync_issue(api, 'owner/repo', VARIABLE, body, [])
        self.assertEqual(api.writes[-1][1], 'POST')
        issue = {'number': 5, 'body': body, 'state': 'closed'}
        api.writes.clear()
        watch.sync_issue(api, 'owner/repo', VARIABLE, body, [issue])
        self.assertEqual(api.writes, [])
        watch.sync_issue(api, 'owner/repo', VARIABLE, body + '\nnew candidate', [issue])
        self.assertEqual(api.writes[-1][2]['state'], 'open')

    def test_resolved_issue_closes_without_touching_other_issues(self):
        api = API()
        body = watch.inspect(api, VARIABLE, OLD, NOW)
        issues = [{'number': 1, 'body': 'unrelated', 'state': 'open'},
                  {'number': 2, 'body': body, 'state': 'open'}]
        watch.sync_issue(api, 'owner/repo', VARIABLE, None, issues)
        self.assertEqual(api.writes, [('repos/owner/repo/issues/2', 'PATCH', {'state': 'closed'})])


if __name__ == '__main__':
    unittest.main()
