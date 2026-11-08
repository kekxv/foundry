#!/usr/bin/env python3
"""Format or check all maintained code with pinned, documented style tools."""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(command):
    subprocess.run(command, cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',
                        action='store_true',
                        help='Check without changing files')
    args = parser.parse_args()
    imports = [
        sys.executable, '-m', 'isort', '--settings-path',
        str(ROOT / '.isort.cfg')
    ]
    if args.check:
        imports += ['--check-only', '--diff']
    run(imports + ['scripts'])
    python = [
        sys.executable, '-m', 'yapf', '--style',
        str(ROOT / '.style.yapf'), '--recursive'
    ]
    if args.check:
        result = subprocess.run(python + ['--diff', 'scripts'],
                                cwd=ROOT,
                                capture_output=True,
                                text=True,
                                encoding='utf-8',
                                check=False)
        if result.returncode or result.stdout:
            sys.stderr.write(result.stderr)
            sys.stdout.write(result.stdout)
            raise SystemExit(
                'Python formatting differs; run python scripts/format_code.py')
    else:
        run(python + ['--in-place', 'scripts'])
    rust = ['cargo', 'fmt', '--all']
    if args.check:
        rust += ['--', '--check']
    run(rust)
    for manifest in sorted((ROOT / 'extensions').glob('*/*/native/Cargo.toml')):
        native = ['cargo', 'fmt', '--manifest-path', str(manifest)]
        if args.check:
            native += ['--', '--check']
        run(native)
    # Invoke the locked local binary; never let npx install an unpinned formatter.
    npm = 'npm.cmd' if sys.platform == 'win32' else 'npm'
    run([
        npm, '--prefix', 'website', 'run',
        'format:check' if args.check else 'format'
    ])
    if args.check:
        print('All source formatting checks passed.')
    else:
        print('All source files formatted.')


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.returncode) from None
