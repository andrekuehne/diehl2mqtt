"""Fork snapshot resolution, exact-source packaging and release immutability."""
import importlib.util
import io
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
import urllib.error

ROOT = Path(__file__).resolve().parents[2]


def script(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


resolver = script('resolve-dev')
packager = script('package-release')
release = script('check-release-available')


class DecoderBuildTests(unittest.TestCase):
    def test_resolver_returns_one_snapshot_and_rejects_ambiguous_results(self):
        first, second = '1' * 40, '2' * 40
        with patch.object(resolver.subprocess, 'check_output', side_effect=[
                first + '\trefs/heads/dev\n', second + '\trefs/heads/dev\n']) as remote:
            snapshot = resolver.resolve()
            self.assertEqual(snapshot, first)
            self.assertEqual(resolver.resolve(), second)
            self.assertEqual(snapshot, first)
            self.assertEqual(remote.call_args.args[0][-1], 'refs/heads/dev')
        for output in ('', 'bad\trefs/heads/dev\n', first + '\trefs/heads/master\n',
                       first + '\trefs/heads/dev\n' + second + '\trefs/heads/dev\n'):
            with patch.object(resolver.subprocess, 'check_output', return_value=output), self.assertRaises(ValueError):
                resolver.resolve()

    def test_all_targets_share_resolved_commit_and_local_git_source_tracks_ref(self):
        workflow = (ROOT / '.github/workflows/build.yml').read_text()
        self.assertEqual(workflow.count('commit=$(python3 scripts/resolve-dev.py)'), 1)
        self.assertEqual(workflow.count('RTL_WMBUS_DEV_REF=${{ steps.decoder.outputs.commit }}'), 3)
        dockerfile = (ROOT / 'Dockerfile').read_text()
        self.assertIn('ARG RTL_WMBUS_DEV_REF=dev', dockerfile)
        self.assertIn('ADD --keep-git-dir=true https://github.com/andrekuehne/rtl-wmbus.git#${RTL_WMBUS_DEV_REF}', dockerfile)
        self.assertIn('COPY --from=dev-build /build/rtl-dev/build/rtl_wmbus /usr/local/bin/rtl_wmbus_dev', dockerfile)

    def provenance(self, commit):
        dockerfile = (ROOT / 'Dockerfile').read_text()
        import re
        upstream = re.search(r'ARG RTL_WMBUS_REF=([a-f0-9]{40})', dockerfile)[1]
        meters = re.search(r'ARG WMBUSMETERS_REF=([a-f0-9]{40})', dockerfile)[1]
        return (f'rtl_wmbus_commit={upstream}\nwmbusmeters_commit={meters}\n'
                'rtl_wmbus_dev_repository=https://github.com/andrekuehne/rtl-wmbus\n'
                f'rtl_wmbus_dev_branch=dev\nrtl_wmbus_dev_commit={commit}\n')

    def test_packaging_uses_image_snapshot_without_resolving_dev_again(self):
        dockerfile = (ROOT / 'Dockerfile').read_text()
        snapshot = '1' * 40
        with patch.object(packager.subprocess, 'check_output', side_effect=AssertionError('No branch lookup')):
            refs = packager.native_refs(dockerfile, self.provenance(snapshot))
        self.assertEqual(refs['RTL_WMBUS_DEV_REF'], snapshot)
        for metadata in (self.provenance('dev'), self.provenance(snapshot).replace('branch=dev', 'branch=master'),
                         self.provenance(snapshot).replace('rtl_wmbus_commit=', 'other=')):
            with self.assertRaises(ValueError):
                packager.native_refs(dockerfile, metadata)

    def test_existing_release_is_rejected_and_network_errors_fail_closed(self):
        with patch.object(release.urllib.request, 'urlopen', return_value=io.BytesIO(b'{}')):
            with self.assertRaisesRegex(RuntimeError, 'already published'):
                release.check('v0.9.0', 'andrekuehne/diehl2mqtt')
        for code in (404, 403, 500):
            error = urllib.error.HTTPError('https://example.invalid', code, 'test', {}, None)
            with patch.object(release.urllib.request, 'urlopen', side_effect=error):
                if code == 404:
                    release.check('v0.9.0', 'andrekuehne/diehl2mqtt')
                else:
                    with self.assertRaisesRegex(RuntimeError, 'Cannot verify'):
                        release.check('v0.9.0', 'andrekuehne/diehl2mqtt')
        with patch.object(release.urllib.request, 'urlopen', side_effect=OSError()):
            with self.assertRaises(RuntimeError):
                release.check('v0.9.0', 'andrekuehne/diehl2mqtt')

    def test_existing_images_are_rejected_and_missing_tags_are_allowed(self):
        for code, stderr, allowed in ((0, '', False), (1, 'manifest unknown', True),
                                      (1, 'TLS/network error', False)):
            with patch.object(release.subprocess, 'run', return_value=subprocess.CompletedProcess([], code, '', stderr)) as inspect:
                if allowed:
                    release.check_images('v0.9.0', 'andrekuehne/diehl2mqtt')
                    self.assertEqual(inspect.call_count, 2)
                else:
                    with self.assertRaises(RuntimeError):
                        release.check_images('v0.9.0', 'andrekuehne/diehl2mqtt')
        workflow = (ROOT / '.github/workflows/build.yml').read_text()
        self.assertNotIn('--clobber', workflow)
        self.assertIn('scripts/check-release-available.py "$GITHUB_REF_NAME" --images', workflow)
