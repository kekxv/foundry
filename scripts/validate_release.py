"""Run on the protected default branch only. No signing credentials needed."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import tomllib

from pages_registry import checkout_pages
from pages_registry import FILES

version = os.environ['VERSION']
sequence = os.environ['SEQUENCE']
assert re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',
                    version), 'Stable SemVer required'
assert sequence.isdigit() and int(sequence) > 0, 'Positive sequence required'
assert tomllib.loads(Path('Cargo.toml').read_text(
))['workspace']['package']['version'] == version, 'Client version mismatch'
releases = subprocess.check_output([
    'gh', 'api', '--paginate', '--jq',
    '.[] | {tag_name, published: (.draft == false and .prerelease == false)}',
    f'repos/{os.environ["GH_REPO"]}/releases'
],
                                   text=True)
releases = [json.loads(line) for line in releases.splitlines()]
if any(release['tag_name'] == f'v{version}' for release in releases):
    raise ValueError('Client release version already exists')
if subprocess.check_output(
    ['git', 'ls-remote', '--tags', 'origin', f'refs/tags/v{version}']):
    raise ValueError('Client release tag already exists')
history = Path('dist/history')
history.mkdir(parents=True, exist_ok=True)
old = {'packages': []}
first_release = True
root = history / 'root.json'
with tempfile.TemporaryDirectory(prefix='foundry-pages-history-') as d:
    deployed = checkout_pages(Path(d))
    existing = {name for name in FILES if (deployed / name).is_file()}
    if existing:
        if existing != set(FILES):
            raise ValueError('Pages registry is missing signed metadata')
        shutil.copyfile(deployed / 'root.json', root)
        subprocess.run([
            'cargo',
            'run',
            '--release',
            '--locked',
            '-p',
            'foundry-release',
            '--',
            'verify',
            '--input',
            str(deployed / 'index.json'),
            '--signature',
            str(deployed / 'index.json.sig'),
            '--root',
            str(root),
            '--allow-expired',
        ],
                       check=True)
        old = json.loads((deployed / 'index.json').read_bytes())
        first_release = False
        if int(sequence) <= old['sequence']:
            raise ValueError('Index sequence must increase')
    elif any(release['published'] for release in releases):
        raise ValueError(
            'Restore the signed registry history on gh-pages before publishing')
    elif Path('trust/root.json').is_file():
        shutil.copyfile('trust/root.json', root)
(history / 'index.json').write_text(json.dumps(old))
with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
    stream.write('history_sha256=' +
                 hashlib.sha256((history /
                                 'index.json').read_bytes()).hexdigest() + '\n')
    stream.write(f'version={version}\nsequence={int(sequence)}\n')
    stream.write(f'first_release={str(first_release).lower()}\n')
