#!/usr/bin/env python3
"""Compare real reference/fork IQ replays, including every gateway tuning option."""
import argparse
import gzip
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import subprocess


def normalized(data):
    rows = []
    for row in data.splitlines():
        fields = row.split(b';')
        if len(fields) != 8 or fields[0] not in (b'C1', b'T1', b'S1'):
            raise ValueError('Unexpected decoder packet format')
        if not re.fullmatch(rb'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{6}', fields[3]):
            raise ValueError('Unexpected decoder timestamp')
        fields[3] = b'<timestamp>'
        rows.append(b';'.join(fields))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--reference', required=True, type=Path)
    parser.add_argument('--dev', required=True, type=Path)
    args = parser.parse_args()
    manifest = json.loads((args.source / 'tests/fixtures/manifest.json').read_text())
    comparisons = 0
    for case in manifest['cases']:
        data = (args.source / case['input']).read_bytes()
        if case.get('gzip'):
            data = gzip.decompress(data)
        if hashlib.sha256(data).hexdigest() != case['sha256']:
            raise ValueError('IQ fixture checksum mismatch')
        expected = (args.source / case['expected']).read_bytes()
        if hashlib.sha256(expected).hexdigest() != case['expected_sha256']:
            raise ValueError('Expected output checksum mismatch')
        configurations = [case['options']]
        if case['center_frequency_hz'] == 868950000 and case['sample_rate_hz'] == 1600000:
            configurations += [case['options'] + ['-f', '-p', 'S'] + fast + algorithm
                               for fast, algorithm in itertools.product(
                                   ([], ['-a']), ([], ['-t', '0'], ['-r', '0']))]
        for index, options in enumerate(configurations):
            outputs = []
            for binary in (args.reference, args.dev):
                result = subprocess.run([str(binary), *options], input=data, capture_output=True,
                                        env=dict(os.environ, LC_ALL='C', TZ='UTC0'), timeout=60)
                if result.returncode:
                    raise ValueError('IQ replay failed: ' + str(binary))
                outputs.append((normalized(result.stdout), result.stderr))
            if outputs[0] != outputs[1]:
                raise ValueError('Reference/fork replay differs: ' + case['name'])
            if index == 0 and outputs[0] != (expected.splitlines(), b''):
                raise ValueError('Replay differs from reviewed golden: ' + case['name'])
            comparisons += 1
        print('PASS IQ replay: ' + case['name'], flush=True)
    print(f'PASS {comparisons} reference/fork IQ comparisons', flush=True)


if __name__ == '__main__':
    main()
