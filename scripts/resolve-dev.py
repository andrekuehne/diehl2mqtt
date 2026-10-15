#!/usr/bin/env python3
"""Resolve the public fork once; CI passes this snapshot to every image build."""
import re
import subprocess

REPOSITORY = 'https://github.com/andrekuehne/rtl-wmbus.git'
BRANCH = 'refs/heads/dev'


def resolve():
    output = subprocess.check_output(['git', 'ls-remote', '--exit-code', REPOSITORY, BRANCH],
                                     text=True, timeout=60)
    match = re.fullmatch(r'([0-9a-f]{40})\s+refs/heads/dev\n?', output)
    if not match:
        raise ValueError('Expected exactly one dev branch commit')
    return match[1]


if __name__ == '__main__':
    print(resolve())
