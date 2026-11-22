"""Publish the initial trust root or preserve the authenticated historical root."""
import json
from pathlib import Path
import shutil


def prepare_public_root(derived, previous, output):
    source = derived
    if previous.is_file():
        candidate = json.loads(derived.read_bytes())
        existing = json.loads(previous.read_bytes())
        if (existing['keys'] != candidate['keys'] or
                existing['threshold'] != candidate['threshold']):
            raise ValueError(
                'Signing key does not match the published trust root')
        source = previous
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, output)


if __name__ == '__main__':
    prepare_public_root(Path('derived-root.json'),
                        Path('dist/history/root.json'),
                        Path('public/root.json'))
