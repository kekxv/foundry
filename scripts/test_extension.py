#!/usr/bin/env python3
"""Run one version's declarative presubmit with a credential-free child environment."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from build_extensions import host_platform
from registry import Registry
from registry import safe_environment

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--extension', required=True)
    p.add_argument('--version')
    p.add_argument('--platform', required=True)
    a = p.parse_args()
    r = Registry(ROOT)
    version = a.version or r.versions(a.extension)[-1]
    config = r.config(a.extension, version)
    manifest = r.manifest(a.extension, version)
    if a.platform != host_platform(
    ) or a.platform not in config['matrix']['platform']:
        raise ValueError('test runner does not match declared platform')
    profile = os.environ.get('FOUNDRY_PROFILE', 'debug')
    suffix = '.exe' if os.name == 'nt' else ''
    env = safe_environment()
    with tempfile.TemporaryDirectory(prefix='foundry-presubmit-') as directory:
        d = Path(directory)
        out = d / 'packages'
        fixture = d / 'fixture 文件.txt'
        fixture.write_bytes(b'abc')
        subprocess.run([
            sys.executable,
            str(ROOT / 'scripts/build_extensions.py'), '--out',
            str(out), '--profile', profile, '--extension', a.extension,
            '--version', version
        ],
                       check=True,
                       env=env,
                       timeout=1200)

        def resolve(value):
            if value == '$fixture':
                return str(fixture)
            if isinstance(value, dict):
                return {k: resolve(v) for k, v in value.items()}
            if isinstance(value, list):
                return [resolve(v) for v in value]
            return value

        for task_id, task in config['tasks'].items():
            cmd = [
                str(ROOT / 'target' / profile / ('foundry' + suffix)),
                '--data-dir',
                str(d / 'state'), 'dev', 'run',
                str(out / 'versions' / a.extension / version),
                task['capability'], '--input',
                json.dumps(resolve(task['input']))
            ]
            for grant in manifest['permissions']:
                cmd += ['--grant', grant]
            result = subprocess.run(cmd,
                                    check=True,
                                    env=env,
                                    capture_output=True,
                                    text=True,
                                    encoding="utf-8",
                                    timeout=60)
            actual = json.loads(result.stdout)
            if actual != task['expect']:
                raise AssertionError(
                    f'{task_id}: {actual!r} != {task["expect"]!r}')
            print(
                json.dumps({
                    'extension': a.extension,
                    'version': version,
                    'platform': a.platform,
                    'task': task_id,
                    'result': actual
                }))


if __name__ == '__main__':
    main()
