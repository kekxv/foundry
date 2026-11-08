"""Run on the protected default branch only. No signing credentials needed."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import tomllib

version = os.environ['VERSION']
sequence = os.environ['SEQUENCE']
assert re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',
                    version), 'Stable SemVer required'
assert sequence.isdigit() and int(sequence) > 0, 'Positive sequence required'
assert tomllib.loads(Path('Cargo.toml').read_text(
))['workspace']['package']['version'] == version, 'Client version mismatch'
assert Path('trust/root.json').is_file(
), 'Configure production trust/root.json before publishing'
# Authentication, permission and transport errors must not be mistaken for an empty registry.
listing = subprocess.run(
    ['gh', 'api', f'repos/{os.environ["GH_REPO"]}/releases?per_page=100'],
    capture_output=True,
    text=True,
    check=True)
releases = json.loads(listing.stdout)
assert all(
    r['tag_name'] != 'v' + version for r in releases), 'Version already exists'
published = [r for r in releases if not r['draft'] and not r['prerelease']]
history = Path('dist/history')
history.mkdir(parents=True, exist_ok=True)
old = {'packages': []}
if published:
    with tempfile.TemporaryDirectory() as d:
        tag = published[0]['tag_name']
        subprocess.run([
            'gh', 'release', 'download', tag, '--pattern', 'index.json',
            '--pattern', 'index.json.sig', '--dir', d
        ],
                       check=True)
        subprocess.run([
            'cargo', 'run', '--release', '--locked', '-p', 'foundry-release',
            '--', 'verify', '--input', f'{d}/index.json', '--signature',
            f'{d}/index.json.sig', '--root', 'trust/root.json',
            '--allow-expired'
        ],
                       check=True)
        old = json.loads(Path(d, 'index.json').read_text())
        assert int(sequence) > old['sequence'], 'Index sequence must increase'
(history / 'index.json').write_text(json.dumps(old))
with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
    stream.write('history_sha256=' +
                 hashlib.sha256((history /
                                 'index.json').read_bytes()).hexdigest() + '\n')
    stream.write(f'version={version}\nsequence={int(sequence)}\n')
