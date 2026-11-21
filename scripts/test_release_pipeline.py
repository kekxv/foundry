"""Offline test of candidate assembly and approval-binding checks (no secrets)."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from registry import Registry

ROOT = Path(__file__).resolve().parents[1]
PLATFORMS = ['linux-x64', 'linux-arm64', 'macos-arm64', 'windows-x64']


class ReleaseChecks(unittest.TestCase):

    def test_candidate_and_rejections(self):
        with tempfile.TemporaryDirectory(
                prefix='foundry-release-test-') as directory:
            d = Path(directory)
            env = dict(os.environ,
                       SOURCE_COMMIT='a' * 40,
                       VERSION='0.1.0',
                       SEQUENCE='2',
                       GITHUB_REPOSITORY='owner/foundry',
                       GITHUB_OUTPUT=str(d / 'outputs'),
                       GITHUB_STEP_SUMMARY=str(d / 'summary'))
            for platform in PLATFORMS:
                part = d / 'candidate' / platform
                part.mkdir(parents=True)
                assets = {}
                packages = []
                registry = Registry(ROOT)
                pairs = [(id, version)
                         for id in registry.names()
                         for version in registry.versions(id)]
                for name, extension_version in pairs:
                    declared = registry.manifest(name,
                                                 extension_version)['platforms']
                    if 'any' not in declared and platform not in declared:
                        continue
                    plat = 'any' if 'any' in declared else platform
                    external = registry.external_packages(
                        name, extension_version)
                    if external:
                        packages.append(
                            dict(id=name,
                                 version=extension_version,
                                 platform=plat,
                                 size=8,
                                 **external[plat]))
                        continue
                    filename = f'{name}-{extension_version}-{plat}.zip'
                    data = filename.encode()
                    (part / filename).write_bytes(data)
                    record = {
                        'size': len(data),
                        'sha256': hashlib.sha256(data).hexdigest()
                    }
                    assets[filename] = record
                    packages.append(
                        dict(
                            id=name,
                            version=extension_version,
                            platform=plat,
                            url=
                            f'https://owner.github.io/foundry/registry/packages/{filename}',
                            **record))
                name = f'foundry-0.1.0-{platform}.zip'
                data = name.encode()
                (part / name).write_bytes(data)
                assets[name] = {
                    'size': len(data),
                    'sha256': hashlib.sha256(data).hexdigest()
                }
                (part / 'assets.json').write_text(json.dumps(assets))
                (part / 'candidates.json').write_text(json.dumps(packages))

            def run(script, success=True):
                p = subprocess.run(
                    [sys.executable,
                     str(ROOT / 'scripts' / script)],
                    cwd=d,
                    env=env,
                    capture_output=True,
                    text=True)
                self.assertEqual(p.returncode == 0, success, p.stderr)

            run('assemble_release.py')
            env['EXPECTED_MANIFEST_SHA256'] = (
                d / 'outputs').read_text().strip().split('=')[1]
            run('verify_candidate.py')
            env['SOURCE_COMMIT'] = 'b' * 40
            run('verify_candidate.py', False)
            env['SOURCE_COMMIT'] = 'a' * 40
            path = d / 'dist/approved/index.json'
            original = path.read_bytes()
            path.write_bytes(original + b' ')
            run('verify_candidate.py', False)
            path.write_bytes(original)
            extra = d / 'dist/approved/injected.py'
            extra.write_text('print("must never run")')
            run('verify_candidate.py', False)
            extra.unlink()
            manifest = d / 'dist/approved/release-manifest.json'
            m = json.loads(manifest.read_text())
            index = json.loads(path.read_text())
            index['packages'][0][
                'url'] = 'https://github.com/attacker/else/releases/download/v0.1.0/x.zip'
            path.write_text(json.dumps(index))
            m['assets']['index.json'] = {
                'size': path.stat().st_size,
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest()
            }
            manifest.write_text(json.dumps(m))
            env['EXPECTED_MANIFEST_SHA256'] = hashlib.sha256(
                manifest.read_bytes()).hexdigest()
            run('verify_candidate.py', False)

    def test_signed_history_survives_yank_and_restore(self):
        for external in (False, True):
            with self.subTest(external=external):
                self.check_history(external)

    def check_history(self, external):
        import shutil
        with tempfile.TemporaryDirectory(prefix='foundry-history-') as temp:
            d = Path(temp)
            scripts = d / 'scripts'
            scripts.mkdir()
            for file in [
                    'assemble_release.py', 'verify_candidate.py', 'registry.py',
                    'pages_registry.py', 'publish_catalogue.py'
            ]:
                shutil.copy2(ROOT / 'scripts' / file, scripts / file)
            extension = d / 'extensions/demo/1.0.0'
            extension.mkdir(parents=True)
            (extension / 'manifest.json').write_text(
                json.dumps({
                    'id': 'demo',
                    'version': '1.0.0',
                    'type': 'javascript',
                    'platforms': ['any']
                }))
            part = d / 'candidate/linux'
            part.mkdir(parents=True)
            original = {
                'id':
                    'demo',
                'version':
                    '1.0.0',
                'platform':
                    'any',
                'url':
                    'https://owner.github.io/foundry/registry/packages/demo-1.0.0-any.zip',
                'sha256':
                    hashlib.sha256(b'original').hexdigest(),
                'size':
                    8
            }
            if external:
                original[
                    'url'] = 'https://downloads.example.org/demo-1.0.0-any.zip'
                (extension / 'packages.yaml').write_text(
                    f'any:\n  url: {original["url"]}\n'
                    f'  sha256: "{original["sha256"]}"\n  size: 10\n',
                    encoding='utf-8')
            history = {'packages': []}
            history_path = d / 'history.json'

            def publish(sequence, yanked, records, assets, valid=True):
                nonlocal history
                shutil.rmtree(d / 'dist', ignore_errors=True)
                (extension.parent / 'metadata.json').write_text(
                    json.dumps({
                        'id': 'demo',
                        'versions': ['1.0.0'],
                        'yanked_versions': {
                            '1.0.0': 'bad'
                        } if yanked else {}
                    }))
                history_path.write_text(json.dumps(history))
                env = dict(os.environ,
                           SOURCE_COMMIT='a' * 40,
                           VERSION=f'0.{sequence}.0',
                           SEQUENCE=str(sequence),
                           GITHUB_REPOSITORY='owner/foundry',
                           GITHUB_OUTPUT=str(d / 'outputs'),
                           GITHUB_STEP_SUMMARY=str(d / 'summary'),
                           PREVIOUS_INDEX=str(history_path),
                           EXPECTED_PREVIOUS_SHA256=hashlib.sha256(
                               history_path.read_bytes()).hexdigest())
                (part / 'candidates.json').write_text(json.dumps(records))
                (part / 'assets.json').write_text(json.dumps(assets))
                result = subprocess.run(
                    [sys.executable,
                     str(scripts / 'assemble_release.py')],
                    cwd=d,
                    env=env,
                    capture_output=True,
                    text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                env['EXPECTED_MANIFEST_SHA256'] = hashlib.sha256(
                    (d / 'dist/approved/release-manifest.json'
                    ).read_bytes()).hexdigest()
                result = subprocess.run(
                    [sys.executable,
                     str(scripts / 'verify_candidate.py')],
                    cwd=d,
                    env=env,
                    capture_output=True,
                    text=True)
                if not valid:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(
                        'External package does not match pinned metadata',
                        result.stderr)
                    return
                self.assertEqual(result.returncode, 0, result.stderr)
                history = json.loads(
                    (d / 'dist/approved/index.json').read_text())

            assets = {}
            if not external:
                (part / 'demo-1.0.0-any.zip').write_bytes(b'original')
                assets['demo-1.0.0-any.zip'] = {
                    'size': 8,
                    'sha256': original['sha256']
                }
            publish(1, False, [original], assets)
            self.assertEqual(history['packages'], [original])
            if external:
                self.assertFalse(
                    (d / 'dist/approved/demo-1.0.0-any.zip').exists())
            publish(2, True, [], {})
            self.assertEqual(history['packages'], [])
            self.assertEqual(history['withdrawnPackages'], [original])
            if external:
                pins = extension / 'packages.yaml'
                original_pins = pins.read_text()
                pins.write_text(
                    original_pins.replace('downloads.example.org',
                                          'other.example.org'))
                publish(3, False, [original], {}, valid=False)
                pins.write_text(original_pins)
            publish(3, False, [original], {})
            self.assertEqual(history['packages'], [original])
            self.assertEqual(history['withdrawnPackages'], [])


if __name__ == '__main__':
    unittest.main()
