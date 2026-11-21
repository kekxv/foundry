"""Versioned extension registry. Configuration is data, never shell source."""
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
from urllib.parse import urlsplit

import yaml

MAX_PACKAGE_BYTES = 250 * 1024**2

RUNNERS = {
    'linux-x64': 'ubuntu-22.04',
    'linux-arm64': 'ubuntu-24.04-arm',
    'macos-arm64': 'macos-15',
    'windows-x64': 'windows-2022'
}


def name(value):
    if not isinstance(value, str) or not re.fullmatch(
            r'[a-z0-9][a-z0-9-]{0,63}', value):
        raise ValueError('invalid extension ID')
    return value


def version_key(value):
    if not isinstance(value, str) or not re.fullmatch(
            r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', value):
        raise ValueError('registry requires stable SemVer x.y.z')
    return tuple(map(int, value.split('.')))


def relative(value):
    if not isinstance(value, str) or not value or any(
            c in value for c in '\\:\0\n\r') or any(
                p in ('', '.', '..') for p in value.split('/')
            ) or PurePosixPath(value).is_absolute():
        raise ValueError('invalid relative path')
    return value


def within(root, rel):
    relative(rel)
    root = Path(root).resolve()
    p = root
    for part in rel.split('/'):
        p = p / part
        if p.is_symlink():
            raise ValueError('registry symlinks forbidden')
    if not p.resolve().is_relative_to(root):
        raise ValueError('registry path escapes root')
    return p


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate configuration key')
        result[key] = value
    return result


def read_json(p):
    if p.stat().st_size > 1024 * 1024:
        raise ValueError('configuration too large')
    return json.loads(p.read_text(encoding='utf-8'), object_pairs_hook=unique)


class StrictLoader(yaml.SafeLoader):
    pass


def yaml_mapping(loader, node, deep=False):
    return unique([(loader.construct_object(k, deep=True),
                    loader.construct_object(v, deep=True))
                   for k, v in node.value])


StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
                             yaml_mapping)


def read_yaml(path):
    if path.stat().st_size > 1024 * 1024:
        raise ValueError('configuration too large')
    text = path.read_text(encoding='utf-8')
    try:
        for t in yaml.scan(text):
            if isinstance(t, (yaml.tokens.AnchorToken, yaml.tokens.AliasToken)):
                raise ValueError('YAML anchors/aliases forbidden')
        return yaml.load(text, Loader=StrictLoader)
    except (yaml.YAMLError, TypeError) as e:
        raise ValueError('invalid presubmit YAML') from e


def fields(obj, allowed, required=()):
    if not isinstance(
            obj,
            dict) or set(obj) - set(allowed) or not set(required) <= set(obj):
        raise ValueError('invalid configuration fields')


