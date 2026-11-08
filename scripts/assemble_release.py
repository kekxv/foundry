"""Assemble candidate data for approval. Never execute downloaded binaries."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import time

from registry import merge_packages
from registry import partition_packages
from registry import published_packages
from registry import Registry

ROOT = Path(__file__).resolve().parents[1]

source = Path('candidate')
out = Path('dist/approved')
out.mkdir(parents=True, exist_ok=True)
packages = {}
assets = {}
for directory in sorted(source.iterdir()):
    if not directory.is_dir():
        continue
    for p in json.loads((directory / 'candidates.json').read_text()):
        key = (p['id'], p['version'], p['platform'])
        if key in packages:
            assert packages[key] == p, 'Conflicting candidate'
        packages[key] = p
    declared = json.loads((directory / 'assets.json').read_text())
    for name, record in declared.items():
        assert Path(name).name == name and name.endswith(
            '.zip'), 'Invalid asset name'
        p = directory / name
        assert p.is_file() and not p.is_symlink(), 'Missing or linked asset'
        assert p.stat().st_size == record['size'] and hashlib.sha256(
            p.read_bytes()).hexdigest(
            ) == record['sha256'], 'Asset digest mismatch'
        if name in assets:
            assert assets[name] == record, 'Conflicting duplicate asset'
        assets[name] = record
        shutil.copy2(p, out / name)
previous = []
if os.environ.get('PREVIOUS_INDEX'):
    history = Path(os.environ['PREVIOUS_INDEX']).read_bytes()
    assert hashlib.sha256(history).hexdigest(
    ) == os.environ['EXPECTED_PREVIOUS_SHA256'], 'History binding mismatch'
    previous = published_packages(json.loads(history))
registry = Registry(ROOT)
active = {(id, v) for id in registry.names() for v in registry.versions(id)}
merged, withdrawn = partition_packages(
    merge_packages(previous, list(packages.values())), active)
index = {
    'schemaVersion': 1,
    'sequence': int(os.environ['SEQUENCE']),
    'expiresAt': int(time.time()) + 30 * 86400,
    'sourceCommit': os.environ['SOURCE_COMMIT'],
    'packages': merged,
    'withdrawnPackages': withdrawn
}
(out / 'index.json').write_text(json.dumps(index, indent=2) + '\n')
assets['index.json'] = {
    'size': (out / 'index.json').stat().st_size,
    'sha256': hashlib.sha256((out / 'index.json').read_bytes()).hexdigest()
}
manifest = {
    'schemaVersion': 1,
    'sourceCommit': os.environ['SOURCE_COMMIT'],
    'version': os.environ['VERSION'],
    'sequence': int(os.environ['SEQUENCE']),
    'assets': assets
}
path = out / 'release-manifest.json'
path.write_text(json.dumps(manifest, indent=2) + '\n')
sha = hashlib.sha256(path.read_bytes()).hexdigest()
with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
    f.write('sha256=' + sha + '\n')
with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
    f.write(
        f'## Candidate for signing approval\n\nCommit: `{manifest["sourceCommit"]}`\n\nManifest SHA-256: `{sha}`\n\nIndex sequence: {manifest["sequence"]}\n\nReview this fixed candidate before approving release-signing.\n'
    )
