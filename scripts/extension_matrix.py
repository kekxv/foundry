#!/usr/bin/env python3
"""Trusted-base planner: parse candidate configuration as data, never execute it."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

from registry import Registry
from registry import RUNNERS

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, default=ROOT)
    p.add_argument('--base')
    p.add_argument('--extension')
    p.add_argument('--version')
    a = p.parse_args()
    r = Registry(a.root)
    if a.version and not a.extension:
        p.error('--version requires --extension')
    pairs = r.all_pairs()
    if a.base:
        if not re.fullmatch('[0-9a-f]{40,64}', a.base):
            raise ValueError('full base commit SHA required')

        def git(*args):
            return subprocess.run(['git', '-C', str(r.root), *args],
                                  check=True,
                                  capture_output=True,
                                  text=True).stdout

        paths = git('diff', '--name-only', '--no-renames', '-z', a.base,
                    'HEAD').strip('\0').split('\0')
        paths = [s for s in paths if s]
        previous = {}
        for path in git('ls-tree', '-r', '--name-only', a.base, '--',
                        'extensions').splitlines():
            if re.fullmatch(r'extensions/[a-z0-9-]+/metadata.json', path):
                previous[path.split('/')[1]] = json.loads(
                    git('show', f'{a.base}:{path}'))['versions']
        r.check_immutable(paths, previous)
        pairs = r.affected(paths)
    if a.extension:
        versions = [a.version] if a.version else r.versions(a.extension, True)
        pairs = [(a.extension, v) for v in versions]
    entries = []
    for id, version in pairs:
        for platform in r.config(id, version)['matrix']['platform']:
            entries.append(
                dict(extension=id,
                     version=version,
                     platform=platform,
                     runner=RUNNERS[platform]))
    if len(entries) > 256:
        raise ValueError('extension matrix exceeds GitHub limit of 256 jobs')
    matrix = {'include': entries}
    encoded = json.dumps(matrix, separators=(',', ':'))
    print(json.dumps(matrix, indent=2))
    if 'GITHUB_OUTPUT' in os.environ:
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
            output.write(
                f'matrix={encoded}\nhas_changes={str(bool(entries)).lower()}\n')


if __name__ == '__main__':
    main()
