#!/usr/bin/env python3
"""Real signed distribution tests. Only temporary test keys are created."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SUFFIX = '.exe' if os.name == 'nt' else ''
BIN = ROOT / 'target' / os.environ.get('FOUNDRY_PROFILE', 'debug')


def command(*args, ok=True, env=None, timeout=60):
    result = subprocess.run([str(x) for x in args],
                            cwd=ROOT,
                            capture_output=True,
                            text=True,
                            encoding="utf-8",
                            env=env,
                            timeout=timeout)
    if ok and result.returncode:
        raise AssertionError(f'{args[0]} failed: {result.stderr}')
    if not ok and not result.returncode:
        raise AssertionError('command unexpectedly succeeded')
    return result


class Distribution(unittest.TestCase):

    def test_three_formal_extensions_and_trust_failures(self):
        with tempfile.TemporaryDirectory(prefix='foundry-test-') as directory:
            d = Path(directory)
            # Fixed historical sources are test fixtures, even when their registry versions are yanked.
            packages = []
            for id in ['text-utils', 'file-digest', 'native-math']:
                output = d / 'built' / id
                command('python3' if os.name != 'nt' else 'python',
                        ROOT / 'scripts/build_extensions.py',
                        '--out',
                        output,
                        '--extension',
                        id,
                        '--version',
                        '0.1.0',
                        timeout=1200)
                packages.extend(
                    json.loads((output / 'candidates.json').read_text()))
            release = BIN / ('foundry-release' + SUFFIX)
            client = BIN / ('foundry' + SUFFIX)
            key, root = d / 'test.key', d / 'root.json'
            command(release, 'keygen', '--private-output', key, '--root-output',
                    root, '--key-id', 'test-only')
            env = dict(os.environ, FOUNDRY_SIGNING_KEY=key.read_text())
            index = d / 'index.json'
            cli = [
                client, '--data-dir', d / 'state', '--trust-root', root,
                '--index', index
            ]

            def publish(seq=1, expiry=None):
                index.write_text(
                    json.dumps({
                        'schemaVersion': 1,
                        'sequence': seq,
                        'expiresAt': expiry or int(time.time()) + 3600,
                        'sourceCommit': 'a' * 40,
                        'packages': packages
                    }))
                command(release,
                        'sign',
                        '--input',
                        index,
                        '--output',
                        str(index) + '.sig',
                        '--key-id',
                        'test-only',
                        env=env)

            publish()
            downloaded = d / 'manual-download.zip'
            result = command(*cli, 'download', 'text-utils', '--output',
                             downloaded)
            self.assertEqual(json.loads(result.stdout)['installed'], False)
            self.assertTrue(downloaded.is_file())
            self.assertEqual(json.loads(command(*cli, 'list').stdout), [])
            alias = d / 'get-alias.zip'
            command(*cli, 'get', 'text-utils', '--output', alias)
            self.assertEqual(downloaded.read_bytes(), alias.read_bytes())
            command(*cli,
                    'download',
                    'text-utils',
                    '--output',
                    downloaded,
                    ok=False)
            command(*cli, 'install', 'text-utils')
            # File locking and atomic state updates must survive concurrent installations.
            parallel = [
                subprocess.Popen(
                    [str(x) for x in [*cli, 'install', 'text-utils']],
                    cwd=ROOT,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE) for _ in range(3)
            ]
            for process in parallel:
                _, error = process.communicate(timeout=30)
                self.assertEqual(process.returncode, 0,
                                 error.decode(errors='replace'))
            out = command(*cli, 'run', 'text-utils', 'normalize', '--input',
                          json.dumps({'text': '  a\r\nb  '}))
            self.assertEqual(json.loads(out.stdout), {'text': 'a\nb'})
            command(*cli, 'install', 'file-digest', ok=False)
            command(*cli, 'install', 'file-digest', '--grant', 'process.spawn')
            source = d / 'space 中文;$(echo nope).txt'
            source.write_bytes(b'abc')
            out = command(*cli, 'run', 'file-digest', 'digest', '--input',
                          json.dumps({'path': str(source)}))
            self.assertEqual(
                json.loads(out.stdout)['sha256'],
                hashlib.sha256(b'abc').hexdigest())
            command(*cli, 'install', 'native-math', '--grant', 'native.call')
            for cap, inp, expected in [('add', {
                    'a': 2,
                    'b': 3
            }, 5), ('hypot', {
                    'a': 3,
                    'b': 4
            }, 5.0)]:
                out = command(*cli, 'run', 'native-math', cap, '--input',
                              json.dumps(inp))
                self.assertEqual(json.loads(out.stdout)['result'], expected)
            command(*cli,
                    'run',
                    'native-math',
                    'add',
                    '--input',
                    '{"a":2147483647,"b":1}',
                    ok=False)
            # Repeated native calls prove workers do not poison the main client.
            command(*cli, 'run', 'native-math', 'add', '--input',
                    '{"a":1,"b":1}')
            # A valid newer index is accepted, rollback and expired index are not.
            publish(2)
            command(*cli, 'search', 'text')
            publish(1)
            command(*cli, 'search', 'text', ok=False)
            publish(3, int(time.time()) - 1)
            command(*cli, 'search', 'text', ok=False)
            publish(3)
            signature = Path(str(index) + '.sig')
            original = signature.read_bytes()
            signature.write_text('{"keyId":"test-only","signature":"' +
                                 '00' * 64 + '"}')
            command(*cli, 'search', 'text', ok=False)
            signature.write_bytes(original)
            # Upgrade to a new, genuinely different version.
            stage = d / 'built/text-utils/versions/text-utils/0.1.0'
            manifest = json.loads((stage / 'manifest.json').read_text())
            manifest['version'] = '0.2.0'
            (stage / 'manifest.json').write_text(json.dumps(manifest))
            out = command(release, 'pack', '--source', stage, '--output',
                          d / 'text-v2.zip', '--platform', 'any')
            candidate = json.loads(out.stdout)
            candidate['url'] = str(d / 'text-v2.zip')
            candidate.pop('file')
            packages.append(candidate)
            publish(4)
            command(*cli, 'upgrade', 'text-utils')
            self.assertIn('0.2.0', command(*cli, 'list').stdout)
            # A failed install must leave the current version usable.
            (d / 'text-v2.zip').write_bytes(b'tampered')
            command(*cli, 'install', 'text-utils', ok=False)
            command(*cli, 'run', 'text-utils', 'normalize', '--input',
                    '{"text":"still works"}')
            # A signed upgrade that adds execution permission must be authorized again.
            manifest['version'] = '0.3.0'
            manifest['permissions'] = ['process.spawn']
            (stage / 'manifest.json').write_text(json.dumps(manifest))
            out = command(release, 'pack', '--source', stage, '--output',
                          d / 'text-v3.zip', '--platform', 'any')
            candidate = json.loads(out.stdout)
            candidate['url'] = str(d / 'text-v3.zip')
            candidate.pop('file')
            packages.append(candidate)
            publish(5)
            command(*cli, 'upgrade', 'text-utils', ok=False)
            self.assertIn('0.2.0', command(*cli, 'list').stdout)
            command(*cli, 'upgrade', 'text-utils', '--grant', 'process.spawn')
            self.assertIn('0.3.0', command(*cli, 'list').stdout)
            installed = json.loads(
                (d / 'state/state.json').read_text())['installed']['text-utils']
            package_dir = d / 'state/packages' / installed['archive_sha256']
            (package_dir / 'main.js').write_text(
                'export async function normalize(){return {text:"tampered"}}')
            command(*cli,
                    'run',
                    'text-utils',
                    'normalize',
                    '--input',
                    '{"text":"x"}',
                    ok=False)
            for name in ['text-utils', 'file-digest', 'native-math']:
                command(*cli, 'uninstall', name)
            self.assertEqual(json.loads(command(*cli, 'list').stdout), [])


if __name__ == '__main__':
    unittest.main()
