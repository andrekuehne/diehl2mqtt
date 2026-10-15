"""Resolve native binaries and provenance from the application that is running."""
from pathlib import Path

# A managed bundle has watermeter/watermeter/*.py, bin/ and provenance/.
APPLICATION_ROOT = Path(__file__).resolve().parents[2]


def native_bundle():
    return (APPLICATION_ROOT / 'bundle.json').is_file()


def executable(name):
    # An incomplete active bundle must fail, never search another installed release.
    return str(APPLICATION_ROOT / 'bin' / name) if native_bundle() else name


def versions_path():
    if native_bundle():
        return APPLICATION_ROOT / 'provenance/versions.txt'
    return Path('/usr/share/watermeter/versions.txt')


def versions():
    path = versions_path()
    if not path.exists():
        return {}
    return dict(line.split('=', 1) for line in path.read_text().splitlines() if '=' in line)
