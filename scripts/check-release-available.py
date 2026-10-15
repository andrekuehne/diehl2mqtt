#!/usr/bin/env python3
"""Fail closed if a version is already published; never replace release assets."""
import argparse
import os
import re
import subprocess
import urllib.error
import urllib.request


def check(tag, repository):
    if not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', tag):
        raise ValueError('Expected a versioned release tag')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Invalid GitHub repository')
    headers = {'Accept': 'application/vnd.github+json'}
    token = os.environ.get('GH_TOKEN')
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = urllib.request.Request(f'https://api.github.com/repos/{repository}/releases/tags/{tag}',
                                     headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30):
            pass
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return
        raise RuntimeError('Cannot verify release availability') from None
    except OSError:
        raise RuntimeError('Cannot verify release availability') from None
    raise RuntimeError('Version already published; use a new patch release for a new snapshot')


def check_images(tag, repository):
    for version in (tag, tag.removeprefix('v')):
        result = subprocess.run(['docker', 'manifest', 'inspect',
                                 f'ghcr.io/{repository.lower()}:{version}'],
                                capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            raise RuntimeError('Versioned image already published; use a new patch release')
        if not any(message in result.stderr.lower() for message in ('manifest unknown', 'no such manifest')):
            raise RuntimeError('Cannot verify versioned image availability')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tag')
    parser.add_argument('--images', action='store_true', help='Also check registry after Docker login')
    args = parser.parse_args()
    repository = os.environ.get('GITHUB_REPOSITORY', 'andrekuehne/diehl2mqtt')
    check(args.tag, repository)
    if args.images:
        check_images(args.tag, repository)
