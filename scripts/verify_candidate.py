"""Validate candidate bytes inside signing job; executes no candidate content."""
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import unquote
from urllib.parse import urlparse

root = Path('dist/approved')
path = root / 'release-manifest.json'
assert hashlib.sha256(path.read_bytes()).hexdigest(
) == os.environ['EXPECTED_MANIFEST_SHA256'], 'Candidate changed after assembly'
m = json.loads(path.read_text())
assert m['schemaVersion'] == 1 and m['sourceCommit'] == os.environ[
    'SOURCE_COMMIT'] and m['version'] == os.environ['VERSION'] and m[
        'sequence'] == int(os.environ['SEQUENCE']), 'Wrong approval binding'
assert {
    p.name for p in root.iterdir()
} == set(m['assets']) | {'release-manifest.json'}, 'Unexpected candidate files'
for name, record in m['assets'].items():
    assert Path(name).name == name and not (
        root / name).is_symlink(), 'Unsafe asset path'
    p = root / name
    assert p.stat().st_size == record['size'] and hashlib.sha256(
        p.read_bytes()).hexdigest() == record['sha256'], 'Asset changed'
index = json.loads((root / 'index.json').read_text())
assert index['sequence'] == m['sequence'] and index['sourceCommit'] == m[
    'sourceCommit'], 'Wrong index binding'
from registry import published_packages
from registry import Registry

registry = Registry(Path(__file__).resolve().parents[1])
expected = set()
for id in registry.names():
    for version in registry.versions(id):
        manifest = registry.manifest(id, version)
        for platform in manifest['platforms']:
            expected.add((id, version, platform))
assert {(p['id'], p['version'], p['platform']) for p in index['packages']
       } == expected, 'Incomplete version/platform coverage'
previous = {}
if os.environ.get('PREVIOUS_INDEX'):
    history = Path(os.environ['PREVIOUS_INDEX']).read_bytes()
    assert hashlib.sha256(history).hexdigest(
    ) == os.environ['EXPECTED_PREVIOUS_SHA256'], 'History binding mismatch'
    previous = {
        (p['id'], p['version'], p['platform']): p
        for p in published_packages(json.loads(history))
    }
ledger = published_packages(index)
assert set(previous) | expected == {
    (p['id'], p['version'], p['platform']) for p in ledger
}, 'Published history removed or unexpected records added'
for p in ledger:
    key = (p['id'], p['version'], p['platform'])
    if key in previous:
        assert p == previous[key], 'Published package changed'
        continue
    u = urlparse(p['url'])
    assert u.scheme == 'https' and u.netloc == 'github.com', 'Untrusted asset origin'
    prefix = f'/{os.environ["GITHUB_REPOSITORY"]}/releases/download/v{m["version"]}/'
    assert u.path.startswith(
        prefix) and not u.query and not u.fragment, 'Wrong release URL'
    name = unquote(u.path[len(prefix):])
    assert '/' not in name and name in m['assets'], 'Missing release asset'
    assert m['assets'][name] == {
        'size': p['size'],
        'sha256': p['sha256']
    }, 'Index digest mismatch'
print(
    'Approved commit, manifest digest, platforms and all asset bytes verified.')