class Registry:

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.directory = self.root / 'extensions'
        if self.directory.is_symlink():
            raise ValueError('symlink registry forbidden')

    def names(self):
        result = []
        for p in self.directory.iterdir():
            if p.is_symlink():
                raise ValueError('symlink extension')
            if p.is_dir():
                name(p.name)
                result.append(p.name)
        return sorted(result)

    def metadata(self, id):
        name(id)
        m = read_json(within(self.directory, f'{id}/metadata.json'))
        fields(m,
               ('id', 'versions', 'yanked_versions', 'maintainers', 'homepage'),
               ('id', 'versions', 'yanked_versions'))
        if m['id'] != id or not isinstance(
                m['versions'], list) or not m['versions'] or len(
                    m['versions']) != len(set(m['versions'])):
            raise ValueError('invalid version list')
        for v in m['versions']:
            version_key(v)
        if not isinstance(m['yanked_versions'], dict) or not set(
                m['yanked_versions']) <= set(m['versions']) or not all(
                    isinstance(s, str) and s
                    for s in m['yanked_versions'].values()):
            raise ValueError('invalid yanked versions')
        actual = {p.name for p in (self.directory / id).iterdir() if p.is_dir()}
        if actual != set(m['versions']):
            raise ValueError('version directories must exactly match metadata')
        for v in m['versions']:
            within(self.directory, f'{id}/{v}')
        return m

    def versions(self, id, include_yanked=False):
        m = self.metadata(id)
        return sorted([
            v for v in m['versions']
            if include_yanked or v not in m['yanked_versions']
        ],
                      key=version_key)

    def source(self, id, version):
        name(id)
        version_key(version)
        if version not in self.versions(id, True):
            raise ValueError('unknown version')
        return within(self.directory, f'{id}/{version}')

    def manifest(self, id, version):
        m = read_json(within(self.source(id, version), 'manifest.json'))
        if m['id'] != id or m['version'] != version:
            raise ValueError('manifest identity/version mismatch')
        return m

    def external_packages(self, id, version):
        source = self.source(id, version)
        yaml_path = within(source, 'packages.yaml')
        legacy_path = within(source, 'packages.json')
        if yaml_path.exists() and legacy_path.exists():
            raise ValueError('use only one of packages.yaml and packages.json')
        if yaml_path.exists():
            records = read_yaml(yaml_path)
        elif legacy_path.exists():
            records = read_json(legacy_path)
        else:
            return {}
        manifest = self.manifest(id, version)
        platforms = manifest['platforms']
        supported = {'any'
                    } if manifest['type'] == 'javascript' else set(RUNNERS)
        if (not platforms or not set(platforms) <= supported or
                not isinstance(records, dict) or
                set(records) != set(platforms)):
            raise ValueError('external ZIPs must cover all declared platforms')
        for record in records.values():
            fields(record, ('url', 'sha256', 'size'), ('url', 'sha256'))
            url = record['url']
            if (not isinstance(url, str) or not url.startswith('https://') or
                    len(url) > 2048 or
                    any(not 33 <= ord(c) <= 126 or c in '#\\' for c in url)):
                raise ValueError('external ZIP URL must use HTTPS')
            parsed = urlsplit(url)
            if not parsed.hostname or parsed.username is not None:
                raise ValueError(
                    'external ZIP URL must have a host and no credentials')
            if (not isinstance(record['sha256'], str) or
                    not re.fullmatch(r'[0-9a-f]{64}', record['sha256'])):
                raise ValueError('external ZIP requires lowercase SHA-256')
            if 'size' in record and (type(record['size']) is not int or
                                     record['size'] <= 0):
                raise ValueError(
                    'external ZIP size estimate must be a positive integer')
        return {
            platform: {
                'url': record['url'],
                'sha256': record['sha256']
            } for platform, record in records.items()
        }

    def config(self, id, version):
        source = self.source(id, version)
        m = self.manifest(id, version)
        c = read_yaml(within(source, 'presubmit.yml'))
        fields(c, ('matrix', 'build', 'tasks'), ('matrix', 'tasks'))
        fields(c['matrix'], ('platform',), ('platform',))
        platforms = c['matrix']['platform']
        if not isinstance(
                platforms, list) or not platforms or len(platforms) != len(
                    set(platforms)) or not set(platforms) <= set(RUNNERS):
            raise ValueError('unsupported runner/platform')
        if 'any' not in m['platforms'] and set(platforms) != set(
                m['platforms']):
            raise ValueError(
                'presubmit must cover all declared native platforms')
        b = c.get('build')
        if self.external_packages(id, version) and 'build' in c:
            raise ValueError('external ZIPs cannot declare a local build')
        if b is not None:
            fields(b, ('cargo_manifest', 'artifacts'),
                   ('cargo_manifest', 'artifacts'))
            within(source, b['cargo_manifest'])
            if not isinstance(b['artifacts'], list) or not b['artifacts']:
                raise ValueError('missing build artifacts')
            for a in b['artifacts']:
                fields(a, ('from', 'to'), ('from', 'to'))
                for s in a.values():
                    relative(s)
        if not isinstance(c['tasks'], dict) or not 1 <= len(c['tasks']) <= 32:
            raise ValueError('invalid test tasks')
        for key, task in c['tasks'].items():
            name(key)
            fields(task, ('capability', 'input', 'expect'),
                   ('capability', 'input', 'expect'))
            if task['capability'] not in m['capabilities']:
                raise ValueError('undeclared test capability')
            json.dumps(task, allow_nan=False)
        return c

    def all_pairs(self):
        return [(id, v) for id in self.names() for v in self.versions(id, True)]

    def affected(self, paths):
        pairs = set()
        for path in paths:
            if path.startswith(
                ('tools/', 'crates/', 'scripts/', 'schemas/',
                 '.github/workflows/')) or path in ('.gitattributes',
                                                    'Cargo.toml', 'Cargo.lock',
                                                    'rust-toolchain.toml',
                                                    'requirements-ci.txt'):
                return self.all_pairs()
            parts = path.split('/')
            if len(parts) >= 3 and parts[0] == 'extensions':
                id = name(parts[1])
                if len(parts) >= 4:
                    version = parts[2]
                    self.source(id, version)
                    pairs.add((id, version))
                else:
                    pairs.update((id, v) for v in self.versions(id, True))
        return sorted(pairs)

    def check_immutable(self, paths, previous):
        for path in paths:
            parts = path.split('/')
            if len(parts) >= 4 and parts[0] == 'extensions' and parts[
                    2] in previous.get(parts[1], []):
                raise ValueError(
                    'existing version is immutable; add a new version or yank it'
                )
        for id, versions in previous.items():
            if not set(versions) <= set(self.versions(id, True)):
                raise ValueError('existing versions cannot be removed')


def merge_packages(previous, current):
    merged = {(p['id'], p['version'], p['platform']): p for p in previous}
    for p in current:
        key = p['id'], p['version'], p['platform']
        if key in merged:
            old = merged[key]
            if (old['sha256'], old['size']) != (p['sha256'], p['size']):
                raise ValueError('published package is immutable')
            continue  # Preserve original immutable URL too.
        merged[key] = p
    return list(merged.values())


def safe_environment(source=None):
    source = os.environ if source is None else source
    allow = {
        'PATH', 'HOME', 'USERPROFILE', 'HOMEDRIVE', 'HOMEPATH', 'TMP', 'TEMP',
        'TMPDIR', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'INCLUDE',
        'LIB', 'LIBPATH', 'CARGO_HOME', 'RUSTUP_HOME', 'NUMBER_OF_PROCESSORS',
        'PROCESSOR_ARCHITECTURE', 'PROGRAMFILES', 'PROGRAMFILES(X86)', 'LANG',
        'LC_ALL', 'SDKROOT', 'MACOSX_DEPLOYMENT_TARGET'
    }
    return {k: v for k, v in source.items() if k.upper() in allow}


def published_packages(index):
    """Append-only signed ledger, including packages unavailable for installation."""
    return merge_packages(index.get('withdrawnPackages', []), index['packages'])


def partition_packages(packages, active):
    return ([p for p in packages if (p['id'], p['version']) in active],
            [p for p in packages if (p['id'], p['version']) not in active])
