#!/usr/bin/env python3
"""BCR-style extension review reports from Git objects, without running PR code."""
import argparse
import difflib
import html
import json
from pathlib import Path
import re
import subprocess

from registry import name
from registry import unique
from registry import version_key

MAX_FILE_BYTES = 256 * 1024
MAX_READ_BYTES = 2 * 1024 * 1024
MAX_FILES = 512
MAX_DIFF_CHARS = 8000
MAX_REPORT_BYTES = 128 * 1024
ROOT = Path(__file__).resolve().parents[1]


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args],
                          check=True,
                          capture_output=True,
                          timeout=30).stdout


class Snapshot:

    def __init__(self, root, commit):
        self.root, self.commit = root, commit
        self.entries = {}
        self.read_bytes = 0
        data = git(root, 'ls-tree', '-r', '-z', '-l', commit, '--',
                   'extensions')
        for entry in data.split(b'\0'):
            if not entry:
                continue
            attributes, path = entry.split(b'\t', 1)
            mode, kind, oid, size = attributes.split()
            if mode not in (b'100644', b'100755') or kind != b'blob':
                raise ValueError(
                    'Extension snapshots cannot contain symlinks or submodules')
            self.entries[path.decode('utf-8')] = {
                'oid': oid.decode(),
                'size': int(size),
                'mode': mode.decode()
            }
            if len(self.entries) > 10000:
                raise ValueError('Extension snapshot exceeds 10000 files')

    def read(self, path):
        entry = self.entries.get(path)
        if entry is None:
            return b''
        size = entry['size']
        if size > MAX_FILE_BYTES or self.read_bytes + size > MAX_READ_BYTES:
            return None
        self.read_bytes += size
        return git(self.root, 'cat-file', 'blob', entry['oid'])

    def manifest(self, path):
        if path not in self.entries:
            return {}
        data = self.read(path)
        if data is None:
            raise ValueError('Manifest exceeds report input limits')
        result = json.loads(data, object_pairs_hook=unique)
        if not isinstance(result, dict):
            raise ValueError('Manifest must be an object')
        return result

    def versions(self, id):
        result = []
        prefix = f'extensions/{id}/'
        for path in self.entries:
            parts = path.split('/')
            if path.startswith(prefix) and len(
                    parts) == 4 and parts[-1] == 'manifest.json':
                version_key(parts[2])
                result.append(parts[2])
        return sorted(result, key=version_key)


def file_diff(old, new, old_path, new_path, label):
    before, after = old.entries.get(old_path), new.entries.get(new_path)
    if before == after:
        return None
    record = {'path': label, 'old': before, 'new': after}
    a, b = old.read(old_path), new.read(new_path)
    if a is None or b is None:
        record[
            'note'] = 'Content omitted: file size or total input limit exceeded.'
        return record
    try:
        if b'\0' in a + b:
            raise UnicodeError()
        aa, bb = a.decode('utf-8'), b.decode('utf-8')
    except UnicodeError:
        record[
            'note'] = 'Binary content omitted; Git object IDs and sizes are recorded.'
        return record
    # Normalize line endings for readable cross-platform review, preserve mode changes separately.
    lines = difflib.unified_diff(aa.splitlines(),
                                 bb.splitlines(),
                                 fromfile='a/' + label,
                                 tofile='b/' + label,
                                 lineterm='',
                                 n=3)
    patch = []
    length = 0
    for line in lines:
        if length + len(line) > MAX_DIFF_CHARS:
            patch.append(
                '... diff truncated; inspect the complete change in Git ...')
            break
        patch.append(line)
        length += len(line) + 1
    record['diff'] = '\n'.join(patch)
    if before and after and before['mode'] != after['mode']:
        record['note'] = f"File mode: {before['mode']} -> {after['mode']}"
    return record


def manifest_changes(old, new):
    result = {}
    for field in ('type', 'plugin', 'permissions', 'platforms', 'capabilities'):
        a, b = old.get(field), new.get(field)
        if a == b:
            continue
        row = {'old': a, 'new': b}
        if field in ('permissions', 'platforms', 'capabilities'):

            def keys(value):
                if isinstance(value, (dict, list)):
                    return {str(v) for v in value}
                return set()

            aa, bb = keys(a), keys(b)
            row.update(added=sorted(bb - aa), removed=sorted(aa - bb))
        result[field] = row
    return result


