"""Stage registry files from the deployed Git branch and signed build assets."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from publish_catalogue import package_base_url
from publish_catalogue import publish_catalogue

FILES = ('index.json', 'index.json.sig', 'root.json')
MAX_GIT_FILE_BYTES = 100 * 1024**2


def checkout_pages(directory):
    ref = 'refs/heads/gh-pages'
    lookup = subprocess.run(['git', 'ls-remote', '--exit-code', 'origin', ref],
                            capture_output=True,
                            text=True,
                            check=False)
    if lookup.returncode == 2:
        return directory / 'registry'
    lookup.check_returncode()
    commit = lookup.stdout.split()[0]
    subprocess.run(['git', 'fetch', '--depth=1', 'origin', commit], check=True)
    if subprocess.check_output(['git', 'ls-tree', commit, '--', 'registry']):
        subprocess.run([
            'git', '--work-tree',
            str(directory), 'restore', f'--source={commit}', '--worktree', '--',
            'registry'
        ],
                       check=True,
                       env=dict(os.environ,
                                GIT_INDEX_FILE=str(directory / 'index')))
    return directory / 'registry'


def stage_registry(previous, out, signed=None, root=None, repository=None):
    old_index = previous / 'index.json'
    present = {name for name in FILES if (previous / name).is_file()}
    if present and present != set(FILES):
        raise ValueError('Pages registry is missing signed metadata')
    if present:
        out.mkdir(parents=True, exist_ok=True)
        for name in FILES:
            shutil.copyfile(previous / name, out / name)
    if (previous / 'packages').is_dir():
        shutil.copytree(previous / 'packages', out / 'packages')
    if signed is None:
        return
    new_index = signed / 'index.json'
    index = json.loads(new_index.read_bytes())
    if present:
        old_sequence = json.loads(old_index.read_bytes())['sequence']
        same_release = (new_index.read_bytes() == old_index.read_bytes() and
                        (signed / 'index.json.sig').read_bytes()
                        == (previous / 'index.json.sig').read_bytes() and
                        root.read_bytes()
                        == (previous / 'root.json').read_bytes())
        if index['sequence'] < old_sequence or (
                index['sequence'] == old_sequence and not same_release):
            raise ValueError('Pages registry sequence must increase')
    out.mkdir(parents=True, exist_ok=True)
    packages = out / 'packages'
    packages.mkdir(exist_ok=True)
    base = package_base_url(repository) + '/'
    for package in index['packages'] + index.get('withdrawnPackages', []):
        if not package['url'].startswith(base):
            continue
        name = package['url'].removeprefix(base)
        if (not name.endswith('.zip') or name != Path(name).name or
                any(c in name for c in '/\\:%?#')):
            raise ValueError(f'invalid Pages package name: {name}')
        destination = packages / name
        archive = destination if destination.is_file() else signed / name
        if not archive.is_file() or archive.is_symlink():
            raise ValueError(f'missing Pages package: {name}')
        size = archive.stat().st_size
        with archive.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if size > MAX_GIT_FILE_BYTES or size != package[
                'size'] or digest != package['sha256']:
            raise ValueError(f'Pages package size or digest mismatch: {name}')
        if archive != destination:
            shutil.copyfile(archive, destination)
    for name in FILES[:2]:
        shutil.copyfile(signed / name, out / name)
    shutil.copyfile(root, out / 'root.json')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--signed', type=Path)
    parser.add_argument('--repository')
    args = parser.parse_args()
    if args.signed and not args.repository:
        parser.error('--signed requires --repository')
    with tempfile.TemporaryDirectory(prefix='foundry-pages-') as temp:
        previous = checkout_pages(Path(temp))
        out = Path('website/public/registry')
        root = args.signed / 'root.json' if args.signed else None
        stage_registry(previous, out, args.signed, root, args.repository)
        publish_catalogue(Path.cwd(), out)


if __name__ == '__main__':
    main()
