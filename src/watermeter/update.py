"""Native LXC application updates. No Docker or host credentials in the guest."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import uuid

ROOT = Path('/opt/diehl2mqtt')
CONFIG = Path('/etc/diehl2mqtt/install.json')
REPOSITORY = 'https://github.com/andrekuehne/diehl2mqtt'
MAX_ARCHIVE = 100 * 1024 * 1024
MAX_EXPANDED = 256 * 1024 * 1024


class UpdateError(ValueError):
    pass


def version(value):
    if not re.fullmatch(r'v\d+\.\d+\.\d+', value, re.ASCII):
        raise UpdateError('Expected a stable version such as v0.4.0')
    return value


def atomic_json(path, data):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x') as stream:
            os.chmod(temporary, 0o600)
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def release_path(name):
    if not re.fullmatch(r'[a-zA-Z0-9_.-]+', name, re.ASCII) or name in ('.', '..'):
        raise UpdateError('Invalid installed release path')
    path = ROOT / 'releases' / name
    if path.is_symlink() or not path.is_dir() or path.resolve().parent != (ROOT / 'releases').resolve():
        raise UpdateError('Installed release directory is missing or unsafe')
    return path


def current_name():
    target = os.readlink(ROOT / 'current')
    parts = PurePosixPath(target).parts
    if len(parts) != 2 or parts[0] != 'releases':
        raise UpdateError('Invalid current release link')
    release_path(parts[1])
    return parts[1]


def switch(name):
    release_path(name)
    temporary = ROOT / ('.current-' + uuid.uuid4().hex)
    try:
        temporary.symlink_to('releases/' + name)
        temporary.replace(ROOT / 'current')
    finally:
        temporary.unlink(missing_ok=True)


def read_state():
    path = ROOT / 'update.json'
    return json.loads(path.read_text()) if path.exists() else {}


def context():
    if os.geteuid() != 0:
        raise UpdateError('Run update as root inside the managed LXC')
    if not CONFIG.is_file() or CONFIG.is_symlink():
        raise UpdateError('This command requires an update-enabled LXC; Docker deployments pull a fresh image')
    installed = json.loads(CONFIG.read_text())
    if installed.get('kind') != 'diehl2mqtt-lxc' or ROOT.is_symlink():
        raise UpdateError('Unrecognized LXC installation')
    current_name()
    return installed


def download(url, limit=65536):
    with urllib.request.urlopen(url, timeout=30) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise UpdateError('Release download exceeds its size limit')
    return data


def latest():
    data = json.loads(download('https://api.github.com/repos/andrekuehne/diehl2mqtt/releases/latest'))
    if data.get('draft') or data.get('prerelease'):
        raise UpdateError('Latest release is not stable')
    return version(data['tag_name'])


def extract(archive, destination):
    """Extract only regular application files; never follow archive links."""
    seen, total = set(), 0
    with tarfile.open(archive, 'r:gz') as stream:
        for member in stream:
            name = PurePosixPath(member.name)
            if (name.is_absolute() or '..' in name.parts or not name.parts
                    or name.parts[0] not in ('watermeter', 'venv', 'bin', 'provenance', 'bundle.json')
                    or member.name in seen or len(seen) >= 20000):
                raise UpdateError('Unsafe application archive path')
            seen.add(member.name)
            total += member.size
            if total > MAX_EXPANDED:
                raise UpdateError('Expanded application archive is too large')
            target = destination.joinpath(*name.parts)
            # The packaged venv has just one harmless relative directory link.
            if member.issym() and member.name == 'venv/lib64' and member.linkname == 'lib':
                continue
            if not (member.isdir() or member.isfile()):
                raise UpdateError('Application archives cannot contain devices or links')
            if target.is_symlink():
                raise UpdateError('Unsafe archive destination')
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as output:
                    shutil.copyfileobj(stream.extractfile(member), output)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)
    binaries = destination / 'venv/bin'
    if binaries.exists():
        raise UpdateError('Unexpected bundled interpreter directory')
    binaries.mkdir()
    for binary in ('python', 'python3'):
        (binaries / binary).symlink_to('/usr/bin/python3')
    (destination / 'venv/lib64').symlink_to('lib')


def compatible(metadata, wanted, os_release=None):
    if os_release is None:
        os_release = platform.freedesktop_os_release()
    if (metadata.get('format') != 1 or metadata.get('version') != wanted
            or metadata.get('architecture') != platform.machine()
            or metadata.get('python') != list(sys.version_info[:2])
            or metadata.get('os') != [os_release.get('ID'), os_release.get('VERSION_ID')]):
        raise UpdateError('Release needs a different OS/Python/architecture; deploy a fresh LXC')


def stage(wanted):
    if shutil.disk_usage(ROOT).free < 512 * 1024 * 1024:
        raise UpdateError('At least 512 MiB free disk space is required to stage an update')
    asset = f'diehl2mqtt-{wanted}-app-amd64.tar.gz'
    base = f'{REPOSITORY}/releases/download/{wanted}/'
    sums = download(base + 'SHA256SUMS').decode().splitlines()
    checks = [line.split()[0] for line in sums if line.split()[1:] == [asset]]
    if len(checks) != 1 or not re.fullmatch('[0-9a-f]{64}', checks[0]):
        raise UpdateError('Release has no checksum for the native application bundle')
    with tempfile.TemporaryDirectory(prefix='.staging-', dir=ROOT) as temp:
        temp = Path(temp)
        archive = temp / 'app.tar.gz'
        digest = hashlib.sha256()
        size = 0
        with urllib.request.urlopen(base + asset, timeout=30) as response, archive.open('xb') as output:
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_ARCHIVE:
                    raise UpdateError('Application archive is too large')
                digest.update(chunk)
                output.write(chunk)
        if digest.hexdigest() != checks[0]:
            raise UpdateError('Application bundle checksum mismatch')
        tree = temp / 'tree'
        tree.mkdir()
        extract(archive, tree)
        metadata = json.loads((tree / 'bundle.json').read_text())
        compatible(metadata, wanted)
        env = dict(os.environ, PYTHONPATH=str(tree / 'watermeter'))
        # No meter/key is needed for these smoke checks. Never print child output.
        for command in ([str(tree / 'venv/bin/python'), '-c', 'import watermeter.__main__, watermeter.update, watermeter.health, paho.mqtt'],
                        [str(tree / 'bin/wmbusmeters'), '--listdrivers'],
                        [str(tree / 'bin/rtl_wmbus'), '-V']):
            result = subprocess.run(command, env=env, capture_output=True, timeout=15)
            if result.returncode:
                raise UpdateError('Staged application failed its compatibility smoke check')
        name = wanted + '-' + checks[0][:12]
        target = ROOT / 'releases' / name
        if target.exists():
            existing = release_path(name)
            if json.loads((existing / 'bundle.json').read_text()) != metadata:
                raise UpdateError('Retained release metadata does not match the verified download')
            # Re-download and replace an unused retained tree, rather than trusting old files.
            if name == current_name():
                raise UpdateError('That application release is already active')
            shutil.rmtree(existing)
        tree.rename(target)
        return name


def queue(name):
    old = current_name()
    if old == name:
        print('Already running that application release')
        return
    metadata = json.loads((release_path(name) / 'bundle.json').read_text())
    version(metadata['version'])
    state = {'phase': 'pending', 'old': old, 'new': name, 'version': metadata['version']}
    atomic_json(ROOT / 'update.json', state)
    switch(name)
    print('Application update queued. The reader restarts in this CT; settings and secrets are preserved.')
    print('Run update --status to see validation or rollback. RF/MQTT delivery still needs checking.')


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', type=version)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--check', action='store_true')
    actions.add_argument('--status', action='store_true')
    actions.add_argument('--rollback', action='store_true')
    parser.add_argument('--yes', action='store_true', help='Skip the application-update confirmation')
    args = parser.parse_args()
    if args.rollback and args.release:
        parser.error('--rollback cannot be combined with --release')
    try:
        installed = context()
        if args.status:
            print(json.dumps({'installed': installed['release'], **read_state()}, indent=2))
            return 0
        with (ROOT / 'update.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise UpdateError('Another update is in progress') from None
            state = read_state()
            if state.get('phase') == 'pending':
                raise UpdateError('An update is awaiting validation; run update --status')
            if args.rollback:
                name = state.get('previous')
                if not name:
                    raise UpdateError('No previous application release is available')
                release_path(name)
                wanted = json.loads((release_path(name) / 'bundle.json').read_text())['version']
            else:
                wanted = args.release or latest()
            print(f"Installed: {installed['release']}; target: {wanted}")
            if args.check or (wanted == installed['release'] and not args.rollback):
                return 0
            if not args.yes and input('Update the reader application? [y/N]: ').strip().lower() != 'y':
                return 0
            queue(name if args.rollback else stage(wanted))
        return 0
    except UpdateError as error:
        print(f'Update stopped: {error}', file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, tarfile.TarError, subprocess.SubprocessError):
        # Network/library errors can contain environment or other private text.
        print('Update stopped safely. Check release compatibility, disk space and network; no credentials are logged.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
