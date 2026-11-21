#!/usr/bin/env python3
"""Build versioned native artifacts on CI, then pack ready-to-use extensions."""
import argparse
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile

from registry import MAX_PACKAGE_BYTES
from registry import published_packages
from registry import Registry
from registry import safe_environment
from registry import within

ROOT = Path(__file__).resolve().parents[1]


def check_external_size(url):
    curl = 'curl.exe' if os.name == 'nt' else 'curl'
    result = subprocess.run([
        curl,
        '-q',
        '--head',
        '--silent',
        '--show-error',
        '--fail',
        '--location',
        '--max-redirs',
        '5',
        '--proto',
        '=https',
        '--proto-redir',
        '=https',
        '--globoff',
        '--max-time',
        '20',
        '--',
        url,
    ],
                            env=safe_environment(),
                            capture_output=True,
                            text=True,
                            encoding='latin-1',
                            timeout=25)
    if result.returncode:
        raise ValueError(
            f'external ZIP size check failed (curl exit {result.returncode})')
    # Redirects and proxies can return multiple header blocks.
    final = re.split(r'\r?\n\r?\n', result.stdout.strip())[-1].splitlines()
    if not final or not re.fullmatch(r'HTTP/\S+ 200(?: .*)?', final[0]):
        raise ValueError('external ZIP size check requires HTTP 200')
    lengths = [
        line.partition(':')[2].strip()
        for line in final[1:]
        if line.partition(':')[0].lower() == 'content-length'
    ]
    if len(lengths) != 1 or not re.fullmatch(r'[0-9]{1,20}', lengths[0]):
        raise ValueError('external ZIP must report a single Content-Length')
    length = int(lengths[0])
    if length > MAX_PACKAGE_BYTES:
        raise ValueError('external ZIP exceeds the 250 MiB size limit')
    if length == 0:
        raise ValueError('external ZIP is empty')
    return length


def host_platform():
    return {
        'Windows': 'windows',
        'Darwin': 'macos',
        'Linux': 'linux'
    }[platform.system()] + '-' + {
        'x86_64': 'x64',
        'AMD64': 'x64',
        'aarch64': 'arm64',
        'arm64': 'arm64'
    }[platform.machine()]


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--out', type=Path, default=ROOT / 'dist')
    p.add_argument('--profile',
                   default=os.environ.get('FOUNDRY_PROFILE', 'debug'),
                   choices=['debug', 'release'])
    p.add_argument('--base-url')
    p.add_argument('--extension')
    p.add_argument('--version')
    p.add_argument('--retain-external-for-scan', action='store_true')
    p.add_argument(
        '--previous-index',
        type=Path,
        help=
        'Previously verified signed index; reuse immutable published artifacts')
    a = p.parse_args()
    if a.version and not a.extension:
        p.error('--version requires --extension')
    registry = Registry(ROOT)
    target = host_platform()
    suffix = '.exe' if os.name == 'nt' else ''
    release = ROOT / 'target' / a.profile / ('foundry-release' + suffix)
    substitutions = {
        'exe':
            suffix,
        'library_prefix':
            '' if os.name == 'nt' else 'lib',
        'library_suffix':
            '.dll' if os.name == 'nt' else
            '.dylib' if platform.system() == 'Darwin' else '.so'
    }
    out = a.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    candidates = []
    previous = published_packages(json.loads(
        a.previous_index.read_text())) if a.previous_index else []
    published = {(x['id'], x['version'], x['platform']): x for x in previous}
    for id in [a.extension] if a.extension else registry.names():
        versions = [a.version] if a.version else registry.versions(id)
        for version in versions:
            source = registry.source(id, version)
            m = registry.manifest(id, version)
            c = registry.config(id, version)
            package_platform = 'any' if m['type'] == 'javascript' else target
            if target not in c['matrix']['platform']:
                continue
            key = (id, version, package_platform)
            external = registry.external_packages(id, version)
            candidate = None
            if external:
                candidate = dict(id=id,
                                 version=version,
                                 platform=package_platform,
                                 **external[package_platform])
            if key in published:
                if candidate is not None and any(
                        published[key].get(field) != value
                        for field, value in candidate.items()):
                    raise ValueError(
                        'published external ZIP metadata is immutable')
                candidates.append(published[key])
                continue
            stage = out / 'versions' / id / version
            if stage.exists():
                shutil.rmtree(stage)
            if candidate is not None:
                candidate['size'] = check_external_size(candidate['url'])
                with tempfile.TemporaryDirectory() as directory:
                    record = Path(directory) / 'package.json'
                    record.write_text(json.dumps(candidate), encoding='utf-8')
                    command = [
                        str(release),
                        'prepare-external',
                        '--package',
                        str(record),
                        '--manifest',
                        str(within(source, 'manifest.json')),
                        '--output',
                        str(stage),
                    ]
                    if a.retain_external_for_scan:
                        scan_dir = out / 'external-scan'
                        scan_dir.mkdir(exist_ok=True)
                        archive = scan_dir / f'{id}-{version}-{package_platform}.zip'
                        command.extend(['--scan-archive', str(archive)])
                    subprocess.run(command,
                                   check=True,
                                   env=safe_environment(),
                                   timeout=120)
                candidates.append(candidate)
                update_dev_alias(registry, out, id, version, stage)
                continue
            stage.mkdir(parents=True)
            shutil.copy2(within(source, 'manifest.json'),
                         stage / 'manifest.json')
            for js in source.rglob('*.js'):
                rel = js.relative_to(source).as_posix()
                if rel.startswith('native/'):
                    continue
                js = within(source, rel)
                dest = stage / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(js, dest)
            if 'build' in c:
                b = c['build']
                build_dir = ROOT / 'target/extensions' / id / version
                cmd = [
                    'cargo', 'build', '--locked', '--manifest-path',
                    str(within(source, b['cargo_manifest'])), '--target-dir',
                    str(build_dir)
                ]
                if a.profile == 'release':
                    cmd.append('--release')
                subprocess.run(cmd,
                               check=True,
                               env=safe_environment(),
                               timeout=900)
                for artifact in b['artifacts']:
                    src = within(build_dir / a.profile,
                                 artifact['from'].format(**substitutions))
                    dest = within(stage, artifact['to'].format(**substitutions))
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)
            # Compatibility alias for local development; distribution keeps every version.
            update_dev_alias(registry, out, id, version, stage)
            filename = f'{id}-{version}-{package_platform}.zip'
            result = subprocess.run([
                str(release), 'pack', '--source',
                str(stage), '--output',
                str(out / filename), '--platform', package_platform
            ],
                                    check=True,
                                    capture_output=True,
                                    text=True,
                                    env=safe_environment(),
                                    timeout=60)
            candidate = json.loads(result.stdout)
            candidate.pop('file')
            candidate['url'] = a.base_url.rstrip(
                '/') + '/' + filename if a.base_url else str(out / filename)
            candidates.append(candidate)
    (out /
     'candidates.json').write_text(json.dumps(candidates, indent=2) + '\n')
    print(f'Prepared {len(candidates)} extension versions for {target}: {out}')


def update_dev_alias(registry, out, id, version, stage):
    if registry.versions(id)[-1:] == [version]:
        alias = out / 'dev' / id
        if alias.exists():
            shutil.rmtree(alias)
        shutil.copytree(stage, alias)


if __name__ == '__main__':
    main()
