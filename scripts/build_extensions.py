#!/usr/bin/env python3
"""Build versioned native artifacts on CI, then pack ready-to-use extensions."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess

from registry import published_packages
from registry import Registry
from registry import safe_environment
from registry import within

ROOT = Path(__file__).resolve().parents[1]


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
            if key in published:
                candidates.append(published[key])
                continue
            stage = out / 'versions' / id / version
            if stage.exists():
                shutil.rmtree(stage)
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
            if registry.versions(id) and version == registry.versions(id)[-1]:
                alias = out / 'dev' / id
                if alias.exists():
                    shutil.rmtree(alias)
                shutil.copytree(stage, alias)
            filename = f'{id}-{version}-{package_platform}.zip'
            result = subprocess.run([
                str(ROOT / 'target' / a.profile /
                    ('foundry-release' + suffix)), 'pack', '--source',
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


if __name__ == '__main__':
    main()
