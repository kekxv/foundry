"""Publish signed registry atomically with the website, never rebuild signed bytes."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

root = Path('trust/root.json')
if not root.exists():
    print(
        'No production trust root configured; build documentation without a registry.'
    )
    raise SystemExit(0)
releases = json.loads(
    subprocess.run(
        ['gh', 'api', f'repos/{os.environ["GH_REPO"]}/releases?per_page=100'],
        capture_output=True,
        text=True,
        check=True).stdout)
published = [r for r in releases if not r['draft'] and not r['prerelease']]
if not published:
    print('No release yet; build documentation without a registry.')
    raise SystemExit(0)
with tempfile.TemporaryDirectory() as d:
    subprocess.run([
        'gh', 'release', 'download', published[0]['tag_name'], '--pattern',
        'index.json', '--pattern', 'index.json.sig', '--dir', d
    ],
                   check=True)
    subprocess.run([
        'cargo', 'run', '--release', '--locked', '-p', 'foundry-release', '--',
        'verify', '--input', f'{d}/index.json', '--signature',
        f'{d}/index.json.sig', '--root',
        str(root)
    ],
                   check=True)
    out = Path('website/public/registry')
    out.mkdir(parents=True, exist_ok=True)
    for name in ['index.json', 'index.json.sig']:
        shutil.copy2(Path(d, name), out / name)
    shutil.copy2(root, out / 'root.json')
