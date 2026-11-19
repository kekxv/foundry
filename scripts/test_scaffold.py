#!/usr/bin/env python3
"""Create, package, install, and run all three Foundry extension templates."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from build_extensions import host_platform
from registry import Registry
from registry import RUNNERS
from registry import safe_environment

ROOT = Path(__file__).resolve().parents[1]
VERSION = '1.2.3'
KEY_ID = 'scaffold-test'
TEMPLATES = {
    'javascript': [],
    'executable': ['--grant', 'process.spawn'],
    'native-library': ['--grant', 'native.call'],
}


def run_test(platform, root):
    suffix = '.exe' if os.name == 'nt' else ''
    bin_dir = ROOT / 'target/debug'
    client = bin_dir / f'foundry{suffix}'
    release = bin_dir / f'foundry-release{suffix}'
    env = safe_environment()

    def run(*command,
            answers=None,
            extra_env=None,
            timeout=60,
            expected_error=None):
        result = subprocess.run([str(arg) for arg in command],
                                cwd=root,
                                env=env | (extra_env or {}),
                                input=answers,
                                capture_output=True,
                                encoding='utf-8',
                                timeout=timeout,
                                check=False)
        if expected_error is not None:
            if result.returncode == 1 and expected_error in result.stderr:
                return result.stdout
            raise AssertionError(
                f'{command} did not fail with {expected_error!r}\n'
                f'{result.stdout}{result.stderr}')
        if result.returncode:
            raise RuntimeError(f'{command} exited with {result.returncode}\n'
                               f'{result.stdout}{result.stderr}')
        return result.stdout

    # Use the real registry builder in an isolated registry so test extensions
    # never become candidates for the repository's publication.
    scripts = root / 'scripts'
    scripts.mkdir()
    for name in ('build_extensions.py', 'registry.py'):
        shutil.copy2(ROOT / 'scripts' / name, scripts / name)
    shutil.copy2(ROOT / 'rust-toolchain.toml', root)
    temp_bin_dir = root / 'target/debug'
    temp_bin_dir.mkdir(parents=True)
    shutil.copy2(release, temp_bin_dir)

    registry = Registry(root)
    for kind in TEMPLATES:
        extension = f'scaffold-{kind}'
        if kind == 'native-library':
            run(client,
                'new',
                '--interactive',
                answers=f'{extension}\n{kind}\n{VERSION}\n\n')
        else:
            run(client,
                'new',
                '--id',
                extension,
                '--type',
                kind,
                '--version',
                VERSION,
                '--output',
                root / 'extensions',
                answers='')
        config = registry.config(extension, VERSION)
        if set(config['matrix']['platform']) != set(RUNNERS):
            raise AssertionError(f'{extension} does not cover all CI platforms')

    packages = root / 'packages'
    print(
        run(sys.executable,
            scripts / 'build_extensions.py',
            '--out',
            packages,
            timeout=1200).strip())
    candidates = packages / 'candidates.json'
    built = json.loads(candidates.read_text(encoding='utf-8'))
    actual = [(item['id'], item['version'], item['platform']) for item in built]
    expected = [(f'scaffold-{kind}', VERSION,
                 'any' if kind == 'javascript' else platform)
                for kind in TEMPLATES]
    if sorted(actual) != sorted(expected):
        raise AssertionError(f'expected {expected}, built {actual}')

    index = root / 'index.json'
    private_key = root / 'scaffold.key'
    public_root = root / 'root.json'
    run(release, 'keygen', '--private-output', private_key, '--root-output',
        public_root, '--key-id', KEY_ID)
    run(release, 'build-index', '--candidates', candidates, '--sequence', 1,
        '--expires-at',
        int(time.time()) + 3600, '--source-commit', '0' * 40, '--output', index)
    run(release,
        'sign',
        '--input',
        index,
        '--output',
        index.with_suffix('.json.sig'),
        '--key-id',
        KEY_ID,
        extra_env={
            'FOUNDRY_SIGNING_KEY': private_key.read_text(encoding='utf-8')
        })

    isolated_client = temp_bin_dir / client.name
    shutil.copy2(client, isolated_client)
    cli = (isolated_client, '--data-dir', root / 'state', '--trust-root',
           public_root, '--index', index)
    for kind, grants in TEMPLATES.items():
        extension = f'scaffold-{kind}'
        run(*cli, 'install', extension, *grants)
        if grants:
            # A JS implementation of echo could otherwise hide a template
            # that never calls its packaged native code.
            run(*cli,
                'run',
                extension,
                'echo',
                '--input',
                '{"value":42}',
                expected_error='foundry-worker must be installed beside foundry'
               )

    shutil.copy2(bin_dir / f'foundry-worker{suffix}', temp_bin_dir)
    for kind in TEMPLATES:
        extension = f'scaffold-{kind}'
        tasks = registry.config(extension, VERSION)['tasks']
        for name, task in tasks.items():
            output = run(*cli, 'run', extension, task['capability'], '--input',
                         json.dumps(task['input']))
            actual = json.loads(output)
            if actual != task['expect']:
                raise AssertionError(
                    f'{extension}/{name}: {actual!r} != {task["expect"]!r}')
        print(f'{platform}: installed and ran {extension}@{VERSION}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--platform', required=True, choices=RUNNERS)
    args = parser.parse_args()
    if args.platform != host_platform():
        parser.error(f'expected {args.platform}, running on {host_platform()}')
    with tempfile.TemporaryDirectory(prefix='foundry-scaffold-') as directory:
        run_test(args.platform, Path(directory))


if __name__ == '__main__':
    main()
