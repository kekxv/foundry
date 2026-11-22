"""Create a platform release artifact, without credentials or signing keys."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

from publish_catalogue import package_base_url

ROOT = Path(__file__).resolve().parents[1]
version = os.environ['VERSION']
platform = os.environ['PLATFORM']
repository = os.environ['RELEASE_REPOSITORY']
out = ROOT / 'dist/release'
out.mkdir(parents=True, exist_ok=True)
base = package_base_url(repository)
command = [
    sys.executable,
    str(ROOT / 'scripts/build_extensions.py'), '--out',
    str(ROOT / 'dist/packages'), '--profile', 'release', '--base-url', base
]
if os.environ.get('PREVIOUS_INDEX'):
    command += ['--previous-index', os.environ['PREVIOUS_INDEX']]
subprocess.run(command, check=True)
for source in (ROOT / 'dist/packages').glob('*.zip'):
    shutil.copy2(source, out / source.name)
shutil.copy2(ROOT / 'dist/packages/candidates.json', out / 'candidates.json')
suffix = '.exe' if platform.startswith('windows') else ''
filename = f'foundry-{version}-{platform}.zip'
with zipfile.ZipFile(out / filename, 'w',
                     compression=zipfile.ZIP_DEFLATED) as archive:
    for binary in ['foundry', 'foundry-worker']:
        source = ROOT / 'target/release' / (binary + suffix)
        info = zipfile.ZipInfo(binary + suffix)
        info.external_attr = 0o100755 << 16
        archive.writestr(info,
                         source.read_bytes(),
                         compress_type=zipfile.ZIP_DEFLATED)
    archive.write(ROOT / 'README.md', 'README.md')
    archive.write(ROOT / 'LICENSE', 'LICENSE')
    archive.write(ROOT / 'dist/history/root.json', 'trust-root.json')
files = {
    p.name: {
        'size': p.stat().st_size,
        'sha256': hashlib.sha256(p.read_bytes()).hexdigest()
    } for p in out.glob('*.zip')
}
(out / 'assets.json').write_text(json.dumps(files, indent=2))