def generate_report(root, base):
    root = Path(root).resolve()
    if not re.fullmatch(r'[0-9a-f]{40,64}', base):
        raise ValueError('A full base commit SHA is required')
    # Require actual commits; unknown bases are errors, never empty reports.
    base = git(root, 'rev-parse', '--verify',
               base + '^{commit}').decode().strip()
    head = git(root, 'rev-parse', '--verify', 'HEAD^{commit}').decode().strip()
    old, new = Snapshot(root, base), Snapshot(root, head)
    changed = sorted(path for path in old.entries.keys() | new.entries.keys()
                     if old.entries.get(path) != new.entries.get(path))
    pairs, root_files = set(), []
    for path in changed:
        parts = path.split('/')
        if len(parts) >= 4:
            name(parts[1])
            version_key(parts[2])
            pairs.add((parts[1], parts[2]))
        else:
            root_files.append(path)
    if len(pairs) > 256:
        raise ValueError('Diff exceeds 256 changed extension versions')
    report = {
        'base': base,
        'head': head,
        'versions': [],
        'metadata': [],
        'truncated': False
    }
    remaining = MAX_FILES
    for id, version in sorted(pairs, key=lambda p: (p[0], version_key(p[1]))):
        old_versions, new_versions = old.versions(id), new.versions(id)
        existed, exists = version in old_versions, version in new_versions
        baseline = version if existed else next(
            (v for v in reversed(old_versions)
             if version_key(v) < version_key(version)), None)
        status = 'modified' if existed and exists else 'deleted' if existed else 'added'
        old_prefix = f'extensions/{id}/{baseline}/' if baseline else '__absent__/'
        new_prefix = f'extensions/{id}/{version}/'
        before = {
            p[len(old_prefix):] for p in old.entries if p.startswith(old_prefix)
        }
        after = {
            p[len(new_prefix):] for p in new.entries if p.startswith(new_prefix)
        }
        change = {
            'id':
                id,
            'version':
                version,
            'status':
                status,
            'baseline':
                baseline,
            'manifest':
                manifest_changes(old.manifest(old_prefix + 'manifest.json'),
                                 new.manifest(new_prefix + 'manifest.json')),
            'files': []
        }
        for path in sorted(before | after):
            if remaining == 0:
                report['truncated'] = True
                break
            record = file_diff(old, new, old_prefix + path, new_prefix + path,
                               path)
            if record:
                change['files'].append(record)
                remaining -= 1
        report['versions'].append(change)
    for path in root_files:
        if remaining == 0:
            report['truncated'] = True
            break
        record = file_diff(old, new, path, path, path)
        if record:
            report['metadata'].append(record)
            remaining -= 1
    return report


def inline(value):
    # HTML code tags escape Markdown, HTML, table separators and control characters.
    text = ''.join(c if c.isprintable() else ' ' for c in str(value))
    escaped = html.escape(text).replace('|', '&#124;')
    escaped = re.sub(r'([\\`*_\[\]{}()!~])', r'\\\1', escaped)
    return '<code>' + escaped + '</code>'


def code_block(content):
    longest = max((len(m.group()) for m in re.finditer(r'`+', content)),
                  default=0)
    fence = '`' * max(3, longest + 1)
    return f'{fence}diff\n{content}\n{fence}\n'


def render_markdown(report):
    lines = [
        '# Extension PR diff\n',
        f"Base: {inline(report['base'])}  \nHead: {inline(report['head'])}\n",
        'New versions are compared with the nearest earlier version in the base commit. '
        'Existing versions are compared with that same version at the base commit.\n'
    ]
    size = sum(len(s.encode()) + 1 for s in lines)
    truncated = report.get('truncated', False)

    def append(block):
        nonlocal size, truncated
        if size + len(block.encode()) + 1 > MAX_REPORT_BYTES - 1024:
            truncated = True
            return
        lines.append(block)
        size += len(block.encode()) + 1

    def files(records):
        for record in records:
            block = f"### {inline(record['path'])}\n\n"
            a, b = record['old'], record['new']
            block += f"Git blob: {inline(a['oid'] if a else '(none)')} → {inline(b['oid'] if b else '(none)')}\n\n"
            block += f"Size: {a['size'] if a else 0} → {b['size'] if b else 0} bytes\n\n"
            if record.get('note'):
                block += record['note'] + '\n\n'
            if record.get('diff'):
                block += code_block(record['diff'])
            append(block)

    if not report['versions'] and not report['metadata']:
        append(
            'No extension source or metadata changes. Shared runtime changes may still test all extensions.\n'
        )
    for change in report['versions']:
        append(
            f"## {inline(change['id']+'@'+change['version'])} — {change['status']}\n\n"
            f"Comparison version: {inline(change['baseline'] or '(new extension/version)')}\n\n"
        )
        if change['status'] in ('modified', 'deleted'):
            append(
                '**Historical version changed: the immutable-version check must reject this PR.**\n'
            )
        for field, values in change['manifest'].items():
            append(
                f"**{field}**: {inline(json.dumps(values, ensure_ascii=False, sort_keys=True))}\n\n"
            )
        files(change['files'])
    if report['metadata']:
        append('## Registry metadata and documentation\n\n')
        files(report['metadata'])
    if truncated:
        lines.append(
            '\n**Report truncated by size/file limits. Inspect the complete change in Git.**\n'
        )
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--base', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--json-output', type=Path)
    args = parser.parse_args()
    report = generate_report(args.root, args.base)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_markdown(report), encoding='utf-8')
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(report, indent=2) + '\n',
                                    encoding='utf-8')
    print(
        f"Generated extension diff: {len(report['versions'])} version changes")


if __name__ == '__main__':
    main()
